"""Query-specific DG-17 sufficiency policy for progressive retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from milai.application.query_intent import has_count_intent
from milai.application.query_ir_compat import infer_operator_family
from milai.domain.query_task_contract import ParseDisposition, QueryOperation
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.sufficiency import SufficiencyDecision, SufficiencyProof

SufficiencyStage = Literal["FTS", "VECTOR", "FINAL"]

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_UNEXECUTED_RELATIVE_TIME = re.compile(
    r"\b(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+|"
    r"a\s+couple\s+of|couple\s+of)\s+"
    r"(?:days?|weeks?|months?|years?)\s+ago\b",
    re.IGNORECASE,
)
_UNEXECUTED_ORDER = re.compile(
    r"\b(?:who|what|which)\b[^?]*\bfirst\b[^?]*\bor\b",
    re.IGNORECASE,
)
_UNEXECUTED_PREFERENCE = re.compile(
    r"\b(?:suggestions?|recommend(?:ation)?s?)\b",
    re.IGNORECASE,
)
_LOOKUP_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "did",
        "do",
        "for",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "memory",
        "my",
        "of",
        "on",
        "previously",
        "recall",
        "record",
        "remember",
        "the",
        "to",
        "was",
        "what",
        "when",
        "which",
        "who",
        "why",
    }
)


def decide_sufficiency(
    request: RetrievalRequest,
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    open_issue_ids: Sequence[str],
    derived_result: Mapping[str, Any] | None,
    *,
    stage: SufficiencyStage,
) -> tuple[SufficiencyDecision, str]:
    """Return a completion proof plus a stable diagnostic reason code."""

    if derived_result is not None:
        return _derived_decision(plan, derived_result)
    memory_query_ir = plan.memory_query_ir
    contract = plan.query_task_contract
    unsupported = (
        contract is not None
        and contract.parse_disposition == ParseDisposition.UNSUPPORTED
    )
    if unsupported or (memory_query_ir is not None and memory_query_ir.mode == "AMBIGUOUS"):
        return (
            SufficiencyDecision(
                status="UNSATISFIED",
                missing_slots=_required_slots(plan),
                stop_reason="QUERY_AMBIGUOUS",
            ),
            "QUERY_TASK_CONTRACT_UNSUPPORTED" if unsupported else "MEMORY_QUERY_IR_AMBIGUOUS",
        )
    if (
        contract is not None
        and contract.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL
    ):
        # Best-effort parsing authorizes governed recall, not a semantic
        # completion claim.  Retrieval may continue and expose context, while
        # the sole final Decision boundary remains explicitly non-COMPLETE.
        required = _required_slots(plan)
        return (
            SufficiencyDecision(
                status="PARTIAL" if results else "UNSATISFIED",
                missing_slots=required,
                stop_reason="QUERY_AMBIGUOUS",
            ),
            "BEST_EFFORT_RECALL_NOT_COMPLETE",
        )
    if plan.operator is not None:
        required = _required_slots(plan)
        return (
            SufficiencyDecision(
                status="UNSATISFIED" if not results else "PARTIAL",
                missing_slots=required,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "OPERATOR_RESULT_INCOMPLETE",
        )

    operator_family = (
        infer_operator_family(memory_query_ir)
        if memory_query_ir is not None
        else None
    )
    typed_operation_unexecuted = (
        contract is not None
        and contract.operation not in {None, QueryOperation.LOOKUP, QueryOperation.STATE_AS_OF}
    )
    if typed_operation_unexecuted or (
        contract is None
        and memory_query_ir is not None
        and operator_family != "LOOKUP"
    ):
        missing = _required_slots(plan)
        unbounded = (
            contract is None
            and memory_query_ir is not None
            and memory_query_ir.completeness == "ALL_MATCHES_IN_RANGE"
            and memory_query_ir.constraints.normalized_temporal is not None
            and memory_query_ir.constraints.normalized_temporal.boundary == "UNBOUNDED"
        )
        return (
            SufficiencyDecision(
                status=("UNBOUNDED" if unbounded else ("PARTIAL" if results else "UNSATISFIED")),
                missing_slots=missing,
                stop_reason="QUERY_AMBIGUOUS" if unbounded else "SEARCH_SPACE_EXHAUSTED",
            ),
            "MEMORY_QUERY_IR_OPERATOR_UNEXECUTED",
        )

    # Raw query parsing is retained only for historic QueryPlans.  New plans
    # receive all operation and proof semantics from QueryTaskContractV01.
    implicit_slots = (
        _unexecuted_requirement_slots(request.query or "")
        if contract is None
        else []
    )
    if implicit_slots:
        return (
            SufficiencyDecision(
                status="PARTIAL" if results else "UNSATISFIED",
                missing_slots=implicit_slots,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "QUERY_OPERATOR_UNEXECUTED",
        )

    evidence = [item for item in results if item.get("kind") == "EVIDENCE_OBSERVATION"]
    canonical = [item for item in results if item.get("kind") != "EVIDENCE_OBSERVATION"]
    if evidence:
        evidence_decision = _evidence_lookup_decision(request, evidence)
        if evidence_decision[0].complete or not canonical:
            return evidence_decision
    return _canonical_decision(
        request,
        plan,
        canonical,
        open_issue_ids,
        stage=stage,
    )


def budget_exhausted_decision(
    covered_slots: Sequence[str] = (), missing_slots: Sequence[str] = ()
) -> SufficiencyDecision:
    return SufficiencyDecision(
        status="PARTIAL" if covered_slots else "UNSATISFIED",
        covered_slots=list(covered_slots),
        missing_slots=list(missing_slots),
        stop_reason="BUDGET_EXHAUSTED",
    )


def unavailable_decision() -> SufficiencyDecision:
    return SufficiencyDecision(
        status="UNSATISFIED",
        stop_reason="MEMORY_UNAVAILABLE",
    )


def _derived_decision(
    plan: QueryPlan, result: Mapping[str, Any]
) -> tuple[SufficiencyDecision, str]:
    status = str(result.get("status", ""))
    required = _required_slots(plan, result)
    covered = _covered_slots(result)
    missing = [slot for slot in required if slot not in covered]
    proof = _composition_proof(result)

    if status in {"CONTESTED"}:
        return (
            SufficiencyDecision(
                status="CONTESTED",
                covered_slots=covered,
                missing_slots=missing,
                proof=proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "DERIVED_RESULT_CONTESTED",
        )
    if status in {"DENIED"}:
        return (
            SufficiencyDecision(
                status="UNSATISFIED",
                covered_slots=covered,
                missing_slots=missing,
                proof=proof,
                stop_reason="ACCESS_DENIED",
            ),
            "DERIVED_RESULT_ACCESS_DENIED",
        )
    if status in {"UNAVAILABLE"}:
        return (
            SufficiencyDecision(
                status="UNSATISFIED",
                covered_slots=covered,
                missing_slots=missing,
                proof=proof,
                stop_reason="MEMORY_UNAVAILABLE",
            ),
            "DERIVED_RESULT_UNAVAILABLE",
        )
    if status in {"ABSENT", "ABSTAINED"}:
        return (
            SufficiencyDecision(
                status="UNSATISFIED",
                covered_slots=covered,
                missing_slots=missing or required,
                proof=proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            str(result.get("reason") or "DERIVED_RESULT_UNSATISFIED"),
        )
    if status == "PARTIAL":
        return (
            SufficiencyDecision(
                status="PARTIAL",
                covered_slots=covered,
                missing_slots=missing,
                proof=proof,
                stop_reason=(
                    "PROJECTION_NOT_READY"
                    if result.get("reason") == "PROJECTION_GAP"
                    else "SEARCH_SPACE_EXHAUSTED"
                ),
            ),
            str(result.get("reason") or "DERIVED_RESULT_PARTIAL"),
        )

    completion_claimed = status in {"COMPLETE", "OK"}
    if not completion_claimed or missing:
        return (
            SufficiencyDecision(
                status="PARTIAL" if covered else "UNSATISFIED",
                covered_slots=covered,
                missing_slots=missing or required,
                proof=proof,
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "DERIVED_RESULT_INCOMPLETE",
        )

    if plan.operator == "TEMPORAL_COUNT_DISTINCT" and not (
        proof.bounded_scan_completed
        and proof.source_partition_closed
        and proof.deduplication_completed
    ):
        return (
            SufficiencyDecision(
                status="UNBOUNDED",
                covered_slots=covered,
                proof=proof,
                stop_reason="PROJECTION_NOT_READY",
            ),
            "RANGE_COMPLETENESS_UNPROVEN",
        )
    return (
        SufficiencyDecision(
            status="COMPLETE",
            covered_slots=covered or required,
            proof=proof,
            stop_reason="REQUIREMENT_SATISFIED",
        ),
        "QUERY_REQUIREMENTS_COMPLETE",
    )


def _required_slots(
    plan: QueryPlan, result: Mapping[str, Any] | None = None
) -> list[str]:
    if plan.query_execution_plan is not None:
        requirements = list(plan.query_execution_plan.completion.required_role_keys)
        if requirements:
            return requirements
    if plan.memory_query_ir is not None:
        slots = [
            requirement.slot_id
            for requirement in plan.memory_query_ir.requirements
            if requirement.required
        ]
        if slots:
            return slots
    raw = plan.operator_arguments.get("required_slots")
    if isinstance(raw, list):
        return [str(value) for value in raw if isinstance(value, str) and value]
    count = plan.operator_arguments.get("required_operand_count")
    if not isinstance(count, int):
        count = plan.operator_arguments.get("minimum_operand_count")
    if isinstance(count, int) and count > 0:
        return [f"OPERAND_{index + 1}" for index in range(count)]
    operands = result.get("operands") if result is not None else None
    if isinstance(operands, list) and operands:
        return [f"OPERAND_{index + 1}" for index in range(len(operands))]
    return ["OPERATOR_RESULT"] if plan.operator is not None else []


def _covered_slots(result: Mapping[str, Any]) -> list[str]:
    completeness = result.get("completeness")
    if isinstance(completeness, Mapping):
        raw = completeness.get("filled_slots")
        if isinstance(raw, list):
            return [str(value) for value in raw if isinstance(value, str) and value]
    operands = result.get("operands")
    if isinstance(operands, list):
        return [f"OPERAND_{index + 1}" for index in range(len(operands))]
    return []


def _composition_proof(result: Mapping[str, Any]) -> SufficiencyProof:
    completeness = result.get("completeness")
    values = completeness if isinstance(completeness, Mapping) else {}
    count_trace = result.get("count_trace")
    count_values = count_trace if isinstance(count_trace, Mapping) else {}
    projection = values.get("projection_position")
    return SufficiencyProof(
        bounded_scan_completed=values.get("bounded_scan_complete") is True,
        source_partition_closed=values.get("source_partition_closed") is True,
        projection_watermark=(
            int(projection)
            if isinstance(projection, int) and not isinstance(projection, bool)
            else None
        ),
        deduplication_completed=(
            result.get("operator") != "TEMPORAL_COUNT_DISTINCT"
            or (
                result.get("status") == "COMPLETE"
                and isinstance(count_values.get("deduplicated_events"), int)
            )
        ),
        version_chain_complete=False,
    )


def build_intermediate_sufficiency_proof(
    result: Mapping[str, Any] | None,
) -> SufficiencyProof:
    """Expose proof extraction without granting a completion disposition."""

    return _composition_proof(result) if result is not None else SufficiencyProof()


def _evidence_lookup_decision(
    request: RetrievalRequest, evidence: Sequence[Mapping[str, Any]]
) -> tuple[SufficiencyDecision, str]:
    if request.required_authority == "ACTION_SAFE":
        return (
            SufficiencyDecision(
                status="PARTIAL",
                missing_slots=["AUTHORITY_SAFE_ANSWER"],
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "ACTION_SAFE_REQUIRES_FULL_PIPELINE",
        )
    query_terms = _meaningful_terms(request.query or "")
    answer_bearing = [
        item
        for item in evidence
        if query_terms.intersection(_meaningful_terms(str(item.get("content", ""))))
    ]
    if not answer_bearing:
        return (
            SufficiencyDecision(
                status="UNSATISFIED",
                missing_slots=["LOOKUP_ANSWER"],
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "EVIDENCE_CANDIDATE_NOT_ANSWER_BEARING",
        )
    return (
        SufficiencyDecision(
            status="PARTIAL",
            missing_slots=["LOOKUP_ANSWER"],
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        "EVIDENCE_LOOKUP_CANDIDATE_ONLY",
    )


def _canonical_decision(
    request: RetrievalRequest,
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    open_issue_ids: Sequence[str],
    *,
    stage: SufficiencyStage,
) -> tuple[SufficiencyDecision, str]:
    if not results:
        return (
            SufficiencyDecision(
                status="UNSATISFIED",
                missing_slots=_required_slots(plan) or ["LOOKUP_ANSWER"],
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "NO_CANONICAL_RESULT",
        )
    if request.required_authority == "ACTION_SAFE" and stage != "FINAL":
        return (
            SufficiencyDecision(
                status="PARTIAL",
                covered_slots=["CANONICAL_RESULT"],
                missing_slots=["FULL_PIPELINE_AUTHORITY_CHECK"],
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "ACTION_SAFE_REQUIRES_FULL_PIPELINE",
        )
    if request.consistency == "READ_YOUR_WRITES" and stage != "FINAL":
        return (
            SufficiencyDecision(
                status="PARTIAL",
                covered_slots=["CANONICAL_RESULT"],
                missing_slots=["FULL_PIPELINE_CAUSAL_CHECK"],
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            ),
            "READ_YOUR_WRITES_REQUIRES_FULL_PIPELINE",
        )
    if plan.access_intent == "POSSIBLE":
        if open_issue_ids:
            return (
                SufficiencyDecision(
                    status="CONTESTED",
                    covered_slots=["CANONICAL_RESULT"],
                    missing_slots=["OPEN_ISSUE_RESOLUTION"],
                    stop_reason="SEARCH_SPACE_EXHAUSTED",
                ),
                "POSSIBLE_PROBE_HAS_OPEN_ISSUE",
            )
        return _complete(f"POSSIBLE_CANONICAL_{stage}_PROBE_SUFFICIENT")
    if stage == "FINAL" and request.memory_intent is None:
        return _complete("TOP_K_EPISODIC_LOOKUP_COMPLETE")
    if request.memory_intent is None:
        return (
            SufficiencyDecision(
                status="PARTIAL",
                covered_slots=["CANONICAL_RESULT"],
                missing_slots=["TYPED_MEMORY_NEED"],
                stop_reason="QUERY_AMBIGUOUS",
            ),
            "UNTYPED_NEED_REQUIRES_FULL_PIPELINE",
        )
    if stage == "FTS":
        if request.memory_intent != "CURRENT_STATE":
            return _partial("NON_SINGLETON_NEED_REQUIRES_VECTOR")
        if len(results) != 1 or open_issue_ids:
            return _partial("CURRENT_STATE_NOT_SINGLETON_OR_HAS_OPEN_ISSUE")
        matched = results[0].get("matched_by")
        if not isinstance(matched, list) or not {"exact", "fts"}.intersection(matched):
            return _partial("CURRENT_STATE_LACKS_LEXICAL_ANCHOR")
        return _complete("CURRENT_SINGLETON_CANONICAL_LEXICAL_SUFFICIENT")
    if request.memory_intent == "CONFLICT" and not open_issue_ids:
        return _partial("CONFLICT_NEED_LACKS_LIVE_OPEN_ISSUE")
    if request.memory_intent in {"HISTORY", "EXPLANATION"} and not all(
        isinstance(result.get("evidence_ids"), list) and result["evidence_ids"]
        for result in results
    ):
        return _partial("HISTORY_OR_EXPLANATION_LACKS_PROVENANCE")
    if request.memory_intent not in {
        "CURRENT_STATE",
        "HISTORY",
        "EXPLANATION",
        "CONFLICT",
    }:
        return _partial("MEMORY_INTENT_REQUIRES_FULL_PIPELINE")
    return _complete(f"TYPED_NEED_CANONICAL_{stage}_SUFFICIENT")


def _complete(reason: str) -> tuple[SufficiencyDecision, str]:
    return (
        SufficiencyDecision(
            status="COMPLETE",
            covered_slots=["CANONICAL_RESULT"],
            stop_reason="REQUIREMENT_SATISFIED",
        ),
        reason,
    )


def _partial(reason: str) -> tuple[SufficiencyDecision, str]:
    return (
        SufficiencyDecision(
            status="PARTIAL",
            covered_slots=["CANONICAL_RESULT"],
            missing_slots=["FULL_PIPELINE_COMPLETION"],
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        reason,
    )


def _meaningful_terms(value: str) -> frozenset[str]:
    return frozenset(
        token
        for raw in _WORD.findall(value.casefold())
        if (token := cast(str, raw)) not in _LOOKUP_STOPWORDS and len(token) > 1
    )


def _unexecuted_requirement_slots(query: str) -> list[str]:
    if has_count_intent(query):
        return ["ALL_MATCHES_IN_RANGE"]
    if _UNEXECUTED_ORDER.search(query):
        return ["OPERAND_1", "OPERAND_2", "TEMPORAL_ORDER_RESULT"]
    if _UNEXECUTED_RELATIVE_TIME.search(query):
        return ["TARGET_EVENT_AT_RELATIVE_TIME"]
    if _UNEXECUTED_PREFERENCE.search(query):
        return ["PREFERENCE_SIGNAL_SET"]
    return []


__all__ = [
    "SufficiencyStage",
    "budget_exhausted_decision",
    "build_intermediate_sufficiency_proof",
    "decide_sufficiency",
    "unavailable_decision",
]
