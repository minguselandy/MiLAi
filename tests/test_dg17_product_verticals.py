from __future__ import annotations

from evals.dg17.product_verticals import Q4_CASE_IDS, build_product_vertical_reports


def test_q4_product_vertical_covers_all_temporal_cases_without_wrong_complete() -> None:
    q4, _q5 = build_product_vertical_reports()

    assert q4["status"] == "Q4_PRODUCT_VERTICAL_COMPLETE"
    assert tuple(case["case_id"] for case in q4["cases"]) == Q4_CASE_IDS
    assert q4["gate"] == {
        "required_case_count": 7,
        "observed_case_count": 7,
        "operator_expected": 7,
        "wrong_complete": 0,
        "source_event_system_time_separation_traced": True,
        "bounded_range_contract": "CLOSED_OPEN_WITH_EVENT_INTERVAL_OVERLAP",
        "top_k_used_as_completeness": False,
    }
    assert q4["external_model_calls"] == 0
    assert q4["product_case_specific_branches"] == 0
    assert q4["efficiency"]["development_gate_passed"] is True
    assert all(case["hidden_model_calls"] == 0 for case in q4["cases"])
    assert all(case["canonical_mutation"] is False for case in q4["cases"])


def test_q5_product_vertical_enforces_join_count_and_preference_boundaries() -> None:
    _q4, q5 = build_product_vertical_reports()
    traces = {trace["trace_id"]: trace for trace in q5["traces"]}

    assert q5["status"] == "Q5_PRODUCT_VERTICAL_COMPLETE"
    assert q5["gate"]["wrong_complete"] == 0
    assert q5["gate"]["preference_canonical_promotion"] == 0
    assert q5["external_model_calls"] == 0
    assert q5["product_case_specific_branches"] == 0
    assert traces["cross-session-required-slots"]["value"] == 12
    assert traces["cross-session-required-slots"]["status"] == "COMPLETE"
    assert traces["same-purpose-join-rejection"]["reason"] == (
        "JOIN_PURPOSE_INCOMPATIBLE"
    )
    assert traces["bounded-count-unknown-event-time"]["reason"] == (
        "EVENT_TIME_UNRESOLVED"
    )
    preference = traces["preference-evidence-derived-view"]
    assert preference["authority_class"] == "EVIDENCE_ONLY"
    assert preference["view_class"] == "DERIVED_VIEW"
    assert preference["canonical"] is False
    assert all(trace["safety_expected"] for trace in traces.values())
    assert all(trace["hidden_model_calls"] == 0 for trace in traces.values())
    assert all(trace["canonical_mutation"] is False for trace in traces.values())
