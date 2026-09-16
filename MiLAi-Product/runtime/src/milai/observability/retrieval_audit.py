"""Default-off, immutable observation of the official retrieval path."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol, cast

from milai.application.acquisition import probe_query
from milai.application.evidence_source import evidence_source_turn_identity
from milai.domain.acquisition import AcquisitionPlan
from milai.domain.reader_evidence_plan import DecisionSnapshot
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.retrieval_audit import (
    CandidateLifecycleStepV01,
    CandidateLifecycleTraceV01,
    DedupDecisionV01,
    EvidenceCandidateV01,
    EvidenceRecordIdentityV01,
    EvidenceSpanIdentityV01,
    LifecycleDisposition,
    ProductRetrievalTraceV01,
    RetrievalDocumentIdentityV01,
    RetrievalOccurrenceV01,
    canonical_sha256,
    semantic_sha256,
)
from milai.domain.semantic_query import MemoryQueryIRV02

_OBSERVED_METHODS = frozenset(
    {
        "projection_state",
        "search_evidence",
        "search_evidence_dense",
        "scan_evidence_range",
        "search_evidence_event_range",
        "hydrate_evidence_adjacency",
        "exact_candidates",
        "search_fts",
        "search_vector",
        "gate_and_hydrate",
        "record_trace",
    }
)


class RetrievalAuditObserver(Protocol):
    """Internal callback shape; Runtime never imports an evaluation package."""

    def capture_product_execution(
        self,
        *,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan | None,
        acquisition_execution: Any | None,
        accepted: list[dict[str, object]],
        rejected: list[dict[str, object]],
        results: list[dict[str, Any]],
        final_decision: Any,
        derived_result: dict[str, Any] | None,
        decision_snapshot: DecisionSnapshot,
        progressive_l1: dict[str, Any],
        stage_sequence: tuple[str, ...],
    ) -> None: ...


class RetrievalAuditRecordingObserver(RetrievalAuditObserver, Protocol):
    """Observer capability required by the repository recording proxy."""

    def observe_repository_call(
        self,
        method: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        result: Any,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RepositoryCallObservation:
    ordinal: int
    method: str
    input_digest: str
    input_component_digests: dict[str, str]
    query_digest: str | None
    query_summary: str | None
    limit: int | None
    output_items: tuple[dict[str, Any], ...]
    output_digest: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "method": self.method,
            "input_digest": self.input_digest,
            "input_component_digests": self.input_component_digests,
            "query_digest": self.query_digest,
            "query_summary": self.query_summary,
            "limit": self.limit,
            "output_count": len(self.output_items),
            "output_digest": self.output_digest,
        }


class AuditRecordingRepository:
    """Transparent forwarding proxy that records immutable call observations."""

    def __init__(
        self,
        repository: object,
        observer: RetrievalAuditRecordingObserver,
    ) -> None:
        self._repository = repository
        self._observer = observer

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._repository, name)
        if name not in _OBSERVED_METHODS or not callable(value):
            return value

        def observed(*args: Any, **kwargs: Any) -> Any:
            result = value(*args, **kwargs)
            self._observer.observe_repository_call(name, args, kwargs, result)
            return result

        return observed


class ProductRetrievalAuditObserver:
    """Collect one execution without changing candidate data or iteration order."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.repository_calls: list[RepositoryCallObservation] = []
        self._captured: dict[str, Any] | None = None

    def observe_repository_call(
        self,
        method: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        result: Any,
    ) -> None:
        material = _repository_call_semantics(method, _call_material(method, args, kwargs))
        items = tuple(_safe_output_items(result))
        self.repository_calls.append(
            RepositoryCallObservation(
                ordinal=len(self.repository_calls) + 1,
                method=method,
                input_digest=semantic_sha256(material),
                input_component_digests=_input_component_digests(material),
                query_digest=_query_digest(method, args),
                query_summary=_query_summary(method, args),
                limit=_call_limit(method, args, kwargs),
                output_items=items,
                output_digest=canonical_sha256(items),
            )
        )

    def capture_product_execution(
        self,
        *,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan | None,
        acquisition_execution: Any | None,
        accepted: list[dict[str, object]],
        rejected: list[dict[str, object]],
        results: list[dict[str, Any]],
        final_decision: Any,
        derived_result: dict[str, Any] | None,
        decision_snapshot: DecisionSnapshot,
        progressive_l1: dict[str, Any],
        stage_sequence: tuple[str, ...],
    ) -> None:
        if self._captured is not None:
            raise RuntimeError("RETRIEVAL_AUDIT_OBSERVER_SINGLE_CAPTURE_ONLY")
        behavior_evidence = _behavior_evidence(
            request=request,
            query_plan=query_plan,
            acquisition_execution=acquisition_execution,
            results=results,
            decision_snapshot=decision_snapshot,
            progressive_l1=progressive_l1,
            stage_sequence=stage_sequence,
        )
        behavior_snapshot = {
            name: semantic_sha256(value) for name, value in behavior_evidence.items()
        }
        self._captured = {
            "request": request,
            "query_plan": query_plan,
            "acquisition_plan": acquisition_plan,
            "acquisition_execution": acquisition_execution,
            "accepted": accepted,
            "rejected": rejected,
            "results": results,
            "final_decision": final_decision,
            "derived_result": derived_result,
            "decision_snapshot": decision_snapshot,
            "progressive_l1": progressive_l1,
            "stage_sequence": stage_sequence,
            "behavior_evidence": behavior_evidence,
            "behavior_snapshot": behavior_snapshot,
            "semantic_digest": canonical_sha256(behavior_snapshot),
        }

    @property
    def semantic_digest(self) -> str:
        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        return str(self._captured["semantic_digest"])

    @property
    def behavior_snapshot(self) -> dict[str, str]:
        """Return only governed product semantics, never wall-clock characterization."""

        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        return dict(cast(dict[str, str], self._captured["behavior_snapshot"]))

    @property
    def behavior_evidence(self) -> dict[str, Any]:
        """Return label-free comparison materials to localize any failed field."""

        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        return cast(dict[str, Any], _safe_value(self._captured["behavior_evidence"]))

    def repository_semantic_digest(self) -> str:
        return canonical_sha256(
            [
                {
                    "method": item.method,
                    "input_digest": item.input_digest,
                    "output_digest": item.output_digest,
                }
                for item in self.repository_calls
            ]
        )

    @property
    def captured_request(self) -> RetrievalRequest:
        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        return cast(RetrievalRequest, self._captured["request"])

    @property
    def captured_query_plan(self) -> QueryPlan:
        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        return cast(QueryPlan, self._captured["query_plan"])

    @property
    def captured_acquisition_plan(self) -> AcquisitionPlan:
        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        value = self._captured["acquisition_plan"]
        if not isinstance(value, AcquisitionPlan):
            raise RuntimeError("RETRIEVAL_AUDIT_ACQUISITION_PLAN_NOT_AVAILABLE")
        return value

    def build_product_trace(
        self,
        *,
        run_identity: str,
        query_ir: MemoryQueryIRV02,
        stage_registry_digest: str,
        baseline_digest: str,
    ) -> ProductRetrievalTraceV01:
        if not self.enabled:
            raise RuntimeError("RETRIEVAL_AUDIT_TRACE_DISABLED")
        if self._captured is None:
            raise RuntimeError("RETRIEVAL_AUDIT_EXECUTION_NOT_CAPTURED")
        captured = self._captured
        request = captured["request"]
        query_plan = captured["query_plan"]
        decision: DecisionSnapshot = captured["decision_snapshot"]
        acquisition_plan = captured["acquisition_plan"]
        execution = captured["acquisition_execution"]
        request_identity = canonical_sha256(_request_semantics(request))
        query_identity = canonical_sha256(
            {
                "query": request.query,
                "reference_time": (
                    request.reference_time.isoformat() if request.reference_time else None
                ),
            }
        )
        if canonical_sha256(query_ir.model_dump(mode="json")) != decision.query_ir_digest:
            raise RuntimeError("RETRIEVAL_AUDIT_QUERY_IR_IDENTITY_MISMATCH")
        occurrences = _occurrences(
            request_identity=request_identity,
            acquisition_plan=acquisition_plan,
            acquisition_execution=execution,
            repository_calls=self.repository_calls,
            progressive_l1=captured["progressive_l1"],
        )
        candidates, dedup = _candidates_and_dedup(
            occurrences,
            execution=execution,
            request=request,
        )
        lifecycles = _lifecycles(
            occurrences,
            execution=execution,
            decision=decision,
            query_ir=query_ir,
        )
        terminal = {
            "ordered_candidate_digest": decision.candidate_snapshot_digest,
            "gate_digest": decision.gate_digest,
            "evidence_set_digest": canonical_sha256(list(decision.accepted_evidence_ids)),
            "interpretation_digest": decision.binding_digest,
            "binding_digest": decision.binding_digest,
            "requirement_state_digest": decision.requirement_state_digest,
            "sufficiency_digest": decision.sufficiency_digest,
            "operator_readiness_digest": decision.operator_result_digest,
            "stage_registry_digest": stage_registry_digest,
        }
        trace = ProductRetrievalTraceV01(
            run_identity=run_identity,
            request_identity=request_identity,
            query_identity=query_identity,
            query_plan_digest=canonical_sha256(query_plan.model_dump(mode="json")),
            query_ir_digest=decision.query_ir_digest,
            requirements=[
                {
                    "requirement_id": item.slot_id,
                    "kind": item.interpretation_kind,
                    "required": item.required,
                }
                for item in query_ir.requirements
            ],
            channel_decisions=_channel_decisions(captured["progressive_l1"]),
            occurrences=occurrences,
            candidates=candidates,
            dedup_decisions=dedup,
            candidate_lifecycles=lifecycles,
            proof_obligations=_product_proof_obligations(query_ir, execution),
            terminal_digests=terminal,
            behavior_neutrality={
                "baseline_digest": baseline_digest,
                "traced_digest": captured["semantic_digest"],
                "exact_match": baseline_digest == captured["semantic_digest"],
            },
            repository_call_trace=[item.safe_dict() for item in self.repository_calls],
            safety={
                "reader_calls": 0,
                "generative_provider_calls": 0,
                "canonical_mutation": False,
                "automatic_retry": False,
                "case_id_in_runtime_payload": False,
            },
        )
        return trace


