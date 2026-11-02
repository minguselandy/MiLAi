"""Actual-shaped CPU receipts select quality, even when cost labels prefer another point."""
import copy
import json
from pathlib import Path

import pytest
from test_saved_feedback_fit import emit_job, fixture

from analyze_feedback_fit import choose_feedback_checkpoint
from analyze_saved_feedback_fit import inputs_for_fit, select, verify_retention
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from quality_feedback import score_quality_feedback
from retrieval_feedback import RESOURCE_FIELDS, score_feedback


def quality_fixture(tmp_path):
    plan, native = fixture(tmp_path)
    native["status"] = "TERMINAL_NATIVE_QUALITY_CURVE_VERIFIED;SAVED_RELOAD_SELECTION_PENDING"
    native["pair_supervision"] = native["recipe"]["pair_supervision"] = "quality-tie"
    fit = plan["fits"][0]
    fit.update(pair_supervision="quality-tie", selection_rule="pure_quality_directional",
               selection_targets=["answer"])
    native["in_memory_selection"] = {"answer": {"update": 0}}
    root = Path(native["recipe"]["output"])
    run = read_json(root / "run.json")
    run["pair_supervision"] = "quality-tie"
    write_json(root / "run.json", run)
    data = Path(native["recipe"]["data"])
    old, feedback = read_jsonl(data / "dev.jsonl"), read_jsonl(data / "feedback.jsonl")
    for i, row in enumerate(feedback):
        pair = row["feedback"]["comparisons"][0]
        pair.update(answer="left" if i == 0 else "right", delivery="unknown", basis={
            "quality_before_resource_tiebreak": {"answer": "tie" if i == 0 else "right",
                                                "delivery": "unknown"},
            "resource_order": {"left": dict.fromkeys(RESOURCE_FIELDS, 0),
                "right": {**dict.fromkeys(RESOURCE_FIELDS, 0), "read_operations": 1}}})
    for name, rows in (("feedback", feedback), ("legacy", feedback[:1]),
                       ("combined", old+feedback)):
        (data / (name + ".jsonl")).write_text("".join(json.dumps(row)+"\n" for row in rows))
    for point in native["curve"]:
        predictions = [read_json(root / "feedback-dev" / str(point["update"]) / f"{i}.json")
                       for i in range(len(feedback))]
        point["feedback-dev"] = {t: score_feedback(feedback, predictions, t)
                                  for t in ("answer", "delivery")}
        point["pure_quality"] = {t: score_quality_feedback(feedback, predictions, t)
                                  for t in ("answer", "delivery")}
        point["quality_cost"] = {t: score_quality_feedback(feedback, predictions, t, "quality-cost")
                                 for t in ("answer", "delivery")}
    for job in [plan["common_base"], *fit["candidates"][1:]]:
        emit_job(plan, native, job)
    return plan, native


def test_quality_saved_selection_uses_same_primary_metric_then_reports_old_skill_loss(tmp_path):
    plan, native = quality_fixture(tmp_path)
    result = select(plan, native)
    assert result["status"] == "SAVED_CPU_QUALITY_SELECTION_VERIFIED"
    assert result["deployment_selection"]["answer"]["update"] == 2
    assert choose_feedback_checkpoint(result["curve"], "answer")["update"] == 4
    assert result["pending_retention_updates"] == [2]
    job, = plan["fits"][0]["conditional_retention_jobs"]
    emit_job(plan, native, job)
    retained = verify_retention(plan, native, result)
    assert retained["status"] == (
        "SAVED_CPU_QUALITY_SELECTION_AND_RETENTION_VERIFIED;HOST_EVALUATION_PENDING")
    assert retained["selected_old_operation"]["answer"]["family_macro_acceptance"] == 0
    changed = copy.deepcopy(result)
    changed["deployment_selection"]["answer"].update(
        update=4, checkpoint=str(tmp_path / "checkpoint-4"))
    with pytest.raises(ValueError, match="after observing retention"):
        verify_retention(plan, native, changed)


def test_quality_mode_and_primary_definition_cannot_be_silently_dropped(tmp_path):
    plan, native = quality_fixture(tmp_path)
    del plan["fits"][0]["selection_rule"]
    with pytest.raises(ValueError, match="declared supervision and metric"):
        inputs_for_fit(plan, native)
