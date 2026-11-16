"""Pair a selected operation model with every prespecified recorded-state baseline."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from analyze_operation_curve import read_predictions, validate_metric
from evaluate_saved_operation_curve import verified_predictions
from milai_lab.analysis.paired_sources import compare_sources
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.memory_control_learning import score_operation_predictions

BASELINES = {"fixed", "fixed_context", "rules", "view_cache", "first_offered", "handoff"}


def compare(rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
            baselines: dict[str, list[dict[str, Any]]], sample_seed: int,
            *, repeats: int = 10000) -> tuple[dict[str, Any], dict[str, Any]]:
    if set(baselines) != BASELINES:
        raise ValueError("All six prespecified recorded-state baselines must be retained")
    results, pairs = {}, {}
    for name, choices in baselines.items():
        units = []
        for row, predicted, baseline in zip(rows, predictions, choices, strict=True):
            meta = row["metadata"]
            offered = row["questions"]["next"]["criteria"]
            if (baseline["event_id"] != meta["event_id"]
                    or baseline["choice"] not in offered or predicted["choice"] not in offered):
                raise ValueError("Baseline identity/order or offered action differs from the model")
            target = row["gold"].get("next", {}).get("probabilities", {})
            units.append({"seed": sample_seed, "unit_id": meta["event_id"],
                "family": meta["family"],
                "baseline": int(target.get(baseline["choice"], 0) > 0) if target else None,
                "candidate": int(target.get(predicted["choice"], 0) > 0) if target else None})
        pairs[name] = units
        results[name] = compare_sources(units, repeats=repeats)
    return results, pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path,
                        help="Audited in-memory analysis or saved CPU results")
    parser.add_argument("baselines", type=Path, help="Fixed dev-baseline-predictions.json")
    parser.add_argument("output", type=Path)
    parser.add_argument("--condition", required=True, choices=("in-memory-gpu", "saved-cpu"))
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    report = read_json(args.results)
    recipe = report["recipe"]
    root = Path(recipe["output"])
    rows = read_jsonl(Path(recipe["data"]) / "dev.jsonl")
    lengths = read_json(root / "lengths.json")["dev"]
    if args.condition == "in-memory-gpu":
        selection = report["in_memory_selection"]
        predictions = read_predictions(root / "dev" / str(selection["update"]), rows, lengths)
    else:
        selection = report["deployment_selection"]
        evaluation = args.results.parent / f"update-{selection['update']}"
        combined = read_jsonl(args.results.parent / "dev-and-feedback.jsonl")
        all_lengths = read_json(root / "lengths.json")
        combined_lengths = [*lengths, *(all_lengths["feedback-dev"]
                            if recipe["feedback_dev_source"] is not None else [])]
        predictions = verified_predictions(evaluation, combined, combined_lengths, recipe,
                                            Path(selection["checkpoint"]))[:len(rows)]
    point = next(p for p in report["curve"] if p["update"] == selection["update"])
    validate_metric(point["dev"], score_operation_predictions(rows, predictions))
    results, pairs = compare(rows, predictions, read_json(args.baselines), recipe["seed"])
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "paired-units.json", pairs)
    output = {"status": "COMPLETE_CONDITIONAL_DEV_COMPARISON", "condition": args.condition,
        "selection": selection, "results_source": str(args.results),
        "baselines_source": str(args.baselines), "seed": recipe["seed"], "comparisons": results,
        "scope": "Selected and evaluated on the same development families;descriptive intervals "
                 "include selection optimism and are not protected confirmation. Static recorded "
                 "states,not baseline rollouts or Host success. All six baselines retained.",
        "model_calls": 0, "no_sha_validation": True, "ledger_recorded": False,
        "compute": {"cpu_seconds": time.process_time()-cpu,
                    "wall_seconds": time.perf_counter()-started}}
    write_json(args.output / "comparisons.json", output)


if __name__ == "__main__":
    main()
