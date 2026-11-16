"""Audit terminal feedback fits; keep native and saved-model selection distinct."""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from analyze_operation_curve import (
    literal_file_equal,
    read_predictions,
    recipe_from_plan,
    saved_tensor_dtypes,
    validate_feedback_metric,
    validate_metric,
)
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control_learning import score_operation_predictions
from quality_feedback import (
    ANSWER_FIRST_MASSES,
    QUALITY_MODES,
    QualityMode,
    answer_first_counts,
    answer_first_weights,
    choose_quality_checkpoint,
    quality_counts,
    quality_event_weights,
    score_answer_first,
    score_quality_feedback,
    validate_quality_pool,
)
from retrieval_feedback import feedback_counts, score_feedback
from retrieval_mixture import event_weights, mixture_event_weights
from train_bounded_laya import state_option_seed, training_stages


def choose_feedback_checkpoint(points: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """Select the declared target's family/state metric; earliest ties include zero."""
    eligible = [p for p in points
                if p["feedback-dev"][target]["family_macro_state_pair_accuracy"] is not None]
    if not eligible:
        raise ValueError("No checkpoint has directional development coverage")
    return min(eligible, key=lambda p: (
        -p["feedback-dev"][target]["family_macro_state_pair_accuracy"], p["update"]))


def feedback_partitions(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]], legacy_ids: set[str],
    scorer: Callable[..., dict[str, Any]] = score_feedback,
) -> dict[str, Any]:
    """Report old/new and actual collector phases without changing the combined score."""
    identities = [r["metadata"]["event_id"] for r in rows]
    if len(set(identities)) != len(rows) or not legacy_ids <= set(identities):
        raise ValueError("Development identities or legacy membership changed")
    groups: dict[str, list[int]] = {"combined": [], "legacy": [], "new": []}
    for i, (row, _) in enumerate(zip(rows, predictions, strict=True)):
        groups["combined"].append(i)
        if row["metadata"]["event_id"] in legacy_ids:
            groups["legacy"].append(i)
        else:
            groups["new"].append(i)
            meta = row["metadata"]
            stratum = meta["collection_policy"] + ("_post" if meta["control_step"] else "_initial")
            groups.setdefault(stratum, []).append(i)
    return {name: {"states": len(indices), "targets": {
        target: scorer([rows[i] for i in indices], [predictions[i] for i in indices], target)
        for target in ("answer", "delivery")}} for name, indices in groups.items()}


def validate_quality_metric(actual: Any, expected: Any) -> None:
    """Compare all quality fields, including unknown/tie support and per-family loss."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise ValueError("Quality metric fields or family coverage changed")
        for key in expected:
            validate_quality_metric(actual[key], expected[key])
    elif isinstance(expected, float):
        if (not isinstance(actual, (float, int)) or isinstance(actual, bool)
                or not math.isfinite(actual)
                or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError("Quality metric value changed")
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError("Quality metric count, mask or meaning changed")


def validate_quality_exposure(run: dict[str, Any], sampled: dict[str, int]) -> None:
    for field, key in (("feedback_target_states", "states_with_targets"),
                       ("target_pairs", "target_pairs"),
                       ("cost_only_direction_pairs", "cost_only_direction_pairs")):
        if run["sampled_" + field] != sampled.get(key, 0):
            raise ValueError("Quality target exposure differs from the actual draw sequence")
    feedback = run["feedback_nonzero_logit_gradient_rows"]
    replay = run["replay_nonzero_logit_gradient_rows"]
    total = run["nonzero_logit_gradient_rows"]
    if (any(type(value) is not int or value < 0 for value in (feedback, replay, total))
            or feedback > sampled.get("states_with_targets", 0)
            or replay > sampled.get("replay_states", 0) or total != feedback + replay):
        raise ValueError("Instrumented logit-gradient counts exceed eligibility or disagree")


def validate_answer_first_exposure(run: dict[str, Any], sampled: dict[str, Any]) -> None:
    expected = {name + "_" + field: counts.get(field, 0)
        for name, counts in sampled["components"].items()
        for field in ("states", "pairs", "directional_pairs", "tie_pairs")}
    if run["sampled_answer_first_components"] != expected:
        raise ValueError("Answer/auxiliary pair exposure differs from the actual sampled rows")


def nominate_answer_first(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most two offline nominees; update0 is a mandatory separate actual-choice control."""
    eligible = [p for p in points if p["update"] > 0
                and p["answer_first"]["coverage"].get("target_pairs", 0)]
    return [{k: point[k] for k in ("update", "checkpoint")} for point in sorted(
        eligible, key=lambda p: (p["answer_first"]["weighted_task_pair_loss"], p["update"]))[:2]]


