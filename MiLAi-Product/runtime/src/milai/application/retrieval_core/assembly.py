from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from milai.adapters import CrossEncoderReranker
from milai.application.evidence_acquisition import (
    DeferredEvidenceAcquisitionExecution,
    EvidenceAcquisitionExecutionRef,
)
from milai.application.evidence_source import evidence_source_turn_identity
from milai.application.lean_recall import compile_lean_recall_plan
from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.application.reader_evidence_plan import (
    DecisionSnapshotRef,
    build_decision_snapshot,
)
from milai.application.retrieval_core.operators import (
    _explicit_compound_subject_matches,
    _operator_support_refs,
    _state_count_cover,
)
from milai.application.retrieval_core.selection import _mmr_select
from milai.application.retrieval_core.temporal import (
    _binary_anchor_cover,
    _binary_event_anchor_terms,
    _relative_point_cover,
    _relative_point_target,
    _temporal_rerank,
)
from milai.domain.acquisition import AcquisitionPlan, AcquisitionState
from milai.domain.lean_recall import (
    EvidenceSet,
    EvidenceSetItem,
    LeanRecallPlan,
    RetrievalOccurrence,
)
from milai.domain.reader_evidence_plan import AcceptedBindingSpan
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import EvidenceRequirementV02, EvidenceSpan, MemoryQueryIRV02
from milai.domain.sufficiency import SufficiencyDecision
from milai.persistence.retrieval_repository import (
    GatedBatch,
    ProjectionState,
    RetrievalCandidate,
)


