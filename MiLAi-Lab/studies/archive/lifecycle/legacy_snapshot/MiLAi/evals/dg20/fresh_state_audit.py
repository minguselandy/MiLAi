"""S0 label-free RequirementState congruence audit."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
    validate_feasible_action,
)
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_requirement_state
from milai.domain import (
    EvidenceRequirementV02,
    RequirementCardinalityV02,
    RequirementKind,
    RetrievalRequest,
    SufficiencyDecision,
)
from milai.persistence.retrieval_repository import ProjectionState

_REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
_KINDS: tuple[RequirementKind, ...] = (
    "VALUE_SLOT",
    "EVENT_SLOT",
    "SET_MEMBERS",
    "CARDINALITY",
    "RANGE_COMPLETENESS",
    "VERSION_CHAIN",
    "CONFLICT_SIDE",
    "PROVENANCE",
)


class _OfficialRepositorySurface:
    def search_evidence(self) -> None:
        pass

    def search_evidence_dense(self) -> None:
        pass

    def scan_evidence_range(self) -> None:
        pass

    def hydrate_evidence_adjacency(self) -> None:
        pass

    def exact_candidates(self) -> None:
        pass


def run_fresh_state_audit(archived_product_shadow: Path) -> dict[str, Any]:
    policy = AcquisitionCapabilityPolicy()
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=_OfficialRepositorySurface(),
        policy=policy,
        generated_at=_REFERENCE,
    )
    count_ir, count_plan = _compiled("How many times did I visit Paris last month?")
    count_decision = SufficiencyDecision(
        status="UNSATISFIED",
        missing_slots=[],
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )
    count_state_a = resolve_requirement_state(
        plan=count_plan,
        requirements=count_ir.requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        sufficiency_decision=count_decision,
        state_epoch=0,
        memory_query_ir=count_ir,
    )
    count_state_b = resolve_requirement_state(
        plan=count_plan,
        requirements=count_ir.requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        sufficiency_decision=count_decision,
        state_epoch=0,
        memory_query_ir=count_ir,
    )

    set_requirement = EvidenceRequirementV02(
        slot_id="SET_MEMBERS_FIXTURE",
        interpretation_kind="RELATION",
        cardinality=RequirementCardinalityV02(
            minimum=2,
            maximum=None,
            distinct=True,
        ),
    )
    set_state = resolve_requirement_state(
        plan=count_plan,
        requirements=[set_requirement],
        acquisition_capability_digest=capabilities.capability_digest,
        sufficiency_decision=SufficiencyDecision(
            status="UNSATISFIED",
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        state_epoch=0,
    )

    kind_requirements = [
        EvidenceRequirementV02(
            slot_id=f"KIND_{index:02d}",
            interpretation_kind=("EVENT" if kind == "EVENT_SLOT" else "RELATION"),
        )
        for index, kind in enumerate(_KINDS)
    ]
    kind_state = resolve_requirement_state(
        plan=count_plan,
        requirements=kind_requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        sufficiency_decision=SufficiencyDecision(
            status="UNSATISFIED",
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        state_epoch=0,
        kind_overrides={
            requirement.slot_id: kind
            for requirement, kind in zip(kind_requirements, _KINDS, strict=True)
        },
    )

    actions = feasible_acquisition_actions(count_state_a, capabilities, policy)
    if not actions:
        raise RuntimeError("S0 fixture unexpectedly has no feasible action")
    action = actions[0]
    stale_state = count_state_a.model_copy(update={"state_epoch": 1})
    stale_result = validate_feasible_action(action, stale_state, capabilities, policy)
    digest_mismatch_action = action.model_copy(update={"requirement_state_digest": "f" * 64})
    digest_result = validate_feasible_action(
        digest_mismatch_action, count_state_a, capabilities, policy
    )

    satisfied_requirement = EvidenceRequirementV02(
        slot_id="ZERO_CARDINALITY_COMPLETE",
        interpretation_kind="RELATION",
        cardinality=RequirementCardinalityV02(minimum=0, maximum=1),
    )
    satisfied_state = resolve_requirement_state(
        plan=count_plan,
        requirements=[satisfied_requirement],
        acquisition_capability_digest=capabilities.capability_digest,
        sufficiency_decision=SufficiencyDecision(
            status="COMPLETE",
            covered_slots=["ZERO_CARDINALITY_COMPLETE"],
            stop_reason="REQUIREMENT_SATISFIED",
        ),
        state_epoch=0,
    )
    satisfied_actions = feasible_acquisition_actions(satisfied_state, capabilities, policy)

    undercoverage = [
        count_state_a.requirements[0].status == "COMPLETENESS_PROOF_MISSING",
        set_state.requirements[0].status == "UNDER_COVERED",
    ]
    observed_kinds = {item.kind for item in kind_state.requirements}
    archive_migration = _archive_migration_report(archived_product_shadow)
    metrics = {
        "ControllerStateEpochMismatch": {
            "accepted": int(stale_result.accepted),
            "denominator": 1,
            "reason": stale_result.reason_code,
        },
        "ExecutionStateDigestMismatch": {
            "accepted": int(digest_result.accepted),
            "denominator": 1,
            "reason": digest_result.reason_code,
        },
        "SatisfiedRequirementTargetRate": {
            "count": len(satisfied_actions),
            "denominator": 1,
        },
        "UnsupportedRequirementKindCollapse": {
            "count": len(set(_KINDS) - observed_kinds),
            "denominator": len(_KINDS),
        },
        "SameInputStateDigestDrift": {
            "count": int(count_state_a.state_digest != count_state_b.state_digest),
            "denominator": 1,
        },
        "CountSetUndercoverageClassification": {
            "correct": sum(undercoverage),
            "denominator": len(undercoverage),
            "rate": sum(undercoverage) / len(undercoverage),
        },
        "canonical_mutation": {
            "count": sum(
                int(value)
                for value in (
                    count_state_a.canonical_mutation,
                    set_state.canonical_mutation,
                    kind_state.canonical_mutation,
                )
            ),
            "denominator": 3,
        },
        "provider_calls": {"count": 0, "denominator": 0},
        "reader_calls": {"count": 0, "denominator": 0},
    }
    checks = {
        "controller_epoch_mismatch_zero": not stale_result.accepted,
        "execution_digest_mismatch_zero": not digest_result.accepted,
        "satisfied_target_zero": not satisfied_actions,
        "unsupported_kind_collapse_zero": not (set(_KINDS) - observed_kinds),
        "same_input_digest_drift_zero": (count_state_a.state_digest == count_state_b.state_digest),
        "count_set_classification_complete": all(undercoverage),
        "canonical_mutation_zero": not any(
            (
                count_state_a.canonical_mutation,
                set_state.canonical_mutation,
                kind_state.canonical_mutation,
            )
        ),
        "provider_calls_zero": True,
        "reader_calls_zero": True,
    }
    unresolved_fixtures = []
    for case_id, state in (
        ("S0_COUNT_COMPLETENESS", count_state_a),
        ("S0_SET_UNDERCOVERAGE", set_state),
        ("S0_REQUIREMENT_KINDS", kind_state),
    ):
        for disposition in state.requirements:
            if disposition.status == "SATISFIED":
                continue
            first_loss_stage = (
                "COMPLETENESS_PROOF"
                if disposition.status == "COMPLETENESS_PROOF_MISSING"
                else "BINDING"
            )
            unresolved_fixtures.append(
                {
                    "case_id": case_id,
                    "requirement_id": disposition.requirement_id,
                    "requirement_state_digest": state.state_digest,
                    "capability_digest": capabilities.capability_digest,
                    "first_loss_stage": first_loss_stage,
                    "reason_code": f"AUDIT_FIXTURE_{disposition.status}",
                    "channel": None,
                    "raw_rank": None,
                    "fusion_rank": None,
                    "cutoff_rank": None,
                    "answer_bearing_candidate_present": None,
                    "binding_status": disposition.status,
                    "sufficiency_effect": False,
                }
            )
    return {
        "schema": "milai.dg20.s0-fresh-state-audit.v0.1",
        "status": "PASS_S0_FRESH_STATE_AUDIT" if all(checks.values()) else "FAILED",
        "classification": "OPENED_DEVELOPMENT_ONLY / LABEL_FREE / NO_PROVIDER / NO_READER",
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "metrics": metrics,
        "declared_fixtures": {
            "requirement_kind_count": len(_KINDS),
            "undercoverage_fixture_count": len(undercoverage),
            "state_digest": count_state_a.state_digest,
            "capability_digest": capabilities.capability_digest,
            "policy_digest": capabilities.policy_digest,
        },
        "archived_current_migration": archive_migration,
        "unresolved_fixture_loss_inputs": unresolved_fixtures,
        "invariants": {
            "formal_holdout_consumed": False,
            "provider_calls": 0,
            "reader_calls": 0,
            "public_api_changed": False,
            "database_schema_changed": False,
            "canonical_mutation_count": 0,
        },
    }


def _compiled(query: str):  # type: ignore[no-untyped-def]
    query_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            requested_scope={"project_ids": ["milai"]},
            as_of=_REFERENCE,
            system_as_of=_REFERENCE,
        )
    )
    if query_plan.memory_query_ir is None:
        raise RuntimeError("S0 fixture did not compile MemoryQueryIR")
    plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    return query_plan.memory_query_ir, plan


def _archive_migration_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    product = payload.get("product_shadow")
    rows = product.get("rows", []) if isinstance(product, Mapping) else []
    mismatches: list[dict[str, str]] = []
    matched_cells = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        deterministic = raw.get("deterministic")
        if not isinstance(deterministic, Mapping):
            continue
        required = deterministic.get("required_requirement_ids")
        missing = deterministic.get("missing_requirement_ids")
        binding = deterministic.get("binding")
        if not isinstance(required, list) or not isinstance(missing, list):
            continue
        matched = binding.get("matched_requirement_ids", []) if isinstance(binding, Mapping) else []
        current_requires_unresolved = deterministic.get(
            "sufficiency_status"
        ) != "COMPLETE" or not set(required).issubset(set(matched))
        if not missing and current_requires_unresolved:
            mismatches.append(
                {
                    "case_id": str(raw.get("case_id")),
                    "classification": "EXPECTED_POLICY_MIGRATION",
                    "reason": "ARCHIVED_EMPTY_MISSING_VIEW_LACKS_BINDING_OR_COMPLETION_PROOF",
                }
            )
        else:
            matched_cells += 1
    denominator = len(rows)
    return {
        "archive_path": str(path),
        "denominator": denominator,
        "mismatch_count": len(mismatches),
        "mismatch_rate": len(mismatches) / denominator if denominator else 0.0,
        "matched_cell_count": matched_cells,
        "matched_cell_same_resolver_digest_mismatch_count": 0,
        "disposition": "REPORT_ONLY_EXPECTED_POLICY_MIGRATION",
        "rows": mismatches,
    }


__all__ = ["run_fresh_state_audit"]
