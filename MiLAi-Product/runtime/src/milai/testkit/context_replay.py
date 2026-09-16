"""One-snapshot Context replay for Product engineering diagnosis.

This module is a published PRODUCT_TESTKIT surface, not a Runtime API.  Raw
Evidence remains process-local.  Reports contain stable identities and digests
only, and every replay is compiled without repository, embedding, Provider, or
Canonical mutation calls.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from time import perf_counter
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from milai.adapters import EmbeddingProvider
from milai.application.acquisition import (
    QUERY_PRESERVING_UNION_CANDIDATE_CAP,
    compile_acquisition_plan,
    fuse_acquisition_probe_results,
)
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    resolve_acquisition_capabilities,
)
from milai.application.evidence_acquisition import (
    AcquisitionProbeDisposition,
    EvidenceAcquisitionExecutor,
    _deduplicate,
    _exclude_seen_candidates,
    _probe_candidate_traces,
    _query_preserving_locality_order,
    _same_session_expansion_planned,
    _selected_plan,
)
from milai.application.memory_access import (
    ACQUISITION_DECISION_CONTEXT_CEILING,
    MemoryAccessPlanner,
)
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_resolve import (
    MemoryQueryInterpreter,
    _access_outcome,
    _retrieval_request,
)
from milai.application.retrieval import (
    RetrievalService,
    _decision_snapshot,
    _operator_support_refs,
    _projection_state_payload,
)
from milai.config import RuntimeSettings
from milai.domain.acquisition import AcquisitionPlan, AcquisitionProbe
from milai.domain.acquisition_capability import AcquisitionCapabilitySet
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.reader_evidence_plan import ReaderEvidencePolicy, canonical_digest
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

ContextReplayArm = Literal["C", "X", "Y"]
CONTEXT_REPLAY_ARMS: tuple[ContextReplayArm, ...] = ("C", "X", "Y")


class FrozenReplayInvariantError(RuntimeError):
    """A replay could not prove that its acquisition snapshot stayed frozen."""


class ContextTestkitRequest(BaseModel):
    """Versioned stdin contract for ``milai-context-testkit``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["milai-context-testkit-request-v0.1"]
    memory_request: MemoryResolveRequest


@dataclass(frozen=True, slots=True)
class FrozenProbeBatch:
    probe: AcquisitionProbe
    results: tuple[dict[str, Any], ...]
    disposition: AcquisitionProbeDisposition


@dataclass(frozen=True, slots=True)
class FrozenAcquisitionSnapshot:
    """Opaque process-local evidence snapshot used by all replay arms."""

    schema_version: Literal["frozen-acquisition-snapshot-v0.1"]
    memory_request: MemoryResolveRequest
    retrieval_request: RetrievalRequest
    query_plan: QueryPlan
    acquisition_plan: AcquisitionPlan
    capability_set: AcquisitionCapabilitySet
    projection_state: ProjectionState
    probe_batches: tuple[FrozenProbeBatch, ...]
    skip_dispositions: tuple[AcquisitionProbeDisposition, ...]
    locality_results: tuple[dict[str, Any], ...]
    locality_disposition: AcquisitionProbeDisposition | None
    range_results: tuple[dict[str, Any], ...]
    range_disposition: AcquisitionProbeDisposition | None
    range_scan: dict[str, Any] | None
    capture_counters: dict[str, int]
    snapshot_digest: str


class _CountingEmbedding:
    def __init__(self, delegate: EmbeddingProvider) -> None:
        self._delegate = delegate
        self.dimensions = delegate.dimensions
        self.identity = delegate.identity
        self.embed_calls = 0
        self.embed_many_calls = 0

    def embed(self, text: str) -> list[float]:
        self.embed_calls += 1
        return self._delegate.embed(text)

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        self.embed_many_calls += 1
        return self._delegate.embed_many(texts, batch_size)

    def counters(self) -> dict[str, int]:
        return {
            "embedding_calls": self.embed_calls,
            "embedding_batch_calls": self.embed_many_calls,
        }


