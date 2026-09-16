from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from milai.application import formation_projection as formation_projection_module
from milai.application.evidence import EvidenceIngested
from milai.application.formation_projection import FormationProjectionStore
from milai.domain.evidence import EvidenceIngestRequest, EvidenceSourceContext
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_projection_build_and_exact_replay_are_deterministic() -> None:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    request, result = _ingest(
        "10000000-0000-4000-8000-000000000001",
        "I currently live in Lisbon.",
    )

    store.observe_ingest(context, request, result)
    first = store.select(context, _query("Where do I currently live?"))
    store.observe_ingest(
        context,
        request,
        EvidenceIngested(
            evidence_id=result.evidence_id,
            blob_id=result.blob_id,
            outbox_id=result.outbox_id,
            replayed=True,
        ),
    )
    second = store.select(context, _query("Where do I currently live?"))

    assert first.status == "SELECTED"
    assert first.evidence_ids == (str(result.evidence_id),)
    assert first.build_epoch == 1
    assert first.projection_digest == second.projection_digest
    assert first.build_epoch == second.build_epoch
    assert first.canonical_mutation is False
    assert first.model_calls == 0


def test_projection_defers_full_build_until_first_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    original = formation_projection_module.DEFAULT_FORMATION_ENGINE
    calls = 0

    class CountingEngine:
        def build(self, sources):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return original.build(sources)

    monkeypatch.setattr(
        formation_projection_module,
        "DEFAULT_FORMATION_ENGINE",
        CountingEngine(),
    )
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    for suffix, content in ((10, "I live in Bern."), (11, "I moved to Ghent.")):
        request, result = _ingest(
            f"10000000-0000-4000-8000-{suffix:012d}",
            content,
        )
        store.observe_ingest(context, request, result)
    assert calls == 0

    first = store.select(context, _query("Where do I live?"))
    second = store.select(context, _query("Where do I live?"))

    assert first.status == "SELECTED"
    assert second.projection_digest == first.projection_digest
    assert calls == 1


def test_projection_requires_exact_project_and_unambiguous_subject_partition() -> None:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    first_request, first_result = _ingest(
        "10000000-0000-4000-8000-000000000002",
        "I live in Riga.",
        subject_id="project-a:self",
    )
    second_request, second_result = _ingest(
        "10000000-0000-4000-8000-000000000003",
        "I live in Oslo.",
        subject_id="project-a:colleague",
    )
    store.observe_ingest(context, first_request, first_result)
    store.observe_ingest(context, second_request, second_result)

    no_scope = store.select(
        context,
        _query("Where do I live?", project_ids=[]),
    )
    ambiguous = store.select(
        context,
        _query("Where do I live?", entities=[]),
    )
    exact = store.select(
        context,
        _query("Where do I live?", entities=["project-a:self"]),
    )
    other_tenant = store.select(
        SessionContext(OTHER_TENANT_ID, ACTOR_ID),
        _query("Where do I live?"),
    )

    assert no_scope.reason_code == "FORMATION_PROJECT_SCOPE_NOT_EXACT"
    assert ambiguous.reason_code == "FORMATION_SUBJECT_AMBIGUOUS"
    assert exact.evidence_ids == (str(first_result.evidence_id),)
    assert other_tenant.reason_code == "FORMATION_PARTITION_NOT_FOUND"


def test_projection_abstains_on_unrelated_generic_query() -> None:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    request, result = _ingest(
        "10000000-0000-4000-8000-000000000004",
        "I attended the Atlas gala on August 2, 2026.",
    )
    store.observe_ingest(context, request, result)

    selection = store.select(context, _query("What is my passport number?"))

    assert selection.status == "NO_MATCH"
    assert selection.evidence_ids == ()
    assert selection.formation_complete is False


def test_projection_selects_from_an_as_of_view_without_future_evidence() -> None:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    current_request, current_result = _ingest(
        "10000000-0000-4000-8000-000000000007",
        "I currently live in Lisbon.",
    )
    future_request, future_result = _ingest(
        "10000000-0000-4000-8000-000000000008",
        "I currently live in Bath.",
        observed_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
    )
    store.observe_ingest(context, current_request, current_result)
    store.observe_ingest(context, future_request, future_result)

    selection = store.select(context, _query("Where do I currently live?"))

    assert selection.status == "SELECTED"
    assert selection.evidence_ids == (str(current_result.evidence_id),)
    assert str(future_result.evidence_id) not in selection.evidence_ids
    assert selection.source_count == 1


def test_projection_falls_back_when_all_sources_are_after_as_of() -> None:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    future_request, future_result = _ingest(
        "10000000-0000-4000-8000-000000000009",
        "I currently live in Bath.",
        observed_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
    )
    store.observe_ingest(context, future_request, future_result)

    selection = store.select(context, _query("Where do I currently live?"))

    assert selection.status == "RAW_FALLBACK"
    assert selection.reason_code == "FORMATION_NO_SOURCES_AS_OF"
    assert selection.evidence_ids == ()


def test_revoke_and_namespace_cleanup_remove_ephemeral_sources() -> None:
    store = FormationProjectionStore()
    context = SessionContext(TENANT_ID, ACTOR_ID)
    request, result = _ingest(
        "10000000-0000-4000-8000-000000000005",
        "I currently live in Bath.",
    )
    store.observe_ingest(context, request, result)
    assert store.select(context, _query("Where do I currently live?")).evidence_ids

    store.revoke(context, result.evidence_id)
    revoked = store.select(context, _query("Where do I currently live?"))
    assert revoked.reason_code == "FORMATION_PARTITION_NOT_FOUND"

    next_request, next_result = _ingest(
        "10000000-0000-4000-8000-000000000006",
        "I currently live in Cork.",
    )
    store.observe_ingest(context, next_request, next_result)
    store.drop_project(context, "project-a")
    dropped = store.select(context, _query("Where do I currently live?"))
    assert dropped.reason_code == "FORMATION_PARTITION_NOT_FOUND"


def _ingest(
    evidence_id: str,
    content: str,
    *,
    subject_id: str = "project-a:self",
    observed_at: datetime = datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
) -> tuple[EvidenceIngestRequest, EvidenceIngested]:
    identifier = UUID(evidence_id)
    request = EvidenceIngestRequest(
        source_type="RUNTIME_OBSERVATION",
        source_ref=f"memory://project-a/session-1/{evidence_id}",
        subject_id=subject_id,
        speaker="user",
        source_context=EvidenceSourceContext(
            session_id="session-1",
            turn_id=evidence_id,
            turn_ordinal=0,
            round_id="round-0",
            round_ordinal=0,
        ),
        observed_at=observed_at,
        content=content,
        permission_snapshot={"readable": True, "project_ids": ["project-a"]},
        retention_state="READABLE",
    )
    result = EvidenceIngested(
        evidence_id=identifier,
        blob_id=UUID(int=identifier.int + 100),
        outbox_id=UUID(int=identifier.int + 200),
        replayed=False,
    )
    return request, result


def _query(
    query: str,
    *,
    project_ids: list[str] | None = None,
    entities: list[str] | None = None,
) -> RetrievalRequest:
    return RetrievalRequest(
        route="L1",
        query=query,
        requested_scope=cast(
            dict[str, JsonValue],
            {"project_ids": ["project-a"] if project_ids is None else project_ids},
        ),
        entities=["project-a:self"] if entities is None else entities,
        as_of=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
        system_as_of=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
    )
