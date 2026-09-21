from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from milai.adapters import (
    CrossEncoderReranker,
    DeterministicHashEmbedding,
    EmbeddingProvider,
    EmbeddingUnavailable,
    RerankerUnavailable,
)
from milai.application.accuracy_acquisition import (
    AccuracyAcquisitionExecutor,
    AccuracyActionBundle,
    accuracy_bundle_query_text,
)
from milai.application.acquisition import (
    QUERY_PRESERVING_UNION_CANDIDATE_CAP,
    compile_acquisition_plan,
)
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    resolve_acquisition_capabilities,
)
from milai.application.acquisition_execution_policy import (
    acquisition_execution_policy_safe_summary,
    default_acquisition_execution_policy,
    recovery_plan_candidate_cap,
    select_acquisition_execution_profile,
)
from milai.application.acquisition_state import (
    acquisition_state_trace_summary,
    advance_acquisition_state,
    build_acquisition_action,
    initialize_acquisition_state,
)
from milai.application.appointment_composition import (
    temporal_query_axis,
)
from milai.application.decision_engine import DEFAULT_DECISION_ENGINE
from milai.application.deterministic_recovery import (
    CapabilityConstrainedRecoveryService,
)
from milai.application.errors import (
    CausalConsistencyError,
    RetrievalRouteDisabled,
    TenantMismatch,
)
from milai.application.evidence_acquisition import (
    EvidenceAcquisitionExecutionRef,
    EvidenceAcquisitionExecutor,
    materialize_acquisition_execution,
)
from milai.application.formation_projection import (
    FormationProjectionMode,
    FormationProjectionStore,
)
from milai.application.formation_semantic_replay import (
    ground_formation_semantics,
    specialize_formation_replay_plan,
)
from milai.application.lean_recall import lean_decision_mode
from milai.application.memory_access import (
    ACQUISITION_DECISION_CONTEXT_CEILING,
    MemoryAccessPlan,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_planner import QueryPlanner, payload_free_query_plan
from milai.application.reader_evidence_plan import (
    materialize_decision_snapshot,
)
from milai.application.recollection import (
    MatchedReplayInvariantError,
    MatchedReplayPolicy,  # noqa: F401 - compatibility import
    MatchedRetrievalReplay,  # noqa: F401 - compatibility import
    RetrievalExecution,
)
from milai.application.requirement_state import resolve_requirement_state
from milai.application.retrieval_core.acquisition import (
    _acquisition_candidate_envelopes,
    _acquisition_reference_material,
    _formation_candidate_results,
    _merge_evidence_results,
    _union_formation_and_raw,
    _use_acquisition_composition,
)
from milai.application.retrieval_core.assembly import (
    _accepted_binding_spans,  # noqa: F401 - compatibility import
    _assemble_results,
    _binding_span_provenance_order,  # noqa: F401 - compatibility import
    _contains_evidence_observation,
    _decision_accepted_evidence_ids,  # noqa: F401 - compatibility import
    _decision_requirement_ids,  # noqa: F401 - compatibility import
    _requirement_evidence_set,  # noqa: F401 - compatibility import
    _response_body,
    _result_evidence_ids,  # noqa: F401 - compatibility import
)
from milai.application.retrieval_core.assembly import (
    _decision_snapshot as _decision_snapshot,
)
from milai.application.retrieval_core.assembly import (
    _projection_state_payload as _projection_state_payload,
)
from milai.application.retrieval_core.candidates import (
    _deduplicate_evidence,  # noqa: F401 - compatibility import
    _diversify_evidence_by_subject,  # noqa: F401 - compatibility import
    _merge_candidates,
    _rank_evidence_turns,  # noqa: F401 - compatibility import
    _result_identity,  # noqa: F401 - compatibility import
)
from milai.application.retrieval_core.operators import (
    _execute_operator_with_accepted_inputs,
    _explicit_compound_subject_matches,  # noqa: F401 - compatibility import
    _state_count_cover,  # noqa: F401 - compatibility import
)
from milai.application.retrieval_core.operators import (
    _operator_support_refs as _operator_support_refs,
)
from milai.application.retrieval_core.policy import (
    _candidate_pool_floor,
    _deadline_exhausted,
    _remaining_timeout_ms,
    _retrieval_policy,
)
from milai.application.retrieval_core.selection import (
    _apply_context_budget,
    _context_budget_view,  # noqa: F401 - compatibility import
    _context_candidate_budget,  # noqa: F401 - compatibility import
    _jaccard,  # noqa: F401 - compatibility import
    _mmr_select,  # noqa: F401 - compatibility import
    _mmr_tokens,  # noqa: F401 - compatibility import
    _set_cover_text,  # noqa: F401 - compatibility import
    _set_cover_tokens,  # noqa: F401 - compatibility import
    _weighted_set_cover_select,  # noqa: F401 - compatibility import
)
from milai.application.retrieval_core.temporal import (
    _binary_anchor_cover,  # noqa: F401 - compatibility import
    _binary_event_anchor_queries,
    _binary_event_anchor_terms,  # noqa: F401 - compatibility import
    _intent_tokens,  # noqa: F401 - compatibility import
    _relative_event_dates,  # noqa: F401 - compatibility import
    _relative_event_distance,  # noqa: F401 - compatibility import
    _relative_event_intent_overlap,  # noqa: F401 - compatibility import
    _relative_point_cover,  # noqa: F401 - compatibility import
    _relative_point_target,  # noqa: F401 - compatibility import
    _relative_target,  # noqa: F401 - compatibility import
    _rerank_by_reference,  # noqa: F401 - compatibility import
    _temporal_rerank,  # noqa: F401 - compatibility import
    _temporal_subject_indices,  # noqa: F401 - compatibility import
    _temporal_text,  # noqa: F401 - compatibility import
    _temporal_timestamp,  # noqa: F401 - compatibility import
    _temporal_tokens,  # noqa: F401 - compatibility import
)
from milai.application.retrieval_core.trace import (
    _EXECUTION_STAGE_BY_OPERATION,  # noqa: F401 - compatibility import
    _abstract_stage_sequence,  # noqa: F401 - compatibility import
    _access_trace_view,
    _build_matched_retrieval_replay,
    _canonical_sha256,  # noqa: F401 - compatibility import
    _execution_trace,
    _latency_spans,  # noqa: F401 - compatibility import
    _LegacyReplayPrefix,
    _public_acquisition_probe_disposition,
    _public_temporal_acquisition_trace,
    _stage_metrics,
    _structural_cost,  # noqa: F401 - compatibility import
    _unavailable_access_trace,
)
from milai.application.sufficiency import (
    budget_exhausted_decision,
    unavailable_decision,
)
from milai.domain import CausalTokenCodec, CausalTokenError
from milai.domain.acquisition import (
    AcquisitionBudgetUse,
    AcquisitionPlan,
    AcquisitionState,
)
from milai.domain.acquisition_capability import AcquisitionCapabilitySet
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.sufficiency import SufficiencyDecision
from milai.observability import OperationTimer
from milai.persistence import DatabaseStatementTimeout, DatabaseUnavailable, SessionContext
from milai.persistence.retrieval_repository import (
    GatedBatch,
    ProjectionState,
    ProjectionUnavailable,
    RetrievalCandidate,
    RetrievalRepository,
    RetrievalTraceCommand,
)

if TYPE_CHECKING:
    from milai.observability.retrieval_audit import RetrievalAuditObserver

_PROGRESSIVE_L1_CONFIG_ID = (
    "progressive-l1-v1:"
    + hashlib.sha256(
        b"typed-need;canonical-gate-before-stop;current-fts;history-explanation-vector;"
        b"action-safe-and-operators-full"
    ).hexdigest()
)
_DETERMINISTIC_RECOVERY_CANDIDATE_CAP = 8


_AssembledResults = tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, Any]],
    list[str],
]


@dataclass(frozen=True, slots=True)
class _FormationApplication:
    execution: EvidenceAcquisitionExecutionRef
    query_plan: QueryPlan
    acquisition_plan: AcquisitionPlan


class _ScopedAccuracyRepository:
    """Adapt the governed Evidence snapshot to the DG-22 accuracy executor."""

    def __init__(
        self,
        repository: RetrievalRepository,
        context: SessionContext,
        request: RetrievalRequest,
        *,
        statement_timeout_ms: int,
    ) -> None:
        self._repository = repository
        self._context = context
        self._request = request
        self._statement_timeout_ms = statement_timeout_ms

    def scan_accuracy_bundle(
        self,
        *,
        query_ir: Any,
        bundle: AccuracyActionBundle,
    ) -> list[dict[str, Any]]:
        if bundle.channel in {"FTS_RAW", "FTS_ENRICHED"}:
            query = accuracy_bundle_query_text(query_ir, bundle)
            if not query:
                return []
            return self._repository.search_evidence(
                self._context,
                query,
                cast(dict[str, object], dict(self._request.requested_scope)),
                self._request.as_of,
                120,
                statement_timeout_ms=self._statement_timeout_ms,
            )
        snapshot_end = self._request.as_of.astimezone(UTC)
        if snapshot_end < datetime.max.replace(tzinfo=UTC):
            snapshot_end += timedelta(microseconds=1)
        snapshot = self._repository.scan_evidence_range(
            self._context,
            cast(dict[str, object], dict(self._request.requested_scope)),
            datetime.min.replace(tzinfo=UTC),
            snapshot_end,
            2_000,
            statement_timeout_ms=self._statement_timeout_ms,
        )
        items = snapshot.get("items")
        if snapshot.get("status") != "COMPLETE" or not isinstance(items, list):
            raise RuntimeError("ACCURACY_GOVERNED_SNAPSHOT_INCOMPLETE")
        if not all(isinstance(item, dict) for item in items):
            raise RuntimeError("ACCURACY_GOVERNED_SNAPSHOT_INVALID")
        return [dict(item) for item in items]