def _assemble_results(
    ranked: list[RetrievalCandidate],
    matched_by: dict[UUID, list[str]],
    batch: GatedBatch,
    limit: int,
    *,
    query: str | None = None,
    reference_time: datetime | None = None,
    plan: QueryPlan | None = None,
    mmr_enabled: bool = False,
    mmr_lambda: float = 0.8,
    reranker: CrossEncoderReranker | None = None,
    reranker_pool_size: int = 10,
    temporal_reranker_pool_size: int = 10,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, Any]],
    list[str],
]:
    ranking = {candidate.claim_version_id: candidate for candidate in ranked}
    outcomes = {UUID(str(outcome["claim_version_id"])): outcome for outcome in batch.outcomes}
    claims = {UUID(str(claim["claim_version_id"])): claim for claim in batch.claims}
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    results: list[dict[str, Any]] = []
    related_open_issue_ids: set[str] = set()
    for candidate in ranked:
        outcome = outcomes.get(candidate.claim_version_id)
        if outcome is not None:
            related_open_issue_ids.update(str(value) for value in outcome.get("open_issue_ids", []))
        if outcome is None or outcome.get("accepted") is not True:
            rejected.append(
                {
                    "claim_version_id": str(candidate.claim_version_id),
                    "reject_reason": (
                        str(outcome.get("reject_reason"))
                        if outcome is not None
                        else "GATE_RESULT_MISSING"
                    ),
                }
            )
            continue
        claim = claims.get(candidate.claim_version_id)
        if claim is None:
            rejected.append(
                {
                    "claim_version_id": str(candidate.claim_version_id),
                    "reject_reason": "CANONICAL_HYDRATION_MISSING",
                }
            )
            continue
        if query is not None and not _explicit_compound_subject_matches(query, claim):
            rejected.append(
                {
                    "claim_version_id": str(candidate.claim_version_id),
                    "reject_reason": "QUERY_SUBJECT_MISMATCH",
                }
            )
            continue
        score = round(ranking[candidate.claim_version_id].score, 8)
        evidence_ids = [str(value) for value in outcome.get("evidence_ids", [])]
        open_issue_ids = [str(value) for value in outcome.get("open_issue_ids", [])]
        sources = matched_by.get(candidate.claim_version_id, [])
        result = dict(claim)
        result.update(
            {
                "relevance_score": score,
                "matched_by": sources,
                "evidence_ids": evidence_ids,
                "open_issue_ids": open_issue_ids,
            }
        )
        results.append(result)
        accepted.append(
            {
                "claim_id": str(outcome["claim_id"]),
                "claim_version_id": str(candidate.claim_version_id),
                "relevance_score": score,
                "matched_by": sources,
                "evidence_ids": evidence_ids,
            }
        )
    results = _temporal_rerank(results, query, reference_time=reference_time)
    result_order = {str(result["claim_version_id"]): index for index, result in enumerate(results)}
    accepted.sort(
        key=lambda item: result_order.get(str(item["claim_version_id"]), len(result_order))
    )
    binary_anchors = _binary_event_anchor_terms(plan)
    relative_target = _relative_point_target(plan)
    if reranker is not None and query and results:
        state_count = plan is not None and plan.operator == "COUNT_DISTINCT"
        selected_pool_size = (
            temporal_reranker_pool_size
            if binary_anchors is not None or relative_target is not None or state_count
            else reranker_pool_size
        )
        rerank_limit = (
            min(selected_pool_size, len(results))
            if binary_anchors is not None or relative_target is not None or state_count
            else limit
        )
        execution = reranker.rerank(
            query, results, limit=rerank_limit, pool_size=selected_pool_size
        )
        if binary_anchors is not None:
            results = _binary_anchor_cover(execution.results, binary_anchors, limit)
        elif relative_target is not None:
            results = _relative_point_cover(execution.results, relative_target, limit, query=query)
        elif state_count:
            results = _state_count_cover(execution.results, query, limit)
        else:
            results = execution.results
        selected_ids = {str(result["claim_version_id"]) for result in results}
        accepted = [item for item in accepted if str(item["claim_version_id"]) in selected_ids]
        accepted_by_id = {str(item["claim_version_id"]): item for item in accepted}
        accepted = [accepted_by_id[str(result["claim_version_id"])] for result in results]
        for result, item in zip(results, accepted, strict=True):
            item["reranker"] = result["reranker"]
    elif binary_anchors is not None:
        results = _binary_anchor_cover(results, binary_anchors, limit)
        selected_ids = {str(result["claim_version_id"]) for result in results}
        accepted = [item for item in accepted if str(item["claim_version_id"]) in selected_ids]
        accepted_by_id = {str(item["claim_version_id"]): item for item in accepted}
        accepted = [accepted_by_id[str(result["claim_version_id"])] for result in results]
    elif relative_target is not None:
        results = _relative_point_cover(results, relative_target, limit, query=query or "")
        selected_ids = {str(result["claim_version_id"]) for result in results}
        accepted = [item for item in accepted if str(item["claim_version_id"]) in selected_ids]
        accepted_by_id = {str(item["claim_version_id"]): item for item in accepted}
        accepted = [accepted_by_id[str(result["claim_version_id"])] for result in results]
    elif mmr_enabled:
        results = _mmr_select(results, limit, relevance_weight=mmr_lambda)
        selected_ids = {str(result["claim_version_id"]) for result in results}
        accepted = [item for item in accepted if str(item["claim_version_id"]) in selected_ids]
        accepted.sort(
            key=lambda item: next(
                index
                for index, result in enumerate(results)
                if str(result["claim_version_id"]) == str(item["claim_version_id"])
            )
        )
    else:
        results = results[:limit]
        accepted = accepted[:limit]
    return accepted, rejected, results, sorted(related_open_issue_ids)


