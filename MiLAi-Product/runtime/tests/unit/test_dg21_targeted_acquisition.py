from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import JsonValue

from milai.adapters import ProjectionIdentity
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
    select_acquisition_execution_profile,
)
from milai.application.deterministic_recovery import (
    _first_loss,
    _selected_execution_action,
    build_acquisition_observation_v02,
)
from milai.application.evidence_acquisition import (
    AcquisitionProbeDisposition,
    EvidenceAcquisitionExecutor,
)
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_initial_requirement_state
from milai.application.source_time import compile_source_time_point_bucket
from milai.domain.acquisition_capability import FeasibleAcquisitionAction
from milai.domain.acquisition_execution_policy import AcquisitionExecutionSelection
from milai.domain.requirement_state import (
    RejectedCandidateDisposition,
    RequirementCardinalityState,
    RequirementDisposition,
    canonical_sha256,
)
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import NormalizedTemporalConstraint
from milai.domain.sufficiency import SufficiencyDecision
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))
SCOPE: dict[str, JsonValue] = {"project_ids": ["dg21"]}


class _Embedding128:
    dimensions = 128
    identity = ProjectionIdentity(
        provider="test",
        model_id="dg21-test-embedding",
        source_dimensions=128,
        projection_dimensions=128,
        normalization="l2",
        code_version="projection-128/v1",
    )

    def embed(self, _text: str) -> list[float]:
        return [0.0] * self.dimensions

    def embed_many(self, texts: list[str], _batch_size: int) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class _Repository:
    def __init__(self) -> None:
        self.fts_calls: list[dict[str, Any]] = []
        self.dense_calls: list[dict[str, Any]] = []
        self.adjacency_calls: list[dict[str, Any]] = []
        self.range_calls: list[dict[str, Any]] = []
        self.dense_items: list[dict[str, Any]] = []
        self.adjacent_items: list[dict[str, Any]] = []
        self.range_items: list[dict[str, Any]] = []
        self.fts_items: list[dict[str, Any]] = []

    def search_evidence(self, *args: object, **kwargs: object) -> list[dict[str, Any]]:
        self.fts_calls.append({"args": list(args), "kwargs": dict(kwargs)})
        return self.fts_items

    def search_evidence_dense(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.dense_calls.append(dict(kwargs))
        return {"status": "COMPLETE", "items": self.dense_items}

    def hydrate_evidence_adjacency(
        self,
        _context: SessionContext,
        *,
        anchor_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
    ) -> list[dict[str, Any]]:
        self.adjacency_calls.append(
            {
                "anchor_evidence_ids": anchor_evidence_ids,
                "requested_scope": requested_scope,
                "as_of": as_of,
                "max_items": max_items,
            }
        )
        return self.adjacent_items

    def scan_evidence_range(
        self,
        _context: SessionContext,
        requested_scope: dict[str, object],
        range_start: datetime,
        range_end: datetime,
        max_items: int,
    ) -> dict[str, object]:
        self.range_calls.append(
            {
                "requested_scope": requested_scope,
                "range_start": range_start,
                "range_end": range_end,
                "max_items": max_items,
            }
        )
        return {
            "status": "PARTIAL",
            "scan_axis": "SOURCE_OBSERVED_TIME",
            "source_partition_closed": False,
            "projection_watermark_covered": False,
            "projection_watermark": 7,
            "target_watermark": 8,
            "source_count": len(self.range_items),
            "projected_count": len(self.range_items),
            "returned_count": len(self.range_items),
            "max_items": max_items,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
            "items": self.range_items,
        }

    def exact_candidates(self) -> None:
        pass


def _evidence(
    evidence_id: str,
    *,
    content: str,
    session_id: str = "session-a",
    round_ordinal: int = 1,
    project_id: str = "dg21",
    readable: bool = True,
    revoked: bool = False,
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": f"opaque://{evidence_id}",
        "subject_id": session_id,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"turn-{round_ordinal}",
            "turn_ordinal": round_ordinal,
            "round_id": f"round-{round_ordinal}",
            "round_ordinal": round_ordinal,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "observed_at": "2022-04-10T12:00:00+00:00",
        "captured_at": "2022-04-10T12:00:01+00:00",
        "content": content,
        "content_hash": canonical_sha256(content),
        "permission_snapshot": {
            "readable": readable,
            "project_ids": [project_id],
        },
        "retention_state": "READABLE",
        "revoked_at": "2026-01-01T00:00:00+00:00" if revoked else None,
        "relevance_score": 1.0,
    }


def _semantic_inputs(
    repository: _Repository,
    *,
    query: str = "How many days passed between Holi and Sunday mass?",
    candidate_limit: int = 12,
    adjacency: bool = False,
    local_expansion: bool = False,
    source_point: bool = False,
) -> tuple[Any, ...]:
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope=SCOPE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request)
    execution_policy = default_acquisition_execution_policy()
    plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=SCOPE,
        authority_floor="INFORMATIONAL",
        candidate_limit=candidate_limit,
        context_tokens=512,
        enable_enriched=True,
        enable_dense=True,
        enable_same_session_expansion=local_expansion,
        source_time_point_profile=(
            execution_policy.profiles.source_time_point if source_point else None
        ),
    )
    capability_policy = AcquisitionCapabilityPolicy(
        policy_version="dg21-test",
        max_candidates=256,
        max_hydrated_items=8,
    )
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            lexical_enrichment_bound=True,
            lexical_enrichment_enabled=True,
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
            adjacent_turns_acquisition_enabled=adjacency or local_expansion,
        ),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=repository,
        policy=capability_policy,
        generated_at=REFERENCE,
        source_observed_range=plan.global_constraints.source_observed_range,
        event_occurrence_range=plan.global_constraints.event_occurrence_range,
    )
    assert query_plan.memory_query_ir is not None
    state = resolve_initial_requirement_state(
        plan,
        query_plan.memory_query_ir.requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        memory_query_ir=query_plan.memory_query_ir,
    )
    actions = feasible_acquisition_actions(
        state,
        capabilities,
        capability_policy,
        source_observed_range=plan.global_constraints.source_observed_range,
        valid_anchor_available=adjacency,
        remaining_candidates=candidate_limit,
        acquisition_plan=plan,
    )
    return (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    )