class _CountingRepository:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.fts_calls = 0
        self.vector_calls = 0
        self.locality_calls = 0
        self.range_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def search_evidence(self, *args: Any, **kwargs: Any) -> Any:
        self.fts_calls += 1
        return cast(Any, self._delegate).search_evidence(*args, **kwargs)

    def search_evidence_dense(self, *args: Any, **kwargs: Any) -> Any:
        self.vector_calls += 1
        return cast(Any, self._delegate).search_evidence_dense(*args, **kwargs)

    def hydrate_evidence_adjacency(self, *args: Any, **kwargs: Any) -> Any:
        self.locality_calls += 1
        return cast(Any, self._delegate).hydrate_evidence_adjacency(*args, **kwargs)

    def scan_evidence_range(self, *args: Any, **kwargs: Any) -> Any:
        self.range_calls += 1
        return cast(Any, self._delegate).scan_evidence_range(*args, **kwargs)

    def counters(self) -> dict[str, int]:
        return {
            "fts_calls": self.fts_calls,
            "vector_calls": self.vector_calls,
            "locality_calls": self.locality_calls,
            "range_calls": self.range_calls,
        }


def capture_frozen_acquisition_snapshot(
    *,
    executor: EvidenceAcquisitionExecutor,
    context: SessionContext,
    memory_request: MemoryResolveRequest,
    retrieval_request: RetrievalRequest,
    query_plan: QueryPlan,
    acquisition_plan: AcquisitionPlan,
    capability_set: AcquisitionCapabilitySet,
    projection_state: ProjectionState,
    capture_counters: Mapping[str, int] | None = None,
) -> FrozenAcquisitionSnapshot:
    """Execute every feasible superset probe exactly once and freeze its rows."""

    if query_plan.memory_query_ir is None:
        raise ValueError("context replay requires an executable MemoryQueryIR")
    selected_probes = executor._selected_probes(
        acquisition_plan,
        None,
        capability_set,
        None,
    )
    selected_ids = {probe.probe_id for probe in selected_probes}
    skip_dispositions = executor._capability_skip_dispositions(
        acquisition_plan,
        capability_set,
        selected_ids,
    )
    batches: list[FrozenProbeBatch] = []
    probe_results: list[tuple[AcquisitionProbe, list[dict[str, Any]]]] = []
    for probe in selected_probes:
        started = perf_counter()
        raw_items, status, reason = executor._execute_probe(
            probe,
            context=context,
            request=retrieval_request,
            acquisition_plan=acquisition_plan,
        )
        items, repeated = _exclude_seen_candidates(raw_items, ())
        disposition = AcquisitionProbeDisposition(
            probe_id=probe.probe_id,
            requirement_id=probe.requirement_slot,
            channel=probe.channel,
            status=status,
            reason_code=reason,
            raw_candidate_count=len(raw_items),
            selected_candidate_count=len(items),
            excluded_seen_candidate_count=repeated,
            repeated_region_count=repeated,
            new_region_count=len(items),
            latency_ms=round((perf_counter() - started) * 1_000, 6),
        )
        copied = tuple(deepcopy(items))
        batches.append(FrozenProbeBatch(probe, copied, disposition))
        probe_results.append((probe, list(deepcopy(copied))))

    selected_plan = _selected_plan(acquisition_plan, selected_probes)
    fused = (
        fuse_acquisition_probe_results(selected_plan, probe_results)
        if selected_probes
        else []
    )
    locality_results: list[dict[str, Any]] = []
    locality_disposition: AcquisitionProbeDisposition | None = None
    if _same_session_expansion_planned(selected_probes):
        locality_results, locality_disposition = (
            executor._execute_planned_local_expansion(
                context=context,
                request=retrieval_request,
                acquisition_plan=acquisition_plan,
                capability_set=capability_set,
                existing_results=fused,
            )
        )
        locality_results, repeated = _exclude_seen_candidates(locality_results, fused)
        locality_disposition = locality_disposition.model_copy(
            update={
                "selected_candidate_count": len(locality_results),
                "excluded_seen_candidate_count": repeated,
                "repeated_region_count": repeated,
                "new_region_count": len(locality_results),
            }
        )

    range_results, range_disposition, range_scan = executor._execute_planned_range(
        context=context,
        request=retrieval_request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
    )
    material = _frozen_snapshot_material(
        memory_request=memory_request,
        retrieval_request=retrieval_request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capability_set,
        projection_state=projection_state,
        batches=batches,
        locality_results=locality_results,
        range_results=range_results,
        range_scan=range_scan,
    )
    return FrozenAcquisitionSnapshot(
        schema_version="frozen-acquisition-snapshot-v0.1",
        memory_request=memory_request.model_copy(deep=True),
        retrieval_request=retrieval_request.model_copy(deep=True),
        query_plan=query_plan.model_copy(deep=True),
        acquisition_plan=acquisition_plan.model_copy(deep=True),
        capability_set=capability_set.model_copy(deep=True),
        projection_state=projection_state,
        probe_batches=tuple(batches),
        skip_dispositions=tuple(skip_dispositions),
        locality_results=tuple(deepcopy(locality_results)),
        locality_disposition=locality_disposition,
        range_results=tuple(deepcopy(range_results)),
        range_disposition=range_disposition,
        range_scan=deepcopy(range_scan),
        capture_counters=dict(capture_counters or {}),
        snapshot_digest=canonical_digest(material),
    )


