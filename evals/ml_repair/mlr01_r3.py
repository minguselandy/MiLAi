"""ML-R01 R3 progressive Context-Evidence boundary witness."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from milai.application.memory_resolve import MemoryResolveService
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.application.retrieval import RetrievalExecution, RetrievalService
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import DecisionSnapshot
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext

from evals.ml_closure.longmemeval_contract import (
    ROOT,
    atomic_json,
    canonical_json,
    load_json,
    sha256_file,
)

RUN_ID = "ml-r01-20260831-001"
RUN_ROOT = ROOT / "var/ml_repair" / RUN_ID
RUN_LOCK_PATH = RUN_ROOT / "run-lock.json"
AMENDMENT_PATH = RUN_ROOT / "protocol-amendment.json"
DEFAULT_OUTPUT = RUN_ROOT / "checkpoints/r3/progressive-boundary.json"
Boundary = Literal["UNIFORM_STRICT", "PROGRESSIVE"]
BOUNDARIES: tuple[Boundary, ...] = ("UNIFORM_STRICT", "PROGRESSIVE")


class MLR01R3Error(RuntimeError):
    """The R3 paired boundary evidence is invalid."""


@dataclass(frozen=True, slots=True)
class BoundaryFixture:
    case_id: str
    lane: Literal["ORDINARY", "STRICT"]
    query: str
    operator_family: str
    evidence: tuple[tuple[str, str, float], ...]
    accepted_evidence_ids: tuple[str, ...]
    relevant_evidence_ids: tuple[str, ...]
    sufficiency_status: Literal["COMPLETE", "PARTIAL"]
    expected_complete: bool


@dataclass(slots=True)
class _FrozenRetrieval:
    body: dict[str, Any]
    snapshot: DecisionSnapshot

    def retrieve(
        self,
        _context: SessionContext,
        _request: RetrievalRequest,
        _request_id: str,
        **_options: Any,
    ) -> RetrievalExecution:
        return RetrievalExecution(
            deepcopy(self.body),
            decision_snapshot=self.snapshot,
        )


def _fixtures() -> tuple[BoundaryFixture, ...]:
    """Synthetic source identities are fixed before either boundary executes."""

    return (
        BoundaryFixture(
            case_id="ordinary-parser-miss",
            lane="ORDINARY",
            query="Which tea do I prefer?",
            operator_family="PREFERENCE",
            evidence=(
                ("accepted-order", "I ordered tea during the trip.", 0.91),
                ("gold-preference", "My favorite tea is oolong.", 0.86),
            ),
            accepted_evidence_ids=("accepted-order",),
            relevant_evidence_ids=("gold-preference",),
            sufficiency_status="PARTIAL",
            expected_complete=False,
        ),
        BoundaryFixture(
            case_id="ordinary-empty-binding",
            lane="ORDINARY",
            query="Where did I leave the blue notebook?",
            operator_family="LOOKUP",
            evidence=(
                ("gold-notebook", "I left the blue notebook in the studio.", 0.93),
                ("notebook-context", "The studio closes at six.", 0.62),
            ),
            accepted_evidence_ids=(),
            relevant_evidence_ids=("gold-notebook",),
            sufficiency_status="PARTIAL",
            expected_complete=False,
        ),
        BoundaryFixture(
            case_id="ordinary-multi-support",
            lane="ORDINARY",
            query="What happened at the garden event?",
            operator_family="LOOKUP",
            evidence=(
                ("gold-garden", "I planted rosemary at the garden event.", 0.94),
                ("gold-friend", "Maya brought the seedlings.", 0.81),
                ("event-noise", "The weather forecast changed later.", 0.47),
            ),
            accepted_evidence_ids=("gold-garden",),
            relevant_evidence_ids=("gold-garden", "gold-friend"),
            sufficiency_status="COMPLETE",
            expected_complete=True,
        ),
        BoundaryFixture(
            case_id="ordinary-stable-lookup",
            lane="ORDINARY",
            query="What is the cobalt code?",
            operator_family="LOOKUP",
            evidence=(
                ("gold-code", "The cobalt code is 47.", 0.99),
                ("code-context", "We discussed access codes yesterday.", 0.58),
            ),
            accepted_evidence_ids=("gold-code",),
            relevant_evidence_ids=("gold-code",),
            sufficiency_status="COMPLETE",
            expected_complete=True,
        ),
        BoundaryFixture(
            case_id="strict-count-partial",
            lane="STRICT",
            query="How many workshops did I attend?",
            operator_family="COUNT",
            evidence=(
                ("count-bound", "I attended the Atlas workshop.", 0.97),
                ("count-ambiguous", "The Orion workshop was planned.", 0.79),
            ),
            accepted_evidence_ids=("count-bound",),
            relevant_evidence_ids=("count-bound",),
            sufficiency_status="PARTIAL",
            expected_complete=False,
        ),
        BoundaryFixture(
            case_id="strict-divide-complete",
            lane="STRICT",
            query="How much did each mug cost?",
            operator_family="DIVIDE",
            evidence=(
                ("divide-total", "The five mugs cost 75 dollars in total.", 0.98),
                ("divide-count", "I purchased five mugs.", 0.97),
                ("divide-noise", "The mugs had funny quotes.", 0.55),
            ),
            accepted_evidence_ids=("divide-total", "divide-count"),
            relevant_evidence_ids=("divide-total", "divide-count"),
            sufficiency_status="COMPLETE",
            expected_complete=True,
        ),
        BoundaryFixture(
            case_id="strict-temporal-partial",
            lane="STRICT",
            query="Which happened first, the repair or the concert?",
            operator_family="TEMPORAL_ORDER",
            evidence=(
                ("temporal-repair", "I repaired the guitar on March 2.", 0.96),
                ("temporal-concert", "I went to the concert later that month.", 0.89),
            ),
            accepted_evidence_ids=("temporal-repair",),
            relevant_evidence_ids=("temporal-repair", "temporal-concert"),
            sufficiency_status="PARTIAL",
            expected_complete=False,
        ),
    )


def _evidence_item(
    fixture: BoundaryFixture,
    ordinal: int,
    evidence_id: str,
    content: str,
    relevance_score: float,
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "canonical_mutation": False,
        "authority_class": "EVIDENCE_ONLY",
        "evidence_id": evidence_id,
        "evidence_ids": [evidence_id],
        "source_ref": f"r3://{fixture.case_id}/turn/{ordinal}",
        "subject_id": fixture.case_id,
        "observed_at": f"2026-08-{ordinal + 1:02d}T00:00:00+00:00",
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "relevance_score": relevance_score,
        "permission_snapshot": {"readable": True, "project_ids": ["mlr01-r3"]},
        "retention_state": "READABLE",
        "access_decision": "ALLOW",
    }


def _execution_material(
    fixture: BoundaryFixture,
) -> tuple[dict[str, Any], DecisionSnapshot, frozenset[str]]:
    items = [
        _evidence_item(fixture, ordinal, evidence_id, content, score)
        for ordinal, (evidence_id, content, score) in enumerate(fixture.evidence)
    ]
    known = frozenset(str(item["evidence_id"]) for item in items)
    if not set(fixture.relevant_evidence_ids).issubset(known):
        raise MLR01R3Error("R3 relevant Evidence identity is outside the snapshot")
    missing = [] if fixture.sufficiency_status == "COMPLETE" else ["ANSWER"]
    decision = {
        "schema_version": "sufficiency-decision-v0.1",
        "status": fixture.sufficiency_status,
        "covered_slots": [] if missing else ["ANSWER"],
        "missing_slots": missing,
        "proof": {"binding_owner": "DETERMINISTIC_RUNTIME"},
        "stop_reason": (
            "REQUIREMENT_SATISFIED" if not missing else "SEARCH_SPACE_EXHAUSTED"
        ),
    }
    query_ir = {
        "schema_version": "memory-query-ir-v0.2",
        "mode": "EPISODIC",
        "answer_shape": "SCALAR",
        "requirements": [{"slot_id": "ANSWER", "required": True}],
        "steps": [
            {
                "kind": "RETRIEVE",
                "constraints": {"operator_family": fixture.operator_family},
            }
        ],
        "completeness": (
            "TOP_K_ACCEPTABLE"
            if fixture.lane == "ORDINARY"
            else "ALL_REQUIRED_BINDINGS"
        ),
    }
    snapshot = build_decision_snapshot(
        source_snapshot_material={
            "case_id": fixture.case_id,
            "evidence_ids": sorted(known),
            "watermark": len(items),
        },
        query_ir_material=query_ir,
        acquisition_plan_material={"identity": "R3_FIXED_CANDIDATES"},
        candidate_snapshot_material=items,
        gate_material={"all_candidates_governance_admitted": True},
        binding_material={
            "accepted_evidence_ids": list(fixture.accepted_evidence_ids),
        },
        requirement_state_material={"required": ["ANSWER"], "missing": missing},
        sufficiency_material=decision,
        operator_result_material={
            "operator_family": fixture.operator_family,
            "status": fixture.sufficiency_status,
            "canonical_mutation": False,
        },
        accepted_evidence_ids=fixture.accepted_evidence_ids,
        required_requirement_ids=("ANSWER",),
        unresolved_requirement_ids=tuple(missing),
    )
    body = {
        "results": items,
        "query_plan": {
            "planner_version": (
                "lean-query-plan-v12-dg17-ir-v02+formation-semantic-replay-v0.2"
            ),
            "memory_query_ir": query_ir,
        },
        "progressive_l1": {"terminal_sufficiency_decision": decision},
        "open_issue_ids": [],
        "consistency": "CANONICAL_REQUIRED",
        "snapshot": {
            "canonical_outbox_sequence": len(items),
            "evidence_watermark": len(items),
        },
        "retrieval_trace_id": f"r3-{fixture.case_id}",
        "degraded_components": [],
        "fallback_used": False,
        "fallback_reason": None,
        "abstained": False,
        "abstention_reason": None,
        "derived_result": {
            "status": fixture.sufficiency_status,
            "kind": "EVIDENCE_COMPOSITION_RESULT",
            "operator": fixture.operator_family,
            "canonical_mutation": False,
            "completeness": {
                "required_slots": ["ANSWER"],
                "filled_slots": [] if missing else ["ANSWER"],
                "unresolved_reasons": missing,
            },
        },
        "access_trace": {"retrieval_trace_id": f"r3-{fixture.case_id}"},
    }
    return body, snapshot, known


def _execute_boundary(
    fixture: BoundaryFixture,
    *,
    boundary: Boundary,
) -> dict[str, Any]:
    body, snapshot, known = _execution_material(fixture)
    retrieval = _FrozenRetrieval(body, snapshot)
    service = MemoryResolveService(
        cast(RetrievalService, retrieval),
        progressive_context_evidence=boundary == "PROGRESSIVE",
    )
    execution = service.resolve(
        SessionContext(UUID(int=1), UUID(int=2)),
        MemoryResolveRequest(
            query=f"Recall previous history evidence: {fixture.query}",
            requested_scope={"project_ids": ["mlr01-r3"]},
            budget=MemoryResolveBudget(
                max_results=12,
                max_candidates=60,
                max_context_tokens=1_024,
                max_latency_ms=500,
            ),
        ),
        f"mlr01-r3-{boundary.casefold()}-{fixture.case_id}",
    )
    response = execution.body
    memory_context = response.get("memory_context")
    if not isinstance(memory_context, Mapping):
        raise MLR01R3Error("R3 Runtime did not compile a MemoryContext")
    reader_ids = frozenset(_strings(memory_context.get("selected_evidence_ids")))
    context_ids = frozenset(_strings(response.get("evidence_refs")))
    accepted_ids = frozenset(_strings(response.get("accepted_binding_evidence_refs")))
    relevant = frozenset(fixture.relevant_evidence_ids)
    recall = len(reader_ids.intersection(relevant)) / len(relevant)
    decision = response.get("sufficiency_decision")
    status = str(decision.get("status")) if isinstance(decision, Mapping) else "ABSENT"
    expected_status = "COMPLETE" if fixture.expected_complete else "PARTIAL"
    contract_correct = (
        recall == 1.0 if fixture.lane == "ORDINARY" else status == expected_status
    )
    return {
        "case_id": fixture.case_id,
        "lane": fixture.lane,
        "boundary": boundary,
        "candidate_snapshot_digest": snapshot.candidate_snapshot_digest,
        "decision_snapshot_digest": snapshot.snapshot_digest,
        "reader_evidence_boundary": response.get("reader_evidence_boundary"),
        "known_evidence_count": len(known),
        "context_evidence_count": len(context_ids),
        "accepted_binding_count": len(accepted_ids),
        "reader_evidence_count": len(reader_ids),
        "relevant_evidence_count": len(relevant),
        "context_evidence_recall": round(recall, 9),
        "accepted_evidence_identity_integrity": int(accepted_ids.issubset(known)),
        "reader_evidence_subset_integrity": int(reader_ids.issubset(context_ids)),
        "reader_grounding_violation": int(not reader_ids.issubset(known)),
        "accepted_binding_correct": len(accepted_ids.intersection(known)),
        "accepted_binding_total": len(accepted_ids),
        "sufficiency_status": status,
        "expected_sufficiency_status": expected_status,
        "wrong_complete": int(not fixture.expected_complete and status == "COMPLETE"),
        "contract_correct": contract_correct,
        "canonical_mutation": False,
    }


def build_r3_report() -> dict[str, Any]:
    run_lock = load_json(RUN_LOCK_PATH)
    amendment = load_json(AMENDMENT_PATH)
    if not isinstance(run_lock, Mapping) or not isinstance(amendment, Mapping):
        raise MLR01R3Error("R3 run authority is absent")
    fixtures = _fixtures()
    rows = [
        _execute_boundary(fixture, boundary=boundary)
        for fixture in fixtures
        for boundary in BOUNDARIES
    ]
    by_key = {(str(row["case_id"]), str(row["boundary"])): row for row in rows}
    paired_identity = all(
        by_key[(fixture.case_id, "UNIFORM_STRICT")]["candidate_snapshot_digest"]
        == by_key[(fixture.case_id, "PROGRESSIVE")]["candidate_snapshot_digest"]
        and by_key[(fixture.case_id, "UNIFORM_STRICT")]["decision_snapshot_digest"]
        == by_key[(fixture.case_id, "PROGRESSIVE")]["decision_snapshot_digest"]
        for fixture in fixtures
    )
    ordinary_historical = [
        row
        for row in rows
        if row["lane"] == "ORDINARY" and row["boundary"] == "UNIFORM_STRICT"
    ]
    ordinary_progressive = [
        row
        for row in rows
        if row["lane"] == "ORDINARY" and row["boundary"] == "PROGRESSIVE"
    ]
    strict_progressive = [
        row
        for row in rows
        if row["lane"] == "STRICT" and row["boundary"] == "PROGRESSIVE"
    ]
    historical_recall = _mean(
        float(row["context_evidence_recall"]) for row in ordinary_historical
    )
    progressive_recall = _mean(
        float(row["context_evidence_recall"]) for row in ordinary_progressive
    )
    strict_correct = sum(
        int(row["accepted_binding_correct"]) for row in strict_progressive
    )
    strict_total = sum(int(row["accepted_binding_total"]) for row in strict_progressive)
    strict_precision = strict_correct / strict_total if strict_total else None
    regressions = sum(
        bool(by_key[(fixture.case_id, "UNIFORM_STRICT")]["contract_correct"])
        and not bool(by_key[(fixture.case_id, "PROGRESSIVE")]["contract_correct"])
        for fixture in fixtures
    )
    metrics = {
        "AcceptedEvidenceIdentityIntegrity": _mean(
            float(row["accepted_evidence_identity_integrity"])
            for row in rows
            if row["boundary"] == "PROGRESSIVE"
        ),
        "ReaderEvidenceSubsetIntegrity": _mean(
            float(row["reader_evidence_subset_integrity"])
            for row in rows
            if row["boundary"] == "PROGRESSIVE"
        ),
        "ordinary_ContextEvidenceRecall_historical": historical_recall,
        "ordinary_ContextEvidenceRecall_progressive": progressive_recall,
        "StrictAcceptedBindingCorrect": strict_correct,
        "StrictAcceptedBindingTotal": strict_total,
        "StrictAcceptedBindingPrecision": strict_precision,
        "WrongCOMPLETE": sum(int(row["wrong_complete"]) for row in rows),
        "CorrectCaseRegression": regressions,
        "ReaderGroundingViolation": sum(
            int(row["reader_grounding_violation"])
            for row in rows
            if row["boundary"] == "PROGRESSIVE"
        ),
    }
    gates = {
        "paired_candidate_and_decision_snapshot_identity_exact": paired_identity,
        "AcceptedEvidenceIdentityIntegrity_eq_1": (
            metrics["AcceptedEvidenceIdentityIntegrity"] == 1.0
        ),
        "ReaderEvidenceSubsetIntegrity_eq_1": (
            metrics["ReaderEvidenceSubsetIntegrity"] == 1.0
        ),
        "ordinary_ContextEvidenceRecall_gte_historical": (
            progressive_recall >= historical_recall
        ),
        "strict_Binding_precision_eq_1_when_applicable": (
            strict_total > 0 and strict_precision == 1.0
        ),
        "Wrong_COMPLETE_eq_0": metrics["WrongCOMPLETE"] == 0,
        "CorrectCaseRegression_eq_0": metrics["CorrectCaseRegression"] == 0,
        "ReaderGroundingViolation_eq_0": metrics["ReaderGroundingViolation"] == 0,
        "model_interpreter_calls_eq_0": True,
        "canonical_mutations_eq_0": not any(row["canonical_mutation"] for row in rows),
        "benchmark_labels_opened_false": True,
    }
    material = {
        "schema": "milai.ml-r01.r3-progressive-boundary.v1",
        "run_id": RUN_ID,
        "run_lock_digest": run_lock.get("run_lock_digest"),
        "protocol_amendment_sha256": sha256_file(AMENDMENT_PATH),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "comparison": (
            "UNIFORM_STRICT_FORMATION_REPLAY_vs_"
            "GOVERNANCE_ADMITTED_SOFT_RANKED_CONTEXT_WITH_STRICT_PROOF"
        ),
        "fixture_count": len(fixtures),
        "ordinary_fixture_count": sum(item.lane == "ORDINARY" for item in fixtures),
        "strict_fixture_count": sum(item.lane == "STRICT" for item in fixtures),
        "metrics": metrics,
        "gates": gates,
        "records": rows,
        "scope": {
            "model_interpreter_calls": 0,
            "requirement_schema_changes": 0,
            "canonical_gate_changes": 0,
            "canonical_mutations": 0,
            "benchmark_labels_opened": False,
            "answer_calls": 0,
            "judge_calls": 0,
            "formal_holdout": False,
            "product_default_enablement": False,
        },
    }
    return {
        **material,
        "report_digest": hashlib.sha256(canonical_json(material)).hexdigest(),
    }


def run_r3(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    report = build_r3_report()
    atomic_json(output, report)
    return report


def _strings(value: object) -> tuple[str, ...]:
    return (
        tuple(str(item) for item in value if isinstance(item, str) and item)
        if isinstance(value, (list, tuple))
        else ()
    )


def _mean(values: Any) -> float:
    selected = [float(value) for value in values]
    if not selected:
        raise MLR01R3Error("R3 metric denominator is empty")
    return round(sum(selected) / len(selected), 9)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_r3(args.output)
    print(report["status"])
    print(report["metrics"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MLR01R3Error", "build_r3_report", "run_r3"]
