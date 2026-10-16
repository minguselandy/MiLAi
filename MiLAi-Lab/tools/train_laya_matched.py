"""Full native Laya training: matched CE versus CE plus joint-marginal consistency.

Both conditions consume the same frozen event groups, token sequences, optimizer
schedule and original checkpoint. Calibration/test families are not consumed.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import resource
import time
from collections import Counter
from pathlib import Path
from typing import Any

from laya_joint_training import marginal_consistency
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(rows: list[dict[str, Any]], tok: Any, max_len: int,
          head_max_len: int) -> list[dict[str, Any]]:
    from laya.common import build_head, build_sequence
    from laya.train import to_internal

    result = []
    for row in rows:
        for qid, question in row["questions"].items():
            q = to_internal(qid, question)
            ids, _, stats = build_sequence(tok, row["state"], q, max_len=max_len,
                head_max_len=head_max_len, return_truncation_stats=True)
            head = build_head(tok, q, head_max_len)[0]
            full_head = build_head(tok, q, 100000)[0]
            result.append({"event_id": row["metadata"]["event_id"], "question": qid,
                "sequence_tokens": len(ids), "state_tokens_dropped": stats["state_tokens_dropped"],
                "head_tokens_dropped": len(full_head) - len(head)})
    return result


def evaluate(model: Any, tok: Any, rows: list[dict[str, Any]], device: Any,
             max_len: int, head_max_len: int) -> dict[str, Any]:
    import torch
    from laya.common import collate_items
    from laya.train import _forward, encode_item, items_from_rows

    model.eval()
    confusion: Counter[tuple[str, str]] = Counter()
    predictions = []
    with torch.no_grad():
        for row in rows:
            items, skipped = items_from_rows(tok, [row], max_len, head_max_len)
            if skipped:
                raise ValueError(f"Evaluation items skipped: {skipped}")
            batch = collate_items([[encode_item(tok, it, max_len, head_max_len) for it in items]],
                                  tok.pad_token_id)
            logits = _forward(model, batch, device, False, False)
            labels = [list(it["q"]["crit"])[int(logits[i, :it["k"]].argmax())]
                      for i, it in enumerate(items)]
            expected = list(row["expected"].values())
            for gold, pred in zip(expected, labels, strict=True):
                confusion[gold, pred] += 1
            predictions.append({"event_id": row["metadata"]["event_id"],
                                "predicted": labels, "expected": expected})
    return {"questions": sum(confusion.values()),
        "correct": sum(v for (gold, pred), v in confusion.items() if gold == pred),
        "confusion": [{"gold": g, "predicted": p, "count": n} for (g, p), n in confusion.items()],
        "predictions": predictions, "calibrated": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--objective", choices=("ce", "consistency"), required=True)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    import torch
    from laya.common import collate_items
    from laya.train import _forward, encode_item, items_from_rows, load_checkpoint, save_checkpoint
    from transformers import AutoTokenizer

    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    max_len, head_max_len, accumulation = 2048, 256, 2
    preparation = read_json(args.data / "preparation.json")
    epochs = len(preparation["epochs"])
    groups = [load_rows(args.data / f"epoch-{i}.jsonl") for i in range(epochs)]
    dev_rows = load_rows(args.data / "dev.jsonl")
    tok = AutoTokenizer.from_pretrained(args.base / "tokenizer", local_files_only=True)
    lengths = [audit(rows, tok, max_len, head_max_len) for rows in groups]
    dev_lengths = audit(dev_rows, tok, max_len, head_max_len)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "lengths.json", {"epochs": lengths, "dev": dev_lengths})
    bad = [r for rows in [*lengths, dev_lengths] for r in rows
           if r["state_tokens_dropped"] or r["head_tokens_dropped"]]
    planned_steps = sum(math.ceil(len(rows) / accumulation) for rows in groups)
    run = {"status": "AUDITED", "pid": os.getpid(), "objective": args.objective,
        "consistency_weight": 0.25 if args.objective == "consistency" else 0.0,
        "base_checkpoint": str(args.base.resolve()), "data": str(args.data.resolve()),
        "device": "cpu", "threads": args.threads, "freeze_encoder": False,
        "epochs": epochs, "groups_per_update": accumulation,
        "optimizer_updates_planned": planned_steps, "optimizer_updates_actual": 0,
        "sequences_planned": sum(len(rows) for rows in lengths),
        "unpadded_token_positions_planned": sum(
            r["sequence_tokens"] for rows in lengths for r in rows),
        "max_len": max_len, "head_max_len": head_max_len,
        "max_actual_length": max(r["sequence_tokens"] for rows in lengths for r in rows),
        "oversized_questions": len(bad), "encoder_lr": 2.5e-5, "head_lr": 1e-4,
        "seed": 0, "calibrated": False, "calibration_test_consumed": False,
        "scope": "matched small-source development diagnosis; not independent test evidence"}
    write_json(args.output / "run.json", run)
    if args.audit_only:
        return
    if bad:
        raise ValueError("Input/head truncation; inspect saved length audit before training")
    started, cpu = time.perf_counter(), time.process_time()
    run["status"] = "RUNNING"
    write_json(args.output / "run.json", run)
    try:
        model, tok, config = load_checkpoint(str(args.base))
        device = torch.device("cpu")
        model.to(device)
        optimizer = torch.optim.AdamW([
            {"params": [p for n, p in model.named_parameters() if n.startswith("encoder.")],
             "lr": run["encoder_lr"]},
            {"params": [p for n, p in model.named_parameters() if not n.startswith("encoder.")],
             "lr": run["head_lr"]}], weight_decay=0.01)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=planned_steps, eta_min=1e-6)
        before = evaluate(model, tok, dev_rows, device, max_len, head_max_len)
        write_json(args.output / "before-dev.json", before)
        history = []
        run.update(sequences_actual=0, unpadded_token_positions_actual=0)
        for epoch, rows in enumerate(groups):
            model.train()
            optimizer.zero_grad(set_to_none=True)
            ce_total = js_total = 0.0
            for index, row in enumerate(rows):
                items, skipped = items_from_rows(tok, [row], max_len, head_max_len)
                if skipped:
                    raise ValueError(f"Training items skipped: {skipped}")
                encoded = [encode_item(tok, it, max_len, head_max_len) for it in items]
                batch = collate_items([encoded], tok.pad_token_id)
                logits = _forward(model, batch, device, False, False)
                mask, target = batch["marker_mask"].to(device), batch["target"].to(device)
                from laya.train import soft_ce_loss

                ce = soft_ce_loss(logits, target, mask)
                js = marginal_consistency(logits) if len(items) == 3 else logits.sum() * 0
                loss = ce + run["consistency_weight"] * js
                if not torch.isfinite(loss):
                    raise ValueError("Non-finite matched training objective")
                window = min(accumulation, len(rows) - (index // accumulation) * accumulation)
                (loss / window).backward()
                if (index + 1) % accumulation == 0 or index + 1 == len(rows):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                    run["optimizer_updates_actual"] += 1
                run["sequences_actual"] += len(items)
                run["unpadded_token_positions_actual"] += int(batch["attention_mask"].sum())
                ce_total += ce.item()
                js_total += js.item()
                print(json.dumps({"epoch": epoch + 1, "group": index + 1,
                    "ce": ce.item(), "js": js.item(), "updates": run["optimizer_updates_actual"]}),
                      flush=True)
            metrics = evaluate(model, tok, dev_rows, device, max_len, head_max_len)
            history.append({"epoch": epoch + 1, "ce_mean": ce_total / len(rows),
                            "js_mean": js_total / len(rows), "dev": metrics})
            write_json(args.output / "history.json", history)
            write_json(args.output / "run.json", run)
            checkpoint_config = {**config, "max_len": max_len, "head_max_len": head_max_len,
                "fine_tuned": True, "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {},
                "training": {**config.get("training", {}), "milai_matched": run}}
            save_checkpoint(model, tok, checkpoint_config, str(args.output / "checkpoint_latest"))
        run["status"] = "COMPLETED"
        checkpoint_config["training"]["milai_matched"] = dict(run)
        save_checkpoint(model, tok, checkpoint_config, str(args.output / "checkpoint"))
        write_json(args.output / "result.json", {**run, "before_dev": before, "history": history})
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        compute = {"wall_seconds": time.perf_counter() - started,
                   "cpu_seconds": time.process_time() - cpu, "runs": 1}
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            state = read_json(args.budget)
            budget = RunBudget(RunLimits(**state["limits"]), args.budget)
            budget.record_compute("laya_matched_" + args.objective, compute)
        write_json(args.output / "compute.json", {**compute,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "device": "cpu", "ledger": str(args.budget)})
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
