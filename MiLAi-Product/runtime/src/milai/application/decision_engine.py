"""Single product owner of final Recollection completion decisions.

Acquisition, ranking, Formation, and model interpretation may provide evidence
to this facade.  None of them can independently promote a query to COMPLETE.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.application.sufficiency import SufficiencyStage, decide_sufficiency
from milai.domain.query_execution import QueryExecutionPlanV01
from milai.domain.query_task_contract import ProofObligation
from milai.domain.requirement_state import RequirementState
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceSpan,
    MemoryQueryIRV02,
    RequirementBinding,
)
from milai.domain.sufficiency import SufficiencyDecision
from milai.domain.temporal_proof import BoundedRangeScanProofV02

DecisionMode = Literal["ORDINARY_RECALL", "STRICT_OPERATOR"]
FINAL_COMPLETE_AUTHORITY = "milai-decision-engine-v0.1"


@dataclass(frozen=True, slots=True)
class DecisionResult:
    sufficiency_decision: SufficiencyDecision
    reason_code: str
    mode: DecisionMode
    final_complete_authority: str = FINAL_COMPLETE_AUTHORITY


class DecisionEngine:
    """Apply governance and typed-proof rules exactly once at a retrieval stop."""

    def decide(
        self,
        query_ir: MemoryQueryIRV02 | None,
        governed_candidates: Sequence[Mapping[str, Any]],
        canonical_results: Sequence[Mapping[str, Any]],
        spans: Sequence[EvidenceSpan],
        interpretations: Sequence[EvidenceInterpretationCandidate],
        bindings: Sequence[RequirementBinding],
        operator_result: Mapping[str, Any] | None,
        temporal_proof: BoundedRangeScanProofV02 | None,
        *,
        request: RetrievalRequest,
        plan: QueryPlan,
        open_issue_ids: Sequence[str] = (),
        requirement_state: RequirementState | None = None,
        stage: SufficiencyStage = "FINAL",
        mode: DecisionMode = "ORDINARY_RECALL",
    ) -> DecisionResult:
        # The existing policy is now an intermediate classifier.  This facade
        # alone may return the final COMPLETE disposition.
        proposed, reason = decide_sufficiency(
            request,
            plan,
            canonical_results,
            open_issue_ids,
            operator_result,
            stage=stage,
        )
        required = (
            list(plan.query_execution_plan.completion.required_role_keys)
            if plan.query_execution_plan is not None
            else (
                [item.slot_id for item in query_ir.requirements if item.required]
                if query_ir
                else []
            )
        )
        completion_bindings = operator_operands_from_raw_bindings(bindings)
        matched = {item.requirement_id for item in completion_bindings}
        if plan.query_task_contract is not None and bindings:
            # A state computed from the compatibility DTO cannot re-authorize
            # a diagnostic Raw match into deterministic completion authority.
            satisfied = sorted(set(required).intersection(matched))
            missing = sorted(set(required).difference(satisfied))
        elif requirement_state is not None:
            satisfied = list(requirement_state.satisfied_requirement_ids)
            missing = list(requirement_state.missing_requirement_ids)
        else:
            satisfied = sorted(set(required).intersection(matched))
            missing = sorted(set(required).difference(satisfied))
        typed_state_available = requirement_state is not None or bool(bindings)

        # Natural-language planning currently has no structured operand source.
        # Raw bindings, Canonical rank, and a completion-shaped mapping are all
        # insufficient.  A future structured API must introduce its own
        # explicit authority object instead of reviving inference here.
        operator_inputs_accepted = False
        operator_status = operator_result.get("status") if operator_result is not None else None
        if (
            mode == "STRICT_OPERATOR"
            and operator_status in {"OK", "COMPLETE"}
            and not operator_inputs_accepted
        ):
            # A completion-shaped mapping is not execution proof.  Every
            # operator operand must close over an exact source span accepted for
            # the current QueryIR before the final boundary may consume it.
            proposed = SufficiencyDecision(
                status="PARTIAL" if matched else "UNSATISFIED",
                covered_slots=[],
                missing_slots=required,
                proof=proposed.proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            )
            reason = "OPERATOR_ACCEPTED_BINDING_INCOMPLETE"

        if open_issue_ids and proposed.complete:
            proposed = SufficiencyDecision(
                status="CONTESTED",
                covered_slots=proposed.covered_slots,
                # OpenIssue is a governance disposition, not a synthetic
                # QueryIR requirement identifier.
                missing_slots=[],
                proof=proposed.proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            )
            reason = "LIVE_OPEN_ISSUE_PREVENTS_COMPLETE"

        count_requires_range_proof = _count_requires_range_proof(
            query_ir,
            plan.operator,
            execution_plan=plan.query_execution_plan,
        )
        if proposed.complete and count_requires_range_proof and (
            temporal_proof is None or not temporal_proof.closure_complete
        ):
            proposed = SufficiencyDecision(
                status="PARTIAL" if canonical_results else "UNSATISFIED",
                covered_slots=satisfied,
                missing_slots=missing or required or ["BOUNDED_RANGE_PROOF"],
                proof=proposed.proof,
                stop_reason="PROJECTION_NOT_READY",
            )
            reason = "BOUNDED_RANGE_CLOSURE_INCOMPLETE"

        if (
            proposed.complete
            and missing
            and typed_state_available
            and not operator_inputs_accepted
            and (
                (stage == "FINAL" and request.memory_intent != "CURRENT_STATE")
                or mode == "STRICT_OPERATOR"
            )
        ):
            proposed = SufficiencyDecision(
                status="PARTIAL" if satisfied else "UNSATISFIED",
                covered_slots=satisfied,
                missing_slots=missing,
                proof=proposed.proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            )
            reason = "REQUIREMENT_STATE_INCOMPLETE"

        natural_language_plan = plan.intent != "EXACT_CURRENT" or plan.complexity != "L0"
        if proposed.complete and not natural_language_plan and required == ["EXACT_STATE"]:
            # The exact address was resolved through the Canonical Gate, not
            # through Raw Evidence operand extraction. Name that actual binding;
            # this proves address resolution, not free-form task understanding.
            proposed = proposed.model_copy(update={"covered_slots": ["EXACT_STATE"]})
            reason = "CANONICAL_EXACT_STATE_BOUND"
        if proposed.complete and natural_language_plan and not operator_inputs_accepted:
            # Governed memory can be useful Reader input without being a
            # Runtime proof that a free-form query is complete.  This also
            # covers deserialized legacy plans that lack the internal contract.
            proposed = SufficiencyDecision(
                status="PARTIAL" if governed_candidates or canonical_results else "UNSATISFIED",
                covered_slots=[],
                missing_slots=required,
                proof=proposed.proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            )
            reason = "NATURAL_LANGUAGE_READER_ONLY"

        # A grounded Raw Evidence binding proves source relevance, not answer
        # completeness.  MiLAi Product emits governed context but has no
        # generative Reader, so only a closed Canonical or executed-operator
        # proof may promote the final disposition to COMPLETE.

        if (
            mode == "STRICT_OPERATOR"
            and proposed.complete
            and required
            and set(required) != matched
            and not operator_inputs_accepted
        ):
            proposed = SufficiencyDecision(
                status="PARTIAL" if matched else "UNSATISFIED",
                covered_slots=sorted(matched),
                missing_slots=sorted(set(required).difference(matched)),
                proof=proposed.proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            )
            reason = "STRICT_ACCEPTED_BINDING_INCOMPLETE"

        # Sufficiency policy diagnostics historically used descriptive slot
        # labels. Persisted decision snapshots may reference only immutable
        # QueryIR requirement IDs.
        if query_ir is not None and not proposed.complete:
            allowed = set(required)
            normalized_covered = [slot for slot in proposed.covered_slots if slot in allowed]
            normalized_missing = [slot for slot in proposed.missing_slots if slot in allowed]
            if proposed.status != "CONTESTED" and not normalized_missing:
                normalized_missing = missing or required
            proposed = SufficiencyDecision(
                status=proposed.status,
                covered_slots=normalized_covered,
                missing_slots=normalized_missing,
                proof=proposed.proof,
                stop_reason=proposed.stop_reason,
            )

        return DecisionResult(proposed, reason, mode)


def _count_requires_range_proof(
    query_ir: MemoryQueryIRV02 | None,
    operator: str | None,
    *,
    execution_plan: QueryExecutionPlanV01 | None = None,
) -> bool:
    """Separate member-set closure from a grounded scalar count fact."""

    if execution_plan is not None:
        return ProofObligation.RANGE_CLOSURE in (
            execution_plan.completion.proof_obligations
        )
    if operator == "TEMPORAL_COUNT_DISTINCT":
        return True
    return (
        query_ir is not None
        and infer_operator_family(query_ir) == "COUNT"
        and query_ir.completeness == "ALL_MATCHES_IN_RANGE"
    )


DEFAULT_DECISION_ENGINE = DecisionEngine()

__all__ = [
    "DEFAULT_DECISION_ENGINE",
    "FINAL_COMPLETE_AUTHORITY",
    "DecisionEngine",
    "DecisionMode",
    "DecisionResult",
]
