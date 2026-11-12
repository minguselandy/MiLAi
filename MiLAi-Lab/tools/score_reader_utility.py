"""Score frozen real branch packets offline; retain sample failures and all alias scores."""
from __future__ import annotations

import argparse
import fcntl
import json
import time
from collections import Counter
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
    parser.add_argument("--precision", choices=("bf16", "float32"), default="bf16")
    parser.add_argument("--max-length", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--padded-token-target", type=int, default=16384)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--compute-phase", required=True)
    args = parser.parse_args()
    if min(args.max_length, args.batch_size, args.padded_token_target) < 1:
        parser.error("Capacity and batch limits must be positive")
    import torch

    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    run: dict[str, Any] = {"status": "RUNNING", "data": str(args.data.resolve()),
        "teacher": str(args.model.resolve()), "template_version": TEMPLATE_VERSION,
        "backend": "transformers-selective-logits-sdpa", "precision": args.precision,
        "device": args.device, "max_length": args.max_length,
        "batch_size": args.batch_size, "padded_token_target": args.padded_token_target,
        "no_sha_validation": True, "automatic_retry": False,
        "aggregation": "arithmetic_mean_of_per_reference_mean_logprob",
        "semantic_meaning": "weak_answer_predictability_not_sufficiency"}
    counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    stage_seconds: dict[str, float] = {}
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
                      "packet_ref", "reference_set_id", "continuation")}
            result.update(score_known=False, references=[], teacher=run["teacher"],
                          template_version=TEMPLATE_VERSION)
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
        for item in work:
            if (not batches or len(batches[-1]) >= args.batch_size
                    or (len(batches[-1]) + 1) * len(item[2].input_ids) > args.padded_token_target):
                batches.append([])
            batches[-1].append(item)
        stage_start = time.perf_counter()
        for number, batch in enumerate(batches):
            # A CUDA/model error aborts the job. Capacity/boundary errors above stay sample-local.
            scores = teacher.score([item[2] for item in batch])
            for (i, j, sequence), token_scores in zip(batch, scores, strict=True):
                results[i]["references"][j].update(
                    score_known=True, mean_logprob=sum(token_scores) / len(token_scores),
                    answer_token_count=len(token_scores), token_logprobs=token_scores,
                    input_token_count=len(sequence.input_ids))
                counts["input_tokens"] += len(sequence.input_ids)
                counts["answer_tokens"] += len(token_scores)
                counts["scoring_sequences"] += 1
            counts["padded_input_tokens"] += (
                max(len(item[2].input_ids) for item in batch) * len(batch))
            counts["batch_forwards"] += 1
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
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1, **counts}
        run["compute"] = measures
        run["stage_wall_seconds"] = stage_seconds
        write_json(args.output / "run.json", run)
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute(args.compute_phase, measures)


if __name__ == "__main__":
    main()
