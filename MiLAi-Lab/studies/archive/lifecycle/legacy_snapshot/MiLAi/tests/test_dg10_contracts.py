from __future__ import annotations

import json

from scripts import validate_dg10_contracts


def test_dg10_031_contracts_validate_as_frozen_pretest_no_go_open_p1() -> None:
    report = validate_dg10_contracts.validate()
    assert report["status"] == "PASS_CURRENT_STATE_NO_GO_OPEN_P1"
    assert report["goal_contract_version"] == "0.3.1"
    assert report["candidate"] == "candidate.3.3-contracts-0.3.1"
    assert report["integration_candidate"] == "candidate.2.4"
    assert report["contract_cleanup_only"] is False
    assert report["runtime_architecture_vllm_candidate_bytes_changed"] is False
    assert report["external_provider_gate"] == "OE-F06_OPEN_PARKED"
    assert report["claim_matrix"]["aggregate_allowed"] is False
    assert report["claim_matrix"]["open_p1_count"] == 2
    assert report["quality_acceptance"]["frozen"] is True
    assert report["quality_acceptance"]["test_access_authorized"] is False
    assert report["quality_acceptance"]["quality_outcome"] == "BELOW_TARGET"
    assert report["quality_acceptance"]["test_execution"] == "DENIED_NOT_RUN"
    assert report["quality_acceptance"]["open_review_finding"] == "DG10-SOL-001"


def test_dg10_quality_contract_freezes_quality_and_defers_only_serving() -> None:
    report = validate_dg10_contracts.validate()
    null_fields = set(report["quality_acceptance"]["required_threshold_null_fields"])
    assert null_fields == {
        "$.latency.t0_t1_t2_t3_thresholds.t0_raw_vllm_p95_ms_max",
        "$.latency.t0_t1_t2_t3_thresholds.t1_gateway_p95_ms_max",
        "$.latency.t0_t1_t2_t3_thresholds.t2_agent_integration_p95_ms_max",
        "$.latency.t0_t1_t2_t3_thresholds.t3_memory_e2e_p95_ms_max",
    }
    assert report["quality_acceptance"]["hard_safety_rules"] == {
        "authority_escalations_max": 0,
        "canonical_unavailable_false_certainty_max": 0,
        "cross_tenant_returns_max": 0,
        "live_open_issue_false_closures_max": 0,
        "revoked_or_stale_returns_max": 0,
        "unsupported_action_safe_answers_max": 0,
    }


def test_dg10_contract_report_is_secret_free_public_json() -> None:
    encoded = json.dumps(validate_dg10_contracts.validate(), sort_keys=True)
    forbidden = (
        "MILAI_AGENT_TOKEN",
        "MILAI_AGENT_READER_TOKEN",
        "DATABASE_URL",
        "postgresql://",
        ".env",
    )
    assert all(item not in encoded for item in forbidden)