def _occurrences(
    *,
    request_identity: str,
    acquisition_plan: AcquisitionPlan | None,
    acquisition_execution: Any | None,
    repository_calls: Sequence[RepositoryCallObservation],
    progressive_l1: Mapping[str, Any],
) -> list[RetrievalOccurrenceV01]:
    values: list[RetrievalOccurrenceV01] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    probes = {item.probe_id: item for item in acquisition_plan.probes} if acquisition_plan else {}
    traces = getattr(acquisition_execution, "probe_candidate_traces", ())
    for trace in traces:
        probe = probes.get(trace.probe_id)
        query = probe_query(probe) if probe is not None else trace.probe_id
        surviving = set(trace.fusion_surviving_candidate_ids)
        for rank, (evidence_id, source_ref) in enumerate(
            zip(trace.raw_candidate_ids, trace.raw_source_refs, strict=True), start=1
        ):
            key = (evidence_id, trace.requirement_id, str(trace.channel), trace.probe_id)
            if key in seen:
                continue
            seen.add(key)
            values.append(
                _occurrence(
                    request_identity=request_identity,
                    requirement_id=trace.requirement_id,
                    channel=str(trace.channel),
                    query=query,
                    evidence_id=evidence_id,
                    source_ref=source_ref,
                    rank=rank,
                    score=None,
                    projection_kind="EVIDENCE_PROBE",
                    discriminator=trace.probe_id,
                    generated_feature_ids=[
                        "FUSION_SURVIVOR" if evidence_id in surviving else "FUSION_DROPPED"
                    ],
                )
            )
    accuracy_targets, accuracy_channel = _accuracy_targets(progressive_l1)
    for call in repository_calls:
        if call.method not in {
            "search_evidence",
            "search_evidence_dense",
            "scan_evidence_range",
            "search_evidence_event_range",
        }:
            continue
        channel = _repository_call_channel(call, acquisition_plan, accuracy_channel)
        requirements = _call_requirements(call, acquisition_plan, accuracy_targets)
        for rank, item in enumerate(call.output_items, start=1):
            evidence_id = item.get("evidence_id")
            source_ref = item.get("source_ref")
            if not isinstance(evidence_id, str) or not isinstance(source_ref, str):
                continue
            for requirement_id in requirements:
                key = (evidence_id, requirement_id, channel, f"call:{call.ordinal}")
                equivalent = any(
                    existing.evidence_record_identity is not None
                    and existing.evidence_record_identity.evidence_id == evidence_id
                    and existing.requirement_id == requirement_id
                    and existing.channel == channel
                    for existing in values
                )
                if key in seen or equivalent:
                    continue
                seen.add(key)
                values.append(
                    _occurrence(
                        request_identity=request_identity,
                        requirement_id=requirement_id,
                        channel=channel,
                        query=call.query_summary or call.method,
                        evidence_id=evidence_id,
                        source_ref=source_ref,
                        rank=rank,
                        score=_score(item),
                        projection_kind=call.method.upper(),
                        discriminator=f"call:{call.ordinal}",
                        generated_feature_ids=["OFFICIAL_REPOSITORY_RETURN"],
                        content_hash=str(
                            item.get("content_hash") or _hash_text(item.get("content"))
                        ),
                        observed_at=_optional_string(item.get("observed_at")),
                    )
                )
    values.sort(
        key=lambda item: (
            item.channel,
            item.requirement_id or "",
            item.raw_rank,
            item.occurrence_id,
        )
    )
    return values


