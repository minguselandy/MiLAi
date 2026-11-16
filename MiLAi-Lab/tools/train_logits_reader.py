"""Matched-data ordinary letter-logit LoRA control, using a local Qwen checkpoint.

Full next-token soft-CE, four epochs, sixteen states/update, the same source/event
weights and shuffles as encoder controls. Only LoRA weights are optimized.
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
from logits_reader import LogitsDecision, collate_decisions, encode_decision
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from train_bounded_laya import event_weights


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    args = parser.parse_args()
    import torch

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3" or torch.cuda.device_count() != 2:
        raise ValueError("Declared allocation is physical GPUs2,3")
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    for i in (0, 1):
        torch.cuda.set_per_process_memory_fraction(0.75, i)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    train = [json.loads(s) for s in (args.data / "train.jsonl").read_text().splitlines()]
    train = [r for r in train if r["gold"]]
    dev = [json.loads(s) for s in (args.data / "dev.jsonl").read_text().splitlines()]
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "base": str(args.base.resolve()), "epochs": 4, "seed": 0, "states_per_update": 16,
           "batch_size": 2, "gradient_accumulation": 8, "learning_rate": 1e-4,
           "lora_rank": 8, "lora_alpha": 16, "precision": "float32", "max_len": 8192,
           "gradient_checkpointing": True, "checkpoint_reentrant": False,
           "forward_counter_scope": "model entries; layer recomputations included in timings",
           "loss": "full-vocabulary next-token soft-CE", "train_states": len(train),
           "dev_states": len(dev), "optimizer_updates": 0, "train_offered_rows": 0,
           "train_completed_rows": 0, "train_offered_tokens": 0, "train_device_forwards": 0,
           "calibration_test_loaded": False, "http_requests": 0, "generated_tokens": 0}
    write_json(args.output / "run.json", run)
    decision = None
    try:
        decision = LogitsDecision(args.base, train_lora=True)
        encoded = [encode_decision({k: r[k] for k in ("state", "questions")},
                                   decision.tokenizer, 8192) for r in train]
        dev_encoded = [encode_decision({k: r[k] for k in ("state", "questions")},
                                       decision.tokenizer, 8192) for r in dev]
        run["preparation_chat_tokenizations"] = len(encoded) + len(dev_encoded)
        run["preparation_letter_tokenizations"] = sum(len(r["letter_ids"])
                                                     for r in encoded + dev_encoded)
        write_json(args.output / "lengths.json", {
            "train": [len(r["input_ids"]) for r in encoded],
            "dev": [len(r["input_ids"]) for r in dev_encoded], "truncated": 0})
        weights = event_weights(train)
        decision.device = torch.device("cuda:0")
        model = decision.model.to(decision.device)
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        parallel = torch.nn.DataParallel(model, device_ids=[0, 1])
        trainable = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
        run["trainable_parameters"] = sum(p.numel() for _, p in trainable)
        run["total_parameters"] = sum(p.numel() for p in model.parameters())
        before = {name: p.detach().cpu().clone() for name, p in trainable}
        optimizer = torch.optim.AdamW([p for _, p in trainable], lr=1e-4, weight_decay=0.01)
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

        history = [{"epoch": 0, "dev": evaluate(0)}]
        write_json(args.output / "history.json", history)
        rng = random.Random(0)  # noqa: S311 -- matched training order
        for epoch in range(1, 5):
            model.train()
            order = list(range(len(train)))
            rng.shuffle(order)
            total_loss = 0.0
            for start in range(0, len(train), 16):
                window = order[start:start + 16]
                optimizer.zero_grad(set_to_none=True)
                for index in range(0, len(window), 2):
                    ids = window[index:index + 2]
                    batch = collate_decisions([encoded[i] for i in ids],
                                               decision.tokenizer.pad_token_id, decision.device)
                    run["train_offered_rows"] += len(ids)
                    run["train_offered_tokens"] += sum(len(encoded[i]["input_ids"]) for i in ids)
                    run["train_device_forwards"] += min(len(ids), 2)
                    logits = parallel(**batch, logits_to_keep=1, use_cache=False,
                                      return_dict=False)[0][:, -1].float()
                    logp = torch.log_softmax(logits, -1)
                    losses = []
                    for j, i in enumerate(ids):
                        target = train[i]["gold"]["next"]["probabilities"]
                        probabilities = torch.tensor([target.get(k, 0) for k in encoded[i]["keys"]],
                                                     device=decision.device)
                        losses.append(-(probabilities * logp[j, encoded[i]["letter_ids"]]).sum()
                                      * weights[i])
                    loss = torch.stack(losses).sum() / len(window)
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite letter-logit training loss")
                    loss.backward()
                    total_loss += float(torch.stack(losses).sum().detach())
                    run["train_completed_rows"] += len(ids)
                torch.nn.utils.clip_grad_norm_([p for _, p in trainable], 1.0)
                optimizer.step()
                scheduler.step()
                run["optimizer_updates"] += 1
                write_json(args.output / "run.json", run)
                print(json.dumps({"epoch": epoch, "updates": run["optimizer_updates"]}), flush=True)
            history.append({"epoch": epoch, "weighted_ce_mean": total_loss / len(train),
                            "dev": evaluate(epoch)})
            write_json(args.output / "history.json", history)
            decision.save(args.output / "checkpoint_latest")
        write_json(args.output / "parameter-changes.json", {
            name: int((p.detach().cpu() != before[name]).sum()) for name, p in trainable})
        decision.save(args.output / "checkpoint")
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        for i in (0, 1):
            torch.cuda.synchronize(i)
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **{k: run[k] for k in ("train_offered_rows", "train_completed_rows",
                                           "train_offered_tokens", "train_device_forwards",
                                           "preparation_chat_tokenizations",
                                           "preparation_letter_tokenizations") if k in run},
                    **{f"dev_{k}": v for k, v in (
                        decision.counters.items() if decision is not None else [])}}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": [torch.cuda.max_memory_allocated(i) for i in (0, 1)]})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute("logits_reader_lora", measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