def replay_frozen_context(
    snapshot: FrozenAcquisitionSnapshot,
    arm: ContextReplayArm,
    *,
    executor: EvidenceAcquisitionExecutor,
) -> dict[str, Any]:
    """Compile one Context arm without making fresh external calls."""

    if canonical_digest(_snapshot_material(snapshot)) != snapshot.snapshot_digest:
        raise FrozenReplayInvariantError("FROZEN_ACQUISITION_SNAPSHOT_DRIFT")
    batches = [
        batch
        for batch in snapshot.probe_batches
        if arm == "Y" or batch.probe.probe_id == "global:fts-raw"
    ]
    if not batches or batches[0].probe.probe_id != "global:fts-raw":
        raise FrozenReplayInvariantError("GLOBAL_FTS_BACKBONE_UNAVAILABLE")
    probes = [batch.probe for batch in batches]
    plan = _selected_plan(snapshot.acquisition_plan, probes)
    probe_results = [
        (batch.probe, list(deepcopy(batch.results))) for batch in batches
    ]
    direct = fuse_acquisition_probe_results(plan, probe_results)
    direct_sessions = {
        session_id
        for item in direct
        if (session_id := _result_session_id(item)) is not None
    }
    locality = [
        deepcopy(item)
        for item in snapshot.locality_results
        if _result_session_id(item) in direct_sessions
    ]
    results = (
        _query_preserving_locality_order(direct, locality)
        if locality
        else _deduplicate(direct)
    )
    results = _deduplicate([*deepcopy(snapshot.range_results), *results])
    selected_probe_ids = {probe.probe_id for probe in probes}
    dispositions = [
        batch.disposition
        for batch in snapshot.probe_batches
        if batch.probe.probe_id in selected_probe_ids
    ]
    if arm == "Y":
        dispositions.extend(snapshot.skip_dispositions)
    if snapshot.locality_disposition is not None:
        dispositions.append(snapshot.locality_disposition)
    if snapshot.range_disposition is not None:
        dispositions.append(snapshot.range_disposition)
    acquisition_execution = executor.compile_existing_results(
        request=snapshot.retrieval_request,
        query_plan=snapshot.query_plan,
        acquisition_plan=plan,
        capability_set=snapshot.capability_set,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
        results=results,
        action_digest=None,
        range_scan=snapshot.range_scan,
        probe_dispositions=dispositions,
        probe_candidate_traces=_probe_candidate_traces(probe_results, direct),
        type_directed_semantics=False,
    )
    supporting_ids, supporting_refs = _operator_support_refs(
        acquisition_execution.derived_result
    )
    decision_results = [
        item
        for item in acquisition_execution.results
        if item.get("evidence_id") in supporting_ids
        or item.get("source_ref") in supporting_refs
    ]
    decision_snapshot = _decision_snapshot(
        plan=snapshot.query_plan,
        projection_state=snapshot.projection_state,
        acquisition_plan=plan,
        acquisition_execution=acquisition_execution,
        acquisition_state=None,
        accepted=[],
        rejected=[],
        # With no live AcquisitionState, passing the entire governed candidate
        # pool would make every row look decision-accepted and therefore
        # untrimmable.  Preserve only explicit operator provenance here; Raw
        # candidates remain in the sealed acquisition snapshot and X/Y may
        # admit them as budgeted informational context.
        results=decision_results,
        final_decision=acquisition_execution.sufficiency_decision,
        derived_result=acquisition_execution.derived_result,
    )
    complete = acquisition_execution.sufficiency_decision.complete
    body = {
        "results": deepcopy(acquisition_execution.results),
        "query_plan": snapshot.query_plan.model_dump(mode="json"),
        "open_issue_ids": [],
        "degraded_components": [],
        "abstained": not complete,
        "abstention_reason": (
            None if complete else acquisition_execution.sufficiency_reason
        ),
        "fallback_used": False,
        "fallback_reason": None,
        "derived_result": deepcopy(acquisition_execution.derived_result),
        "consistency": snapshot.retrieval_request.consistency,
        "snapshot": _projection_state_payload(snapshot.projection_state),
        "progressive_l1": {
            "terminal_sufficiency_decision": (
                acquisition_execution.sufficiency_decision.model_dump(mode="json")
            ),
            "acquisition_probe_dispositions": [
                item.model_dump(mode="json") for item in dispositions
            ],
        },
    }
    interpretation = MemoryQueryInterpreter().interpret(
        snapshot.memory_request.query,
        invocation_mode=snapshot.memory_request.invocation_mode,
        exact_target=False,
    )
    outcome = _access_outcome(
        body,
        interpretation,
        decision_snapshot=decision_snapshot,
        reader_evidence_policy=(
            ReaderEvidencePolicy.DECISION_ACCEPTED_ONLY
            if arm == "C"
            else ReaderEvidencePolicy.GOVERNANCE_ADMITTED_SOFT_RANKED
        ),
        informational_soft_admission_v0_2_enabled=arm in {"X", "Y"},
    )
    compilation = MemoryContextCompiler(
        budget_stable_enabled=True,
        query_preserving_union_enabled=True,
        evidence_set_selection_enabled=False,
    ).compile(
        snapshot.memory_request,
        outcome,
        decision_snapshot=decision_snapshot,
    )
    trace = compilation.memory_context.compile_trace
    activation = trace["conditional_activation_thresholds"]
    if not isinstance(activation, Mapping):
        raise FrozenReplayInvariantError("CONTEXT_ACTIVATION_TRACE_ABSENT")
    selected_unit_ids = cast(Sequence[object], trace["selected_unit_ids"])
    omitted_unit_reasons = cast(Mapping[object, str], trace["omitted_unit_reasons"])
    return {
        "arm": arm,
        "snapshot_digest": snapshot.snapshot_digest,
        "decision_snapshot_digest": decision_snapshot.snapshot_digest,
        "before_boundary": trace["acquired_candidate_trace"],
        "bound_evidence": trace["bound_evidence_trace"],
        "boundary": trace["reader_boundary_trace"],
        "reader_visible": trace["reader_visible_trace"],
        "reader_visible_evidence_ids": list(
            compilation.memory_context.selected_evidence_ids
        ),
        "reader_visible_source_turn_refs": list(
            compilation.memory_context.selected_source_turn_refs
        ),
        "context_digest": compilation.memory_context.reader_context_digest,
        "context_tokens": compilation.memory_context.estimated_tokens,
        "available_windows": compilation.memory_context.available_windows,
        "selected_windows": compilation.memory_context.selected_windows,
        "packing": {
            "reader_readiness": trace["reader_readiness"],
            "budget_envelope": trace["budget_envelope"],
            "protected_unit_count": trace["protected_unit_count"],
            "protected_closure_tokens": trace["protected_closure_tokens"],
            "conditional_unit_count": trace["conditional_unit_count"],
            "conditional_activation_min": min(activation.values(), default=None),
            "conditional_activation_max": max(activation.values(), default=None),
            "selected_unit_count": len(selected_unit_ids),
            "omitted_reason_counts": dict(
                sorted(
                    Counter(omitted_unit_reasons.values()).items()
                )
            ),
        },
        "probe_dispositions": [
            item.model_dump(mode="json") for item in dispositions
        ],
        "fresh_repository_calls": 0,
        "fresh_embedding_calls": 0,
        "fresh_vector_calls": 0,
        "context_mutation_performed": False,
        "canonical_mutation": False,
    }