def _accuracy_execution_safe_summary(execution: Mapping[str, Any]) -> dict[str, Any]:
    """Expose bounded cost/provenance counters, never candidate contents."""

    summary: dict[str, Any] = {}
    for key in ("executor_identity", "policy_version"):
        value = execution.get(key)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"ACCURACY_EXECUTION_INVALID_{key.upper()}")
        summary[key] = value
    for key in (
        "candidates_scanned",
        "candidates_hydrated",
        "useful_candidate_count",
        "repository_probe_calls",
        "provider_controller_calls",
        "automatic_retries",
    ):
        value = execution.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError(f"ACCURACY_EXECUTION_INVALID_{key.upper()}")
        summary[key] = value
    canonical_mutation = execution.get("canonical_mutation")
    if canonical_mutation is not False:
        raise RuntimeError("ACCURACY_EXECUTION_CANONICAL_MUTATION")
    summary["canonical_mutation"] = False
    return summary


class RetrievalService:
    def __init__(
        self,
        repository: RetrievalRepository,
        embedding: EmbeddingProvider | None = None,
        planner: QueryPlanner | None = None,
        causal_tokens: CausalTokenCodec | None = None,
        mmr_enabled: bool = False,
        mmr_lambda: float = 0.8,
        reranker: CrossEncoderReranker | None = None,
        reranker_pool_size: int = 10,
        temporal_reranker_pool_size: int = 20,
        lexical_enrichment_enabled: bool = False,
        evidence_dense_enabled: bool = False,
        deterministic_recovery_enabled: bool = False,
        type_directed_semantics_enabled: bool = False,
        type_directed_acquisition_enabled: bool = False,
        query_time_event_enabled: bool | None = None,
        budget_stable_context_enabled: bool = False,
        retrieval_audit_observer: RetrievalAuditObserver | None = None,
        formation_projection: FormationProjectionStore | None = None,
        formation_mode: FormationProjectionMode = "OFF",
        query_preserving_union_enabled: bool = False,
        additive_union_v0_2_enabled: bool = False,
    ) -> None:
        if not 0.5 <= mmr_lambda <= 1.0:
            raise ValueError("mmr_lambda must be between 0.5 and 1.0")
        self._repository = repository
        self._embedding = embedding or DeterministicHashEmbedding()
        self._planner = planner or QueryPlanner()
        self._causal_tokens = causal_tokens
        self._mmr_enabled = mmr_enabled
        self._mmr_lambda = mmr_lambda
        self._reranker = reranker
        self._reranker_pool_size = reranker_pool_size
        self._temporal_reranker_pool_size = temporal_reranker_pool_size
        self._lexical_enrichment_enabled = lexical_enrichment_enabled
        self._evidence_dense_enabled = evidence_dense_enabled
        self._deterministic_recovery_enabled = deterministic_recovery_enabled
        self._type_directed_semantics_enabled = (
            type_directed_semantics_enabled or type_directed_acquisition_enabled
        )
        self._type_directed_acquisition_enabled = type_directed_acquisition_enabled
        self._budget_stable_context_enabled = budget_stable_context_enabled
        self._query_preserving_union_enabled = query_preserving_union_enabled
        self._additive_union_v0_2_enabled = additive_union_v0_2_enabled
        self._retrieval_audit_observer = retrieval_audit_observer
        if (formation_mode == "OFF") != (formation_projection is None):
            raise ValueError(
                "Formation projection must be absent in OFF and present in SHADOW/CANARY"
            )
        self._formation_projection = formation_projection
        self._formation_mode = formation_mode
        self._query_time_event_enabled = (
            type_directed_acquisition_enabled
            if query_time_event_enabled is None
            else query_time_event_enabled
        )
        self._evidence_acquisition_executor = EvidenceAcquisitionExecutor(
            repository,
            self._embedding,
        )
        self._deterministic_recovery_service = CapabilityConstrainedRecoveryService(
            self._evidence_acquisition_executor
        )
        self._acquisition_capability_policy = AcquisitionCapabilityPolicy()
        self._deterministic_recovery_policy = AcquisitionCapabilityPolicy(
            max_candidates=_DETERMINISTIC_RECOVERY_CANDIDATE_CAP
        )
        self._acquisition_execution_policy = default_acquisition_execution_policy()
        self._dg21_recovery_capability_policy = AcquisitionCapabilityPolicy(
            policy_version="dg21-execution-policy-adapter-v0.1",
            max_candidates=2_000,
            # Preserve the legacy deterministic recovery's matched 8-item
            # hydration envelope. DG21 profiles may scan more rows, but C/D
            # compose on B and must not silently replace B with a narrower
            # evidence set.
            max_hydrated_items=8,
        )

    def _apply_formation_projection(
        self,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        capability_set: AcquisitionCapabilitySet,
        baseline: EvidenceAcquisitionExecutionRef,
        progressive_l1: dict[str, Any],
        degraded: set[str],
        stages: OperationTimer,
        statement_timeout_ms: int | None,
    ) -> _FormationApplication:
        """Canary source IDs through live Gate and the full semantic compiler."""

        if self._formation_mode == "OFF":
            return _FormationApplication(baseline, query_plan, acquisition_plan)
        projection = self._formation_projection
        if projection is None:
            raise AssertionError("enabled Formation mode has no projection")
        selection = stages.call(
            "formation_selection_ms",
            projection.select,
            context,
            request,
        )
        trace = {
            "mode": self._formation_mode,
            **selection.safe_trace(),
            "formation_matched": selection.status == "SELECTED",
            "hydrated_source_count": 0,
            "governance_rejected_source_count": 0,
            "new_governed_candidate_count": 0,
            "new_accepted_binding_count": 0,
            "required_evidence_coverage_delta": 0.0,
            "operator_ready_delta": 0,
            "full_semantics_recomputed": False,
            "raw_baseline_preserved": True,
            "shadow_only": self._formation_mode == "SHADOW",
            "applied": False,
            "fallback_taken": True,
        }
        progressive_l1["formation_projection"] = trace
        if not selection.evidence_ids:
            return _FormationApplication(baseline, query_plan, acquisition_plan)
        if baseline.bounded_range_scan_proof is not None:
            trace["integration_reason_code"] = "FORMATION_RANGE_PROOF_PRESERVED"
            return _FormationApplication(baseline, query_plan, acquisition_plan)
        try:
            hydrated = stages.call(
                "formation_hydration_ms",
                self._repository.hydrate_evidence_by_ids,
                context,
                evidence_ids=list(selection.evidence_ids),
                requested_scope=dict(request.requested_scope),
                as_of=request.as_of,
                max_items=min(24, len(selection.evidence_ids)),
                statement_timeout_ms=statement_timeout_ms,
            )
            formed_results = _formation_candidate_results(
                hydrated,
                projection_digest=selection.projection_digest,
            )
            trace["hydrated_source_count"] = len(formed_results)
            trace["governance_rejected_source_count"] = max(
                0,
                len(selection.evidence_ids) - len(formed_results),
            )
            if not formed_results:
                trace["integration_reason_code"] = "FORMATION_GOVERNANCE_REJECTED_ALL"
                return _FormationApplication(baseline, query_plan, acquisition_plan)
            combined = _union_formation_and_raw(formed_results, baseline.results)
            if len(combined) > acquisition_plan.budget.hydrate_count:
                trace["integration_reason_code"] = "FORMATION_HYDRATION_BUDGET_PRESERVED"
                return _FormationApplication(baseline, query_plan, acquisition_plan)
            grounded = ground_formation_semantics(selection, hydrated)
            replay = specialize_formation_replay_plan(
                query_plan,
                acquisition_plan,
                selection,
                query=request.query or "",
            )
            trace.update(
                {
                    "semantic_artifact_count": grounded.artifact_count,
                    "grounded_span_count": len(grounded.spans),
                    "grounded_interpretation_count": len(grounded.interpretations),
                    "semantic_specialization": replay.specialization,
                }
            )
            augmented = self._evidence_acquisition_executor.compile_existing_results(
                request=request,
                query_plan=replay.query_plan,
                acquisition_plan=replay.acquisition_plan,
                capability_set=capability_set,
                mode=(
                    "SHADOW_NO_CONTEXT_MUTATION" if self._formation_mode == "SHADOW" else "PRODUCT"
                ),
                state_epoch=baseline.requirement_state.state_epoch + 1,
                results=combined,
                action_digest=baseline.action_digest,
                probe_dispositions=baseline.probe_dispositions,
                probe_candidate_traces=baseline.probe_candidate_traces,
                type_directed_semantics=baseline.type_directed_semantics,
                grounded_formation_semantics=grounded,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "formation_projection_canary_failed",
                extra={"formation_mode": self._formation_mode},
            )
            degraded.add("formation_projection")
            trace["integration_reason_code"] = "FORMATION_CANARY_EXECUTION_FAILED"
            return _FormationApplication(baseline, query_plan, acquisition_plan)

        baseline_satisfied = set(baseline.requirement_state.satisfied_requirement_ids)
        augmented_satisfied = set(augmented.requirement_state.satisfied_requirement_ids)
        required_count = max(1, len(augmented.requirement_state.requirements))
        baseline_candidate_ids = {item.candidate_id for item in baseline.candidates}
        augmented_candidate_ids = {item.candidate_id for item in augmented.candidates}
        same_requirement_universe = replay.specialization == "UNCHANGED"
        semantics_regressed = (
            same_requirement_universe and not baseline_satisfied.issubset(augmented_satisfied)
        ) or (
            baseline.sufficiency_decision.complete and not augmented.sufficiency_decision.complete
        )
        trace.update(
            {
                "full_semantics_recomputed": True,
                "baseline_requirement_state_digest": (baseline.requirement_state.state_digest),
                "augmented_requirement_state_digest": (augmented.requirement_state.state_digest),
                "baseline_complete": baseline.sufficiency_decision.complete,
                "augmented_complete": augmented.sufficiency_decision.complete,
                "newly_satisfied_requirement_count": len(augmented_satisfied - baseline_satisfied),
                "new_governed_candidate_count": len(
                    augmented_candidate_ids - baseline_candidate_ids
                ),
                "new_accepted_binding_count": len(
                    augmented_satisfied - baseline_satisfied
                ),
                "required_evidence_coverage_delta": round(
                    (len(augmented_satisfied) - len(baseline_satisfied)) / required_count,
                    9,
                ),
                "operator_ready_delta": int(
                    not augmented.requirement_state.missing_requirement_ids
                )
                - int(not baseline.requirement_state.missing_requirement_ids),
                "semantics_regressed": semantics_regressed,
            }
        )
        if semantics_regressed:
            trace["integration_reason_code"] = "FORMATION_SEMANTIC_REGRESSION_FALLBACK"
            return _FormationApplication(baseline, query_plan, acquisition_plan)
        if self._formation_mode == "SHADOW":
            trace["integration_reason_code"] = "FORMATION_SHADOW_OBSERVED"
            return _FormationApplication(baseline, query_plan, acquisition_plan)
        if not augmented_satisfied.difference(baseline_satisfied):
            # Keep a newly governed Formation candidate in the sealed
            # acquisition snapshot, but do not turn it into Reader-visible Raw
            # Evidence unless the semantic pass accepted new requirement
            # coverage.  This is independent of the configured default Reader
            # policy: a canary candidate is not itself an accepted Binding.
            augmented = augmented.model_copy(
                update={"results": [dict(item) for item in baseline.results]}
            )
        trace.update(
            {
                "integration_reason_code": "FORMATION_CANARY_APPLIED",
                "applied": True,
                "fallback_taken": False,
            }
        )
        return _FormationApplication(
            augmented,
            replay.query_plan,
            replay.acquisition_plan,
        )

    def retrieve(
        self,
        context: SessionContext,
        request: RetrievalRequest,
        request_id: str,
        *,
        require_user_confirmation: bool = False,
        context_budget: int = 8_000,
        resolved_claim_version_id: UUID | None = None,
        resolution_dimensions: dict[str, bool] | None = None,
        state_address_resolution_ms: float | None = None,
        allow_historical: bool = False,
        access_plan: MemoryAccessPlan | None = None,
        capture_matched_replay: bool = False,
        defer_decision_snapshot: bool = False,
    ) -> RetrievalExecution:
        if request.tenant_id is not None and request.tenant_id != context.tenant_id:
            raise TenantMismatch("body tenant does not match authenticated tenant")
        minimum_outbox_sequence: int | None = None
        if request.causal_token is not None:
            if self._causal_tokens is None:
                raise CausalConsistencyError("CAUSAL_TOKEN_VALIDATION_UNAVAILABLE")
            try:
                position = self._causal_tokens.decode(request.causal_token, context.tenant_id)
            except CausalTokenError as exc:
                raise CausalConsistencyError("INVALID_CAUSAL_TOKEN") from exc
            minimum_outbox_sequence = position.minimum_outbox_sequence
        presentation_context_budget = (
            access_plan.context_token_budget if access_plan is not None else context_budget
        )
        decision_input_budget = (
            ACQUISITION_DECISION_CONTEXT_CEILING
            if self._budget_stable_context_enabled
            else presentation_context_budget
        )
        plan = self._planner.plan(
            request,
            require_user_confirmation=require_user_confirmation,
            context_budget=decision_input_budget,
            minimum_outbox_sequence=minimum_outbox_sequence,
            access_intent=access_plan.access_intent if access_plan is not None else None,
            candidate_cap=access_plan.candidate_cap if access_plan is not None else 256,
            deadline_ms=access_plan.deadline_ms if access_plan is not None else 2_000,
            reranker_candidate_cap=(
                access_plan.reranker_candidate_cap if access_plan is not None else 20
            ),
            hard_partitions=(access_plan.hard_partitions if access_plan is not None else ()),
            vector_policy=(access_plan.vector_policy if access_plan is not None else "LEGACY"),
            reranker_policy=(access_plan.reranker_policy if access_plan is not None else "LEGACY"),
        )
        if plan.complexity == "L2":
            raise RetrievalRouteDisabled("L2 is not enabled in Lean V1")
        if capture_matched_replay and request.route != "L1":
            raise MatchedReplayInvariantError("matched replay is only valid for L1")
        if (
            resolved_claim_version_id is not None
            or resolution_dimensions is not None
            or allow_historical
        ) and request.route != "L0":
            raise ValueError("pre-resolved StateAddress is only valid for L0")
        dimensions = dict(resolution_dimensions) if resolution_dimensions is not None else None

        started = perf_counter()
        stages = OperationTimer()
        if state_address_resolution_ms is not None:
            stages.observe_duration("state_address_resolution_ms", state_address_resolution_ms)
        fingerprint = _fingerprint(context.tenant_id, request)
        scope = cast(dict[str, object], dict(request.requested_scope))
        degraded: set[str] = set()
        fallback_used = False
        fallback_reason: str | None = None
        initial_state: ProjectionState | None = None
        causal_wait_outcome: str | None = None
        causal_waited_ms = 0
        progressive_l1: dict[str, Any] = {
            "config_identity": _PROGRESSIVE_L1_CONFIG_ID,
            "enabled": request.route == "L1"
            and (request.memory_intent is not None or access_plan is not None),
            "memory_intent": request.memory_intent,
            "access_intent": access_plan.access_intent if access_plan is not None else None,
            "budget": (
                {
                    "candidate_cap": access_plan.candidate_cap,
                    "deadline_ms": access_plan.deadline_ms,
                    "context_token_budget": access_plan.context_token_budget,
                    "reranker_candidate_cap": access_plan.reranker_candidate_cap,
                }
                if access_plan is not None
                else None
            ),
            "candidate_counts": {},
            "escalation_reasons": [],
            "deadline_outcome": "NOT_APPLICABLE" if access_plan is None else "PENDING",
            "context_token_upper_bound": 0,
            "context_budget_truncated": False,
            "stages_attempted": [],
            "sufficiency_checks": [],
            "sufficiency_decisions": [],
            "terminal_sufficiency_decision": None,
            "stop_stage": None,
            "sufficiency_reason": None,
        }
        acquisition_plan: AcquisitionPlan | None = None
        acquisition_state: AcquisitionState | None = None
        acquisition_execution: EvidenceAcquisitionExecutionRef | None = None
        legacy_replay_prefix: _LegacyReplayPrefix | None = None
        try:
            initial_state = stages.call(
                "projection_state_ms", self._repository.projection_state, context
            )
            candidate_groups: list[list[RetrievalCandidate]] = []
            query = request.query or ""
            source_weights, recent_enabled, multi_intent = _retrieval_policy(query)
            minimum_candidates = _candidate_pool_floor(plan, multi_intent)
            candidate_limit = (
                access_plan.candidate_cap
                if access_plan is not None
                else min(256, max(minimum_candidates, request.limit * 3))
            )
            search_budget_exhausted = False
            evidence_results: list[dict[str, Any]] = []
            evidence_composition: dict[str, Any] | None = None
            evidence_search = getattr(self._repository, "search_evidence", None)
            if (
                request.route == "L1"
                and request.required_authority == "INFORMATIONAL"
                and callable(evidence_search)
            ):
                progressive_l1["stages_attempted"].append("EVIDENCE_FTS")
                acquisition_plan = compile_acquisition_plan(
                    plan,
                    query=query,
                    principal_scope=scope,
                    authority_floor=request.required_authority,
                    candidate_limit=(
                        QUERY_PRESERVING_UNION_CANDIDATE_CAP
                        if (
                            self._query_preserving_union_enabled
                            or self._additive_union_v0_2_enabled
                        )
                        else candidate_limit
                    ),
                    context_tokens=decision_input_budget,
                    tenant_id=str(context.tenant_id),
                    principal_id=str(context.actor_id),
                    enable_enriched=self._lexical_enrichment_enabled,
                    enable_dense=self._evidence_dense_enabled,
                    enable_same_session_expansion=(
                        self._type_directed_acquisition_enabled
                        or self._query_preserving_union_enabled
                        or self._additive_union_v0_2_enabled
                    ),
                    query_preserving_union=self._query_preserving_union_enabled,
                    additive_union_v0_2=self._additive_union_v0_2_enabled,
                )
                progressive_l1["acquisition_plan"] = acquisition_plan.model_dump(mode="json")
                if plan.memory_query_ir is not None:
                    capability_set = resolve_acquisition_capabilities(
                        config=AcquisitionRuntimeCapabilityConfig(
                            lexical_enrichment_bound=self._lexical_enrichment_enabled,
                            lexical_enrichment_enabled=self._lexical_enrichment_enabled,
                            evidence_dense_enabled=self._evidence_dense_enabled,
                            adjacent_turns_acquisition_enabled=(
                                self._type_directed_acquisition_enabled
                                or self._query_preserving_union_enabled
                                or self._additive_union_v0_2_enabled
                            ),
                            query_time_event_enabled=self._query_time_event_enabled,
                            embedding_projection_dimensions=(
                                self._embedding.identity.projection_dimensions
                            ),
                        ),
                        projection_state=initial_state,
                        repository=self._repository,
                        policy=self._acquisition_capability_policy,
                        generated_at=request.system_as_of,
                        source_observed_range=(
                            acquisition_plan.global_constraints.source_observed_range
                        ),
                        event_occurrence_range=(
                            None
                            if self._additive_union_v0_2_enabled
                            else acquisition_plan.global_constraints.event_occurrence_range
                        ),
                    )
                    progressive_l1["acquisition_capability"] = {
                        "capability_digest": capability_set.capability_digest,
                        "config_digest": capability_set.config_digest,
                        "projection_snapshot_digest": (capability_set.projection_snapshot_digest),
                        "policy_digest": capability_set.policy_digest,
                        "channels": {
                            key: {
                                "status": value.status,
                                "reason": value.reason,
                            }
                            for key, value in capability_set.channels.items()
                        },
                        "expansions": {
                            key: {
                                "status": value.status,
                                "reason": value.reason,
                            }
                            for key, value in capability_set.expansions.items()
                        },
                    }
                    acquisition_execution = self._evidence_acquisition_executor.execute(
                        context=context,
                        request=request,
                        query_plan=plan,
                        acquisition_plan=acquisition_plan,
                        capability_set=capability_set,
                        policy=self._acquisition_capability_policy,
                        mode="PRODUCT",
                        state_epoch=0,
                        type_directed_semantics=self._type_directed_semantics_enabled,
                        defer_semantics=(
                            defer_decision_snapshot and self._retrieval_audit_observer is None
                            and not capture_matched_replay and self._formation_mode == "OFF"
                            and not self._deterministic_recovery_enabled
                        ),
                    )
                    if self._deterministic_recovery_enabled:
                        progressive_l1["baseline_acquisition_capability"] = deepcopy(
                            progressive_l1["acquisition_capability"]
                        )
                        terminal_selection = None
                        if self._type_directed_semantics_enabled and (
                            acquisition_execution.sufficiency_decision.complete
                            or not acquisition_execution.requirement_state.missing_requirement_ids
                        ):
                            terminal_selection = select_acquisition_execution_profile(
                                policy=self._acquisition_execution_policy,
                                query_ir=plan.memory_query_ir,
                                requirement_state=acquisition_execution.requirement_state,
                                sufficiency=acquisition_execution.sufficiency_decision,
                                capability_set=capability_set,
                                remaining_budget={
                                    "acquisition_passes": 1,
                                    "candidate_count": (
                                        self._acquisition_execution_policy.profiles.semantic_slot.dense_candidate_cap
                                    ),
                                },
                            )
                            if terminal_selection.terminal_disposition not in {
                                "COMPLETE",
                                "NO_TARGETABLE_REQUIREMENT",
                            }:
                                raise AssertionError(
                                    "DG21 terminal precondition selected acquisition work"
                                )
                        if self._type_directed_semantics_enabled:
                            progressive_l1["acquisition_execution_policy"] = (
                                acquisition_execution_policy_safe_summary(
                                    self._acquisition_execution_policy
                                )
                            )
                        recovery_candidate_limit = (
                            recovery_plan_candidate_cap(
                                self._acquisition_execution_policy,
                                plan.memory_query_ir,
                            )
                            if self._type_directed_acquisition_enabled
                            else candidate_limit
                        )
                        recovery_plan = (
                            acquisition_plan
                            if terminal_selection is not None
                            else compile_acquisition_plan(
                                plan,
                                query=query,
                                principal_scope=scope,
                                authority_floor=request.required_authority,
                                candidate_limit=recovery_candidate_limit,
                                context_tokens=decision_input_budget,
                                tenant_id=str(context.tenant_id),
                                principal_id=str(context.actor_id),
                                enable_enriched=True,
                                enable_dense=True,
                                source_time_point_profile=(
                                    self._acquisition_execution_policy.profiles.source_time_point
                                    if self._type_directed_acquisition_enabled
                                    else None
                                ),
                            )
                        )
                        recovery_policy = (
                            self._dg21_recovery_capability_policy
                            if self._type_directed_acquisition_enabled
                            else self._deterministic_recovery_policy
                        )
                        recovery_capability_set = (
                            capability_set
                            if terminal_selection is not None
                            else resolve_acquisition_capabilities(
                                config=AcquisitionRuntimeCapabilityConfig(
                                    lexical_enrichment_bound=True,
                                    lexical_enrichment_enabled=True,
                                    evidence_dense_enabled=True,
                                    adjacent_turns_acquisition_enabled=(
                                        self._type_directed_acquisition_enabled
                                    ),
                                    query_time_event_enabled=(self._query_time_event_enabled),
                                    embedding_projection_dimensions=(
                                        self._embedding.identity.projection_dimensions
                                    ),
                                ),
                                projection_state=initial_state,
                                repository=self._repository,
                                policy=recovery_policy,
                                generated_at=request.system_as_of,
                                source_observed_range=(
                                    recovery_plan.global_constraints.source_observed_range
                                ),
                                event_occurrence_range=(
                                    recovery_plan.global_constraints.event_occurrence_range
                                ),
                            )
                        )
                        recovery = (
                            None
                            if terminal_selection is not None
                            else self._deterministic_recovery_service.recover(
                                context=context,
                                request=request,
                                query_plan=plan,
                                recovery_plan=recovery_plan,
                                capability_set=recovery_capability_set,
                                policy=recovery_policy,
                                baseline_execution=materialize_acquisition_execution(
                                    acquisition_execution,
                                ),
                                mode="PRODUCT",
                                type_directed_semantics=(self._type_directed_semantics_enabled),
                                execution_policy=(
                                    self._acquisition_execution_policy
                                    if self._type_directed_acquisition_enabled
                                    else None
                                ),
                                accuracy_executor=(
                                    AccuracyAcquisitionExecutor(
                                        _ScopedAccuracyRepository(
                                            self._repository,
                                            context,
                                            request,
                                            statement_timeout_ms=plan.deadline_ms,
                                        )
                                    )
                                    if self._type_directed_acquisition_enabled
                                    else None
                                ),
                            )
                        )
                        if terminal_selection is not None:
                            progressive_l1["deterministic_recovery"] = {
                                "enabled": True,
                                "attempted": False,
                                "initial_requirement_state_digest": (
                                    acquisition_execution.requirement_state.state_digest
                                ),
                                "initial_requirement_state_epoch": (
                                    acquisition_execution.requirement_state.state_epoch
                                ),
                                "capability_digest": capability_set.capability_digest,
                                "observation_digest": None,
                                "execution_selection": terminal_selection.model_dump(mode="json"),
                                "decision": {
                                    "reason_code": (terminal_selection.terminal_disposition),
                                    "selected_action": None,
                                    "extra_passes_authorized": 0,
                                    "provider_calls_authorized": 0,
                                    "automatic_retries_authorized": 0,
                                    "canonical_mutation": False,
                                },
                                "auxiliary_work": {
                                    "recovery_plan_compilations": 0,
                                    "capability_resolutions": 0,
                                    "observation_builds": 0,
                                    "repository_probe_calls": 0,
                                    "model_calls": 0,
                                },
                                "extra_pass_count": 0,
                                "provider_calls": 0,
                                "automatic_retries": 0,
                                "canonical_mutation": False,
                            }
                        else:
                            assert recovery is not None
                            progressive_l1["deterministic_recovery"] = {
                                "enabled": True,
                                "attempted": True,
                                "initial_requirement_state_digest": (
                                    recovery.initial_requirement_state.state_digest
                                ),
                                "initial_requirement_state_epoch": (
                                    recovery.initial_requirement_state.state_epoch
                                ),
                                "initial_requirement_dispositions": [
                                    {
                                        "requirement_id": item.requirement_id,
                                        "kind": item.kind,
                                        "status": item.status,
                                        "observed_cardinality": item.observed_cardinality,
                                        "required_minimum": item.required_cardinality.minimum,
                                        "proof_status": item.proof_status,
                                    }
                                    for item in recovery.initial_requirement_state.requirements
                                ],
                                "capability_digest": (recovery_capability_set.capability_digest),
                                "observation_digest": (recovery.observation.observation_digest),
                                "decision": recovery.decision.model_dump(mode="json"),
                                "execution_selection": (
                                    recovery.execution_selection.model_dump(mode="json")
                                    if recovery.execution_selection is not None
                                    else None
                                ),
                                "superseded_execution_selection": (
                                    recovery.superseded_execution_selection.model_dump(mode="json")
                                    if recovery.superseded_execution_selection is not None
                                    else None
                                ),
                                "accuracy_decision": recovery.accuracy_decision,
                                "effective_acquisition_plan_digest": (
                                    recovery.effective_acquisition_plan_digest
                                ),
                                "extra_pass_count": recovery.extra_pass_count,
                                "provider_calls": recovery.provider_calls,
                                "automatic_retries": recovery.automatic_retries,
                                "canonical_mutation": recovery.canonical_mutation,
                            }
                            if recovery.accuracy_execution is not None:
                                progressive_l1["deterministic_recovery"]["accuracy_acquisition"] = (
                                    _accuracy_execution_safe_summary(recovery.accuracy_execution)
                                )
                        if recovery is not None and recovery.final_execution is not None:
                            acquisition_plan = recovery.effective_acquisition_plan
                            capability_set = recovery_capability_set
                            acquisition_execution = recovery.final_execution
                            progressive_l1["acquisition_plan"] = acquisition_plan.model_dump(
                                mode="json"
                            )
                            progressive_l1["acquisition_capability"] = {
                                "capability_digest": capability_set.capability_digest,
                                "config_digest": capability_set.config_digest,
                                "projection_snapshot_digest": (
                                    capability_set.projection_snapshot_digest
                                ),
                                "policy_digest": capability_set.policy_digest,
                                "channels": {
                                    key: {
                                        "status": value.status,
                                        "reason": value.reason,
                                    }
                                    for key, value in capability_set.channels.items()
                                },
                                "expansions": {
                                    key: {
                                        "status": value.status,
                                        "reason": value.reason,
                                    }
                                    for key, value in capability_set.expansions.items()
                                },
                            }
                    formation_application = self._apply_formation_projection(
                        context=context,
                        request=request,
                        query_plan=plan,
                        acquisition_plan=acquisition_plan,
                        capability_set=capability_set,
                        baseline=acquisition_execution,
                        progressive_l1=progressive_l1,
                        degraded=degraded,
                        stages=stages,
                        statement_timeout_ms=None,
                    )
                    acquisition_execution = formation_application.execution
                    plan = formation_application.query_plan
                    acquisition_plan = formation_application.acquisition_plan
                    progressive_l1["acquisition_plan"] = acquisition_plan.model_dump(mode="json")
                    stages.observe_duration(
                        "evidence_fts_ms",
                        sum(item.latency_ms for item in acquisition_execution.probe_dispositions),
                    )
                    for disposition in acquisition_execution.probe_dispositions:
                        if (
                            disposition.channel in {"FTS_RAW", "FTS_ENRICHED"}
                            and disposition.requirement_id is not None
                            and disposition.status == "EXECUTED"
                        ):
                            stages.observe_duration(
                                "evidence_slot_fts_ms",
                                disposition.latency_ms,
                            )
                    evidence_results = acquisition_execution.results
                    evidence_composition = acquisition_execution.derived_result
                    if plan.memory_query_ir is None:
                        raise AssertionError(
                            "Formation application removed the executable MemoryQueryIR"
                        )
                    acquisition_state = initialize_acquisition_state(
                        acquisition_plan,
                        plan.memory_query_ir.requirements,
                        acquisition_capability_digest=capability_set.capability_digest,
                        memory_query_ir=plan.memory_query_ir,
                        requirement_state=acquisition_execution.requirement_state,
                    )
                    progressive_l1["acquisition_state"] = acquisition_state_trace_summary(
                        acquisition_state
                    )
                    progressive_l1["semantic_audit"] = (
                        acquisition_execution.semantic_audit.model_dump(mode="json")
                        if acquisition_execution.semantic_audit is not None
                        else None
                    )
                    probe_dispositions = [
                        _public_acquisition_probe_disposition(value)
                        for value in acquisition_execution.probe_dispositions
                    ]
                    progressive_l1["acquisition_probe_dispositions"] = probe_dispositions
                    progressive_l1["candidate_counts"]["evidence_fts"] = sum(
                        value.raw_candidate_count
                        for value in acquisition_execution.probe_dispositions
                        if value.channel in {"FTS_RAW", "FTS_ENRICHED"}
                        and value.requirement_id is None
                    )
                    progressive_l1["candidate_counts"]["evidence_slot_union"] = len(
                        evidence_results
                    )
                    temporal_disposition = next(
                        (
                            value
                            for value in acquisition_execution.probe_dispositions
                            if value.channel in {"SOURCE_OBSERVED_RANGE_SCAN", "TEMPORAL_EVENT"}
                        ),
                        None,
                    )
                    if temporal_disposition is not None:
                        progressive_l1["temporal_acquisition"] = _public_temporal_acquisition_trace(
                            temporal_query_axis(plan),
                            temporal_disposition,
                        )
                        progressive_l1["candidate_counts"]["evidence_range_scan"] = (
                            temporal_disposition.selected_candidate_count
                        )
                    if any(
                        value.status == "TIMEOUT"
                        for value in acquisition_execution.probe_dispositions
                    ):
                        search_budget_exhausted = True
                        degraded.add("search_budget")
                if initial_state.evidence_dead_letter:
                    degraded.add("evidence_dead_letter")
            if access_plan is None:
                plan = plan.model_copy(
                    update={
                        "candidate_cap": candidate_limit,
                        "hard_partitions": [
                            "tenant",
                            "principal_scope",
                            "project_scope",
                            "valid_time",
                            *(["entity"] if request.entities else []),
                            *(["memory_type"] if request.memory_types else []),
                        ],
                    }
                )
            binary_anchor_queries = _binary_event_anchor_queries(plan)

            if request.consistency == "READ_YOUR_WRITES":
                assert minimum_outbox_sequence is not None
                if request.route == "L0":
                    causal_wait_outcome = "CANONICAL_L0"
                else:
                    wait_result = self._repository.wait_for_outbox_sequence(
                        context,
                        minimum_outbox_sequence,
                        request.causal_wait_timeout_ms,
                    )
                    initial_state = wait_result.state
                    causal_wait_outcome = wait_result.outcome
                    causal_waited_ms = wait_result.waited_ms

            assembled: (
                tuple[
                    list[dict[str, object]],
                    list[dict[str, object]],
                    list[dict[str, Any]],
                    list[str],
                ]
                | None
            ) = None
            derived_result: dict[str, Any] | None = None
            if request.route == "L0":
                if dimensions is not None:
                    candidate_groups.append(
                        [RetrievalCandidate(resolved_claim_version_id, 1.0, "l0")]
                        if resolved_claim_version_id is not None
                        else []
                    )
                else:
                    candidate_groups.append(
                        stages.call(
                            "l0_ms",
                            self._repository.l0_candidates,
                            context,
                            claim_id=request.claim_id,
                            subject_id=request.subject_id,
                            predicate=request.predicate,
                            claim_type=request.claim_type,
                        )
                    )
            else:
                progressive_l1["stages_attempted"].append("EXACT_FTS")
                try:
                    exact_candidates = stages.call(
                        "exact_ms",
                        self._repository.exact_candidates,
                        context,
                        query,
                        scope,
                        request.as_of,
                        candidate_limit,
                        entities=request.entities,
                        memory_types=request.memory_types,
                        statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                    )
                except DatabaseStatementTimeout:
                    exact_candidates = []
                    search_budget_exhausted = True
                candidate_groups.append(exact_candidates)
                progressive_l1["candidate_counts"]["exact"] = len(exact_candidates)
                if initial_state.fts_dead_letter:
                    degraded.add("fts_dead_letter")
                if initial_state.vector_dead_letter:
                    degraded.add("vector_dead_letter")
                fts_candidates: list[RetrievalCandidate] = []
                if not search_budget_exhausted:
                    try:
                        fts_candidates = stages.call(
                            "fts_ms",
                            self._repository.search_fts,
                            context,
                            query,
                            scope,
                            request.as_of,
                            candidate_limit,
                            entities=request.entities,
                            memory_types=request.memory_types,
                            statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                        )
                    except ProjectionUnavailable as exc:
                        degraded.add(exc.component)
                    except DatabaseStatementTimeout:
                        search_budget_exhausted = True
                candidate_groups.append(fts_candidates)
                progressive_l1["candidate_counts"]["fts"] = len(fts_candidates)
                if "fts" not in degraded and not search_budget_exhausted:
                    for anchor_query in binary_anchor_queries:
                        try:
                            anchor_candidates = stages.call(
                                "fts_ms",
                                self._repository.search_fts,
                                context,
                                anchor_query,
                                scope,
                                request.as_of,
                                candidate_limit,
                                entities=request.entities,
                                memory_types=request.memory_types,
                                statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                            )
                            candidate_groups.append(anchor_candidates)
                            progressive_l1["candidate_counts"]["fts"] += len(anchor_candidates)
                        except ProjectionUnavailable as exc:
                            degraded.add(exc.component)
                            break
                        except DatabaseStatementTimeout:
                            search_budget_exhausted = True
                            break
                if progressive_l1["enabled"]:
                    ranked, matched_by = stages.call(
                        "fusion_ms",
                        _merge_candidates,
                        candidate_groups,
                        candidate_limit,
                        source_weights=source_weights,
                    )
                    progressive_l1["candidate_counts"]["fused_fts"] = len(ranked)
                    try:
                        batch = stages.call(
                            "canonical_gate_ms",
                            self._repository.gate_and_hydrate,
                            context,
                            [candidate.claim_version_id for candidate in ranked],
                            request.required_authority,
                            scope,
                            request.as_of,
                            request.required_lifecycle,
                            request.accepted_epistemic_statuses,
                            request.required_freshness,
                            request.minimum_confidence,
                            request.system_as_of,
                            statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                        )
                    except DatabaseStatementTimeout:
                        search_budget_exhausted = True
                        batch = GatedBatch(initial_state, [], [])
                    progressive_l1["candidate_counts"]["canonical_fts"] = sum(
                        outcome.get("accepted") is True for outcome in batch.outcomes
                    )
                    preview = stages.call(
                        "result_assembly_preview_ms",
                        _assemble_results,
                        ranked,
                        matched_by,
                        batch,
                        request.limit,
                        query=request.query,
                        reference_time=request.reference_time or request.as_of,
                        plan=plan,
                        mmr_enabled=self._mmr_enabled,
                        mmr_lambda=self._mmr_lambda,
                    )
                    preview = self._decision_input_view(
                        preview,
                        presentation_context_budget,
                        progressive_l1,
                        degraded,
                        evidence_multiplier=False,
                    )
                    preview = _merge_evidence_results(preview, evidence_results, request.limit)
                    preview_derived = (
                        evidence_composition
                        if evidence_composition is not None
                        else stages.call(
                            "query_operator_preview_ms",
                            _execute_operator_with_accepted_inputs,
                            plan,
                            preview[2],
                            acquisition_execution,
                        )
                    )
                    decision_result = stages.call(
                        "sufficiency_decision_ms",
                        DEFAULT_DECISION_ENGINE.decide,
                        plan.memory_query_ir,
                        (
                            acquisition_execution.candidates
                            if acquisition_execution is not None
                            else ()
                        ),
                        preview[2],
                        (
                            acquisition_execution.spans
                            if acquisition_execution is not None
                            else ()
                        ),
                        (
                            acquisition_execution.interpretations
                            if acquisition_execution is not None
                            else ()
                        ),
                        (
                            acquisition_execution.bindings
                            if acquisition_execution is not None
                            else ()
                        ),
                        preview_derived,
                        None,
                        request=request,
                        plan=plan,
                        open_issue_ids=preview[3],
                        stage="FTS",
                        mode=lean_decision_mode(plan),
                    )
                    decision, reason = (
                        decision_result.sufficiency_decision,
                        decision_result.reason_code,
                    )
                    sufficient = _record_sufficiency_decision(
                        progressive_l1,
                        stage="FTS",
                        decision=decision,
                        reason=reason,
                    )
                    reader_available = _stage_memory_available(plan, preview)
                    progressive_l1["sufficiency_reason"] = reason
                    if capture_matched_replay and _contains_evidence_observation(preview[2]):
                        legacy_progressive = deepcopy(progressive_l1)
                        legacy_progressive["stop_stage"] = "EVIDENCE_FTS"
                        legacy_progressive["sufficiency_reason"] = "LEGACY_ANY_EVIDENCE_STOP"
                        legacy_progressive["terminal_sufficiency_decision"] = decision.payload()
                        legacy_progressive["matched_replay_policy_override"] = {
                            "policy": "DG16_ANY_EVIDENCE_STOP",
                            "trigger": "EVIDENCE_OBSERVATION_PRESENT",
                            "typed_decision_preserved": True,
                            "canonical_mutation": False,
                        }
                        legacy_replay_prefix = _LegacyReplayPrefix(
                            assembled=deepcopy(preview),
                            derived_result=deepcopy(preview_derived),
                            progressive_l1=legacy_progressive,
                            degraded=set(degraded),
                            fallback_used=fallback_used,
                            fallback_reason=fallback_reason,
                            stage_metrics=_stage_metrics(stages, started),
                            stage_sequence=stages.sequence(),
                        )
                    if sufficient or reader_available:
                        assembled = preview
                        derived_result = preview_derived
                        progressive_l1["stop_stage"] = "EVIDENCE_FTS" if evidence_results else "FTS"
                        stages.increment("progressive_l1_fts_stop")
                    elif access_plan is not None:
                        progressive_l1["escalation_reasons"].append(f"FTS_INSUFFICIENT:{reason}")
                if access_plan is not None and (
                    search_budget_exhausted or _deadline_exhausted(access_plan, started)
                ):
                    search_budget_exhausted = True
                    degraded.add("search_budget")
                    progressive_l1["deadline_outcome"] = "EXHAUSTED"
                    if assembled is None:
                        assembled = preview
                        derived_result = preview_derived
                        progressive_l1["stop_stage"] = "BUDGET"
                        progressive_l1["sufficiency_reason"] = "SEARCH_DEADLINE_EXHAUSTED"
                        budget_decision = budget_exhausted_decision()
                        _record_sufficiency_decision(
                            progressive_l1,
                            stage="BUDGET",
                            decision=budget_decision,
                            reason="SEARCH_DEADLINE_EXHAUSTED",
                            terminal=True,
                        )
                        stages.increment("progressive_l1_budget_stop")

                if assembled is None and not search_budget_exhausted:
                    progressive_l1["stages_attempted"].append("VECTOR")
                    try:
                        query_embedding = stages.call(
                            "query_embedding_ms", self._embedding.embed, query
                        )
                        candidate_groups.append(
                            stages.call(
                                "vector_ms",
                                self._repository.search_vector,
                                context,
                                query_embedding,
                                scope,
                                request.as_of,
                                candidate_limit,
                                entities=request.entities,
                                memory_types=request.memory_types,
                                model_id=self._embedding.identity.model_id,
                                projection_version=self._embedding.identity.key,
                                statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                            )
                        )
                        vector_candidates = candidate_groups[-1]
                        progressive_l1["candidate_counts"]["vector"] = len(vector_candidates)
                    except (ProjectionUnavailable, EmbeddingUnavailable) as exc:
                        degraded.add(
                            exc.component if isinstance(exc, ProjectionUnavailable) else "vector"
                        )
                        progressive_l1["candidate_counts"]["vector"] = 0
                    except DatabaseStatementTimeout:
                        search_budget_exhausted = True
                        degraded.add("search_budget")
                        progressive_l1["candidate_counts"]["vector"] = 0
                        progressive_l1["deadline_outcome"] = "EXHAUSTED"

                    if recent_enabled and access_plan is None:
                        candidate_groups.append(
                            stages.call(
                                "recent_canonical_ms",
                                self._repository.recent_canonical_candidates,
                                context,
                                query,
                                scope,
                                request.as_of,
                                candidate_limit,
                                entities=request.entities,
                                memory_types=request.memory_types,
                            )
                        )

                    if causal_wait_outcome in {"TIMEOUT", "DEAD_LETTER"}:
                        try:
                            canonical_candidates = stages.call(
                                "canonical_fallback_ms",
                                self._repository.canonical_search,
                                context,
                                query,
                                scope,
                                request.as_of,
                                candidate_limit,
                                entities=request.entities,
                                memory_types=request.memory_types,
                                statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                            )
                        except DatabaseStatementTimeout:
                            search_budget_exhausted = True
                            degraded.add("search_budget")
                        else:
                            candidate_groups.append(canonical_candidates)
                            fallback_used = True
                            fallback_reason = (
                                "CAUSAL_WAIT_TIMEOUT"
                                if causal_wait_outcome == "TIMEOUT"
                                else "CAUSAL_DEAD_LETTER"
                            )

                    all_search_unavailable = {"fts", "vector"}.issubset(degraded)
                    if all_search_unavailable and not fallback_used:
                        try:
                            canonical_candidates = stages.call(
                                "canonical_fallback_ms",
                                self._repository.canonical_search,
                                context,
                                query,
                                scope,
                                request.as_of,
                                candidate_limit,
                                entities=request.entities,
                                memory_types=request.memory_types,
                                statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                            )
                        except DatabaseStatementTimeout:
                            search_budget_exhausted = True
                            degraded.add("search_budget")
                        else:
                            candidate_groups.append(canonical_candidates)
                            fallback_used = True
                            fallback_reason = "PROJECTION_UNAVAILABLE"

            if request.route == "L0" or assembled is None:
                ranked, matched_by = stages.call(
                    "fusion_ms",
                    _merge_candidates,
                    candidate_groups,
                    candidate_limit,
                    source_weights=source_weights,
                )
                if request.route == "L1":
                    progressive_l1["candidate_counts"]["fused_total"] = len(ranked)
                try:
                    batch = stages.call(
                        "canonical_gate_ms",
                        self._repository.gate_and_hydrate,
                        context,
                        [candidate.claim_version_id for candidate in ranked],
                        request.required_authority,
                        scope,
                        request.as_of,
                        request.required_lifecycle,
                        request.accepted_epistemic_statuses,
                        request.required_freshness,
                        request.minimum_confidence,
                        request.system_as_of,
                        allow_historical=allow_historical,
                        statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                    )
                except DatabaseStatementTimeout:
                    search_budget_exhausted = True
                    degraded.add("search_budget")
                    assert initial_state is not None
                    batch = GatedBatch(initial_state, [], [])
                if request.route == "L1":
                    progressive_l1["candidate_counts"]["canonical_total"] = sum(
                        outcome.get("accepted") is True for outcome in batch.outcomes
                    )

            if (
                request.route == "L1"
                and request.consistency == "READ_YOUR_WRITES"
                and not fallback_used
                and batch.projection_state.canonical_snapshot_outbox_sequence
                > initial_state.canonical_snapshot_outbox_sequence
            ):
                try:
                    canonical_candidates = stages.call(
                        "canonical_fallback_ms",
                        self._repository.canonical_search,
                        context,
                        request.query or "",
                        scope,
                        request.as_of,
                        candidate_limit,
                        entities=request.entities,
                        memory_types=request.memory_types,
                        statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                    )
                except DatabaseStatementTimeout:
                    search_budget_exhausted = True
                    degraded.add("search_budget")
                    canonical_candidates = []
                candidate_groups.append(canonical_candidates)
                fallback_used = True
                fallback_reason = "SNAPSHOT_ADVANCED"
                ranked, matched_by = stages.call(
                    "fusion_ms",
                    _merge_candidates,
                    candidate_groups,
                    candidate_limit,
                    source_weights=source_weights,
                )
                try:
                    batch = stages.call(
                        "canonical_gate_ms",
                        self._repository.gate_and_hydrate,
                        context,
                        [candidate.claim_version_id for candidate in ranked],
                        request.required_authority,
                        scope,
                        request.as_of,
                        request.required_lifecycle,
                        request.accepted_epistemic_statuses,
                        request.required_freshness,
                        request.minimum_confidence,
                        request.system_as_of,
                        allow_historical=allow_historical,
                        statement_timeout_ms=_remaining_timeout_ms(access_plan, started),
                    )
                except DatabaseStatementTimeout:
                    search_budget_exhausted = True
                    degraded.add("search_budget")
                    assert initial_state is not None
                    batch = GatedBatch(initial_state, [], [])

            if assembled is None and progressive_l1["enabled"]:
                preview = stages.call(
                    "result_assembly_preview_ms",
                    _assemble_results,
                    ranked,
                    matched_by,
                    batch,
                    request.limit,
                    query=request.query,
                    reference_time=request.reference_time or request.as_of,
                    plan=plan,
                    mmr_enabled=self._mmr_enabled,
                    mmr_lambda=self._mmr_lambda,
                )
                preview = self._decision_input_view(
                    preview,
                    presentation_context_budget,
                    progressive_l1,
                    degraded,
                    evidence_multiplier=False,
                )
                preview = _merge_evidence_results(preview, evidence_results, request.limit)
                preview_derived = (
                    evidence_composition
                    if evidence_composition is not None
                    else stages.call(
                        "query_operator_preview_ms",
                        _execute_operator_with_accepted_inputs,
                        plan,
                        preview[2],
                        acquisition_execution,
                    )
                )
                decision_result = stages.call(
                    "sufficiency_decision_ms",
                    DEFAULT_DECISION_ENGINE.decide,
                    plan.memory_query_ir,
                    (
                        acquisition_execution.candidates
                        if acquisition_execution is not None
                        else ()
                    ),
                    preview[2],
                    (
                        acquisition_execution.spans
                        if acquisition_execution is not None
                        else ()
                    ),
                    (
                        acquisition_execution.interpretations
                        if acquisition_execution is not None
                        else ()
                    ),
                    (
                        acquisition_execution.bindings
                        if acquisition_execution is not None
                        else ()
                    ),
                    preview_derived,
                    None,
                    request=request,
                    plan=plan,
                    open_issue_ids=preview[3],
                    stage="VECTOR",
                    mode=lean_decision_mode(plan),
                )
                decision, reason = (
                    decision_result.sufficiency_decision,
                    decision_result.reason_code,
                )
                sufficient = _record_sufficiency_decision(
                    progressive_l1,
                    stage="VECTOR",
                    decision=decision,
                    reason=reason,
                )
                reader_available = _stage_memory_available(plan, preview)
                progressive_l1["sufficiency_reason"] = reason
                if sufficient or reader_available:
                    assembled = preview
                    derived_result = preview_derived
                    progressive_l1["stop_stage"] = "VECTOR"
                    stages.increment("progressive_l1_vector_stop")
                elif access_plan is not None:
                    progressive_l1["escalation_reasons"].append(f"VECTOR_INSUFFICIENT:{reason}")
                if access_plan is not None and (
                    search_budget_exhausted or _deadline_exhausted(access_plan, started)
                ):
                    degraded.add("search_budget")
                    progressive_l1["deadline_outcome"] = "EXHAUSTED"
                    if assembled is None:
                        assembled = preview
                        derived_result = preview_derived
                        progressive_l1["stop_stage"] = "BUDGET"
                        progressive_l1["sufficiency_reason"] = "SEARCH_DEADLINE_EXHAUSTED"
                        budget_decision = budget_exhausted_decision()
                        _record_sufficiency_decision(
                            progressive_l1,
                            stage="BUDGET",
                            decision=budget_decision,
                            reason="SEARCH_DEADLINE_EXHAUSTED",
                            terminal=True,
                        )
                        stages.increment("progressive_l1_budget_stop")

            if assembled is None:
                selected_reranker = (
                    self._reranker
                    if _should_rerank(
                        request,
                        plan,
                        batch,
                        access_plan,
                        deadline_exhausted=(
                            access_plan is not None and _deadline_exhausted(access_plan, started)
                        ),
                    )
                    else None
                )
                if selected_reranker is not None:
                    progressive_l1["stages_attempted"].append("RERANKER")
                    progressive_l1["candidate_counts"]["reranker_input"] = min(
                        sum(outcome.get("accepted") is True for outcome in batch.outcomes),
                        plan.reranker_candidate_cap,
                    )
                try:
                    assembled = stages.call(
                        "reranker_ms" if selected_reranker is not None else "result_assembly_ms",
                        _assemble_results,
                        ranked,
                        matched_by,
                        batch,
                        request.limit,
                        query=request.query,
                        reference_time=request.reference_time or request.as_of,
                        plan=plan,
                        mmr_enabled=self._mmr_enabled and request.route == "L1",
                        mmr_lambda=self._mmr_lambda,
                        reranker=selected_reranker,
                        reranker_pool_size=min(
                            self._reranker_pool_size, plan.reranker_candidate_cap
                        ),
                        temporal_reranker_pool_size=min(
                            self._temporal_reranker_pool_size,
                            plan.reranker_candidate_cap,
                        ),
                    )
                    if selected_reranker is not None and progressive_l1["enabled"]:
                        progressive_l1["candidate_counts"]["reranker_output"] = len(assembled[2])
                        progressive_l1["stop_stage"] = "RERANKER"
                        progressive_l1["sufficiency_reason"] = "FULL_PIPELINE_COMPLETED"
                        stages.increment("progressive_l1_reranker_stop")
                except RerankerUnavailable:
                    degraded.add("reranker")
                    fallback_used = True
                    fallback_reason = fallback_reason or "RERANKER_UNAVAILABLE"
                    assembled = stages.call(
                        "result_assembly_ms",
                        _assemble_results,
                        ranked,
                        matched_by,
                        batch,
                        request.limit,
                        query=request.query,
                        reference_time=request.reference_time or request.as_of,
                        plan=plan,
                        mmr_enabled=self._mmr_enabled and request.route == "L1",
                        mmr_lambda=self._mmr_lambda,
                    )
                assembled = _merge_evidence_results(assembled, evidence_results, request.limit)
                derived_result = (
                    evidence_composition
                    if _use_acquisition_composition(plan, evidence_composition)
                    else stages.call(
                        "query_operator_ms",
                        _execute_operator_with_accepted_inputs,
                        plan,
                        assembled[2],
                        acquisition_execution,
                    )
                )
            assembled = self._decision_input_view(
                assembled,
                presentation_context_budget,
                progressive_l1,
                degraded,
                evidence_multiplier=True,
            )
            accepted, rejected, results, open_issue_ids = assembled
            if dimensions is not None:
                dimensions["correctly_resolved"] = bool(results) or any(
                    outcome.get("reject_reason") == "OPEN_ISSUE" for outcome in rejected
                )
            final_result = stages.call(
                "sufficiency_decision_ms",
                DEFAULT_DECISION_ENGINE.decide,
                plan.memory_query_ir,
                acquisition_execution.candidates if acquisition_execution is not None else (),
                results,
                acquisition_execution.spans if acquisition_execution is not None else (),
                acquisition_execution.interpretations if acquisition_execution is not None else (),
                acquisition_execution.bindings if acquisition_execution is not None else (),
                derived_result,
                (
                    acquisition_execution.bounded_range_scan_proof
                    if acquisition_execution is not None
                    and getattr(
                        acquisition_execution.bounded_range_scan_proof,
                        "schema_version",
                        None,
                    )
                    == "bounded-range-scan-proof-v0.2"
                    else None
                ),
                request=request,
                plan=plan,
                open_issue_ids=open_issue_ids,
                requirement_state=(
                    acquisition_execution.requirement_state
                    if acquisition_execution is not None
                    else None
                ),
                stage="FINAL",
                mode=lean_decision_mode(plan),
            )
            final_decision = final_result.sufficiency_decision
            final_sufficiency_reason = final_result.reason_code
            _record_sufficiency_decision(
                progressive_l1,
                stage="FINAL",
                decision=final_decision,
                reason=final_sufficiency_reason,
                terminal=progressive_l1["stop_stage"] != "BUDGET",
            )
            if acquisition_plan is not None and acquisition_state is not None:
                deterministic_action = build_acquisition_action(
                    action_kind="DETERMINISTIC_PASS",
                    pass_index=0,
                    requirement_ids=acquisition_state.missing_requirement_ids,
                    probe_ids=[probe.probe_id for probe in acquisition_plan.probes],
                )
                acquisition_candidates = _acquisition_candidate_envelopes(evidence_results)
                acquisition_bindings, acquisition_notes = (
                    _acquisition_reference_material(
                        evidence_results,
                        plan.memory_query_ir.requirements,
                        execution=acquisition_execution,
                    )
                    if plan.memory_query_ir is not None
                    else ([], [])
                )
                aligned_requirement_state = (
                    resolve_requirement_state(
                        plan=acquisition_plan,
                        requirements=plan.memory_query_ir.requirements,
                        acquisition_capability_digest=(
                            acquisition_state.requirement_state.acquisition_capability_digest
                        ),
                        candidates=acquisition_candidates,
                        spans=(
                            acquisition_execution.spans if acquisition_execution is not None else ()
                        ),
                        interpretations=(
                            acquisition_execution.interpretations
                            if acquisition_execution is not None
                            else ()
                        ),
                        bindings=acquisition_bindings,
                        sufficiency_decision=final_decision,
                        state_epoch=acquisition_state.requirement_state.state_epoch,
                        memory_query_ir=plan.memory_query_ir,
                        accepted_evidence_overrides={
                            requirement_id: [
                                note.evidence_id
                                for note in acquisition_notes
                                if note.requirement_id == requirement_id
                            ]
                            for requirement_id in acquisition_state.required_requirement_ids
                        },
                    )
                    if plan.memory_query_ir is not None
                    else acquisition_state.requirement_state
                )
                elapsed_acquisition_ms = (perf_counter() - started) * 1_000
                transition = advance_acquisition_state(
                    acquisition_state,
                    deterministic_action,
                    candidates=acquisition_candidates,
                    bindings=acquisition_bindings,
                    notes=acquisition_notes,
                    sufficiency_decision=final_decision,
                    requirement_state=aligned_requirement_state,
                    budget_use=AcquisitionBudgetUse(
                        candidate_count=len(acquisition_candidates),
                        context_tokens=min(
                            int(progressive_l1["context_token_upper_bound"]),
                            acquisition_state.remaining_budget.context_tokens,
                        ),
                        latency_ms=min(
                            elapsed_acquisition_ms,
                            acquisition_state.remaining_budget.latency_ms,
                        ),
                    ),
                )
                acquisition_state = transition.state
                progressive_l1["acquisition_state_transition"] = {
                    "outcome": transition.outcome,
                    "reason_code": transition.reason_code,
                    "repeated_anchor_count": transition.repeated_anchor_count,
                    "repeated_window_count": transition.repeated_window_count,
                    "canonical_mutation": transition.canonical_mutation,
                }
                progressive_l1["acquisition_state"] = acquisition_state_trace_summary(
                    acquisition_state
                )
            # A canonical state selector can remain semantically PARTIAL while
            # still yielding governed lookup memory.  Preserve the existing
            # abstention behavior for every other incomplete derived/strict
            # operation.
            canonical_lookup_ready = (
                request.memory_intent == "CURRENT_STATE"
                and lean_decision_mode(plan) == "ORDINARY_RECALL"
                and plan.operator == "LATEST_VALID_STATE"
                and any(item.get("claim_version_id") is not None for item in results)
            )
            operator_abstained = (
                (
                    plan.operator is not None
                    or derived_result is not None
                    or (
                        plan.memory_query_ir is not None
                        and infer_operator_family(plan.memory_query_ir) != "LOOKUP"
                    )
                )
                and not final_decision.complete
                and not canonical_lookup_ready
            )
            abstained = not results or operator_abstained
            abstention_reason = None
            if abstained:
                if operator_abstained:
                    abstention_reason = (
                        f"OPERATOR_{derived_result.get('reason', 'INCOMPLETE')}"
                        if derived_result is not None
                        else (f"SUFFICIENCY_{final_decision.status}_{final_decision.stop_reason}")
                    )
                else:
                    reject_reasons = {str(value.get("reject_reason")) for value in rejected}
                    if request.route == "L0" and reject_reasons.intersection(
                        {"PERMISSION_DENIED", "SCOPE_MISMATCH"}
                    ):
                        abstention_reason = "ACCESS_DENIED"
                    elif search_budget_exhausted:
                        abstention_reason = "SEARCH_BUDGET_EXHAUSTED"
                    elif progressive_l1["context_budget_truncated"]:
                        abstention_reason = "CONTEXT_TOKEN_BUDGET_EXCEEDED"
                    else:
                        abstention_reason = "CANONICAL_GATE_REJECTED" if ranked else "NO_CANDIDATE"
            duration_ms = max(0, int((perf_counter() - started) * 1_000))
            if access_plan is not None and progressive_l1["deadline_outcome"] == "PENDING":
                progressive_l1["deadline_outcome"] = (
                    "EXHAUSTED" if duration_ms > access_plan.deadline_ms else "MET"
                )
                if progressive_l1["deadline_outcome"] == "EXHAUSTED":
                    degraded.add("search_budget")
            progressive_l1["observed_runtime_ms"] = duration_ms
            if capture_matched_replay and initial_state != batch.projection_state:
                raise MatchedReplayInvariantError("projection state changed during matched replay")
            persisted_stage_metrics = _stage_metrics(stages, started)
            execution_trace = _execution_trace(
                request=request,
                plan=plan,
                stage_sequence=stages.sequence(),
                progressive_l1=progressive_l1,
                fallback_reason=fallback_reason,
                abstention_reason=abstention_reason,
                result_count=len(results),
                resolution_dimensions=dimensions,
            )
            trace_id = stages.call(
                "trace_write_ms",
                self._repository.record_trace,
                context,
                RetrievalTraceCommand(
                    request_id=request_id,
                    route=cast(Literal["L0", "L1"], plan.complexity),
                    consistency=plan.consistency_mode,
                    query_fingerprint=fingerprint,
                    query_plan=payload_free_query_plan(plan),
                    requested_scope=scope,
                    as_of=request.as_of,
                    required_authority=request.required_authority,
                    canonical_snapshot=(batch.projection_state.canonical_snapshot_outbox_sequence),
                    fts_watermark=batch.projection_state.fts_watermark,
                    vector_watermark=batch.projection_state.vector_watermark,
                    accepted=accepted,
                    rejected=rejected,
                    fallback_used=fallback_used,
                    fallback_reason=fallback_reason,
                    abstained=abstained,
                    abstention_reason=abstention_reason,
                    duration_ms=duration_ms,
                    minimum_outbox_sequence=minimum_outbox_sequence,
                    causal_wait_outcome=causal_wait_outcome,
                    causal_waited_ms=causal_waited_ms,
                    execution_trace=execution_trace,
                    stage_metrics=cast(dict[str, object], persisted_stage_metrics),
                ),
            )
            access_trace = _access_trace_view(
                trace_id=trace_id,
                request_id=request_id,
                canonical_position=batch.projection_state.canonical_snapshot_outbox_sequence,
                execution_trace=execution_trace,
                stage_metrics=persisted_stage_metrics,
            )
            response_body = _response_body(
                plan=plan,
                results=results,
                open_issue_ids=open_issue_ids,
                trace_id=trace_id,
                state=batch.projection_state,
                degraded=degraded,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                abstained=abstained,
                abstention_reason=abstention_reason,
                minimum_outbox_sequence=minimum_outbox_sequence,
                causal_wait_outcome=causal_wait_outcome,
                causal_waited_ms=causal_waited_ms,
                derived_result=derived_result,
                stage_metrics=_stage_metrics(stages, started),
                progressive_l1=progressive_l1,
                access_trace=access_trace,
            )
            decision_snapshot = _decision_snapshot(
                plan=plan,
                projection_state=batch.projection_state,
                acquisition_plan=acquisition_plan,
                acquisition_execution=acquisition_execution,
                acquisition_state=acquisition_state,
                accepted=accepted,
                rejected=rejected,
                results=results,
                final_decision=final_decision,
                derived_result=derived_result,
                defer_digests=(
                    defer_decision_snapshot
                    and self._retrieval_audit_observer is None
                    and not capture_matched_replay
                ),
            )
            if self._retrieval_audit_observer is not None:
                self._retrieval_audit_observer.capture_product_execution(
                    request=request,
                    query_plan=plan,
                    acquisition_plan=acquisition_plan,
                    acquisition_execution=(
                        materialize_acquisition_execution(acquisition_execution)
                        if acquisition_execution is not None else None
                    ),
                    accepted=accepted,
                    rejected=rejected,
                    results=results,
                    final_decision=final_decision,
                    derived_result=derived_result,
                    decision_snapshot=materialize_decision_snapshot(decision_snapshot),
                    progressive_l1=progressive_l1,
                    stage_sequence=stages.sequence(),
                )
            matched_replay = (
                _build_matched_retrieval_replay(
                    request=request,
                    plan=plan,
                    request_id=request_id,
                    query_fingerprint=fingerprint,
                    state=batch.projection_state,
                    trace_id=trace_id,
                    current_body=response_body,
                    legacy_prefix=legacy_replay_prefix,
                    minimum_outbox_sequence=minimum_outbox_sequence,
                    causal_wait_outcome=causal_wait_outcome,
                    causal_waited_ms=causal_waited_ms,
                )
                if capture_matched_replay
                else None
            )
            return RetrievalExecution(
                response_body,
                matched_replay=matched_replay,
                decision_snapshot=decision_snapshot,
                context_candidate_items=tuple(
                    deepcopy(item)
                    for item in (
                        acquisition_execution.results
                        if acquisition_execution is not None
                        else results
                    )
                ),
            )
        except DatabaseUnavailable:
            unavailable = unavailable_decision()
            _record_sufficiency_decision(
                progressive_l1,
                stage="CANONICAL_STORE",
                decision=unavailable,
                reason="CANONICAL_UNAVAILABLE",
                terminal=True,
            )
            return RetrievalExecution(
                _response_body(
                    plan=plan,
                    results=[],
                    open_issue_ids=[],
                    trace_id=None,
                    state=initial_state,
                    degraded=degraded | {"canonical_database"},
                    fallback_used=fallback_used,
                    fallback_reason=fallback_reason,
                    abstained=True,
                    abstention_reason="CANONICAL_UNAVAILABLE",
                    minimum_outbox_sequence=minimum_outbox_sequence,
                    causal_wait_outcome=causal_wait_outcome,
                    causal_waited_ms=causal_waited_ms,
                    derived_result=None,
                    stage_metrics=_stage_metrics(stages, started),
                    progressive_l1=progressive_l1,
                    access_trace=_unavailable_access_trace(
                        request=request,
                        plan=plan,
                        request_id=request_id,
                        stage_sequence=stages.sequence(),
                        fallback_reason=fallback_reason,
                        stage_metrics=_stage_metrics(stages, started),
                        resolution_dimensions=dimensions,
                    ),
                ),
                status_code=503,
            )

    def _decision_input_view(
        self,
        assembled: _AssembledResults,
        presentation_budget: int,
        progressive_l1: dict[str, Any],
        degraded: set[str],
        *,
        evidence_multiplier: bool,
    ) -> _AssembledResults:
        """Preserve legacy filtering only while the DG-23 candidate is disabled."""

        if self._budget_stable_context_enabled:
            return assembled
        legacy_budget = presentation_budget
        if evidence_multiplier and any(
            result.get("kind") == "EVIDENCE_OBSERVATION" for result in assembled[2]
        ):
            legacy_budget = min(32_000, presentation_budget * 4)
        return _apply_context_budget(
            assembled,
            legacy_budget,
            progressive_l1,
            degraded,
        )

    def get_trace(self, context: SessionContext, trace_id: UUID) -> dict[str, Any] | None:
        trace = self._repository.get_trace(context, trace_id)
        if trace is None:
            return None
        query_plan = trace.get("query_plan")
        if isinstance(query_plan, Mapping):
            # Older experimental rows may predate the payload-free write
            # projection. Never re-expose their query-derived planner fields.
            trace["query_plan"] = payload_free_query_plan(query_plan)
        execution_trace = trace.get("execution_trace")
        stage_metrics = trace.get("stage_metrics")
        if isinstance(execution_trace, dict) and isinstance(stage_metrics, dict):
            trace["access_trace"] = _access_trace_view(
                trace_id=trace_id,
                request_id=str(trace["request_id"]),
                canonical_position=int(trace["canonical_snapshot_outbox_sequence"]),
                execution_trace=cast(dict[str, object], execution_trace),
                stage_metrics=stage_metrics,
            )
        return trace

    def system_status(self, context: SessionContext) -> dict[str, Any]:
        state = self._repository.projection_state(context)
        snapshot = state.canonical_snapshot_outbox_sequence
        embedding_state = str(getattr(self._embedding, "runtime_state", "READY"))
        vector_degraded = state.vector_dead_letter or embedding_state == "DEGRADED"
        return {
            "canonical_snapshot": snapshot,
            "watermarks": [
                {
                    "projection": "evidence",
                    "watermark": state.evidence_watermark,
                    "lag": max(0, snapshot - state.evidence_watermark),
                    "dead_letter": state.evidence_dead_letter,
                },
                {
                    "projection": "fts",
                    "watermark": state.fts_watermark,
                    "lag": max(0, snapshot - state.fts_watermark),
                    "dead_letter": state.fts_dead_letter,
                },
                {
                    "projection": "vector",
                    "watermark": state.vector_watermark,
                    "lag": max(0, snapshot - state.vector_watermark),
                    "dead_letter": state.vector_dead_letter,
                },
            ],
            "routes": {
                "L0": {"enabled": True, "degraded": False},
                "L1": {
                    "enabled": True,
                    "degraded": state.fts_dead_letter or vector_degraded,
                    "components": {
                        "fts": "DEAD_LETTER" if state.fts_dead_letter else "AVAILABLE",
                        "vector": (
                            "DEAD_LETTER"
                            if state.vector_dead_letter
                            else ("DEGRADED" if vector_degraded else "AVAILABLE")
                        ),
                    },
                },
                "L2": {"enabled": False, "degraded": False, "reason": "ROUTE_DISABLED"},
            },
        }