def _bound_action(
    selection: AcquisitionExecutionSelection,
    actions: list[FeasibleAcquisitionAction],
) -> FeasibleAcquisitionAction:
    source = next(
        item
        for item in actions
        if item.target_requirement_id == selection.target_requirement_id
        and item.channel == selection.selected_channel
    )
    payload = source.model_dump(mode="json", exclude={"action_digest"})
    payload["bounded_cost"] = {
        "acquisition_passes": selection.effective_budget.acquisition_passes,
        "candidate_count": selection.effective_budget.candidate_count,
        "model_calls": 0,
    }
    return FeasibleAcquisitionAction.model_validate(
        {"action_digest": canonical_sha256(payload), **payload}
    )


def test_first_loss_distinguishes_possible_semantics_from_rejected_candidates() -> None:
    possible = RequirementDisposition(
        requirement_id="EVENT",
        kind="EVENT_SLOT",
        status="MISSING",
        required_cardinality=RequirementCardinalityState(minimum=1, maximum=1),
        observed_cardinality=0,
        proof_status="MISSING",
        possible_binding_refs=["a" * 64],
    )
    rejected = RequirementDisposition(
        requirement_id="EVENT",
        kind="EVENT_SLOT",
        status="MISSING",
        required_cardinality=RequirementCardinalityState(minimum=1, maximum=1),
        observed_cardinality=0,
        proof_status="MISSING",
        rejected_binding_refs=["b" * 64],
        rejected_candidates=[
            RejectedCandidateDisposition(
                candidate_ref="candidate:1",
                binding_ref="b" * 64,
                reason_code="ENTITY_INCOMPATIBLE",
            )
        ],
        rejection_summary={"ENTITY_INCOMPATIBLE": 1},
    )

    assert _first_loss(possible, []) == "BINDING_POSSIBLE_SEMANTICS_OWNER"
    assert _first_loss(rejected, []) == "CANDIDATES_WITHOUT_COMPATIBLE_BINDING"


def test_official_action_binding_preserves_baseline_hydration_below_scan_budget() -> None:
    repository = _Repository()
    (
        _request,
        query_plan,
        _plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    ) = _semantic_inputs(repository)
    assert query_plan.memory_query_ir is not None
    selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 12},
    )

    action = _selected_execution_action(
        selection,
        actions,
        requirement_state=state,
        capability_set=capabilities,
        policy=capability_policy,
    )

    assert action is not None
    assert selection.effective_budget.hydrate_count == 12
    assert capability_policy.max_hydrated_items == 8
    assert action.bounded_cost["candidate_count"] == 8


