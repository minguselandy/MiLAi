from __future__ import annotations

from pathlib import Path

from evals.dg23.budget_causality import (
    AFFECTED_CASE_ID,
    build_budget_causality_audit,
)

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s1_audits_all_frozen_cells_without_calls_or_labels() -> None:
    audit = build_budget_causality_audit(ROOT)

    assert audit["status"] == "PASS_DG22_BUDGET_CAUSALITY_AUDIT"
    assert audit["hard_gate"]["passed"]
    assert len(audit["records"]) == 20
    assert len(audit["first_divergence_traces"]) == 10
    assert audit["label_boundary"]["source_labels_loaded"] is False
    assert audit["safety"]["reader_calls"] == 0
    assert audit["safety"]["provider_calls"] == 0


def test_dg23_s1_reproduces_affected_case_and_locates_first_divergence() -> None:
    audit = build_budget_causality_audit(ROOT)
    affected = audit["affected_case"]

    assert affected["case_id"] == AFFECTED_CASE_ID
    assert len(affected["budget_512_selected_source_refs"]) == 3
    assert len(affected["budget_2048_selected_source_refs"]) == 8
    assert affected["budget_512_answer"] == "Tom"
    assert affected["budget_2048_answer"] == "Mark and Sarah"
    assert affected["budget_512_seed"] != affected["budget_2048_seed"]
    assert (
        affected["first_divergent_layer"]
        == "ACQUISITION_SELECTED_CANDIDATE_SNAPSHOT"
    )


def test_dg23_s1_emits_each_required_machine_audit_layer() -> None:
    audit = build_budget_causality_audit(ROOT)
    required = {
        "candidate_snapshot_digest",
        "gate_digest",
        "binding_digest",
        "requirement_state_digest",
        "sufficiency_digest",
        "operator_digest",
        "selected_source_refs",
        "visible_spans",
        "context_sha256",
        "sealed_reader_seed",
    }

    assert all(required <= set(row) for row in audit["records"])
    assert all(
        len(row["visible_spans"]) == len(row["selected_source_refs"])
        for row in audit["records"]
    )
