from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from evals.dg23.decision_separation import (
    DIAGNOSTIC_BUDGETS,
    build_decision_separation_report,
)
from milai.application.memory_query import MemoryQueryCompiler
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.application.retrieval import _decision_requirement_ids
from milai.domain.sufficiency import SufficiencyDecision
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s2_all_diagnostic_budgets_share_one_decision_snapshot() -> None:
    report = build_decision_separation_report(ROOT)

    assert report["status"] == "PASS_BUDGET_INVARIANT_DECISION_SNAPSHOT"
    assert report["hard_gate"]["passed"]
    assert tuple(report["diagnostic_budgets"]) == DIAGNOSTIC_BUDGETS
    assert len({row["decision_snapshot_digest"] for row in report["records"]}) == 1
    assert len({row["acquisition_plan_digest"] for row in report["records"]}) == 1
    assert len({row["binding_digest"] for row in report["records"]}) == 1


def test_dg23_s2_presentation_cap_is_absent_from_decision_contract() -> None:
    report = build_decision_separation_report(ROOT)
    fields = set(report["decision_snapshot"])

    assert not any("budget" in field for field in fields)
    assert {
        row["context_candidate_budget"] for row in report["records"]
    } == {32_000}
    assert report["public_boundary"]["mcp_request_schema_changed"] is False


def test_dg23_s2_decision_snapshot_is_frozen_and_rejects_unresolved_drift() -> None:
    snapshot = build_decision_snapshot(
        source_snapshot_material={"source": 1},
        query_ir_material={"query": 1},
        acquisition_plan_material={"plan": 1},
        candidate_snapshot_material=[{"candidate": 1}],
        gate_material={"gate": "ALLOWED"},
        binding_material={"R1": ["E1"]},
        requirement_state_material={"required": ["R1"]},
        sufficiency_material={"status": "COMPLETE"},
        operator_result_material=None,
        required_requirement_ids=["R1"],
    )

    with pytest.raises(ValidationError, match="frozen"):
        snapshot.gate_digest = "0" * 64
    with pytest.raises(ValueError, match="unresolved requirements"):
        build_decision_snapshot(
            source_snapshot_material={},
            query_ir_material={},
            acquisition_plan_material={},
            candidate_snapshot_material=[],
            gate_material={},
            binding_material={},
            requirement_state_material={},
            sufficiency_material={},
            operator_result_material=None,
            required_requirement_ids=["R1"],
            unresolved_requirement_ids=["R2"],
        )


def test_dg23_s2_legacy_query_uses_frozen_sufficiency_requirement_universe() -> None:
    decision = SufficiencyDecision(
        status="PARTIAL",
        covered_slots=["KNOWN"],
        missing_slots=["LOOKUP_ANSWER"],
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )

    assert _decision_requirement_ids(None, decision) == ["KNOWN", "LOOKUP_ANSWER"]


def test_dg23_s2_query_ir_still_rejects_any_foreign_sufficiency_reference() -> None:
    query_ir = MemoryQueryCompiler().compile(
        "What game did I finally beat last weekend?",
        reference_time=datetime(2026, 8, 29, tzinfo=UTC),
        scope={"project_ids": ["dg23-test"]},
    )
    decision = SufficiencyDecision(
        status="PARTIAL",
        covered_slots=["CANONICAL_RESULT"],
        missing_slots=["FOREIGN_REQUIREMENT"],
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )

    with pytest.raises(AssertionError, match="FOREIGN_REQUIREMENT"):
        _decision_requirement_ids(query_ir, decision)
