"""Audit complete Laya sequences and run native full soft-CE on grouped events."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import resource
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def audit_lengths(rows: list[dict[str, Any]], tokenizer: Any,
                  max_len: int, head_max_len: int) -> list[dict[str, Any]]:
    from laya.common import build_sequence
    from laya.train import to_internal

    lengths = []
    for row in rows:
        for qid, question in row["questions"].items():
            ids, _, stats = build_sequence(tokenizer, row["state"], to_internal(qid, question),
                max_len=max_len, head_max_len=head_max_len, return_truncation_stats=True)
            lengths.append({"event_id": row["metadata"]["event_id"], "question": qid,
                "labelled": qid in row["expected"], "sequence_tokens": len(ids),
                "full_sequence_tokens": len(ids) + stats["state_tokens_dropped"], **stats})
    return lengths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-len", type=int, default=2048)
    parser.add_argument("--head-max-len", type=int, default=256)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    import torch
    from laya.train import TrainConfig, finetune
    from transformers import AutoTokenizer

    torch.set_num_threads(args.threads)
    tokenizer = AutoTokenizer.from_pretrained(args.base / "tokenizer", local_files_only=True)
    lengths = {}
    for split in ("train", "dev", "calibration", "test"):
        rows = [json.loads(s) for s in (args.data / f"{split}.jsonl").read_text().splitlines()]
        lengths[split] = audit_lengths(rows, tokenizer, args.max_len, args.head_max_len)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "lengths.json", lengths)
    oversized = [r for records in lengths.values() for r in records if r["truncated"]]
    write_json(args.output / "audit.json", {
        "complete_inputs": not oversized, "oversized_questions": len(oversized),
        "max_sequence_tokens": max(r["full_sequence_tokens"]
                                   for records in lengths.values() for r in records),
        "max_len": args.max_len, "head_max_len": args.head_max_len,
    })
    if args.audit_only:
        return
    if oversized:
        raise ValueError("Complete event inputs exceed capacity; inspect lengths.json")
    cfg = TrainConfig(loss="soft-ce", freeze_encoder=False, epochs=4, micro_batch=2,
        grad_accum=16, encoder_lr=2.5e-5, head_lr=1e-4, max_len=args.max_len,
        head_max_len=args.head_max_len, calib_max=0, calib_frac=0.0, seed=0,
        eval_data=str(args.data / "dev.jsonl"), log_every=1)
    write_json(args.output / "run.json", {"status": "RUNNING", "pid": os.getpid(),
        "base_checkpoint": str(args.base.resolve()), "device": args.device,
        "config": asdict(cfg), "calibrated": False,
        "scope": "full encoder and head; small exposed family-separated diagnostic"})
    started, cpu = time.perf_counter(), time.process_time()
    try:
        report = finetune(str(args.data / "train.jsonl"), str(args.base),
                          str(args.output / "checkpoint"), cfg, device=args.device)
        write_json(args.output / "result.json", {"status": "COMPLETED", **report})
    finally:
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu,
                    "runs": 1}
        # Local training never resets or creates a separate budget.
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            state = read_json(args.budget)
            budget = RunBudget(RunLimits(**state["limits"]), args.budget)
            budget.record_compute("laya_training", measures)
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "device": args.device, "threads": args.threads, "ledger": str(args.budget)})


if __name__ == "__main__":
    main()