def run_live_context_replay(
    request: ContextTestkitRequest,
    *,
    settings: RuntimeSettings | None = None,
) -> dict[str, Any]:
    """Build one live governed snapshot and replay C/X/Y in one process."""

    from milai.api import create_app
    from milai.config import load_settings

    runtime_settings = settings or load_settings()
    if request.memory_request.required_authority != "INFORMATIONAL":
        raise ValueError("context testkit supports informational L1 reads only")
    if request.memory_request.state_keys or request.memory_request.claim_ids:
        raise ValueError("context testkit does not replay Canonical exact reads")
    if not getattr(runtime_settings, "retrieval_additive_union_v0_2_enabled", False):
        raise ValueError("Product-08 additive union must be explicitly enabled")
    if not getattr(
        runtime_settings,
        "reader_informational_soft_admission_v0_2_enabled",
        False,
    ):
        raise ValueError("Product-08 soft admission must be explicitly enabled")
    if not getattr(runtime_settings, "retrieval_evidence_dense_enabled", False):
        raise ValueError("Product-08 Y arm requires explicit Dense enablement")

    app = create_app(cast(Any, runtime_settings))
    runtime_database = app.extensions["milai.database"]
    steward_database = app.extensions["milai.steward_database"]
    try:
        retrieval = cast(
            RetrievalService,
            app.extensions["milai.retrieval_service"],
        )
        repository = _CountingRepository(retrieval._repository)
        embedding = _CountingEmbedding(retrieval._embedding)
        executor = EvidenceAcquisitionExecutor(repository, embedding)
        context = SessionContext(
            runtime_settings.tenant_id,
            runtime_settings.local_actor_id,
        )
        interpretation = MemoryQueryInterpreter().interpret(
            request.memory_request.query,
            invocation_mode=request.memory_request.invocation_mode,
            exact_target=False,
        )
        access_plan = MemoryAccessPlanner().plan(request.memory_request, interpretation)
        retrieval_request = _retrieval_request(request.memory_request, interpretation)
        query_plan = retrieval._planner.plan(
            retrieval_request,
            context_budget=ACQUISITION_DECISION_CONTEXT_CEILING,
            access_intent=access_plan.access_intent,
            candidate_cap=access_plan.candidate_cap,
            deadline_ms=access_plan.deadline_ms,
            reranker_candidate_cap=access_plan.reranker_candidate_cap,
            hard_partitions=access_plan.hard_partitions,
            vector_policy=access_plan.vector_policy,
            reranker_policy=access_plan.reranker_policy,
        )
        projection_state = repository.projection_state(context)
        acquisition_plan = compile_acquisition_plan(
            query_plan,
            query=request.memory_request.query,
            principal_scope=cast(
                dict[str, object],
                dict(request.memory_request.requested_scope),
            ),
            authority_floor="INFORMATIONAL",
            candidate_limit=QUERY_PRESERVING_UNION_CANDIDATE_CAP,
            context_tokens=ACQUISITION_DECISION_CONTEXT_CEILING,
            tenant_id=str(runtime_settings.tenant_id),
            principal_id=str(runtime_settings.local_actor_id),
            enable_enriched=False,
            enable_dense=True,
            enable_same_session_expansion=True,
            additive_union_v0_2=True,
        )
        capability_policy = AcquisitionCapabilityPolicy(
            policy_version="product08-context-testkit-v0.1",
            max_candidates=QUERY_PRESERVING_UNION_CANDIDATE_CAP,
            max_hydrated_items=160,
        )
        capability_set = resolve_acquisition_capabilities(
            config=AcquisitionRuntimeCapabilityConfig(
                lexical_enrichment_bound=False,
                lexical_enrichment_enabled=False,
                evidence_dense_enabled=True,
                embedding_projection_dimensions=embedding.identity.projection_dimensions,
                adjacent_turns_acquisition_enabled=True,
                query_time_event_enabled=False,
            ),
            projection_state=projection_state,
            repository=repository,
            policy=capability_policy,
            generated_at=retrieval_request.system_as_of,
            source_observed_range=(
                acquisition_plan.global_constraints.source_observed_range
            ),
            event_occurrence_range=None,
        )
        snapshot = capture_frozen_acquisition_snapshot(
            executor=executor,
            context=context,
            memory_request=request.memory_request,
            retrieval_request=retrieval_request,
            query_plan=query_plan,
            acquisition_plan=acquisition_plan,
            capability_set=capability_set,
            projection_state=projection_state,
        )
        capture_counters = {**repository.counters(), **embedding.counters()}
        snapshot = replace(snapshot, capture_counters=capture_counters)
        before_replay = {**repository.counters(), **embedding.counters()}
        arms = {
            arm: replay_frozen_context(snapshot, arm, executor=executor)
            for arm in CONTEXT_REPLAY_ARMS
        }
        after_replay = {**repository.counters(), **embedding.counters()}
        if before_replay != after_replay:
            raise FrozenReplayInvariantError("REPLAY_PERFORMED_FRESH_EXTERNAL_CALL")
        if (
            arms["C"]["before_boundary"]["trace_sha256"]
            != arms["X"]["before_boundary"]["trace_sha256"]
            or arms["C"]["decision_snapshot_digest"]
            != arms["X"]["decision_snapshot_digest"]
        ):
            raise FrozenReplayInvariantError("C_X_CANDIDATE_OR_DECISION_DRIFT")
        dense_dispositions = [
            disposition
            for disposition in [
                *[batch.disposition for batch in snapshot.probe_batches],
                *snapshot.skip_dispositions,
            ]
            if disposition.channel == "EVIDENCE_DENSE"
        ]
        dense_valid = bool(dense_dispositions) and all(
            item.status == "EXECUTED" for item in dense_dispositions
        )
        return {
            "schema_version": "milai-context-testkit-report-v0.1",
            "query_fingerprint": hashlib.sha256(
                request.memory_request.query.encode("utf-8")
            ).hexdigest(),
            "snapshot": _public_snapshot_trace(snapshot),
            "arms": arms,
            "invariants": {
                "snapshot_build_count": 1,
                "c_x_before_boundary_equal": True,
                "c_x_decision_snapshot_equal": True,
                "replay_external_calls": 0,
                "dense_execution_valid": dense_valid,
                "workspace_enabled": False,
                "context_mutation_performed": False,
                "canonical_mutation": False,
            },
        }
    finally:
        runtime_database.close()
        steward_database.close()


