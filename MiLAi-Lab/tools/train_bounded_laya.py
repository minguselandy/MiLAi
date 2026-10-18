"""Matched soft-CE or acceptable-set loss on two explicitly allocated GPUs.

All labelled prefixes are used. Normalize within event and then family, so a
long history or a family with many derived states cannot dominate the objective.
Calibration/test are not loaded. GPU zero-shot and checkpoint dev use the same
inputs, model and evaluator. This is a learning diagnosis, not a QA benchmark.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import random
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluate_bounded_laya import NativeDecision, score_predictions
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from train_laya_matched import audit

TrainingWindow = list[tuple[int, int]]  # (data pass, row index)


def training_stages(size: int, epochs: int, seed: int,
                    update_budget: int | None = None) -> list[tuple[int, list[TrainingWindow]]]:
    """Legacy epochs or an exact budget of full16-example optimizer updates.

    Budgeted updates cross pass boundaries without dropping or padding examples.
    Half/final checkpoints are fixed in advance, not selected by development loss.
    """
    if size < 1 or epochs < 1 or (update_budget is not None and update_budget < 1):
        raise ValueError("Training requires labelled states and a positive budget")
    rng = random.Random(seed)  # noqa: S311 -- reproducible training schedule
    if update_budget is None:
        stages = []
        for epoch in range(1, epochs + 1):
            order = list(range(size))
            rng.shuffle(order)
            stages.append((epoch, [[(epoch, i) for i in order[start:start + 16]]
                                   for start in range(0, size, 16)]))
        return stages
    draws: TrainingWindow = []
    data_pass = 0
    while len(draws) < update_budget * 16:
        data_pass += 1
        order = list(range(size))
        rng.shuffle(order)
        draws.extend((data_pass, i) for i in order)
    windows = [draws[i:i + 16] for i in range(0, update_budget * 16, 16)]
    cuts = sorted({update_budget // 2, update_budget} - {0})
    return [(end, windows[start:end]) for start, end in zip([0, *cuts[:-1]], cuts, strict=True)]


def state_option_seed(seed: int, data_pass: int, state_id: int) -> int:
    """Integer source-state identity keeps shared options aligned across different masks."""
    return (seed << 64) + (data_pass << 32) + state_id


def event_weights(rows: list[dict[str, Any]]) -> list[float]:
    keys = [(r["metadata"]["family"],
             r["metadata"].get("training_event", r["metadata"]["row"])) for r in rows]
    counts = Counter(keys)
    events: dict[str, set[int | str]] = defaultdict(set)
    for family, event in counts:
        events[family].add(event)
    return [len(rows) / len(events) / len(events[family]) / counts[family, event]
            for family, event in keys]


def decision_loss(logits: Any, target: Any, mask: Any, objective: str) -> Any:
    """Return per-state loss; padding is never an acceptable action.

    Set likelihood rewards any admitted action without forcing uniform mass
    among equivalent positives. It does not correct the source labels.
    """
    import torch

    valid_logits = logits.masked_fill(~mask, -torch.inf)
    if objective == "set":
        positive_logits = valid_logits.masked_fill(~(target > 0), -torch.inf)
        return torch.logsumexp(valid_logits, -1) - torch.logsumexp(positive_logits, -1)
    logp = torch.log_softmax(valid_logits, dim=-1).masked_fill(~mask, 0)
    return -(target * logp).sum(-1)


def compute_counts(run: dict[str, Any], evaluations: dict[str, Counter[str]]) -> dict[str, int]:
    """Keep optimization work distinct from evaluation on the training split."""
    counts = {k: run[k] for k in (
        "train_sequence_rows", "train_input_tokens", "train_batch_forwards",
        "train_device_forwards", "train_batch_attempts", "train_offered_rows",
        "train_offered_tokens")}
    for split, counters in evaluations.items():
        prefix = "train_eval" if split == "train" else split
        counts.update({f"{prefix}_{key}": value for key, value in counters.items()})
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--compute-phase", help="Distinct phase in the original shared ledger")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--optimizer-updates", type=int,
                        help="Use this exact update budget with full16-example windows")
    parser.add_argument("--dev-data", type=Path,
                        help="Common development labels/inputs independent of the training recipe")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--head-max-len", type=int, default=384)
    parser.add_argument("--backend", choices=("native", "linear"), default="native")
    parser.add_argument("--objective", choices=("soft-ce", "set"), default="soft-ce")
    parser.add_argument("--task", choices=("bounded_reader", "memory_operation"),
                        default="bounded_reader", help="Use task-specific offline decision metrics")
    parser.add_argument("--operation-state", choices=("full", "mechanical"), default="full",
                        help="Retrain with the same operation-state projection used in the Host")
    parser.add_argument("--evaluate-train", action="store_true",
                        help="Save train-prefix predictions as a learning diagnosis")
    parser.add_argument("--train-eval-final-only", action="store_true",
                        help="With --evaluate-train, evaluate training states only after fitting")
    parser.add_argument("--shuffle-options", action="store_true",
                        help="Resample option slots and matching targets each training epoch")
    args = parser.parse_args()
    import torch
    from laya.common import collate_items
    from laya.train import (
        _forward,
        draw_option_order,
        encode_item,
        items_from_rows,
        save_checkpoint,
    )

    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3" or torch.cuda.device_count() != 2:
        raise ValueError("This declared run uses only physical GPUs 2,3")
    for device in (0, 1):
        torch.cuda.set_per_process_memory_fraction(0.75, device)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    train = [json.loads(x) for x in (args.data / "train.jsonl").read_text().splitlines()]
    train = [r for r in train if r["gold"]]
    dev_path = args.dev_data or args.data / "dev.jsonl"
    dev = [json.loads(x) for x in dev_path.read_text().splitlines()]
    if args.task == "memory_operation":
        from milai_lab.methods.laya_memory_policy import project_operation_payload

        train = [project_operation_payload(row, args.operation_state) for row in train]
        dev = [project_operation_payload(row, args.operation_state) for row in dev]
    stages = training_stages(len(train), args.epochs, args.seed, args.optimizer_updates)
    axis = "epoch" if args.optimizer_updates is None else "optimizer_updates"
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "base_checkpoint": str(args.checkpoint.resolve()), "seed": args.seed,
           "physical_gpus": [2, 3], "device": "cuda", "torch_version": torch.__version__,
           "cuda_version": torch.version.cuda, "precision": "float32",
           "reference_compile": False,
           "backend": args.backend, "task": args.task, "operation_state": args.operation_state,
           "epochs": args.epochs if args.optimizer_updates is None else None,
           "planned_optimizer_updates": sum(len(windows) for _, windows in stages),
           "checkpoint_axis": axis, "dev_source": str(dev_path.resolve()),
           "batch_size": 4, "gradient_accumulation": 4,
           "max_len": args.max_len, "head_max_len": args.head_max_len, "train_states": len(train),
           "dev_states": len(dev), "encoder_lr": 2.5e-5, "head_lr": 1e-4,
           "freeze_encoder": False, "objective": args.objective,
           "loss_weighting": "event-and-family-normalized",
           "evaluate_train": args.evaluate_train,
           "train_eval_final_only": args.train_eval_final_only,
           "shuffle_options": args.shuffle_options,
           "calibration_test_loaded": False, "http_requests": 0,
           "optimizer_updates": 0, "train_sequence_rows": 0, "train_input_tokens": 0,
           "train_batch_forwards": 0, "train_device_forwards": 0,
           "train_batch_attempts": 0, "train_offered_rows": 0, "train_offered_tokens": 0}
    write_json(args.output / "run.json", run)
    write_json(args.output / "training-plan.json", stages)
    decision: NativeDecision
    evaluation_counts: dict[str, Counter[str]] = defaultdict(Counter)
    try:
        if args.backend == "linear":
            from linear_reader_classifier import LinearDecision, save_linear_checkpoint

            decision = LinearDecision(args.checkpoint, args.max_len, args.head_max_len)
            checkpoint_writer = save_linear_checkpoint
        else:
            decision = NativeDecision(args.checkpoint, args.max_len, args.head_max_len)
            checkpoint_writer = save_checkpoint
        decision.config = {**decision.config, "operation_state": args.operation_state}
        model, tok = decision.model, decision.tokenizer
        # ModernBERT's compiled MLP cannot be traced concurrently by DataParallel
        # replicas when the final batch changes shape. Use its ordinary MLP path.
        model.encoder.config.reference_compile = False
        lengths = {split: audit(rows, tok, args.max_len, args.head_max_len) for split, rows in (
            ("train", train), ("dev", dev))}
        write_json(args.output / "lengths.json", lengths)
        if any(r["state_tokens_dropped"] or r["head_tokens_dropped"]
               for records in lengths.values() for r in records):
            raise ValueError("Complete-input audit failed")
        items, skipped = items_from_rows(tok, train, args.max_len, args.head_max_len)
        if skipped or len(items) != len(train):
            raise ValueError(f"Invalid training items: {skipped}")
        encoded = [encode_item(tok, item, args.max_len, args.head_max_len) for item in items]
        weights = event_weights(train)
        write_json(args.output / "sampling.json", [
            {"event_id": r["metadata"]["event_id"], "family": r["metadata"]["family"],
             "source_row": r["metadata"]["row"], "weight": w}
            for r, w in zip(train, weights, strict=True)])
        decision.device = torch.device("cuda:0")
        model.to(decision.device)
        parallel = torch.nn.DataParallel(model, device_ids=[0, 1])
        parameters = dict(model.named_parameters())
        probes = {"encoder": next(n for n in parameters if n.startswith("encoder.")),
                  "head": next(n for n in parameters if not n.startswith("encoder."))}
        before = {key: parameters[name].detach().cpu().clone() for key, name in probes.items()}
        optimizer = torch.optim.AdamW([
            {"params": [p for n, p in parameters.items() if n.startswith("encoder.")],
             "lr": run["encoder_lr"]},
            {"params": [p for n, p in parameters.items() if not n.startswith("encoder.")],
             "lr": run["head_lr"]}], weight_decay=0.01)
        steps = run["planned_optimizer_updates"]
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, steps, eta_min=1e-6)

        def evaluate(epoch: int, split: str = "dev") -> dict[str, Any]:
            model.eval()
            predictions = []
            rows = dev if split == "dev" else train
            for index, row in enumerate(rows):
                payload = {k: row[k] for k in ("state", "questions")}
                previous_counts = dict(decision.counters)
                predictions.append(decision.predict(payload))
                evaluation_counts[split].update({
                    k: v - previous_counts[k] for k, v in decision.counters.items()})
                write_json(args.output / split / str(epoch) / f"{index}.json", predictions[-1])
            if args.task == "memory_operation":
                from milai_lab.methods.memory_control_learning import score_operation_predictions

                result = score_operation_predictions(rows, predictions)
            else:
                result = score_predictions(rows, predictions)
            write_json(args.output / split / str(epoch) / "summary.json", result)
            return result

        history = [{axis: 0, "dev": evaluate(0)}]
        if args.evaluate_train and not args.train_eval_final_only:
            history[0]["train"] = evaluate(0, "train")
        write_json(args.output / "history.json", history)
        option_rng = random.Random(args.seed + 10000)  # noqa: S311 -- independent of row order
        encoded_pass = 0
        for checkpoint_step, windows in stages:
            model.train()
            loss_total = 0.0
            offered = 0
            for window in windows:
                denominator = len(window)
                optimizer.zero_grad(set_to_none=True)
                for start in range(0, len(window), 4):
                    indices, batch_items = [], []
                    for data_pass, index in window[start:start + 4]:
                        if encoded_pass != data_pass:
                            if args.shuffle_options:
                                option_orders = []
                                for item, row in zip(items, train, strict=True):
                                    shuffle_rng = option_rng
                                    if args.optimizer_updates is not None:
                                        state_seed = state_option_seed(
                                            args.seed, data_pass, row["metadata"]["state_id"])
                                        shuffle_rng = random.Random(state_seed)  # noqa: S311
                                    option_orders.append(draw_option_order(
                                        item, shuffle_rng, ("choice",)))
                                encoded = [encode_item(tok, item, args.max_len, args.head_max_len,
                                           option_order=order) for item, order in zip(
                                               items, option_orders, strict=True)]
                                write_json(args.output / "option-orders" / f"{data_pass}.json",
                                           option_orders)
                            encoded_pass = data_pass
                            run["data_passes_started"] = data_pass
                        indices.append(index)
                        batch_items.append([encoded[index]])
                    batch = collate_items(batch_items, tok.pad_token_id)
                    run["train_batch_attempts"] += 1
                    run["train_offered_rows"] += len(indices)
                    run["train_offered_tokens"] += int(batch["attention_mask"].sum())
                    logits = _forward(parallel, batch, decision.device, False, False)
                    mask = batch["marker_mask"].to(decision.device)
                    target = batch["target"].to(decision.device)
                    ce = decision_loss(logits, target, mask, args.objective)
                    weighted = ce * torch.tensor([weights[i] for i in indices],
                                                  device=decision.device)
                    loss = weighted.sum() / denominator
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite decision loss")
                    loss.backward()
                    loss_total += float(weighted.sum().detach())
                    offered += len(indices)
                    run["train_sequence_rows"] += len(indices)
                    run["train_input_tokens"] += int(batch["attention_mask"].sum())
                    run["train_batch_forwards"] += 1
                    run["train_device_forwards"] += min(len(indices), 2)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                run["optimizer_updates"] += 1
                write_json(args.output / "run.json", run)
                print(json.dumps({"data_pass": encoded_pass,
                                  "updates": run["optimizer_updates"]}), flush=True)
            history.append({axis: checkpoint_step, "weighted_loss_mean": loss_total / offered,
                            "dev": evaluate(checkpoint_step)})
            if args.objective == "soft-ce":
                history[-1]["weighted_ce_mean"] = loss_total / offered
            if args.evaluate_train and (
                    not args.train_eval_final_only or checkpoint_step == stages[-1][0]):
                history[-1]["train"] = evaluate(checkpoint_step, "train")
            write_json(args.output / "history.json", history)
            config = {**decision.config, "max_len": args.max_len, "head_max_len": args.head_max_len,
                      "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {},
                      "fine_tuned": True,
                      "training": {"milai_reader": {**run, axis: checkpoint_step}}}
            checkpoint_writer(model, tok, config, str(args.output / "checkpoint_latest"))
        changes = {key: {"parameter": name, "changed_elements": int((
            parameters[name].detach().cpu() != before[key]).sum())} for key, name in probes.items()}
        write_json(args.output / "parameter-probes.json", changes)
        checkpoint_writer(model, tok, config, str(args.output / "checkpoint"))
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        for device in (0, 1):
            torch.cuda.synchronize(device)
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **compute_counts(run, evaluation_counts)}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": [torch.cuda.max_memory_allocated(i) for i in (0, 1)],
            "ledger": str(args.budget)})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            phase = args.compute_phase or (
                f"{'laya' if args.backend == 'native' else 'linear'}_memory_operation_ce"
                if args.task == "memory_operation" else
                "laya_reader_ce" if args.backend == "native" else "linear_reader_ce")
            budget.record_compute(phase, measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