def _response_body(
    *,
    plan: QueryPlan,
    results: list[dict[str, Any]],
    open_issue_ids: list[str],
    trace_id: UUID | None,
    state: ProjectionState | None,
    degraded: set[str],
    fallback_used: bool,
    fallback_reason: str | None,
    abstained: bool,
    abstention_reason: str | None,
    minimum_outbox_sequence: int | None,
    causal_wait_outcome: str | None,
    causal_waited_ms: int,
    derived_result: dict[str, Any] | None,
    stage_metrics: dict[str, Any],
    progressive_l1: dict[str, Any],
    access_trace: dict[str, Any],
) -> dict[str, Any]:
    snapshot = None
    if state is not None:
        snapshot = {
            "canonical_outbox_sequence": state.canonical_snapshot_outbox_sequence,
            "evidence_watermark": state.evidence_watermark,
            "fts_watermark": state.fts_watermark,
            "vector_watermark": state.vector_watermark,
        }
    return {
        "route": plan.complexity,
        "consistency": plan.consistency_mode,
        "query_plan": plan.model_dump(mode="json"),
        "results": results,
        "derived_result": derived_result,
        "open_issue_ids": open_issue_ids,
        "retrieval_trace_id": str(trace_id) if trace_id is not None else None,
        "snapshot": snapshot,
        "degraded_components": sorted(degraded),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "abstained": abstained,
        "causal_wait": {
            "minimum_outbox_sequence": minimum_outbox_sequence,
            "outcome": causal_wait_outcome,
            "waited_ms": causal_waited_ms,
        },
        "abstention_reason": abstention_reason,
        "stage_metrics": stage_metrics,
        "progressive_l1": progressive_l1,
        "access_plan": {
            "schema_version": "memory-access-plan-v1",
            "access_intent": plan.access_intent,
            "candidate_cap": plan.candidate_cap,
            "deadline_ms": plan.deadline_ms,
            "context_token_budget": plan.context_budget,
            "reranker_candidate_cap": plan.reranker_candidate_cap,
            "hard_partitions": plan.hard_partitions,
            "vector_policy": plan.vector_policy,
            "reranker_policy": plan.reranker_policy,
        },
        "access_trace": access_trace,
    }


def _contains_evidence_observation(results: list[dict[str, Any]]) -> bool:
    return any(item.get("kind") == "EVIDENCE_OBSERVATION" for item in results)


def _projection_state_payload(state: ProjectionState) -> dict[str, int | bool]:
    return {
        "canonical_snapshot_outbox_sequence": (state.canonical_snapshot_outbox_sequence),
        "evidence_watermark": state.evidence_watermark,
        "fts_watermark": state.fts_watermark,
        "vector_watermark": state.vector_watermark,
        "evidence_dead_letter": state.evidence_dead_letter,
        "fts_dead_letter": state.fts_dead_letter,
        "vector_dead_letter": state.vector_dead_letter,
    }


