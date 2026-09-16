from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
    recovery_plan_candidate_cap,
)
from milai.application.appointment_composition import (
    compose_evidence_range_count,
    normalize_query_time_event_scan,
)
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.query_planner import QueryPlanner
from milai.application.source_time import compile_event_time_point_bucket
from milai.domain import RetrievalRequest
from milai.domain.acquisition import AcquisitionPlan
from milai.domain.acquisition_capability import AcquisitionCapabilitySet
from milai.domain.acquisition_execution_policy import SourceTimePointProfile
from milai.domain.retrieval import QueryPlan
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState, RetrievalRepository

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))
QUERY = "How many babies were born to friends and family in the last few months?"


def test_event_scan_budget_is_not_used_as_generic_candidate_budget() -> None:
    query_ir = _plan().memory_query_ir
    assert query_ir is not None
    policy = default_acquisition_execution_policy()
    assert policy.profiles.event_range_enumeration.max_items == 2_000
    assert recovery_plan_candidate_cap(policy, query_ir) == 256


def _request() -> RetrievalRequest:
    return RetrievalRequest(
        route="L1",
        query=QUERY,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )


def _plan() -> QueryPlan:
    return QueryPlanner().plan(_request())


def _items() -> list[dict[str, object]]:
    return [
        {
            "evidence_id": "late-maya-birth",
            "source_ref": "memory://session/late/turn/0",
            "subject_id": "late",
            # This observation is exactly at the event interval's exclusive end.
            # A source-time slice over that interval misses it, while the governed
            # as-of snapshot includes it.
            "observed_at": REFERENCE.isoformat(),
            "captured_at": REFERENCE.isoformat(),
            "content": "My friend Maya welcomed a baby on January 5th.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
        },
        {
            "evidence_id": "old-nora-birth",
            "source_ref": "memory://session/old/turn/0",
            "subject_id": "old",
            "observed_at": "2023-01-03T09:00:00+00:00",
            "captured_at": "2023-01-03T09:00:01+00:00",
            "content": "My friend Nora welcomed a baby on November 1st, 2022.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
        },
        {
            "evidence_id": "irrelevant-dinner",
            "source_ref": "memory://session/dinner/turn/0",
            "subject_id": "dinner",
            "observed_at": "2023-02-04T09:00:00+00:00",
            "captured_at": "2023-02-04T09:00:01+00:00",
            "content": "My family met for dinner on February 3rd.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
        },
    ]


def _full_snapshot(*, items: list[dict[str, object]] | None = None) -> dict[str, Any]:
    values = _items() if items is None else items
    interval = _plan().operator_arguments["temporal_range"]
    assert isinstance(interval, dict)
    return {
        "status": "COMPLETE",
        "scan_axis": "SOURCE_OBSERVED_TIME",
        "source_snapshot_axis": "SOURCE_OBSERVED_TIME",
        "partition_kind": "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF",
        "source_snapshot_end": (REFERENCE + timedelta(microseconds=1)).isoformat(),
        "event_range_start": interval["start"],
        "event_range_end": interval["end"],
        "event_range_boundary": "CLOSED_OPEN",
        "event_normalization_owner": "DETERMINISTIC_RUNTIME",
        "event_normalization_version": "query-time-event-v1",
        "source_partition_closed": True,
        "projection_watermark_covered": True,
        "projection_watermark": 91,
        "target_watermark": 91,
        "source_count": len(values),
        "projected_count": len(values),
        "returned_count": len(values),
        "max_items": 2_000,
        "dead_letter_gap": False,
        "unreadable_evidence_count": 0,
        "items": values,
    }