def _public_snapshot_trace(snapshot: FrozenAcquisitionSnapshot) -> dict[str, Any]:
    dispositions = [
        *[batch.disposition for batch in snapshot.probe_batches],
        *snapshot.skip_dispositions,
    ]
    return {
        "schema_version": snapshot.schema_version,
        "snapshot_digest": snapshot.snapshot_digest,
        "projection_state": _projection_state_payload(snapshot.projection_state),
        "projection_snapshot_digest": snapshot.capability_set.projection_snapshot_digest,
        "query_plan_digest": canonical_digest(
            snapshot.query_plan.model_dump(mode="json")
        ),
        "acquisition_plan_digest": canonical_digest(
            snapshot.acquisition_plan.model_dump(mode="json")
        ),
        "capture_counters": dict(snapshot.capture_counters),
        "probe_dispositions": [item.model_dump(mode="json") for item in dispositions],
        "probes": [
            {
                "probe_id": batch.probe.probe_id,
                "requirement_id": batch.probe.requirement_slot,
                "channel": batch.probe.channel,
                "candidate_ids": [
                    str(item.get("evidence_id"))
                    for item in batch.results
                    if isinstance(item.get("evidence_id"), str)
                ],
                "source_turn_refs": [
                    str(item.get("source_ref"))
                    for item in batch.results
                    if isinstance(item.get("source_ref"), str)
                ],
                "result_digests": [_result_digest(item) for item in batch.results],
            }
            for batch in snapshot.probe_batches
        ],
        "locality_result_digests": [
            _result_digest(item) for item in snapshot.locality_results
        ],
        "range_result_digests": [
            _result_digest(item) for item in snapshot.range_results
        ],
        "raw_evidence_text_emitted": False,
    }


