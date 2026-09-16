from __future__ import annotations

from evals.dg17.q6_preflight import build_q6_preflight


def test_q6_preflight_freezes_twenty_cells_without_external_calls() -> None:
    report = build_q6_preflight()

    assert report["status"] == "Q6_PREFLIGHT_COMPLETE_EXECUTION_AUTHORIZED"
    assert report["frozen_contract"]["case_count"] == 10
    assert report["frozen_contract"]["token_budgets"] == [512, 2048]
    assert report["frozen_contract"]["cell_count_per_executed_arm"] == 20
    assert len(report["case_matrix"]) == 10
    assert report["execution"] == {
        "runtime_started": False,
        "retrieval_calls": 0,
        "reader_calls": 0,
        "semantic_hint_calls": 0,
        "semantic_repair_calls": 0,
        "automatic_retries": 0,
        "external_experiments": "AUTHORIZED_BY_USER / SEALED_SCORING_NOT_STARTED",
    }
    assert report["formal_holdout_consumed"] is False
    assert report["formal_source_id_overlap"] == []
    assert report["execution_authorized"] is True
    assert "ANSWER_BEARING_LABEL_INDEPENDENT_REVIEW_PENDING" in report[
        "blocking_conditions"
    ]


def test_q6_preflight_binds_product_gates_and_reader_em_boundary() -> None:
    report = build_q6_preflight()
    readiness = report["readiness"]
    stability = report["reader_exact_match_stability_boundary"]
    bindings = report["artifact_bindings"]

    assert readiness["q4_temporal_cases_expected"] == 7
    assert readiness["q4_temporal_case_denominator"] == 7
    assert readiness["q4_wrong_complete"] == 0
    assert readiness["q5_wrong_complete"] == 0
    assert readiness["current10_deterministic_operator_expected"] == 10
    assert readiness["current10_deterministic_operator_denominator"] == 10
    assert readiness["q3c_live_shadow_characterized"] is True
    assert readiness["q6_live_matched_receipt_available"] is False
    assert readiness["local_deterministic_gate_passed"] is True
    assert readiness["answer_bearing_annotation_manifest_available"] is True
    assert (
        readiness["answer_bearing_annotation_independent_review_complete"] is False
    )
    assert readiness["q0_receipt_lineage_disposition_available"] is True
    assert readiness["q0_multiseed_oracle_receipt_available"] is True
    assert readiness["q0_authoritative_oracle_receipt_available"] is False
    assert readiness["q1r_stable_context_implementation_available"] is True
    assert readiness["q1r_same_snapshot_matched_receipt_available"] is True
    assert readiness["q1r_context_stability_gate_passed"] is True
    assert readiness["q3a_typed_contract_gate_passed"] is True
    assert readiness["q3b_declared_fixture_gate_passed"] is True
    assert readiness["q3_typed_requirement_identity_gate_passed"] is True
    assert bindings["local_deterministic_gate"]["status"] == "PASS"
    assert bindings["local_deterministic_gate"]["sha256"]
    assert bindings["evidence_atom_v01_compatibility_disposition"]["status"] == (
        "DOCUMENT"
    )
    assert bindings["evidence_atom_v01_compatibility_disposition"]["sha256"]
    assert bindings["answer_bearing_annotation_manifest"]["status"] == "DOCUMENT"
    assert bindings["answer_bearing_annotation_manifest"]["sha256"]
    assert bindings["q0_receipt_lineage_disposition"]["status"] == "DOCUMENT"
    assert bindings["q0_multiseed_oracle"]["status"] == (
        "Q0_MULTI_SEED_ORACLE_CHARACTERIZED"
    )
    assert report["arms"]["DG17_MINIMAL_SEMANTIC_QUERY_HINT_EXECUTED"].startswith(
        "NOT_AUTHORIZED"
    )
    assert all(
        row["deterministic_operator_expected"] for row in report["case_matrix"]
    )
    assert all(
        row["deterministic_auxiliary_model_calls"] == 0
        for row in report["case_matrix"]
    )
    assert stability["strict_em_boundary_observed"] is True
    assert stability["same_payload_reader_variability_signal"] is True
    assert stability["retrieval_rework_indicated"] is False
    assert report["release_claim_authorized"] is False
