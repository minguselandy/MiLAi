"""Single official executor for product and no-context-mutation shadow acquisition."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from milai.adapters import (
    DeterministicHashEmbedding,
    EmbeddingProvider,
    EmbeddingUnavailable,
)
from milai.application.acquisition import (
    _probe_ranking_speakers,
    additive_union_v0_2_enabled,
    apply_probe_source_policy,
    fuse_acquisition_probe_results,
    probe_query,
    query_preserving_union_enabled,
    rank_evidence_turns,
)
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    executable_closed_open_range,
    validate_feasible_action,
)
from milai.application.appointment_composition import (
    compose_evidence_range_count,
    normalize_query_time_event_scan,
    prioritize_temporal_evidence,
    temporal_query_axis,
    temporal_range,
)
from milai.application.deferred_raw_semantics import DeferredRawSemantics
from milai.application.evidence_dense import evidence_turn_projection_version
from milai.application.evidence_semantics import (
    bind_requirements,
    deduplicate_projected_spans,
    evidence_source_eligible,
    interpret_evidence_spans,
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.evidence_source import (
    structured_evidence_identity,
    structured_evidence_speaker,
)
from milai.application.formation_semantic_replay import GroundedFormationSemantics
from milai.application.lean_recall import lean_decision_mode
from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.application.preference_composition import (
    prioritize_preference_evidence,
    synthesize_preference_evidence_view,
)
from milai.application.prepared_evidence_spans import PreparedEvidenceSpans
from milai.application.quantity_composition import (
    compose_divide_evidence_values,
    prioritize_composition_evidence,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_operators import (
    build_accepted_operator_inputs,
    execute_binding_backed_query_operator,
    execute_query_operator,
)
from milai.application.requirement_state import resolve_requirement_state
from milai.application.sufficiency import build_intermediate_sufficiency_proof
from milai.domain.acquisition import (
    AcquisitionPlan,
    AcquisitionProbe,
    CandidateEnvelope,
)
from milai.domain.acquisition_capability import (
    AcquisitionCapabilityName,
    AcquisitionCapabilitySet,
    FeasibleAcquisitionAction,
)
from milai.domain.acquisition_execution_policy import AcquisitionExecutionSelection
from milai.domain.requirement_acquisition import (
    RequirementAcquisitionPlanV01,
    RequirementAcquisitionPlanValidationV01,
    RequirementCompleteRetrievalPolicyV01,
    validate_requirement_acquisition_plan,
)
from milai.domain.requirement_state import RequirementState, canonical_sha256
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    MemoryQueryIRV02,
    RequirementBinding,
    TypeDirectedSemanticAudit,
)
from milai.domain.sufficiency import SufficiencyDecision
from milai.domain.temporal_proof import (
    BoundedRangeAccessClosureV02,
    BoundedRangeDedupClosureV02,
    BoundedRangeEventSetClosureV02,
    BoundedRangeProjectionClosureV02,
    BoundedRangeQueryClosureV02,
    BoundedRangeScanClosureV02,
    BoundedRangeScanProofV02,
    BoundedRangeSnapshotClosureV02,
    build_bounded_range_scan_proof_v02,
    build_event_time_interval_v02,
)
from milai.persistence import DatabaseStatementTimeout, SessionContext
from milai.persistence.retrieval_repository import ProjectionUnavailable

EvidenceAcquisitionMode = Literal["PRODUCT", "SHADOW_NO_CONTEXT_MUTATION"]
OFFICIAL_EXECUTOR_IDENTITY: Literal["milai-evidence-acquisition-executor-v0.1"] = (
    "milai-evidence-acquisition-executor-v0.1"
)


class AcquisitionProbeDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_id: str
    requirement_id: str | None = None
    channel: AcquisitionCapabilityName
    status: str
    reason_code: str
    raw_candidate_count: int = Field(ge=0)
    selected_candidate_count: int = Field(ge=0)
    excluded_seen_candidate_count: int = Field(default=0, ge=0)
    repeated_region_count: int = Field(default=0, ge=0)
    new_region_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(ge=0)


class AcquisitionProbeCandidateTrace(BaseModel):
    """Ordered pre-fusion candidates and their official cutoff disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_id: str
    requirement_id: str | None = None
    channel: AcquisitionCapabilityName
    candidate_limit: int = Field(ge=1)
    raw_candidate_ids: list[str]
    raw_source_refs: list[str]
    fusion_surviving_candidate_ids: list[str]
    fusion_surviving_source_refs: list[str]


class EvidenceAcquisitionFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-acquisition-execution-v0.1"] = (
        "evidence-acquisition-execution-v0.1"
    )
    executor_identity: Literal["milai-evidence-acquisition-executor-v0.1"] = (
        OFFICIAL_EXECUTOR_IDENTITY
    )
    mode: EvidenceAcquisitionMode
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    results: list[dict[str, Any]]
    candidates: list[CandidateEnvelope]
    requirement_state: RequirementState
    sufficiency_decision: SufficiencyDecision
    sufficiency_reason: str
    derived_result: dict[str, Any] | None = None
    bounded_range_scan_proof: BoundedRangeScanProofV02 | None = None
    probe_dispositions: list[AcquisitionProbeDisposition]
    probe_candidate_traces: list[AcquisitionProbeCandidateTrace]
    type_directed_semantics: bool = False
    semantic_audit: TypeDirectedSemanticAudit | None = None
    context_mutation_performed: Literal[False] = False
    canonical_mutation: Literal[False] = False


class EvidenceAcquisitionExecution(EvidenceAcquisitionFacts):
    spans: list[EvidenceSpan]
    interpretations: list[EvidenceInterpretationCandidate]
    bindings: list[RequirementBinding]
    candidate_requirement_attribution: dict[str, dict[str, int]]


class DeferredEvidenceAcquisitionExecution:
    """Internal work reference; serialization always produces the complete DTO."""

    def __init__(
        self, facts: EvidenceAcquisitionFacts, semantics: DeferredRawSemantics,
        requirements: Sequence[EvidenceRequirementV02],
    ) -> None:
        self._facts = facts
        self.semantics = semantics
        self._requirements = deepcopy(list(requirements))
        self._execution: EvidenceAcquisitionExecution | None = None
        self._lock = Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._facts, name)

    @property
    def spans(self) -> Sequence[EvidenceSpan]:
        return self.semantics.spans

    @property
    def interpretations(self) -> Sequence[EvidenceInterpretationCandidate]:
        return self.semantics.interpretations

    @property
    def bindings(self) -> Sequence[RequirementBinding]:
        return self.semantics.bindings

    def materialize(self) -> EvidenceAcquisitionExecution:
        with self._lock:
            if self._execution is None:
                interpretations, bindings = self.semantics.materialize()
                self._execution = EvidenceAcquisitionExecution(
                    **self._facts.model_dump(), spans=list(self.spans),
                    interpretations=interpretations, bindings=bindings,
                    candidate_requirement_attribution=_candidate_requirement_attribution(
                        self._requirements, bindings, interpretations, self.spans,
                    ),
                )
            return self._execution

    @property
    def candidate_requirement_attribution(self) -> dict[str, dict[str, int]]:
        return self.materialize().candidate_requirement_attribution

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return self.materialize().model_dump(**kwargs)

    def model_copy(self, **kwargs: Any) -> EvidenceAcquisitionExecution:
        return self.materialize().model_copy(**kwargs)


EvidenceAcquisitionExecutionRef = (
    EvidenceAcquisitionExecution | DeferredEvidenceAcquisitionExecution
)


def materialize_acquisition_execution(
    execution: EvidenceAcquisitionExecutionRef,
) -> EvidenceAcquisitionExecution:
    return (
        execution.materialize()
        if isinstance(execution, DeferredEvidenceAcquisitionExecution)
        else execution
    )