def _occurrence(
    *,
    request_identity: str,
    requirement_id: str | None,
    channel: str,
    query: str,
    evidence_id: str,
    source_ref: str,
    rank: int,
    score: float | None,
    projection_kind: str,
    discriminator: str,
    generated_feature_ids: list[str],
    content_hash: str | None = None,
    observed_at: str | None = None,
) -> RetrievalOccurrenceV01:
    query_digest = canonical_sha256(query)
    occurrence_id = canonical_sha256(
        [request_identity, requirement_id, channel, discriminator, rank, evidence_id]
    )
    content_digest = (
        content_hash
        if content_hash is not None and _is_digest(content_hash)
        else canonical_sha256(source_ref)
    )
    tenant_scope_digest = canonical_sha256(request_identity)
    return RetrievalOccurrenceV01(
        occurrence_id=occurrence_id,
        request_identity=request_identity,
        requirement_id=requirement_id,
        channel=channel,
        channel_query_digest=query_digest,
        channel_query_semantic_summary=" ".join(query.split())[:256],
        normalized_terms=sorted(set(query.casefold().split())),
        generated_feature_ids=generated_feature_ids,
        retrieval_document_identity=RetrievalDocumentIdentityV01(
            projection_kind=projection_kind,
            projection_version="official-runtime-current",
            index_identity=f"official:{channel}",
            document_id=evidence_id,
            source_locator=source_ref,
            content_digest=content_digest,
        ),
        evidence_record_identity=EvidenceRecordIdentityV01(
            tenant_scope_digest=tenant_scope_digest,
            evidence_id=evidence_id,
            source_identity="EVIDENCE_RECORD",
            source_ref=source_ref,
            content_hash=content_digest,
            observed_at=observed_at,
            retention_snapshot_digest=canonical_sha256([request_identity, "retention"]),
            permission_snapshot_digest=canonical_sha256([request_identity, "permission"]),
        ),
        raw_rank=rank,
        raw_score=score,
        score_direction="HIGHER_IS_BETTER" if score is not None else "NOT_EXPOSED",
        latency_ms=None,
    )


