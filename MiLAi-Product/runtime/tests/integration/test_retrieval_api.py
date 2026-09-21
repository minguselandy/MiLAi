from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain import CausalTokenCodec
from milai.persistence import Database, DatabaseUnavailable, SessionContext
from milai.persistence.context_repository import ContextRepository
from milai.persistence.projection_repository import ProjectionRepository
from milai.persistence.retrieval_repository import ProjectionUnavailable, RetrievalRepository
from milai.workers.main import FoundationWorker

pytestmark = pytest.mark.integration

ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
REVIEWER_TOKEN = "reviewer-token-with-at-least-32-characters"
CAUSAL_TOKEN_SECRET = "test-causal-secret-with-at-least-32-characters"
SCOPE = {"project_ids": ["milai"]}


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture
def retrieval_runtime(tmp_path: Path):  # type: ignore[no-untyped-def]
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=uuid4(),
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        agent_reviewer_token=REVIEWER_TOKEN,
        causal_token_secret=CAUSAL_TOKEN_SECRET,
        worker_event_limit=10_000,
        worker_retry_delay_seconds=0,
        worker_max_attempts=1,
    )
    prepare_runtime_directories(settings)
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    worker_database = Database(settings, dsn=_url("MILAI_TEST_WORKER_DATABASE_URL"))
    app = create_app(settings, database=api_database, steward_database=steward_database)
    app.config["TESTING"] = True
    yield settings, app, worker_database
    api_database.close()
    steward_database.close()
    worker_database.close()


def _headers(key: str | None = None, request_id: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {API_TOKEN}"}
    if key is not None:
        result["Idempotency-Key"] = key
    if request_id is not None:
        result["X-Request-ID"] = request_id
    return result


def _review_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {REVIEWER_TOKEN}",
        "Idempotency-Key": key,
    }


def _ingest(client, content: str) -> str:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v1/evidence",
        headers=_headers(f"evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"retrieval-test://{uuid4()}",
            "subject_id": "retrieval-test",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    assert response.status_code == 201
    return str(response.json["evidence_id"])


def _create_claim(
    client,  # type: ignore[no-untyped-def]
    token: str,
    *,
    authority: str = "ACTION_SAFE",
    valid_time_from: str | None = None,
    lifecycle: str | None = None,
    epistemic_status: str | None = None,
    freshness: str | None = None,
    confidence: float = 0.99,
    value: object = "current",
    subject_id: str | None = None,
    claim_type: str = "FACT",
) -> dict[str, str]:
    evidence_id = _ingest(client, f"grounding for {token}")
    patch: dict[str, object] = {
        "subject_id": subject_id or f"subject-{uuid4()}",
        "predicate": "runtime.retrieval.fact",
        "claim_type": claim_type,
        "payload": {"token": token, "value": value},
        "authority": authority,
        "confidence": confidence,
    }
    if valid_time_from is not None:
        patch["valid_time_from"] = valid_time_from
    if lifecycle is not None:
        patch["lifecycle"] = lifecycle
    if epistemic_status is not None:
        patch["epistemic_status"] = epistemic_status
    if freshness is not None:
        patch["freshness"] = freshness
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": patch,
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": SCOPE,
            "requested_authority": authority,
            "derivation_policy_id": "retrieval-test-v1",
            "derivation_snapshot": {"fixture": "retrieval"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "retrieval-test-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    return {
        "claim_id": str(review.json["claim_id"]),
        "claim_version_id": str(review.json["claim_version_id"]),
        "evidence_id": evidence_id,
        "outbox_id": str(review.json["outbox_id"]),
    }


def _supersede(client, claim: dict[str, str], token: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    evidence_id = _ingest(client, f"replacement grounding for {token}")
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"supersede-{uuid4()}"),
        json={
            "target_claim_id": claim["claim_id"],
            "operation": "SUPERSEDE",
            "expected_version_id": claim["claim_version_id"],
            "proposed_patch": {
                "payload": {"token": token, "value": "replacement"},
                "authority": "ACTION_SAFE",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": SCOPE,
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "retrieval-test-v1",
            "derivation_snapshot": {"fixture": "retrieval-supersede"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "retrieval-test-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    return {
        "claim_id": str(review.json["claim_id"]),
        "claim_version_id": str(review.json["claim_version_id"]),
        "evidence_id": evidence_id,
        "outbox_id": str(review.json["outbox_id"]),
    }


def _causal_token(client, *outbox_ids: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v1/causal-tokens",
        headers=_headers(),
        json={"outbox_ids": list(outbox_ids)},
    )
    assert response.status_code == 201
    return dict(response.json)


def _run_worker(settings: RuntimeSettings, database: Database, worker_id: str) -> None:
    worker = FoundationWorker(
        settings,
        database,
        repository=ProjectionRepository(database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=worker_id,
    )
    assert worker.run_once() > 0


def _query(client, payload: dict[str, object], request_id: str | None = None):  # type: ignore[no-untyped-def]
    return client.post(
        "/v1/retrieval/query",
        headers=_headers(request_id=request_id),
        json=payload,
    )


def _reject_reason(client, payload: dict[str, object]) -> str:  # type: ignore[no-untyped-def]
    response = _query(client, payload)
    assert response.status_code == 200
    assert response.json["abstained"] is True
    trace = client.get(
        f"/v1/retrieval-traces/{response.json['retrieval_trace_id']}",
        headers=_headers(),
    )
    assert trace.status_code == 200
    return str(trace.json["rejected_candidates"][0]["reject_reason"])


@pytest.mark.integration
def test_exact_evidence_hydration_rechecks_scope_as_of_and_revocation(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()

    def capture(
        *, project_id: str, observed_at: str, content: str, turn: int
    ) -> str:
        response = client.post(
            "/v1/evidence",
            headers=_headers(f"formation-hydration-{uuid4()}"),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"formation-hydration://session/{turn}",
                "subject_id": f"{project_id}:self",
                "speaker": "user",
                "source_context": {
                    "session_id": f"session-{project_id}",
                    "turn_id": f"turn-{turn}",
                    "turn_ordinal": turn,
                    "round_id": f"round-{turn}",
                    "round_ordinal": turn,
                },
                "observed_at": observed_at,
                "content": content,
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": [project_id],
                },
                "retention_state": "READABLE",
            },
        )
        assert response.status_code == 201
        return str(response.json["evidence_id"])

    allowed = capture(
        project_id="project-a",
        observed_at="2026-08-20T00:00:00+00:00",
        content="I currently live in Lisbon.",
        turn=0,
    )
    cross_scope = capture(
        project_id="project-b",
        observed_at="2026-08-20T00:00:00+00:00",
        content="I currently live in Oslo.",
        turn=1,
    )
    future = capture(
        project_id="project-a",
        observed_at="2026-09-20T00:00:00+00:00",
        content="I currently live in Bath.",
        turn=2,
    )
    _run_worker(settings, worker_database, "formation-hydration-worker")

    repository = RetrievalRepository(app.extensions["milai.database"])
    context = SessionContext(settings.tenant_id, ACTOR_ID)
    hydrated = repository.hydrate_evidence_by_ids(
        context,
        evidence_ids=[cross_scope, allowed, future],
        requested_scope={"project_ids": ["project-a"]},
        as_of=datetime(2026, 8, 31, tzinfo=UTC),
        max_items=3,
    )

    assert [item["evidence_id"] for item in hydrated] == [allowed]
    assert hydrated[0]["speaker"] == "user"
    assert hydrated[0]["sidecar_channel"] == "FORMED_SOURCE_HYDRATION"
    assert hydrated[0]["canonical"] is False

    revoke = client.post(
        f"/v1/evidence/{allowed}/revoke",
        headers=_headers(f"formation-hydration-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202
    after_revoke = repository.hydrate_evidence_by_ids(
        context,
        evidence_ids=[allowed],
        requested_scope={"project_ids": ["project-a"]},
        as_of=datetime(2026, 8, 31, tzinfo=UTC),
        max_items=1,
    )
    assert after_revoke == []


@pytest.mark.integration
def test_formation_off_shadow_canary_and_restart_preserve_raw_authority(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, off_app, worker_database = retrieval_runtime
    canary_settings = settings.model_copy(update={"feature_profile": "FORMED_CANARY"})
    canary_app = create_app(
        canary_settings,
        database=off_app.extensions["milai.database"],
        steward_database=off_app.extensions["milai.steward_database"],
    )
    canary_app.config["TESTING"] = True
    canary_client = canary_app.test_client()
    ingest_key = f"formation-canary-ingest-{uuid4()}"
    ingest_payload = {
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": "formation-canary://session-1/turn-0",
        "subject_id": "project-formation:self",
        "speaker": "user",
        "source_context": {
            "session_id": "formation-session-1",
            "turn_id": "formation-turn-0",
            "turn_ordinal": 0,
            "round_id": "formation-round-0",
            "round_ordinal": 0,
        },
        "observed_at": "2026-08-20T00:00:00+00:00",
        "content": "I prefer aisle seats over window seats.",
        "media_type": "text/plain",
        "permission_snapshot": {
            "readable": True,
            "project_ids": ["project-formation"],
        },
        "retention_state": "READABLE",
    }
    ingested = canary_client.post(
        "/v1/evidence",
        headers=_headers(ingest_key),
        json=ingest_payload,
    )
    assert ingested.status_code == 201
    evidence_id = str(ingested.json["evidence_id"])
    _run_worker(settings, worker_database, "formation-canary-worker")

    query_payload = {
        "query": "What preference should be recalled?",
        "requested_scope": {"project_ids": ["project-formation"]},
        "required_authority": "INFORMATIONAL",
        "required_freshness": "CURRENT",
        "consistency_mode": "CANONICAL_REQUIRED",
        "budget": {
            "max_results": 12,
            "max_candidates": 24,
            "max_context_tokens": 2500,
            "max_latency_ms": 2000,
        },
        "entities": ["project-formation:self"],
    }
    off_before = off_app.test_client().post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-off-{uuid4()}"),
        json=query_payload,
    )
    canary = canary_client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-canary-{uuid4()}"),
        json=query_payload,
    )
    assert off_before.status_code == 200
    assert canary.status_code == 200
    assert evidence_id not in off_before.json["evidence_refs"]
    assert evidence_id not in canary.json["evidence_refs"]
    formation_trace = canary.json["search_trace"]["formation_projection"]
    assert formation_trace["mode"] == "CANARY"
    assert formation_trace["applied"] is True
    assert formation_trace["full_semantics_recomputed"] is True
    assert formation_trace["raw_baseline_preserved"] is True
    assert formation_trace["canonical_mutation"] is False
    assert formation_trace["model_calls"] == 0
    assert formation_trace["new_governed_candidate_count"] == 1
    assert formation_trace["new_accepted_binding_count"] == 0

    shadow_settings = settings.model_copy(update={"feature_profile": "FORMED_SHADOW"})
    shadow_app = create_app(
        shadow_settings,
        database=off_app.extensions["milai.database"],
        steward_database=off_app.extensions["milai.steward_database"],
    )
    shadow_app.config["TESTING"] = True
    shadow_client = shadow_app.test_client()
    replay = shadow_client.post(
        "/v1/evidence",
        headers=_headers(ingest_key),
        json=ingest_payload,
    )
    assert replay.status_code == 200
    assert replay.json["replayed"] is True
    shadow = shadow_client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-shadow-{uuid4()}"),
        json=query_payload,
    )
    assert shadow.status_code == 200
    assert _memory_semantics(shadow.json) == _memory_semantics(off_before.json)
    assert shadow.json["search_trace"]["formation_projection"]["shadow_only"] is True
    assert shadow.json["search_trace"]["formation_projection"]["applied"] is False

    restarted_canary = create_app(
        canary_settings,
        database=off_app.extensions["milai.database"],
        steward_database=off_app.extensions["milai.steward_database"],
    )
    restarted_canary.config["TESTING"] = True
    after_restart = restarted_canary.test_client().post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-restart-{uuid4()}"),
        json=query_payload,
    )
    off_after = off_app.test_client().post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-rollback-{uuid4()}"),
        json=query_payload,
    )
    assert _memory_semantics(after_restart.json) == _memory_semantics(off_before.json)
    assert _memory_semantics(off_after.json) == _memory_semantics(off_before.json)
    assert (
        after_restart.json["search_trace"]["formation_projection"]["reason_code"]
        == "FORMATION_PARTITION_NOT_FOUND"
    )

    wrong_scope = canary_client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-wrong-scope-{uuid4()}"),
        json={
            **query_payload,
            "requested_scope": {"project_ids": ["project-other"]},
        },
    )
    assert wrong_scope.status_code == 200
    assert evidence_id not in wrong_scope.json["evidence_refs"]

    revoke = canary_client.post(
        f"/v1/evidence/{evidence_id}/revoke",
        headers=_headers(f"formation-canary-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202
    after_revoke = canary_client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id=f"formation-after-revoke-{uuid4()}"),
        json=query_payload,
    )
    assert after_revoke.status_code == 200
    assert evidence_id not in after_revoke.json["evidence_refs"]

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as connection:
        assert connection.execute(
            "SELECT to_regclass('milai.formation_projection')"
        ).fetchone() == (None,)


