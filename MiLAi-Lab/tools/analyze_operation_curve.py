"""Audit complete operation curves and retain in-memory versus saved-model selection separately."""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import struct
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.methods.memory_control_learning import score_operation_predictions
from retrieval_feedback import feedback_dev_report, score_feedback
from retrieval_mixture import event_weights, mixture_event_weights
from train_bounded_laya import state_option_seed, training_stages


def recipe_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    argv = plan["argv"]
    script = next(i for i, value in enumerate(argv) if Path(value).name == "train_bounded_laya.py")
    data, base, output = argv[script+1:script+4]
    def flag(name: str) -> str:
        return str(argv[argv.index(name)+1])
    end = argv.index("--eval-at-updates") + 1
    points = []
    while end < len(argv) and not argv[end].startswith("--"):
        points.append(int(argv[end]))
        end += 1
    budget = int(flag("--optimizer-updates"))
    return {"data": data, "base_checkpoint": base, "output": output,
        "execution_prefix": argv[:script],
        "backend": flag("--backend") if "--backend" in argv else "native",
        "precision": "float32", "reference_compile": False,
        "task": flag("--task"), "objective": flag("--objective"),
        "operation_state": flag("--operation-state"), "seed": int(flag("--seed")),
        "max_len": int(flag("--max-len")), "head_max_len": int(flag("--head-max-len")),
        "encoder_lr": float(flag("--encoder-lr")), "head_lr": float(flag("--head-lr")),
        "batch_size": int(flag("--micro-batch-size")), "planned_optimizer_updates": budget,
        "freeze_encoder": "--freeze-encoder" in argv,
        "gradient_checkpointing": "--gradient-checkpointing" in argv,
        "shuffle_options": "--shuffle-options" in argv,
        "evaluate_train": "--evaluate-train" in argv,
        "evaluation_updates": [0, *sorted({*points, budget})],
        "feedback_dev_source": (flag("--feedback-dev-data")
                                if "--feedback-dev-data" in argv else None),
        "compute_phase": flag("--compute-phase"), "ledger": flag("--budget"),
        "source_version": plan["source_version"]}


def saved_tensor_dtypes(path: Path) -> dict[str, int]:
    with path.open("rb") as stream:
        size = struct.unpack("<Q", stream.read(8))[0]
        header = json.loads(stream.read(size))
    return dict(Counter(value["dtype"] for key, value in header.items() if key != "__metadata__"))