def _decision_snapshot(
    *,
    plan: QueryPlan,
    projection_state: ProjectionState,
    acquisition_plan: AcquisitionPlan | None,
    acquisition_execution: EvidenceAcquisitionExecutionRef | None,
    acquisition_state: AcquisitionState | None,
    accepted: list[dict[str, object]],
    rejected: list[dict[str, object]],
    results: list[dict[str, Any]],
    final_decision: SufficiencyDecision,
    derived_result: dict[str, Any] | None,
    defer_digests: bool = False,
) -> DecisionSnapshotRef:
    """Capture one immutable semantic decision before Context presentation."""

    query_ir = plan.memory_query_ir
    lean_recall_plan = compile_lean_recall_plan(plan)
    required_requirement_ids = _decision_requirement_ids(query_ir, final_decision)
    missing = sorted(final_decision.missing_slots)
    supporting_evidence_ids, supporting_source_refs = _operator_support_refs(derived_result)
    accepted_evidence_ids = _decision_accepted_evidence_ids(
        acquisition_state=acquisition_state,
        acquisition_execution=acquisition_execution,
        results=results,
        supporting_evidence_ids=supporting_evidence_ids,
        supporting_source_refs=supporting_source_refs,
    )
    accepted_binding_spans = _accepted_binding_spans(
        acquisition_execution,
        accepted_evidence_ids=set(accepted_evidence_ids),
        requirements=(query_ir.requirements if query_ir is not None else ()),
        supporting_evidence_ids=(supporting_evidence_ids if derived_result is not None else None),
        supporting_source_refs=(supporting_source_refs if derived_result is not None else None),
    )
    evidence_set = _requirement_evidence_set(
        lean_recall_plan=lean_recall_plan,
        required_requirement_ids=required_requirement_ids,
        accepted_binding_spans=accepted_binding_spans,
        execution=acquisition_execution,
    )
    candidate_material: object
    binding_material: object
    if acquisition_execution is None:
        candidate_material = {
            "identity": "LEGACY_GOVERNED_RESULT_CANDIDATES",
            "results": results,
        }
        binding_material = {"identity": "LEGACY_RESULT_BINDING", "results": results}
    elif isinstance(acquisition_execution, DeferredEvidenceAcquisitionExecution) and defer_digests:
        candidate_material = acquisition_execution.candidates
        binding_material = acquisition_execution.semantics
    else:
        candidate_material = acquisition_execution.candidates
        binding_material = {
            "spans": acquisition_execution.spans,
            "interpretations": acquisition_execution.interpretations,
            "bindings": acquisition_execution.bindings,
            "semantic_audit": acquisition_execution.semantic_audit,
        }
    requirement_state_material: object = (
        acquisition_state.requirement_state
        if acquisition_state is not None
        else {
            "identity": "SUFFICIENCY_DERIVED_REQUIREMENT_STATE",
            "required": required_requirement_ids,
            "covered": sorted(final_decision.covered_slots),
            "missing": missing,
        }
    )
    return build_decision_snapshot(
        source_snapshot_material=_projection_state_payload(projection_state),
        query_ir_material=(
            query_ir if query_ir is not None else {"identity": "MEMORY_QUERY_IR_ABSENT"}
        ),
        acquisition_plan_material=(
            acquisition_plan
            if acquisition_plan is not None
            else {"identity": "ACQUISITION_PLAN_NOT_APPLICABLE"}
        ),
        candidate_snapshot_material=candidate_material,
        gate_material={"accepted": accepted, "rejected": rejected},
        binding_material=binding_material,
        requirement_state_material=requirement_state_material,
        sufficiency_material=final_decision,
        operator_result_material=derived_result,
        lean_recall_mode=lean_recall_plan.mode,
        lean_recall_plan_material=lean_recall_plan,
        evidence_set=evidence_set,
        accepted_evidence_ids=accepted_evidence_ids,
        accepted_binding_spans=accepted_binding_spans,
        rejected_reasons=[
            str(item["reject_reason"])
            for item in rejected
            if isinstance(item.get("reject_reason"), str)
        ],
        required_requirement_ids=required_requirement_ids,
        unresolved_requirement_ids=missing,
        defer_digests=defer_digests,
    )


def _requirement_evidence_set(
    *,
    lean_recall_plan: LeanRecallPlan,
    required_requirement_ids: Sequence[str],
    accepted_binding_spans: Sequence[AcceptedBindingSpan],
    execution: EvidenceAcquisitionExecutionRef | None,
) -> EvidenceSet:
    role_by_requirement = {
        item.requirement_id: item.requirement_role
        for item in lean_recall_plan.requirements
    }
    candidate_by_evidence_id = (
        {item.source_evidence_id: item for item in execution.candidates}
        if execution is not None
        else {}
    )
    items: list[EvidenceSetItem] = []
    for span in accepted_binding_spans:
        candidate = candidate_by_evidence_id.get(span.evidence_id)
        occurrences: list[RetrievalOccurrence] = []
        if candidate is not None:
            occurrences.extend(
                RetrievalOccurrence(
                    channel=channel,
                    channel_rank=rank,
                    fusion_rank=candidate.fusion_rank,
                    expansion_origin=candidate.expansion_origin,
                )
                for channel, rank in sorted(candidate.channel_ranks.items())
            )
            occurrences.extend(
                RetrievalOccurrence(
                    channel="PROBE",
                    probe_id=probe_id,
                    probe_rank=rank,
                    fusion_rank=candidate.fusion_rank,
                    expansion_origin=candidate.expansion_origin,
                )
                for probe_id, rank in sorted(candidate.probe_ranks.items())
            )
        items.append(
            EvidenceSetItem(
                requirement_ids=span.requirement_ids,
                requirement_roles=tuple(
                    sorted(
                        {
                            role_by_requirement.get(requirement_id, requirement_id)
                            for requirement_id in span.requirement_ids
                        }
                    )
                ),
                evidence_id=span.evidence_id,
                source_turn_ref=span.source_turn_ref,
                session_id=span.session_id,
                source_role=span.speaker,
                start=span.start,
                end=span.end,
                text=span.text,
                observed_at=span.observed_at,
                occurrences=tuple(
                    sorted(
                        occurrences,
                        key=lambda item: (
                            item.channel,
                            item.probe_id or "",
                            item.channel_rank or 0,
                            item.probe_rank or 0,
                            item.fusion_rank or 0,
                        ),
                    )
                ),
            )
        )
    return EvidenceSet(
        required_requirement_ids=tuple(sorted(set(required_requirement_ids))),
        items=tuple(
            sorted(
                items,
                key=lambda item: (
                    item.source_turn_ref,
                    item.start,
                    item.end,
                    item.requirement_ids,
                    item.evidence_id,
                ),
            )
        ),
    )


