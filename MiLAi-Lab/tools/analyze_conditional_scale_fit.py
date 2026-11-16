"""Audit fixed-epoch auxiliary fits and the unchanged matched-operation curves."""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from analyze_operation_curve import (
    analyze as analyze_operation,
)
from analyze_operation_curve import (
    literal_file_equal,
    recipe_from_plan,
    saved_tensor_dtypes,
)
from evaluate_bounded_laya import score_applicability_predictions
from milai_lab.datasets.conditional_applicability import score_condition_pairs
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_mixture import event_weights
from train_bounded_laya import state_option_seed, training_microbatches, training_stages


def auxiliary_recipe(spec: dict[str, Any]) -> dict[str, Any]:
    argv = spec["argv"]
    index = next(i for i, arg in enumerate(argv) if Path(arg).name == "train_bounded_laya.py")

    def flag(name: str) -> str:
        return str(argv[argv.index(name) + 1])

    if (
        "--optimizer-updates" in argv
        or "--eval-at-updates" in argv
        or "--eval-every-updates" in argv
        or int(flag("--epochs")) != 1
        or "--train-eval-final-only" not in argv
        or "--skip-initial-dev" in argv
    ):
        raise ValueError("The auxiliary scale uses one complete epoch and fixed terminal weights")
    return {
        "data": argv[index + 1],
        "base_checkpoint": argv[index + 2],
        "output": argv[index + 3],
        "dev_source": flag("--dev-data"),
        "backend": "native",
        "task": "instruction_applicability",
        "objective": "soft-ce",
        "operation_state": "full",
        "device": "cuda",
        "physical_gpus": [2, 3],
        "precision": "float32",
        "reference_compile": False,
        "checkpoint_axis": "epoch",
        "epochs": 1,
        "seed": int(flag("--seed")),
        "max_len": int(flag("--max-len")),
        "head_max_len": int(flag("--head-max-len")),
        "batch_size": int(flag("--micro-batch-size")),
        "encoder_lr": float(flag("--encoder-lr")),
        "head_lr": float(flag("--head-lr")),
        "freeze_encoder": "--freeze-encoder" in argv,
        "gradient_checkpointing": "--gradient-checkpointing" in argv,
        "shuffle_options": "--shuffle-options" in argv,
        "evaluate_train": "--evaluate-train" in argv,
        "train_eval_final_only": True,
        "evaluate_initial_dev": True,
        "evaluation_points": [1],
        "planned_optimizer_updates": spec["updates"],
        "expected_draws": spec["draws"],
        "expected_train_tokens": spec["expected_pass1_tokens"],
        "ledger": flag("--budget"),
        "compute_phase": flag("--compute-phase"),
    }


def validate_applicability_prediction(
    row: dict[str, Any], result: dict[str, Any], length: dict[str, Any]
) -> None:
    keys = list(row["questions"]["applicability"]["criteria"])
    if (
        set(row["questions"]) != {"applicability"}
        or row["metadata"]["event_id"] != length["event_id"]
        or length["question"] != "applicability"
        or length["state_tokens_dropped"]
        or length["head_tokens_dropped"]
        or list(result["logits"]) != keys
        or list(result["probabilities"]) != keys
        or any(
            not math.isfinite(v)
            for field in ("logits", "probabilities")
            for v in result[field].values()
        )
        or result["choice"] != max(keys, key=lambda key: result["probabilities"][key])
        or result["truncated"]
        or result["input_tokens"] != length["sequence_tokens"]
    ):
        raise ValueError("Applicability prediction, literal option order or complete input changed")


def applicability_predictions(
    folder: Path, rows: list[dict[str, Any]], lengths: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()) != list(
        range(len(rows))
    ):
        raise ValueError("Applicability prediction coverage is incomplete")
    predictions = []
    for i, (row, length) in enumerate(zip(rows, lengths, strict=True)):
        prediction = read_json(folder / f"{i}.json")
        validate_applicability_prediction(row, prediction, length)
        predictions.append(prediction)
    return predictions


