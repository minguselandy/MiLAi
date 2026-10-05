"""Missing opportunities and source clusters remain explicit in result analysis."""

from __future__ import annotations

import pytest

from milai_lab.analysis.edit_results import (
    halumem_suite,
    longmemeval_categories,
    paired_interval,
    receipt_effect,
    user_metrics,
    writer_operations,
)
from milai_lab.harness.artifact_io import write_json


def test_paired_user_resampling_does_not_turn_calls_into_independent_users():
    result = paired_interval([0.2, 0.7], [0.4, 0.9], repeats=200)
    assert result["users"] == 2 and result["resamples"] == 200
    assert abs(result["difference_second_minus_first"] - 0.2) < 1e-9
    assert all(abs(value - 0.2) < 1e-9 for value in result["percentile_95_interval"])


def test_all_opportunities_include_empty_update_retrieval_and_invalid_judgments():
    records = {
        "memory_integrity_records": [
            {"memory_source": "primary", "memory_integrity_score": 2},
            {"memory_source": "primary", "memory_integrity_score": None},
        ],
        "memory_accuracy_records": [
            {"memory_accuracy_score": 2},
            {"memory_accuracy_score": None},
        ],
        "memory_update_records": [
            {"memory_update_type": "Correct"},
            {"memory_update_type": None},
        ],
        "question_answering_records": [
            {"result_type": "Correct"},
            {"result_type": None},
        ],
    }
    metrics = user_metrics(records, {"total_updates": 4, "empty_update_retrieval": 2})
    assert metrics["update_correct_all_opportunities"] == 0.25
    assert metrics["update_correct_scored"] == 0.5
    assert metrics["update_correct_valid"] == 1
    assert metrics["denominators"]["update_unscored_opportunities"] == 2
    assert metrics["qa_correct_all"] == 0.5 and metrics["qa_correct_valid"] == 1
    assert metrics["formed_memory_accuracy_all"] == 0.5
    assert metrics["formation_recall_all"] == 0.5


def test_missing_arms_produce_no_comparative_effect_and_longmem_rows_get_no_false_ci(tmp_path):
    incomplete = halumem_suite(tmp_path, ["B0", "B1", "B2", "M"])
    assert incomplete["status"] == "INCOMPLETE" and incomplete["paired_effects"] is None
    result = longmemeval_categories(
        [
            {"question_id": "one", "question_type": "knowledge-update", "autoeval_label": True},
            {"question_id": "two_abs", "question_type": "knowledge-update", "autoeval_label": None},
        ]
    )
    assert result["categories"]["total"]["accuracy_all"] == 0.5
    assert result["categories"]["total"]["accuracy_valid"] == 1
    assert result["categories"]["abstention"]["opportunities"] == 1
    assert result["categories"]["abstention"]["accuracy_valid"] is None
    assert result["interval"] is None