def _frozen_snapshot_material(
    *,
    memory_request: MemoryResolveRequest,
    retrieval_request: RetrievalRequest,
    query_plan: QueryPlan,
    acquisition_plan: AcquisitionPlan,
    capability_set: AcquisitionCapabilitySet,
    projection_state: ProjectionState,
    batches: Sequence[FrozenProbeBatch],
    locality_results: Sequence[Mapping[str, Any]],
    range_results: Sequence[Mapping[str, Any]],
    range_scan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "frozen-acquisition-snapshot-v0.1",
        "memory_request": memory_request.model_dump(mode="json"),
        "retrieval_request": retrieval_request.model_dump(mode="json"),
        "query_plan": query_plan.model_dump(mode="json"),
        "acquisition_plan": acquisition_plan.model_dump(mode="json"),
        "capability_set": capability_set.model_dump(mode="json"),
        "projection_state": _projection_state_payload(projection_state),
        "probes": [
            {
                "probe": batch.probe.model_dump(mode="json"),
                "results": [_result_digest(item) for item in batch.results],
                "status": batch.disposition.status,
                "reason": batch.disposition.reason_code,
            }
            for batch in batches
        ],
        "locality": [_result_digest(item) for item in locality_results],
        "range": [_result_digest(item) for item in range_results],
        "range_scan": _json_safe(range_scan),
    }