def literal_file_equal(left: Path, right: Path) -> bool:
    """Direct bytes, not a content digest;weights are never loaded into a model."""
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            x, y = a.read(8 * 1024 * 1024), b.read(8 * 1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


def choose_checkpoint(points: list[dict[str, Any]]) -> dict[str, Any]:
    """The declared family metric, earliest tie;0 participates like every other checkpoint."""
    eligible = [point for point in points if point["dev"]["family_macro_acceptance"] is not None]
    return min(eligible, key=lambda p: (-p["dev"]["family_macro_acceptance"], p["update"]))


def read_predictions(folder: Path, rows: list[dict[str, Any]],
                     lengths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actual_indices = sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())
    if actual_indices != list(range(len(rows))):
        raise ValueError("Prediction coverage is incomplete or differs from the declared row order")
    predictions = []
    for index, (row, length) in enumerate(zip(rows, lengths, strict=True)):
        result = read_json(folder / f"{index}.json")
        validate_prediction(row, result, length)
        predictions.append(result)
    return predictions


def validate_prediction(row: dict[str, Any], result: dict[str, Any],
                        length: dict[str, Any]) -> None:
    if row["metadata"]["event_id"] != length["event_id"] or length["question"] != "next":
        raise ValueError("Saved input lengths do not identify the same ordered operation rows")
    keys = list(row["questions"]["next"]["criteria"])
    if (list(result["logits"]) != keys or list(result["probabilities"]) != keys
            or any(not math.isfinite(v) for field in ("logits", "probabilities")
                   for v in result[field].values())
            or result["choice"] != max(keys, key=lambda k: result["probabilities"][k])
            or result["truncated"] or result["input_tokens"] != length["sequence_tokens"]):
        raise ValueError("Prediction choices,finite logits or exact input length changed")


def operation_diagnostics(rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
                          lengths: list[dict[str, Any]], positions: dict[str, Any],
                          ) -> dict[str, Any]:
    summary = score_operation_predictions(rows, predictions)
    buckets: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, (row, length) in enumerate(zip(rows, lengths, strict=True)):
        meta = row["metadata"]
        buckets["component"][meta["component"]].append(i)
        buckets["length"]["<=8192" if length["sequence_tokens"] <= 8192 else ">8192"].append(i)
        state = (expand_observation_state(row["state"])
                 if "observation_encoding" in row["state"] else row["state"])
        count = len(state["pending_candidates"])
        buckets["candidates"]["0" if not count else "1-8" if count <= 8 else
                               "9-16" if count <= 16 else "17+"].append(i)
        target = row["gold"].get("next", {}).get("probabilities", {})
        if any(value > 0 and meta["action_kinds"][key] == "READ" for key, value in target.items()):
            buckets["read_opportunity"]["reviewed_positive_READ_available"].append(i)
        if positions:
            position = positions[meta["event_id"]]
            if (position["family"] != meta["family"]
                    or position["sequence_tokens"] != length["sequence_tokens"]):
                raise ValueError("Witness positions belong to a different input condition")
            buckets["whole_source_position"][position["position_bucket"]].append(i)
    summary["raw_states"] = len(rows)
    summary["registered_families_in_input"] = len({r["metadata"]["family"] for r in rows})
    summary["buckets"] = {dimension: {label: score_operation_predictions(
        [rows[i] for i in indices], [predictions[i] for i in indices])
        for label, indices in groups.items()} for dimension, groups in buckets.items()}
    summary["position_scope"] = (
        "Whole source/range coverage,not minimal answer spans or semantic sufficiency")
    return summary


def validate_metric(saved: dict[str, Any], actual: dict[str, Any]) -> None:
    if saved["counts"] != actual["counts"] or saved["families"] != actual["families"]:
        raise ValueError("Saved aggregate counts differ from the actual per-row predictions")
    x, y = saved["family_macro_acceptance"], actual["family_macro_acceptance"]
    if x != y and (x is None or y is None or not math.isclose(x, y, rel_tol=0, abs_tol=1e-12)):
        raise ValueError("Saved source-family metric differs from per-row predictions")


def validate_feedback_metric(saved: dict[str, Any], actual: dict[str, Any]) -> None:
    for key in ("counts", "families", "families_with_direction", "coverage"):
        if saved[key] != actual[key]:
            raise ValueError("Saved feedback counts differ from actual predictions")
    for key in ("family_macro_state_pair_accuracy", "family_macro_state_pair_loss"):
        x, y = saved[key], actual[key]
        if x != y and (x is None or y is None or not math.isclose(x, y, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("Saved feedback metric differs from actual predictions")


def analyze(recipe: dict[str, Any], *, position_directory: Path | None = None) -> dict[str, Any]:
    root, data = Path(recipe["output"]), Path(recipe["data"])
    run = read_json(root / "run.json")
    if (run["status"] != "COMPLETED"
            or run["optimizer_updates"] != recipe["planned_optimizer_updates"]):
        raise ValueError("Checkpoint selection requires the complete declared training run")
    proc = Path("/proc") / str(run["pid"]) / "cmdline"
    if proc.exists() and str(root.resolve()).encode() in proc.read_bytes().split(b"\0"):
        raise ValueError("The declared training process still owns this output")
    fields = ("backend", "precision", "reference_compile", "task", "objective",
        "operation_state", "seed", "max_len", "head_max_len",
        "encoder_lr", "head_lr", "batch_size", "freeze_encoder", "gradient_checkpointing",
        "shuffle_options", "planned_optimizer_updates", "evaluate_train")
    if any(run[key] != recipe[key] for key in fields):
        raise ValueError("Completed run differs from the declared experimental condition")
    if (Path(run["data"]).resolve() != data.resolve()
            or Path(run["base_checkpoint"]).resolve() != Path(recipe["base_checkpoint"]).resolve()
            or run["evaluation_points"] != recipe["evaluation_updates"][1:]
            or not run["evaluate_initial_dev"] or not run["evaluate_train"]
            or run["train_eval_final_only"]):
        raise ValueError("Data or synchronized curve coverage differs from the plan")
    raw = {split: read_jsonl(data / f"{split}.jsonl") for split in ("train", "dev")}
    rows = {"train": [r for r in raw["train"] if r["gold"]], "dev": raw["dev"]}
    if recipe["feedback_dev_source"] is not None:
        if (Path(run["feedback_dev_source"]).resolve()
                != Path(recipe["feedback_dev_source"]).resolve()):
            raise ValueError("Feedback development source differs from the declared fixed input")
        rows["feedback-dev"] = read_jsonl(Path(recipe["feedback_dev_source"]))
    if any(set(row["questions"]) != {"next"} for split in rows.values() for row in split):
        raise ValueError("This analyzer covers operation-only curves,not combined task metrics")
    lengths = read_json(root / "lengths.json")
    sampling = read_json(root / "sampling.json")
    mixture = read_json(data / "mixture.json") if recipe["task"] == "mixed_retrieval" else None
    weights = (mixture_event_weights(rows["train"], mixture) if mixture
               else event_weights(rows["train"]))
    for row, item, weight in zip(rows["train"], sampling, weights, strict=True):
        meta = row["metadata"]
        if (item["event_id"] != meta["event_id"] or item["family"] != meta["family"]
                or not math.isclose(item["weight"], weight, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("Training identity/order or loss weight differs from saved sampling")
        if recipe["task"] == "mixed_retrieval" and any(item[k] != meta[k] for k in (
                "task", "component")):
            raise ValueError("Saved sampling component or task changed")
    planned = training_stages(len(rows["train"]), 1, recipe["seed"],
        recipe["planned_optimizer_updates"], recipe["evaluation_updates"][1:])
    stages = read_json(root / "training-plan.json")
    if json.loads(json.dumps(planned)) != stages:
        raise ValueError("Saved training draws or common cosine checkpoints differ from the plan")
    draws = [item for _, windows in stages for window in windows for item in window]
    train_tokens = sum(lengths["train"][index]["sequence_tokens"] for _, index in draws)
    if len(draws) != run["train_sequence_rows"] or train_tokens != run["train_input_tokens"]:
        raise ValueError("Completed training exposure differs from saved draw/input lengths")
    if recipe["task"] == "mixed_retrieval":
        sampled_components = Counter(rows["train"][i]["metadata"]["component"] for _, i in draws)
        if dict(sampled_components) != run["sampled_component_rows"]:
            raise ValueError("Component draw counts differ from the recorded uniform sampling")
    if recipe["shuffle_options"]:
        for data_pass in sorted({p for p, _ in draws}):
            actual = read_json(root / "option-orders" / f"{data_pass}.json")
            for row, order in zip(rows["train"], actual, strict=True):
                count = len(row["questions"]["next"]["criteria"])
                expected = list(range(count))
                state_seed = state_option_seed(
                    recipe["seed"], data_pass, row["metadata"]["state_id"])
                rng = random.Random(state_seed)  # noqa: S311 -- recorded augmentation seed
                rng.shuffle(expected)
                if order != (expected if count > 1 else None):
                    raise ValueError("Saved option order differs from its source-state seed")
    history = read_json(root / "history.json")
    if [p["optimizer_updates"] for p in history] != recipe["evaluation_updates"]:
        raise ValueError("Only complete declared synchronized histories are eligible")
    positions = {split: ({p["event_id"]: p for p in read_json(
        position_directory / f"{split}-positions.json")} if position_directory else {})
        for split in ("train", "dev")}
    curve, checkpoint_records = [], []
    costs: Counter[str] = Counter()
    for saved in history:
        update = saved["optimizer_updates"]
        point: dict[str, Any] = {"update": update}
        for split in rows:
            predictions = read_predictions(root / split / str(update), rows[split], lengths[split])
            summary = read_json(root / split / str(update) / "summary.json")
            if split == "feedback-dev":
                point[split] = {target: score_feedback(rows[split], predictions, target)
                                for target in ("answer", "delivery")}
                point[split]["coverage"] = feedback_dev_report(
                    rows[split], raw["train"], raw["dev"])
                if point[split]["coverage"] != summary["coverage"]:
                    raise ValueError("Feedback development coverage differs from its recorded pool")
                for target in ("answer", "delivery"):
                    validate_feedback_metric(summary[target], point[split][target])
                    validate_feedback_metric(saved[split][target], point[split][target])
            else:
                point[split] = operation_diagnostics(
                    rows[split], predictions, lengths[split], positions[split])
                metric = (summary["by_task"]["memory_operation"]
                          if recipe["task"] == "mixed_retrieval" else summary)
                validate_metric(metric, point[split])
                prior = saved[split]["by_task"]["memory_operation"] if recipe["task"] == (
                    "mixed_retrieval") else saved[split]
                validate_metric(prior, point[split])
                if recipe["task"] == "mixed_retrieval":
                    for component, score in point[split]["buckets"]["component"].items():
                        validate_metric(summary["by_component"][component], score)
            costs[split + "_rows"] += len(predictions)
            costs[split + "_tokens"] += sum(p["input_tokens"] for p in predictions)
        point["train_dev_family_gap"] = (point["train"]["family_macro_acceptance"]
                                         - point["dev"]["family_macro_acceptance"])
        checkpoint = (Path(recipe["base_checkpoint"]) if update == 0 else
                      root / "checkpoints" / f"update-{update}")
        config = read_json(checkpoint / "rl_agent_config.json")
        if update:
            recorded = config["training"]["milai_reader"]
            if (recorded["optimizer_updates"] != update
                    or any(recorded[k] != recipe[k] for k in fields)):
                raise ValueError("Checkpoint metadata does not match its declared training point")
        checkpoint_records.append({"update": update, "path": str(checkpoint),
            "tensor_dtypes": saved_tensor_dtypes(checkpoint / "model.safetensors")})
        point["checkpoint"] = str(checkpoint)
        curve.append(point)
    final = root / "checkpoints" / f"update-{recipe['planned_optimizer_updates']}"
    if not literal_file_equal(final / "model.safetensors", root / "checkpoint/model.safetensors"):
        raise ValueError("Final duplicate checkpoint differs from the saved terminal point")
    compute = read_json(root / "compute.json")
    for split in rows:
        prefix = "train_eval" if split == "train" else split
        if (compute[prefix + "_input_tokens"] != costs[split + "_tokens"]
                or compute[prefix + "_sequence_rows"] != costs[split + "_rows"]):
            raise ValueError("Recorded evaluation compute differs from actual prediction coverage")
    ledger_phase = read_json(Path(recipe["ledger"]))["compute"][recipe["compute_phase"]]
    measures = {k: v for k, v in compute.items() if k not in (
        "ledger", "peak_rss_kib", "peak_cuda_allocated_bytes")}
    if any(ledger_phase[k] != value for k, value in measures.items()):
        raise ValueError("Unique run compute phase does not match its existing ledger entry")
    selected = choose_checkpoint(curve)
    return {"status": "COMPLETE_IN_MEMORY_CURVE_AUDITED;PERSISTED_SELECTION_PENDING",
        "recipe": recipe, "curve": curve, "saved_checkpoints": checkpoint_records,
        "in_memory_selection": {"update": selected["update"], "checkpoint": selected["checkpoint"],
            "metric": selected["dev"]["family_macro_acceptance"],
            "rule": "highest dev source-family macro acceptance,earliest tie,0eligible"},
        "deployment_selection": None, "raw_rows": {s: len(r) for s, r in raw.items()},
        "raw_families": {s: len({row["metadata"]["family"] for row in values})
                         for s, values in raw.items()},
        "training_draws_verified": len(draws), "training_tokens_verified": train_tokens,
        "evaluation_totals_verified": dict(costs), "final_checkpoint_bytes_equal": True,
        "compute_already_recorded": compute, "unique_ledger_phase_equal": True,
        "input_length_scope": "Saved audits check state/global-head budgets;intrinsic option "
                              "clipping needs the separately retained encoding audit.",
        "scope": "In-memory training precision,not saved-model quality or Host success. "
                 "Native serialization may round weights. CPU saved-candidate evaluation is "
                 "required before downstream binding. Whole-job wall includes preparation "
                 "and evaluation;it is not isolated GPU kernel time. No compute rebilled."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run-id", help="Select a run in a multi-run amendment's plans array")
    parser.add_argument("--positions", type=Path)
    args = parser.parse_args()
    plan = read_json(args.plan)
    if args.run_id:
        plan = next(p for p in plan["plans"] if p["run_id"] == args.run_id)
    started, cpu = time.perf_counter(), time.process_time()
    report = analyze(recipe_from_plan(plan), position_directory=args.positions)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "curve.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(["update", "split", "labelled", "accepted", "family_macro_acceptance",
                         "handoff_outside_reviewed_preference"])
        for point in report["curve"]:
            for split in ("train", "dev"):
                score = point[split]
                writer.writerow([point["update"], split, score["counts"]["labelled"],
                    score["counts"].get("accepted", 0), score["family_macro_acceptance"],
                    score["counts"].get("handoff_outside_reviewed_preference", 0)])
    report.update(model_calls=0, no_sha_validation=True, ledger_recorded=False,
        analysis_compute={"cpu_seconds": time.process_time()-cpu,
                          "wall_seconds": time.perf_counter()-started})
    write_json(args.output / "analysis.json", report)
    print({"status": report["status"], "in_memory_selection": report["in_memory_selection"]})


if __name__ == "__main__":
    main()
