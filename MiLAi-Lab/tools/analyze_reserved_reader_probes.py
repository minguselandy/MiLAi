"""Summarize frozen reserved-prefix probes without selecting or tuning a model.

Reference labels and qualified source judgments stay separate. These original-view
predictions have no pre-save dev baseline and are not a presentation-invariance test.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from analyze_global_reader import diagnostics, source_diagnostics
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from probe_bounded_invariance import canonical_prediction, transform


def collect(root: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    rows = [json.loads(x) for x in Path(protocol["invariance"]["data"]).read_text().splitlines()]
    reviews = {r["source_row"]: r for r in read_json(Path(protocol["source_review"]))["cases"]}
    if protocol["invariance"]["variants"] != ["original"]:
        raise ValueError("Reserved protocol requires only the frozen original view")
    models = []
    actual: Counter[str] = Counter()
    checked = 0
    for model in protocol["models"]:
        folder = Path(model["probe_root"])
        run = read_json(folder / "run.json")
        if run["status"] != "COMPLETED" or run["completed"] != len(rows):
            raise ValueError("Every reserved prefix must have its first terminal output")
        predictions = []
        for index, row in enumerate(rows):
            call = folder / "calls" / str(index) / "original"
            payload = {k: row[k] for k in ("state", "questions")}
            expected, mapping = transform(
                payload, "original", protocol["invariance"]["seed"] + index
            )
            visible, prediction = read_json(call / "input.json"), read_json(call / "output.json")
            criteria = list(expected["questions"]["next"]["criteria"])
            if (
                visible != expected
                or list(visible["questions"]["next"]["criteria"]) != criteria
                or read_json(call / "action-map.json") != mapping
                or list(prediction["logits"]) != criteria
                or list(prediction["probabilities"]) != criteria
                or prediction["choice"] not in mapping
            ):
                raise ValueError(
                    f"Reserved probe input/output mapping differs: {model['name']}/{index}"
                )
            predictions.append(canonical_prediction(prediction, mapping))
            checked += 1
        compute = read_json(folder / "compute.json")
        actual.update(compute)
        models.append(
            {
                "model": model["name"],
                "reference": diagnostics(rows, predictions),
                "source": source_diagnostics(rows, predictions, reviews),
                "compute": compute,
            }
        )
    return {
        "status": "ALL_RESERVED_PREFIX_PROBES_CLOSED_AND_INPUTS_VERIFIED",
        "models": models,
        "input_output_mappings_verified": checked,
        "actual_compute_already_charged": dict(actual),
        "model_work_rebilled": False,
        "new_model_calls": 0,
        "scope": "Frozen original-view reference-prefix diagnostics on reserved source groups. "
        "No presentation variants or pre-save comparison; not actual-policy QA. Source "
        "judgments are qualified author review, not independent gold. All models retained.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    report = collect(args.root)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "report.json", report)
    measures = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "analyses": 1,
    }
    budget_path = Path(read_json(args.root / "protocol.json")["reader"]["budget_path"])
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute("global_reserved_reader_probe_analysis", measures)
    write_json(args.output / "compute.json", measures)
    print(report["status"])


if __name__ == "__main__":
    main()