def validate_applicability_metric(saved: dict[str, Any], actual: dict[str, Any]) -> None:
    if any(
        saved[key] != actual[key]
        for key in ("counts", "families", "confusion", "family_macro_accuracy")
    ):
        raise ValueError("Applicability aggregate differs from actual predictions and masks")


def conditional_diagnostics(
    study: dict[str, Any], rows: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, Any]:
    config = study["conditional_diagnostics"]
    native = read_jsonl(Path(config["native"]) / "matrix.jsonl")
    reviewed = read_jsonl(Path(config["reviewed"]) / "matrix.jsonl")
    if reviewed != rows or any(
        any(a[k] != z[k] for k in ("state", "questions"))
        for a, z in zip(native, reviewed, strict=True)
    ):
        raise ValueError("Conditional diagnostic labels do not bind the same visible inputs")
    pairs = read_jsonl(Path(config["reviewed"]) / "condition-pairs.jsonl")
    native_pairs = read_jsonl(Path(config["native"]) / "condition-pairs.jsonl")
    interpretation = read_json(Path(config["interpretation"]))
    clear, inconsistent = [
        interpretation[k] for k in ("clear_requirement_changes", "native_label_inconsistencies")
    ]

    def identity(pair: dict[str, Any]) -> tuple[str, str]:
        return pair["left_event"], pair["right_event"]

    changes = [p for p in pairs if p["kind"] == "change"]
    if (
        any(p not in changes for p in [*clear, *inconsistent])
        or len({identity(p) for p in [*clear, *inconsistent]}) != len(changes)
        or len(clear) + len(inconsistent) != len(changes)
    ):
        raise ValueError("Declared semantic subsets must partition all computed changes")
    subsets = {
        "all_reviewed": pairs,
        "clear_requirement_change": clear,
        "native_label_inconsistency": inconsistent,
        "stable_positive": [p for p in pairs if p["kind"] == "stable" and p["left_label"] is True],
        "stable_negative": [p for p in pairs if p["kind"] == "stable" and p["left_label"] is False],
    }
    return {
        "native_only": score_condition_pairs(native, native_pairs, predictions),
        "reviewed": {
            key: score_condition_pairs(rows, values, predictions) for key, values in subsets.items()
        },
        "native_classification": score_applicability_predictions(native, predictions),
        "reviewed_classification": score_applicability_predictions(rows, predictions),
        "scope": "Same actual predictions, separate original and source-author labels. "
        "Label inconsistencies are not instruction effects; unknown accuracy is undefined. "
        "This is shared-corpus development, not native FollowIR or Host confirmation.",
    }