def _memory_semantics(value: dict[str, object]) -> dict[str, object]:
    return {
        key: value.get(key)
        for key in (
            "status",
            "requirement",
            "items",
            "evidence_refs",
            "derived_result",
            "abstention_reason",
        )
    }


@pytest.mark.integration
def test_l0_uses_canonical_gate_without_vector_and_l2_is_disabled(retrieval_runtime) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = retrieval_runtime
    client = app.test_client()
    claim = _create_claim(client, f"l0token{uuid4().hex}")

    response = _query(
        client,
        {
            "route": "L0",
            "claim_id": claim["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert response.status_code == 200
    assert response.json["abstained"] is False, response.json
    assert response.json["results"][0]["claim_version_id"] == claim["claim_version_id"]
    assert response.json["results"][0]["matched_by"] == ["l0"]

    disabled = _query(client, {"route": "L2"})
    assert disabled.status_code == 422
    assert disabled.json["error"]["code"] == "ROUTE_DISABLED"


@pytest.mark.integration
def test_l1_merges_fts_vector_and_persists_payload_free_append_only_trace(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"mergetoken{uuid4().hex}"
    claim = _create_claim(client, token)
    _run_worker(settings, worker_database, "retrieval-merge-worker")
    causal = _causal_token(client, claim["outbox_id"])

    response = _query(
        client,
        {
            "route": "L1",
            "query": token,
            "consistency": "READ_YOUR_WRITES",
            "causal_token": causal["causal_token"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
        request_id="retrieval-merge-request",
    )
    assert response.status_code == 200
    assert response.json["results"][0]["claim_version_id"] == claim["claim_version_id"]
    assert response.json["results"][0]["matched_by"] == ["fts", "vector"]
    assert response.json["fallback_used"] is False
    assert (
        response.json["query_plan"]["planner_version"]
        == "lean-query-plan-v12-dg17-ir-v02"
    )
    assert (
        response.json["query_plan"]["minimum_outbox_sequence"] == causal["minimum_outbox_sequence"]
    )
    assert response.json["causal_wait"]["outcome"] == "REACHED"
    assert "minimum_commit_seq" not in response.json["query_plan"]
    assert response.json["query_plan"]["complexity"] == "L1"
    assert token not in json.dumps(response.json["query_plan"])
    stage_metrics = response.json["stage_metrics"]
    assert {
        "canonical_gate_ms",
        "fts_ms",
        "fusion_ms",
        "query_embedding_ms",
        "query_total_ms",
        "trace_write_ms",
        "vector_ms",
    } <= set(stage_metrics["durations_ms"])
    assert stage_metrics["durations_ms"]["query_total_ms"] >= sum(
        duration
        for stage, duration in stage_metrics["durations_ms"].items()
        if stage != "query_total_ms"
    )
    assert token not in json.dumps(stage_metrics)
    access_trace = response.json["access_trace"]
    assert access_trace["schema_version"] == "access-trace-v0.1"
    assert access_trace["requested_intent"] is None
    assert access_trace["planned_stage"] == "SEARCH"
    assert access_trace["attempted_stages"] == [
        "EXACT",
        "FTS",
        "VECTOR",
        "CANONICAL_GATE",
        "HYDRATE",
        "SUFFICIENCY",
    ]
    assert access_trace["terminal_stage"] == "VECTOR"
    assert access_trace["canonical_position"] >= 1
    assert access_trace["route_trace_complete"] is True
    assert token not in json.dumps(access_trace)

    contract_alias = client.post(
        "/v1/memory/query",
        headers=_headers(),
        json={
            "route": "L1",
            "query": token,
            "consistency": "READ_YOUR_WRITES",
            "causal_token": causal["causal_token"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert contract_alias.status_code == 200
    assert contract_alias.json["results"][0]["claim_version_id"] == claim["claim_version_id"]

    watermarks = client.get("/v1/system/watermarks", headers=_headers())
    assert watermarks.status_code == 200
    assert {item["projection"] for item in watermarks.json["watermarks"]} == {
        "evidence",
        "fts",
        "vector",
    }
    assert all(item["lag"] >= 0 for item in watermarks.json["watermarks"])

    routes = client.get("/v1/system/degraded-routes", headers=_headers())
    assert routes.status_code == 200
    assert routes.json["routes"]["L0"] == {"degraded": False, "enabled": True}
    assert routes.json["routes"]["L2"]["reason"] == "ROUTE_DISABLED"

    trace_id = response.json["retrieval_trace_id"]
    trace = client.get(f"/v1/retrieval-traces/{trace_id}", headers=_headers())
    assert trace.status_code == 200
    assert trace.json["request_id"] == "retrieval-merge-request"
    assert trace.json["query_plan"] == response.json["query_plan"]
    assert trace.json["minimum_outbox_sequence"] == causal["minimum_outbox_sequence"]
    assert trace.json["causal_wait_outcome"] == "REACHED"
    assert trace.json["execution_trace"]["schema_version"] == "retrieval-execution-v1"
    assert trace.json["execution_trace"]["route_trace_complete"] is True
    assert trace.json["stage_metrics"]["counts"]["query_total_ms"] == 1
    assert trace.json["access_trace"]["retrieval_trace_id"] == trace_id
    assert trace.json["access_trace"]["runtime_request_id"] == "retrieval-merge-request"
    assert len(trace.json["query_fingerprint"]) == 64
    assert token not in json.dumps(trace.json)

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as api_connection:
        api_connection.execute(
            "SELECT set_config('milai.tenant_id', %s, false)", (str(settings.tenant_id),)
        )
        api_connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        with pytest.raises(psycopg.Error):
            api_connection.execute(
                """
                UPDATE milai.retrieval_trace SET duration_ms = duration_ms + 1
                WHERE tenant_id = %s AND trace_id = %s
                """,
                (settings.tenant_id, trace_id),
            )

    signature = (
        "milai.record_retrieval_trace(uuid,uuid,text,text,text,text,jsonb,jsonb,"
        "timestamptz,text,bigint,bigint,bigint,jsonb,jsonb,boolean,text,boolean,"
        "text,integer,bigint,text,integer,jsonb,jsonb)"
    )
    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as api_connection:
        assert api_connection.execute(
            "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
            (signature,),
        ).fetchone()[0]
    with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward_connection:
        assert not steward_connection.execute(
            "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
            (signature,),
        ).fetchone()[0]


@pytest.mark.integration
def test_query_first_memory_resolve_is_task_free_typed_and_governed(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"resolvecurrent{uuid4().hex}"
    claim = _create_claim(
        client,
        token,
        valid_time_from="2026-08-25T00:00:00+00:00",
    )
    _run_worker(settings, worker_database, "memory-resolve-worker")

    hit = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-hit"),
        json={
            "query": f"What is the current {token} status?",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "budget": {"max_results": 3},
            "entities": [token],
            "temporal": {"mode": "CURRENT"},
        },
    )
    assert hit.status_code == 200
    assert hit.json["schema_version"] == "access-outcome-v0.1"
    assert hit.json["status"] == "HIT", hit.json
    assert hit.json["memory_intent"] == "REQUIRED"
    assert hit.json["requirement"] == "EXACT"
    assert hit.json["availability"] == "AVAILABLE"
    assert hit.json["sufficiency_decision"]["status"] == "PARTIAL"
    assert hit.json["derived_result"]["operand_authority"] == "CANONICAL_GATE_ONLY"
    assert hit.json["items"][0]["claim_version_id"] == claim["claim_version_id"]
    assert hit.json["evidence_refs"] == [claim["evidence_id"]]
    assert hit.json["context_receipt"]["schema_version"] == "context-receipt-v0.1"
    assert hit.json["trace_id"] is not None
    assert hit.json["access_trace"]["requested_intent"] == "CURRENT_STATE"
    assert hit.json["access_trace"]["planned_stage"] == "SEARCH"
    encoded_hit = json.dumps(hit.json).lower()
    assert '"task_id"' not in encoded_hit
    assert '"task_context"' not in encoded_hit
    assert '"task_enhancement"' not in encoded_hit

    for language, query in (
        ("zh", f"当前 {token} 状态是什么?"),
        ("mixed", f"Recall 当前 {token} status"),
    ):
        localized = client.post(
            "/v1/memory/resolve",
            headers=_headers(request_id=f"memory-resolve-{language}"),
            json={
                "query": query,
                "requested_scope": SCOPE,
                "required_authority": "ACTION_SAFE",
                "budget": {"max_results": 3},
            },
        )
        assert localized.status_code == 200
        assert localized.json["status"] == "HIT", localized.json
        assert localized.json["memory_intent"] == "REQUIRED"
        assert localized.json["requirement"] == "EXACT"
        assert localized.json["items"][0]["claim_version_id"] == claim["claim_version_id"]

    absent = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"What is unrecorded{uuid4().hex}?",
            "requested_scope": {"project_ids": ["empty-project"]},
        },
    )
    assert absent.status_code == 200
    assert absent.json["status"] == "ABSENT"
    assert absent.json["memory_intent"] == "REQUIRED"
    assert absent.json["requirement"] == "SEARCH"
    assert absent.json["items"] == []
    assert absent.json["abstention_reason"] == "NO_CANDIDATE"

    wrong_scope = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"What is the current {token} status?",
            "requested_scope": {"project_ids": ["other-project"]},
            "required_authority": "ACTION_SAFE",
        },
    )
    assert wrong_scope.status_code == 200
    assert wrong_scope.json["status"] in {"ABSENT", "ABSTAINED"}
    assert wrong_scope.json["items"] == []

    insufficient = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"Recall: what is the recorded value for {token}?",
            "requested_scope": SCOPE,
            "required_authority": "USER_CONFIRMED",
        },
    )
    assert insufficient.status_code == 200
    assert insufficient.json["status"] == "ABSTAINED"
    assert insufficient.json["abstention_reason"] == "CANONICAL_GATE_REJECTED"
    assert insufficient.json["items"] == []

    revoke = client.post(
        f"/v1/evidence/{claim['evidence_id']}/revoke",
        headers=_headers(f"resolve-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202
    revoked = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"Recall: what is the recorded value for {token}?",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert revoked.status_code == 200
    assert revoked.json["status"] == "ABSTAINED"
    assert revoked.json["items"] == []
    assert revoked.json["abstention_reason"] == "CANONICAL_GATE_REJECTED"

    malformed = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={"query": token, "task_id": "must-not-be-accepted"},
    )
    assert malformed.status_code == 400
    assert malformed.json["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.integration
def test_possible_query_keeps_compact_canonical_hit_within_reader_budget(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"resolvepossible{uuid4().hex}"
    claim = _create_claim(client, token)
    _run_worker(settings, worker_database, "memory-resolve-possible-worker")

    possible = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-possible-hit"),
        json={
            "query": f"What is the recorded value for {token}?",
            "invocation_mode": "PREFETCH_AUTO",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "budget": {"max_results": 3},
        },
    )

    assert possible.status_code == 200
    assert possible.json["status"] == "HIT", possible.json
    assert possible.json["memory_intent"] == "POSSIBLE"
    assert possible.json["requirement"] == "SEARCH"
    assert possible.json["access_plan"]["context_token_budget"] == 768
    assert possible.json["items"][0]["claim_version_id"] == claim["claim_version_id"]
    assert possible.json["search_trace"]["context_budget_truncated"] is False


@pytest.mark.integration
def test_memory_resolve_hard_partitions_entity_type_scope_and_time_before_vector(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"partitiontoken{uuid4().hex}"
    selected = _create_claim(
        client,
        token,
        subject_id="release-alpha",
        claim_type="PROJECT_STATE",
    )
    _create_claim(
        client,
        token,
        subject_id="release-beta",
        claim_type="PERSONAL_FACT",
    )
    _run_worker(settings, worker_database, "memory-resolve-partition-worker")

    response = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-hard-partitions"),
        json={
            "query": f"Recall: what is the recorded value for {token}?",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "entities": ["release-alpha"],
            "memory_types": ["PROJECT_STATE"],
            "budget": {
                "max_results": 3,
                "max_candidates": 30,
                "max_context_tokens": 2500,
                "max_latency_ms": 500,
            },
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == "HIT", response.json
    assert [item["claim_version_id"] for item in response.json["items"]] == [
        selected["claim_version_id"]
    ]
    access_plan = response.json["access_plan"]
    assert access_plan["candidate_cap"] == 30
    assert access_plan["hard_partitions"] == [
        "tenant",
        "principal_scope",
        "project_scope",
        "valid_time",
        "entity",
        "memory_type",
    ]
    trace = response.json["access_trace"]
    assert trace["attempted_stages"].index("FTS") < trace["attempted_stages"].index(
        "CANONICAL_GATE"
    )
    assert "VECTOR" not in trace["attempted_stages"]
    assert "CANONICAL_FALLBACK" not in trace["attempted_stages"]
    progressive = response.json["search_trace"]
    assert progressive["candidate_counts"].get("vector", 0) == 0
    assert progressive["deadline_outcome"] == "MET"
    assert (
        progressive["context_token_upper_bound"]
        <= access_plan["context_token_budget"]
    )


@pytest.mark.integration
def test_optional_task_context_matched_query_narrows_without_changing_authority(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"taskcontext{uuid4().hex}"
    selected = _create_claim(
        client,
        token,
        subject_id="release-alpha",
        claim_type="PROJECT_STATE",
    )
    _create_claim(
        client,
        token,
        subject_id="release-beta",
        claim_type="PERSONAL_FACT",
    )
    _run_worker(settings, worker_database, "memory-resolve-task-context-worker")
    base_payload = {
        "query": f"Recall: what is the recorded value for {token}?",
        "requested_scope": SCOPE,
        "required_authority": "INFORMATIONAL",
        "budget": {
            "max_results": 3,
            "max_candidates": 30,
            "max_context_tokens": 2500,
            "max_latency_ms": 500,
        },
    }

    task_off = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-task-off"),
        json=base_payload,
    )
    task_on = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-task-on"),
        json={
            **base_payload,
            "task_context": {
                "project_ids": ["milai"],
                "entities": ["release-alpha"],
                "memory_types": ["PROJECT_STATE"],
                "action_risk": "HIGH",
            },
        },
    )

    assert task_off.status_code == task_on.status_code == 200
    assert task_off.json["status"] == task_on.json["status"] == "HIT"
    expected = selected["claim_version_id"]
    assert expected in [item["claim_version_id"] for item in task_off.json["items"]]
    assert [item["claim_version_id"] for item in task_on.json["items"]] == [expected]
    assert "task_enhancement" not in task_off.json
    enhancement = task_on.json["task_enhancement"]
    assert enhancement["applied"] is True
    assert enhancement["authority_unchanged"] is True
    assert enhancement["action_risk_non_authoritative"] is True
    assert task_on.json["access_plan"]["hard_partitions"][-2:] == [
        "entity",
        "memory_type",
    ]
    assert (
        task_on.json["search_trace"]["context_token_upper_bound"]
        < task_off.json["search_trace"]["context_token_upper_bound"]
    )

    task_on_receipt = task_on.json["context_receipt"]
    reused_task_off = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-task-on-reused-task-off"),
        json={
            **base_payload,
            "entities": ["release-alpha"],
            "memory_types": ["PROJECT_STATE"],
            "previous_context_id": task_on_receipt["context_capsule_id"],
        },
    )
    assert reused_task_off.status_code == 200
    assert reused_task_off.json["receipt_reused"] is True
    assert reused_task_off.json["trace_id"] == task_on.json["trace_id"]
    assert "task_enhancement" not in reused_task_off.json
    assert all(
        not str(key).lower().startswith("task")
        for key in reused_task_off.json
    )


@pytest.mark.integration
def test_task_context_cannot_widen_host_project_scope(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = retrieval_runtime
    response = app.test_client().post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-task-scope-widening"),
        json={
            "query": "Recall release state",
            "requested_scope": SCOPE,
            "task_context": {"project_ids": ["attacker-project"]},
        },
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.integration
def test_possible_probe_database_deadline_is_typed_and_does_not_escalate(
    retrieval_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = retrieval_runtime
    client = app.test_client()

    def slow_exact(
        repository: RetrievalRepository,
        context: SessionContext,
        *_args: object,
        statement_timeout_ms: int | None = None,
        **_kwargs: object,
    ) -> list[object]:
        with repository._database.connection(
            context,
            read_only=True,
            statement_timeout_ms=statement_timeout_ms,
        ) as connection:
            connection.execute("SELECT pg_sleep(0.1)").fetchone()
        return []

    monkeypatch.setattr(RetrievalRepository, "exact_candidates", slow_exact)
    response = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-search-deadline"),
        json={
            "query": "Could this affect the release?",
            "requested_scope": SCOPE,
            "budget": {
                "max_results": 3,
                "max_candidates": 30,
                "max_context_tokens": 768,
                "max_latency_ms": 25,
            },
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == "ABSTAINED"
    assert response.json["abstention_reason"] == "SEARCH_BUDGET_EXHAUSTED"
    assert response.json["search_trace"]["deadline_outcome"] == "EXHAUSTED"
    assert response.json["search_trace"]["stop_stage"] == "BUDGET"
    assert "VECTOR" not in response.json["access_trace"]["attempted_stages"]


@pytest.mark.integration
def test_search_context_token_cap_keeps_whole_canonical_items_or_abstains(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"largecontext{uuid4().hex}"
    _create_claim(client, token, value="x" * 2_000)
    _run_worker(settings, worker_database, "memory-resolve-context-budget-worker")

    response = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-context-budget"),
        json={
            "query": f"Recall: what is the recorded value for {token}?",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "budget": {
                "max_results": 3,
                "max_candidates": 30,
                "max_context_tokens": 128,
                "max_latency_ms": 500,
            },
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == "ABSTAINED"
    assert response.json["items"] == []
    assert response.json["abstention_reason"] == "CONTEXT_TOKEN_BUDGET_EXCEEDED"
    assert response.json["search_trace"]["context_budget_truncated"] is True
    assert response.json["search_trace"]["context_token_upper_bound"] <= 128
    assert "context_budget" in response.json["degraded_components"]


@pytest.mark.integration
def test_query_first_memory_resolve_preserves_live_open_issue_refs(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"resolveconflict{uuid4().hex}"
    claim = _create_claim(
        client,
        token,
        valid_time_from="2026-08-25T00:00:00+00:00",
    )
    original = client.get(f"/v1/claims/{claim['claim_id']}", headers=_headers())
    assert original.status_code == 200
    original_system_time = original.json["system_time"]
    _run_worker(settings, worker_database, "memory-resolve-conflict-worker")

    contradicting_evidence = _ingest(client, f"contradicting grounding for {token}")
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"resolve-conflict-{uuid4()}"),
        json={
            "target_claim_id": claim["claim_id"],
            "operation": "CONTRADICT",
            "expected_version_id": claim["claim_version_id"],
            "proposed_patch": {},
            "contradicting_evidence_refs": [contradicting_evidence],
            "scope_predicate": SCOPE,
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "retrieval-conflict-v1",
            "derivation_snapshot": {"fixture": "memory-resolve-conflict"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"resolve-conflict-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "retrieval-conflict-v1",
            "reason_code": "CONFLICT_CONFIRMED",
        },
    )
    assert review.status_code == 200
    issue_id = review.json["open_issue_id"]

    contested = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-resolve-contested"),
        json={
            "query": f"Are there conflicting branches for memory {token}?",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert contested.status_code == 200
    assert contested.json["status"] == "CONTESTED", contested.json
    assert contested.json["open_issue_ids"] == [issue_id]
    assert contested.json["items"] == []
    assert contested.json["interpretation"]["retrieval_intent"] == "CONFLICT"
    assert contested.json["abstention_reason"] == "CANONICAL_GATE_REJECTED"

    exact_contested = client.post(
        "/v1/memory/get",
        headers=_headers(request_id="memory-state-contested"),
        json={
            "claim_id": claim["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert exact_contested.status_code == 200
    assert exact_contested.json["status"] == "CONTESTED", exact_contested.json
    assert exact_contested.json["items"] == []
    assert exact_contested.json["open_issue_ids"] == [issue_id]
    assert exact_contested.json["resolution"] | {
        "addressable": True,
        "reachable": True,
        "correctly_resolved": True,
    } == exact_contested.json["resolution"]
    assert exact_contested.json["access_trace"]["structural_cost"] == {
        "auxiliary_llm_calls": 0,
        "embedding_calls": 0,
        "vector_search_calls": 0,
        "reranker_calls": 0,
        "broad_head_scan_calls": 0,
    }

    before_issue_existed = client.post(
        "/v1/memory/get",
        headers=_headers(request_id="memory-state-before-open-issue"),
        json={
            "claim_id": claim["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "valid_at": "2026-08-25T12:00:00+00:00",
            "known_at": original_system_time,
        },
    )
    assert before_issue_existed.status_code == 200
    assert before_issue_existed.json["status"] == "HIT", before_issue_existed.json
    assert before_issue_existed.json["open_issue_ids"] == []
    assert before_issue_existed.json["items"][0]["claim_version_id"] == claim[
        "claim_version_id"
    ]


@pytest.mark.integration
def test_memory_state_view_is_dynamic_bitemporal_and_exact_cost_bounded(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = retrieval_runtime
    client = app.test_client()
    token = f"stateview{uuid4().hex}"
    original = _create_claim(
        client,
        token,
        valid_time_from="2026-08-25T00:00:00+00:00",
        value="original",
    )
    canonical = client.get(f"/v1/claims/{original['claim_id']}", headers=_headers())
    assert canonical.status_code == 200
    state_key = {
        "subject": canonical.json["subject_id"],
        "predicate": canonical.json["predicate"],
        "claim_type": canonical.json["claim_type"],
    }
    original_system_time = canonical.json["system_time"]

    by_state_key = client.post(
        "/v1/memory/get",
        headers=_headers(request_id="memory-state-current"),
        json={
            "state_key": state_key,
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert by_state_key.status_code == 200
    assert by_state_key.json["schema_version"] == "memory-state-view-v0.1"
    assert by_state_key.json["status"] == "HIT", by_state_key.json
    assert by_state_key.json["items"][0]["claim_version_id"] == original["claim_version_id"]
    assert by_state_key.json["items"][0]["payload"]["value"] == "original"
    assert by_state_key.json["resolution"] | {
        "mode": "CURRENT",
        "addressable": True,
        "reachable": True,
        "correctly_resolved": True,
    } == by_state_key.json["resolution"]
    assert {
        "derivation_policy_id",
        "model_id",
        "template_id",
        "scope_predicate",
        "matched_by",
        "relevance_score",
    }.isdisjoint(by_state_key.json["items"][0])
    access_trace = by_state_key.json["access_trace"]
    assert access_trace["sufficiency_decision"]["status"] == "COMPLETE", access_trace
    assert access_trace["sufficiency_decision"]["missing_slots"] == []
    assert access_trace["sufficiency_decision"]["covered_slots"] == ["EXACT_STATE"]
    assert access_trace["planned_stage"] == "EXACT"
    assert access_trace["terminal_stage"] == "EXACT"
    assert access_trace["spans"]["state_address_ms"] >= 0
    assert access_trace["spans"]["repository_sql_ms"] >= access_trace["spans"][
        "state_address_ms"
    ]
    assert access_trace["resolution_dimensions"] == {
        "addressable": True,
        "reachable": True,
        "correctly_resolved": True,
    }
    assert access_trace["structural_cost"] == {
        "auxiliary_llm_calls": 0,
        "embedding_calls": 0,
        "vector_search_calls": 0,
        "reranker_calls": 0,
        "broad_head_scan_calls": 0,
    }

    exact_resolve = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-state-resolve"),
        json={
            "query": "Read the exact current state.",
            "state_keys": [state_key],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert exact_resolve.status_code == 200
    assert exact_resolve.json["status"] == "HIT", exact_resolve.json
    assert exact_resolve.json["requirement"] == "EXACT"
    assert exact_resolve.json["state_view_schema_version"] == "memory-state-view-v0.1"
    assert exact_resolve.json["items"][0]["claim_version_id"] == original["claim_version_id"]
    assert exact_resolve.json["access_trace"]["structural_cost"] == access_trace[
        "structural_cost"
    ]

    replacement = _supersede(client, original, token)
    current = client.post(
        "/v1/memory/get",
        headers=_headers(),
        json={
            "claim_id": original["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert current.status_code == 200
    assert current.json["items"][0]["claim_version_id"] == replacement["claim_version_id"]
    assert current.json["items"][0]["payload"]["value"] == "replacement"
    assert current.json["access_trace"]["sufficiency_decision"]["status"] == "COMPLETE"

    historical = client.post(
        "/v1/memory/get",
        headers=_headers(request_id="memory-state-historical"),
        json={
            "claim_id": original["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "valid_at": "2026-08-25T12:00:00+00:00",
            "known_at": original_system_time,
        },
    )
    assert historical.status_code == 200
    assert historical.json["status"] == "HIT", historical.json
    assert historical.json["resolution"]["mode"] == "HISTORICAL"
    assert historical.json["items"][0]["claim_version_id"] == original["claim_version_id"]
    assert historical.json["items"][0]["payload"]["value"] == "original"
    assert historical.json["access_trace"]["structural_cost"] == access_trace[
        "structural_cost"
    ]
    historical_resolve_payload = {
        "query": "Recall the exact historical state",
        "claim_ids": [original["claim_id"]],
        "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
        "valid_at": "2026-08-25T12:00:00+00:00",
        "known_at": original_system_time,
    }
    historical_resolve = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-state-historical-resolve"),
        json=historical_resolve_payload,
    )
    assert historical_resolve.status_code == 200
    assert historical_resolve.json["status"] == "HIT", historical_resolve.json
    historical_receipt = historical_resolve.json["context_receipt"]
    historical_reuse = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="memory-state-historical-reuse"),
        json={
            **historical_resolve_payload,
            "previous_context_id": historical_receipt["context_capsule_id"],
        },
    )
    assert historical_reuse.status_code == 200
    assert historical_reuse.json["status"] == "HIT", historical_reuse.json
    assert historical_reuse.json["receipt_reused"] is True
    assert historical_reuse.json["items"][0]["claim_version_id"] == original[
        "claim_version_id"
    ]

    scoped_out = client.post(
        "/v1/memory/get",
        headers=_headers(),
        json={
            "state_key": state_key,
            "requested_scope": {"project_ids": ["not-milai"]},
            "required_authority": "ACTION_SAFE",
        },
    )
    assert scoped_out.status_code == 200
    assert scoped_out.json["status"] == "ABSENT"
    assert scoped_out.json["items"] == []
    assert scoped_out.json["resolution"]["addressable"] is False
    assert scoped_out.json["resolution"]["reachable"] is False
    assert scoped_out.json["resolution"]["correctly_resolved"] is False
    assert scoped_out.json["access_trace"]["sufficiency_decision"]["status"] != "COMPLETE"

    malformed = client.post(
        "/v1/memory/get",
        headers=_headers(),
        json={"claim_id": original["claim_id"], "state_key": state_key},
    )
    assert malformed.status_code == 400
    assert malformed.json["error"]["code"] == "INVALID_REQUEST"

    unresolved_multi_target = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": "Read exact state",
            "claim_ids": [original["claim_id"], str(uuid4())],
            "requested_scope": SCOPE,
        },
    )
    assert unresolved_multi_target.status_code == 400
    assert unresolved_multi_target.json["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.integration
def test_task_free_context_receipt_reuses_and_misses_fall_back_in_same_call(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, _worker_database = retrieval_runtime
    client = app.test_client()
    claim = _create_claim(client, f"receipthit{uuid4().hex}")
    payload: dict[str, object] = {
        "query": "Read the exact current receipt state",
        "claim_ids": [claim["claim_id"]],
        "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
    }

    first = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-first"),
        json=payload,
    )
    assert first.status_code == 200
    assert first.json["status"] == "HIT", first.json
    receipt = first.json["context_receipt"]
    assert receipt["schema_version"] == "context-receipt-v0.1"
    assert receipt["freshness_at_issue"] == "CURRENT"
    assert receipt["consistency_mode_at_issue"] == "CANONICAL_REQUIRED"
    not_owner = ContextRepository(app.extensions["milai.database"]).validate_task_free_capsule(
        SessionContext(settings.tenant_id, uuid4()),
        UUID(receipt["context_capsule_id"]),
        expected_coverage=receipt["requirement_coverage"],
        requested_scope=SCOPE,
        required_authority="ACTION_SAFE",
        required_freshness="CURRENT",
        valid_at=datetime.now(UTC),
        known_at=datetime.now(UTC),
        historical=False,
    )
    assert not_owner.valid is False
    assert not_owner.reason == "RECEIPT_NOT_FOUND_OR_NOT_OWNED"
    capsule = client.get(
        f"/v1/context-capsules/{receipt['context_capsule_id']}",
        headers=_headers(),
    )
    assert capsule.status_code == 200
    assert set(capsule.json["protected_sections"]) == {
        "MEMORY STATE VIEW",
        "OPEN ISSUE IDS",
        "RETRIEVED EVIDENCE",
        "TRACE POINTERS",
        "RECEIPT METADATA",
    }
    assert "ACTIVE GOAL" not in capsule.json["protected_sections"]
    assert "CONSTRAINTS" not in capsule.json["protected_sections"]

    reused = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-reused"),
        json={**payload, "previous_context_id": receipt["context_capsule_id"]},
    )
    assert reused.status_code == 200
    assert reused.json["status"] == "HIT"
    assert reused.json["receipt_reused"] is True
    assert reused.json["trace_id"] == first.json["trace_id"]
    assert reused.json["access_trace"]["attempted_stages"] == ["REUSE_VALIDATION"]
    assert reused.json["access_trace"]["terminal_stage"] == "REUSE"
    assert reused.json["access_trace"]["structural_cost"] == {
        "auxiliary_llm_calls": 0,
        "embedding_calls": 0,
        "vector_search_calls": 0,
        "reranker_calls": 0,
        "broad_head_scan_calls": 0,
    }

    with psycopg.connect(_url("MILAI_TEST_DATABASE_URL")) as owner:
        owner.execute(
            "SELECT set_config('milai.tenant_id', %s, true)",
            (str(settings.tenant_id),),
        )
        owner.execute(
            """
            UPDATE milai.context_capsule
            SET expires_at = CURRENT_TIMESTAMP - interval '1 second'
            WHERE tenant_id = %s AND capsule_id = %s
            """,
            (settings.tenant_id, UUID(receipt["context_capsule_id"])),
        )
    expired = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-expired"),
        json={**payload, "previous_context_id": receipt["context_capsule_id"]},
    )
    assert expired.status_code == 200
    assert expired.json["status"] == "HIT"
    assert expired.json["receipt_reused"] is False
    assert expired.json["receipt_fallback_reason"] == "RECEIPT_EXPIRED"

    missing = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-missing"),
        json={**payload, "previous_context_id": str(uuid4())},
    )
    assert missing.status_code == 200
    assert missing.json["status"] == "HIT"
    assert missing.json["receipt_reused"] is False
    assert missing.json["receipt_fallback_reason"] == (
        "RECEIPT_NOT_FOUND_OR_NOT_OWNED"
    )
    assert missing.json["access_trace"]["attempted_stages"][0] == (
        "REUSE_VALIDATION"
    )
    assert missing.json["access_trace"]["terminal_stage"] == "EXACT"
    fresh_receipt = missing.json["context_receipt"]

    scope_changed = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-scope-changed"),
        json={
            **payload,
            "requested_scope": {"project_ids": ["other"]},
            "previous_context_id": fresh_receipt["context_capsule_id"],
        },
    )
    assert scope_changed.status_code == 200
    assert scope_changed.json["receipt_reused"] is False
    assert scope_changed.json["receipt_fallback_reason"] == "RECEIPT_COVERAGE_MISS"
    assert scope_changed.json["access_trace"]["attempted_stages"][0] == (
        "REUSE_VALIDATION"
    )

    replacement = _supersede(client, claim, f"receipthead{uuid4().hex}")
    head_changed = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-head-changed"),
        json={**payload, "previous_context_id": fresh_receipt["context_capsule_id"]},
    )
    assert head_changed.status_code == 200
    assert head_changed.json["status"] == "HIT", head_changed.json
    assert head_changed.json["items"][0]["claim_version_id"] == replacement[
        "claim_version_id"
    ]
    assert head_changed.json["receipt_reused"] is False
    assert head_changed.json["receipt_fallback_reason"] == (
        "RECEIPT_CANONICAL_POSITION_CHANGED"
    )


@pytest.mark.integration
def test_task_free_context_receipt_issue_change_invalidates_before_exact_fallback(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = retrieval_runtime
    client = app.test_client()
    token = f"receiptissue{uuid4().hex}"
    claim = _create_claim(client, token)
    payload: dict[str, object] = {
        "query": "Read the exact current issue-sensitive state",
        "claim_ids": [claim["claim_id"]],
        "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
    }
    first = client.post("/v1/memory/resolve", headers=_headers(), json=payload)
    assert first.status_code == 200
    receipt = first.json["context_receipt"]

    contradicting_evidence = _ingest(client, f"contradicting receipt grounding {token}")
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"receipt-conflict-{uuid4()}"),
        json={
            "target_claim_id": claim["claim_id"],
            "operation": "CONTRADICT",
            "expected_version_id": claim["claim_version_id"],
            "proposed_patch": {},
            "contradicting_evidence_refs": [contradicting_evidence],
            "scope_predicate": SCOPE,
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "receipt-conflict-v1",
            "derivation_snapshot": {"fixture": "context-receipt"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"receipt-conflict-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "receipt-conflict-v1",
            "reason_code": "CONFLICT_CONFIRMED",
        },
    )
    assert review.status_code == 200

    changed = client.post(
        "/v1/memory/resolve",
        headers=_headers(request_id="receipt-issue-changed"),
        json={**payload, "previous_context_id": receipt["context_capsule_id"]},
    )
    assert changed.status_code == 200
    assert changed.json["status"] == "CONTESTED", changed.json
    assert changed.json["open_issue_ids"] == [review.json["open_issue_id"]]
    assert changed.json["context_receipt"] is None
    assert changed.json["receipt_reused"] is False
    assert changed.json["receipt_fallback_reason"] == (
        "RECEIPT_CANONICAL_POSITION_CHANGED"
    )




@pytest.mark.integration
def test_dg11_compare_does_not_infer_operand_roles_from_canonical_gate(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"operatortoken{uuid4().hex}"
    first = _create_claim(
        client,
        token,
        value=10,
        valid_time_from="2026-08-01T00:00:00+00:00",
    )
    second = _create_claim(
        client,
        token,
        value=16,
        valid_time_from="2026-08-11T00:00:00+00:00",
    )
    _run_worker(settings, worker_database, "dg11-operator-worker")

    response = _query(
        client,
        {
            "route": "L1",
            "query": f"What is the difference between {token} events?",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
            "limit": 3,
        },
        request_id="dg11-operator-request",
    )

    assert response.status_code == 200
    assert response.json["abstained"] is True
    assert response.json["abstention_reason"] == "OPERATOR_REQUIRED_SLOT_MISSING"
    assert response.json["query_plan"]["operator"] == "COMPARE_EVENTS"
    assert response.json["derived_result"]["status"] == "ABSTAINED"
    assert response.json["derived_result"]["reason"] == "REQUIRED_SLOT_MISSING"
    assert response.json["derived_result"]["accepted_input_evidence_ids"] == []
    assert response.json["derived_result"]["accepted_input_requirement_ids"] == []
    assert response.json["derived_result"]["operands"] == []
    assert response.json["derived_result"]["hidden_model_calls"] == 0
    assert response.json["derived_result"]["canonical_mutation"] is False
    assert {item["claim_version_id"] for item in response.json["results"]} == {
        first["claim_version_id"],
        second["claim_version_id"],
    }


@pytest.mark.integration
def test_ryw_falls_back_when_projection_lags(retrieval_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    baseline = _create_claim(client, f"baselinetoken{uuid4().hex}")
    _run_worker(settings, worker_database, "retrieval-baseline-worker")
    assert baseline["claim_id"]
    token = f"lagtoken{uuid4().hex}"
    claim = _create_claim(client, token)
    causal = _causal_token(client, claim["outbox_id"])

    response = _query(
        client,
        {
            "route": "L1",
            "query": token,
            "consistency": "READ_YOUR_WRITES",
            "causal_token": causal["causal_token"],
            "causal_wait_timeout_ms": 0,
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert response.status_code == 200
    assert response.json["fallback_used"] is True
    assert response.json["fallback_reason"] == "CAUSAL_WAIT_TIMEOUT"
    assert (
        response.json["causal_wait"]["minimum_outbox_sequence"] == causal["minimum_outbox_sequence"]
    )
    assert response.json["causal_wait"]["outcome"] == "TIMEOUT"
    assert response.json["causal_wait"]["waited_ms"] >= 0
    assert response.json["results"][0]["claim_version_id"] == claim["claim_version_id"]
    assert "canonical" in response.json["results"][0]["matched_by"]


@pytest.mark.integration
def test_ryw_rejects_missing_forged_cross_tenant_and_future_positions(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, _worker_database = retrieval_runtime
    client = app.test_client()
    token = f"causalvalidation{uuid4().hex}"
    claim = _create_claim(client, token)
    causal = _causal_token(client, claim["outbox_id"])
    base: dict[str, object] = {
        "route": "L1",
        "query": token,
        "consistency": "READ_YOUR_WRITES",
        "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
        "causal_wait_timeout_ms": 0,
    }

    missing = _query(client, base)
    assert missing.status_code == 400
    assert missing.json["error"]["code"] == "INVALID_REQUEST"

    authentic = str(causal["causal_token"])
    forged = authentic[:-1] + ("A" if authentic[-1] != "A" else "B")
    wrong_key = CausalTokenCodec(API_TOKEN).issue(
        settings.tenant_id, int(causal["minimum_outbox_sequence"])
    )
    cross_tenant = CausalTokenCodec(CAUSAL_TOKEN_SECRET).issue(
        uuid4(), int(causal["minimum_outbox_sequence"])
    )
    future = CausalTokenCodec(CAUSAL_TOKEN_SECRET).issue(settings.tenant_id, 2**62)
    for supplied, code in (
        (forged, "INVALID_CAUSAL_TOKEN"),
        (wrong_key, "INVALID_CAUSAL_TOKEN"),
        (cross_tenant, "INVALID_CAUSAL_TOKEN"),
        (future, "CAUSAL_SEQUENCE_NOT_FOUND"),
    ):
        rejected = _query(client, base | {"causal_token": supplied})
        assert rejected.status_code == 400
        assert rejected.json["error"]["code"] == code

    unknown_outbox = client.post(
        "/v1/causal-tokens",
        headers=_headers(),
        json={"outbox_ids": [str(uuid4())]},
    )
    assert unknown_outbox.status_code == 404
    assert unknown_outbox.json["error"]["code"] == "OUTBOX_POSITION_NOT_FOUND"


@pytest.mark.integration
def test_ryw_dead_letter_falls_back_and_records_precise_outcome(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"causaldeadletter{uuid4().hex}"
    claim = _create_claim(client, token)
    causal = _causal_token(client, claim["outbox_id"])
    broken = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=None,
        worker_id="retrieval-dead-letter-worker",
    )
    assert broken.run_once() > 0

    response = _query(
        client,
        {
            "route": "L1",
            "query": token,
            "consistency": "READ_YOUR_WRITES",
            "causal_token": causal["causal_token"],
            "causal_wait_timeout_ms": 100,
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert response.status_code == 200
    assert response.json["fallback_used"] is True
    assert response.json["fallback_reason"] == "CAUSAL_DEAD_LETTER"
    assert response.json["causal_wait"]["outcome"] == "DEAD_LETTER"
    assert response.json["results"][0]["claim_version_id"] == claim["claim_version_id"]
    trace = client.get(
        f"/v1/retrieval-traces/{response.json['retrieval_trace_id']}",
        headers=_headers(),
    )
    assert trace.json["causal_wait_outcome"] == "DEAD_LETTER"
    assert trace.json["minimum_outbox_sequence"] == causal["minimum_outbox_sequence"]


@pytest.mark.integration
def test_ryw_snapshot_advance_forces_canonical_merge(
    retrieval_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"causalsnapshot{uuid4().hex}"
    first = _create_claim(client, token)
    _run_worker(settings, worker_database, "retrieval-snapshot-baseline-worker")
    causal = _causal_token(client, first["outbox_id"])
    original_gate = RetrievalRepository.gate_and_hydrate
    concurrent: dict[str, str] = {}

    def advancing_gate(repository, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not concurrent:
            concurrent.update(_create_claim(client, token))
        return original_gate(repository, *args, **kwargs)

    monkeypatch.setattr(RetrievalRepository, "gate_and_hydrate", advancing_gate)
    response = _query(
        client,
        {
            "route": "L1",
            "query": token,
            "consistency": "READ_YOUR_WRITES",
            "causal_token": causal["causal_token"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert response.status_code == 200
    assert response.json["causal_wait"]["outcome"] == "REACHED"
    assert response.json["fallback_used"] is True
    assert response.json["fallback_reason"] == "SNAPSHOT_ADVANCED"
    returned = {item["claim_version_id"] for item in response.json["results"]}
    assert returned == {first["claim_version_id"]}
    trace = client.get(
        f"/v1/retrieval-traces/{response.json['retrieval_trace_id']}",
        headers=_headers(),
    )
    rejected = {
        item["claim_version_id"]: item["reject_reason"]
        for item in trace.json["rejected_candidates"]
    }
    assert rejected[concurrent["claim_version_id"]] == "OUTSIDE_SYSTEM_TIME"


@pytest.mark.integration
def test_gate_rejects_stale_projection_revocation_scope_authority_and_time(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    stale_token = f"staletoken{uuid4().hex}"
    stale = _create_claim(client, stale_token)
    revoked_token = f"revokedtoken{uuid4().hex}"
    revoked = _create_claim(client, revoked_token)
    future = _create_claim(
        client,
        f"futuretoken{uuid4().hex}",
        valid_time_from="2030-01-01T00:00:00+00:00",
    )
    _run_worker(settings, worker_database, "retrieval-rejection-worker")
    _supersede(client, stale, f"replacementtoken{uuid4().hex}")
    revoke = client.post(
        f"/v1/evidence/{revoked['evidence_id']}/revoke",
        headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202

    stale_result = _query(
        client,
        {
            "route": "L1",
            "query": stale_token,
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert stale_result.status_code == 200
    stale_trace = client.get(
        f"/v1/retrieval-traces/{stale_result.json['retrieval_trace_id']}",
        headers=_headers(),
    )
    assert stale_result.json["abstained"] is True
    assert stale_trace.json["rejected_candidates"][0]["reject_reason"] == "STALE_VERSION"

    revoked_result = _query(
        client,
        {
            "route": "L1",
            "query": revoked_token,
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    revoked_trace = client.get(
        f"/v1/retrieval-traces/{revoked_result.json['retrieval_trace_id']}",
        headers=_headers(),
    )
    assert revoked_result.json["abstained"] is True
    assert revoked_trace.json["rejected_candidates"][0]["reject_reason"] == "GROUNDING_BLOCKED"

    for payload, reason in (
        (
            {
                "route": "L0",
                "claim_id": future["claim_id"],
                "requested_scope": {"project_ids": ["other"]},
                "required_authority": "ACTION_SAFE",
                "as_of": "2031-01-01T00:00:00+00:00",
            },
            "SCOPE_MISMATCH",
        ),
        (
            {
                "route": "L0",
                "claim_id": future["claim_id"],
                "requested_scope": SCOPE,
                "required_authority": "USER_CONFIRMED",
                "as_of": "2031-01-01T00:00:00+00:00",
            },
            "AUTHORITY_INSUFFICIENT",
        ),
        (
            {
                "route": "L0",
                "claim_id": future["claim_id"],
                "requested_scope": SCOPE,
                "required_authority": "ACTION_SAFE",
                "as_of": "2026-08-15T00:00:00+00:00",
            },
            "OUTSIDE_VALID_TIME",
        ),
    ):
        result = _query(client, payload)
        trace = client.get(
            f"/v1/retrieval-traces/{result.json['retrieval_trace_id']}",
            headers=_headers(),
        )
        assert result.json["abstained"] is True
        assert trace.json["rejected_candidates"][0]["reject_reason"] == reason

    mismatch = _query(
        client,
        {
            "tenant_id": str(uuid4()),
            "route": "L0",
            "claim_id": future["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert mismatch.status_code == 403


@pytest.mark.integration
def test_gate_evaluates_all_state_axes_confidence_and_bitemporal_dimensions(
    retrieval_runtime,
) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = retrieval_runtime
    client = app.test_client()
    archived = _create_claim(client, f"archived{uuid4().hex}", lifecycle="ARCHIVED")
    challenged = _create_claim(client, f"challenged{uuid4().hex}", epistemic_status="CHALLENGED")
    unprovable = _create_claim(client, f"unprovable{uuid4().hex}", epistemic_status="UNPROVABLE")
    stale = _create_claim(client, f"freshness{uuid4().hex}", freshness="STALE")
    informational = _create_claim(client, f"authority{uuid4().hex}", authority="INFORMATIONAL")
    low_confidence = _create_claim(client, f"confidence{uuid4().hex}", confidence=0.25)
    temporal = _create_claim(
        client,
        f"temporal{uuid4().hex}",
        valid_time_from="2030-01-01T00:00:00+00:00",
    )

    def l0(claim: dict[str, str], **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "route": "L0",
            "claim_id": claim["claim_id"],
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        }
        payload.update(overrides)
        return payload

    for payload, reason in (
        (l0(archived), "LIFECYCLE_MISMATCH"),
        (l0(challenged), "EPISTEMIC_MISMATCH"),
        (l0(unprovable), "EPISTEMIC_MISMATCH"),
        (l0(stale), "FRESHNESS_MISMATCH"),
        (l0(informational), "AUTHORITY_INSUFFICIENT"),
        (l0(low_confidence, minimum_confidence=0.9), "CONFIDENCE_BELOW_MINIMUM"),
        (
            l0(temporal, as_of="2026-08-16T00:00:00+00:00"),
            "OUTSIDE_VALID_TIME",
        ),
        (
            l0(
                low_confidence,
                minimum_confidence=0.0,
                system_as_of="2000-01-01T00:00:00+00:00",
            ),
            "OUTSIDE_SYSTEM_TIME",
        ),
    ):
        assert _reject_reason(client, payload) == reason

    for payload in (
        l0(archived, required_lifecycle="ARCHIVED"),
        l0(challenged, accepted_epistemic_statuses=["CHALLENGED"]),
        l0(stale, required_freshness="STALE"),
    ):
        accepted = _query(client, payload)
        assert accepted.status_code == 200
        assert accepted.json["abstained"] is False

    challenged_result = _query(
        client,
        l0(challenged, accepted_epistemic_statuses=["CHALLENGED"]),
    )
    assert challenged_result.json["results"][0]["authority"] == "ACTION_SAFE"
    assert challenged_result.json["results"][0]["epistemic_status"] == "CHALLENGED"


@pytest.mark.integration
def test_vector_outage_degrades_and_canonical_outage_abstains(
    retrieval_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = retrieval_runtime
    client = app.test_client()
    token = f"degradetoken{uuid4().hex}"
    claim = _create_claim(client, token)
    _run_worker(settings, worker_database, "retrieval-degrade-worker")

    def unavailable_vector(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        raise ProjectionUnavailable("vector")

    monkeypatch.setattr(RetrievalRepository, "search_vector", unavailable_vector)
    degraded = _query(
        client,
        {
            "route": "L1",
            "query": token,
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert degraded.status_code == 200
    assert degraded.json["results"][0]["claim_version_id"] == claim["claim_version_id"]
    assert degraded.json["degraded_components"] == ["vector"]
    assert degraded.json["results"][0]["matched_by"] == ["fts"]

    def unavailable_gate(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        raise DatabaseUnavailable("synthetic outage")

    monkeypatch.setattr(RetrievalRepository, "gate_and_hydrate", unavailable_gate)
    unavailable = _query(
        client,
        {
            "route": "L1",
            "query": token,
            "consistency": "CANONICAL_REQUIRED",
            "requested_scope": SCOPE,
            "required_authority": "ACTION_SAFE",
        },
    )
    assert unavailable.status_code == 503
    assert unavailable.json["abstained"] is True
    assert unavailable.json["abstention_reason"] == "CANONICAL_UNAVAILABLE"
    assert unavailable.json["results"] == []
    assert unavailable.json["retrieval_trace_id"] is None

    monkeypatch.setattr(RetrievalRepository, "projection_state", unavailable_gate)
    for endpoint in ("/v1/system/watermarks", "/v1/system/degraded-routes"):
        status = client.get(endpoint, headers=_headers())
        assert status.status_code == 503
        assert status.json["error"]["code"] == "CANONICAL_UNAVAILABLE"