def test_source_time_point_bucket_preserves_declared_local_precision() -> None:
    policy = default_acquisition_execution_policy()
    temporal = NormalizedTemporalConstraint(
        reference_time=datetime.fromisoformat("2022-04-12T22:57:00+00:00"),
        start=datetime.fromisoformat("2022-04-10T22:57:00+00:00"),
        end=datetime.fromisoformat("2022-04-10T22:57:00+00:00"),
        boundary="POINT",
        time_axis="SOURCE_OBSERVED_TIME",
        precision="DAY",
        timezone="UTC",
    )

    result = compile_source_time_point_bucket(
        temporal,
        policy.profiles.source_time_point,
    )

    assert result.status == "COMPILED"
    assert result.range_start == datetime.fromisoformat("2022-04-10T00:00:00+00:00")
    assert result.range_end == datetime.fromisoformat("2022-04-11T00:00:00+00:00")
    assert result.time_axis_substitution is False
    assert result.semantic_widening is False


def test_source_time_point_bucket_fails_closed_on_invalid_timezone_and_axis() -> None:
    policy = default_acquisition_execution_policy()
    base = {
        "reference_time": "2022-04-12T22:57:00+00:00",
        "start": "2022-04-10T22:57:00+00:00",
        "end": "2022-04-10T22:57:00+00:00",
        "boundary": "POINT",
        "precision": "DAY",
        "timezone": "Not/A_Real_Zone",
    }
    invalid_zone = compile_source_time_point_bucket(
        NormalizedTemporalConstraint.model_validate({**base, "time_axis": "SOURCE_OBSERVED_TIME"}),
        policy.profiles.source_time_point,
    )
    wrong_axis = compile_source_time_point_bucket(
        NormalizedTemporalConstraint.model_validate(
            {**base, "timezone": "UTC", "time_axis": "EVENT_TIME"}
        ),
        policy.profiles.source_time_point,
    )

    assert invalid_zone.status == "UNPROVEN"
    assert invalid_zone.range_start is None and invalid_zone.range_end is None
    assert wrong_axis.status == "UNPROVEN"
    assert wrong_axis.reason_code == "TIME_AXIS_NOT_SOURCE_OBSERVED"


def test_target_action_uses_only_target_probe_and_excludes_seen_candidate() -> None:
    repository = _Repository()
    repeated = _evidence("seen", content="I attended Sunday mass on March 10.")
    target = _evidence("target", content="I joined the Holi festival on March 8.")
    repository.dense_items = [repeated, target]
    (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    ) = _semantic_inputs(repository)
    assert query_plan.memory_query_ir is not None
    selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 12},
    )
    action = _bound_action(selection, actions)

    result = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=plan,
        capability_set=capabilities,
        policy=capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=state,
        existing_results=[repeated],
        type_directed_semantics=True,
        execution_selection=selection,
    )

    assert selection.selected_channel == "EVIDENCE_DENSE"
    assert selection.targeted_only is True
    assert selection.include_global_probe is False
    assert len(repository.dense_calls) == 1
    assert [item.probe_id for item in result.probe_dispositions] == [
        f"slot:{selection.target_requirement_id}:evidence-dense"
    ]
    disposition = result.probe_dispositions[0]
    assert disposition.raw_candidate_count == 2
    assert disposition.selected_candidate_count == 1
    assert disposition.excluded_seen_candidate_count == 1
    assert disposition.repeated_region_count == 1
    assert {item["evidence_id"] for item in result.results} == {"seen", "target"}
    target_candidate = next(
        item for item in result.candidates if item.source_evidence_id == "target"
    )
    assert target_candidate.matched_slots == [selection.target_requirement_id]


def test_selector_does_not_repeat_an_executed_target_channel() -> None:
    repository = _Repository()
    (
        _request,
        query_plan,
        _plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    ) = _semantic_inputs(repository)
    target_id = state.missing_requirement_ids[0]
    observation = build_acquisition_observation_v02(
        requirement_state=state,
        capability_set=capabilities,
        policy=capability_policy,
        probe_dispositions=[
            AcquisitionProbeDisposition(
                probe_id=f"slot:{target_id}:evidence-dense",
                requirement_id=target_id,
                channel="EVIDENCE_DENSE",
                status="EXECUTED",
                reason_code="EXECUTED",
                raw_candidate_count=0,
                selected_candidate_count=0,
                latency_ms=1,
            )
        ],
        feasible_actions=actions,
        remaining_budget={
            "acquisition_passes": 1,
            "candidate_count": 12,
            "model_calls": 0,
        },
    )
    assert query_plan.memory_query_ir is not None

    selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 12},
        observation=observation,
    )

    assert selection.selected_channel == "FTS_ENRICHED"