class RequirementAcquisitionPlanExecutionV01(BaseModel):
    """Lineage wrapper for one validated official batch execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["requirement-acquisition-plan-execution-v0.1"] = (
        "requirement-acquisition-plan-execution-v0.1"
    )
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation: RequirementAcquisitionPlanValidationV01
    executed_action_digests: list[str] = Field(min_length=1, max_length=2)
    repository_probe_calls: int = Field(ge=1, le=2)
    planned_candidate_cap_sum: int = Field(ge=1, le=120)
    initial_requirement_state_epoch: int = Field(ge=0)
    final_requirement_state_epoch: int = Field(ge=1)
    full_semantics_recomputations: Literal[1] = 1
    execution: EvidenceAcquisitionExecution
    provider_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    context_mutation_performed: Literal[False] = False
    canonical_mutation: Literal[False] = False


class EvidenceAcquisitionExecutor:
    """Execute governed Evidence acquisition once under a digest-bound capability set."""

    def __init__(
        self,
        repository: object,
        embedding: EmbeddingProvider | None = None,
    ) -> None:
        self._repository = repository
        self._embedding = embedding or DeterministicHashEmbedding()

    def execute(
        self,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        capability_set: AcquisitionCapabilitySet,
        policy: AcquisitionCapabilityPolicy,
        mode: EvidenceAcquisitionMode,
        state_epoch: int,
        action: FeasibleAcquisitionAction | None = None,
        current_requirement_state: RequirementState | None = None,
        existing_results: Sequence[Mapping[str, Any]] = (),
        type_directed_semantics: bool = False,
        execution_selection: AcquisitionExecutionSelection | None = None,
        defer_semantics: bool = False,
    ) -> EvidenceAcquisitionExecutionRef:
        if query_plan.memory_query_ir is None:
            raise ValueError("official Evidence acquisition requires MemoryQueryIR")
        if action is not None:
            if current_requirement_state is None:
                raise ValueError("CURRENT_REQUIREMENT_STATE_REQUIRED")
            validation = validate_feasible_action(
                action,
                current_requirement_state,
                capability_set,
                policy,
            )
            if not validation.accepted:
                raise ValueError(validation.reason_code)
        if execution_selection is not None:
            _validate_execution_selection(execution_selection, action)
        selected_probes = self._selected_probes(
            acquisition_plan,
            action,
            capability_set,
            execution_selection,
        )
        if (
            action is not None
            and action.channel in {"FTS_RAW", "FTS_ENRICHED", "EVIDENCE_DENSE"}
            and not selected_probes
        ):
            raise ValueError("ACTION_NOT_REPRESENTED_IN_ACQUISITION_PLAN")
        results: list[dict[str, Any]] = [dict(item) for item in existing_results]
        selected_probe_ids = {probe.probe_id for probe in selected_probes}
        dispositions: list[AcquisitionProbeDisposition] = (
            self._capability_skip_dispositions(
                acquisition_plan,
                capability_set,
                selected_probe_ids,
            )
            if action is None
            else []
        )
        range_scan: dict[str, Any] | None = None
        probe_results: list[tuple[AcquisitionProbe, list[dict[str, Any]]]] = []
        fused_probe_results: list[dict[str, Any]] = []
        ranking_features: dict[tuple[str, str], tuple[int, bool]] = {}
        for probe in selected_probes:
            started = perf_counter()
            raw_items, status, reason = self._execute_probe(
                probe,
                context=context,
                request=request,
                acquisition_plan=acquisition_plan,
                ranking_features=ranking_features,
            )
            items, repeated = _exclude_seen_candidates(
                raw_items,
                existing_results,
            )
            probe_results.append((probe, items))
            dispositions.append(
                AcquisitionProbeDisposition(
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
            )
        if selected_probes:
            selected_plan = _selected_plan(acquisition_plan, selected_probes)
            fused = fuse_acquisition_probe_results(selected_plan, probe_results)
            fused_probe_results = fused
            results = _deduplicate([*results, *fused])

        if action is None and _same_session_expansion_planned(selected_probes):
            extra, disposition = self._execute_planned_local_expansion(
                context=context,
                request=request,
                acquisition_plan=acquisition_plan,
                capability_set=capability_set,
                existing_results=results,
            )
            extra, repeated = _exclude_seen_candidates(extra, results)
            disposition = disposition.model_copy(
                update={
                    "selected_candidate_count": len(extra),
                    "excluded_seen_candidate_count": repeated,
                    "repeated_region_count": repeated,
                    "new_region_count": len(extra),
                }
            )
            results = (
                _query_preserving_locality_order(results, extra)
                if query_preserving_union_enabled(acquisition_plan)
                else _deduplicate([*results, *extra])
            )
            dispositions.append(disposition)

        if action is not None and action.channel in {
            "SOURCE_OBSERVED_RANGE_SCAN",
            "ADJACENT_TURNS",
            "SAME_EPISODE",
            "TEMPORAL_EVENT",
        }:
            extra, disposition, range_scan = self._execute_structural_action(
                action,
                context=context,
                request=request,
                query_plan=query_plan,
                acquisition_plan=acquisition_plan,
                existing_results=results,
                execution_selection=execution_selection,
            )
            extra, repeated = _exclude_seen_candidates(extra, results)
            disposition = disposition.model_copy(
                update={
                    "selected_candidate_count": len(extra),
                    "excluded_seen_candidate_count": repeated,
                    "repeated_region_count": repeated,
                    "new_region_count": len(extra),
                }
            )
            results = _deduplicate([*results, *extra])
            dispositions.append(disposition)
        elif action is None:
            extra, planned_disposition, range_scan = self._execute_planned_range(
                context=context,
                request=request,
                query_plan=query_plan,
                acquisition_plan=acquisition_plan,
            )
            if planned_disposition is not None:
                results = _deduplicate([*extra, *results])
                dispositions.append(planned_disposition)

        return self.compile_existing_results(
            request=request,
            query_plan=query_plan,
            acquisition_plan=acquisition_plan,
            capability_set=capability_set,
            mode=mode,
            state_epoch=state_epoch,
            results=results,
            action_digest=action.action_digest if action is not None else None,
            range_scan=range_scan,
            probe_dispositions=dispositions,
            probe_candidate_traces=_probe_candidate_traces(
                probe_results,
                fused_probe_results,
            ),
            type_directed_semantics=type_directed_semantics,
            defer_semantics=defer_semantics,
        )

    def _execute_planned_local_expansion(
        self,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        acquisition_plan: AcquisitionPlan,
        capability_set: AcquisitionCapabilitySet,
        existing_results: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], AcquisitionProbeDisposition]:
        """Hydrate bounded same-session locality inside initial acquisition."""

        started = perf_counter()
        capability = capability_set.capability("ADJACENT_TURNS")
        remaining = max(0, acquisition_plan.budget.hydrate_count - len(existing_results))
        simple_union = query_preserving_union_enabled(acquisition_plan)
        anchor_rows = _structured_adjacency_anchors(
            existing_results,
            max_anchors=24 if simple_union else 2,
            distinct_sessions=simple_union,
        )
        anchors = [str(item["evidence_id"]) for item in anchor_rows]
        method = getattr(self._repository, "hydrate_evidence_adjacency", None)
        items: list[dict[str, Any]] = []
        raw_count = 0
        status: str = capability.status
        reason = capability.reason
        if remaining < 1:
            status, reason = "DISABLED", "SHARED_HYDRATION_BUDGET_EXHAUSTED"
        elif not anchors:
            status, reason = "UNAVAILABLE", "NO_VALID_ANCHOR"
        elif capability.executable and callable(method):
            if simple_union:
                # Walk toward the beginning of each high-ranked real session.
                # Each hop returns at most the same-round partner and one
                # previous-round turn.  The walk is round-robin across at
                # most 24 sessions and stops exactly at the shared hydration
                # budget (normally 120 units after 40 direct candidates).
                frontiers = [dict(item) for item in anchor_rows]
                collected: list[dict[str, Any]] = []
                for _depth in range(4):
                    next_frontiers: list[dict[str, Any]] = []
                    for frontier in frontiers:
                        per_call = min(2, remaining - raw_count)
                        evidence_id = frontier.get("evidence_id")
                        if per_call < 1 or not isinstance(evidence_id, str):
                            continue
                        raw = method(
                            context,
                            anchor_evidence_ids=[evidence_id],
                            requested_scope=dict(request.requested_scope),
                            as_of=request.as_of,
                            max_items=per_call,
                        )
                        raw_count += (
                            len(raw)
                            if isinstance(raw, Sequence)
                            and not isinstance(raw, (str, bytes))
                            else 0
                        )
                        governed = _governed_adjacent_items(
                            raw,
                            anchors=[frontier],
                            requested_scope=request.requested_scope,
                            radius=1,
                            max_items=per_call,
                            strict=True,
                        )
                        collected.extend(governed)
                        previous = _previous_round_frontier(frontier, governed)
                        if previous is not None:
                            next_frontiers.append(previous)
                    if not next_frontiers or raw_count >= remaining:
                        break
                    frontiers = next_frontiers
                items = _deduplicate(collected)[:remaining]
                status, reason = "EXECUTED", "SAME_SESSION_LANDMARK_WALK"
            else:
                max_items = min(4, remaining)
                raw = method(
                    context,
                    anchor_evidence_ids=anchors,
                    requested_scope=dict(request.requested_scope),
                    as_of=request.as_of,
                    max_items=max_items,
                )
                raw_count = (
                    len(raw)
                    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes))
                    else 0
                )
                items = _governed_adjacent_items(
                    raw,
                    anchors=anchor_rows,
                    requested_scope=request.requested_scope,
                    radius=2,
                    max_items=max_items,
                    strict=True,
                )
                status, reason = "EXECUTED", "SAME_SESSION_BOUNDED"
        requirement_ids = _anchor_requirement_ids(anchor_rows)
        hydrated = _envelope_structural_items(
            items,
            channel="ADJACENT_TURNS",
            requirement_ids=requirement_ids,
        )
        return (
            hydrated,
            AcquisitionProbeDisposition(
                probe_id="planned:same-session-local-expansion",
                channel="ADJACENT_TURNS",
                status=status,
                reason_code=reason,
                raw_candidate_count=raw_count,
                selected_candidate_count=len(hydrated),
                latency_ms=round((perf_counter() - started) * 1_000, 6),
            ),
        )

    def execute_plan(
        self,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        requirement_acquisition_plan: RequirementAcquisitionPlanV01,
        capability_set: AcquisitionCapabilitySet,
        capability_policy: AcquisitionCapabilityPolicy,
        requirement_policy: RequirementCompleteRetrievalPolicyV01,
        current_requirement_state: RequirementState,
        feasible_actions: Sequence[FeasibleAcquisitionAction],
        current_snapshot_identity: str,
        current_access_snapshot_identity: str,
        mode: EvidenceAcquisitionMode,
        existing_results: Sequence[Mapping[str, Any]] = (),
        type_directed_semantics: bool = False,
        execution_selections: Mapping[str, AcquisitionExecutionSelection] | None = None,
        baseline_candidate_caps: Mapping[str, int] | None = None,
    ) -> RequirementAcquisitionPlanExecutionV01:
        """Validate, execute, union, and recompute one predeclared batch.

        All freshness, membership, probe-shape, and aggregate-budget checks
        finish before the first repository call. No action can be added after
        execution begins.
        """

        if query_plan.memory_query_ir is None:
            raise ValueError("official Evidence acquisition requires MemoryQueryIR")
        if acquisition_plan.query_ir_digest != requirement_acquisition_plan.lineage.query_ir_digest:
            raise ValueError("STALE_ACQUISITION_PLAN:QUERY_IR_DIGEST_MISMATCH")
        validation = validate_requirement_acquisition_plan(
            requirement_acquisition_plan,
            requirement_state=current_requirement_state,
            feasible_actions=feasible_actions,
            policy=requirement_policy,
            current_snapshot_identity=current_snapshot_identity,
            current_access_snapshot_identity=current_access_snapshot_identity,
            baseline_candidate_caps=baseline_candidate_caps,
        )
        if not validation.accepted:
            raise ValueError("STALE_ACQUISITION_PLAN:" + ",".join(validation.reason_codes))
        if len(requirement_acquisition_plan.actions) > 2:
            raise ValueError("DG25_REVIEWED_ACTION_BUDGET_EXCEEDED")

        feasible_by_digest = _unique_feasible_actions(feasible_actions)
        selections = dict(execution_selections or {})
        plan_digests = {item.action_digest for item in requirement_acquisition_plan.actions}
        if set(selections) - plan_digests:
            raise ValueError("UNREGISTERED_EXECUTION_SELECTION")

        execution_actions: list[FeasibleAcquisitionAction] = []
        probes_by_action: dict[str, list[AcquisitionProbe]] = {}
        structural_actions: list[FeasibleAcquisitionAction] = []
        repository_probe_calls = 0
        for planned in requirement_acquisition_plan.actions:
            action = feasible_by_digest[planned.action_digest]
            action_validation = validate_feasible_action(
                action,
                current_requirement_state,
                capability_set,
                capability_policy,
            )
            if not action_validation.accepted:
                raise ValueError("STALE_ACQUISITION_PLAN:" + action_validation.reason_code)
            selection = selections.get(action.action_digest)
            if selection is not None:
                _validate_execution_selection(selection, action)
            probes = self._selected_probes(
                acquisition_plan,
                action,
                capability_set,
                selection,
            )
            if action.channel in {"FTS_RAW", "FTS_ENRICHED", "EVIDENCE_DENSE"}:
                if len(probes) != 1:
                    raise ValueError("ACTION_REPOSITORY_CALL_BUDGET_MISMATCH")
                probes_by_action[action.action_digest] = probes
                repository_probe_calls += 1
            else:
                if action.channel == "SAME_EPISODE":
                    raise ValueError("SAME_EPISODE_EXECUTOR_NOT_IMPLEMENTED")
                structural_actions.append(action)
                repository_probe_calls += 1
            execution_actions.append(action)

        if len(structural_actions) > 1:
            raise ValueError("MULTIPLE_STRUCTURAL_ACTIONS_UNSUPPORTED")
        if repository_probe_calls != (
            requirement_acquisition_plan.aggregate_budget.planned_repository_calls
        ):
            raise ValueError("PLAN_REPOSITORY_CALL_BUDGET_MISMATCH")

        next_epoch = current_requirement_state.state_epoch + 1
        if len(execution_actions) == 1:
            action = execution_actions[0]
            execution = self.execute(
                context=context,
                request=request,
                query_plan=query_plan,
                acquisition_plan=acquisition_plan,
                capability_set=capability_set,
                policy=capability_policy,
                mode=mode,
                state_epoch=next_epoch,
                action=action,
                current_requirement_state=current_requirement_state,
                existing_results=existing_results,
                type_directed_semantics=type_directed_semantics,
                execution_selection=selections.get(action.action_digest),
            )
            return _plan_execution(
                requirement_acquisition_plan,
                validation=validation,
                execution_actions=execution_actions,
                repository_probe_calls=repository_probe_calls,
                initial_epoch=current_requirement_state.state_epoch,
                execution=execution,
            )

        results: list[dict[str, Any]] = [dict(item) for item in existing_results]
        dispositions: list[AcquisitionProbeDisposition] = []
        probe_results: list[tuple[AcquisitionProbe, list[dict[str, Any]]]] = []
        selected_probes = [
            probe
            for action in execution_actions
            for probe in probes_by_action.get(action.action_digest, [])
        ]
        for probe in selected_probes:
            started = perf_counter()
            raw_items, status, reason = self._execute_probe(
                probe,
                context=context,
                request=request,
                acquisition_plan=acquisition_plan,
            )
            items, repeated = _exclude_seen_candidates(raw_items, existing_results)
            probe_results.append((probe, items))
            dispositions.append(
                AcquisitionProbeDisposition(
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
            )
        fused_probe_results: list[dict[str, Any]] = []
        if selected_probes:
            selected_plan = _selected_plan(acquisition_plan, selected_probes)
            fused_probe_results = fuse_acquisition_probe_results(
                selected_plan,
                probe_results,
            )
            results = _deduplicate([*results, *fused_probe_results])

        range_scan: dict[str, Any] | None = None
        if structural_actions:
            action = structural_actions[0]
            extra, disposition, range_scan = self._execute_structural_action(
                action,
                context=context,
                request=request,
                query_plan=query_plan,
                acquisition_plan=acquisition_plan,
                existing_results=results,
                execution_selection=selections.get(action.action_digest),
            )
            extra, repeated = _exclude_seen_candidates(extra, results)
            dispositions.append(
                disposition.model_copy(
                    update={
                        "selected_candidate_count": len(extra),
                        "excluded_seen_candidate_count": repeated,
                        "repeated_region_count": repeated,
                        "new_region_count": len(extra),
                    }
                )
            )
            results = _deduplicate([*results, *extra])

        execution = self.compile_existing_results(
            request=request,
            query_plan=query_plan,
            acquisition_plan=acquisition_plan,
            capability_set=capability_set,
            mode=mode,
            state_epoch=next_epoch,
            results=results,
            action_digest=None,
            range_scan=range_scan,
            probe_dispositions=dispositions,
            probe_candidate_traces=_probe_candidate_traces(
                probe_results,
                fused_probe_results,
            ),
            type_directed_semantics=type_directed_semantics,
        )
        return _plan_execution(
            requirement_acquisition_plan,
            validation=validation,
            execution_actions=execution_actions,
            repository_probe_calls=repository_probe_calls,
            initial_epoch=current_requirement_state.state_epoch,
            execution=execution,
        )

    def compile_existing_results(
        self,
        *,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        capability_set: AcquisitionCapabilitySet,
        mode: EvidenceAcquisitionMode,
        state_epoch: int,
        results: Sequence[Mapping[str, Any]],
        action_digest: str | None,
        range_scan: Mapping[str, Any] | None = None,
        probe_dispositions: Sequence[AcquisitionProbeDisposition] = (),
        probe_candidate_traces: Sequence[AcquisitionProbeCandidateTrace] = (),
        type_directed_semantics: bool = False,
        grounded_formation_semantics: GroundedFormationSemantics | None = None,
        defer_semantics: bool = False,
    ) -> EvidenceAcquisitionExecutionRef:
        """Compile governed preselected results without another repository pass."""

        query_ir = query_plan.memory_query_ir
        if query_ir is None:
            raise ValueError("official Evidence acquisition requires MemoryQueryIR")
        compiled_results = [dict(item) for item in results]
        formation_binding_operator = (
            grounded_formation_semantics is not None
            and query_plan.operator
            in {
                "LATEST_VALID_STATE",
                "TEMPORAL_BEFORE_AFTER",
                "COMPARE_EVENT_IDENTITY",
                "COMPOSE_STATE",
            }
        )
        protect_binding_operands = formation_binding_operator or (
            type_directed_semantics
            and query_plan.operator == "TEMPORAL_DISTANCE"
            and query_plan.operator_arguments.get("distance_mode") == "between_events"
        )
        binding_backed_operator = query_plan.operator is not None
        bounded_temporal_operator = temporal_range(query_plan) is not None
        derived_result = (
            self._derived_result(
                query_plan,
                compiled_results,
                range_scan=range_scan,
            )
            if range_scan is not None
            or not binding_backed_operator
            or bounded_temporal_operator
            else None
        )
        if protect_binding_operands and grounded_formation_semantics is None:
            # Preserve the whole bounded probe snapshot until typed bindings
            # have selected the operator operands.  A raw-text provisional
            # result is not allowed to evict a later, stronger MATCH before
            # Binding has had a chance to inspect it.
            provisional_spans = project_evidence_spans(compiled_results)
            provisional_interpretations, provisional_bindings, _audit = (
                _run_product_type_directed_semantics(
                    query_ir.requirements,
                    provisional_spans,
                )
            )
            derived_result = execute_binding_backed_query_operator(
                query_plan,
                compiled_results,
                provisional_spans,
                provisional_interpretations,
                provisional_bindings,
            )
        compiled_results = _prioritize_results(
            query_plan,
            compiled_results,
            derived_result,
        )
        defer_raw = (
            defer_semantics and not type_directed_semantics
            and grounded_formation_semantics is None and query_plan.operator is None
            and range_scan is None and lean_decision_mode(query_plan) == "ORDINARY_RECALL"
        )
        raw_spans: Sequence[EvidenceSpan]
        spans: Sequence[EvidenceSpan]
        if defer_raw:
            raw_spans = spans = PreparedEvidenceSpans(compiled_results, deduplicate=True)
        else:
            raw_spans = project_evidence_spans(compiled_results)
            spans = _merge_grounded_spans(raw_spans, grounded_formation_semantics)
        semantic_audit: TypeDirectedSemanticAudit | None = None
        deferred_semantics = None
        interpretations: Sequence[EvidenceInterpretationCandidate]
        bindings: Sequence[RequirementBinding]
        if defer_raw:
            deferred_semantics = DeferredRawSemantics(
                query_ir.requirements, spans, compatibility_profile="dg22-v0.2",
            )
            interpretations = deferred_semantics.interpretations
            bindings = deferred_semantics.bindings
        elif type_directed_semantics:
            interpretations, bindings, semantic_audit = _run_product_type_directed_semantics(
                query_ir.requirements,
                raw_spans,
                grounded_formation_semantics=grounded_formation_semantics,
            )
        else:
            interpretations = _merge_grounded_interpretations(
                interpret_evidence_spans(raw_spans),
                grounded_formation_semantics,
            )
            bindings = bind_requirements(
                query_ir.requirements,
                interpretations,
                spans,
                # QueryTaskContract selects the query-local planning profile;
                # these Raw-language interpretations remain diagnostics and
                # Reader-ranking signals, never deterministic operand authority.
                # The legacy profile below affects diagnostic classification
                # only; absent contract lineage cannot restore authority.
                compatibility_profile=(
                    "dg22-v0.2"
                    if query_plan.query_task_contract is not None
                    or lean_decision_mode(query_plan) == "ORDINARY_RECALL"
                    or query_plan.operator
                    in {"TEMPORAL_BEFORE_AFTER", "TEMPORAL_DISTANCE"}
                    or grounded_formation_semantics is not None
                    else "legacy-v0.1"
                ),
            )
        if binding_backed_operator:
            if (
                derived_result is not None
                and derived_result.get("kind") == "EVIDENCE_COMPOSITION_RESULT"
            ):
                derived_result = _authorize_bounded_composition_result(
                    query_plan,
                    derived_result,
                    compiled_results,
                    spans,
                    interpretations,
                    bindings,
                )
            else:
                derived_result = execute_binding_backed_query_operator(
                    query_plan,
                    compiled_results,
                    spans,
                    interpretations,
                    bindings,
                )
        authoritative_bindings = operator_operands_from_raw_bindings(bindings)
        matched_requirement_ids = sorted(
            {
                binding.requirement_id
                for binding in authoritative_bindings
                if binding.status == "MATCH"
            }
        )
        required_requirement_ids = sorted(
            requirement.slot_id for requirement in query_ir.requirements if requirement.required
        )
        missing_requirement_ids = sorted(
            set(required_requirement_ids).difference(matched_requirement_ids)
        )
        # Acquisition is an intermediate evidence/binding producer.  It never
        # emits COMPLETE; the product DecisionEngine owns the terminal decision.
        sufficiency = SufficiencyDecision(
            status="PARTIAL" if matched_requirement_ids or compiled_results else "UNSATISFIED",
            covered_slots=matched_requirement_ids,
            missing_slots=missing_requirement_ids,
            proof=build_intermediate_sufficiency_proof(derived_result),
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        )
        reason = "ACQUISITION_INTERMEDIATE_DECISION_DEFERRED"
        candidates = _candidate_envelopes(compiled_results)
        requirement_state = resolve_requirement_state(
            plan=acquisition_plan,
            requirements=query_ir.requirements,
            acquisition_capability_digest=capability_set.capability_digest,
            candidates=candidates,
            spans=spans,
            interpretations=interpretations,
            bindings=authoritative_bindings,
            sufficiency_decision=sufficiency,
            state_epoch=state_epoch,
            memory_query_ir=query_ir,
        )
        facts: dict[str, Any] = dict(
            mode=mode,
            acquisition_capability_digest=capability_set.capability_digest,
            action_digest=action_digest,
            results=compiled_results,
            candidates=candidates,
            requirement_state=requirement_state,
            sufficiency_decision=sufficiency,
            sufficiency_reason=reason,
            derived_result=derived_result,
            bounded_range_scan_proof=(
                _bounded_range_scan_proof_v02(
                    range_scan,
                    query_ir=query_ir,
                    requirement_state=requirement_state,
                )
                if range_scan is not None
                else None
            ),
            probe_dispositions=list(probe_dispositions),
            probe_candidate_traces=list(probe_candidate_traces),
            type_directed_semantics=type_directed_semantics,
            semantic_audit=semantic_audit,
        )
        if deferred_semantics is not None:
            return DeferredEvidenceAcquisitionExecution(
                EvidenceAcquisitionFacts(**facts), deferred_semantics, query_ir.requirements,
            )
        return EvidenceAcquisitionExecution(
            **facts, spans=list(spans),
            interpretations=list(interpretations), bindings=list(bindings),
            candidate_requirement_attribution=_candidate_requirement_attribution(
                query_ir.requirements, bindings, interpretations, spans,
            ),
        )

    def _selected_probes(
        self,
        plan: AcquisitionPlan,
        action: FeasibleAcquisitionAction | None,
        capability_set: AcquisitionCapabilitySet,
        execution_selection: AcquisitionExecutionSelection | None,
    ) -> list[AcquisitionProbe]:
        if action is None:
            return [
                probe
                for probe in plan.probes
                if capability_set.capability(probe.channel).executable
            ]
        if action.channel not in {"FTS_RAW", "FTS_ENRICHED", "EVIDENCE_DENSE"}:
            return []
        return [
            probe
            for probe in plan.probes
            if probe.channel == action.channel
            and (
                probe.requirement_slot == action.target_requirement_id
                if execution_selection is not None
                and execution_selection.targeted_only
                and not execution_selection.include_global_probe
                else probe.requirement_slot in {None, action.target_requirement_id}
            )
        ]

    def _capability_skip_dispositions(
        self,
        plan: AcquisitionPlan,
        capability_set: AcquisitionCapabilitySet,
        selected_probe_ids: set[str],
    ) -> list[AcquisitionProbeDisposition]:
        values: list[AcquisitionProbeDisposition] = []
        for probe in plan.probes:
            if probe.probe_id in selected_probe_ids:
                continue
            capability = capability_set.capability(probe.channel)
            values.append(
                AcquisitionProbeDisposition(
                    probe_id=probe.probe_id,
                    requirement_id=probe.requirement_slot,
                    channel=probe.channel,
                    status=capability.status,
                    reason_code=capability.reason,
                    raw_candidate_count=0,
                    selected_candidate_count=0,
                    latency_ms=0,
                )
            )
        return values

    def _execute_probe(
        self,
        probe: AcquisitionProbe,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        acquisition_plan: AcquisitionPlan,
        ranking_features: dict[tuple[str, str], tuple[int, bool]] | None = None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        if probe.channel == "EVIDENCE_DENSE":
            # Product-08 uses QueryIR temporal structure as an acquisition hint,
            # not as permission to suppress an otherwise governed discovery
            # channel.  The Evidence-dense projection has no event-time filter;
            # execute the scoped/as-of query and leave temporal acceptance to
            # Binding/operator validation.  Legacy strict plans still fail
            # closed when they cannot enforce the requested event range here.
            if (
                acquisition_plan.global_constraints.event_occurrence_range is not None
                and not additive_union_v0_2_enabled(acquisition_plan)
            ):
                return [], "UNAVAILABLE", "EVENT_TIME_FILTER_UNAVAILABLE"
            source_range = acquisition_plan.global_constraints.source_observed_range
            if source_range is not None and not executable_closed_open_range(source_range):
                return [], "UNAVAILABLE", "SOURCE_TIME_FILTER_UNAVAILABLE"
            method = getattr(self._repository, "search_evidence_dense", None)
            if not callable(method) or self._embedding.identity.projection_dimensions != 128:
                return [], "UNAVAILABLE", "PROJECTION_UNAVAILABLE"
            try:
                embedding = self._embedding.embed(probe_query(probe))
                payload = method(
                    context,
                    embedding,
                    dict(request.requested_scope),
                    request.as_of,
                    probe.candidate_limit,
                    model_id=self._embedding.identity.model_id,
                    projection_version=evidence_turn_projection_version(self._embedding.identity),
                    source_observed_range=source_range,
                )
            except (ProjectionUnavailable, EmbeddingUnavailable):
                return [], "UNAVAILABLE", "PROJECTION_UNAVAILABLE"
            items = payload.get("items") if isinstance(payload, Mapping) else None
            if payload.get("status") != "COMPLETE" or not isinstance(items, list):
                return [], "PARTIAL", "PROJECTION_PARTIAL"
            return apply_probe_source_policy(probe, items), "EXECUTED", "EXECUTED"
        method = getattr(self._repository, "search_evidence", None)
        if not callable(method):
            return [], "UNAVAILABLE", "REPOSITORY_METHOD_UNAVAILABLE"
        try:
            items = method(
                context,
                probe_query(probe),
                dict(request.requested_scope),
                request.as_of,
                probe.candidate_limit,
            )
        except ProjectionUnavailable:
            return [], "UNAVAILABLE", "PROJECTION_UNAVAILABLE"
        except DatabaseStatementTimeout:
            return [], "TIMEOUT", "SEARCH_BUDGET_EXHAUSTED"
        ranked = rank_evidence_turns(
            apply_probe_source_policy(probe, items),
            probe_query(probe),
            preferred_speakers=_probe_ranking_speakers(probe),
            feature_cache=ranking_features,
        )
        return ranked, "EXECUTED", "EXECUTED"

    def _execute_planned_range(
        self,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
    ) -> tuple[
        list[dict[str, Any]],
        AcquisitionProbeDisposition | None,
        dict[str, Any] | None,
    ]:
        bounded = temporal_range(query_plan)
        if bounded is None:
            return [], None, None
        if temporal_query_axis(query_plan) != "SOURCE_OBSERVED_TIME":
            return (
                [],
                AcquisitionProbeDisposition(
                    probe_id="planned:source-observed-range",
                    channel="TEMPORAL_EVENT",
                    status="UNAVAILABLE",
                    reason_code="EVENT_PROJECTION_NOT_READY",
                    raw_candidate_count=0,
                    selected_candidate_count=0,
                    latency_ms=0,
                ),
                None,
            )
        method = getattr(self._repository, "scan_evidence_range", None)
        if not callable(method):
            return (
                [],
                AcquisitionProbeDisposition(
                    probe_id="planned:source-observed-range",
                    channel="SOURCE_OBSERVED_RANGE_SCAN",
                    status="UNAVAILABLE",
                    reason_code="REPOSITORY_METHOD_UNAVAILABLE",
                    raw_candidate_count=0,
                    selected_candidate_count=0,
                    latency_ms=0,
                ),
                None,
            )
        started = perf_counter()
        scan = method(
            context,
            dict(request.requested_scope),
            bounded[0],
            bounded[1],
            2_000,
        )
        items = scan.get("items", []) if isinstance(scan, Mapping) else []
        hydrated = _envelope_structural_items(
            items if isinstance(items, list) else [],
            channel="SOURCE_OBSERVED_RANGE_SCAN",
            requirement_ids=[
                item.slot_id for item in query_plan.memory_query_ir.requirements if item.required
            ]
            if query_plan.memory_query_ir is not None
            else [],
        )
        return (
            hydrated,
            AcquisitionProbeDisposition(
                probe_id="planned:source-observed-range",
                channel="SOURCE_OBSERVED_RANGE_SCAN",
                status="EXECUTED",
                reason_code=str(scan.get("status", "PARTIAL")),
                raw_candidate_count=len(items),
                selected_candidate_count=len(hydrated),
                latency_ms=round((perf_counter() - started) * 1_000, 6),
            ),
            dict(scan),
        )

    def _execute_structural_action(
        self,
        action: FeasibleAcquisitionAction,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        existing_results: Sequence[Mapping[str, Any]],
        execution_selection: AcquisitionExecutionSelection | None,
    ) -> tuple[
        list[dict[str, Any]],
        AcquisitionProbeDisposition,
        dict[str, Any] | None,
    ]:
        started = perf_counter()
        items: list[dict[str, Any]] = []
        scanned_item_count: int | None = None
        range_scan: dict[str, Any] | None = None
        status, reason = "UNAVAILABLE", "CAPABILITY_NOT_EXECUTED"
        if action.channel == "SOURCE_OBSERVED_RANGE_SCAN":
            bounded = _source_observed_bounds(acquisition_plan)
            method = getattr(self._repository, "scan_evidence_range", None)
            if bounded is not None and temporal_query_axis(query_plan) == "SOURCE_OBSERVED_TIME":
                if callable(method):
                    scan = method(
                        context,
                        dict(request.requested_scope),
                        bounded[0],
                        bounded[1],
                        min(2_000, action.bounded_cost["candidate_count"]),
                    )
                    raw = scan.get("items", []) if isinstance(scan, Mapping) else []
                    items = [dict(value) for value in raw if isinstance(value, Mapping)]
                    status, reason = "EXECUTED", str(scan.get("status", "EXECUTED"))
                    range_scan = dict(scan)
                else:
                    reason = "REPOSITORY_METHOD_UNAVAILABLE"
            else:
                reason = "SOURCE_OBSERVED_RANGE_NOT_APPLICABLE"
        elif action.channel == "ADJACENT_TURNS":
            method = getattr(self._repository, "hydrate_evidence_adjacency", None)
            strict_governance = execution_selection is not None
            max_anchors = 2 if strict_governance else 24
            anchor_rows = _structured_adjacency_anchors(
                existing_results,
                max_anchors=max_anchors,
            )
            anchors = [str(item["evidence_id"]) for item in anchor_rows]
            if callable(method) and anchors:
                raw = method(
                    context,
                    anchor_evidence_ids=anchors,
                    requested_scope=dict(request.requested_scope),
                    as_of=request.as_of,
                    max_items=min(
                        4 if strict_governance else 120,
                        action.bounded_cost["candidate_count"],
                    ),
                )
                items = _governed_adjacent_items(
                    raw,
                    anchors=anchor_rows,
                    requested_scope=request.requested_scope,
                    radius=2,
                    max_items=min(
                        4 if strict_governance else 120,
                        action.bounded_cost["candidate_count"],
                    ),
                    strict=strict_governance,
                )
                status, reason = "EXECUTED", "EXECUTED"
            else:
                reason = "NO_VALID_ANCHOR" if not anchors else "REPOSITORY_METHOD_UNAVAILABLE"
        elif action.channel == "SAME_EPISODE":
            reason = "NOT_IMPLEMENTED"
        elif action.channel == "TEMPORAL_EVENT":
            bounded = _event_occurrence_bounds(acquisition_plan)
            method = getattr(self._repository, "search_evidence_event_range", None)
            if bounded is None or temporal_query_axis(query_plan) != "EVENT_OCCURRENCE_TIME":
                reason = "EVENT_RANGE_NOT_APPLICABLE"
            elif not callable(method):
                reason = "EVENT_RANGE_METHOD_NOT_READY"
            else:
                try:
                    source_scan = method(
                        context,
                        dict(request.requested_scope),
                        bounded[0],
                        bounded[1],
                        request.as_of,
                        2_000,
                    )
                except DatabaseStatementTimeout:
                    status, reason = "TIMEOUT", "SEARCH_BUDGET_EXHAUSTED"
                else:
                    if not isinstance(source_scan, Mapping):
                        reason = "EVENT_RANGE_SCAN_INVALID"
                    else:
                        range_scan = normalize_query_time_event_scan(
                            query_plan,
                            source_scan,
                            expected_range=bounded,
                        )
                        raw = range_scan.get("items", [])
                        scanned = (
                            [dict(value) for value in raw if isinstance(value, Mapping)]
                            if isinstance(raw, list)
                            else []
                        )
                        range_scan["items"] = scanned
                        scanned_item_count = len(scanned)
                        derived = compose_evidence_range_count(query_plan, range_scan)
                        items = prioritize_temporal_evidence(range_scan, derived)[
                            : action.bounded_cost["candidate_count"]
                        ]
                        status = "EXECUTED"
                        reason = str(
                            range_scan.get(
                                "event_normalization_status",
                                range_scan.get("status", "PARTIAL"),
                            )
                        )
        hydrated = _envelope_structural_items(
            items,
            channel=action.channel,
            requirement_ids=[action.target_requirement_id],
            action_digest=action.action_digest,
        )
        return (
            hydrated,
            AcquisitionProbeDisposition(
                probe_id=f"action:{action.action_digest}",
                requirement_id=action.target_requirement_id,
                channel=action.channel,
                status=status,
                reason_code=reason,
                raw_candidate_count=(
                    scanned_item_count if scanned_item_count is not None else len(items)
                ),
                selected_candidate_count=len(hydrated),
                latency_ms=round((perf_counter() - started) * 1_000, 6),
            ),
            range_scan,
        )

    def _derived_result(
        self,
        query_plan: QueryPlan,
        results: Sequence[Mapping[str, Any]],
        *,
        range_scan: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if query_plan.operator == "DIVIDE_EVIDENCE_VALUES":
            return compose_divide_evidence_values(query_plan, results)
        if (
            query_plan.memory_query_ir is not None
            and infer_operator_family(query_plan.memory_query_ir) == "PREFERENCE_RESOLVE"
        ):
            return synthesize_preference_evidence_view(query_plan, results)
        bounded = temporal_range(query_plan)
        if bounded is not None:
            scan = (
                dict(range_scan)
                if range_scan is not None
                else {
                    "status": "PARTIAL",
                    "items": [dict(item) for item in results],
                    "scan_axis": "CANDIDATE_SET",
                    "source_partition_closed": False,
                    "projection_watermark_covered": False,
                }
            )
            return compose_evidence_range_count(query_plan, scan)
        return execute_query_operator(query_plan, results)


def _authorize_bounded_composition_result(
    query_plan: QueryPlan,
    derived_result: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    bindings: Sequence[RequirementBinding],
) -> dict[str, Any]:
    """Attach strict operand authority without discarding bounded-scan proof."""

    value = dict(derived_result)
    if value.get("status") not in {"OK", "COMPLETE"}:
        return value
    accepted = build_accepted_operator_inputs(
        query_plan,
        results,
        spans,
        interpretations,
        bindings,
    )
    accepted_ids = {item.span.source_evidence_id for item in accepted.operands}
    accepted_refs = {item.span.source_turn_ref for item in accepted.operands}
    operands = value.get("operands")
    if not isinstance(operands, list):
        return value
    operand_ids = {
        str(item["evidence_id"])
        for item in operands
        if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str)
    }
    operand_refs = {
        str(item["source_ref"])
        for item in operands
        if isinstance(item, Mapping) and isinstance(item.get("source_ref"), str)
    }
    if (
        not accepted.complete
        or not operand_ids.issubset(accepted_ids)
        or not operand_refs.issubset(accepted_refs)
    ):
        return value
    value.update(
        {
            "operand_authority": "ACCEPTED_BINDING_ONLY",
            "accepted_input_requirement_ids": list(
                accepted.filled_requirement_ids
            ),
            "accepted_input_evidence_ids": sorted(accepted_ids),
        }
    )
    return value


def _run_product_type_directed_semantics(
    requirements: Sequence[EvidenceRequirementV02],
    spans: Sequence[EvidenceSpan],
    *,
    grounded_formation_semantics: GroundedFormationSemantics | None = None,
) -> tuple[
    list[EvidenceInterpretationCandidate],
    list[RequirementBinding],
    TypeDirectedSemanticAudit,
]:
    """Bind the product flag to the frozen DG22 compatibility profile."""

    interpretations, _bindings, base_audit = run_type_directed_semantics(
        requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    allowed = {requirement.interpretation_kind for requirement in requirements}
    grounded_values = (
        [item for item in grounded_formation_semantics.interpretations if item.kind in allowed]
        if grounded_formation_semantics is not None
        else []
    )
    grounded_suppressed = (
        len(grounded_formation_semantics.interpretations) - len(grounded_values)
        if grounded_formation_semantics is not None
        else 0
    )
    interpretations = _merge_interpretation_values(interpretations, grounded_values)
    combined_spans = _merge_grounded_spans(spans, grounded_formation_semantics)
    bindings = bind_requirements(
        requirements,
        interpretations,
        combined_spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )
    suppressed = base_audit.suppressed_interpretation_count + grounded_suppressed
    legacy_evaluations = len(requirements) * (len(interpretations) + suppressed)
    audit = TypeDirectedSemanticAudit(
        allowed_interpretation_kinds=sorted(allowed),
        span_count=len(combined_spans),
        suppressed_interpretation_count=suppressed,
        materialized_interpretation_count=len(interpretations),
        legacy_binding_evaluation_count=legacy_evaluations,
        binding_evaluation_count=len(bindings),
        type_pruned_before_binding_count=legacy_evaluations - len(bindings),
        materialized_type_mismatch_count=0,
        exact_source_span_failure_count=0,
    )
    return interpretations, bindings, audit


def _merge_grounded_spans(
    spans: Sequence[EvidenceSpan],
    grounded: GroundedFormationSemantics | None,
) -> list[EvidenceSpan]:
    if grounded is None:
        return deduplicate_projected_spans(spans)
    values = {item.span_id: item for item in spans}
    for item in grounded.spans if grounded is not None else ():
        existing = values.get(item.span_id)
        if existing is not None and existing != item:
            raise ValueError("FORMATION_SPAN_ID_COLLISION")
        values[item.span_id] = item
    return sorted(
        values.values(),
        key=lambda item: (
            item.source_timestamp or datetime.min.replace(tzinfo=_query_timezone(spans)),
            item.source_turn_ref,
            item.start,
            item.span_id,
        ),
    )


def _merge_grounded_interpretations(
    interpretations: Sequence[EvidenceInterpretationCandidate],
    grounded: GroundedFormationSemantics | None,
) -> list[EvidenceInterpretationCandidate]:
    return _merge_interpretation_values(
        interpretations,
        grounded.interpretations if grounded is not None else (),
    )


def _merge_interpretation_values(
    left: Sequence[EvidenceInterpretationCandidate],
    right: Sequence[EvidenceInterpretationCandidate],
) -> list[EvidenceInterpretationCandidate]:
    values = {item.interpretation_id: item for item in left}
    for item in right:
        existing = values.get(item.interpretation_id)
        if existing is not None and existing != item:
            raise ValueError("FORMATION_INTERPRETATION_ID_COLLISION")
        values[item.interpretation_id] = item
    return sorted(
        values.values(),
        key=lambda item: (item.span_id, item.kind, item.interpretation_id),
    )


def _query_timezone(spans: Sequence[EvidenceSpan]) -> Any:
    for span in spans:
        if span.source_timestamp is not None:
            return span.source_timestamp.tzinfo
    return UTC


def _selected_plan(plan: AcquisitionPlan, probes: Sequence[AcquisitionProbe]) -> AcquisitionPlan:
    slots = {probe.requirement_slot for probe in probes if probe.requirement_slot is not None}
    quota = {
        slot: plan.fusion.per_slot_quota.get(slot, plan.budget.candidate_count)
        for slot in sorted(slots)
    }
    return plan.model_copy(
        update={
            "probes": list(probes),
            "fusion": plan.fusion.model_copy(update={"per_slot_quota": quota}),
        }
    )


def _validate_execution_selection(
    selection: AcquisitionExecutionSelection,
    action: FeasibleAcquisitionAction | None,
) -> None:
    if selection.terminal_disposition != "ACTIONABLE":
        raise ValueError("TERMINAL_EXECUTION_SELECTION_CANNOT_EXECUTE")
    if action is None:
        raise ValueError("ACTIONABLE_EXECUTION_SELECTION_REQUIRES_ACTION")
    if (
        selection.target_requirement_id != action.target_requirement_id
        or selection.selected_channel != action.channel
    ):
        raise ValueError("EXECUTION_SELECTION_ACTION_MISMATCH")
    bounded_count = action.bounded_cost.get("candidate_count")
    if (
        action.bounded_cost.get("acquisition_passes")
        != selection.effective_budget.acquisition_passes
        or action.bounded_cost.get("model_calls") != 0
        or not isinstance(bounded_count, int)
        or isinstance(bounded_count, bool)
        or bounded_count < 1
        or bounded_count > selection.effective_budget.hydrate_count
    ):
        raise ValueError("EXECUTION_SELECTION_BUDGET_MISMATCH")
    if selection.include_global_probe:
        raise ValueError("DG21_TARGET_ACTION_GLOBAL_PROBE_FORBIDDEN")


def _exclude_seen_candidates(
    items: Sequence[Mapping[str, Any]],
    existing: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    seen_evidence = {
        str(item["evidence_id"]) for item in existing if isinstance(item.get("evidence_id"), str)
    }
    seen_sources = {
        str(item["source_ref"]) for item in existing if isinstance(item.get("source_ref"), str)
    }
    selected: list[dict[str, Any]] = []
    repeated = 0
    for item in items:
        evidence_id = item.get("evidence_id")
        source_ref = item.get("source_ref")
        if (isinstance(evidence_id, str) and evidence_id in seen_evidence) or (
            isinstance(source_ref, str) and source_ref in seen_sources
        ):
            repeated += 1
            continue
        selected.append(dict(item))
    return selected, repeated


def _source_observed_bounds(plan: AcquisitionPlan) -> tuple[datetime, datetime] | None:
    raw = plan.global_constraints.source_observed_range
    if not executable_closed_open_range(raw):
        return None
    assert raw is not None
    start = _aware_datetime(raw.get("start"))
    end = _aware_datetime(raw.get("end"))
    if start is None or end is None or start >= end:
        return None
    return start, end


def _event_occurrence_bounds(plan: AcquisitionPlan) -> tuple[datetime, datetime] | None:
    raw = plan.global_constraints.event_occurrence_range
    if not executable_closed_open_range(raw):
        return None
    assert raw is not None
    start = _aware_datetime(raw.get("start"))
    end = _aware_datetime(raw.get("end"))
    if start is None or end is None or start >= end:
        return None
    return start, end


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _structured_adjacency_anchors(
    items: Sequence[Mapping[str, Any]],
    *,
    max_anchors: int,
    distinct_sessions: bool = False,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_sessions: set[str] = set()
    for item in items:
        evidence_id = item.get("evidence_id")
        context = item.get("source_context")
        if (
            not isinstance(evidence_id, str)
            or evidence_id in seen
            or item.get("source_context_source") != "STRUCTURED_TURN_METADATA"
            or not isinstance(context, Mapping)
            or not isinstance(context.get("session_id"), str)
            or not isinstance(context.get("round_ordinal"), int)
        ):
            continue
        session_id = str(context["session_id"])
        if distinct_sessions and session_id in seen_sessions:
            continue
        values.append(dict(item))
        seen.add(evidence_id)
        seen_sessions.add(session_id)
        if len(values) >= max_anchors:
            break
    return values


def _same_session_expansion_planned(probes: Sequence[AcquisitionProbe]) -> bool:
    return any(probe.expansion_policy in {"ADJACENT_TURNS", "SAME_SESSION"} for probe in probes)


def _query_preserving_locality_order(
    direct: Sequence[Mapping[str, Any]],
    locality: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Place one direct representative per hydrated session before its neighbors.

    The public retrieval response has a smaller presentation limit than the
    acquisition budget.  Keeping the 24 structured anchors first guarantees
    query-preserving breadth; placing their SQL-ranked same/adjacent-round
    neighbors next guarantees that bounded locality is not silently truncated.
    """

    anchors = _structured_adjacency_anchors(
        direct,
        max_anchors=24,
        distinct_sessions=True,
    )
    anchor_ids = {
        str(item["evidence_id"])
        for item in anchors
        if isinstance(item.get("evidence_id"), str)
    }
    session_order = [
        str(item["source_context"]["session_id"])
        for item in anchors
        if isinstance(item.get("source_context"), Mapping)
        and isinstance(item["source_context"].get("session_id"), str)
    ]
    landmark_by_session: dict[str, dict[str, Any]] = {}
    for item in locality:
        context = item.get("source_context")
        if not isinstance(context, Mapping) or not isinstance(
            context.get("session_id"), str
        ):
            continue
        session_id = str(context["session_id"])
        current = landmark_by_session.get(session_id)
        if current is None or _source_position(item) < _source_position(current):
            landmark_by_session[session_id] = dict(item)
    landmarks = [
        landmark_by_session[session_id]
        for session_id in session_order
        if session_id in landmark_by_session
    ]
    landmark_ids = {
        str(item["evidence_id"])
        for item in landmarks
        if isinstance(item.get("evidence_id"), str)
    }
    remaining_direct = [
        item for item in direct if str(item.get("evidence_id")) not in anchor_ids
    ]
    remaining_locality = [
        item for item in locality if str(item.get("evidence_id")) not in landmark_ids
    ]
    return _deduplicate(
        [*anchors, *landmarks, *remaining_direct, *remaining_locality]
    )


