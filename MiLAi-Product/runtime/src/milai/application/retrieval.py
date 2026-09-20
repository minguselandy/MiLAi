from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
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
    DeferredEvidenceAcquisitionExecution,
    EvidenceAcquisitionExecutionRef,
    EvidenceAcquisitionExecutor,
    materialize_acquisition_execution,
)
from milai.application.evidence_source import evidence_source_turn_identity
from milai.application.formation_projection import (
    FormationProjectionMode,
    FormationProjectionStore,
)
from milai.application.formation_semantic_replay import (
    ground_formation_semantics,
    specialize_formation_replay_plan,
)
from milai.application.lean_recall import compile_lean_recall_plan, lean_decision_mode
from milai.application.memory_access import (
    ACQUISITION_DECISION_CONTEXT_CEILING,
    MemoryAccessPlan,
)
from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_operators import (
    execute_binding_backed_query_operator,
    execute_query_operator,
)
from milai.application.query_planner import QueryPlanner, payload_free_query_plan
from milai.application.reader_evidence_plan import (
    DecisionSnapshotRef,
    build_decision_snapshot,
    materialize_decision_snapshot,
)
from milai.application.recollection import (
    MatchedReplayInvariantError,
    MatchedReplayPolicy,
    MatchedRetrievalReplay,
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
from milai.application.retrieval_core.candidates import (
    _deduplicate_evidence,  # noqa: F401 - compatibility import
    _diversify_evidence_by_subject,  # noqa: F401 - compatibility import
    _merge_candidates,
    _rank_evidence_turns,  # noqa: F401 - compatibility import
    _result_identity,  # noqa: F401 - compatibility import
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
    _mmr_select,
    _mmr_tokens,  # noqa: F401 - compatibility import
    _set_cover_text,  # noqa: F401 - compatibility import
    _set_cover_tokens,  # noqa: F401 - compatibility import
    _weighted_set_cover_select,  # noqa: F401 - compatibility import
)
from milai.application.retrieval_core.temporal import (
    _binary_anchor_cover,
    _binary_event_anchor_queries,
    _binary_event_anchor_terms,
    _intent_tokens,  # noqa: F401 - compatibility import
    _relative_event_dates,  # noqa: F401 - compatibility import
    _relative_event_distance,  # noqa: F401 - compatibility import
    _relative_event_intent_overlap,  # noqa: F401 - compatibility import
    _relative_point_cover,
    _relative_point_target,
    _relative_target,  # noqa: F401 - compatibility import
    _rerank_by_reference,  # noqa: F401 - compatibility import
    _temporal_rerank,
    _temporal_subject_indices,  # noqa: F401 - compatibility import
    _temporal_text,
    _temporal_timestamp,
    _temporal_tokens,
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
from milai.domain.lean_recall import (
    EvidenceSet,
    EvidenceSetItem,
    LeanRecallPlan,
    RetrievalOccurrence,
)
from milai.domain.reader_evidence_plan import AcceptedBindingSpan
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    EvidenceSpan,
    MemoryQueryIRV02,
)
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

_STATE_COUNT_VALUE = re.compile(
    r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"\d+(?:,\d{3})*)(?!\w)",
    re.IGNORECASE,
)
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
class _LegacyReplayPrefix:
    assembled: _AssembledResults
    derived_result: dict[str, Any] | None
    progressive_l1: dict[str, Any]
    degraded: set[str]
    fallback_used: bool
    fallback_reason: str | None
    stage_metrics: dict[str, Any]
    stage_sequence: tuple[str, ...]


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


_COMPOUND_IDENTIFIER = re.compile(
    r"(?<![\w-])[^\W_]+(?:-[^\W_]+)+(?![\w-])",
    re.UNICODE,
)


def _explicit_compound_subject_matches(
    query: str,
    claim: Mapping[str, Any],
) -> bool:
    """Reject a shorter canonical subject hidden inside a named compound.

    Token search intentionally decomposes identifiers so that ordinary recall
    remains forgiving.  Once both the query and a canonical Claim carry a
    compound identifier, however, the full identifier is an explicit address:
    ``outside-orchid-release`` must not resolve ``orchid-release`` merely
    because all of the shorter subject's words occur inside it.
    """

    subject = claim.get("subject_id")
    if not isinstance(subject, str) or "-" not in subject:
        return True
    explicit = {
        match.group(0).casefold()
        for match in _COMPOUND_IDENTIFIER.finditer(query)
    }
    normalized_subject = subject.casefold()
    if normalized_subject in explicit:
        return True
    return not any(
        identifier.startswith(f"{normalized_subject}-")
        or identifier.endswith(f"-{normalized_subject}")
        or f"-{normalized_subject}-" in identifier
        for identifier in explicit
    )


def _state_count_cover(
    candidates: list[dict[str, Any]], query: str, limit: int
) -> list[dict[str, Any]]:
    """Keep the newest strong scalar-state evidence in the visible Top-k.

    Cross-encoders favor verbose lexical matches and can rank an older value
    above a terse update.  We still let the reranker bound the candidate set,
    then reserve one slot for the newest candidate whose numeric line has
    nearly the best query-term coverage.
    """
    if limit <= 0 or not candidates:
        return []
    query_tokens = _temporal_tokens(query)
    evidence: list[tuple[int, datetime, int]] = []
    for index, candidate in enumerate(candidates):
        timestamp = _temporal_timestamp(candidate)
        if timestamp is None:
            continue
        text = _temporal_text(candidate)
        best_overlap = max(
            (
                len(query_tokens.intersection(_temporal_tokens(line)))
                for line in text.splitlines()
                if _STATE_COUNT_VALUE.search(line) is not None
                and not re.match(r"^\s*assistant:\s*\d+\.\s*$", line, re.IGNORECASE)
            ),
            default=0,
        )
        if best_overlap > 0:
            evidence.append((best_overlap, timestamp, index))
    if not evidence:
        return candidates[:limit]
    best_overlap = max(item[0] for item in evidence)
    minimum_overlap = max(1, best_overlap - 1)
    eligible = [item for item in evidence if item[0] >= minimum_overlap]
    _overlap, _timestamp, selected_index = max(
        eligible, key=lambda item: (item[1], item[0], -item[2])
    )
    priority = [selected_index]
    priority.extend(index for index in range(len(candidates)) if index != selected_index)
    return [candidates[index] for index in priority[:limit]]


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


def _execute_operator_with_accepted_inputs(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    execution: EvidenceAcquisitionExecutionRef | None,
) -> dict[str, Any] | None:
    canonical_results = [
        item for item in results if item.get("claim_version_id") is not None
    ]
    if lean_decision_mode(plan) == "ORDINARY_RECALL":
        if not canonical_results:
            # Raw natural language remains Reader context.  QueryIR planning
            # cannot promote it to a deterministic operand merely because a
            # lexical or model interpretation matched the question.
            return None
        canonical_result = execute_query_operator(plan, canonical_results)
        if canonical_result is None:
            return None
        return {
            **canonical_result,
            "operand_authority": "CANONICAL_GATE_ONLY",
        }
    if execution is None:
        return execute_binding_backed_query_operator(
            plan,
            results,
            (),
            (),
            (),
        )
    return execute_binding_backed_query_operator(
        plan,
        results,
        execution.spans,
        execution.interpretations,
        execution.bindings,
    )


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


def _operator_support_refs(
    derived_result: Mapping[str, Any] | None,
) -> tuple[set[str], set[str]]:
    """Collect only explicit operator provenance, never arbitrary string values."""

    evidence_ids: set[str] = set()
    source_refs: set[str] = set()

    def collect(value: Mapping[str, Any]) -> None:
        for key in (
            "evidence_id",
            "source_evidence_id",
        ):
            raw = value.get(key)
            if isinstance(raw, str) and raw:
                evidence_ids.add(raw)
        for key in (
            "evidence_ids",
            "evidence_refs",
            "source_evidence_ids",
        ):
            raw = value.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                evidence_ids.update(item for item in raw if isinstance(item, str) and item)
        for key in ("source_ref", "source_turn_ref"):
            raw = value.get(key)
            if isinstance(raw, str) and raw:
                source_refs.add(raw)
        for key in ("source_refs", "source_turn_refs"):
            raw = value.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                source_refs.update(item for item in raw if isinstance(item, str) and item)
        operands = value.get("operands")
        if isinstance(operands, Sequence) and not isinstance(operands, (str, bytes)):
            for operand in operands:
                if isinstance(operand, Mapping):
                    collect(operand)

    if derived_result is not None and derived_result.get("canonical_mutation") is not True:
        collect(derived_result)
    return evidence_ids, source_refs


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


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_matched_retrieval_replay(
    *,
    request: RetrievalRequest,
    plan: QueryPlan,
    request_id: str,
    query_fingerprint: str,
    state: ProjectionState,
    trace_id: UUID,
    current_body: dict[str, Any],
    legacy_prefix: _LegacyReplayPrefix | None,
    minimum_outbox_sequence: int | None,
    causal_wait_outcome: str | None,
    causal_waited_ms: int,
) -> MatchedRetrievalReplay:
    evidence_snapshot = {
        "schema_version": "runtime-evidence-snapshot-v0.1",
        "projection_state": _projection_state_payload(state),
        "start_end_projection_identity_equal": True,
        "capture_mode": "ONE_RETRIEVAL_EXECUTION_PREFIX_REPLAY",
    }
    snapshot_digest = _canonical_sha256(evidence_snapshot)
    current = deepcopy(current_body)
    legacy_early_stop = legacy_prefix is not None
    if legacy_prefix is None:
        legacy = deepcopy(current_body)
    else:
        accepted, _rejected, results, open_issue_ids = legacy_prefix.assembled
        legacy_execution_trace = _execution_trace(
            request=request,
            plan=plan,
            stage_sequence=legacy_prefix.stage_sequence,
            progressive_l1=legacy_prefix.progressive_l1,
            fallback_reason=legacy_prefix.fallback_reason,
            abstention_reason=None,
            result_count=len(results),
        )
        legacy_access_trace = _access_trace_view(
            trace_id=trace_id,
            request_id=request_id,
            canonical_position=state.canonical_snapshot_outbox_sequence,
            execution_trace=legacy_execution_trace,
            stage_metrics=legacy_prefix.stage_metrics,
        )
        legacy_access_trace["matched_replay_view"] = True
        legacy_access_trace["shared_execution_trace_id"] = str(trace_id)
        legacy = _response_body(
            plan=plan,
            results=deepcopy(results),
            open_issue_ids=deepcopy(open_issue_ids),
            trace_id=trace_id,
            state=state,
            degraded=set(legacy_prefix.degraded),
            fallback_used=legacy_prefix.fallback_used,
            fallback_reason=legacy_prefix.fallback_reason,
            abstained=not bool(results),
            abstention_reason=None if results else "NO_CANDIDATE",
            minimum_outbox_sequence=minimum_outbox_sequence,
            causal_wait_outcome=causal_wait_outcome,
            causal_waited_ms=causal_waited_ms,
            derived_result=deepcopy(legacy_prefix.derived_result),
            stage_metrics=deepcopy(legacy_prefix.stage_metrics),
            progressive_l1=deepcopy(legacy_prefix.progressive_l1),
            access_trace=legacy_access_trace,
        )
        # The accepted prefix is deliberately retained only as replay metadata;
        # it is not persisted as a second RetrievalTrace or canonical outcome.
        legacy["matched_replay_accepted_count"] = len(accepted)
    policy_bodies: dict[MatchedReplayPolicy, dict[str, Any]] = {
        "DG16_ANY_EVIDENCE_STOP": legacy,
        "DG17_QUERY_SPECIFIC_STOP": current,
    }
    policy_metadata: dict[MatchedReplayPolicy, dict[str, Any]] = {
        "DG16_ANY_EVIDENCE_STOP": {
            "policy": "DG16_ANY_EVIDENCE_STOP",
            "early_stop_applied": legacy_early_stop,
            "stop_trigger": (
                "EVIDENCE_OBSERVATION_PRESENT"
                if legacy_early_stop
                else "NO_EVIDENCE_PREFIX_USE_CURRENT_OUTCOME"
            ),
            "typed_sufficiency_preserved": True,
            "fresh_retrieval_calls": 0,
        },
        "DG17_QUERY_SPECIFIC_STOP": {
            "policy": "DG17_QUERY_SPECIFIC_STOP",
            "early_stop_applied": False,
            "stop_trigger": "QUERY_SPECIFIC_SUFFICIENCY",
            "typed_sufficiency_preserved": True,
            "fresh_retrieval_calls": 1,
        },
    }
    shared = {
        "query_fingerprint": query_fingerprint,
        "retrieval_trace_id": str(trace_id),
        "retrieval_execution_count": 1,
        "evidence_snapshot_digest": snapshot_digest,
        "canonical_mutation": False,
    }
    for metadata in policy_metadata.values():
        metadata["shared_execution"] = dict(shared)
    return MatchedRetrievalReplay(
        schema_version="matched-retrieval-replay-v0.1",
        evidence_snapshot=evidence_snapshot,
        evidence_snapshot_digest=snapshot_digest,
        policy_bodies=policy_bodies,
        policy_metadata=policy_metadata,
    )


def _stage_metrics(stages: OperationTimer, started: float) -> dict[str, Any]:
    snapshot = stages.snapshot()
    elapsed_ms = (perf_counter() - started) * 1_000
    measured_stage_ms = sum(snapshot["durations_ms"].values())
    snapshot["durations_ms"]["query_total_ms"] = round(max(elapsed_ms, measured_stage_ms), 3)
    snapshot["counts"]["query_total_ms"] = 1
    return snapshot


def _public_acquisition_probe_disposition(value: Any) -> dict[str, Any]:
    """Keep the stable progressive trace while retaining the internal typed reason."""

    payload = cast(dict[str, Any], value.model_dump(mode="json"))
    payload["candidate_count"] = value.selected_candidate_count
    if value.reason_code in {
        "EVENT_TIME_FILTER_UNAVAILABLE",
        "SOURCE_TIME_FILTER_UNAVAILABLE",
    }:
        payload["status"] = value.reason_code
    return payload


def _public_temporal_acquisition_trace(
    query_axis: str,
    disposition: Any,
) -> dict[str, Any]:
    reason = str(disposition.reason_code)
    if disposition.channel == "TEMPORAL_EVENT" and reason in {
        "EVENT_PROJECTION_NOT_READY",
        "EVENT_PROJECTION_UNAVAILABLE",
    }:
        return {
            "query_axis": query_axis,
            "scan_axis": "CANDIDATE_SET",
            "disposition": "EVENT_PROJECTION_UNAVAILABLE",
        }
    return {
        "query_axis": query_axis,
        "scan_axis": (
            "SOURCE_OBSERVED_TIME"
            if disposition.channel == "SOURCE_OBSERVED_RANGE_SCAN"
            else "EVENT_OCCURRENCE_TIME"
        ),
        "disposition": reason,
    }


_EXECUTION_STAGE_BY_OPERATION = {
    "l0_ms": "EXACT",
    "state_address_resolution_ms": "EXACT",
    "evidence_fts_ms": "EVIDENCE_FTS",
    "evidence_slot_fts_ms": "EVIDENCE_FTS",
    "evidence_range_scan_ms": "EVIDENCE_RANGE_SCAN",
    "evidence_composition_ms": "COMPOSITION",
    "exact_ms": "EXACT",
    "fts_ms": "FTS",
    "vector_ms": "VECTOR",
    "recent_canonical_ms": "CANONICAL_FALLBACK",
    "canonical_fallback_ms": "CANONICAL_FALLBACK",
    "canonical_gate_ms": "CANONICAL_GATE",
    "result_assembly_preview_ms": "HYDRATE",
    "result_assembly_ms": "HYDRATE",
    "reranker_ms": "RERANKER",
    "query_operator_preview_ms": "SUFFICIENCY",
    "query_operator_ms": "SUFFICIENCY",
    "sufficiency_decision_ms": "SUFFICIENCY",
}


def _abstract_stage_sequence(operations: tuple[str, ...]) -> list[str]:
    stages: list[str] = []
    for operation in operations:
        stage = _EXECUTION_STAGE_BY_OPERATION.get(operation)
        if stage is not None and (not stages or stages[-1] != stage):
            stages.append(stage)
    return stages


def _execution_trace(
    *,
    request: RetrievalRequest,
    plan: QueryPlan,
    stage_sequence: tuple[str, ...],
    progressive_l1: dict[str, Any],
    fallback_reason: str | None,
    abstention_reason: str | None,
    result_count: int,
    resolution_dimensions: dict[str, bool] | None = None,
) -> dict[str, object]:
    attempted_stages = _abstract_stage_sequence(stage_sequence)
    progressive_stop = progressive_l1.get("stop_stage")
    if abstention_reason is not None:
        terminal_stage = (
            "SUFFICIENCY" if abstention_reason.startswith("OPERATOR_") else "CANONICAL_GATE"
        )
        stop_reason = abstention_reason
    elif isinstance(progressive_stop, str):
        terminal_stage = progressive_stop
        stop_reason = str(
            progressive_l1.get("sufficiency_reason") or "PROGRESSIVE_STOP_CONDITION_MET"
        )
    elif request.route == "L0":
        terminal_stage = "EXACT"
        stop_reason = "CANONICAL_EXACT_RESULT_RESOLVED"
    elif fallback_reason is not None and "CANONICAL_FALLBACK" in attempted_stages:
        terminal_stage = "CANONICAL_FALLBACK"
        stop_reason = fallback_reason
    else:
        terminal_stage = next(
            (
                stage
                for stage in reversed(attempted_stages)
                if stage in {"RERANKER", "VECTOR", "FTS", "EXACT", "CANONICAL_FALLBACK"}
            ),
            "CANONICAL_GATE",
        )
        stop_reason = "CANONICAL_RESULTS_RESOLVED"
    trace: dict[str, object] = {
        "schema_version": "retrieval-execution-v1",
        "requested_intent": request.memory_intent,
        "planned_stage": "EXACT" if plan.complexity == "L0" else "SEARCH",
        "attempted_stages": attempted_stages,
        "terminal_stage": terminal_stage,
        "stop_reason": stop_reason,
        "fallback_reason": fallback_reason,
        "result_count": result_count,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "sufficiency_decision": progressive_l1.get("terminal_sufficiency_decision"),
    }
    if resolution_dimensions is not None:
        trace["resolution_dimensions"] = dict(resolution_dimensions)
    acquisition_state = progressive_l1.get("acquisition_state")
    if isinstance(acquisition_state, dict):
        trace["acquisition_state"] = dict(acquisition_state)
    return trace


def _latency_spans(stage_metrics: dict[str, Any]) -> dict[str, float | None]:
    raw_durations = stage_metrics.get("durations_ms")
    durations = raw_durations if isinstance(raw_durations, dict) else {}

    def duration(name: str) -> float:
        value = durations.get(name, 0.0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    sql_operations = (
        "projection_state_ms",
        "l0_ms",
        "state_address_resolution_ms",
        "exact_ms",
        "fts_ms",
        "vector_ms",
        "recent_canonical_ms",
        "canonical_fallback_ms",
        "canonical_gate_ms",
    )
    return {
        "mcp_decode_ms": None,
        "broker_ipc_ms": None,
        "state_address_ms": duration("state_address_resolution_ms"),
        "runtime_kernel_ms": duration("query_total_ms"),
        "formation_selection_ms": duration("formation_selection_ms"),
        "formation_hydration_ms": duration("formation_hydration_ms"),
        "repository_sql_ms": round(sum(duration(name) for name in sql_operations), 3),
        "rerank_ms": duration("reranker_ms"),
        "hydrate_ms": round(
            duration("result_assembly_preview_ms") + duration("result_assembly_ms"), 3
        ),
        "host_total_ms": None,
    }


def _structural_cost(stage_metrics: dict[str, Any]) -> dict[str, int]:
    raw_counts = stage_metrics.get("counts")
    counts = raw_counts if isinstance(raw_counts, dict) else {}

    def count(name: str) -> int:
        value = counts.get(name, 0)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    return {
        "auxiliary_llm_calls": 0,
        "embedding_calls": count("query_embedding_ms"),
        "vector_search_calls": count("vector_ms"),
        "reranker_calls": count("reranker_ms"),
        "broad_head_scan_calls": count("canonical_fallback_ms"),
    }


def _access_trace_view(
    *,
    trace_id: UUID,
    request_id: str,
    canonical_position: int,
    execution_trace: dict[str, object],
    stage_metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "access-trace-v0.1",
        "retrieval_trace_id": str(trace_id),
        "runtime_request_id": request_id,
        "requested_intent": execution_trace.get("requested_intent"),
        "planned_stage": execution_trace.get("planned_stage"),
        "attempted_stages": execution_trace.get("attempted_stages", []),
        "terminal_stage": execution_trace.get("terminal_stage"),
        "stop_reason": execution_trace.get("stop_reason"),
        "fallback_reason": execution_trace.get("fallback_reason"),
        "canonical_position": canonical_position,
        "spans": _latency_spans(stage_metrics),
        "structural_cost": _structural_cost(stage_metrics),
        "resolution_dimensions": execution_trace.get("resolution_dimensions"),
        "route_trace_complete": execution_trace.get("route_trace_complete") is True,
        "trace_gap_reason": execution_trace.get("trace_gap_reason"),
        "sufficiency_decision": execution_trace.get("sufficiency_decision"),
        "acquisition_state": execution_trace.get("acquisition_state"),
    }


def _unavailable_access_trace(
    *,
    request: RetrievalRequest,
    plan: QueryPlan,
    request_id: str,
    stage_sequence: tuple[str, ...],
    fallback_reason: str | None,
    stage_metrics: dict[str, Any],
    resolution_dimensions: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "access-trace-v0.1",
        "retrieval_trace_id": None,
        "runtime_request_id": request_id,
        "requested_intent": request.memory_intent,
        "planned_stage": "EXACT" if plan.complexity == "L0" else "SEARCH",
        "attempted_stages": _abstract_stage_sequence(stage_sequence),
        "terminal_stage": "CANONICAL_STORE",
        "stop_reason": "CANONICAL_UNAVAILABLE",
        "fallback_reason": fallback_reason,
        "canonical_position": None,
        "spans": _latency_spans(stage_metrics),
        "structural_cost": _structural_cost(stage_metrics),
        "resolution_dimensions": resolution_dimensions,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "sufficiency_decision": unavailable_decision().payload(),
    }