def _fingerprint(tenant_id: UUID, request: RetrievalRequest) -> str:
    canonical = request.model_dump(mode="json", exclude_none=False)
    canonical["authenticated_tenant_id"] = str(tenant_id)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _should_rerank(
    request: RetrievalRequest,
    plan: QueryPlan,
    batch: GatedBatch,
    access_plan: MemoryAccessPlan | None,
    *,
    deadline_exhausted: bool,
) -> bool:
    if request.route != "L1" or request.limit != 3 or deadline_exhausted:
        return False
    if access_plan is None:
        return True
    if access_plan.reranker_candidate_cap == 0:
        return False
    accepted_count = sum(outcome.get("accepted") is True for outcome in batch.outcomes)
    return request.limit < accepted_count <= access_plan.reranker_candidate_cap


def _record_sufficiency_decision(
    progressive_l1: dict[str, Any],
    *,
    stage: str,
    decision: SufficiencyDecision,
    reason: str,
    terminal: bool = False,
) -> bool:
    payload = decision.payload()
    progressive_l1["sufficiency_checks"].append(
        {"stage": stage, "sufficient": decision.complete, "reason": reason}
    )
    progressive_l1["sufficiency_decisions"].append(
        {"stage": stage, "diagnostic_reason": reason, "decision": payload}
    )
    if terminal:
        progressive_l1["terminal_sufficiency_decision"] = payload
    return decision.complete


def _stage_memory_available(
    plan: QueryPlan,
    assembled: tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, Any]],
        list[str],
    ],
) -> bool:
    """Stop acquisition on usable memory without claiming semantic completion."""

    results, open_issue_ids = assembled[2], assembled[3]
    if not results or open_issue_ids:
        return False
    if lean_decision_mode(plan) == "ORDINARY_RECALL":
        return True
    contract = plan.query_task_contract
    return (
        contract is not None
        and contract.evidence_topology == "SINGLE_ITEM"
        and any(item.get("claim_version_id") is not None for item in results)
    )
