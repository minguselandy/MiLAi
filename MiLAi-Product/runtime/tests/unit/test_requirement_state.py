from __future__ import annotations

from datetime import UTC, datetime

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
    validate_feasible_action,
)
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_requirement_state
from milai.domain import CandidateEnvelope, RetrievalRequest, SufficiencyDecision
from milai.persistence.retrieval_repository import ProjectionState

REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)


class _RepositorySurface:
    def search_evidence(self) -> None:
        pass

    def search_evidence_dense(self) -> None:
        pass

    def scan_evidence_range(self) -> None:
        pass

    def hydrate_evidence_adjacency(self) -> None:
        pass

    def exact_candidates(self) -> None:
        pass


def _compiled(query: str):  # type: ignore[no-untyped-def]
    query_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            requested_scope={"project_ids": ["milai"]},
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    assert query_plan.memory_query_ir is not None
    return query_plan.memory_query_ir, acquisition_plan


def _capabilities(*, source_range: bool = False):  # type: ignore[no-untyped-def]
    policy = AcquisitionCapabilityPolicy()
    capability_set = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(
            canonical_snapshot_outbox_sequence=7,
            fts_watermark=7,
            vector_watermark=7,
            fts_dead_letter=False,
            vector_dead_letter=False,
            evidence_watermark=7,
            evidence_dead_letter=False,
        ),
        repository=_RepositorySurface(),
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=(
            {
                "start": "2026-08-01T00:00:00+00:00",
                "end": "2026-09-01T00:00:00+00:00",
                "boundary": "CLOSED_OPEN",
            }
            if source_range
            else None
        ),
    )
    return policy, capability_set


def test_requirement_state_digest_is_deterministic_and_excludes_generation_time() -> None:
    query_ir, plan = _compiled("How many times did I visit Paris last month?")
    policy, capability_set = _capabilities(source_range=True)
    later_capability_set = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=_RepositorySurface(),
        policy=policy,
        generated_at=datetime(2026, 8, 28, 9, tzinfo=UTC),
        source_observed_range={
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-09-01T00:00:00+00:00",
            "boundary": "CLOSED_OPEN",
        },
    )
    assert capability_set.capability_digest == later_capability_set.capability_digest
    decision = SufficiencyDecision(
        status="UNSATISFIED",
        missing_slots=[],
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )
    first = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_set.capability_digest,
        sufficiency_decision=decision,
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    second = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_set.capability_digest,
        sufficiency_decision=decision,
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    assert first == second
    assert first.state_digest == second.state_digest
    disposition = first.requirements[0]
    assert disposition.kind == "CARDINALITY"
    assert disposition.status == "COMPLETENESS_PROOF_MISSING"


def test_sufficiency_covered_slot_without_binding_cannot_be_satisfied() -> None:
    query_ir, plan = _compiled("How much did I pay per ceramic mug?")
    _policy, capability_set = _capabilities()
    state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_set.capability_digest,
        sufficiency_decision=SufficiencyDecision(
            status="COMPLETE",
            covered_slots=["TOTAL_PRICE", "ITEM_COUNT"],
            stop_reason="REQUIREMENT_SATISFIED",
        ),
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    assert state.satisfied_requirement_ids == []
    assert state.missing_requirement_ids == ["ITEM_COUNT", "TOTAL_PRICE"]


def test_accepted_binding_and_sufficiency_are_both_required_for_satisfaction() -> None:
    query_ir, plan = _compiled("How much did I pay per ceramic mug?")
    _policy, capability_set = _capabilities()
    source = {
        "evidence_id": "evidence-47",
        "source_ref": "memory://session/s-1/turn/0",
        "subject_id": "s-1",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": REFERENCE.isoformat(),
        "content": "I paid $60 for 5 ceramic mugs.",
        "content_hash": "source-hash",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
    spans = project_evidence_spans([source])
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(query_ir.requirements, interpretations, spans)
    candidate = CandidateEnvelope(
        candidate_id="evidence-47",
        source_evidence_id="evidence-47",
        source_turn_ref="memory://session/s-1/turn/0",
        subject_id="subject-47",
        session_id="s-1",
        turn_id="s-1:turn:0",
        identity_source="STRUCTURED_TURN_METADATA",
        speaker="user",
        speaker_source="STRUCTURED_TURN_METADATA",
        source_observed_at=REFERENCE,
        matched_probes=["global:fts-raw"],
        matched_slots=["ITEM_COUNT", "TOTAL_PRICE"],
        channel_ranks={"FTS_RAW": 1},
        channel_scores={"FTS_RAW": 1.0},
        probe_ranks={"global:fts-raw": 1},
        probe_scores={"global:fts-raw": 1.0},
        fusion_rank=1,
        fusion_score=1.0,
        matched_fields=["lexical_text"],
        body_ref="memory://session/s-1/turn/0",
        body_hydrated=True,
    )
    state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_set.capability_digest,
        candidates=[candidate],
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        sufficiency_decision=SufficiencyDecision(
            status="COMPLETE",
            covered_slots=["TOTAL_PRICE", "ITEM_COUNT"],
            stop_reason="REQUIREMENT_SATISFIED",
        ),
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    assert state.satisfied_requirement_ids == ["ITEM_COUNT", "TOTAL_PRICE"]
    assert all(item.accepted_binding_refs for item in state.requirements)
    assert all(item.accepted_evidence_refs == ["evidence-47"] for item in state.requirements)


def test_feasible_actions_exclude_satisfied_and_fail_closed_on_stale_state() -> None:
    query_ir, plan = _compiled("How many times did I visit Paris last month?")
    policy, capability_set = _capabilities(source_range=True)
    state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=capability_set.capability_digest,
        sufficiency_decision=SufficiencyDecision(
            status="UNSATISFIED",
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    actions = feasible_acquisition_actions(
        state,
        capability_set,
        policy,
        source_observed_range=plan.global_constraints.source_observed_range,
    )
    assert actions
    # The query compiler owns an EVENT_TIME interval.  Even though the repository
    # can execute source-observed scans, that capability is not applicable here.
    assert {item.channel for item in actions} == {"FTS_RAW"}
    assert capability_set.channels["TEMPORAL_EVENT"].reason == "POLICY_DISABLED"
    stale = state.model_copy(update={"state_epoch": 1})
    validation = validate_feasible_action(actions[0], stale, capability_set, policy)
    assert validation.accepted is False
    assert validation.reason_code == "STALE_REQUIREMENT_STATE"


def test_point_source_time_is_dispositioned_before_closed_open_execution() -> None:
    policy = AcquisitionCapabilityPolicy()
    capability_set = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
        ),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=_RepositorySurface(),
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range={
            "start": "2026-08-18T08:00:00Z",
            "end": "2026-08-18T08:00:00Z",
            "boundary": "POINT",
        },
    )

    dense = capability_set.channels["EVIDENCE_DENSE"]
    assert dense.status == "UNAVAILABLE"
    assert dense.reason == "SOURCE_TIME_FILTER_UNAVAILABLE"
    source_scan = capability_set.channels["SOURCE_OBSERVED_RANGE_SCAN"]
    assert source_scan.status == "UNAVAILABLE"
    assert source_scan.reason == "SOURCE_RANGE_BOUNDARY_UNSUPPORTED"
