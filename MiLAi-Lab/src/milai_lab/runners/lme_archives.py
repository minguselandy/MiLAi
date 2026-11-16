"""Archive terminal LME cases with the existing lossless common-base format."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.case_archive import archive_case, restore_case
from milai_lab.runners.lme_continuation import prediction_roots


def _inside(root: Path, relative: str) -> Path:
    path = (root/relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Case archive paths must stay inside the prediction collection")
    return path


def archive_lme_cases(predictions: Path, scores: Path, *, source_version: str) -> dict[str, Any]:
    """After prediction/scoring close, preserve all attempted runtimes including failures.

    The existing archive function compares every reconstructed byte before removing
    a case directory. Templates, predictions, scoring outputs and cohort denominators
    remain in place. Restore a case explicitly for later Store review or re-scoring.
    """
    predictions, scores = predictions.resolve(), scores.resolve()
    generation, grading = read_json(predictions/"driver.json"), read_json(scores/"driver.json")
    if generation["status"] not in {
            "COMPLETED", "COMPLETED_WITH_RETAINED_FAILURES", "FAILED"} or grading["status"] not in {
            "COMPLETED", "COMPLETED_WITH_UNSCORED_POSITIONS", "FAILED"}:
        raise ValueError("Close prediction and scoring phases before archiving cases")
    if Path(grading["predictions"]).resolve() != predictions or [c["question_id"]
            for c in generation["cases"]] != [c["question_id"] for c in grading["cases"]]:
        raise ValueError("Scoring must refer to this complete prediction cohort")
    entries = []
    owners = prediction_roots(predictions)
    for case in generation["cases"]:
        if "runtime" not in case:
            continue
        owner = Path(case.get("owner_predictions", predictions)).resolve()
        if owner not in owners:
            raise ValueError("Case owner is outside the declared prediction ancestry")
        runtime = _inside(owner, case["runtime"])
        parent = _inside(owner, f"memory/{case['pool']}/cases")
        base = _inside(owner, f"memory/{case['pool']}/template")
        if runtime.parent != parent or not runtime.name.isdecimal() or not base.is_dir():
            raise ValueError("Runtime must be a declared case with its retained template")
        if not runtime.is_dir():
            raise FileNotFoundError(f"Declared case runtime is missing: {runtime}")
        entries.append({"row": case["row"], "prediction_status": case["status"],
            "scoring_status": grading["cases"][case["row"]]["status"],
            "owner_predictions": str(owner),
            "runtime": str(runtime.relative_to(owner)),
            "base": str(base.relative_to(owner)),
            "archive": f"case-archives/case-{case['row']:04d}.tar.gz", "status": "PENDING"})
    actual = {p.resolve() for owner in owners
              for p in (owner/"memory").glob("*/cases/*") if p.is_dir()}
    declared = {_inside(Path(e["owner_predictions"]), e["runtime"]) for e in entries}
    if actual != declared or len(declared) != len(entries):
        raise ValueError("Retain a unique declared mapping for every actual case directory")
    if any(_inside(Path(e["owner_predictions"]), e["base"]).is_relative_to(case)
           or case.is_relative_to(_inside(Path(e["owner_predictions"]), e["base"]))
           for e in entries for case in declared):
        raise ValueError("Retained templates must be separate from archived case directories")
    output = predictions/"case-archives"
    output.mkdir(exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {"schema": "lme_case_archives_v1", "status": "RUNNING",
        "source_version": source_version, "scores": str(scores), "cases": entries,
        "planned_question_count": len(generation["cases"]), "original_outcomes_changed": False,
        "retention": "Complete unchanged templates plus per-case fixed-offset byte blocks; "
                     "all predictions, scoring outputs and unattempted positions retained",
        "no_sha_validation": True, "automatic_retry": False, "ledger_recorded": False}
    write_json(output/"index.json", report)
    try:
        for entry in entries:
            entry["status"] = "ARCHIVING"
            write_json(output/"index.json", report)
            owner = Path(entry["owner_predictions"])
            result = archive_case(_inside(owner, entry["runtime"]),
                _inside(predictions, entry["archive"]), _inside(owner, entry["base"]))
            entry.update(status="ARCHIVED", details=result)
            write_json(output/"index.json", report)
        report.update(status="COMPLETED", archived_cases=len(entries),
            original_case_bytes=sum(e["details"]["uncompressed_bytes"] for e in entries),
            archive_bytes=sum(e["details"]["archive_bytes"] for e in entries))
    except BaseException as error:
        report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report["compute"] = {"cpu_seconds": time.process_time()-cpu,
                             "wall_seconds": time.perf_counter()-started}
        write_json(output/"index.json", report)
    return report


def restore_lme_case(predictions: Path, row: int) -> Path:
    """Restore one independent runtime to its original path; archive/base stay retained."""
    predictions = predictions.resolve()
    index = read_json(predictions/"case-archives/index.json")
    if index["schema"] != "lme_case_archives_v1":
        raise ValueError("Unsupported LME case archive index")
    entry, = [e for e in index["cases"] if e["row"] == row and e["status"] == "ARCHIVED"]
    owner = Path(entry.get("owner_predictions", predictions)).resolve()
    if owner not in prediction_roots(predictions):
        raise ValueError("Restore owner is outside the declared prediction ancestry")
    started, cpu = time.perf_counter(), time.process_time()
    restored = restore_case(_inside(predictions, entry["archive"]),
        _inside(owner, entry["base"]), _inside(owner, entry["runtime"]))
    # Keep restore observations outside the byte-identical restored runtime.
    write_json(predictions/"case-archives"/f"restore-{row:04d}.json", {
        "runtime": str(restored), "archive_retained": True, "base_retained": True,
        "cpu_seconds": time.process_time()-cpu, "wall_seconds": time.perf_counter()-started,
        "ledger_recorded": False, "no_sha_validation": True})
    return restored