def _candidates_and_dedup(
    occurrences: Sequence[RetrievalOccurrenceV01],
    *,
    execution: Any | None,
    request: RetrievalRequest,
) -> tuple[list[EvidenceCandidateV01], list[DedupDecisionV01]]:
    grouped: dict[str, list[RetrievalOccurrenceV01]] = defaultdict(list)
    for item in occurrences:
        identity = item.evidence_record_identity
        if identity is not None:
            grouped[identity.evidence_id].append(item)
    spans_by_evidence: dict[str, list[EvidenceSpanIdentityV01]] = defaultdict(list)
    for span in getattr(execution, "spans", ()):
        spans_by_evidence[span.source_evidence_id].append(
            EvidenceSpanIdentityV01(
                evidence_id=span.source_evidence_id,
                span_start=span.start,
                span_end=span.end,
                span_digest=canonical_sha256(span.text),
                source_role=span.speaker,
                occurrence_time=(
                    span.source_timestamp.isoformat() if span.source_timestamp else None
                ),
            )
        )
    values: list[EvidenceCandidateV01] = []
    decisions: list[DedupDecisionV01] = []
    for evidence_id, lineage in sorted(grouped.items()):
        identity = lineage[0].evidence_record_identity
        assert identity is not None
        source_ref = identity.source_ref
        turn = evidence_source_turn_identity(source_ref)
        values.append(
            EvidenceCandidateV01(
                candidate_identity=evidence_id,
                evidence_record_identity=identity,
                hydrated_span_identities=sorted(
                    spans_by_evidence[evidence_id],
                    key=lambda item: (item.span_start, item.span_end),
                ),
                session_id=turn[0] if turn is not None else None,
                turn_id=str(turn[1]) if turn is not None else None,
                region_id=source_ref,
                discovery_lineage=[
                    {
                        "occurrence_id": item.occurrence_id,
                        "channel": item.channel,
                        "raw_rank": item.raw_rank,
                        "raw_score": item.raw_score,
                    }
                    for item in lineage
                ],
            )
        )
        if len(lineage) > 1:
            decisions.append(
                DedupDecisionV01(
                    dedup_policy_version="official-evidence-id-first-v0.1",
                    dedup_key_version="evidence-id-v0.1",
                    dedup_key_digest=canonical_sha256(evidence_id),
                    winner_candidate_identity=evidence_id,
                    loser_candidate_identities=[item.occurrence_id for item in lineage[1:]],
                    winner_reason="FIRST_STABLE_EVIDENCE_ID_REPRESENTATIVE",
                    preserved_channel_lineage=sorted({item.channel for item in lineage}),
                )
            )
    return values, decisions