def _source_position(item: Mapping[str, Any]) -> tuple[int, int, str]:
    context = item.get("source_context")
    values = context if isinstance(context, Mapping) else {}
    round_ordinal = values.get("round_ordinal")
    turn_ordinal = values.get("turn_ordinal")
    return (
        round_ordinal if isinstance(round_ordinal, int) else 2**31,
        turn_ordinal if isinstance(turn_ordinal, int) else 2**31,
        str(item.get("source_ref", "")),
    )


def _previous_round_frontier(
    frontier: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    frontier_context = frontier.get("source_context")
    if not isinstance(frontier_context, Mapping) or not isinstance(
        frontier_context.get("round_ordinal"), int
    ):
        return None
    frontier_round = int(frontier_context["round_ordinal"])
    previous = [
        dict(item)
        for item in candidates
        if _source_position(item)[0] < frontier_round
    ]
    return min(previous, key=_source_position) if previous else None


def _anchor_requirement_ids(anchors: Sequence[Mapping[str, Any]]) -> list[str]:
    values: set[str] = set()
    for anchor in anchors:
        candidate = anchor.get("acquisition_candidate")
        if not isinstance(candidate, Mapping):
            continue
        matched_slots = candidate.get("matched_slots")
        if isinstance(matched_slots, Sequence) and not isinstance(matched_slots, (str, bytes)):
            values.update(item for item in matched_slots if isinstance(item, str))
    return sorted(values)


def _governed_adjacent_items(
    items: object,
    *,
    anchors: Sequence[Mapping[str, Any]],
    requested_scope: Mapping[str, object],
    radius: int,
    max_items: int,
    strict: bool,
) -> list[dict[str, Any]]:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return []
    if not strict:
        return [dict(item) for item in items if isinstance(item, Mapping)][:max_items]
    anchor_positions = {
        (
            str(item["source_context"]["session_id"]),
            int(item["source_context"]["round_ordinal"]),
        )
        for item in anchors
        if isinstance(item.get("source_context"), Mapping)
    }
    requested_projects = _string_set(requested_scope.get("project_ids"))
    selected: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping) or not evidence_source_eligible(raw):
            continue
        context = raw.get("source_context")
        permission = raw.get("permission_snapshot")
        if (
            raw.get("source_context_source") != "STRUCTURED_TURN_METADATA"
            or not isinstance(context, Mapping)
            or not isinstance(context.get("session_id"), str)
            or not isinstance(context.get("round_ordinal"), int)
            or not isinstance(permission, Mapping)
            or permission.get("readable") is not True
        ):
            continue
        allowed_projects = _string_set(permission.get("project_ids"))
        if requested_projects and not requested_projects.issubset(allowed_projects):
            continue
        session_id = str(context["session_id"])
        round_ordinal = int(context["round_ordinal"])
        if not any(
            session_id == anchor_session and abs(round_ordinal - anchor_round) <= radius
            for anchor_session, anchor_round in anchor_positions
        ):
            continue
        selected.append(dict(raw))
        if len(selected) >= max_items:
            break
    return selected