class _EventRepository:
    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        self.snapshot = _full_snapshot() if snapshot is None else snapshot
        self.event_calls: list[tuple[datetime, datetime, datetime, int]] = []

    def search_evidence(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        return []

    def search_evidence_event_range(
        self,
        context: SessionContext,
        requested_scope: dict[str, object],
        event_range_start: datetime,
        event_range_end: datetime,
        as_of: datetime,
        max_items: int,
    ) -> dict[str, Any]:
        del context, requested_scope
        self.event_calls.append((event_range_start, event_range_end, as_of, max_items))
        return self.snapshot

    def scan_evidence_range(self) -> None:
        pass


class _RepositoryPrototype(RetrievalRepository):
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, datetime, int, int | None]] = []

    def scan_evidence_range(
        self,
        context: SessionContext,
        requested_scope: dict[str, object],
        range_start: datetime,
        range_end: datetime,
        max_items: int,
        *,
        statement_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        del context, requested_scope
        self.calls.append((range_start, range_end, max_items, statement_timeout_ms))
        return _full_snapshot()


def _capabilities(
    repository: object,
    *,
    query_time_event_enabled: bool,
) -> tuple[AcquisitionPlan, AcquisitionCapabilityPolicy, AcquisitionCapabilitySet]:
    plan = compile_acquisition_plan(
        _plan(),
        query=QUERY,
        principal_scope=_request().requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    policy = AcquisitionCapabilityPolicy()
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            query_time_event_enabled=query_time_event_enabled
        ),
        projection_state=ProjectionState(91, 91, 91, False, False, 91, False),
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        event_occurrence_range=plan.global_constraints.event_occurrence_range,
    )
    return plan, policy, capabilities


def test_temporal_event_capability_is_default_off_and_exact_range_gated() -> None:
    repository = _EventRepository()
    _, _, disabled = _capabilities(repository, query_time_event_enabled=False)
    assert disabled.channels["TEMPORAL_EVENT"].status == "DISABLED"
    assert disabled.channels["TEMPORAL_EVENT"].reason == "POLICY_DISABLED"

    _, _, enabled = _capabilities(repository, query_time_event_enabled=True)
    assert enabled.channels["TEMPORAL_EVENT"].status == "ENABLED"
    assert enabled.channels["TEMPORAL_EVENT"].reason == ("QUERY_TIME_EVENT_NORMALIZATION_READY")
    assert enabled.channels["TEMPORAL_EVENT"].limits["max_items"] == 2_000


def test_event_point_compiles_to_exact_day_bucket_without_axis_substitution() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What kitchen appliance did I buy 10 days ago?",
        requested_scope={"project_ids": ["milai"]},
        as_of=datetime(2023, 3, 25, 18, 26, tzinfo=UTC),
        system_as_of=datetime(2023, 3, 25, 18, 26, tzinfo=UTC),
    )
    query_plan = QueryPlanner().plan(request)
    query_ir = query_plan.memory_query_ir
    assert query_ir is not None
    temporal = query_ir.constraints.normalized_temporal
    assert temporal is not None
    compilation = compile_event_time_point_bucket(temporal, SourceTimePointProfile())

    assert compilation.status == "COMPILED"
    assert compilation.original_axis == "EVENT_TIME"
    assert compilation.time_axis_substitution is False
    assert compilation.semantic_widening is False
    assert compilation.range_start == datetime(2023, 3, 15, tzinfo=UTC)
    assert compilation.range_end == datetime(2023, 3, 16, tzinfo=UTC)
    executable = compilation.executable_range()
    assert executable is not None
    assert executable["time_axis"] == "EVENT_TIME"
    assert executable["boundary"] == "CLOSED_OPEN"

    missing_timezone = compile_event_time_point_bucket(
        temporal.model_copy(update={"timezone": None}),
        SourceTimePointProfile(),
    )
    assert missing_timezone.status == "UNPROVEN"
    assert missing_timezone.reason_code == "EVENT_POINT_TIMEZONE_MISSING"
    assert missing_timezone.executable_range() is None


def test_query_time_normalization_counts_late_report_without_axis_substitution() -> None:
    normalized = normalize_query_time_event_scan(_plan(), _full_snapshot())
    result = compose_evidence_range_count(_plan(), normalized)

    assert normalized["status"] == "COMPLETE"
    assert normalized["scan_axis"] == "EVENT_OCCURRENCE_TIME"
    assert normalized["time_axis_substitution"] is False
    assert normalized["event_range_predicate"] == "CLOSED_OPEN_OVERLAP"
    assert result is not None and result["status"] == "COMPLETE"
    assert result["value"] == 1
    assert result["evidence_refs"] == ["late-maya-birth"]
    assert result["operands"][0]["event_at"].startswith("2023-01-05")
    assert result["operands"][0]["source_timestamp"] == REFERENCE.isoformat()