def test_official_executor_rejects_stale_target_action() -> None:
    repository = _Repository()
    (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    ) = _semantic_inputs(repository)
    assert query_plan.memory_query_ir is not None
    selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 12},
    )
    source = _bound_action(selection, actions)
    payload = source.model_dump(mode="json", exclude={"action_digest"})
    payload["requirement_state_digest"] = "f" * 64
    stale = FeasibleAcquisitionAction.model_validate(
        {"action_digest": canonical_sha256(payload), **payload}
    )

    try:
        EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
            context=CONTEXT,
            request=request,
            query_plan=query_plan,
            acquisition_plan=plan,
            capability_set=capabilities,
            policy=capability_policy,
            mode="SHADOW_NO_CONTEXT_MUTATION",
            state_epoch=1,
            action=stale,
            current_requirement_state=state,
            type_directed_semantics=True,
            execution_selection=selection,
        )
    except ValueError as exc:
        assert str(exc) == "STALE_REQUIREMENT_STATE"
    else:
        raise AssertionError("stale target action was accepted")


def test_adjacency_enforces_radius_session_scope_lifecycle_and_caps() -> None:
    repository = _Repository()
    anchor = _evidence("anchor", content="I am considering a local trip.")
    valid = _evidence(
        "valid",
        content="I want to visit Denver soon.",
        round_ordinal=3,
    )
    repository.adjacent_items = [
        anchor,
        valid,
        _evidence("cross-session", content="wrong", session_id="session-b"),
        _evidence("outside-radius", content="wrong", round_ordinal=4),
        _evidence("cross-scope", content="wrong", project_id="other"),
        _evidence("unreadable", content="wrong", readable=False),
        _evidence("revoked", content="wrong", revoked=True),
    ]
    (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    ) = _semantic_inputs(repository, adjacency=True)
    observation = build_acquisition_observation_v02(
        requirement_state=state,
        capability_set=capabilities,
        policy=capability_policy,
        probe_dispositions=[],
        feasible_actions=actions,
        remaining_budget={
            "acquisition_passes": 1,
            "candidate_count": 12,
            "model_calls": 0,
        },
        valid_adjacency_anchor_count=1,
    )
    assert query_plan.memory_query_ir is not None
    unrelated_anchor_selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 12},
        observation=observation,
    )
    assert unrelated_anchor_selection.selected_channel == "EVIDENCE_DENSE"

    target_id = state.missing_requirement_ids[0]
    material = observation.model_dump(mode="json", exclude={"observation_digest"})
    for requirement in material["requirements"]:
        if requirement["requirement_id"] == target_id:
            requirement["matched_evidence_refs"] = ["anchor"]
    observation = type(observation).model_validate(
        {"observation_digest": canonical_sha256(material), **material}
    )
    selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 12},
        observation=observation,
    )
    action = _bound_action(selection, actions)

    result = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=plan,
        capability_set=capabilities,
        policy=capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=state,
        existing_results=[anchor],
        type_directed_semantics=True,
        execution_selection=selection,
    )

    assert selection.selected_channel == "ADJACENT_TURNS"
    assert repository.adjacency_calls[0]["anchor_evidence_ids"] == ["anchor"]
    assert repository.adjacency_calls[0]["max_items"] == 4
    assert {item["evidence_id"] for item in result.results} == {"anchor", "valid"}
    disposition = result.probe_dispositions[0]
    assert disposition.requirement_id == selection.target_requirement_id
    assert disposition.repeated_region_count == 1
    assert disposition.new_region_count == 1


