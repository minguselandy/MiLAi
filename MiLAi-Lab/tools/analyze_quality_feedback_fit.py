"""Quality-control native verifier using the shared complete-fit audit."""
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path
from typing import Any, cast

from analyze_feedback_fit import analyze
from milai_lab.harness.artifact_io import read_json, write_json
from quality_feedback import QUALITY_MODES, QualityMode


def quality_analysis_plan(quality: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    """Permit only the already-declared supervision overlay and its output/cost identity."""
    if (quality["common_initialization"] != original["common_initialization"]
            or quality["base_runtime"] != original["frozen_lab"]
            or quality["first_comparison"] != list(QUALITY_MODES)):
        raise ValueError("Quality controls changed initialization, runtime or declared modes")
    baseline, = [p for p in original["plans"] if p["source_cohort"] == quality["source_cohort"]
                 and p["arm"] == quality["target"]]
    baseline_argv = baseline["argv"]
    original_entry = next(i for i, a in enumerate(baseline_argv)
                          if Path(a).name == "train_bounded_laya.py")
    adapted = []
    if [p["arm"] for p in quality["plans"]] != quality["first_comparison"]:
        raise ValueError("Quality arm order or mode coverage changed")
    for spec in quality["plans"]:
        argv = list(spec["argv"])
        entry = next(i for i, a in enumerate(argv) if Path(a).name == "train_bounded_laya.py")
        mode = argv.index("--pair-supervision")
        if (argv.count("--pair-supervision") != 1 or argv[mode + 1] != spec["arm"]
                or Path(argv[entry]) != Path(quality["training_overlay"]) / "train_bounded_laya.py"
                or argv[entry + 3] != spec["output"]
                or argv[argv.index("--compute-phase") + 1] != spec["compute_phase"]
                or spec["source_cohort"] != quality["source_cohort"]
                or spec["cwd"] != baseline["cwd"]):
            raise ValueError("Quality overlay or output binding differs from the declared arm")
        del argv[mode:mode + 2]
        argv[entry] = baseline_argv[original_entry]
        argv[entry + 3] = baseline["output"]
        argv[argv.index("--compute-phase") + 1] = baseline["compute_phase"]
        if argv != baseline_argv:
            raise ValueError("Quality comparison changed matched original training budget/recipe")
        expected_path = ":".join((str(Path(quality["base_runtime"]) / "src"),
                                  quality["training_overlay"],
                                  str(Path(quality["base_runtime"]) / "tools")))
        if (spec["environment"]["PYTHONPATH"] != expected_path
                or {k: v for k, v in spec["environment"].items() if k != "PYTHONPATH"}
                != {k: v for k, v in baseline["environment"].items() if k != "PYTHONPATH"}):
            raise ValueError("Quality comparison changed runtime imports or declared environment")
        adapted.append({**copy.deepcopy(spec), "arm": quality["target"],
                        "quality_mode": spec["arm"]})
    return {"source_version": original["source_version"] + "+quality-supervision-frozen-overlay-v1",
        "protocol": original["protocol"], "plans": adapted,
        "original_plan_source_version": original["source_version"],
        "quality_runtime": quality["base_runtime"], "quality_overlay": quality["training_overlay"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quality_plan", type=Path)
    parser.add_argument("original_plan", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    quality, original = read_json(args.quality_plan), read_json(args.original_plan)
    plan = quality_analysis_plan(quality, original)
    spec, = [p for p in plan["plans"] if p["run_id"] == args.run_id]
    result = analyze(plan, args.run_id, quality_mode=cast(QualityMode, spec["quality_mode"]))
    result.update(quality_plan=str(args.quality_plan.resolve()),
        original_plan=str(args.original_plan.resolve()),
        comparison_limit=quality["legacy_comparison_limit"],
        cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
        model_calls=0, no_sha_validation=True)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "analysis.json", result)
    print(result["status"], result["in_memory_selection"])


if __name__ == "__main__":
    main()
