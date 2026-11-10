"""CE, acceptable-set or reviewed-pair loss on explicitly allocated CUDA devices.

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
from typing import Any, cast

from conditional_training import (
    conditional_change_targets,
    conditional_relative_loss,
    conditional_training_groups,
)
from evaluate_bounded_laya import score_applicability_predictions, score_predictions
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.laya_local import NativeDecision
from quality_feedback import (
    ANSWER_FIRST_MASSES,
    QUALITY_MODES,
    QualityMode,
    answer_first_counts,
    answer_first_loss,
    answer_first_weights,
    quality_counts,
    quality_event_weights,
    quality_pair_loss,
    score_answer_first,
    score_quality_feedback,
    validate_quality_pool,
)
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
from training_recovery import (
    TrainingInterruption,
    make_scheduler,
    restore_training_state,
    save_training_state,
)

TrainingWindow = list[tuple[int, int]]  # (data pass, row index)


def training_microbatches(window: TrainingWindow, size: int,
                          lengths: list[int] | None = None,
                          paired: bool = False,
                          padded_token_target: int | None = None) -> list[TrainingWindow]:
    """Partition one optimizer window without changing its examples or loss denominator."""
    if size < 1 or (paired and size % 2):
        raise ValueError("Conditional pairs require an even microbatch size")
    width = 2 if paired else 1
    groups = [window[start:start + width] for start in range(0, len(window), width)]
    if lengths is not None:
        groups.sort(key=lambda group: max(lengths[index] for _, index in group))
    # The only singleton in a paired window is its final tail. Keep it last,
    # so sorting cannot shift the boundaries of any following pair.
    if paired:
        groups = [group for group in groups if len(group) == 2] + [
            group for group in groups if len(group) == 1]
    microbatches: list[TrainingWindow] = []
    current: TrainingWindow = []
    for group in groups:
        trial = [*current, *group]
        exceeds_tokens = (padded_token_target is not None and lengths is not None
                          and max(lengths[i] for _, i in trial) * len(trial)
                          > padded_token_target)
        if current and (len(trial) > size or exceeds_tokens):
            microbatches.append(current)
            current = []
        current.extend(group)
    if current:
        microbatches.append(current)
    return microbatches


def training_forward(model: Any, parallel: Any, batch: dict[str, Any], device: Any,
                     precision: str = "float32") -> Any:
    """Avoid dispatching an empty shard when a microbatch has fewer rows than devices."""
    import torch
    from laya.train import _forward  # type: ignore[import-untyped]  # SDK has no py.typed.

    executor = (model if parallel is None or
                batch["input_ids"].shape[0] < len(parallel.device_ids) else parallel)
    with torch.autocast(device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
        # The SDK's amp=True selects FP16. Its FP32 logits keep all losses and
        # their reductions outside this BF16 forward context.
        return _forward(executor, batch, device, False, False)


def training_stages(size: int, epochs: int, seed: int,
                    update_budget: int | None = None,
                    eval_at_updates: list[int] | None = None,
                    eval_every_updates: int | None = None,
                    row_groups: list[list[int]] | None = None,
                    batch_rows: int = 16,
                    full_passes: bool = False,
                    ) -> list[tuple[int, list[TrainingWindow]]]:
    """Full epochs or an exact budget of fixed-size optimizer updates.

    Legacy budgeted updates cross pass boundaries without dropping examples.
    Optional two-row groups use exact full passes, with an unpadded final window.
    Checkpoints are fixed in advance, not selected by development loss.
    """
    if (size < 1 or epochs < 1 or batch_rows < 1
            or (update_budget is not None and update_budget < 1)):
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
    if full_passes and row_groups is None and update_budget is not None:
        if update_budget != math.ceil(size / batch_rows) * epochs:
            raise ValueError("Full-pass update budget must include each unpadded epoch tail")
        exact: list[TrainingWindow] = []
        for data_pass in range(1, epochs + 1):
            order = list(range(size))
            rng.shuffle(order)
            exact.extend([[(data_pass, i) for i in order[start:start + batch_rows]]
                          for start in range(0, size, batch_rows)])
        cuts = sorted({update_budget // 2, update_budget} - {0})
        if eval_at_updates is not None:
            cuts = sorted({*eval_at_updates, update_budget})
        elif eval_every_updates is not None:
            cuts = sorted({*range(eval_every_updates, update_budget, eval_every_updates),
                           update_budget})
        return [(end, exact[start:end])
                for start, end in zip([0, *cuts[:-1]], cuts, strict=True)]
    if row_groups is not None:
        if (update_budget is None
                or batch_rows % 2
                or sorted(i for group in row_groups for i in group) != list(range(size))
                or any(len(group) not in (1, 2) for group in row_groups)
                or sum(len(group) == 1 for group in row_groups) > 1
                or update_budget != math.ceil(size / batch_rows) * epochs):
            raise ValueError("Grouped schedule requires exact full passes of all distinct rows")
        grouped_windows: list[TrainingWindow] = []
        for data_pass in range(1, epochs + 1):
            group_order = [group for group in row_groups if len(group) == 2]
            rng.shuffle(group_order)
            group_order.extend(group for group in row_groups if len(group) == 1)
            grouped_draws = [(data_pass, i) for group in group_order for i in group]
            grouped_windows.extend(grouped_draws[start:start + batch_rows]
                                   for start in range(0, len(grouped_draws), batch_rows))
        cuts = sorted({update_budget // 2, update_budget} - {0})
        if eval_at_updates is not None:
            cuts = sorted({*eval_at_updates, update_budget})
        elif eval_every_updates is not None:
            cuts = sorted({*range(eval_every_updates, update_budget, eval_every_updates),
                           update_budget})
        return [(end, grouped_windows[start:end])
                for start, end in zip([0, *cuts[:-1]], cuts, strict=True)]
    if update_budget is None:
        stages = []
        for epoch in range(1, epochs + 1):
            order = list(range(size))
            rng.shuffle(order)
            stages.append((epoch, [[(epoch, i) for i in order[start:start + batch_rows]]
                                   for start in range(0, size, batch_rows)]))
        return stages
    draws: TrainingWindow = []
    data_pass = 0
    while len(draws) < update_budget * batch_rows:
        data_pass += 1
        order = list(range(size))
        rng.shuffle(order)
        draws.extend((data_pass, i) for i in order)
    windows = [draws[i:i + batch_rows]
               for i in range(0, update_budget * batch_rows, batch_rows)]
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


def feedback_training_losses(
    logits: Any, target: Any, mask: Any, keys: list[list[str]],
    rows: list[dict[str, Any]], feedback_target: str,
    quality_mode: QualityMode | None, replay_objective: str = "soft-ce",
    label_smoothing: float = 0.0,
    component_weights: list[dict[str, float]] | None = None,
) -> Any:
    """Keep feedback supervision fixed while choosing the old-operation replay loss."""
    import torch

    replay = decision_loss(logits, target, mask, replay_objective)
    if component_weights is not None:
        return torch.stack([
            answer_first_loss(logits[i], keys[i], row["feedback"]["comparisons"], weight,
                              label_smoothing=label_smoothing)
            if "feedback" in row else weight["replay"] * replay[i]
            for i, (row, weight) in enumerate(zip(rows, component_weights, strict=True))])
    return torch.stack([
        (quality_pair_loss(logits[i], keys[i], row["feedback"]["comparisons"],
                           feedback_target, quality_mode, label_smoothing=label_smoothing)
         if quality_mode is not None else
         pair_loss(logits[i], keys[i], row["feedback"]["comparisons"], feedback_target))
        if "feedback" in row else replay[i]
        for i, row in enumerate(rows)])


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
    for key in ("feedback_target_states", "target_pairs", "cost_only_direction_pairs"):
        if "sampled_" + key in run:
            counts["train_" + key] = run["sampled_" + key]
    for key in ("nonzero_logit_gradient_rows", "feedback_nonzero_logit_gradient_rows",
                "replay_nonzero_logit_gradient_rows"):
        if key in run:
            counts["train_" + key] = run[key]
    for key, count in run.get("sampled_answer_first_components", {}).items():
        counts["train_answer_first_" + key] = count
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--compute-phase", help="Distinct phase in the original shared ledger")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--parallel-mode", choices=("legacy-dp", "single"), default="legacy-dp")
    parser.add_argument("--precision", choices=("float32", "bf16"), default="float32")
    parser.add_argument("--memory-fraction", type=float,
                        help="Optional allocator share; legacy-dp defaults to0.75, single to1")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--optimizer-updates", type=int,
                        help="Exact update budget with full effective-batch windows")
    parser.add_argument("--full-passes", action="store_true",
                        help="With explicit updates, retain every unpadded epoch tail")
    evaluation = parser.add_mutually_exclusive_group()
    evaluation.add_argument("--eval-at-updates", type=int, nargs="+")
    evaluation.add_argument("--eval-every-updates", type=int)
    parser.add_argument("--encoder-lr", type=float, default=2.5e-5)
    parser.add_argument("--head-lr", type=float, default=1e-4)
    parser.add_argument("--freeze-encoder", action="store_true")
    parser.add_argument("--micro-batch-size", type=int, choices=(1, 2, 4, 8, 16), default=4,
                        help="Maximum per-forward rows within an optimizer window")
    parser.add_argument("--effective-batch-rows", type=int, default=16)
    parser.add_argument("--length-bucketed-microbatches", action="store_true",
                        help="Group lengths within each update window, keeping pairs atomic")
    parser.add_argument("--log-every-updates", type=int, default=1,
                        help="Aggregate synchronized timing and progress over this many updates")
    parser.add_argument("--microbatch-padded-token-target", type=int,
                        help="Shrink long microbatches; an atomic pair can exceed this soft target")
    parser.add_argument("--eval-batch-size", type=int, default=1,
                        help="Native evaluation rows per forward; cached SDK encoding when >1")
    parser.add_argument("--cache-evaluation", action="store_true",
                        help="Reuse native evaluation tokens across checkpoints, including batch1")
    parser.add_argument("--eval-precision", choices=("float32", "bf16"), default="float32")
    parser.add_argument("--dev-data", type=Path,
                        help="Common development labels/inputs independent of the training recipe")
    parser.add_argument("--full-dev-data", type=Path,
                        help="Full fixed development panel, separate from the frequent fast panel")
    parser.add_argument("--full-dev-at", type=int, nargs="+",
                        help="Checkpoint-axis values for full dev; defaults to the final point")
    parser.add_argument("--aux-dev-data", type=Path,
                        help="Separate development domain evaluated at every declared point")
    parser.add_argument("--feedback-dev-data", type=Path,
                        help="Separate source-disjoint answer/delivery evaluation for all arms")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--head-max-len", type=int, default=384)
    parser.add_argument("--backend", choices=("native", "linear"), default="native")
    parser.add_argument("--objective", choices=("soft-ce", "set", "pair"), default="soft-ce")
    parser.add_argument("--feedback-target", choices=("answer", "delivery"),
                        help="Pair objective only; both targets use the same reviewed pair pool")
    parser.add_argument("--pair-supervision", default="legacy-direction",
                        choices=("legacy-direction", *QUALITY_MODES, "answer-first"),
                        help="Quality controls use explicit pre-cost judgments; legacy unchanged")
    parser.add_argument("--pair-label-smoothing", type=float, default=0.0,
                        help="Quality-mode training targets only; ties stay0.5, unknowns masked")
    parser.add_argument("--replay-weight", type=float, default=0.25,
                        help="Relative loss mass of old-operation replay under the pair objective")
    parser.add_argument("--pair-mass-mode", choices=("normalized-total", "component-sum"),
                        help="Historical default: normalized total; answer-first: component sum")
    parser.add_argument("--replay-objective", choices=("soft-ce", "set"), default="soft-ce",
                        help="Pair replay only: target CE or likelihood of the accepted set")
    parser.add_argument("--task", choices=("bounded_reader", "memory_operation",
                                           "instruction_applicability", "mixed_retrieval"),
                        default="bounded_reader", help="Use task-specific offline decision metrics")
    parser.add_argument("--mixture", type=Path,
                        help="Component loss masses for mixed_retrieval; draws stay uniform")
    parser.add_argument("--mixture-loss-scale", type=float, default=1.0,
                        help="Multiply normalized component masses, e.g.1.25 for task+0.25 replay")
    parser.add_argument("--conditional-pairs", type=Path,
                        help="Known disjoint pairs kept in two-row microbatches over full passes")
    parser.add_argument("--conditional-loss-weight", type=float, default=0.0,
                        help="Relative change-pair loss; stable pairs retain unit supervision")
    parser.add_argument("--operation-state", choices=(
                            "full", "mechanical", "shared", "shared_request_text",
                            "shared_actions", "shared_actions_request_text",
                            "compact_actions", "compact_actions_request_text"),
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
    parser.add_argument("--reuse-training-tokens", action="store_true",
                        help="Reuse SDK tokens across audit, preparation and option permutation")
    parser.add_argument("--gradient-checkpointing", action="store_true",
                        help="Recompute encoder activations during backward to reduce memory")
    parser.add_argument("--scheduler", choices=("legacy-cosine", "warmup-cosine"),
                        default="legacy-cosine")
    parser.add_argument("--warmup-fraction", type=float, default=0.03)
    parser.add_argument("--warmup-max-updates", type=int, default=200)
    parser.add_argument("--lr-floor-ratio", type=float, default=0.1)
    parser.add_argument("--save-training-state-every", type=int, default=0,
                        help="Save FP32/optimizer/RNG/sampler state every N updates and stage end")
    parser.add_argument("--resume-training-state", type=Path,
                        help="Resume a local training-state.pt into a new output directory")
    parser.add_argument("--stop-after-updates", type=int,
                        help="Explicit update-boundary interruption with recovery state")
    args = parser.parse_args()
    if (not 0 <= args.warmup_fraction < 1 or args.warmup_max_updates < 0
            or not 0 <= args.lr_floor_ratio <= 1 or args.save_training_state_every < 0
            or (args.stop_after_updates is not None and args.stop_after_updates < 1)):
        parser.error("Invalid warmup, recovery interval, interruption point or LR floor")
    if args.log_every_updates < 1:
        parser.error("Log interval must be positive")
    if args.microbatch_padded_token_target is not None and (
            args.microbatch_padded_token_target < 1 or not args.length_bucketed_microbatches):
        parser.error("Positive microbatch token target requires length grouping")
    batched_evaluation = args.cache_evaluation or args.eval_batch_size != 1
    if args.eval_batch_size < 1 or (batched_evaluation and args.backend != "native"):
        parser.error("Batched/cached evaluation requires native backend and positive batch size")
    if args.eval_precision != "float32" and not batched_evaluation:
        parser.error("Explicit BF16 evaluation requires batched/cached evaluation")
    if args.precision == "bf16" and args.parallel_mode != "single":
        parser.error("BF16 uses the single-device path; legacy DataParallel remains FP32")
    if args.memory_fraction is not None and not 0 < args.memory_fraction <= 1:
        parser.error("Allocator fraction must be in (0,1]")
    if (args.objective == "pair") != (args.feedback_target is not None):
        parser.error("Pair training requires --feedback-target; CE does not use it")
    if args.objective == "pair" and (args.task != "memory_operation"
                                    or not 0 < args.replay_weight < float("inf")):
        parser.error("Pair feedback uses memory_operation and a positive finite replay weight")
    if args.objective == "pair" and args.optimizer_updates is None:
        parser.error("Pair feedback requires an explicit matched optimizer-update budget")
    if args.replay_objective != "soft-ce" and args.objective != "pair":
        parser.error("--replay-objective applies only to pair training")
    if args.pair_supervision != "legacy-direction" and (
            args.objective != "pair" or args.feedback_dev_data is None):
        parser.error("Quality supervision requires pair objective and fixed feedback development")
    answer_first = args.pair_supervision == "answer-first"
    if answer_first and (args.feedback_target != "answer" or args.replay_objective != "set"):
        parser.error("Answer-first uses --feedback-target answer and --replay-objective set")
    quality_mode = (cast(QualityMode, args.pair_supervision)
                    if args.pair_supervision in QUALITY_MODES else None)
    quality_supervised = quality_mode is not None or answer_first
    mass_mode = args.pair_mass_mode or ("component-sum" if answer_first else "normalized-total")
    if args.pair_mass_mode is not None and not quality_supervised:
        parser.error("--pair-mass-mode applies to explicit quality supervision")
    if answer_first and mass_mode != "component-sum":
        parser.error("Answer-first keeps the declared component sum without total normalization")
    if not 0 <= args.pair_label_smoothing < .5:
        parser.error("Pair label smoothing must be finite and in [0,0.5)")
    if args.pair_label_smoothing and not quality_supervised:
        parser.error("Pair label smoothing requires an explicit quality-supervision mode")
    if (args.task == "mixed_retrieval") != (args.mixture is not None):
        parser.error("mixed_retrieval requires --mixture, and other tasks do not use it")
    if args.mixture is not None and args.optimizer_updates is None:
        parser.error("The mixed recipe requires an explicit matched optimizer-update budget")
    if (not math.isfinite(args.mixture_loss_scale) or args.mixture_loss_scale <= 0
            or (args.mixture_loss_scale != 1.0 and args.mixture is None)):
        parser.error("Mixture loss scale must be positive finite and requires a mixture")
    if args.conditional_pairs is not None and (
            args.task not in {"instruction_applicability", "mixed_retrieval"}
            or args.objective == "pair" or args.micro_batch_size % 2
            or args.effective_batch_rows % 2
            or args.optimizer_updates is None):
        parser.error("Conditional grouping uses unit supervision, even batches and exact updates")
    if (not math.isfinite(args.conditional_loss_weight) or args.conditional_loss_weight < 0
            or (args.conditional_loss_weight and args.conditional_pairs is None)):
        parser.error("Conditional loss weight must be nonnegative finite and requires pairs")
    if any(not math.isfinite(lr) or lr <= 0 for lr in (args.encoder_lr, args.head_lr)):
        parser.error("Learning rates must be positive and finite")
    if args.feedback_dev_data is not None and args.task not in {
            "memory_operation", "mixed_retrieval"}:
        parser.error("Feedback development evaluates memory-operation inputs")
    try:
        training_stages(1, args.epochs, args.seed, args.optimizer_updates,
                        args.eval_at_updates, args.eval_every_updates,
                        batch_rows=args.effective_batch_rows)
    except ValueError as error:
        parser.error(str(error))
    import torch
    from laya.common import collate_items  # type: ignore[import-untyped]  # SDK has no py.typed.
    from laya.train import (
        draw_option_order,
        encode_item,
        items_from_rows,
        save_checkpoint,
    )

    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = torch.device(args.device)
    if device.type != "cuda":
        parser.error("Training requires an allocated CUDA device")
    primary = device.index if device.index is not None else torch.cuda.current_device()
    device = torch.device("cuda", primary)
    device_ids = ([primary] if args.parallel_mode == "single" else
                  [primary, *[i for i in range(torch.cuda.device_count()) if i != primary]])
    memory_fraction = args.memory_fraction
    if memory_fraction is None:
        memory_fraction = .75 if args.parallel_mode == "legacy-dp" else 1.0
    for index in device_ids:
        torch.cuda.set_per_process_memory_fraction(memory_fraction, index)
        torch.cuda.reset_peak_memory_stats(index)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    raw_train = read_jsonl(args.data / "train.jsonl")
    train = [r for r in raw_train if r["gold"] or (args.objective == "pair" and "feedback" in r)]
    dev_path = args.dev_data or args.data / "dev.jsonl"
    dev = read_jsonl(dev_path)
    full_dev = read_jsonl(args.full_dev_data) if args.full_dev_data is not None else []
    aux_dev = read_jsonl(args.aux_dev_data) if args.aux_dev_data is not None else []
    feedback_dev = read_jsonl(args.feedback_dev_data) if args.feedback_dev_data is not None else []
    if quality_supervised:
        validate_quality_pool([*train, *feedback_dev])
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
    elif args.task == "instruction_applicability":
        from retrieval_mixture import project_applicability_row

        train = [project_applicability_row(row, args.operation_state) for row in train]
        dev = [project_applicability_row(row, args.operation_state) for row in dev]
    if full_dev:
        if args.task == "memory_operation":
            full_dev = [project_operation_payload(row, args.operation_state) for row in full_dev]
        elif args.task == "mixed_retrieval":
            full_dev = [project_mixed_row(row, args.operation_state) for row in full_dev]
        elif args.task == "instruction_applicability":
            full_dev = [project_applicability_row(row, args.operation_state) for row in full_dev]
    if aux_dev:
        if args.task == "memory_operation":
            aux_dev = [project_operation_payload(row, args.operation_state) for row in aux_dev]
        elif args.task == "mixed_retrieval":
            aux_dev = [project_mixed_row(row, args.operation_state) for row in aux_dev]
        elif args.task == "instruction_applicability":
            aux_dev = [project_applicability_row(row, args.operation_state) for row in aux_dev]
    mixture = normalized_mixture(read_json(args.mixture)) if args.mixture is not None else None
    weights = mixture_event_weights(train, mixture) if mixture is not None else event_weights(train)
    if mixture is not None:
        weights = [weight * args.mixture_loss_scale for weight in weights]
    component_weights = answer_first_weights(train, args.replay_weight) if answer_first else None
    if answer_first:
        weights = [1.0] * len(train)  # Component weights already include the full loss masses.
    elif quality_mode is not None:
        weights = quality_event_weights(train, args.feedback_target, quality_mode,
                                        args.replay_weight,
                                        normalize_total=mass_mode == "normalized-total")
    elif args.objective == "pair":
        # Normalize each component by family/event, then apply the declared replay mass.
        weighted_rows = [{**row, "metadata": {**row["metadata"],
            "component": "feedback" if "feedback" in row else "operation_replay"}}
            for row in train]
        weights = mixture_event_weights(weighted_rows, {
            "feedback": 1.0, "operation_replay": args.replay_weight})
    row_groups = None
    change_targets: dict[tuple[int, ...], tuple[float, float]] = {}
    if args.conditional_pairs is not None:
        conditional_pairs = read_jsonl(args.conditional_pairs)
        row_groups = conditional_training_groups(
            train, conditional_pairs, args.seed)
        if args.conditional_loss_weight:
            change_targets = conditional_change_targets(train, conditional_pairs)
            if not change_targets:
                raise ValueError("Relative condition loss requires supported training change pairs")
    stages = training_stages(len(train), args.epochs, args.seed, args.optimizer_updates,
                             args.eval_at_updates, args.eval_every_updates, row_groups,
                             args.effective_batch_rows, args.full_passes)
    full_dev_at = args.full_dev_at or [stages[-1][0]]
    if args.full_dev_at is not None and (args.full_dev_data is None
            or not set(full_dev_at) <= {step for step, _ in stages}):
        parser.error("Full development points must be declared checkpoints with --full-dev-data")
    axis = "epoch" if args.optimizer_updates is None else "optimizer_updates"
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "base_checkpoint": str(args.checkpoint.resolve()), "seed": args.seed,
           "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
           "device_ids": device_ids, "device": str(device),
           "devices": [{"index": i, "name": torch.cuda.get_device_name(i),
                        "total_bytes": torch.cuda.get_device_properties(i).total_memory}
                       for i in device_ids],
           "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
           "precision": args.precision, "parameter_precision": "float32",
           "parallel_mode": args.parallel_mode, "memory_fraction": memory_fraction,
           "tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
           "tf32_cudnn": torch.backends.cudnn.allow_tf32,
           "reference_compile": False,
           "gradient_checkpointing": args.gradient_checkpointing,
           "scheduler": args.scheduler, "warmup_fraction": args.warmup_fraction,
           "warmup_max_updates": args.warmup_max_updates, "lr_floor_ratio": args.lr_floor_ratio,
           "save_training_state_every": args.save_training_state_every,
           "resume_training_state": (str(args.resume_training_state.resolve())
                                     if args.resume_training_state else None),
           "forward_count_scope": "Logical model calls; activation recomputation is in time cost",
           "backend": args.backend, "task": args.task, "operation_state": args.operation_state,
           "epochs": args.epochs if args.optimizer_updates is None else None,
           "planned_optimizer_updates": sum(len(windows) for _, windows in stages),
           "planned_sequence_rows": sum(len(window) for _, windows in stages for window in windows),
           "checkpoint_axis": axis, "dev_source": str(dev_path.resolve()),
           "full_passes": args.full_passes,
           "full_dev_source": str(args.full_dev_data.resolve()) if args.full_dev_data else None,
           "full_dev_states": len(full_dev), "full_dev_at": full_dev_at if full_dev else [],
           "aux_dev_source": str(args.aux_dev_data.resolve()) if args.aux_dev_data else None,
           "aux_dev_states": len(aux_dev),
           "batch_size": args.micro_batch_size,
           "eval_batch_size": args.eval_batch_size,
           "cache_evaluation": batched_evaluation, "eval_precision": args.eval_precision,
           "effective_batch_rows": args.effective_batch_rows,
           "length_bucketed_microbatches": args.length_bucketed_microbatches,
           "log_every_updates": args.log_every_updates,
           "microbatch_padded_token_target": args.microbatch_padded_token_target,
           "gradient_accumulation": math.ceil(args.effective_batch_rows / args.micro_batch_size),
           "gradient_accumulation_scope": "Nominal minimum; actual tail/token batches vary",
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
           "train_batch_attempts": 0, "train_offered_rows": 0, "train_offered_tokens": 0,
           "train_padded_input_tokens": 0}
    if mixture is not None:
        run.update(loss_weighting="declared component mass, then family and event",
                   mixture=mixture, mixture_loss_scale=args.mixture_loss_scale,
                   sampling="uniform shuffled passes over labelled rows",
                   sampled_component_rows={}, sampled_task_rows={},
                   sampled_component_input_tokens={})
    if row_groups is not None:
        run.update(conditional_pairs=str(args.conditional_pairs.resolve()),
                   sampling="shuffled two-row groups; each unit once per full pass; no padding",
                   planned_sequence_rows=sum(len(w) for _, windows in stages for w in windows),
                   conditional_loss_weight=args.conditional_loss_weight)
        if args.conditional_loss_weight:
            run.update(conditional_change_pairs=len(change_targets), conditional_pair_draws=0,
                       conditional_pair_weighting="mean-one family weights over change pairs",
                       conditional_loss_normalization="weighted change-pair sum divided by actual "
                           "change-pair count per optimizer window; zero in empty windows",
                       loss_reporting="weighted_loss_mean retains unit loss; relative contribution "
                           "is separately reported per optimizer window")
        write_json(args.output / "training-windows.json", stages)
    if args.objective == "pair":
        run.update(feedback_target=args.feedback_target, replay_weight=args.replay_weight,
                   feedback_pool=feedback_counts(train, args.feedback_target),
                   sampling="uniform shuffled passes over retained feedback and old replay rows",
                   loss_weighting="feedback:replay mass 1:alpha, then family/event; "
                                  "mean directional pairs within each state",
                   tie_unknown_sampling="Retained as zero-direction states in both arms",
                   sampled_feedback_states=0, sampled_replay_states=0,
                   sampled_directional_pairs=0, sampled_tie_pairs=0, sampled_unknown_pairs=0)
    if quality_supervised:
        run.update(pair_supervision=args.pair_supervision,
            feedback_pool=(answer_first_counts(train) if answer_first else
                           quality_counts(train, args.feedback_target,
                                          cast(QualityMode, quality_mode))),
            loss_weighting="known pairs within state; eligible family/event within fixed "
                           "feedback/replay masses; zero-target rows kept with zero weight",
            selection_rule="pure_quality[target].directional.family_macro_state_pair_accuracy; "
                           "highest, earliest tie, update0 eligible; cost and tie fit separate",
            tie_unknown_sampling="All rows retained; quality-tie uses0.5; quality-cost uses0.5 "
                                 "unless cost dominance exists; quality-direction skips ties. "
                                 "Unknown-target states have zero loss weight",
            sampled_feedback_target_states=0, sampled_target_pairs=0,
            sampled_cost_only_direction_pairs=0,
            nonzero_logit_gradient_rows=0, feedback_nonzero_logit_gradient_rows=0,
            replay_nonzero_logit_gradient_rows=0,
            gradient_count_scope="Nonzero gradient at per-forward output logits, before parameter "
                                 "clipping/optimizer momentum; not per-parameter attribution")
        if args.pair_label_smoothing:
            run["pair_label_smoothing"] = args.pair_label_smoothing
        if mass_mode == "component-sum":
            run["pair_mass_mode"] = mass_mode
    if answer_first:
        run.update(answer_first_component_masses={**ANSWER_FIRST_MASSES,
                                                 "replay": args.replay_weight},
            sampled_answer_first_components={},
            loss_weighting="0.80 answer-known + 0.20 delivery-answer-unknown + alpha replay; "
                "each component normalized by eligible family/event; no total rescale",
            tie_unknown_sampling="Pair masks within each state; known answer tie stays0.5; "
                "delivery auxiliary only when answer unknown; both unknown have zero gradient",
            selection_rule="Offline pair metrics nominate at most two candidates; update0 and "
                "simple baseline included in actual full-menu fixed-dev answer-success selection. "
                "Earliest quality tie; unexecuted choices unknown; autonomous Host separate.")
    if args.objective == "pair" and args.replay_objective == "set":
        run.update(replay_objective="set",
            replay_target_scope="Positive old-operation targets form an accepted set; target "
                                "magnitudes are not preferences within that set. Feedback "
                                "targets, row sampling and replay loss mass are unchanged.")
    write_json(args.output / "run.json", run)
    write_json(args.output / "training-plan.json", stages)
    decision: NativeDecision
    evaluation_counts: dict[str, Counter[str]] = defaultdict(Counter)
    stage_seconds: Counter[str] = Counter()
    segment_start_counts: dict[str, int] = {}

    def synchronize() -> None:
        for index in device_ids:
            torch.cuda.synchronize(index)

    def save_model(config: dict[str, Any], destination: Path) -> None:
        synchronize()
        save_started = time.perf_counter()
        checkpoint_writer(model, tok, config, str(destination))
        stage_seconds["save"] += time.perf_counter() - save_started

    try:
        if args.backend == "linear":
            from linear_reader_classifier import LinearDecision, save_linear_checkpoint

            decision = LinearDecision(args.checkpoint, args.max_len, args.head_max_len)
            checkpoint_writer = save_linear_checkpoint
        else:
            decision = NativeDecision(args.checkpoint, args.max_len, args.head_max_len,
                                      device=str(device))
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
        if args.full_dev_data is not None:
            evaluation_rows["full-dev"] = full_dev
        if args.aux_dev_data is not None:
            evaluation_rows["aux-dev"] = aux_dev
        if args.feedback_dev_data is not None:
            evaluation_rows["feedback-dev"] = feedback_dev
        codec_rows = ([encoding_row(row) for row in train]
                      if args.objective == "pair" else train)
        training_tok = tok
        if args.reuse_training_tokens:
            from training_token_reuse import prepare_training_rows

            train_lengths, items, skipped, encoded, training_tok = prepare_training_rows(
                tok, codec_rows, args.max_len, args.head_max_len)
            lengths = {"train": train_lengths, **{
                split: audit(rows, tok, args.max_len, args.head_max_len)
                for split, rows in evaluation_rows.items() if split != "train"}}
            run["training_token_reuse"] = training_tok.counters
        else:
            lengths = {split: audit(rows, tok, args.max_len, args.head_max_len)
                       for split, rows in evaluation_rows.items()}
        write_json(args.output / "lengths.json", lengths)
        if any(r["state_tokens_dropped"] or r["head_tokens_dropped"]
               for records in lengths.values() for r in records):
            raise ValueError("Complete-input audit failed")
        if not args.reuse_training_tokens:
            items, skipped = items_from_rows(tok, codec_rows, args.max_len, args.head_max_len)
            encoded = [encode_item(tok, item, args.max_len, args.head_max_len) for item in items]
        if skipped or len(items) != len(train):
            raise ValueError(f"Invalid training items: {skipped}")
        encoded_lengths = [len(item["ids"]) for item in encoded]
        option_orders: list[list[int] | None] = [None] * len(items)
        write_json(args.output / "sampling.json", [
            {"event_id": r["metadata"]["event_id"], "family": r["metadata"]["family"],
             "source_row": r["metadata"]["row"], "weight": w,
             **({"answer_first_component_weights": component_weights[index]}
                if component_weights is not None else {}),
             **({"component": r["metadata"]["component"], "task": r["metadata"]["task"]}
                if mixture is not None else {})}
            for index, (r, w) in enumerate(zip(train, weights, strict=True))])
        decision.device = device
        model.to(decision.device)
        parallel = (torch.nn.DataParallel(model, device_ids=device_ids)
                    if args.parallel_mode == "legacy-dp" else None)
        run["attention_backend"] = model.encoder.config._attn_implementation
        run["encoder_max_position_embeddings"] = model.encoder.config.max_position_embeddings
        run["parameter_dtypes"] = dict(Counter(str(p.dtype) for p in model.parameters()))
        stage_seconds["prepare"] = time.perf_counter() - started
        parameters = dict(model.named_parameters())
        probes = {"encoder": next(n for n in parameters if n.startswith("encoder.")),
                  "head": next(n for n in parameters if not n.startswith("encoder."))}
        before = {key: parameters[name].detach().cpu().clone() for key, name in probes.items()}
        optimizer = torch.optim.AdamW(optimizer_groups(
            model, args.encoder_lr, args.head_lr, args.freeze_encoder), weight_decay=0.01)
        steps = run["planned_optimizer_updates"]
        scheduler = make_scheduler(optimizer, steps, warmup_fraction=args.warmup_fraction,
            warmup_max_updates=args.warmup_max_updates, floor_ratio=args.lr_floor_ratio,
            mode=args.scheduler)
        # Ordinary version paths and row IDs identify the fixed data; no digest gate.
        recipe_fields = ("data", "checkpoint", "seed", "epochs", "optimizer_updates",
            "task", "operation_state", "objective", "feedback_target", "pair_supervision",
            "pair_label_smoothing", "replay_weight", "replay_objective", "pair_mass_mode",
            "mixture", "mixture_loss_scale", "conditional_pairs", "conditional_loss_weight",
            "encoder_lr", "head_lr", "freeze_encoder", "shuffle_options", "precision",
            "parallel_mode", "micro_batch_size", "effective_batch_rows",
            "length_bucketed_microbatches", "microbatch_padded_token_target", "max_len",
            "head_max_len", "gradient_checkpointing", "scheduler", "warmup_fraction",
            "warmup_max_updates", "lr_floor_ratio", "full_passes", "full_dev_data", "full_dev_at",
            "aux_dev_data")
        contract = {"recipe": {key: str(value.resolve()) if isinstance(value, Path) else value
                    for key in recipe_fields if (value := getattr(args, key)) is not None},
                    "data_event_ids": [row["metadata"]["event_id"] for row in train],
                    "weights": weights, "stages": stages,
                    "dev_source": str(dev_path.resolve())}
        if args.reuse_training_tokens:
            contract["recipe"]["reuse_training_tokens"] = True
        resumed = (restore_training_state(args.resume_training_state, model, optimizer, scheduler,
                                          contract=contract)
                   if args.resume_training_state else None)
        if resumed is not None:
            for key, value in resumed["run"].items():
                if (key.startswith(("train_", "sampled_")) or key in {
                        "optimizer_updates", "data_passes_started", "conditional_pair_draws",
                        "nonzero_logit_gradient_rows", "feedback_nonzero_logit_gradient_rows",
                        "replay_nonzero_logit_gradient_rows"}):
                    run[key] = value
            segment_start_counts = compute_counts(run, {})
            run["resumed_at_update"] = run["optimizer_updates"]

        evaluation_cache: dict[str, Any] = {}

        def evaluate(epoch: int, split: str = "dev") -> dict[str, Any]:
            synchronize()
            eval_started = time.perf_counter()
            model.eval()
            predictions = []
            rows = evaluation_rows[split]
            if batched_evaluation:
                previous_counts = dict(decision.counters)
                if split not in evaluation_cache:
                    evaluation_cache[split] = decision.prepare_batch(rows)
                predictions = decision.predict_prepared(
                    evaluation_cache[split], args.eval_batch_size, precision=args.eval_precision)
                evaluation_counts[split].update({
                    k: v - previous_counts[k] for k, v in decision.counters.items()})
                destination = args.output / split / str(epoch) / "predictions.jsonl"
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("w") as stream:
                    for index, prediction in enumerate(predictions):
                        stream.write(json.dumps({"row": index, **prediction}) + "\n")
            else:
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
                if quality_supervised:
                    result["pure_quality"] = {target: score_quality_feedback(
                        rows, predictions, target, "quality-tie")
                        for target in ("answer", "delivery")}
                    result["quality_cost"] = {target: score_quality_feedback(
                        rows, predictions, target, "quality-cost")
                        for target in ("answer", "delivery")}
                if quality_supervised and mass_mode == "component-sum":
                    result["answer_first"] = score_answer_first(rows, predictions)
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
            stage_seconds["evaluation"] += time.perf_counter() - eval_started
            return result

        history = (resumed["history"] if resumed is not None else
                   [] if args.skip_initial_dev else [{axis: 0, "dev": evaluate(0)}])
        if args.feedback_dev_data is not None and not args.skip_initial_dev and resumed is None:
            history[0]["feedback-dev"] = evaluate(0, "feedback-dev")
        if args.aux_dev_data is not None and not args.skip_initial_dev and resumed is None:
            history[0]["aux-dev"] = evaluate(0, "aux-dev")
        if args.evaluate_train and not args.train_eval_final_only and resumed is None:
            if not history:
                history.append({axis: 0})
            history[0]["train"] = evaluate(0, "train")
        write_json(args.output / "history.json", history)
        option_rng = random.Random(args.seed + 10000)  # noqa: S311 -- independent of row order
        encoded_pass = 0
        if resumed is not None:
            option_rng.setstate(resumed["option_rng"])
            encoded_pass, option_orders = resumed["encoded_pass"], resumed["option_orders"]
            encoded = [encode_item(training_tok, item, args.max_len, args.head_max_len,
                                   option_order=order)
                       for item, order in zip(items, option_orders, strict=True)]
            encoded_lengths = [len(item["ids"]) for item in encoded]
            previous = Path(resumed["output"])
            # Reuse completed evaluation points without replay or writing into old runs.
            for point in history:
                for split in evaluation_rows:
                    source = previous / split / str(point[axis])
                    if source.exists():
                        target = args.output / split / str(point[axis])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.symlink_to(source.resolve(), target_is_directory=True)
            for name in ("option-orders", "checkpoints"):
                if (previous / name).exists():
                    (args.output / name).mkdir(exist_ok=True)
                    for source in (previous / name).iterdir():
                        (args.output / name / source.name).symlink_to(
                            source.resolve(), target_is_directory=source.is_dir())

        def save_recovery(stage_index: int, window_index: int, stage_loss: Any,
                          stage_offered: int, condition_sum: float) -> None:
            synchronize()
            saving = time.perf_counter()
            save_training_state(args.output / "recovery/training-state.pt", model,
                optimizer, scheduler, contract=contract, progress={
                    "stage_index": stage_index, "window_index": window_index,
                    "stage_loss": float(stage_loss), "stage_offered": stage_offered,
                    "condition_sum": condition_sum, "run": run, "history": history,
                    "encoded_pass": encoded_pass, "option_orders": option_orders,
                    "option_rng": option_rng.getstate(), "output": str(args.output.resolve())})
            stage_seconds["save"] += time.perf_counter() - saving

        for stage_index, (checkpoint_step, windows) in enumerate(stages):
            if resumed is not None and stage_index < resumed["stage_index"]:
                continue
            partial = (resumed if resumed is not None and stage_index == resumed["stage_index"]
                       else {})
            training_mode(model, args.freeze_encoder)
            loss_total = torch.tensor(partial.get("stage_loss", 0.0), device=device)
            offered = partial.get("stage_offered", 0)
            condition_loss_total = partial.get("condition_sum", 0.0)
            profile_open = False
            for window_index in range(partial.get("window_index", 0), len(windows)):
                window = windows[window_index]
                if not profile_open:
                    synchronize()
                    update_started, update_cpu = time.perf_counter(), time.process_time()
                    prior_tokens = run["train_input_tokens"]
                    prior_padded_tokens = run["train_padded_input_tokens"]
                    prior_rows = run["train_sequence_rows"]
                    prior_updates = run["optimizer_updates"]
                    profile_open = True
                denominator = len(window)
                optimizer.zero_grad(set_to_none=True)
                microbatches = training_microbatches(
                    window, args.micro_batch_size,
                    encoded_lengths if args.length_bucketed_microbatches else None,
                    paired=row_groups is not None,
                    padded_token_target=args.microbatch_padded_token_target)
                condition_pair_count = sum(
                    tuple(i for _, i in micro[start:start + 2]) in change_targets
                    for micro in microbatches for start in range(0, len(micro), 2))
                for microbatch in microbatches:
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
                                encoded = [
                                    encode_item(training_tok, item, args.max_len,
                                                args.head_max_len, option_order=order)
                                    for item, order in zip(items, option_orders, strict=True)]
                                encoded_lengths = [len(item["ids"]) for item in encoded]
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
                    logits = training_forward(model, parallel, batch, decision.device,
                                              args.precision)
                    mask = batch["marker_mask"].to(decision.device)
                    target = batch["target"].to(decision.device)
                    if args.objective == "pair":
                        batch_rows = [train[i] for i in indices]
                        ce = feedback_training_losses(
                            logits, target, mask, batch_keys, batch_rows, args.feedback_target,
                            quality_mode, args.replay_objective, args.pair_label_smoothing,
                            [component_weights[i] for i in indices]
                            if component_weights is not None else None)
                        counts: dict[str, Any] = (
                                  answer_first_counts(batch_rows) if answer_first else
                                  quality_counts(batch_rows, args.feedback_target, quality_mode)
                                  if quality_mode is not None else
                                  feedback_counts(batch_rows, args.feedback_target))
                        for name in ("feedback_states", "replay_states", "directional_pairs",
                                     "tie_pairs", "unknown_pairs"):
                            run["sampled_" + name] += counts.get(name, 0)
                        if quality_supervised:
                            run["sampled_feedback_target_states"] += counts.get(
                                "states_with_targets", 0)
                            run["sampled_target_pairs"] += counts.get("target_pairs", 0)
                            run["sampled_cost_only_direction_pairs"] += counts.get(
                                "cost_only_direction_pairs", 0)
                        if answer_first:
                            sampled = run["sampled_answer_first_components"]
                            for name, support in counts["components"].items():
                                for field in ("states", "pairs", "directional_pairs", "tie_pairs"):
                                    key = name + "_" + field
                                    sampled[key] = sampled.get(key, 0) + support.get(field, 0)
                    else:
                        ce = decision_loss(logits, target, mask, args.objective)
                    weighted = ce * torch.tensor([weights[i] for i in indices],
                                                  device=decision.device)
                    loss = weighted.sum() / denominator
                    for pair_start in range(0, len(indices), 2):
                        pair_indices = indices[pair_start:pair_start + 2]
                        condition_target = change_targets.get(tuple(pair_indices))
                        if condition_target is None:
                            continue
                        direction, pair_weight = condition_target
                        relative = conditional_relative_loss(
                            logits[pair_start:pair_start + 2],
                            batch_keys[pair_start:pair_start + 2], direction)
                        contribution = (args.conditional_loss_weight * pair_weight * relative
                                        / condition_pair_count)
                        loss = loss + contribution
                        condition_loss_total += float(contribution.detach())
                        run["conditional_pair_draws"] += 1
                        with (args.output / "conditional-losses.jsonl").open("a") as stream:
                            stream.write(json.dumps({
                                "update": run["optimizer_updates"] + 1,
                                "events": [train[i]["metadata"]["event_id"] for i in pair_indices],
                                "data_pass": encoded_pass, "direction": direction,
                                "family_weight": pair_weight,
                                "window_change_pairs": condition_pair_count,
                                "relative_loss": float(relative.detach()),
                                "optimizer_contribution": float(contribution.detach()),
                            }) + "\n")
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite decision loss")
                    if quality_supervised:
                        logits.retain_grad()
                    loss.backward()
                    if quality_supervised:
                        nonzero = logits.grad.detach().ne(0).any(dim=1).tolist()
                        for index, active in zip(indices, nonzero, strict=True):
                            run["nonzero_logit_gradient_rows"] += int(active)
                            component = "feedback" if "feedback" in train[index] else "replay"
                            run[component + "_nonzero_logit_gradient_rows"] += int(active)
                    loss_total += weighted.sum().detach()
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
                    run["train_padded_input_tokens"] += batch["attention_mask"].numel()
                    run["train_batch_forwards"] += 1
                    run["train_device_forwards"] += min(len(indices), len(device_ids))
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                run["optimizer_updates"] += 1
                recovery_due = (args.save_training_state_every > 0
                    and run["optimizer_updates"] % args.save_training_state_every == 0)
                interrupt_due = run["optimizer_updates"] == args.stop_after_updates
                if ((window_index + 1) % args.log_every_updates == 0
                        or window_index == len(windows) - 1 or recovery_due or interrupt_due):
                    synchronize()
                    update_seconds = time.perf_counter() - update_started
                    stage_seconds["training"] += update_seconds
                    with (args.output / "update-profile.jsonl").open("a") as stream:
                        stream.write(json.dumps({
                            "update": run["optimizer_updates"],
                            "first_update": prior_updates + 1,
                            "updates": run["optimizer_updates"] - prior_updates,
                            "rows": run["train_sequence_rows"] - prior_rows,
                            "input_tokens": run["train_input_tokens"] - prior_tokens,
                            "padded_input_tokens": (run["train_padded_input_tokens"]
                                                    - prior_padded_tokens),
                            "wall_seconds": update_seconds,
                            "cpu_seconds": time.process_time() - update_cpu,
                        }) + "\n")
                    write_json(args.output / "run.json", run)
                    print(json.dumps({"data_pass": encoded_pass,
                                      "updates": run["optimizer_updates"]}), flush=True)
                    profile_open = False
                if recovery_due or interrupt_due:
                    save_recovery(stage_index, window_index + 1, loss_total,
                                  offered, condition_loss_total)
                if interrupt_due:
                    raise TrainingInterruption()
            loss_mean = float(loss_total) / offered
            history.append({axis: checkpoint_step, "weighted_loss_mean": loss_mean,
                            "dev": evaluate(checkpoint_step)})
            if args.conditional_loss_weight:
                history[-1]["conditional_loss_optimizer_mean"] = condition_loss_total / len(windows)
            if args.feedback_dev_data is not None:
                history[-1]["feedback-dev"] = evaluate(checkpoint_step, "feedback-dev")
            if args.full_dev_data is not None and checkpoint_step in full_dev_at:
                history[-1]["full-dev"] = evaluate(checkpoint_step, "full-dev")
            if args.aux_dev_data is not None:
                history[-1]["aux-dev"] = evaluate(checkpoint_step, "aux-dev")
            if args.objective == "soft-ce":
                history[-1]["weighted_ce_mean"] = loss_mean
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
            save_model(config, destination)
            if args.save_training_state_every:
                save_recovery(stage_index + 1, 0, 0.0, 0, 0.0)
            resumed = None
        changes = {key: {"parameter": name, "changed_elements": int((
            parameters[name].detach().cpu() != before[key]).sum())} for key, name in probes.items()}
        write_json(args.output / "parameter-probes.json", changes)
        config = {**decision.config, "max_len": args.max_len, "head_max_len": args.head_max_len,
                  "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {}, "fine_tuned": True,
                  "training": {"milai_reader": {**run, axis: stages[-1][0]}}}
        save_model(config, args.output / "checkpoint")
        run["status"] = "COMPLETED"
    except TrainingInterruption:
        run["status"] = "INTERRUPTED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        synchronize()
        segment_counts = compute_counts(run, evaluation_counts)
        for key, value in segment_start_counts.items():
            segment_counts[key] -= value
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **segment_counts}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "stage_wall_seconds": dict(stage_seconds),
            "gpu_hours": measures["wall_seconds"] * len(device_ids) / 3600,
            "peak_cuda_allocated_bytes": [torch.cuda.max_memory_allocated(i) for i in device_ids],
            "peak_cuda_reserved_bytes": [torch.cuda.max_memory_reserved(i) for i in device_ids],
            "final_cuda_free_total_bytes": [list(torch.cuda.mem_get_info(i)) for i in device_ids],
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
