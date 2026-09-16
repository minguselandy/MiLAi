from __future__ import annotations

from pathlib import Path

from evals.dg21.type_directed_replay import run_type_directed_replay

_ROOT = Path(__file__).resolve().parents[1]


def test_dg21_s2_replays_all_matched_records_with_semantic_equivalence() -> None:
    result = run_type_directed_replay(_ROOT)

    assert result["status"] == "PASS_TYPE_DIRECTED_SEMANTICS_AND_FAST_STOP"
    assert result["hard_gate"]["passed"]
    assert result["metrics"]["matched_record_count"] == 20
    assert all(item["exact_span_equivalent"] for item in result["records"])
    assert all(item["match_possible_equivalent"] for item in result["records"])
    assert all(item["requirement_state_equivalent"] for item in result["records"])
    assert all(item["sufficiency_equivalent"] for item in result["records"])


def test_dg21_s2_prunes_frozen_type_denominator_before_binding() -> None:
    result = run_type_directed_replay(_ROOT)
    archive = result["archive_denominator_audit"]

    assert archive["legacy_type_incompatible_count"] == 1997
    assert archive["directed_materialized_type_incompatible_count"] == 0
    assert archive["materialized_type_incompatible_reduction"] >= 0.8
    assert archive["binding_evaluation_reduction"] >= 0.7
    assert result["metrics"]["target_requirement_binding_recall_regression"] == 0
    assert result["metrics"]["required_evidence_set_coverage_regression"] == 0


def test_dg21_s2_terminal_semantics_are_safe_and_zero_work() -> None:
    result = run_type_directed_replay(_ROOT)
    terminal = {item["terminal_disposition"] for item in result["records"]}

    assert "COMPLETE" in terminal
    assert "NO_TARGETABLE_REQUIREMENT" in terminal
    assert "DETERMINISTIC_COMPLETE" not in terminal
    assert result["metrics"]["wrong_complete"] == 0
    assert result["metrics"]["exact_complete_auxiliary_work_count"] == 0
    assert result["safety"]["provider_calls"] == 0
    assert result["safety"]["reader_calls"] == 0
    assert result["safety"]["candidate_budget_changes"] == 0
