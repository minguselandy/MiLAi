from __future__ import annotations

from evals.dg25.plan_execution import build_s2_reports


def test_s2_r0p_is_exactly_equivalent_to_legacy_r0_semantics() -> None:
    _traces, _validation, equivalence = build_s2_reports()

    assert equivalence["arm_order"] == ["R0", "R0P"]
    assert equivalence["exact_semantic_equivalence"] is True
    assert all(equivalence["dimension_equivalence"].values())
    assert equivalence["r0_repository_calls"] == 1
    assert equivalence["r0p_repository_calls"] == 1
    assert equivalence["r0p_full_semantics_recomputations"] == 1
    assert equivalence["r0p_state_epoch_increment"] == 1
    assert equivalence["r0p_baseline_action_digest_preserved"] is True
    assert equivalence["r0p_baseline_candidate_cap_preserved"] is True


def test_s2_composes_proof_and_discovery_with_bounded_cost() -> None:
    traces, _validation, _equivalence = build_s2_reports()
    composition = traces["proof_discovery_composition"]

    assert [
        item["action_role"] for item in composition["compilation"]["plan"]["actions"]
    ] == ["EVIDENCE_DISCOVERY", "PROOF_CLOSURE"]
    assert composition["channels_retained"] == ["FTS_RAW", "TEMPORAL_EVENT"]
    assert composition["result_evidence_ids"] == ["event-proof", "raw-discovery"]
    assert composition["bounded_range_scan_proof_present"] is True
    assert traces["cost_ledger"]["proof_discovery"] == {
        "repository_calls": 2,
        "planned_candidate_cap_sum": 16,
        "extra_state_passes": 1,
        "range_rows_scanned": 1,
    }


def test_s2_invalid_plans_fail_before_repository_execution() -> None:
    _traces, validation, _equivalence = build_s2_reports()

    assert validation["hard_gate"]["passed"] is True
    assert validation["counts"] == {
        "fresh_accepted": 2,
        "negative_total": 3,
        "negative_rejected_before_repository_call": 3,
    }
    assert {
        item["scenario"]: item["expected_reason"]
        for item in validation["negative_records"]
    } == {
        "STALE_SNAPSHOT": "SNAPSHOT_IDENTITY_MISMATCH",
        "UNREGISTERED_ACTION": "UNREGISTERED_ACTION",
        "BUDGET_OVERFLOW": "REPOSITORY_CALL_BUDGET_EXCEEDED",
    }
    assert validation["stale_plan_accepted"] == 0
    assert validation["infeasible_or_unregistered_action_executed"] == 0
    assert validation["aggregate_budget_overflow_executed"] == 0
    assert validation["automatic_retries"] == 0