def analyze(plan: dict[str, Any], run_id: str, *,
            quality_mode: QualityMode | None = None,
            pair_label_smoothing: float | None = None,
            replay_objective: str | None = None,
            answer_first: bool = False, component_sum: bool = False) -> dict[str, Any]:
    spec, = [p for p in plan["plans"] if p["run_id"] == run_id]
    recipe = recipe_from_plan({**spec, "source_version": plan["source_version"]})
    root, data = Path(recipe["output"]), Path(recipe["data"])
    run = read_json(root / "run.json")
    supervision = "answer-first" if answer_first else quality_mode
    mass_mode = "component-sum" if answer_first or component_sum else "normalized-total"
    if run.get("pair_mass_mode", "normalized-total") != mass_mode:
        raise ValueError("Pair loss mass convention differs from its declared analysis")
    if component_sum and (supervision is None or "--pair-mass-mode" not in spec["argv"]
            or spec["argv"][spec["argv"].index("--pair-mass-mode") + 1] != "component-sum"):
        raise ValueError("Component-sum control needs its explicit quality recipe")
    if run["status"] != "COMPLETED" or run["optimizer_updates"] != recipe[
            "planned_optimizer_updates"]:
        raise ValueError("Feedback selection requires the complete declared fit")
    process = Path("/proc", str(run["pid"]), "cmdline")
    if process.exists() and str(root).encode() in process.read_bytes().split(b"\0"):
        raise ValueError("The trainer still owns this output")
    fields: tuple[str, ...] = (
              "backend", "precision", "reference_compile", "task", "objective", "operation_state",
              "seed", "max_len", "head_max_len", "encoder_lr", "head_lr", "batch_size",
              "planned_optimizer_updates", "freeze_encoder", "gradient_checkpointing",
              "shuffle_options", "evaluate_train")
    if mass_mode == "component-sum":
        recipe["pair_mass_mode"] = mass_mode
        fields = (*fields, "pair_mass_mode")
    if any(run[k] != recipe[k] for k in fields):
        raise ValueError("Completed feedback fit differs from its frozen recipe")
    if supervision is not None:
        argv = spec["argv"]
        if (supervision not in (*QUALITY_MODES, "answer-first") or recipe["objective"] != "pair"
                or argv[argv.index("--pair-supervision") + 1] != supervision
                or run["pair_supervision"] != supervision):
            raise ValueError("Quality supervision differs from the declared fit")
        recipe["pair_supervision"] = supervision
        recipe["device"] = "cuda"
        recipe["physical_gpus"] = [int(x) for x in spec["environment"][
            "CUDA_VISIBLE_DEVICES"].split(",")]
        fields = (*fields, "pair_supervision", "device", "physical_gpus")
        if run["device"] != recipe["device"] or run["physical_gpus"] != recipe["physical_gpus"]:
            raise ValueError("Quality training device allocation changed")
    elif run.get("pair_supervision", "legacy-direction") != "legacy-direction":
        raise ValueError("Quality-supervised fit requires its declared quality selection rule")
    if pair_label_smoothing is not None:
        argv = spec["argv"]
        if (supervision is None or not 0 < pair_label_smoothing < .5
                or argv.count("--pair-label-smoothing") != 1
                or float(argv[argv.index("--pair-label-smoothing") + 1]) != pair_label_smoothing
                or run["pair_label_smoothing"] != pair_label_smoothing):
            raise ValueError("Pair smoothing differs from the declared regularization fit")
        recipe["pair_label_smoothing"] = pair_label_smoothing
        fields = (*fields, "pair_label_smoothing")
    elif run.get("pair_label_smoothing", 0.0) != 0.0:
        raise ValueError("Smoothed fit requires its declared regularization audit")
    if replay_objective is not None:
        argv = spec["argv"]
        if (recipe["objective"] != "pair" or replay_objective != "set"
                or argv.count("--replay-objective") != 1
                or argv[argv.index("--replay-objective") + 1] != replay_objective
                or run.get("replay_objective") != replay_objective):
            raise ValueError("Replay objective differs from the declared optimization fit")
        recipe["replay_objective"] = replay_objective
        fields = (*fields, "replay_objective")
    elif run.get("replay_objective", "soft-ce") != "soft-ce":
        raise ValueError("Set replay requires its declared optimization audit")
    if answer_first:
        if spec["arm"] != "answer" or replay_objective != "set":
            raise ValueError("Answer-first analysis requires answer target and accepted-set replay")
        recipe["answer_first_component_masses"] = {**ANSWER_FIRST_MASSES, "replay": .25}
        if run["answer_first_component_masses"] != recipe["answer_first_component_masses"]:
            raise ValueError("Answer-first loss component masses changed")
        fields = (*fields, "answer_first_component_masses")
    if (Path(run["data"]) != data or Path(run["base_checkpoint"]) != Path(recipe["base_checkpoint"])
            or run["evaluation_points"] != recipe["evaluation_updates"][1:]
            or not run["evaluate_initial_dev"]
            or Path(run["feedback_dev_source"]) != Path(recipe["feedback_dev_source"])):
        raise ValueError("Initialization, inputs or evaluation schedule changed")

    train = read_jsonl(data / "train.jsonl")
    dev = read_jsonl(data / "dev.jsonl")
    feedback = read_jsonl(Path(recipe["feedback_dev_source"]))
    protocol = read_json(Path(plan["protocol"]))
    legacy = read_jsonl(Path(protocol["feedback_dev"]["old_file"]))
    if feedback[:len(legacy)] != legacy:
        raise ValueError("Original feedback development rows changed")
    legacy_ids = {r["metadata"]["event_id"] for r in legacy}
    component_weights = None
    if spec["arm"] == "continued-ce":
        if any(not row["gold"] or "feedback" in row for row in train):
            raise ValueError("Continued CE must use its original labelled replacements/replay")
        weights = event_weights(train)
    else:
        if run["feedback_target"] != spec["arm"] or run["replay_weight"] != 0.25:
            raise ValueError("Feedback target or replay loss mass changed")
        if answer_first:
            validate_quality_pool([*train, *feedback])
            component_weights = answer_first_weights(train, .25)
            weights = [1.0] * len(train)
            pool = answer_first_counts(train)
        elif quality_mode is None:
            weighted = [{**r, "metadata": {**r["metadata"], "component":
                         "feedback" if "feedback" in r else "operation_replay"}} for r in train]
            weights = mixture_event_weights(weighted, {"feedback": 1.0, "operation_replay": 0.25})
            pool = feedback_counts(train, spec["arm"])
        else:
            validate_quality_pool([*train, *feedback])
            weights = quality_event_weights(train, spec["arm"], quality_mode, .25,
                                            normalize_total=not component_sum)
            pool = quality_counts(train, spec["arm"], quality_mode)
        if run["feedback_pool"] != pool:
            raise ValueError("Feedback directional/tie/unknown support changed")
    if len(train) != run["train_states"] or len(dev) != run["dev_states"]:
        raise ValueError("Actual training/development row counts changed")
    for index, (row, sampled, weight) in enumerate(zip(
            train, read_json(root / "sampling.json"), weights, strict=True)):
        if (sampled["event_id"] != row["metadata"]["event_id"]
                or sampled["family"] != row["metadata"]["family"]
                or not math.isclose(sampled["weight"], weight, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("Training identities or state/family weights changed")
        if component_weights is not None and sampled[
                "answer_first_component_weights"] != component_weights[index]:
            raise ValueError("Independent answer/auxiliary/replay weights changed")
    stages = read_json(root / "training-plan.json")
    expected = training_stages(len(train), 1, recipe["seed"],
                              recipe["planned_optimizer_updates"], recipe["evaluation_updates"][1:])
    if stages != json.loads(json.dumps(expected)):
        raise ValueError("Actual draw sequence or update schedule changed")
    draws = [item for _, windows in stages for window in windows for item in window]
    lengths = read_json(root / "lengths.json")
    for split, rows in [("train", train), ("dev", dev), ("feedback-dev", feedback)]:
        for row, length in zip(rows, lengths[split], strict=True):
            if (length["event_id"] != row["metadata"]["event_id"] or length["question"] != "next"
                    or length["state_tokens_dropped"] or length["head_tokens_dropped"]):
                raise ValueError("Native input identity or complete-input capacity changed")
    if (len(draws) != run["train_sequence_rows"]
            or sum(lengths["train"][i]["sequence_tokens"] for _, i in draws)
            != run["train_input_tokens"]):
        raise ValueError("Actual training draws/tokens differ from native lengths")
    if spec["arm"] != "continued-ce":
        sampled = (answer_first_counts([train[i] for _, i in draws]) if answer_first else
                   feedback_counts([train[i] for _, i in draws], spec["arm"])
                   if quality_mode is None else
                   quality_counts([train[i] for _, i in draws], spec["arm"], quality_mode))
        for k in ("feedback_states", "replay_states", "directional_pairs", "tie_pairs",
                  "unknown_pairs"):
            if run["sampled_" + k] != sampled.get(k, 0):
                raise ValueError("Observed gradient-target exposure differs from actual draws")
        if supervision is not None:
            validate_quality_exposure(run, sampled)
        if answer_first:
            validate_answer_first_exposure(run, sampled)
    for data_pass in sorted({p for p, _ in draws}):
        orders = read_json(root / "option-orders" / f"{data_pass}.json")
        for row, order in zip(train, orders, strict=True):
            count = len(row["questions"]["next"]["criteria"])
            expected_order = list(range(count))
            rng = random.Random(state_option_seed(  # noqa: S311 -- original augmentation seed
                recipe["seed"], data_pass, row["metadata"]["state_id"]))
            rng.shuffle(expected_order)
            if order != (expected_order if count > 1 else None):
                raise ValueError("Recorded option slots differ from the declared state seed")

    history = read_json(root / "history.json")
    if [h["optimizer_updates"] for h in history] != recipe["evaluation_updates"]:
        raise ValueError("Feedback curve does not cover every declared checkpoint")
    curve: list[dict[str, Any]] = []
    costs: Counter[str] = Counter()
    prior_gradients = dict.fromkeys(("nonzero_logit_gradient_rows",
        "feedback_nonzero_logit_gradient_rows", "replay_nonzero_logit_gradient_rows"), 0)
    for native in history:
        update = native["optimizer_updates"]
        point: dict[str, Any] = {"update": update}
        for split, rows in [("dev", dev), ("feedback-dev", feedback)]:
            predictions = read_predictions(root / split / str(update), rows, lengths[split])
            saved = read_json(root / split / str(update) / "summary.json")
            if split == "dev":
                point[split] = score_operation_predictions(rows, predictions)
                validate_metric(saved, point[split])
                validate_metric(native[split], point[split])
            else:
                point["partitions"] = feedback_partitions(rows, predictions, legacy_ids)
                point[split] = point["partitions"]["combined"]["targets"]
                for target in ("answer", "delivery"):
                    validate_feedback_metric(saved[target], point[split][target])
                    validate_feedback_metric(native[split][target], point[split][target])
                if supervision is not None:
                    point["quality_partitions"] = feedback_partitions(
                        rows, predictions, legacy_ids, score_quality_feedback)
                    point["pure_quality"] = point["quality_partitions"]["combined"]["targets"]
                    point["quality_cost"] = {target: score_quality_feedback(
                        rows, predictions, target, "quality-cost")
                        for target in ("answer", "delivery")}
                    for name in ("pure_quality", "quality_cost"):
                        validate_quality_metric(saved[name], point[name])
                        validate_quality_metric(native[split][name], point[name])
                if answer_first or component_sum:
                    point["answer_first"] = score_answer_first(rows, predictions)
                    validate_quality_metric(saved["answer_first"], point["answer_first"])
                    validate_quality_metric(native[split]["answer_first"], point["answer_first"])
            costs[split + "_rows"] += len(predictions)
            costs[split + "_tokens"] += sum(p["input_tokens"] for p in predictions)
        checkpoint = Path(recipe["base_checkpoint"]) if update == 0 else (
            root / "checkpoints" / f"update-{update}")
        config = read_json(checkpoint / "rl_agent_config.json")
        if update:
            recorded = config["training"]["milai_reader"]
            if recorded["optimizer_updates"] != update or any(
                    recorded[k] != recipe[k] for k in fields):
                raise ValueError("Saved checkpoint metadata differs from its declared point")
            if supervision is not None:
                prefix = [train[i] for stop, windows in stages if stop <= update
                          for window in windows for _, i in window]
                exposure = (answer_first_counts(prefix) if answer_first else
                            quality_counts(prefix, spec["arm"], cast(QualityMode, quality_mode)))
                validate_quality_exposure(recorded, exposure)
                if answer_first:
                    validate_answer_first_exposure(recorded, exposure)
                for key in prior_gradients:
                    if recorded[key] < prior_gradients[key] or recorded[key] > run[key]:
                        raise ValueError("Checkpoint gradient counters are not cumulative")
                    prior_gradients[key] = recorded[key]
                if update == recipe["planned_optimizer_updates"] and any(
                        recorded[key] != run[key] for key in prior_gradients):
                    raise ValueError("Terminal checkpoint gradient counters differ from run")
        point.update(checkpoint=str(checkpoint),
                     saved_tensor_dtypes=saved_tensor_dtypes(checkpoint / "model.safetensors"))
        curve.append(point)
    terminal = root / "checkpoints" / f"update-{recipe['planned_optimizer_updates']}"
    if not literal_file_equal(terminal / "model.safetensors",
                              root / "checkpoint/model.safetensors"):
        raise ValueError("Final duplicate differs from the terminal saved weights")
    compute = read_json(root / "compute.json")
    for split in ("dev", "feedback-dev"):
        if (compute[split + "_sequence_rows"] != costs[split + "_rows"]
                or compute[split + "_input_tokens"] != costs[split + "_tokens"]):
            raise ValueError("Native evaluation compute differs from observed predictions")
    recorded_cost = read_json(Path(recipe["ledger"]))["compute"][recipe["compute_phase"]]
    if any(recorded_cost[k] != v for k, v in compute.items()
           if k not in ("ledger", "peak_rss_kib", "peak_cuda_allocated_bytes")):
        raise ValueError("Terminal compute does not match its original ledger entry")
    if supervision is not None:
        for key in ("feedback_target_states", "target_pairs", "cost_only_direction_pairs"):
            if compute["train_" + key] != run["sampled_" + key]:
                raise ValueError("Quality target compute differs from actual sampled support")
        for key in ("nonzero_logit_gradient_rows", "feedback_nonzero_logit_gradient_rows",
                    "replay_nonzero_logit_gradient_rows"):
            if compute["train_" + key] != run[key]:
                raise ValueError("Gradient counter compute differs from the terminal run")
    if answer_first:
        for key, count in run["sampled_answer_first_components"].items():
            if compute["train_answer_first_" + key] != count:
                raise ValueError("Component exposure compute differs from the terminal run")
    targets = ("answer", "delivery") if spec["arm"] == "continued-ce" else (spec["arm"],)
    chooser = choose_feedback_checkpoint if quality_mode is None else choose_quality_checkpoint
    selection = (None if answer_first else {target: {k: chooser(curve, target)[k]
                          for k in ("update", "checkpoint")} for target in targets})
    return {"status": ("TERMINAL_ANSWER_FIRST_CURVE_VERIFIED;ACTUAL_CHOICE_SELECTION_PENDING"
                       if answer_first else
                       "TERMINAL_NATIVE_FEEDBACK_CURVE_VERIFIED;SAVED_RELOAD_SELECTION_PENDING"
                       if quality_mode is None else
                       "TERMINAL_NATIVE_QUALITY_CURVE_VERIFIED;SAVED_RELOAD_SELECTION_PENDING"),
        "run_id": run_id, "recipe": recipe, "arm": spec["arm"], "curve": curve,
        **({"pair_supervision": "answer-first", "offline_nominations": nominate_answer_first(curve),
            "selection_rule": "At most two offline task-loss nominees; evaluate their actual "
                "saved full-menu choices with update0/simple baseline on fixed dev. Select by "
                "actual answer success, earliest tie. No deployment selection from pair loss."}
           if answer_first else {}),
        **({"pair_supervision": quality_mode,
            "selection_rule": "pure quality directional family/state accuracy; "
                              "earliest tie,0 eligible",
            "gradient_counters": {key: run[key] for key in (
                "nonzero_logit_gradient_rows", "feedback_nonzero_logit_gradient_rows",
                "replay_nonzero_logit_gradient_rows")},
            "gradient_verification_scope": "Instrumented aggregate logit-gradient counters; "
                "eligibility/compute consistency, not reconstructed parameter gradients."}
           if quality_mode is not None else {}),
        "in_memory_selection": selection, "deployment_selection": None,
        "train_draws": len(draws), "train_input_tokens": run["train_input_tokens"],
        "evaluation_totals": dict(costs), "native_compute_already_recorded": compute,
        "parameter_probes": read_json(root / "parameter-probes.json"),
        "scope": ("New masked objective and component-normalized diagnostics. Offline nominees "
                 "need saved reload and actual full-menu outcome selection; all unknowns retained."
                 if answer_first else
                 "Same original target and family/state scoring. Native GPU curve and saved FP16 "
                 "weights are distinct; every feedback candidate still needs CPU FP32 reload. "
                 "No inference of Host quality or unexecuted option labels.")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("output", type=Path)
    parser.add_argument("--answer-first", action="store_true")
    parser.add_argument("--quality-mode", choices=QUALITY_MODES)
    parser.add_argument("--component-sum", action="store_true")
    parser.add_argument("--replay-objective", choices=("set",))
    args = parser.parse_args()
    started = time.process_time()
    result = analyze(read_json(args.plan), args.run_id, answer_first=args.answer_first,
                     replay_objective="set" if args.answer_first else args.replay_objective,
                     quality_mode=args.quality_mode, component_sum=args.component_sum)
    args.output.mkdir(parents=True, exist_ok=False)
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
                  model_calls=0, no_sha_validation=True)
    write_json(args.output / "analysis.json", result)
    print(result["status"], result["in_memory_selection"])


if __name__ == "__main__":
    main()
