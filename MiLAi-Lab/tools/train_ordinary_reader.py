"""Matched ordinary reranker: same encoder initialization, events, weights and updates.

Four epochs and sixteen states per optimizer update match the typed CE arm.
The ordinary scalar head is newly initialized. Expanded action encoding is
charged explicitly, including STOP options and every development pass.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import random
import resource
import time
from pathlib import Path

from evaluate_bounded_laya import score_predictions
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from ordinary_reader_reranker import (
    OrdinaryDecision,
    build_model,
    collate,
    encode_actions,
    save_model,
)
from train_bounded_laya import event_weights


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    args = parser.parse_args()
    import torch
    from laya.train import load_checkpoint

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3" or torch.cuda.device_count() != 2:
        raise ValueError("Declared training allocation is physical GPUs 2,3")
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    for device in (0, 1):
        torch.cuda.set_per_process_memory_fraction(0.75, device)
    device = torch.device("cuda:0")
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    train = [json.loads(line) for line in (args.data / "train.jsonl").read_text().splitlines()]
    train = [row for row in train if row["gold"]]
    dev = [json.loads(line) for line in (args.data / "dev.jsonl").read_text().splitlines()]
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "base": str(args.base.resolve()), "model": "same ModernBERT encoder + CLS linear head",
           "epochs": 4, "states_per_update": 16, "encoder_lr": 2.5e-5, "head_lr": 1e-4,
           "seed": 0, "optimizer_updates": 0, "reference_compile": False,
           "train_states": len(train), "dev_states": len(dev), "train_offered_states": 0,
           "train_completed_states": 0, "train_offered_sequences": 0,
           "train_offered_tokens": 0, "train_device_forward_attempts": 0,
           "physical_gpus": [2, 3], "precision": "float32", "calibration_test_loaded": False}
    write_json(args.output / "run.json", run)
    decision = None
    try:
        original, tok, _ = load_checkpoint(str(args.base))
        model = build_model(original.encoder)
        del original
        model.encoder.config.reference_compile = False
        encoded = [encode_actions({k: row[k] for k in ("state", "questions")}, tok)
                   for row in train]
        dev_lengths = [encode_actions({k: row[k] for k in ("state", "questions")}, tok)
                       for row in dev]
        run["preparation_state_tokenizations"] = len(train) + len(dev)
        run["preparation_action_tokenizations"] = sum(len(x["keys"])
                                                     for x in encoded + dev_lengths)
        write_json(args.output / "lengths.json", {
            split: [{"state": i, "sequence_rows": len(x["keys"]),
                     "input_tokens": x["input_tokens"],
                     "max_sequence": max(map(len, x["sequences"]))}
                    for i, x in enumerate(items)]
            for split, items in (("train", encoded), ("dev", dev_lengths))})
        weights = event_weights(train)
        write_json(args.output / "weights.json", weights)
        model.to(device)
        parallel = torch.nn.DataParallel(model, device_ids=[0, 1])
        decision = OrdinaryDecision(model, tok, device)
        optimizer = torch.optim.AdamW([
            {"params": model.encoder.parameters(), "lr": 2.5e-5},
            {"params": model.scorer.parameters(), "lr": 1e-4}], weight_decay=0.01)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=4 * math.ceil(len(train) / 16), eta_min=1e-6)

        def evaluate(epoch):
            model.eval()
            predictions = []
            for i, row in enumerate(dev):
                predictions.append(decision.predict({k: row[k] for k in ("state", "questions")}))
                write_json(args.output / "dev" / str(epoch) / f"{i}.json", predictions[-1])
            result = score_predictions(dev, predictions)
            write_json(args.output / "dev" / str(epoch) / "summary.json", result)
            return result

        history = [{"epoch": 0, "scope": "random scalar head, not a pretrained decision baseline",
                    "dev": evaluate(0)}]
        write_json(args.output / "history.json", history)
        rng = random.Random(0)  # noqa: S311 -- matched training order
        for epoch in range(1, 5):
            model.train()
            order = list(range(len(train)))
            rng.shuffle(order)
            total_loss = 0.0
            for start in range(0, len(order), 16):
                window = order[start:start + 16]
                optimizer.zero_grad(set_to_none=True)
                for i in window:
                    example = encoded[i]
                    batch = collate(example, tok.pad_token_id, device)
                    run["train_offered_states"] += 1
                    run["train_offered_sequences"] += len(example["keys"])
                    run["train_offered_tokens"] += example["input_tokens"]
                    run["train_device_forward_attempts"] += min(len(example["keys"]), 2)
                    scores = parallel(**batch)
                    gold = train[i]["gold"]["next"]["probabilities"]
                    target = torch.tensor([gold.get(k, 0) for k in example["keys"]], device=device)
                    loss = -(target * torch.log_softmax(scores, -1)).sum() * weights[i]
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite ordinary reranker CE")
                    (loss / len(window)).backward()
                    total_loss += float(loss.detach())
                    run["train_completed_states"] += 1
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                run["optimizer_updates"] += 1
                write_json(args.output / "run.json", run)
                print(json.dumps({"epoch": epoch, "updates": run["optimizer_updates"]}), flush=True)
            history.append({"epoch": epoch, "weighted_ce_mean": total_loss / len(train),
                            "dev": evaluate(epoch)})
            write_json(args.output / "history.json", history)
            save_model(model, tok, args.output / "checkpoint_latest")
        save_model(model, tok, args.output / "checkpoint")
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        for device_index in (0, 1):
            torch.cuda.synchronize(device_index)
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **{k: v for k, v in run.items()
                       if k.startswith(("train_", "preparation_")) and isinstance(v, int)},
                    **{f"dev_{k}": v for k, v in (
                        decision.counters.items() if decision is not None else [])}}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": [torch.cuda.max_memory_allocated(i) for i in (0, 1)]})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute("ordinary_reader_ce", measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