def _lifecycles(
    occurrences: Sequence[RetrievalOccurrenceV01],
    *,
    execution: Any | None,
    decision: DecisionSnapshot,
    query_ir: MemoryQueryIRV02,
) -> list[CandidateLifecycleTraceV01]:
    result_ids = {str(item.get("evidence_id")) for item in getattr(execution, "results", ())}
    trace_survivors: set[tuple[str, str | None, str]] = set()
    for trace in getattr(execution, "probe_candidate_traces", ()):
        trace_survivors.update(
            (value, trace.requirement_id, str(trace.channel))
            for value in trace.fusion_surviving_candidate_ids
        )
    interpretation_by_id = {
        item.interpretation_id: item for item in getattr(execution, "interpretations", ())
    }
    span_by_id = {item.span_id: item for item in getattr(execution, "spans", ())}
    binding_by_evidence_requirement: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for binding in getattr(execution, "bindings", ()):
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        span = span_by_id.get(interpretation.span_id) if interpretation is not None else None
        if span is not None:
            binding_by_evidence_requirement[
                (span.source_evidence_id, binding.requirement_id)
            ].append(binding)
    satisfied = set()
    state = getattr(execution, "requirement_state", None)
    if state is not None:
        satisfied = set(state.satisfied_requirement_ids)
    lifecycles: list[CandidateLifecycleTraceV01] = []
    seen_evidence: set[str] = set()
    for occurrence in occurrences:
        identity = occurrence.evidence_record_identity
        if identity is None:
            continue
        evidence_id = identity.evidence_id
        requirement = occurrence.requirement_id
        is_plan_trace = any(
            feature in {"FUSION_SURVIVOR", "FUSION_DROPPED"}
            for feature in occurrence.generated_feature_ids
        )
        fusion_survived = (
            (evidence_id, requirement, occurrence.channel) in trace_survivors
            if is_plan_trace
            else evidence_id in result_ids
        )
        steps: list[CandidateLifecycleStepV01] = []
        steps.append(_step(12, "S12", "KEPT", "OFFICIAL_REPOSITORY_RETURN", occurrence.raw_rank))
        steps.append(_step(14, "S14", "KEPT", "OFFICIAL_CHANNEL_ORDER", occurrence.raw_rank))
        steps.append(
            _step(15, "S15", "KEPT", "WITHIN_OFFICIAL_PRODUCT_CUTOFF", occurrence.raw_rank)
        )
        if not fusion_survived:
            steps.append(
                _step(22, "S22", "DROPPED", "FIXED_PRIORITY_SUPPRESSION", occurrence.raw_rank)
            )
            steps.extend(_not_applicable_after(23))
        else:
            steps.append(_step(20, "S20", "KEPT", "CROSS_CHANNEL_UNION_MEMBER"))
            dedup_disposition = "REDISCOVERED" if evidence_id in seen_evidence else "KEPT"
            steps.append(_step(21, "S21", dedup_disposition, "EVIDENCE_ID_LINEAGE_PRESERVED"))
            seen_evidence.add(evidence_id)
            if evidence_id not in result_ids:
                steps.append(_step(23, "S23", "DROPPED", "GLOBAL_CUTOFF_DROP"))
                steps.extend(_not_applicable_after(30))
            else:
                steps.append(_step(23, "S23", "KEPT", "GLOBAL_RESULT_MEMBER"))
                span_present = any(
                    span.source_evidence_id == evidence_id
                    for span in getattr(execution, "spans", ())
                )
                steps.append(_step(30, "S30", "KEPT", "BODY_HYDRATED"))
                steps.append(_step(31, "S31", "KEPT", "GOVERNANCE_GATE_ACCEPTED"))
                steps.append(_step(32, "S32", "KEPT", "EVIDENCE_SET_MEMBER"))
                steps.append(
                    _step(
                        40,
                        "S40",
                        "KEPT" if span_present else "DROPPED",
                        "SPAN_PROJECTED" if span_present else "SPAN_NOT_GROUNDED",
                    )
                )
                interpreted = any(
                    span_by_id.get(item.span_id) is not None
                    and span_by_id[item.span_id].source_evidence_id == evidence_id
                    for item in interpretation_by_id.values()
                )
                steps.append(
                    _step(
                        41,
                        "S41",
                        "KEPT" if interpreted else "DROPPED",
                        (
                            "INTERPRETATION_PRODUCED"
                            if interpreted
                            else "INTERPRETATION_NOT_PRODUCED"
                        ),
                    )
                )
                bindings = binding_by_evidence_requirement.get((evidence_id, requirement or ""), [])
                matched = any(item.status == "MATCH" for item in bindings)
                if requirement is None:
                    steps.append(_step(42, "S42", "NOT_APPLICABLE", "GLOBAL_PROBE_NO_SLOT"))
                elif matched:
                    steps.append(_step(42, "S42", "KEPT", "BINDING_MATCH"))
                elif bindings:
                    steps.append(_step(42, "S42", "REJECTED", _binding_reason(bindings[0])))
                else:
                    steps.append(_step(42, "S42", "REJECTED", "INTERPRETATION_NOT_PRODUCED"))
                steps.append(
                    _step(
                        43,
                        "S43",
                        "KEPT" if requirement in satisfied else "REJECTED",
                        (
                            "REQUIREMENT_SATISFIED"
                            if requirement in satisfied
                            else "REQUIREMENT_UNSATISFIED"
                        ),
                    )
                )
                steps.append(
                    _step(
                        44,
                        "S44",
                        "KEPT" if requirement in satisfied else "REJECTED",
                        (
                            "SUFFICIENCY_ACCEPTED"
                            if requirement in satisfied
                            else "PROOF_ACTION_NOT_SELECTED"
                        ),
                    )
                )
                steps.append(
                    _step(
                        45,
                        "S45",
                        "KEPT" if requirement in satisfied else "REJECTED",
                        (
                            "OPERATOR_READY"
                            if requirement in satisfied
                            else "PROOF_ACTION_NOT_SELECTED"
                        ),
                    )
                )
        lifecycles.append(
            CandidateLifecycleTraceV01(
                occurrence_id=occurrence.occurrence_id,
                candidate_identity=evidence_id,
                requirement_candidates=[requirement] if requirement else [],
                discovery={
                    "channel": occurrence.channel,
                    "query_digest": occurrence.channel_query_digest,
                    "normalized_terms": occurrence.normalized_terms,
                    "generated_feature_ids": occurrence.generated_feature_ids,
                    "channel_rank": occurrence.raw_rank,
                    "raw_score": occurrence.raw_score,
                },
                lifecycle=steps,
            )
        )
    return lifecycles


def _step(
    sequence: int,
    stage_id: str,
    disposition: str,
    reason: str,
    rank: int | None = None,
) -> CandidateLifecycleStepV01:
    material = [sequence, stage_id, disposition, reason, rank]
    return CandidateLifecycleStepV01(
        sequence_index=sequence,
        stage_id=stage_id,
        disposition=LifecycleDisposition(disposition),
        reason_code=reason,
        rank_before=rank,
        rank_after=rank if disposition in {"KEPT", "REDISCOVERED"} else None,
        cutoff=None,
        validator_identity="milai-runtime-retrieval-audit-v0.1",
        decision_digest=canonical_sha256(material),
    )


def _not_applicable_after(start: int) -> list[CandidateLifecycleStepV01]:
    stages = [
        (23, "S23"),
        (30, "S30"),
        (31, "S31"),
        (32, "S32"),
        (40, "S40"),
        (41, "S41"),
        (42, "S42"),
        (43, "S43"),
        (44, "S44"),
        (45, "S45"),
    ]
    return [
        _step(sequence, stage, "NOT_APPLICABLE", "PRIOR_IRRECOVERABLE_DROP")
        for sequence, stage in stages
        if sequence >= start
    ]