def test_prepared_ranges_no_change_and_pending_http_are_not_successful_writes(tmp_path):
    maintenance = tmp_path / "maintenance" / "halumem" / "owner"
    for session, batches in (
        (0, [[{"start": 0, "end": 8}]]),
        (1, [[{"start": 0, "end": 3}], [{"start": 3, "end": 7}]]),
    ):
        write_json(
            maintenance / str(session) / "source-coverage.json",
            {
                "original_characters": 8 if session == 0 else 7,
                "covered_characters": 8 if session == 0 else 7,
                "batches": batches,
            },
        )
    batch = maintenance / "0" / "batch-0000"
    write_json(
        batch / "proposals.json",
        [
            {"action": "create"},
            {"action": "update", "edits": [{"operation": "replace"}]},
            {"action": "update", "edits": [{"operation": "delete"}]},
        ],
    )
    for ordinal, receipt in enumerate(
        [
            {"ok": True, "status": "committed"},
            {"ok": True, "status": "no_change"},
            {"ok": False, "status": "rejected", "reason": "FunctionalRejection: outside_scope"},
        ]
    ):
        write_json(batch / f"receipt-{ordinal}.json", receipt)
    write_json(batch / "complete.json", {})
    write_json(maintenance / "0" / "complete.json", {"extracted_memories": ["formed"]})
    write_json(tmp_path / "evaluation" / "halumem" / "owner" / "0" / "complete.json", {})
    http = tmp_path / "http" / "halumem" / "owner" / "0" / "writer" / "0"
    write_json(http / "request.json", {})
    write_json(http / "response.json", {})
    failed = maintenance / "1" / "batch-0000"
    write_json(
        failed / "writer-failure.json",
        {
            "type": "ValueError",
            "message": "Context unavailable without loss: 66000 input tokens",
            "additional_attempts": 0,
        },
    )
    write_json(failed / "complete.json", {})
    write_json(tmp_path / "http" / "halumem" / "owner" / "1" / "writer" / "1" / "request.json", {})

    result = writer_operations(tmp_path, "owner", [0, 1, 2])
    assert result["expected_sessions"] == 3
    assert result["counts"]["prepared_sessions"] == 2
    assert result["counts"]["maintenance_completed_sessions"] == 1
    assert result["counts"]["prepared_characters"] == 15
    assert result["counts"]["characters_in_recorded_requests"] == 12
    assert result["counts"]["characters_in_confirmed_responses"] == 8
    assert result["requests_without_confirmed_responses"] == 1
    assert result["pending_prepared_batches"] == 1
    assert result["counts"]["confirmed_committed_operations"] == 1
    assert result["counts"]["accepted_no_change_operations"] == 1
    assert result["counts"]["rejected_operations"] == 1
    assert result["committed_actions"] == {"create": 1}
    assert result["first_attempt_writer_failures"] == {"context_unavailable_before_http": 1}
    assert result["counts"]["additional_writer_attempts"] == 0


def test_a_completed_empty_writer_list_remains_separate_from_failed_writer(tmp_path):
    session = tmp_path / "maintenance" / "halumem" / "owner" / "0"
    write_json(
        session / "source-coverage.json",
        {
            "original_characters": 3,
            "covered_characters": 3,
            "batches": [[{"start": 0, "end": 3}]],
        },
    )
    write_json(session / "batch-0000" / "proposals.json", [])
    write_json(session / "batch-0000" / "complete.json", {})
    result = writer_operations(tmp_path, "owner", None)
    assert result["expected_sessions"] is None
    assert result["counts"]["writer_returned_empty_list_batches"] == 1
    assert result["first_attempt_writer_failures"] == {}
    assert result["committed_actions"] == {}


def test_replay_of_an_original_commit_is_not_a_pure_no_change_or_second_write():
    assert (
        receipt_effect(
            {
                "ok": True,
                "status": "no_change",
                "replayed": True,
                "original_status": "committed",
            }
        )
        == "replayed_commit"
    )
    assert (
        receipt_effect({"ok": True, "status": "committed", "replayed": True}) == "replayed_commit"
    )
    assert receipt_effect({"ok": True, "status": "no_change"}) == "no_change"
    assert (
        receipt_effect(
            {
                "ok": True,
                "status": "no_change",
                "replayed": True,
                "original_status": "no_change",
            }
        )
        == "no_change"
    )
    assert (
        receipt_effect(
            {
                "ok": True,
                "status": "no_change",
                "replayed": True,
                "original_status": "unknown",
            }
        )
        == "other_or_unconfirmed"
    )
    assert receipt_effect({"ok": False, "status": "rejected", "replayed": True}) == "rejected"
    assert (
        receipt_effect({"ok": True, "status": "no_change", "replayed": True})
        == "other_or_unconfirmed"
    )


def test_a_response_without_its_original_request_is_not_confirmed_exposure(tmp_path):
    write_json(
        tmp_path / "maintenance" / "halumem" / "owner" / "0" / "source-coverage.json",
        {
            "original_characters": 3,
            "covered_characters": 3,
            "batches": [[{"start": 0, "end": 3}]],
        },
    )
    write_json(tmp_path / "http" / "halumem" / "owner" / "0" / "writer" / "0" / "response.json", {})
    with pytest.raises(ValueError, match="original recorded request"):
        writer_operations(tmp_path, "owner", [0])