def _string_set(value: object) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {item for item in value if isinstance(item, str)}


def _prioritize_results(
    query_plan: QueryPlan,
    results: list[dict[str, Any]],
    derived_result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    prioritized = prioritize_composition_evidence(results, derived_result)
    prioritized = prioritize_preference_evidence(prioritized, derived_result)
    if temporal_range(query_plan) is not None:
        scan = {"items": prioritized}
        prioritized = prioritize_temporal_evidence(scan, derived_result)
    return prioritized[: query_plan.candidate_cap]


def _candidate_envelopes(results: Sequence[Mapping[str, Any]]) -> list[CandidateEnvelope]:
    values: list[CandidateEnvelope] = []
    seen: set[str] = set()
    for result in results:
        raw = result.get("acquisition_candidate")
        if not isinstance(raw, Mapping):
            continue
        candidate = CandidateEnvelope.model_validate(dict(raw))
        if candidate.candidate_id not in seen:
            values.append(candidate)
            seen.add(candidate.candidate_id)
    return values


def _probe_candidate_traces(
    probe_results: Sequence[tuple[AcquisitionProbe, Sequence[Mapping[str, Any]]]],
    fused_results: Sequence[Mapping[str, Any]],
) -> list[AcquisitionProbeCandidateTrace]:
    fused_ids = {
        str(item["evidence_id"])
        for item in fused_results
        if isinstance(item.get("evidence_id"), str)
    }
    values: list[AcquisitionProbeCandidateTrace] = []
    for probe, results in probe_results:
        raw = [
            (str(item["evidence_id"]), str(item["source_ref"]))
            for item in results
            if isinstance(item.get("evidence_id"), str) and isinstance(item.get("source_ref"), str)
        ]
        surviving = [item for item in raw if item[0] in fused_ids]
        values.append(
            AcquisitionProbeCandidateTrace(
                probe_id=probe.probe_id,
                requirement_id=probe.requirement_slot,
                channel=probe.channel,
                candidate_limit=probe.candidate_limit,
                raw_candidate_ids=[item[0] for item in raw],
                raw_source_refs=[item[1] for item in raw],
                fusion_surviving_candidate_ids=[item[0] for item in surviving],
                fusion_surviving_source_refs=[item[1] for item in surviving],
            )
        )
    return values


def _envelope_structural_items(
    items: Sequence[Mapping[str, Any]],
    *,
    channel: AcquisitionCapabilityName,
    requirement_ids: Sequence[str],
    action_digest: str | None = None,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for rank, raw in enumerate(items, start=1):
        evidence_id = raw.get("evidence_id")
        source_ref = raw.get("source_ref")
        if not isinstance(evidence_id, str) or not isinstance(source_ref, str):
            continue
        source_identity = structured_evidence_identity(raw, source_ref)
        if source_identity is None:
            continue
        speaker, speaker_source = structured_evidence_speaker(raw)
        probe_id = f"action:{action_digest}" if action_digest is not None else f"official:{channel}"
        envelope = CandidateEnvelope(
            candidate_id=evidence_id,
            source_evidence_id=evidence_id,
            source_turn_ref=source_ref,
            subject_id=source_identity.subject_id,
            session_id=source_identity.session_id,
            turn_id=source_identity.turn_id,
            identity_source=source_identity.identity_source,
            speaker=speaker,
            speaker_source=speaker_source,
            source_observed_at=raw.get("observed_at"),
            matched_probes=[probe_id],
            matched_slots=sorted(set(requirement_ids)),
            channel_ranks={channel: rank},
            channel_scores={channel: float(raw.get("relevance_score") or 0.0)},
            probe_ranks={probe_id: rank},
            probe_scores={probe_id: float(raw.get("relevance_score") or 0.0)},
            fusion_rank=rank,
            fusion_score=float(raw.get("relevance_score") or 0.0),
            expansion_origin=(channel if channel in {"ADJACENT_TURNS", "SAME_EPISODE"} else None),
            matched_fields=[
                "structured_range"
                if channel == "SOURCE_OBSERVED_RANGE_SCAN"
                else "structural_expansion"
            ],
            body_ref=source_ref,
            body_hydrated=isinstance(raw.get("content"), str),
        )
        value = dict(raw)
        value["acquisition_candidate"] = envelope.model_dump(mode="json")
        values.append(value)
    return values


def _deduplicate(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for item in items:
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            values.setdefault(evidence_id, dict(item))
    return list(values.values())


def _bounded_range_scan_proof_v02(
    scan: Mapping[str, Any],
    *,
    query_ir: MemoryQueryIRV02,
    requirement_state: RequirementState,
) -> BoundedRangeScanProofV02:
    """Convert official repository facts into the sole V02 temporal proof."""

    raw_scan_axis = scan.get("scan_axis")
    if raw_scan_axis not in {"SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"}:
        raise ValueError("range scan must declare its physical temporal axis")
    temporal = query_ir.constraints.normalized_temporal
    if temporal is None or temporal.start is None or temporal.end is None:
        raise ValueError("bounded range proof requires a resolved interval")
    source_time_only = raw_scan_axis == "SOURCE_OBSERVED_TIME"
    interval_end = temporal.end
    if interval_end <= temporal.start:
        interval_end = temporal.start + (
            timedelta(hours=1)
            if temporal.precision == "HOUR"
            else timedelta(minutes=1)
            if temporal.precision == "MINUTE"
            else timedelta(days=1)
        )
    interval = build_event_time_interval_v02(
        interval_start=temporal.start,
        interval_end_exclusive=interval_end,
        timezone=temporal.timezone or "UTC",
        precision="RELATIVE_RANGE",
        basis="SOURCE_OBSERVED_PROXY" if source_time_only else "EXPLICIT_CALENDAR",
        ambiguity_reasons=("SOURCE_TIME_NOT_EVENT_TIME",) if source_time_only else (),
    )
    items = scan.get("items")
    returned_count = scan.get("returned_count")
    if not isinstance(returned_count, int) or isinstance(returned_count, bool):
        returned_count = len(items) if isinstance(items, list) else 0
    source_count = _optional_nonnegative_int(scan.get("source_count"))
    projected_count = _optional_nonnegative_int(scan.get("projected_count"))
    max_items = _optional_positive_int(scan.get("max_items")) or 2_000
    target = _optional_nonnegative_int(scan.get("target_watermark")) or 0
    projected = _optional_nonnegative_int(scan.get("projection_watermark")) or 0
    unreadable = _optional_nonnegative_int(scan.get("unreadable_evidence_count")) or 0
    source_closed = scan.get("source_partition_closed") is True
    raw_complete = scan.get("status") == "COMPLETE"
    max_items_hit = source_count is not None and source_count > max_items
    snapshot_material = {
        "query": query_ir.model_dump(mode="json"),
        "scan": {key: value for key, value in scan.items() if key != "items"},
    }
    snapshot_digest = canonical_sha256(snapshot_material)
    return build_bounded_range_scan_proof_v02(
        query_closure=BoundedRangeQueryClosureV02(
            query_ir_digest=canonical_sha256(query_ir.model_dump(mode="json")),
            requirement_state_digest=requirement_state.state_digest,
            event_time_interval=interval,
            timezone=temporal.timezone or "UTC",
        ),
        snapshot_closure=BoundedRangeSnapshotClosureV02(
            transaction_snapshot_identity=snapshot_digest,
            source_partition_snapshot_identity=canonical_sha256(
                {
                    "source_count": source_count,
                    "range": [temporal.start.isoformat(), interval_end.isoformat()],
                }
            ),
            access_snapshot_identity=canonical_sha256(
                {"unreadable": unreadable, "policy": "canonical-gate"}
            ),
            revocation_snapshot_identity=canonical_sha256(
                {"snapshot": snapshot_digest, "revocation_checked": True}
            ),
            snapshot_stable=source_closed,
        ),
        scan_closure=BoundedRangeScanClosureV02(
            source_partition_closed=source_closed,
            range_scan_complete=raw_complete and not source_time_only,
            max_items=max_items,
            max_items_hit=max_items_hit,
            unreadable_source_count=unreadable,
        ),
        projection_closure=BoundedRangeProjectionClosureV02(
            projection_version=str(scan.get("projection_version") or "unknown"),
            temporal_normalizer_version="memory-query-v02",
            target_watermark=target,
            projection_watermark=projected,
            projection_watermark_covered=projected >= target,
            dead_letter_gap=scan.get("dead_letter_gap") is True,
            unprojected_source_count=max(0, (source_count or 0) - (projected_count or 0)),
            raw_fallback_closed=raw_complete and not source_time_only,
        ),
        event_set_closure=BoundedRangeEventSetClosureV02(
            candidate_event_count=returned_count,
            in_range_event_count=0 if source_time_only else returned_count,
            out_of_range_event_count=0,
            ambiguous_time_count=0,
            unresolved_event_count=returned_count if source_time_only else 0,
            event_identity_policy_version="formation-event-identity-v02",
        ),
        dedup_closure=BoundedRangeDedupClosureV02(
            dedup_policy_version="event-identity-dedup-v02",
            duplicate_group_count=0,
            unresolved_duplicate_group_count=returned_count if source_time_only else 0,
            distinct_event_count=0 if source_time_only else returned_count,
            dedup_complete=not source_time_only,
        ),
        access_closure=BoundedRangeAccessClosureV02(
            policy_digest=canonical_sha256("canonical-gate-v1"),
            unreadable_evidence_count=unreadable,
            access_snapshot_valid=unreadable == 0,
        ),
    )


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _optional_positive_int(value: object) -> int | None:
    result = _optional_nonnegative_int(value)
    return result if result is not None and result > 0 else None


def _candidate_requirement_attribution(
    requirements: Sequence[Any],
    bindings: Sequence[RequirementBinding],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    spans: Sequence[EvidenceSpan],
) -> dict[str, dict[str, int]]:
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {item.span_id: item for item in spans}
    result: dict[str, dict[str, int]] = {}
    for requirement in requirements:
        counts: Counter[str] = Counter()
        evidence: set[str] = set()
        for binding in bindings:
            if binding.requirement_id != requirement.slot_id:
                continue
            counts[binding.status] += 1
            interpretation = interpretation_by_id.get(binding.interpretation_id)
            span = span_by_id.get(interpretation.span_id) if interpretation is not None else None
            if span is not None:
                evidence.add(span.source_evidence_id)
        result[requirement.slot_id] = {
            "candidate_count": len(evidence),
            "matched_binding_count": counts["MATCH"],
            "possible_binding_count": counts["POSSIBLE"],
            "rejected_binding_count": counts["REJECTED"],
        }
    return result


def _unique_feasible_actions(
    actions: Sequence[FeasibleAcquisitionAction],
) -> dict[str, FeasibleAcquisitionAction]:
    values: dict[str, FeasibleAcquisitionAction] = {}
    for action in actions:
        if action.action_digest in values:
            raise ValueError("DUPLICATE_FEASIBLE_ACTION_DIGEST")
        values[action.action_digest] = action
    return values


def _plan_execution(
    plan: RequirementAcquisitionPlanV01,
    *,
    validation: RequirementAcquisitionPlanValidationV01,
    execution_actions: Sequence[FeasibleAcquisitionAction],
    repository_probe_calls: int,
    initial_epoch: int,
    execution: EvidenceAcquisitionExecutionRef,
) -> RequirementAcquisitionPlanExecutionV01:
    execution = materialize_acquisition_execution(execution)
    if execution.requirement_state.state_epoch != initial_epoch + 1:
        raise ValueError("REQUIREMENT_STATE_EPOCH_INCREMENT_MISMATCH")
    return RequirementAcquisitionPlanExecutionV01(
        plan_digest=plan.plan_digest,
        validation=validation,
        executed_action_digests=[item.action_digest for item in execution_actions],
        repository_probe_calls=repository_probe_calls,
        planned_candidate_cap_sum=plan.aggregate_budget.planned_candidate_cap_sum,
        initial_requirement_state_epoch=initial_epoch,
        final_requirement_state_epoch=execution.requirement_state.state_epoch,
        execution=execution,
    )


__all__ = [
    "OFFICIAL_EXECUTOR_IDENTITY",
    "AcquisitionProbeCandidateTrace",
    "AcquisitionProbeDisposition",
    "BoundedRangeScanProofV02",
    "EvidenceAcquisitionExecution",
    "EvidenceAcquisitionExecutor",
    "EvidenceAcquisitionMode",
    "RequirementAcquisitionPlanExecutionV01",
]