def _channel_decisions(progressive_l1: Mapping[str, Any]) -> list[dict[str, Any]]:
    capability = progressive_l1.get("acquisition_capability")
    channels = capability.get("channels") if isinstance(capability, Mapping) else {}
    dispositions = progressive_l1.get("acquisition_probe_dispositions")
    disposition_rows = dispositions if isinstance(dispositions, list) else []
    values = []
    for channel in (
        "FTS_RAW",
        "FTS_ENRICHED",
        "EVIDENCE_DENSE",
        "SOURCE_OBSERVED_RANGE_SCAN",
        "TEMPORAL_EVENT",
        "CANONICAL_STATE",
    ):
        state = channels.get(channel) if isinstance(channels, Mapping) else None
        state_map = state if isinstance(state, Mapping) else {}
        invoked = [row for row in disposition_rows if row.get("channel") == channel]
        values.append(
            {
                "channel": channel,
                "capability_status": state_map.get("status", "NOT_APPLICABLE"),
                "policy_eligibility": state_map.get("reason", "NOT_APPLICABLE"),
                "invocation_disposition": (
                    "INVOKED"
                    if any(row.get("status") == "EXECUTED" for row in invoked)
                    else "NOT_INVOKED_BY_POLICY"
                ),
                "reason_code": (
                    "EXECUTED"
                    if any(row.get("status") == "EXECUTED" for row in invoked)
                    else str(state_map.get("reason", "NOT_APPLICABLE"))
                ),
            }
        )
    return values


def _product_proof_obligations(
    query_ir: MemoryQueryIRV02, execution: Any | None
) -> list[dict[str, Any]]:
    exhaustive = query_ir.completeness == "ALL_MATCHES_IN_RANGE"
    kinds = (
        [
            "BOUNDED_RANGE_SCAN",
            "SOURCE_PARTITION_CLOSURE",
            "EVENT_TIME_RESOLUTION",
            "DEDUP_COMPLETENESS",
            "PROJECTION_CLOSURE",
            "RAW_FALLBACK_CLOSURE",
            "ACCESS_SNAPSHOT",
        ]
        if exhaustive
        else ["ACCESS_SNAPSHOT", "EVENT_TIME_RESOLUTION"]
        if any(item.interpretation_kind == "EVENT" for item in query_ir.requirements)
        else ["ACCESS_SNAPSHOT"]
    )
    proof = getattr(execution, "bounded_range_scan_proof", None)
    result = []
    for requirement in query_ir.requirements:
        for kind in kinds:
            status = "EMITTED"
            if kind in {"BOUNDED_RANGE_SCAN", "SOURCE_PARTITION_CLOSURE"} and proof is None:
                status = "ACTION_NOT_SELECTED"
            elif kind == "BOUNDED_RANGE_SCAN" and proof is not None:
                status = str(proof.status)
            result.append(
                {
                    "requirement_id": requirement.slot_id,
                    "obligation_id": f"{requirement.slot_id}:{kind}",
                    "kind": kind,
                    "status": status,
                    "proof_artifact_digest": (
                        canonical_sha256(proof.model_dump(mode="json"))
                        if proof is not None
                        else None
                    ),
                    "proof_artifact": (
                        proof.model_dump(mode="json") if proof is not None else None
                    ),
                }
            )
    return result


def _accuracy_targets(progressive_l1: Mapping[str, Any]) -> tuple[list[str], str | None]:
    recovery = progressive_l1.get("deterministic_recovery")
    recovery_map = recovery if isinstance(recovery, Mapping) else {}
    decision = recovery_map.get("accuracy_decision")
    decision_map = decision if isinstance(decision, Mapping) else {}
    bundle = decision_map.get("bundle")
    if bundle is not None and hasattr(bundle, "model_dump"):
        bundle = bundle.model_dump(mode="json")
    bundle_map = bundle if isinstance(bundle, Mapping) else {}
    targets = bundle_map.get("target_requirement_ids")
    return (
        [str(item) for item in targets] if isinstance(targets, list) else [],
        str(bundle_map["channel"]) if isinstance(bundle_map.get("channel"), str) else None,
    )


def _repository_call_channel(
    call: RepositoryCallObservation,
    plan: AcquisitionPlan | None,
    accuracy_channel: str | None,
) -> str:
    if call.method == "search_evidence_dense":
        return "EVIDENCE_DENSE"
    if call.method == "search_evidence_event_range":
        return "TEMPORAL_EVENT"
    if call.method == "scan_evidence_range":
        return "SOURCE_OBSERVED_RANGE_SCAN"
    if plan is not None and call.query_digest is not None:
        for probe in plan.probes:
            if canonical_sha256(probe_query(probe)) == call.query_digest:
                return str(probe.channel)
    return accuracy_channel or "FTS_RAW"


def _call_requirements(
    call: RepositoryCallObservation,
    plan: AcquisitionPlan | None,
    accuracy_targets: Sequence[str],
) -> list[str | None]:
    if plan is not None and call.query_digest is not None:
        values = [
            probe.requirement_slot
            for probe in plan.probes
            if canonical_sha256(probe_query(probe)) == call.query_digest
        ]
        if values:
            return list(dict.fromkeys(values))
    return list(accuracy_targets) if accuracy_targets else [None]