def test_source_time_slice_cannot_claim_event_time_completeness() -> None:
    result = compose_evidence_range_count(_plan(), _full_snapshot())

    assert result is not None and result["status"] == "PARTIAL"
    assert result["value"] is None
    assert result["reason"] == "EVENT_TIME_DOMAIN_UNPROVEN"
    assert result["completeness"]["scan_temporal_axis"] == "SOURCE_OBSERVED_TIME"


def test_normalization_fails_closed_on_count_watermark_and_dead_letter_gaps() -> None:
    count_gap = _full_snapshot()
    count_gap["source_count"] = 4
    normalized_count_gap = normalize_query_time_event_scan(_plan(), count_gap)
    assert normalized_count_gap["status"] == "PARTIAL"
    assert normalized_count_gap["event_normalization_reason"] == (
        "SOURCE_SNAPSHOT_PROOF_INCOMPLETE"
    )

    watermark_gap = _full_snapshot()
    watermark_gap["projection_watermark_covered"] = False
    normalized_watermark_gap = normalize_query_time_event_scan(_plan(), watermark_gap)
    assert normalized_watermark_gap["status"] == "PARTIAL"

    dead_letter_gap = _full_snapshot()
    dead_letter_gap["dead_letter_gap"] = True
    normalized_dead_letter_gap = normalize_query_time_event_scan(_plan(), dead_letter_gap)
    assert normalized_dead_letter_gap["status"] == "PARTIAL"


def test_relevant_event_without_resolvable_time_never_returns_complete() -> None:
    undated = _items()[0]
    undated["content"] = "My friend welcomed a baby named Rowan."
    normalized = normalize_query_time_event_scan(
        _plan(),
        _full_snapshot(items=[undated]),
    )
    result = compose_evidence_range_count(_plan(), normalized)

    assert result is not None and result["status"] == "PARTIAL"
    assert result["value"] is None
    assert result["reason"] == "EVENT_TIME_UNRESOLVED"


def test_repository_prototype_scans_full_as_of_partition_and_declares_event_contract() -> None:
    repository = _RepositoryPrototype()
    result = repository.search_evidence_event_range(
        CONTEXT,
        {"project_ids": ["milai"]},
        datetime(2022, 12, 27, 12, tzinfo=UTC),
        REFERENCE,
        REFERENCE,
        2_000,
        statement_timeout_ms=700,
    )

    assert repository.calls == [
        (
            datetime.min.replace(tzinfo=UTC),
            REFERENCE + timedelta(microseconds=1),
            2_000,
            700,
        )
    ]
    assert result["partition_kind"] == "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF"
    assert result["scan_axis"] == "SOURCE_OBSERVED_TIME"
    assert result["event_range_boundary"] == "CLOSED_OPEN"
    assert result["event_normalization_owner"] == "DETERMINISTIC_RUNTIME"


