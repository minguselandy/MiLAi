"""Measure native Laya decisions on frozen read prefixes, without generation.

All model-visible requests and first outputs are saved. Reference labels are
used only after the forward pass. The original shared ledger receives CPU cost;
no HTTP request or zero-output-token saving is invented for this local workload.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import resource
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


class NativeDecision:
    def __init__(self, checkpoint: Path, max_len: int, head_max_len: int) -> None:
        import torch
        from laya.train import load_checkpoint

        self.model, self.tokenizer, self.config = load_checkpoint(str(checkpoint))
        self.device = torch.device("cpu")
        self.model.to(self.device).eval()
        self.max_len, self.head_max_len = max_len, head_max_len
        self.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                             state_tokenizations=0, state_tokens=0)

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        import torch
        from laya.common import (
            build_head,
            build_sequence,
            collate_items,
            encode_text,
            serialize_state,
        )
        from laya.train import _forward, encode_item, make_item, to_internal

        started, cpu = time.perf_counter(), time.process_time()
        question = to_internal("next", payload["questions"]["next"])
        state_ids = encode_text(self.tokenizer, serialize_state(payload["state"]).replace(
            self.tokenizer.mask_token, " "), add_special_tokens=False)["input_ids"]
        self.counters["state_tokenizations"] += 1
        self.counters["state_tokens"] += len(state_ids)
        _, _, stats = build_sequence(self.tokenizer, payload["state"], question,
            max_len=self.max_len, head_max_len=self.head_max_len, state_ids=state_ids,
            return_truncation_stats=True)
        head = build_head(self.tokenizer, question, self.head_max_len)[0]
        full_head = build_head(self.tokenizer, question, 100000)[0]
        if stats["truncated"] or head != full_head:
            raise ValueError("Finite decision input exceeds declared complete-input capacity")
        keys = list(question["crit"])
        # Dummy targets satisfy the batch format; _forward receives no target tensor.
        item, reason = make_item(self.tokenizer, question, [1 / len(keys)] * len(keys),
                                 state_ids, self.head_max_len, self.max_len)
        if reason:
            raise ValueError(f"Unencodable decision: {reason}")
        batch = collate_items([[encode_item(self.tokenizer, item, self.max_len,
                                            self.head_max_len)]], self.tokenizer.pad_token_id)
        preparation_seconds = time.perf_counter() - started
        inference_started = time.perf_counter()
        with torch.no_grad():
            logits = _forward(self.model, batch, self.device, False, False)[0, :len(keys)]
            probabilities = torch.softmax(logits, dim=-1).tolist()
        inference_seconds = time.perf_counter() - inference_started
        self.counters["forwards"] += 1
        self.counters["sequence_rows"] += 1
        self.counters["input_tokens"] += int(batch["attention_mask"].sum())
        return {"choice": keys[max(range(len(keys)), key=lambda i: probabilities[i])],
                "probabilities": dict(zip(keys, probabilities, strict=True)),
                "input_tokens": int(batch["attention_mask"].sum()), "truncated": False,
                "preparation_seconds": preparation_seconds,
                "inference_seconds": inference_seconds,
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "calibrated": False}


def score_predictions(rows: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict:
    counts: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = {}
    family: dict[str, list[int]] = {}
    for row, predicted in zip(rows, predictions, strict=True):
        target = row.get("gold", {}).get("next", {}).get("probabilities", {})
        if not target:
            counts["masked_reference"] += 1
            continue
        choice = predicted["choice"]
        accepted = int(target.get(choice, 0) > 0)
        counts["labelled"] += 1
        counts["accepted"] += accepted
        status = row["metadata"]["label_status"]
        stats = strata.setdefault(status, Counter())
        stats["labelled"] += 1
        stats["accepted"] += accepted
        group = row["metadata"]["family"]
        family.setdefault(group, []).append(accepted)
        if choice == "stop_sufficient" and target.get(choice, 0) == 0:
            counts["unsupported_sufficient_stop"] += 1
        if choice == "stop_exhausted" and target.get(choice, 0) == 0:
            counts["unsupported_exhaustion_stop"] += 1
        if choice.startswith("open_") and any(k.startswith("stop_") for k in target):
            counts["unnecessary_continue"] += 1
        first = next((k for k in row["questions"]["next"]["criteria"]
                      if k.startswith("open_")), "stop_exhausted")
        counts["first_remaining_candidate_accepted"] += int(target.get(first, 0) > 0)
    return {"counts": dict(counts), "strata": {k: dict(v) for k, v in strata.items()},
            "family_macro_acceptance": sum(sum(v) / len(v) for v in family.values()) / len(family),
            "families": len(family),
            "scope": "Reference-proof prefix decisions; not Reader QA or net pipeline benefit"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--head-max-len", type=int, default=384)
    args = parser.parse_args()
    import torch

    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in args.data.read_text().splitlines()]
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "checkpoint": str(args.checkpoint.resolve()), "device": "cpu",
           "threads": args.threads, "max_len": args.max_len,
           "head_max_len": args.head_max_len, "completed_states": 0, "planned_states": len(rows),
           "calibrated": False, "http_requests": 0}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    predictions = []
    model = None
    try:
        model = NativeDecision(args.checkpoint, args.max_len, args.head_max_len)
        for index, row in enumerate(rows):
            payload = {k: row[k] for k in ("state", "questions")}
            write_json(args.output / "calls" / str(index) / "input.json", payload)
            prediction = model.predict(payload)
            write_json(args.output / "calls" / str(index) / "output.json", prediction)
            predictions.append(prediction)
            run["completed_states"] += 1
            write_json(args.output / "run.json", run)
            print(json.dumps({"completed": len(predictions), "planned": len(rows),
                              "input_tokens": prediction["input_tokens"]}), flush=True)
        write_json(args.output / "results.json", score_predictions(rows, predictions))
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **(model.counters if model is not None else {})}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "ledger": str(args.budget)})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute("laya_reader_prefix", measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