def _decision_requirement_ids(
    query_ir: MemoryQueryIRV02 | None,
    final_decision: SufficiencyDecision,
) -> list[str]:
    """Resolve the immutable requirement universe for a decision snapshot.

    Semantic L1 queries own an explicit QueryIR, so every Sufficiency reference
    must be drawn from it.  Legacy exact/L0 queries intentionally have no
    QueryIR; for those paths the already-frozen Sufficiency decision is the
    semantic authority, and its covered/missing union is the complete universe.
    """

    referenced = set(final_decision.covered_slots).union(final_decision.missing_slots)
    if query_ir is None:
        return sorted(referenced)
    required = sorted(
        requirement.slot_id for requirement in query_ir.requirements if requirement.required
    )
    # Covered slots may carry legacy execution summaries such as
    # CANONICAL_RESULT.  Only unresolved slots become Reader requirements and
    # therefore must be owned by the immutable QueryIR.
    unexpected = set(final_decision.missing_slots).difference(required)
    if unexpected:
        raise AssertionError(
            "sufficiency references requirements outside the immutable QueryIR: "
            + ",".join(sorted(unexpected))
        )
    return required


def _decision_accepted_evidence_ids(
    *,
    acquisition_state: AcquisitionState | None,
    acquisition_execution: EvidenceAcquisitionExecutionRef | None,
    results: Sequence[Mapping[str, Any]],
    supporting_evidence_ids: set[str],
    supporting_source_refs: set[str],
) -> list[str]:
    """Combine bounded state notes with operator support from one governed snapshot.

    EvidenceReferenceNote is intentionally bounded and may therefore be a
    non-exhaustive cache of accepted provenance.  An internal deterministic
    operator can add a support only when that Evidence is present in the same
    governed result snapshot; arbitrary or stale result references cannot
    enlarge the decision boundary.
    """

    governed_ids = {
        evidence_id for result in results for evidence_id in _result_evidence_ids(dict(result))
    }
    accepted_ids = (
        {note.evidence_id for note in acquisition_state.accepted_evidence_refs}
        if acquisition_state is not None
        else set(governed_ids)
    )
    operator_supported_ids = set(supporting_evidence_ids)
    if acquisition_execution is not None and supporting_source_refs:
        operator_supported_ids.update(
            span.source_evidence_id
            for span in acquisition_execution.spans
            if span.source_turn_ref in supporting_source_refs
        )
    formation_backed_operator = (
        acquisition_execution is not None
        and bool(operator_supported_ids)
        and any(
            getattr(span, "provenance", {}).get("formation_artifact_kind") is not None
            for span in acquisition_execution.spans
        )
    )
    if formation_backed_operator:
        # Raw neighbors remain in the sealed decision audit, but only explicit
        # operator operands cross the Reader boundary as accepted evidence.
        return sorted(operator_supported_ids.intersection(governed_ids))
    accepted_ids.update(operator_supported_ids.intersection(governed_ids))
    return sorted(accepted_ids)