def test_official_executor_applies_general_event_point_bucket() -> None:
    reference = datetime(2023, 3, 25, 18, 26, tzinfo=UTC)
    request = RetrievalRequest(
        route="L1",
        query="What kitchen appliance did I buy 10 days ago?",
        requested_scope={"project_ids": ["milai"]},
        as_of=reference,
        system_as_of=reference,
    )
    query_plan = QueryPlanner().plan(request)
    policy = AcquisitionCapabilityPolicy()
    execution_policy = SourceTimePointProfile()
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=request.query or "",
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=4,
        context_tokens=512,
        source_time_point_profile=execution_policy,
    )
    event_range = acquisition_plan.global_constraints.event_occurrence_range
    assert event_range is not None
    snapshot = {
        "status": "COMPLETE",
        "scan_axis": "SOURCE_OBSERVED_TIME",
        "source_snapshot_axis": "SOURCE_OBSERVED_TIME",
        "partition_kind": "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF",
        "source_snapshot_end": (reference + timedelta(microseconds=1)).isoformat(),
        "event_range_start": event_range["start"],
        "event_range_end": event_range["end"],
        "event_range_boundary": "CLOSED_OPEN",
        "event_normalization_owner": "DETERMINISTIC_RUNTIME",
        "event_normalization_version": "query-time-event-v1",
        "source_partition_closed": True,
        "projection_watermark_covered": True,
        "projection_watermark": 92,
        "target_watermark": 92,
        "source_count": 1,
        "projected_count": 1,
        "returned_count": 1,
        "max_items": 2_000,
        "dead_letter_gap": False,
        "unreadable_evidence_count": 0,
        "items": [
            {
                "evidence_id": "smoker-purchase",
                "source_ref": "memory://session/smoker/turn/0",
                "subject_id": "smoker",
                "observed_at": "2023-03-15T19:38:00+00:00",
                "captured_at": "2023-03-15T19:38:01+00:00",
                "content": "I just got a smoker today.",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "revoked_at": None,
            }
        ],
    }
    repository = _EventRepository(snapshot)
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(query_time_event_enabled=True),
        projection_state=ProjectionState(92, 92, 92, False, False, 92, False),
        repository=repository,
        policy=policy,
        generated_at=reference,
        event_occurrence_range=event_range,
    )
    executor = EvidenceAcquisitionExecutor(repository)
    baseline = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    action = next(
        item
        for item in feasible_acquisition_actions(
            baseline.requirement_state,
            capabilities,
            policy,
            event_occurrence_range=event_range,
            remaining_candidates=4,
            acquisition_plan=acquisition_plan,
        )
        if item.channel == "TEMPORAL_EVENT"
    )

    execution = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=baseline.requirement_state,
        existing_results=baseline.results,
    )

    assert event_range["boundary"] == "CLOSED_OPEN"
    assert event_range["time_axis"] == "EVENT_TIME"
    assert event_range["compiled_from_boundary"] == "POINT"
    assert execution.derived_result is not None
    assert execution.derived_result["status"] == "OK"
    assert execution.derived_result["value"]["selected_date"] == "2023-03-15"
    assert execution.derived_result["operands"][0]["time_axis"] == "EVENT_TIME"
    assert execution.bounded_range_scan_proof is not None
    assert execution.bounded_range_scan_proof.scan_closure.scan_axis == (
        "EVENT_OCCURRENCE_TIME"
    )
    assert execution.bounded_range_scan_proof.query_closure.event_time_interval.basis == (
        "EXPLICIT_CALENDAR"
    )
    assert execution.bounded_range_scan_proof.closure_complete is True
    assert repository.event_calls[0][3] == 2_000


def test_official_executor_scans_full_partition_but_hydrates_only_action_budget() -> None:
    request = _request()
    query_plan = _plan()
    repository = _EventRepository()
    acquisition_plan, policy, capabilities = _capabilities(
        repository,
        query_time_event_enabled=True,
    )
    executor = EvidenceAcquisitionExecutor(repository)
    baseline = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    actions = feasible_acquisition_actions(
        baseline.requirement_state,
        capabilities,
        policy,
        event_occurrence_range=(acquisition_plan.global_constraints.event_occurrence_range),
        remaining_candidates=1,
        acquisition_plan=acquisition_plan,
    )
    action = next(item for item in actions if item.channel == "TEMPORAL_EVENT")

    execution = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=baseline.requirement_state,
        existing_results=baseline.results,
    )

    assert repository.event_calls[0][3] == 2_000
    disposition = next(
        item for item in execution.probe_dispositions if item.channel == "TEMPORAL_EVENT"
    )
    assert disposition.raw_candidate_count == 3
    assert disposition.selected_candidate_count == 1
    assert len(execution.candidates) == 1
    assert execution.derived_result is not None
    assert execution.derived_result["status"] == "COMPLETE"
    assert execution.derived_result["value"] == 1
    assert execution.bounded_range_scan_proof is not None
    assert execution.bounded_range_scan_proof.scan_closure.scan_axis == (
        "EVENT_OCCURRENCE_TIME"
    )
    assert execution.bounded_range_scan_proof.event_set_closure.candidate_event_count == 3
    assert action.bounded_cost == {
        "acquisition_passes": 1,
        "candidate_count": 1,
        "model_calls": 0,
    }
    assert execution.context_mutation_performed is False
    assert execution.canonical_mutation is False