def analyze_auxiliary(study: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    recipe = auxiliary_recipe(spec)
    root = Path(recipe["output"])
    run = read_json(root / "run.json")
    if (
        run["status"] != "COMPLETED"
        or run["optimizer_updates"] != recipe["planned_optimizer_updates"]
    ):
        raise ValueError("Auxiliary analysis requires the completed declared epoch")
    proc = Path("/proc", str(run["pid"]), "cmdline")
    if proc.exists() and str(root).encode() in proc.read_bytes().split(b"\0"):
        raise ValueError("The auxiliary trainer still owns its output")
    fields = [
        key
        for key in recipe
        if key
        not in {"output", "ledger", "compute_phase", "expected_draws", "expected_train_tokens"}
    ]
    if any(run[key] != recipe[key] for key in fields):
        raise ValueError("Native auxiliary condition differs from its fixed-epoch recipe")
    train = read_jsonl(Path(recipe["data"]) / "train.jsonl")
    dev = read_jsonl(Path(recipe["dev_source"]))
    if any(not r["gold"] or r["metadata"]["split"] != "train" for r in train):
        raise ValueError("Auxiliary training admits only declared known training targets")
    if any(r["metadata"]["split"] != "dev" for r in dev):
        raise ValueError("Development data cannot change its partition")
    if (
        run["train_states"] != len(train)
        or run["dev_states"] != len(dev)
        or run["http_requests"] != 0
        or run["calibration_test_loaded"]
    ):
        raise ValueError("Auxiliary row coverage or declared evaluation scope changed")
    lengths = read_json(root / "lengths.json")
    for split, rows in [("train", train), ("dev", dev)]:
        for row, length in zip(rows, lengths[split], strict=True):
            if (
                length["event_id"] != row["metadata"]["event_id"]
                or length["question"] != "applicability"
                or length["state_tokens_dropped"]
                or length["head_tokens_dropped"]
            ):
                raise ValueError("Auxiliary length records changed input identity or clipped text")
    weights = event_weights(train)
    for row, item, weight in zip(train, read_json(root / "sampling.json"), weights, strict=True):
        if (
            item["event_id"] != row["metadata"]["event_id"]
            or item["family"] != row["metadata"]["family"]
            or item["weight"] != weight
        ):
            raise ValueError("Auxiliary sampling identities or family/event weights changed")
    stages = training_stages(len(train), 1, recipe["seed"])
    if read_json(root / "training-plan.json") != json.loads(json.dumps(stages)):
        raise ValueError("Auxiliary schedule differs from one unrepeated epoch")
    windows = [window for _, values in stages for window in values]
    draws = [item for window in windows for item in window]
    batches = [
        batch for window in windows for batch in training_microbatches(window, recipe["batch_size"])
    ]
    expected_counts = {
        "train_sequence_rows": len(draws),
        "train_offered_rows": len(draws),
        "train_input_tokens": recipe["expected_train_tokens"],
        "train_offered_tokens": recipe["expected_train_tokens"],
        "train_batch_attempts": len(batches),
        "train_batch_forwards": len(batches),
        "train_device_forwards": sum(min(len(batch), 2) for batch in batches),
    }
    if (
        len(draws) != recipe["expected_draws"]
        or len(windows) != recipe["planned_optimizer_updates"]
        or any(run[k] != v for k, v in expected_counts.items())
    ):
        raise ValueError("Native auxiliary draws, tokens or actual forward counts differ")
    for row, order in zip(train, read_json(root / "option-orders/1.json"), strict=True):
        expected = list(range(len(row["questions"]["applicability"]["criteria"])))
        rng = random.Random(state_option_seed(recipe["seed"], 1, row["metadata"]["state_id"]))  # noqa: S311
        rng.shuffle(expected)
        if order != expected:
            raise ValueError("Auxiliary option permutation differs from its original state seed")
    history = read_json(root / "history.json")
    if [h["epoch"] for h in history] != [0, 1] or "train" in history[0]:
        raise ValueError(
            "Auxiliary diagnostics require dev0/1 and terminal-only training evaluation"
        )
    costs: Counter[str] = Counter()
    curve = []
    for point in history:
        epoch = point["epoch"]
        result: dict[str, Any] = {"epoch": epoch}
        evaluations = {"dev": dev}
        if epoch == 1:
            evaluations["train"] = train
        for split, rows in evaluations.items():
            predictions = applicability_predictions(root / split / str(epoch), rows, lengths[split])
            score = score_applicability_predictions(rows, predictions)
            validate_applicability_metric(
                read_json(root / split / str(epoch) / "summary.json"), score
            )
            validate_applicability_metric(point[split], score)
            result[split] = score
            if split == "dev":
                result["conditional"] = conditional_diagnostics(study, rows, predictions)
            costs[split + "_rows"] += len(predictions)
            costs[split + "_tokens"] += sum(p["input_tokens"] for p in predictions)
        curve.append(result)
    checkpoint = root / "checkpoint"
    config = read_json(checkpoint / "rl_agent_config.json")
    recorded = config["training"]["milai_reader"]
    if (
        recorded["epoch"] != 1
        or recorded["optimizer_updates"] != recipe["planned_optimizer_updates"]
        or any(recorded[k] != recipe[k] for k in fields)
        or any(recorded[k] != value for k, value in expected_counts.items())
    ):
        raise ValueError("Terminal auxiliary metadata does not identify the declared full epoch")
    if not literal_file_equal(
        checkpoint / "model.safetensors", root / "checkpoint_latest/model.safetensors"
    ):
        raise ValueError("Auxiliary terminal and latest saved weights differ")
    probes = read_json(root / "parameter-probes.json")
    if any(probes[group]["changed_elements"] <= 0 for group in ("encoder", "head")):
        raise ValueError("The declared full auxiliary update has no recorded parameter movement")
    compute = read_json(root / "compute.json")
    if any(compute[k] != v for k, v in expected_counts.items()):
        raise ValueError("Auxiliary compute does not match actual training counters")
    for split in ("dev", "train"):
        prefix = "train_eval" if split == "train" else split
        if (
            compute[prefix + "_sequence_rows"] != costs[split + "_rows"]
            or compute[prefix + "_input_tokens"] != costs[split + "_tokens"]
        ):
            raise ValueError("Auxiliary evaluation compute differs from actual predictions")
    ledger = read_json(Path(recipe["ledger"]))["compute"][recipe["compute_phase"]]
    if Path(compute["ledger"]) != Path(recipe["ledger"]) or any(
        ledger[k] != v
        for k, v in compute.items()
        if k not in {"ledger", "peak_rss_kib", "peak_cuda_allocated_bytes"}
    ):
        raise ValueError("Auxiliary compute does not match its existing original-ledger phase")
    return {
        "status": "TERMINAL_AUXILIARY_EPOCH_VERIFIED;SAVED_RELOAD_PENDING",
        "run_id": spec["run_id"],
        "recipe": recipe,
        "curve": curve,
        "fixed_terminal_checkpoint": str(checkpoint),
        "selected_on_dev": False,
        "saved_tensor_dtypes": saved_tensor_dtypes(checkpoint / "model.safetensors"),
        "training_draws": len(draws),
        "last_window_size": len(windows[-1]),
        "training_input_tokens": run["train_input_tokens"],
        "parameter_probes": probes,
        "compute_already_recorded": compute,
        "deployment_verified": False,
        "scope": "Verified native exposure and recorded parameter-probe movement, not "
        "per-example nonzero gradients. Fixed endpoint, no semantic-dev selection. "
        "Saved precision/device behavior and actual Host benefit remain separate.",
    }


def analyze_scale_fit(study: dict[str, Any], run_id: str) -> dict[str, Any]:
    if run_id == "pure-operation-baseline":
        recipe = recipe_from_plan(
            {
                **study["baseline_operation_spec"],
                "source_version": "declared-query-scale-operation-freeze",
            }
        )
        result = analyze_operation(recipe)
        result.update(run_id=run_id, stage="pure_operation_baseline")
        return result
    matches = [
        (kind, arm[kind])
        for arm in study["arms"]
        for kind in ("auxiliary", "operation")
        if arm[kind]["run_id"] == run_id
    ]
    if len(matches) != 1:
        raise ValueError("Run identity must name exactly one declared scale stage")
    kind, spec = matches[0]
    if kind == "auxiliary":
        return analyze_auxiliary(study, spec)
    recipe = recipe_from_plan({**spec, "source_version": "declared-query-scale-operation-freeze"})
    result = analyze_operation(recipe)
    result.update(
        run_id=run_id, stage="matched_operation", study_baseline=study["baseline_operation_run"]
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    result = analyze_scale_fit(read_json(args.study), args.run_id)
    result.update(
        model_calls=0,
        ledger_recorded=False,
        cpu_seconds_pending=time.process_time() - started,
        no_sha_validation=True,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "analysis.json", result)
    print(result["status"], args.run_id)


if __name__ == "__main__":
    main()
