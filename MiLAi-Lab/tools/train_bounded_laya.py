"""CE, acceptable-set or reviewed-pair loss on two explicitly allocated GPUs.

All labelled prefixes are used. Normalize within event and then family, so a
long history or a family with many derived states cannot dominate the objective.
Calibration/test are not loaded. GPU zero-shot and checkpoint dev use the same
inputs, model and evaluator. This is a learning diagnosis, not a QA benchmark.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluate_bounded_laya import score_applicability_predictions, score_predictions
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.laya_local import NativeDecision
from retrieval_feedback import (
    encoding_row,
    feedback_counts,
    feedback_dev_report,
    pair_loss,
    score_feedback,
)
from retrieval_mixture import (
    event_weights,
    mixture_event_weights,
    normalized_mixture,
    project_mixed_row,
    score_mixed_predictions,
)
from train_laya_matched import audit

TrainingWindow = list[tuple[int, int]]  # (data pass, row index)


def training_microbatches(window: TrainingWindow, size: int) -> list[TrainingWindow]:
    """Partition one optimizer window without changing its examples or loss denominator."""
    return [window[start:start + size] for start in range(0, len(window), size)]


def training_forward(model: Any, parallel: Any, batch: dict[str, Any], device: Any) -> Any:
    """Avoid dispatching an empty shard when a microbatch has fewer rows than devices."""
    from laya.train import _forward

    executor = model if batch["input_ids"].shape[0] < len(parallel.device_ids) else parallel
    return _forward(executor, batch, device, False, False)


def training_stages(size: int, epochs: int, seed: int,
                    update_budget: int | None = None,
                    eval_at_updates: list[int] | None = None,
                    eval_every_updates: int | None = None,
                    ) -> list[tuple[int, list[TrainingWindow]]]:
    """Legacy epochs or an exact budget of full16-example optimizer updates.

    Budgeted updates cross pass boundaries without dropping or padding examples.
    Half/final checkpoints are fixed in advance, not selected by development loss.
    """
    if size < 1 or epochs < 1 or (update_budget is not None and update_budget < 1):
        raise ValueError("Training requires labelled states and a positive budget")
    if eval_at_updates is not None and eval_every_updates is not None:
        raise ValueError("Specify evaluation points or an interval, not both")
    if eval_at_updates is not None or eval_every_updates is not None:
        if update_budget is None:
            raise ValueError("Custom evaluation requires an explicit optimizer-update budget")
        if eval_every_updates is not None and eval_every_updates < 1:
            raise ValueError("Evaluation interval must be positive")
        if eval_at_updates is not None and any(
                step < 1 or step > update_budget for step in eval_at_updates):
            raise ValueError("Evaluation points must be within the optimizer-update budget")
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
    if eval_at_updates is not None:
        cuts = sorted({*eval_at_updates, update_budget})
    elif eval_every_updates is not None:
        cuts = sorted({*range(eval_every_updates, update_budget, eval_every_updates),
                       update_budget})
    return [(end, windows[start:end]) for start, end in zip([0, *cuts[:-1]], cuts, strict=True)]


def optimizer_groups(model: Any, encoder_lr: float, head_lr: float,
                     freeze_encoder: bool) -> list[dict[str, Any]]:
    """Optimize the declared parameter scope; a frozen encoder has no optimizer state."""
    model.encoder.requires_grad_(not freeze_encoder)
    parameters = dict(model.named_parameters())
    groups = [{"params": [p for n, p in parameters.items() if not n.startswith("encoder.")],
               "lr": head_lr}]
    if not freeze_encoder:
        groups.insert(0, {"params": list(model.encoder.parameters()), "lr": encoder_lr})
    return groups


def training_mode(model: Any, freeze_encoder: bool) -> None:
    model.train()
    if freeze_encoder:
        model.encoder.eval()


def state_option_seed(seed: int, data_pass: int, state_id: int) -> int:
    """Integer source-state identity keeps shared options aligned across different masks."""
    return (seed << 64) + (data_pass << 32) + state_id


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
    for component, count in run.get("sampled_component_rows", {}).items():
        counts[f"train_component_{component}_rows"] = count
    for component, tokens in run.get("sampled_component_input_tokens", {}).items():
        counts[f"train_component_{component}_input_tokens"] = tokens
    for key in ("feedback_states", "replay_states", "directional_pairs",
                "tie_pairs", "unknown_pairs"):
        if "sampled_" + key in run:
            counts["train_" + key] = run["sampled_" + key]
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
    evaluation = parser.add_mutually_exclusive_group()
    evaluation.add_argument("--eval-at-updates", type=int, nargs="+")
    evaluation.add_argument("--eval-every-updates", type=int)
    parser.add_argument("--encoder-lr", type=float, default=2.5e-5)
    parser.add_argument("--head-lr", type=float, default=1e-4)
    parser.add_argument("--freeze-encoder", action="store_true")
    parser.add_argument("--micro-batch-size", type=int, choices=(1, 2, 4, 8, 16), default=4,
                        help="Per-forward rows; effective optimizer windows remain16 examples")
    parser.add_argument("--dev-data", type=Path,
                        help="Common development labels/inputs independent of the training recipe")
    parser.add_argument("--feedback-dev-data", type=Path,
                        help="Separate source-disjoint answer/delivery evaluation for all arms")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--head-max-len", type=int, default=384)
    parser.add_argument("--backend", choices=("native", "linear"), default="native")
    parser.add_argument("--objective", choices=("soft-ce", "set", "pair"), default="soft-ce")
    parser.add_argument("--feedback-target", choices=("answer", "delivery"),
                        help="Pair objective only; both targets use the same reviewed pair pool")
    parser.add_argument("--replay-weight", type=float, default=0.25,
                        help="Relative loss mass of old CE replay under the pair objective")
    parser.add_argument("--task", choices=("bounded_reader", "memory_operation",
                                           "instruction_applicability", "mixed_retrieval"),
                        default="bounded_reader", help="Use task-specific offline decision metrics")
    parser.add_argument("--mixture", type=Path,
                        help="Component loss masses for mixed_retrieval; draws stay uniform")
    parser.add_argument("--operation-state", choices=(
                            "full", "mechanical", "shared", "shared_request_text",
                            "shared_actions", "shared_actions_request_text"),
                        default="full",
                        help="Retrain with the same operation-state projection used in the Host")
    parser.add_argument("--evaluate-train", action="store_true",
                        help="Save train-prefix predictions as a learning diagnosis")
    parser.add_argument("--train-eval-final-only", action="store_true",
                        help="With --evaluate-train, evaluate training states only after fitting")
    parser.add_argument("--skip-initial-dev", action="store_true",
                        help="Omit unchanged base-checkpoint evaluation; retain its prior results")
    parser.add_argument("--shuffle-options", action="store_true",
                        help="Resample option slots and matching targets each training epoch")
    parser.add_argument("--gradient-checkpointing", action="store_true",
                        help="Recompute encoder activations during backward to reduce memory")
    args = parser.parse_args()
    if (args.objective == "pair") != (args.feedback_target is not None):
        parser.error("Pair training requires --feedback-target; CE does not use it")
    if args.objective == "pair" and (args.task != "memory_operation"
                                    or not 0 < args.replay_weight < float("inf")):
        parser.error("Pair feedback uses memory_operation and a positive finite replay weight")
    if args.objective == "pair" and args.optimizer_updates is None:
        parser.error("Pair feedback requires an explicit matched optimizer-update budget")
    if (args.task == "mixed_retrieval") != (args.mixture is not None):
        parser.error("mixed_retrieval requires --mixture, and other tasks do not use it")
    if args.mixture is not None and args.optimizer_updates is None:
        parser.error("The mixed recipe requires an explicit matched optimizer-update budget")
    if any(not math.isfinite(lr) or lr <= 0 for lr in (args.encoder_lr, args.head_lr)):
        parser.error("Learning rates must be positive and finite")
    if args.feedback_dev_data is not None and args.task not in {
            "memory_operation", "mixed_retrieval"}:
        parser.error("Feedback development evaluates memory-operation inputs")
    try:
        training_stages(1, args.epochs, args.seed, args.optimizer_updates,
                        args.eval_at_updates, args.eval_every_updates)
    except ValueError as error:
        parser.error(str(error))
    import torch
    from laya.common import collate_items
    from laya.train import (
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
    raw_train = read_jsonl(args.data / "train.jsonl")
    train = [r for r in raw_train if r["gold"] or (args.objective == "pair" and "feedback" in r)]
    dev_path = args.dev_data or args.data / "dev.jsonl"
    dev = read_jsonl(dev_path)
    feedback_dev = read_jsonl(args.feedback_dev_data) if args.feedback_dev_data is not None else []
    feedback_development = feedback_dev_report(feedback_dev, raw_train, dev)
    if args.feedback_dev_data is not None:
        from milai_lab.methods.laya_memory_policy import project_operation_payload

        feedback_dev = [project_operation_payload(row, args.operation_state)
                        for row in feedback_dev]
    if args.task == "memory_operation":
        from milai_lab.methods.laya_memory_policy import project_operation_payload

        train = [project_operation_payload(row, args.operation_state) for row in train]
        dev = [project_operation_payload(row, args.operation_state) for row in dev]
    elif args.task == "mixed_retrieval":
        train = [project_mixed_row(row, args.operation_state) for row in train]
        dev = [project_mixed_row(row, args.operation_state) for row in dev]
    elif args.task == "instruction_applicability" and args.operation_state in {
            "shared_request_text", "shared_actions_request_text"}:
        from milai_lab.memory.request_text import project_request_text

        train = [project_request_text(row) for row in train]
        dev = [project_request_text(row) for row in dev]
    mixture = normalized_mixture(read_json(args.mixture)) if args.mixture is not None else None
    weights = mixture_event_weights(train, mixture) if mixture is not None else event_weights(train)
    if args.objective == "pair":
        # Normalize each component by family/event, then apply the declared replay mass.
        weighted_rows = [{**row, "metadata": {**row["metadata"],
            "component": "feedback" if "feedback" in row else "operation_replay"}}
            for row in train]
        weights = mixture_event_weights(weighted_rows, {
            "feedback": 1.0, "operation_replay": args.replay_weight})
    stages = training_stages(len(train), args.epochs, args.seed, args.optimizer_updates,
                             args.eval_at_updates, args.eval_every_updates)
    axis = "epoch" if args.optimizer_updates is None else "optimizer_updates"
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "base_checkpoint": str(args.checkpoint.resolve()), "seed": args.seed,
           "physical_gpus": [2, 3], "device": "cuda", "torch_version": torch.__version__,
           "cuda_version": torch.version.cuda, "precision": "float32",
           "reference_compile": False,
           "gradient_checkpointing": args.gradient_checkpointing,
           "forward_count_scope": "Logical model calls; activation recomputation is in time cost",
           "backend": args.backend, "task": args.task, "operation_state": args.operation_state,
           "epochs": args.epochs if args.optimizer_updates is None else None,
           "planned_optimizer_updates": sum(len(windows) for _, windows in stages),
           "checkpoint_axis": axis, "dev_source": str(dev_path.resolve()),
           "batch_size": args.micro_batch_size,
           "gradient_accumulation": 16 // args.micro_batch_size,
           "max_len": args.max_len, "head_max_len": args.head_max_len, "train_states": len(train),
           "dev_states": len(dev), "encoder_lr": args.encoder_lr, "head_lr": args.head_lr,
           "freeze_encoder": args.freeze_encoder, "objective": args.objective,
           "evaluation_points": [step for step, _ in stages],
           "feedback_dev": feedback_development,
           "feedback_dev_source": (str(args.feedback_dev_data.resolve())
                                   if args.feedback_dev_data is not None else None),
           "loss_weighting": "event-and-family-normalized",
           "evaluate_train": args.evaluate_train,
           "train_eval_final_only": args.train_eval_final_only,
           "evaluate_initial_dev": not args.skip_initial_dev,
           "shuffle_options": args.shuffle_options,
           "calibration_test_loaded": False, "http_requests": 0,
           "optimizer_updates": 0, "train_sequence_rows": 0, "train_input_tokens": 0,
           "train_batch_forwards": 0, "train_device_forwards": 0,
           "train_batch_attempts": 0, "train_offered_rows": 0, "train_offered_tokens": 0}
    if mixture is not None:
        run.update(loss_weighting="declared component mass, then family and event",
                   mixture=mixture, sampling="uniform shuffled passes over labelled rows",
                   sampled_component_rows={}, sampled_task_rows={},
                   sampled_component_input_tokens={})
    if args.objective == "pair":
        run.update(feedback_target=args.feedback_target, replay_weight=args.replay_weight,
                   feedback_pool=feedback_counts(train, args.feedback_target),
                   sampling="uniform shuffled passes over retained feedback and old replay rows",
                   loss_weighting="feedback:replay mass 1:alpha, then family/event; "
                                  "mean directional pairs within each state",
                   tie_unknown_sampling="Retained as zero-direction states in both arms",
                   sampled_feedback_states=0, sampled_replay_states=0,
                   sampled_directional_pairs=0, sampled_tie_pairs=0, sampled_unknown_pairs=0)
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
        if args.gradient_checkpointing:
            model.encoder.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False})
        evaluation_rows = {"train": train, "dev": dev}
        if args.feedback_dev_data is not None:
            evaluation_rows["feedback-dev"] = feedback_dev
        lengths = {split: audit(rows, tok, args.max_len, args.head_max_len)
                   for split, rows in evaluation_rows.items()}
        write_json(args.output / "lengths.json", lengths)
        if any(r["state_tokens_dropped"] or r["head_tokens_dropped"]
               for records in lengths.values() for r in records):
            raise ValueError("Complete-input audit failed")
        codec_rows = ([encoding_row(row) for row in train]
                      if args.objective == "pair" else train)
        items, skipped = items_from_rows(tok, codec_rows, args.max_len, args.head_max_len)
        if skipped or len(items) != len(train):
            raise ValueError(f"Invalid training items: {skipped}")
        encoded = [encode_item(tok, item, args.max_len, args.head_max_len) for item in items]
        option_orders: list[list[int] | None] = [None] * len(items)
        write_json(args.output / "sampling.json", [
            {"event_id": r["metadata"]["event_id"], "family": r["metadata"]["family"],
             "source_row": r["metadata"]["row"], "weight": w,
             **({"component": r["metadata"]["component"], "task": r["metadata"]["task"]}
                if mixture is not None else {})}
            for r, w in zip(train, weights, strict=True)])
        decision.device = torch.device("cuda:0")
        model.to(decision.device)
        parallel = torch.nn.DataParallel(model, device_ids=[0, 1])
        parameters = dict(model.named_parameters())
        probes = {"encoder": next(n for n in parameters if n.startswith("encoder.")),
                  "head": next(n for n in parameters if not n.startswith("encoder."))}
        before = {key: parameters[name].detach().cpu().clone() for key, name in probes.items()}
        optimizer = torch.optim.AdamW(optimizer_groups(
            model, args.encoder_lr, args.head_lr, args.freeze_encoder), weight_decay=0.01)
        steps = run["planned_optimizer_updates"]
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, steps, eta_min=1e-6)

        def evaluate(epoch: int, split: str = "dev") -> dict[str, Any]:
            model.eval()
            predictions = []
            rows = evaluation_rows[split]
            for index, row in enumerate(rows):
                payload = {k: row[k] for k in ("state", "questions")}
                previous_counts = dict(decision.counters)
                predictions.append(decision.predict(payload))
                evaluation_counts[split].update({
                    k: v - previous_counts[k] for k, v in decision.counters.items()})
                write_json(args.output / split / str(epoch) / f"{index}.json", predictions[-1])
            if split == "feedback-dev":
                result = {target: score_feedback(rows, predictions, target)
                          for target in ("answer", "delivery")}
                result["coverage"] = feedback_development
            elif args.task == "memory_operation":
                from milai_lab.methods.memory_control_learning import score_operation_predictions

                result = score_operation_predictions(rows, predictions)
                if args.objective == "pair":
                    result["reviewed_branch_pairs"] = score_feedback(
                        rows, predictions, args.feedback_target)
            elif args.task == "instruction_applicability":
                result = score_applicability_predictions(rows, predictions)
            elif args.task == "mixed_retrieval":
                result = score_mixed_predictions(rows, predictions)
            else:
                result = score_predictions(rows, predictions)
            write_json(args.output / split / str(epoch) / "summary.json", result)
            return result

        history = [] if args.skip_initial_dev else [{axis: 0, "dev": evaluate(0)}]
        if args.feedback_dev_data is not None and not args.skip_initial_dev:
            history[0]["feedback-dev"] = evaluate(0, "feedback-dev")
        if args.evaluate_train and not args.train_eval_final_only:
            if not history:
                history.append({axis: 0})
            history[0]["train"] = evaluate(0, "train")
        write_json(args.output / "history.json", history)
        option_rng = random.Random(args.seed + 10000)  # noqa: S311 -- independent of row order
        encoded_pass = 0
        for checkpoint_step, windows in stages:
            training_mode(model, args.freeze_encoder)
            loss_total = 0.0
            offered = 0
            for window in windows:
                denominator = len(window)
                optimizer.zero_grad(set_to_none=True)
                for microbatch in training_microbatches(window, args.micro_batch_size):
                    indices, batch_items, batch_keys = [], [], []
                    for data_pass, index in microbatch:
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
                        keys = list(items[index]["q"]["crit"])
                        order = option_orders[index]
                        batch_keys.append(keys if order is None else [keys[i] for i in order])
                    batch = collate_items(batch_items, tok.pad_token_id)
                    run["train_batch_attempts"] += 1
                    run["train_offered_rows"] += len(indices)
                    run["train_offered_tokens"] += int(batch["attention_mask"].sum())
                    logits = training_forward(model, parallel, batch, decision.device)
                    mask = batch["marker_mask"].to(decision.device)
                    target = batch["target"].to(decision.device)
                    ce = decision_loss(logits, target, mask,
                                       "soft-ce" if args.objective == "pair" else args.objective)
                    if args.objective == "pair":
                        ce = torch.stack([
                            pair_loss(logits[slot], batch_keys[slot],
                                      train[index]["feedback"]["comparisons"], args.feedback_target)
                            if "feedback" in train[index] else ce[slot]
                            for slot, index in enumerate(indices)])
                        counts = feedback_counts([train[i] for i in indices], args.feedback_target)
                        for name in ("feedback_states", "replay_states", "directional_pairs",
                                     "tie_pairs", "unknown_pairs"):
                            run["sampled_" + name] += counts.get(name, 0)
                    weighted = ce * torch.tensor([weights[i] for i in indices],
                                                  device=decision.device)
                    loss = weighted.sum() / denominator
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite decision loss")
                    loss.backward()
                    loss_total += float(weighted.sum().detach())
                    offered += len(indices)
                    run["train_sequence_rows"] += len(indices)
                    if mixture is not None:
                        token_counts = batch["attention_mask"].sum(dim=1).tolist()
                        for index, tokens in zip(indices, token_counts, strict=True):
                            for field, count_key in (("component", "sampled_component_rows"),
                                                     ("task", "sampled_task_rows")):
                                name = train[index]["metadata"][field]
                                run[count_key][name] = run[count_key].get(name, 0) + 1
                            component = train[index]["metadata"]["component"]
                            component_tokens = run["sampled_component_input_tokens"]
                            component_tokens[component] = (
                                component_tokens.get(component, 0) + int(tokens))
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
            if args.feedback_dev_data is not None:
                history[-1]["feedback-dev"] = evaluate(checkpoint_step, "feedback-dev")
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
            destination = args.output / "checkpoint_latest"
            if args.eval_at_updates is not None or args.eval_every_updates is not None:
                destination = args.output / "checkpoints" / f"update-{checkpoint_step}"
            checkpoint_writer(model, tok, config, str(destination))
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
            backend = "laya" if args.backend == "native" else "linear"
            phase = args.compute_phase or {
                "memory_operation": f"{backend}_memory_operation_ce",
                "instruction_applicability": f"{backend}_instruction_applicability_ce",
                "mixed_retrieval": f"{backend}_mixed_retrieval_ce",
                "bounded_reader": f"{backend}_reader_ce",
            }[args.task]
            budget.record_compute(phase, measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
