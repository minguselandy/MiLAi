"""Compile the lean LOOKUP/STRICT adapter from existing Product query types."""

from __future__ import annotations

from typing import Literal

from milai.application.query_ir_compat import infer_operator_family
from milai.domain.lean_recall import LeanRecallMode, LeanRecallPlan, LeanRecallRequirement
from milai.domain.query_execution import CompletionMode
from milai.domain.query_task_contract import EvidenceRole, QueryOperation, TypedRequirementV01
from milai.domain.retrieval import QueryPlan

LeanDecisionMode = Literal["ORDINARY_RECALL", "STRICT_OPERATOR"]

_STRICT_COMPLETENESS = frozenset(
    {
        "ALL_REQUIRED_BINDINGS",
        "ALL_MATCHES_IN_RANGE",
        "COMPLETE_VERSION_CHAIN",
    }
)


def compile_lean_recall_plan(plan: QueryPlan) -> LeanRecallPlan:
    contract = plan.query_task_contract
    execution = plan.query_execution_plan
    if contract is not None and execution is not None:
        canonical_state_lookup = contract.operation == QueryOperation.STATE_AS_OF
        strict = (
            not canonical_state_lookup
            and execution.completion.mode != CompletionMode.LOOKUP_READINESS
        )
        typed_mode: LeanRecallMode = "STRICT" if strict else "LOOKUP"
        typed_requirements = tuple(
            LeanRecallRequirement(
                # The public v0.2 Binding lane still addresses role keys.  The
                # typed requirement identity remains available in the internal
                # execution plan until Binding itself migrates.
                requirement_id=requirement.role_key,
                requirement_role=_typed_requirement_role(
                    requirement,
                    index=index,
                    operation=contract.operation,
                ),
                source_roles=tuple(
                    sorted(
                        speaker.value
                        for speaker in (
                            requirement.source.allowed_speakers
                            or requirement.source.preferred_speakers
                        )
                    )
                ),
                required=True,
            )
            for index, requirement in enumerate(
                execution.binding.requirements,
                start=1,
            )
            if requirement.required
        )
        return LeanRecallPlan(
            mode=typed_mode,
            operator=plan.operator if strict else None,
            requirements=typed_requirements,
        )

    query_ir = plan.memory_query_ir
    # LATEST_VALID_STATE is a selection over already governed canonical state,
    # not a value composition over independent raw-Evidence operands. Requiring
    # an Evidence Binding for it rejects a valid canonical HIT when the source
    # evidence is intentionally terse (for example, a grounding pointer). The
    # Canonical Gate remains the authority boundary for this lookup.
    canonical_state_lookup = (
        (plan.operator == "LATEST_VALID_STATE" or (
            plan.intent == "EXACT_CURRENT" and plan.complexity == "L0"
            and plan.operator is None
        ))
        and query_ir is not None
        and query_ir.mode == "STATE"
    )
    strict = not canonical_state_lookup and (
        plan.operator is not None
        or (query_ir is not None and query_ir.completeness in _STRICT_COMPLETENESS)
    )
    mode: LeanRecallMode = "STRICT" if strict else "LOOKUP"
    requirements = tuple(
        LeanRecallRequirement(
            requirement_id=requirement.slot_id,
            requirement_role=_requirement_role(plan, index),
            source_roles=tuple(
                sorted(
                    set(
                        requirement.evidence_source.allowed_speakers
                        or requirement.evidence_source.preferred_speakers
                    )
                )
            ),
            required=requirement.required,
        )
        for index, requirement in enumerate(
            query_ir.requirements if query_ir is not None else (),
            start=1,
        )
        if requirement.required
    )
    return LeanRecallPlan(
        mode=mode,
        operator=plan.operator if strict else None,
        requirements=requirements,
    )


def lean_decision_mode(plan: QueryPlan) -> LeanDecisionMode:
    return (
        "STRICT_OPERATOR"
        if compile_lean_recall_plan(plan).mode == "STRICT"
        else "ORDINARY_RECALL"
    )


def _requirement_role(plan: QueryPlan, index: int) -> str:
    query_ir = plan.memory_query_ir
    family = infer_operator_family(query_ir) if query_ir is not None else "LOOKUP"
    if family == "LOOKUP" and plan.operator in {None, "LATEST_VALID_STATE"}:
        return "ANSWER"
    if family == "COUNT" or plan.operator in {"COUNT_DISTINCT", "TEMPORAL_COUNT_DISTINCT"}:
        return "EVENT_MEMBER"
    if plan.operator == "LATEST_VALID_STATE":
        return "STATE_AS_OF"
    if family == "WHY_CHANGE":
        return "OLD_STATE" if index == 1 else "NEW_STATE" if index == 2 else f"STATE_{index}"
    return "OPERAND_A" if index == 1 else "OPERAND_B" if index == 2 else f"OPERAND_{index}"


def _typed_requirement_role(
    requirement: TypedRequirementV01,
    *,
    index: int,
    operation: QueryOperation | None,
) -> str:
    """Adapt typed roles to the stable lean presentation vocabulary."""

    role = requirement.evidence_role
    if operation in {QueryOperation.LOOKUP, QueryOperation.STATE_AS_OF}:
        return "ANSWER"
    if role == EvidenceRole.COLLECTION_MEMBER:
        return "EVENT_MEMBER"
    if role in {EvidenceRole.NUMERATOR, EvidenceRole.LEFT_OPERAND}:
        return "OPERAND_A"
    if role in {EvidenceRole.DENOMINATOR, EvidenceRole.RIGHT_OPERAND}:
        return "OPERAND_B"
    if role == EvidenceRole.PRIOR_STATE:
        return "OLD_STATE"
    if role == EvidenceRole.CURRENT_STATE:
        return "NEW_STATE"
    if role == EvidenceRole.TRANSITION:
        return "TRANSITION"
    if role == EvidenceRole.STATE:
        return "STATE_AS_OF"
    if role in {EvidenceRole.EVENT, EvidenceRole.OPERAND}:
        return "OPERAND_A" if index == 1 else "OPERAND_B" if index == 2 else f"OPERAND_{index}"
    return requirement.role_key


__all__ = ["LeanDecisionMode", "compile_lean_recall_plan", "lean_decision_mode"]