def test_initial_acquisition_expands_only_bounded_same_session_turns() -> None:
    repository = _Repository()
    anchor = _evidence(
        "00000000-0000-0000-0000-000000000101",
        content="I attended Holi and later mentioned Sunday mass.",
        round_ordinal=4,
    )
    answer = _evidence(
        "00000000-0000-0000-0000-000000000102",
        content="The two events were three days apart.",
        round_ordinal=5,
    )
    cross_session = _evidence(
        "00000000-0000-0000-0000-000000000103",
        content="A tempting answer from another session.",
        session_id="session-b",
        round_ordinal=5,
    )
    unreadable = _evidence(
        "00000000-0000-0000-0000-000000000104",
        content="An unreadable same-session answer.",
        round_ordinal=5,
        readable=False,
    )
    repository.fts_items = [anchor]
    repository.adjacent_items = [anchor, cross_session, unreadable, answer]
    (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        _execution_policy,
        _state,
        _actions,
    ) = _semantic_inputs(
        repository,
        candidate_limit=6,
        local_expansion=True,
    )

    result = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=plan,
        capability_set=capabilities,
        policy=capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
        type_directed_semantics=True,
    )

    assert repository.adjacency_calls == [
        {
            "anchor_evidence_ids": [anchor["evidence_id"]],
            "requested_scope": SCOPE,
            "as_of": REFERENCE,
            "max_items": 4,
        }
    ]
    assert {item["evidence_id"] for item in result.results} == {
        anchor["evidence_id"],
        answer["evidence_id"],
    }
    assert len(result.results) <= plan.budget.hydrate_count
    answer_candidate = next(
        item for item in result.candidates if item.source_evidence_id == answer["evidence_id"]
    )
    assert answer_candidate.expansion_origin == "ADJACENT_TURNS"
    disposition = next(
        item
        for item in result.probe_dispositions
        if item.probe_id == "planned:same-session-local-expansion"
    )
    assert disposition.reason_code == "SAME_SESSION_BOUNDED"
    assert disposition.raw_candidate_count == 4
    assert disposition.selected_candidate_count == 1
    assert disposition.repeated_region_count == 1


def test_initial_acquisition_does_not_expand_when_locality_treatment_is_off() -> None:
    repository = _Repository()
    repository.fts_items = [
        _evidence(
            "00000000-0000-0000-0000-000000000111",
            content="I attended Holi and later mentioned Sunday mass.",
        )
    ]
    repository.adjacent_items = [
        _evidence(
            "00000000-0000-0000-0000-000000000112",
            content="The two events were three days apart.",
            round_ordinal=2,
        )
    ]
    (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        _execution_policy,
        _state,
        _actions,
    ) = _semantic_inputs(repository, adjacency=True)

    EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=plan,
        capability_set=capabilities,
        policy=capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
        type_directed_semantics=True,
    )

    assert repository.adjacency_calls == []


def test_source_point_plan_and_official_scan_use_exact_compiled_bucket() -> None:
    repository = _Repository()
    repository.range_items = [_evidence("point-hit", content="I mentioned cooking with a friend.")]
    query = "I mentioned cooking with a friend a couple of days ago. What was it?"
    (
        request,
        query_plan,
        plan,
        capability_policy,
        capabilities,
        execution_policy,
        state,
        actions,
    ) = _semantic_inputs(
        repository,
        query=query,
        candidate_limit=128,
        source_point=True,
    )
    assert query_plan.memory_query_ir is not None
    temporal = query_plan.memory_query_ir.constraints.normalized_temporal
    assert temporal is not None
    assert temporal.time_axis == "SOURCE_OBSERVED_TIME"
    assert temporal.precision == "DAY"
    assert temporal.timezone == "UTC"
    compiled = plan.global_constraints.source_observed_range
    assert compiled is not None
    assert compiled["boundary"] == "CLOSED_OPEN"
    assert compiled["compiled_from_boundary"] == "POINT"
    selection = select_acquisition_execution_profile(
        policy=execution_policy,
        query_ir=query_plan.memory_query_ir,
        requirement_state=state,
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=state.missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=capabilities,
        remaining_budget={"acquisition_passes": 1, "candidate_count": 128},
    )
    action = _bound_action(selection, actions)

    result = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=plan,
        capability_set=capabilities,
        policy=capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=state,
        type_directed_semantics=True,
        execution_selection=selection,
    )

    assert selection.selected_channel == "SOURCE_OBSERVED_RANGE_SCAN"
    assert repository.range_calls[0]["range_start"] == datetime.fromisoformat(
        "2026-08-26T00:00:00+00:00"
    )
    assert repository.range_calls[0]["range_end"] == datetime.fromisoformat(
        "2026-08-27T00:00:00+00:00"
    )
    assert repository.range_calls[0]["max_items"] == 128
    assert result.bounded_range_scan_proof is not None
    assert result.bounded_range_scan_proof.query_closure.event_time_interval.basis == (
        "SOURCE_OBSERVED_PROXY"
    )
    assert result.bounded_range_scan_proof.closure_complete is False
