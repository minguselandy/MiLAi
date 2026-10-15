"""Partial replay reports retain missing/invalid outcomes without inventing pairs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from milai_lab.analysis.edit_results import evidence_replay_comparison, evidence_replay_summary
from milai_lab.harness.artifact_io import write_json


def _configure(root: Path, count: int) -> None:
    write_json(root / "actual-config.json", {
        "experiment_name": root.name, "evidence_variant": "S2",
        "evidence_replay": {"source_run": "actual-original-prefix", "questions": [
            {"owner": "owner", "session": 0, "question": index} for index in range(count)
        ]},
    })


def _prediction(root: Path, index: int, *, missing: bool = False) -> None:
    reader = {"calls": 1, "input_tokens": 10, "output_tokens": 2}
    ranker = {"calls": 1, "input_tokens": 3, "output_tokens": 1}
    write_json(root / f"predictions/halumem/owner/0/qa/{index}/complete.json", {
        "execution": "missing" if missing else "answered",
        "hypothesis": None if missing else "SECRET ANSWER BODY",
        "prediction_cost": {
            "models": {"reader": reader, "ranker": ranker},
            "stages": {"answer": {"reader": reader}, "ranking": {"ranker": ranker}},
            "embedding_tokens": 0, "elapsed_seconds": 1.25,
        },
    })


def _evaluation(root: Path, index: int, label: str | None, *, missing: bool = False) -> None:
    usage = {"calls": 1, "input_tokens": 5, "output_tokens": 1}
    write_json(root / f"evaluation/halumem/owner/0/qa/{index}/complete.json", {
        "record": {"uuid": "owner", "ssession_id": 0, "question_index": index,
                   "question": "SECRET QUESTION BODY", "answer": "SECRET GOLD BODY",
                   "evidence": ["SECRET EVIDENCE BODY"], "result_type": label},
        "judge_cost": {"models": {} if missing else {"judge": usage},
                       "stages": {} if missing else {"answer": {"judge": usage}},
                       "elapsed_seconds": 0 if missing else 0.5},
    })


def test_mixed_partial_checkpoints_define_denominators_costs_and_paired_coverage(
    tmp_path: Path,
) -> None:
    control, candidate = tmp_path / "control", tmp_path / "candidate"
    for root in (control, candidate):
        _configure(root, 7)
    for index, label in [(0, "Correct"), (1, None), (2, None), (3, "Correct"), (6, "Other")]:
        _prediction(control, index, missing=index == 2)
        _evaluation(control, index, label, missing=index == 2)
    # A begun prediction has no settled checkpoint; it is not a known missing answer.
    write_json(control / "native/halumem/owner/0/qa/4/retrieval.json", {})
    for index in (0, 1, 2, 3, 4, 6):
        _prediction(candidate, index)
    for index, label in [(0, "Hallucination"), (1, "Correct"), (2, "Correct"),
                         (4, "Correct"), (6, None)]:
        _evaluation(candidate, index, label)
    # These mutable files can be stale or temporarily shrink during scoring.
    write_json(control / "evidence-results.json", [{"correct": 999, "opportunities": 999}])
    write_json(candidate / "evidence-results.json", [])
    write_json(control / "terminal-score.json", {"status": "SCORED", "resources_settled": True})
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    report = evidence_replay_comparison(control, candidate)
    first, second = report["control"], report["candidate"]
    assert first["counts"] == {
        "planned": 7, "executed": 6, "answered": 4, "missing": 1, "not_run": 1,
        "unfinished_predictions": 1, "pending_score": 0, "scored": 5,
        "correct": 2, "invalid": 2, "unfinished": 1,
    }
    assert second["counts"]["pending_score"] == second["counts"]["unfinished"] == 1
    assert first["labels"] == {"Correct": 2, "invalid": 2, "missing": 1}
    assert first["questions"][6]["official_label"] == "Other"
    assert not first["score_complete"] and not second["score_complete"]
    assert first["correct_ratio_all_opportunities"] is None
    assert second["correct_ratio_all_opportunities"] is None
    assert first["scored_subset"]["correct_ratio"] == 2 / 5
    assert report["paired_coverage"]["completed_scored_common"] == 4
    assert report["paired_coverage"]["planned_common_ratio"] == 4 / 7
    paired = report["paired_scored"]
    assert paired["candidate_only_correct"] == 2
    assert paired["control_only_correct"] == 1
    assert paired["both_noncorrect"] == 1 and paired["net_correct"] == 1
    assert paired["candidate_only_question_ids"] == [
        "halumem/owner/0/qa/1", "halumem/owner/0/qa/2",
    ]
    assert not report["full_comparison_complete"]
    assert first["prediction_cost"]["models"]["reader"] == {
        "calls": 5, "input_tokens": 50, "output_tokens": 10,
    }
    assert first["prediction_cost"]["stages"]["ranking"]["ranker"]["calls"] == 5
    assert first["prediction_cost"]["unfinished_questions_excluded"] == 1
    assert not first["prediction_cost"]["coverage_complete_for_executed"]
    assert first["judge_cost"]["models"]["judge"]["calls"] == 4
    assert second["judge_cost"]["pending_evaluations_excluded"] == 1
    assert "SECRET" not in json.dumps(report)
    assert all(path.read_bytes() == contents for path, contents in before.items())

    unscored = tmp_path / "unscored"
    _configure(unscored, 7)
    _prediction(unscored, 0)
    assert evidence_replay_comparison(control, unscored)["paired_scored"] is None
    assert evidence_replay_summary(unscored)["labels"] == {}

    closed = tmp_path / "closed"
    _configure(closed, 3)
    for index, label in enumerate(["Correct", None, None]):
        _prediction(closed, index, missing=index == 2)
        _evaluation(closed, index, label, missing=index == 2)
    partial: dict[str, Any] = evidence_replay_summary(closed)
    assert partial["counts"]["scored"] == 3 and partial["correct_ratio_all_opportunities"] is None
    write_json(closed / "terminal-score.json", {"status": "SCORED", "resources_settled": True})
    complete = evidence_replay_summary(closed)
    assert complete["score_complete"] and complete["correct_ratio_all_opportunities"] == 1 / 3
    assert complete["labels"] == {"Correct": 1, "invalid": 1, "missing": 1}
