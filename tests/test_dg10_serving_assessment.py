from __future__ import annotations

from scripts import run_dg10_serving_assessment as assessment


def test_bound_serving_assessment_recomputes_and_denies_bmg04() -> None:
    report = assessment._load_bound(
        assessment.SERVING_REPORT, assessment.SERVING_REPORT_SHA256
    )
    sidecar = assessment._load_bound(
        assessment.SERVING_SIDECAR, assessment.SERVING_SIDECAR_SHA256
    )
    result = assessment.build_assessment(report, sidecar)
    assert result["recomputation"]["public_record_count"] == 96
    assert result["recomputation"]["raw_record_count"] == 96
    assert result["native_call_accounting"]["T2"]["failed_requests"] == 9
    assert result["native_call_accounting"]["T2"]["native_events_all_attempts"] == 24
    assert result["bmg04_exit_criteria"]["result"] == "NO_GO_CHARACTERIZATION_ONLY"
    assert result["release_effect"]["may_authorize_test"] is False


def test_tool_boundary_has_one_completed_recall_per_t3_request() -> None:
    report = assessment._load_bound(
        assessment.SERVING_REPORT, assessment.SERVING_REPORT_SHA256
    )
    sidecar = assessment._load_bound(
        assessment.SERVING_SIDECAR, assessment.SERVING_SIDECAR_SHA256
    )
    raw_index = assessment._validate_sidecar(report, sidecar)
    timings = assessment._tool_boundary_metrics(raw_index)
    assert set(timings) == {"c1", "c4", "c8"}
    assert all(value["sample_count"] == 8 for value in timings.values())
    assert all(value["minimum_ms"] >= 0 for value in timings.values())


def test_pair_delta_marks_t2_success_denominator_noncomparable() -> None:
    report = assessment._load_bound(
        assessment.SERVING_REPORT, assessment.SERVING_REPORT_SHA256
    )
    cells = assessment._validate_and_summarize_cells(report)
    delta = assessment._pair_delta(
        cells, left_tier="T2", right_tier="T1", concurrency=1
    )
    assert delta["success_denominators"] == {
        "left": 3,
        "right": 8,
        "equal_full_denominators": False,
    }
    assert delta["latency_delta_comparable"] is False