def _binding_reason(binding: Any) -> str:
    compatibility = getattr(binding, "compatibility", None)
    if compatibility is not None:
        payload = compatibility.model_dump(mode="json")
        mapping = {
            "subject": "SUBJECT_MISMATCH",
            "predicate": "PREDICATE_MISMATCH",
            "value_type": "VALUE_TYPE_MISMATCH",
            "source": "SOURCE_ROLE_MISMATCH",
            "temporal": "EVENT_TIME_MISMATCH",
            "unit": "UNIT_MISMATCH",
        }
        for key, mapping_reason in mapping.items():
            if payload.get(key) is False:
                return mapping_reason
    binding_reason = getattr(binding, "reason", None)
    if isinstance(binding_reason, str):
        for value in (
            "SUBJECT_MISMATCH",
            "PREDICATE_MISMATCH",
            "VALUE_TYPE_MISMATCH",
            "SOURCE_ROLE_MISMATCH",
            "EVENT_TIME_MISMATCH",
            "UNIT_MISMATCH",
        ):
            if value in binding_reason:
                return value
    return "PREDICATE_MISMATCH"


def _call_material(method: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    safe_args = []
    for index, value in enumerate(args):
        if index == 0 and hasattr(value, "tenant_id") and hasattr(value, "actor_id"):
            safe_args.append(
                {
                    "tenant_digest": canonical_sha256(str(value.tenant_id)),
                    "actor_digest": canonical_sha256(str(value.actor_id)),
                }
            )
        else:
            safe_args.append(_safe_value(value))
    return {"method": method, "args": safe_args, "kwargs": _safe_value(dict(kwargs))}


def _repository_call_semantics(method: str, value: Any) -> Any:
    """Normalize call material without hiding timeout policy or its disposition.

    The exact remaining millisecond count is a wall-clock observation and will
    naturally differ between matched executions.  Whether a repository call is
    unbounded, bounded, or already exhausted is behaviorally meaningful and is
    retained.  Other ``*_ms`` configuration values are deliberately preserved.
    """

    normalized = _normalize_repository_call_value(method, value)
    if method == "gate_and_hydrate" and isinstance(normalized, Mapping):
        args = normalized.get("args")
        if isinstance(args, list) and len(args) > 9:
            args[9] = "WALL_CLOCK_BOUNDARY_PRESENT"
    return normalized


def _input_component_digests(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            for nested_key, nested in item.items():
                result[f"{key}.{nested_key}"] = semantic_sha256(nested)
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                if isinstance(nested, Mapping):
                    for nested_key, component in nested.items():
                        result[f"{key}.{index}.{nested_key}"] = semantic_sha256(component)
                else:
                    result[f"{key}.{index}"] = semantic_sha256(nested)
        else:
            result[str(key)] = semantic_sha256(item)
    return dict(sorted(result.items()))


def _normalize_repository_call_value(method: str, value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key == "statement_timeout_ms":
                if item is None:
                    normalized[key] = "UNBOUNDED"
                elif isinstance(item, (int, float)) and item <= 0:
                    normalized[key] = "EXHAUSTED"
                else:
                    normalized[key] = "BOUNDED"
                continue
            if key == "system_as_of":
                normalized[key] = "WALL_CLOCK_BOUNDARY_PRESENT"
                continue
            if method == "record_trace" and (
                key
                in {
                    "latency_ms",
                    "created_at",
                    "timestamp",
                    "trace_id",
                    "request_id",
                    "duration_ms",
                    "durations_ms",
                    "elapsed_ms",
                    "total_ms",
                    "causal_waited_ms",
                    "waited_ms",
                }
                or key.endswith("_latency_ms")
            ):
                continue
            normalized[key] = _normalize_repository_call_value(method, item)
        return normalized
    if isinstance(value, list):
        return [_normalize_repository_call_value(method, item) for item in value]
    return value


def _behavior_evidence(
    *,
    request: RetrievalRequest,
    query_plan: QueryPlan,
    acquisition_execution: Any | None,
    results: Sequence[Mapping[str, Any]],
    decision_snapshot: DecisionSnapshot,
    progressive_l1: Mapping[str, Any],
    stage_sequence: tuple[str, ...],
) -> dict[str, Any]:
    """Project field-addressable, behavior-only evidence for OFF/ON checks."""

    dispositions = getattr(acquisition_execution, "probe_dispositions", ())
    probe_traces = getattr(acquisition_execution, "probe_candidate_traces", ())
    candidates = getattr(acquisition_execution, "candidates", ())
    if dispositions:
        channel_material: Any = [
            _channel_disposition_semantics(item) for item in dispositions
        ]
    else:
        channel_material = {
            "stage_sequence": list(stage_sequence),
            "stages_attempted": progressive_l1.get("stages_attempted", []),
            "stop_stage": progressive_l1.get("stop_stage"),
            "fallback_reason": progressive_l1.get("fallback_reason"),
        }
    candidate_material = [
        {
            "candidate_id": item.candidate_id,
            "source_evidence_id": item.source_evidence_id,
            "source_turn_ref": item.source_turn_ref,
            "fusion_rank": item.fusion_rank,
        }
        for item in candidates
    ]
    ordered_results = [_safe_result_identity(item) for item in results]
    dedup_material = {
        "probe_survival": [
            {
                "probe_id": item.probe_id,
                "requirement_id": item.requirement_id,
                "channel": str(item.channel),
                "raw_candidate_ids": list(item.raw_candidate_ids),
                "fusion_surviving_candidate_ids": list(
                    item.fusion_surviving_candidate_ids
                ),
            }
            for item in probe_traces
        ],
        "fusion_winners": [
            {
                "candidate_id": item.candidate_id,
                "source_evidence_id": item.source_evidence_id,
                "fusion_rank": item.fusion_rank,
            }
            for item in candidates
        ],
    }
    requirement_state = getattr(acquisition_execution, "requirement_state", None)
    if requirement_state is not None:
        requirement_state_material: Any = {
            "requirements": [
                item.model_dump(mode="json") for item in requirement_state.requirements
            ],
            "candidate_snapshot_digest": requirement_state.candidate_snapshot_digest,
            "binding_digest": requirement_state.binding_digest,
            "sufficiency_decision_digest": (
                requirement_state.sufficiency_decision_digest
            ),
            "sufficiency_policy_version": requirement_state.sufficiency_policy_version,
            "state_epoch": requirement_state.state_epoch,
            "lifetime": requirement_state.lifetime,
            "canonical": requirement_state.canonical,
            "canonical_mutation": requirement_state.canonical_mutation,
        }
    else:
        requirement_state_material = {
            "required_requirement_ids": list(
                decision_snapshot.required_requirement_ids
            ),
            "unresolved_requirement_ids": list(
                decision_snapshot.unresolved_requirement_ids
            ),
        }
    return {
        "request_semantic_digest": {
            "request": _request_semantics(request),
            "query_plan": _query_plan_behavior_semantics(query_plan),
        },
        "channel_invocation_digest": channel_material,
        "candidate_set_and_order_digest": candidate_material or ordered_results,
        "dedup_winner_digest": dedup_material,
        "gate_digest": decision_snapshot.gate_digest,
        "evidence_set_digest": list(decision_snapshot.accepted_evidence_ids),
        "ordered_result_digest": ordered_results,
        "interpretation_binding_digest": decision_snapshot.binding_digest,
        "requirement_state_digest": requirement_state_material,
        "sufficiency_operator_digest": {
            "sufficiency": decision_snapshot.sufficiency_digest,
            "operator": decision_snapshot.operator_result_digest,
        },
    }


def _channel_disposition_semantics(item: Any) -> dict[str, Any]:
    """Describe channel invocation without run-local probe identity or latency."""

    return {
        "requirement_id": item.requirement_id,
        "channel": str(item.channel),
        "status": item.status,
        "reason_code": item.reason_code,
        "raw_candidate_count": item.raw_candidate_count,
        "selected_candidate_count": item.selected_candidate_count,
        "excluded_seen_candidate_count": item.excluded_seen_candidate_count,
        "repeated_region_count": item.repeated_region_count,
        "new_region_count": item.new_region_count,
    }


def _safe_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _safe_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_value(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_output_items(result: Any) -> list[dict[str, Any]]:
    raw: Any = result
    if isinstance(result, Mapping) and isinstance(result.get("items"), list):
        raw = result["items"]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    values = []
    for item in raw:
        if isinstance(item, Mapping):
            values.append(
                {
                    key: item.get(key)
                    for key in (
                        "evidence_id",
                        "source_ref",
                        "content_hash",
                        "content",
                        "observed_at",
                        "relevance_score",
                        "score",
                        "subject_id",
                    )
                    if item.get(key) is not None
                }
            )
        elif hasattr(item, "claim_version_id"):
            values.append(
                {
                    "document_id": str(item.claim_version_id),
                    "score": float(item.score),
                    "source": str(item.source),
                }
            )
    return values


def _safe_result_identity(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in ("evidence_id", "source_ref", "claim_version_id", "score")
        if item.get(key) is not None
    }


def _request_semantics(request: RetrievalRequest) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    payload.pop("tenant_id", None)
    payload.pop("system_as_of", None)
    return payload


def _query_plan_behavior_semantics(query_plan: QueryPlan) -> dict[str, Any]:
    payload = query_plan.model_dump(mode="json")
    constraint = payload.get("time_constraint")
    if isinstance(constraint, dict):
        constraint.pop("system_as_of", None)
    return payload


def _query_digest(method: str, args: Sequence[Any]) -> str | None:
    summary = _query_summary(method, args)
    return canonical_sha256(summary) if summary is not None else None


def _query_summary(method: str, args: Sequence[Any]) -> str | None:
    if method == "search_evidence" and len(args) > 1 and isinstance(args[1], str):
        return args[1]
    if method == "search_evidence_dense":
        return "DENSE_VECTOR_DIGEST:" + canonical_sha256(args[1] if len(args) > 1 else [])
    if method in {"scan_evidence_range", "search_evidence_event_range"}:
        return method.upper()
    return None


def _call_limit(method: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> int | None:
    positions = {
        "search_evidence": 4,
        "search_evidence_dense": 4,
        "scan_evidence_range": 4,
        "search_evidence_event_range": 5,
    }
    index = positions.get(method)
    if index is not None and len(args) > index and isinstance(args[index], int):
        return int(args[index])
    for key in ("limit", "max_items"):
        if isinstance(kwargs.get(key), int):
            return int(kwargs[key])
    return None


def _score(item: Mapping[str, Any]) -> float | None:
    for key in ("relevance_score", "score"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _hash_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _is_digest(value: str | None) -> bool:
    return (
        value is not None and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
    )


__all__ = [
    "AuditRecordingRepository",
    "ProductRetrievalAuditObserver",
    "RepositoryCallObservation",
    "RetrievalAuditObserver",
    "RetrievalAuditRecordingObserver",
]