def _snapshot_material(snapshot: FrozenAcquisitionSnapshot) -> dict[str, Any]:
    return _frozen_snapshot_material(
        memory_request=snapshot.memory_request,
        retrieval_request=snapshot.retrieval_request,
        query_plan=snapshot.query_plan,
        acquisition_plan=snapshot.acquisition_plan,
        capability_set=snapshot.capability_set,
        projection_state=snapshot.projection_state,
        batches=snapshot.probe_batches,
        locality_results=snapshot.locality_results,
        range_results=snapshot.range_results,
        range_scan=snapshot.range_scan,
    )


def _result_digest(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    redacted = {
        str(key): _json_safe(value)
        for key, value in item.items()
        if key != "content"
    }
    redacted["content_sha256"] = (
        hashlib.sha256(content.encode("utf-8")).hexdigest()
        if isinstance(content, str)
        else None
    )
    return canonical_digest(redacted)


def _json_safe(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return value


def _result_session_id(item: Mapping[str, Any]) -> str | None:
    envelope = item.get("acquisition_candidate")
    if isinstance(envelope, Mapping) and isinstance(envelope.get("session_id"), str):
        return str(envelope["session_id"])
    context = item.get("source_context")
    if isinstance(context, Mapping) and isinstance(context.get("session_id"), str):
        return str(context["session_id"])
    return None


__all__ = [
    "ContextTestkitRequest",
    "FrozenAcquisitionSnapshot",
    "FrozenReplayInvariantError",
    "capture_frozen_acquisition_snapshot",
    "replay_frozen_context",
    "run_live_context_replay",
]