def _accepted_binding_spans(
    execution: EvidenceAcquisitionExecutionRef | None,
    *,
    accepted_evidence_ids: set[str],
    requirements: Sequence[EvidenceRequirementV02] = (),
    supporting_evidence_ids: set[str] | None = None,
    supporting_source_refs: set[str] | None = None,
) -> list[AcceptedBindingSpan]:
    """Project answer-supporting MATCH bindings to exact source spans.

    A single-valued requirement exposes one earliest governed provenance root,
    not every later repetition of the same answer-bearing event.  When an
    operator result exists, its explicit provenance is the protection boundary:
    the wider proof scan remains in the sealed decision audit without making
    every classified candidate an untrimmable Reader unit.
    """

    if execution is None:
        return []
    accepted_bindings = operator_operands_from_raw_bindings(execution.bindings)
    if not accepted_bindings:
        return []
    span_by_id = {span.span_id: span for span in execution.spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation
        for interpretation in execution.interpretations
    }
    span_ids_by_requirement: dict[str, set[str]] = defaultdict(set)
    for binding in accepted_bindings:
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        if interpretation is not None:
            span = span_by_id.get(interpretation.span_id)
            answer_supporting = (
                supporting_evidence_ids is None and supporting_source_refs is None
            ) or (
                span is not None
                and (
                    span.source_evidence_id in (supporting_evidence_ids or set())
                    or span.source_turn_ref in (supporting_source_refs or set())
                )
            )
            if (
                span is not None
                and span.source_evidence_id in accepted_evidence_ids
                and answer_supporting
            ):
                span_ids_by_requirement[binding.requirement_id].add(interpretation.span_id)
    maximum_by_requirement = {
        requirement.slot_id: requirement.cardinality.maximum for requirement in requirements
    }
    retained_requirement_ids_by_span: dict[str, set[str]] = defaultdict(set)
    for requirement_id, span_ids in span_ids_by_requirement.items():
        ordered = sorted(
            span_ids,
            key=lambda span_id: _binding_span_provenance_order(span_by_id[span_id]),
        )
        maximum = maximum_by_requirement.get(requirement_id)
        for span_id in ordered if maximum is None else ordered[:maximum]:
            retained_requirement_ids_by_span[span_id].add(requirement_id)
    projected = []
    for span_id, requirement_ids in retained_requirement_ids_by_span.items():
        span = span_by_id.get(span_id)
        if span is None:
            continue
        projected.append(
            AcceptedBindingSpan(
                requirement_ids=tuple(sorted(requirement_ids)),
                evidence_id=span.source_evidence_id,
                source_turn_ref=span.source_turn_ref,
                session_id=span.session_id,
                speaker=span.speaker,
                start=span.start,
                end=span.end,
                text=span.text,
                observed_at=(
                    span.source_timestamp.isoformat() if span.source_timestamp is not None else None
                ),
            )
        )
    return sorted(
        projected,
        key=lambda item: (
            item.source_turn_ref,
            item.start,
            item.end,
            item.requirement_ids,
            item.evidence_id,
        ),
    )


def _binding_span_provenance_order(span: EvidenceSpan) -> tuple[str, str, int, int]:
    turn_identity = evidence_source_turn_identity(span.source_turn_ref)
    episode = turn_identity[0] if turn_identity is not None else span.source_turn_ref
    turn = turn_identity[1] if turn_identity is not None else 2**31 - 1
    return (
        span.source_timestamp.isoformat() if span.source_timestamp is not None else "",
        episode,
        turn,
        span.start,
    )


def _result_evidence_ids(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    evidence_id = result.get("evidence_id")
    if isinstance(evidence_id, str) and evidence_id:
        values.append(evidence_id)
    evidence_ids = result.get("evidence_ids")
    if isinstance(evidence_ids, list):
        values.extend(value for value in evidence_ids if isinstance(value, str) and value)
    return values

