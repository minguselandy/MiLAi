"""Score frozen real branch packets offline; retain sample failures and all alias scores."""
from __future__ import annotations

import argparse
import fcntl
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.reader_teacher_scoring import (
    TEMPLATE_VERSION,
    TransformersReaderTeacher,
    encode_answer,
    teacher_messages,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="Prepared offline packet/reference JSONL")
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--precision", choices=("bf16", "float32"), default="float32",
                        help="FP32 avoids observed BF16 batch-dependent likelihood drift")
    parser.add_argument("--max-length", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--padded-token-target", type=int, default=16384)
    parser.add_argument("--share-alias-prefix", action="store_true",
                        help="Explicit FP32 DynamicCache backend for same-packet answer aliases")
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--compute-phase", required=True)
    args = parser.parse_args()
    if min(args.max_length, args.batch_size, args.padded_token_target) < 1:
        parser.error("Capacity and batch limits must be positive")
    if args.share_alias_prefix and args.precision != "float32":
        parser.error("The alias-prefix numerical comparison is declared for FP32 only")
    import torch

    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    run: dict[str, Any] = {"status": "RUNNING", "data": str(args.data.resolve()),
        "teacher": str(args.model.resolve()), "template_version": TEMPLATE_VERSION,
        "backend": ("transformers-selective-logits-sdpa-alias-prefix" if args.share_alias_prefix
                    else "transformers-selective-logits-sdpa"), "precision": args.precision,
        "device": args.device, "max_length": args.max_length,
        "ledger_recorded": False,
        "batch_size": args.batch_size, "padded_token_target": args.padded_token_target,
        "no_sha_validation": True, "automatic_retry": False,
        "aggregation": "arithmetic_mean_of_per_reference_mean_logprob",
        "share_alias_prefix": args.share_alias_prefix,
        "token_scope": "input_tokens counts actual model token processing; "
                       "reference_input_tokens counts all complete reference sequences",
        "semantic_meaning": "weak_answer_predictability_not_sufficiency"}
    configuration = {"backend": run["backend"], "precision": args.precision,
                     "tf32_matmul": False, "tf32_cudnn": False,
                     "template_version": TEMPLATE_VERSION,
                     "aggregation": run["aggregation"], "numerical_protocol": (
                         "likelihood-v3-alias-prefix" if args.share_alias_prefix
                         else "likelihood-v2")}
    run["scoring_configuration"] = configuration
    run["torch_version"] = torch.__version__
    counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    stage_seconds: dict[str, float] = {}
    teacher = None
    write_json(args.output / "run.json", run)
    try:
        if args.device.startswith("cuda"):
            torch.cuda.set_device(args.device)
            torch.cuda.reset_peak_memory_stats(args.device)
        stage_start = time.perf_counter()
        teacher = TransformersReaderTeacher(str(args.model), args.device, args.precision)
        stage_seconds["model_load"] = time.perf_counter() - stage_start
        if args.max_length > teacher.capacity:
            raise ValueError("Requested capacity exceeds this model's configured context")
        records = read_jsonl(args.data)
        stage_start = time.perf_counter()
        work = []
        for i, row in enumerate(records):
            result = {k: row[k] for k in ("event_id", "family", "research_split", "action",
                      "packet_ref", "reference_set_id", "continuation", "execution_status")}
            result.update(score_known=False, references=[], teacher=run["teacher"],
                          template_version=TEMPLATE_VERSION, scoring_configuration=configuration)
            results.append(result)
            if row["execution_status"] != "completed":
                result["failure"] = "branch_not_completed"
                continue
            messages = teacher_messages(row["wire"])
            if not row["references"]:
                result["failure"] = "no_eligible_reference"
                continue
            for j, reference in enumerate(row["references"]):
                item: dict[str, Any] = {"reference_index": j, "score_known": False}
                result["references"].append(item)
                try:
                    sequence = encode_answer(teacher.tokenizer, messages, reference,
                                             args.max_length)
                except ValueError as error:
                    item["failure"] = str(error)
                    continue
                work.append((i, j, sequence))
        work.sort(key=lambda item: len(item[2].input_ids))
        stage_seconds["input_preparation"] = time.perf_counter() - stage_start
        batches: list[list[Any]] = []
        cached_groups = []
        if args.share_alias_prefix:
            by_packet = defaultdict(list)
            for item in work:
                by_packet[item[0]].append(item)
            cached_groups = [group for group in by_packet.values() if len(group) > 1]
            work = [group[0] for group in by_packet.values() if len(group) == 1]
        for item in work:
            if (not batches or len(batches[-1]) >= args.batch_size
                    or (len(batches[-1]) + 1) * len(item[2].input_ids) > args.padded_token_target):
                batches.append([])
            batches[-1].append(item)
        stage_start = time.perf_counter()
        for number, (batch, shared) in enumerate([
            *((b, False) for b in batches), *((b, True) for b in cached_groups)
        ]):
            # A CUDA/model error aborts the job. Capacity/boundary errors above stay sample-local.
            if shared:
                scores, actual = teacher.score_aliases([item[2] for item in batch],
                    batch_size=args.batch_size, padded_token_target=args.padded_token_target)
                counts["input_tokens"] += actual["processed_input_tokens"]
                counts["padded_input_tokens"] += actual["processed_padded_input_tokens"]
                counts["batch_forwards"] += (actual["cache_prefix_forwards"]
                                             + actual["cache_suffix_forwards"])
                counts["shared_alias_packet_groups"] += 1
            else:
                scores = teacher.score([item[2] for item in batch])
                counts["input_tokens"] += sum(len(item[2].input_ids) for item in batch)
                counts["padded_input_tokens"] += (
                    max(len(item[2].input_ids) for item in batch) * len(batch))
                counts["batch_forwards"] += 1
            for (i, j, sequence), token_scores in zip(batch, scores, strict=True):
                results[i]["references"][j].update(
                    score_known=True, mean_logprob=sum(token_scores) / len(token_scores),
                    answer_token_count=len(token_scores), token_logprobs=token_scores,
                    input_token_count=len(sequence.input_ids))
                counts["reference_input_tokens"] += len(sequence.input_ids)
                counts["answer_tokens"] += len(token_scores)
                counts["scoring_sequences"] += 1
            # One append per batch preserves completed target scores if a later batch fails.
            with (args.output / "reference-scores.jsonl").open("a") as stream:
                for i, j, _ in batch:
                    stream.write(json.dumps({"record_index": i,
                        "event_id": results[i]["event_id"], "action": results[i]["action"],
                        **results[i]["references"][j]}) + "\n")
            if (number + 1) % 25 == 0:
                print(json.dumps({"batch": number + 1, **counts}), flush=True)
        stage_seconds["scoring"] = time.perf_counter() - stage_start
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        with (args.output / "scores.jsonl").open("x") as stream:
            for result in results:
                aliases = result["references"]
                if aliases and all(a["score_known"] for a in aliases):
                    result.update(score_known=True,
                        mean_logprob=sum(a["mean_logprob"] for a in aliases) / len(aliases),
                        answer_token_count=sum(a["answer_token_count"] for a in aliases))
                counts["scored_packets" if result["score_known"] else "unscored_packets"] += 1
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
        if run["status"] == "COMPLETED" and counts["unscored_packets"]:
            run["status"] = "COMPLETED_WITH_FAILURES"
        if args.device.startswith("cuda") and torch.cuda.is_initialized():
            torch.cuda.synchronize(args.device)
            run["peak_cuda_allocated_bytes"] = torch.cuda.max_memory_allocated(args.device)
            run["peak_cuda_reserved_bytes"] = torch.cuda.max_memory_reserved(args.device)
        # A shared HTTP ledger lease can outlive scoring. Release model allocations before
        # waiting for that existing lease so the next finite GPU job can use the device.
        teacher = None
        if args.device.startswith("cuda") and torch.cuda.is_initialized():
            torch.cuda.empty_cache()
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1, **counts}
        run["compute"] = measures
        run["stage_wall_seconds"] = stage_seconds
        run["compute_wall_scope"] = (
            "Model load, input preparation, scoring and cleanup; before ledger wait")
        write_json(args.output / "run.json", run)
        ledger_wait_started = time.perf_counter()
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            run["ledger_wait_wall_seconds"] = time.perf_counter() - ledger_wait_started
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute(args.compute_phase, measures)
        run["ledger_recorded"] = True
        run["process_wall_seconds_including_ledger_wait"] = time.perf_counter() - started
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
