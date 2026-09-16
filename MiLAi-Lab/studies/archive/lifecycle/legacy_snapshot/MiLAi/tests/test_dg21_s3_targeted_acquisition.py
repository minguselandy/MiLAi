from __future__ import annotations

from pathlib import Path

from evals.dg21.targeted_acquisition import run_targeted_acquisition_matrix

_ROOT = Path(__file__).resolve().parents[1]


def test_dg21_s3_targeted_official_executor_matrix_passes() -> None:
    result = run_targeted_acquisition_matrix(_ROOT)

    assert result["status"] == "PASS_TARGETED_SOURCE_ADJACENCY"
    assert result["hard_gate"]["passed"]
    assert (
        result["metrics"]["target_requirement_attribution_numerator"]
        == (result["metrics"]["target_requirement_attribution_denominator"])
    )
    assert result["metrics"]["global_probe_count"] == 0
    assert result["metrics"]["repeated_candidate_accepted_count"] == 0
    assert result["metrics"]["unsupported_action_accepted_count"] == 0


def test_dg21_s3_source_and_adjacency_fail_closed() -> None:
    result = run_targeted_acquisition_matrix(_ROOT)

    assert result["adjacency"]["governance_violation_accepted_count"] == 0
    assert result["adjacency"]["anchor_count"] <= 2
    assert result["adjacency"]["max_items"] <= 4
    assert result["source_point"]["compiled_boundary"] == "CLOSED_OPEN"
    assert result["source_point"]["scan_axis"] == "SOURCE_OBSERVED_TIME"
    assert result["source_point"]["time_axis_substitution"] is False
    assert result["source_point"]["semantic_widening"] is False
    assert result["opened_9a_diagnosis"]["compiled"] is True


def test_dg21_s3_candidate_sweep_has_one_fixed_selected_policy() -> None:
    result = run_targeted_acquisition_matrix(_ROOT)
    sweep = result["semantic_candidate_sweep"]

    assert [item["candidate_cap"] for item in sweep] == [8, 12, 16]
    assert [item["effective_candidate_count"] for item in sweep] == [8, 12, 12]
    assert len({item["policy_digest"] for item in sweep}) == 1
    assert all(item["repository_probe_calls"] == 1 for item in sweep)
    assert all(item["acquisition_passes"] == 1 for item in sweep)
    assert result["safety"]["formal_holdout_consumed"] is False
