from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue

from milai.application.acquisition import compile_acquisition_plan
from milai.application.evidence import EvidenceIngested
from milai.application.formation_projection import FormationProjectionStore
from milai.application.formation_semantic_replay import (
    ground_formation_semantics,
    specialize_formation_replay_plan,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.evidence import EvidenceIngestRequest, EvidenceSourceContext
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
REFERENCE = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def test_event_entities_keep_actor_relation_but_exclude_temporal_anchor() -> None:
    identity_query = "Did my colleague and my dentist attend the same Atlas workshop?"
    identity_sources = _build_selection(
        identity_query,
        [
            "My colleague Devon Stone and I attended the Atlas workshop on February 3, 2026.",
            (
                "Stone and I attended that same Atlas workshop on February 3, 2026; "
                "my dentist Devon Reed attended a different Atlas workshop on February 18, 2026."
            ),
        ],
    )
    identity_grounded = ground_formation_semantics(*identity_sources)
    identity_events = [
        item
        for item in identity_grounded.interpretations
        if item.kind == "EVENT"
    ]
    colleague = next(
        item
        for item in identity_events
        if "2026-02-03"
        in str(cast(dict[str, Any], item.value)["event_identity"])
        and "colleague" in item.entities
    )
    dentist = next(item for item in identity_events if "dentist" in item.entities)

    assert "dentist" not in colleague.entities
    assert "colleague" not in dentist.entities

    temporal_query = "Which happened first, the workshop or the visit, and when was the visit?"
    temporal_sources = _build_selection(
        temporal_query,
        [
            "I attended the Delta workshop on March 2, 2026.",
            (
                "Two days after the Delta workshop, I visited the Delta fort. "
                "For clarity, I attended that same Delta workshop on March 2, 2026."
            ),
        ],
    )
    temporal_grounded = ground_formation_semantics(*temporal_sources)
    visit = next(
        item
        for item in temporal_grounded.interpretations
        if item.kind == "EVENT"
        and cast(dict[str, Any], item.value).get("event_type") == "visit"
    )

    assert "visit" in visit.entities
    assert "fort" in visit.entities
    assert "workshop" not in visit.entities


def test_specialized_formation_slots_use_the_bounded_hydration_universe() -> None:
    query = "Which happened first, the workshop or the visit, and when was the visit?"
    selection, _hydrated = _build_selection(
        query,
        [
            "I attended the Delta workshop on March 2, 2026.",
            (
                "Two days after the Delta workshop, I visited the Delta fort. "
                "For clarity, I attended that same Delta workshop on March 2, 2026."
            ),
        ],
    )
    request = _query(query)
    plan = QueryPlanner().plan(request)
    acquisition = compile_acquisition_plan(
        plan,
        query=query,
        principal_scope={"project_ids": ["project-a"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=24,
        context_tokens=2_500,
    )

    replay = specialize_formation_replay_plan(
        plan,
        acquisition,
        selection,
        query=query,
    )

    assert replay.specialization == "EVENT_TIME_REPLAY"
    assert replay.acquisition_plan.budget.hydrate_count == 24
    assert replay.query_plan.memory_query_ir is not None
    for requirement in replay.query_plan.memory_query_ir.requirements:
        assert requirement.cardinality.minimum == 1
        assert requirement.cardinality.maximum == 24
        assert requirement.cardinality.distinct is False


def _build_selection(
    query: str,
    contents: list[str],
) -> tuple[Any, list[dict[str, Any]]]:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    hydrated: list[dict[str, Any]] = []
    for index, content in enumerate(contents, start=1):
        evidence_id = UUID(int=1000 + index)
        request = EvidenceIngestRequest(
            source_type="RUNTIME_OBSERVATION",
            source_ref=f"memory://project-a/session-{index}/turn-0",
            subject_id="project-a:self",
            speaker="user",
            source_context=EvidenceSourceContext(
                session_id=f"session-{index}",
                turn_id=f"turn-{index}",
                turn_ordinal=0,
                round_id=f"round-{index}",
                round_ordinal=0,
            ),
            observed_at=REFERENCE - timedelta(hours=len(contents) - index + 1),
            content=content,
            permission_snapshot={"readable": True, "project_ids": ["project-a"]},
            retention_state="READABLE",
        )
        result = EvidenceIngested(
            evidence_id=evidence_id,
            blob_id=UUID(int=2000 + index),
            outbox_id=UUID(int=3000 + index),
            replayed=False,
        )
        store.observe_ingest(context, request, result)
        assert request.source_context is not None
        hydrated.append(
            {
                "evidence_id": str(evidence_id),
                "source_ref": request.source_ref,
                "scope_id": "project-a",
                "subject_id": request.subject_id,
                "speaker": request.speaker,
                "content": request.content,
                "observed_at": request.observed_at.isoformat(),
                "source_context": request.source_context.model_dump(mode="json"),
                "permission_snapshot": dict(request.permission_snapshot),
                "retention_state": request.retention_state,
                "access_decision": "ALLOWED",
                "revoked_at": None,
            }
        )
    selection = store.select(context, _query(query))
    assert selection.status == "SELECTED"
    assert selection.semantic_projection is not None
    return selection, hydrated


def _query(query: str) -> RetrievalRequest:
    return RetrievalRequest(
        route="L1",
        query=query,
        requested_scope=cast(dict[str, JsonValue], {"project_ids": ["project-a"]}),
        entities=["project-a:self"],
        as_of=REFERENCE,
        system_as_of=REFERENCE,
        limit=12,
    )
