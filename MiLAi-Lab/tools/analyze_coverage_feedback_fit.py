"""Verify coverage fits against their literal source derivation and matched Q training recipe."""
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path
from typing import Any

from analyze_feedback_fit import analyze
from analyze_quality_feedback_fit import quality_analysis_plan
from feedback_coverage import compile_coverage_controls
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def verify_coverage_data(study: dict[str, Any]) -> dict[str, Any]:
    source, root = Path(study["source_data"]), Path(study["data_root"])
    if study["target"] != "answer" or study["quality_mode"] != "quality-direction":
        raise ValueError("This declared coverage comparison uses pure-quality ANSWER directions")
    expected = compile_coverage_controls(read_jsonl(source / "train.jsonl"))
    if study["common_families"] != expected["eligible_families"]:
        raise ValueError("Coverage common-source selection changed")
    if read_json(root / "source-slot-mapping.json")["mapping"] != expected["mapping"]:
        raise ValueError("Coverage source-slot identity mapping changed")
    preparation = read_json(root / "preparation.json")
    for key in ("eligible_families", "excluded_families", "collectors", "target", "mode", "counts"):
        if preparation[key] != expected[key]:
            raise ValueError("Coverage declaration differs from its original source derivation")
    for name, rows in expected["arms"].items():
        if read_jsonl(root / name / "train.jsonl") != rows:
            raise ValueError("Matched coverage training rows changed from their literal source")
        for filename in ("dev.jsonl", "feedback-dev.jsonl"):
            if (root / name / filename).read_bytes() != (source / filename).read_bytes():
                raise ValueError("Coverage development inputs changed")
    return {key: expected[key] for key in ("eligible_families", "excluded_families",
                                           "collectors", "counts", "scope")}


def coverage_analysis_plan(
    study: dict[str, Any], quality: dict[str, Any], original: dict[str, Any],
) -> dict[str, Any]:
    base = quality_analysis_plan(quality, original)
    baseline, = [p for p in base["plans"] if p["quality_mode"] == "quality-direction"]
    entry = next(i for i, arg in enumerate(baseline["argv"])
                 if Path(arg).name == "train_bounded_laya.py")
    if (study["source_data"] != baseline["argv"][entry + 1]
            or study["common_initialization"] != quality["common_initialization"]
            or study["base_runtime"] != quality["base_runtime"]
            or study["training_overlay"] != quality["training_overlay"]
            or [p["coverage_arm"] for p in study["plans"]] != ["initial_only", "initial_post"]):
        raise ValueError("Coverage study changed its source, runtime, initialization or arm order")
    derivation = verify_coverage_data(study)
    plans = []
    for spec in study["plans"]:
        argv = list(spec["argv"])
        data = Path(study["data_root"]) / spec["coverage_arm"]
        feedback = argv.index("--feedback-dev-data") + 1
        phase = argv.index("--compute-phase") + 1
        if (argv[entry + 1] != str(data) or argv[feedback] != str(data / "feedback-dev.jsonl")
                or argv[entry + 3] != spec["output"] or argv[phase] != spec["compute_phase"]
                or spec["arm"] != "answer"
                or spec["source_cohort"] != len(study["common_families"])
                or spec["environment"] != baseline["environment"]
                or spec["cwd"] != baseline["cwd"]):
            raise ValueError("Coverage arm data/output/source count or environment changed")
        argv[entry + 1] = baseline["argv"][entry + 1]
        argv[entry + 3] = baseline["output"]
        argv[feedback] = baseline["argv"][feedback]
        argv[phase] = baseline["compute_phase"]
        if argv != baseline["argv"]:
            raise ValueError("Coverage controls changed the matched Q objective/budget/recipe")
        plans.append({**copy.deepcopy(spec), "quality_mode": "quality-direction"})
    return {"source_version": base["source_version"] + "+matched-coverage-data-v1",
        "protocol": base["protocol"], "plans": plans, "coverage_derivation": derivation,
        "unmatched_full_Q_reference_run_id": baseline["run_id"],
        "scope": "Both coverage arms are new fits on the same eligible source/replay subset. "
                 "The full128 Q fit is a reference, not the matched coverage baseline."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("quality_plan", type=Path)
    parser.add_argument("original_plan", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    plan = coverage_analysis_plan(read_json(args.study), read_json(args.quality_plan),
                                   read_json(args.original_plan))
    spec, = [p for p in plan["plans"] if p["run_id"] == args.run_id]
    result = analyze(plan, args.run_id, quality_mode="quality-direction")
    result.update(coverage_arm=spec["coverage_arm"],
        coverage_derivation=plan["coverage_derivation"], study=str(args.study.resolve()),
        full_Q_reference_is_not_matched_control=True, model_calls=0, ledger_recorded=False,
        cpu_seconds_pending=time.process_time() - started, no_sha_validation=True)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "analysis.json", result)
    print(result["status"], result["coverage_arm"], result["in_memory_selection"])


if __name__ == "__main__":
    main()
