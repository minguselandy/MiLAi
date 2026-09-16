"""Single product owner of final Recollection completion decisions.

Acquisition, ranking, Formation, and model interpretation may provide evidence
to this facade.  None of them can independently promote a query to COMPLETE.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from milai.application.query_ir_compat import infer_operator_family
from milai.application.sufficiency import SufficiencyStage, decide_sufficiency
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
            [item.slot_id for item in query_ir.requirements if item.required]
            if query_ir
            else []
        )
        matched = {
            item.requirement_id
            for item in bindings
            if item.status == "MATCH"
        }
        if requirement_state is not None:
            satisfied = list(requirement_state.satisfied_requirement_ids)
            missing = list(requirement_state.missing_requirement_ids)
        else:
            satisfied = sorted(set(required).intersection(matched))
            missing = sorted(set(required).difference(satisfied))
        typed_state_available = requirement_state is not None or bool(bindings)

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

        family = infer_operator_family(query_ir) if query_ir is not None else None
        is_count = family == "COUNT" or plan.operator in {
            "COUNT_DISTINCT",
            "TEMPORAL_COUNT_DISTINCT",
        }
        if proposed.complete and is_count and (
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

        operator_status = operator_result.get("status") if operator_result is not None else None
        if (
            not proposed.complete
            and stage == "FINAL"
            and operator_status in {"OK", "COMPLETE"}
            and required
            and not missing
            and matched
            and not open_issue_ids
        ):
            proposed = SufficiencyDecision(
                status="COMPLETE",
                covered_slots=required,
                proof=proposed.proof,
                stop_reason="REQUIREMENT_SATISFIED",
            )
            reason = "GROUNDED_OPERATOR_COMPLETE"

        # Evidence LOOKUP may complete only through a grounded accepted Binding;
        # lexical overlap and candidate presence are intentionally insufficient.
        if (
            not proposed.complete
            and stage == "FINAL"
            and family == "LOOKUP"
            and required
            and not missing
            and matched
            and not open_issue_ids
            and request.required_authority != "ACTION_SAFE"
        ):
            proposed = SufficiencyDecision(
                status="COMPLETE",
                covered_slots=required,
                proof=proposed.proof,
                stop_reason="REQUIREMENT_SATISFIED",
            )
            reason = "GROUNDED_ACCEPTED_BINDING_COMPLETE"

        if (
            mode == "STRICT_OPERATOR"
            and proposed.complete
            and required
            and set(required) != matched
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


DEFAULT_DECISION_ENGINE = DecisionEngine()

__all__ = [
    "DEFAULT_DECISION_ENGINE",
    "FINAL_COMPLETE_AUTHORITY",
    "DecisionEngine",
    "DecisionMode",
    "DecisionResult",
]
