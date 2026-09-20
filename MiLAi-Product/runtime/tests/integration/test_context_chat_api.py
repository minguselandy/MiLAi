from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain import (
    MemoryNeedSignature,
    StateKeyRef,
    action_identity_digest,
    canonical_sha256,
)
from milai.persistence import Database, DatabaseUnavailable
from milai.persistence.projection_repository import ProjectionRepository
from milai.persistence.retrieval_repository import RetrievalRepository
from milai.workers.main import FoundationWorker

ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
REVIEWER_TOKEN = "reviewer-token-with-at-least-32-characters"
SCOPE = {"project_ids": ["milai"]}
DIGEST = "a" * 64


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture
def context_runtime(tmp_path: Path):  # type: ignore[no-untyped-def]
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=uuid4(),
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        agent_reviewer_token=REVIEWER_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
        worker_event_limit=10_000,
        worker_retry_delay_seconds=0,
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


def _headers(key: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {API_TOKEN}"}
    if key is not None:
        result["Idempotency-Key"] = key
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
            "source_ref": f"context-test://{uuid4()}",
            "subject_id": "context-test",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    assert response.status_code == 201
    return str(response.json["evidence_id"])


def _live_confirmation(
    client,  # type: ignore[no-untyped-def]
    tenant_id: UUID,
    request: dict[str, object],
    *,
    nonce: str | None = None,
    binding_digest: str | None = None,
    observed_at: datetime | None = None,
    readable: bool = True,
) -> tuple[str, str]:
    nonce = nonce or str(uuid4())
    action_digest = request.get("action_digest")
    assert isinstance(action_digest, str)
    expected_binding = binding_digest or action_identity_digest(
        tenant_id=tenant_id,
        query=str(request["query"]),
        active_goal=str(request["active_goal"]),
        requested_scope=request["requested_scope"],  # type: ignore[arg-type]
        required_authority=request["required_authority"],  # type: ignore[arg-type]
        action_digest=action_digest,
    )
    response = client.post(
        "/v1/evidence",
        headers=_headers(f"confirmation-{uuid4()}"),
        json={
            "source_type": "USER_CONFIRMATION",
            "source_ref": f"chat-confirmation:v2:{nonce}:{expected_binding}",
            "subject_id": "action-sensitive-chat",
            "observed_at": (observed_at or datetime.now(UTC)).isoformat(),
            "content": "CONFIRM_ACTION",
            "media_type": "text/plain",
            "permission_snapshot": {"readable": readable},
            "retention_state": "READABLE",
        },
    )
    assert response.status_code == 201
    return str(response.json["evidence_id"]), nonce


def _create_claim(client, token: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    evidence_id = _ingest(client, f"context grounding {token}")
    subject_id = f"context-subject-{uuid4()}"
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": subject_id,
                "predicate": "context.fact",
                "claim_type": "FACT",
                "payload": {"token": token, "value": "verified"},
                "authority": "ACTION_SAFE",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": SCOPE,
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "context-test-v1",
            "derivation_snapshot": {"fixture": "context"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "context-test-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    return {
        "claim_id": str(review.json["claim_id"]),
        "claim_version_id": str(review.json["claim_version_id"]),
        "evidence_id": evidence_id,
        "subject_id": subject_id,
    }


def _run_worker(settings: RuntimeSettings, database: Database) -> None:
    worker = FoundationWorker(
        settings,
        database,
        repository=ProjectionRepository(database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"context-worker-{uuid4()}",
    )
    assert worker.run_once() > 0


def _open_conflict(client, claim: dict[str, str]) -> str:  # type: ignore[no-untyped-def]
    contradiction = _ingest(client, f"contradiction-{uuid4()}")
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"conflict-{uuid4()}"),
        json={
            "target_claim_id": claim["claim_id"],
            "operation": "CONTRADICT",
            "expected_version_id": claim["claim_version_id"],
            "proposed_patch": {},
            "contradicting_evidence_refs": [contradiction],
            "scope_predicate": SCOPE,
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "context-test-v1",
            "derivation_snapshot": {"fixture": "context-conflict"},
        },
    )
    assert proposal.status_code == 201
    reviewed = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "context-test-v1",
            "reason_code": "SYNTHETIC_CONFLICT_CONFIRMED",
        },
    )
    assert reviewed.status_code == 200
    return str(reviewed.json["open_issue_id"])


def _chat_payload(token: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "query": f"What is the recorded value for {token}?",
        "active_goal": "回答当前项目状态",
        "constraints": ["不得绕过 Canonical Gate", "保留 live OpenIssue"],
        "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
        "consistency": "CANONICAL_REQUIRED",
    }
    result.update(overrides)
    return result


def _prepare_payload(token: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "query": f"Recall: what is the recorded value for {token}?",
        "active_goal": "回答当前项目状态",
        "session_id": "session-composite",
        "agent_id": "agent-composite",
        "profile_id": "reader-lite",
        "task_epoch": "task-composite",
        "event": "TASK_START",
        "requested_scope": SCOPE,
        "required_authority": "ACTION_SAFE",
        "consistency": "CANONICAL_REQUIRED",
        "constraints": ["保留相关 OpenIssue"],
        "compiler_digest": DIGEST,
        "router_digest": DIGEST,
        "tokenizer_digest": DIGEST,
        "policy_digest": DIGEST,
        "budget": {"memory_deadline_ms": 5_000},
    }
    result.update(overrides)
    return result


def _typed_current_need(claim: dict[str, str]) -> dict[str, object]:
    key = StateKeyRef(
        scope=SCOPE,
        subject=claim["subject_id"],
        predicate="context.fact",
        claim_type="FACT",
        claim_id=UUID(claim["claim_id"]),
    )
    signature = MemoryNeedSignature(
        scope=SCOPE,
        required_authority="ACTION_SAFE",
        consistency_floor="CANONICAL_REQUIRED",
        state_keys=[key],
        temporal_need="CURRENT",
        evidence_need="SUPPORT_POINTERS",
        intent_class="CURRENT_STATE",
    )
    return {
        "need_signature_id": signature.signature_id,
        "memory_need_signature": signature.model_dump(mode="json"),
        "state_key_ref": key.model_dump(mode="json"),
    }


@pytest.mark.integration
def test_composite_prepare_context_reuses_hit_then_falls_through_to_exact(
    context_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"compositetoken{uuid4().hex}"
    claim = _create_claim(client, token)
    _run_worker(settings, worker_database)
    typed_need = _typed_current_need(claim)

    prepared = client.post(
        "/v1/memory/prepare-context",
        headers=_headers(),
        json=_prepare_payload(token, **typed_need),
    )
    assert prepared.status_code == 200
    assert prepared.json["status"] == "READY"
    assert prepared.json["route"] == "L1"
    assert prepared.json["context_capsule"]["protected_sections"]["ACTIVE STATE"]
    validation_token = prepared.json["validation_token"]

    cached = client.post(
        "/v1/memory/prepare-context",
        headers=_headers(),
        json=_prepare_payload(
            "ordinary tool output",
            event="TOOL_RESULT",
            requested_route="CACHE",
            previous_validation_token=validation_token,
            **typed_need,
        ),
    )
    assert cached.status_code == 200
    assert cached.json["status"] == "UNCHANGED"
    assert cached.json["route"] == "CACHE"
    assert cached.json["context_capsule"] is None
    assert cached.json["usage"] == {
        "prepare_context_calls": 2,
        "full_recall_calls": 1,
        "delta_refreshes": 0,
        "validation_calls": 1,
    }

    _create_claim(client, f"advance{uuid4().hex}")
    _run_worker(settings, worker_database)
    stale = client.post(
        "/v1/memory/prepare-context",
        headers=_headers(),
        json=_prepare_payload(
            "retry",
            event="MODEL_RETRY",
            requested_route="CACHE",
            previous_validation_token=cached.json["validation_token"],
            **typed_need,
        ),
    )
    assert stale.status_code == 200
    assert stale.json["status"] == "READY"
    assert stale.json["route"] == "L0"
    assert stale.json["current_state_envelope"]["status"] == "HIT"
    assert stale.json["validation_token"]
    assert stale.json["usage"] == {
        "prepare_context_calls": 3,
        "full_recall_calls": 2,
        "delta_refreshes": 0,
        "validation_calls": 2,
    }
    trace = stale.json["recall_execution_trace"]
    assert trace["requested_route"] == "CACHE"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "CACHE_CANONICAL_POSITION_CHANGED"
    assert trace["next_route_recommended"] is None


@pytest.mark.integration
def test_action_validate_is_action_bound_and_canonical_outage_abstains(
    context_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"actionvalidate{uuid4().hex}"
    _create_claim(client, token)
    _run_worker(settings, worker_database)
    action_digest = hashlib.sha256(
        b'{"arguments":{"environment":"staging"},"tool":"deploy"}'
    ).hexdigest()
    payload = _prepare_payload(
        token,
        event="ACTION_PROPOSED",
        action_digest=action_digest,
        slot_ttl_seconds=300,
    )

    validated = client.post(
        "/v1/memory/prepare-context",
        headers=_headers(),
        json=payload,
    )
    assert validated.status_code == 200
    assert validated.json["status"] == "READY"
    assert validated.json["route"] == "ACTION_VALIDATE"
    assert validated.json["validation_token"]

    replay = client.post(
        "/v1/memory/prepare-context",
        headers=_headers(),
        json=_prepare_payload(
            "ordinary tool result",
            event="TOOL_RESULT",
            previous_validation_token=validated.json["validation_token"],
        ),
    )
    assert replay.status_code == 409
    assert replay.json["error"]["code"] == "CONTEXT_VALIDATION_TOKEN_INVALID"

    def unavailable_gate(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        raise DatabaseUnavailable("synthetic outage")

    monkeypatch.setattr(RetrievalRepository, "gate_and_hydrate", unavailable_gate)
    unavailable = client.post(
        "/v1/memory/prepare-context",
        headers=_headers(),
        json=payload | {"action_digest": "b" * 64},
    )
    assert unavailable.status_code == 503
    assert unavailable.json["status"] == "ABSTAIN"
    assert unavailable.json["reason"] == "CANONICAL_UNAVAILABLE"
    assert unavailable.json["validation_token"] is None


@pytest.mark.integration
def test_composite_capsule_compiles_through_shipped_task_controller(
    context_runtime,
) -> None:  # type: ignore[no-untyped-def]
    milai_client = pytest.importorskip("milai_client")
    openworker = pytest.importorskip("milai_openworker_mcp")
    tokenizer_path = Path("/cra/qwen36-35B/tokenizer.json")
    if not tokenizer_path.is_file():
        pytest.skip("target tokenizer.json is unavailable")
    settings, app, worker_database = context_runtime
    http = app.test_client()
    marker = f"compositecompile{uuid4().hex}"
    _create_claim(http, marker)
    _run_worker(settings, worker_database)

    class _Client:
        def prepare_context(self, request):  # type: ignore[no-untyped-def]
            response = http.post(
                "/v1/memory/prepare-context",
                headers=_headers(),
                json=request.to_api(),
            )
            assert response.status_code == 200, response.json
            return milai_client.PrepareContextEnvelope.from_api(response.json)

    counter = openworker.TargetTokenizerCounter(tokenizer_path)
    controller = milai_client.TaskMemoryController(
        _Client(),
        compiler_digest=DIGEST,
        router_digest=DIGEST,
        policy_digest=DIGEST,
    )
    prepared = controller.prepare_context(
        marker,
        identity=milai_client.TaskMemoryIdentity(
            str(settings.tenant_id),
            "session-controller",
            "openworker",
            "reader-lite",
            "task-controller",
        ),
        event="TASK_START",
        active_goal="回答当前项目状态",
        recall_policy=milai_client.AgentRecallPolicy(
            scope=SCOPE,
            authority="ACTION_SAFE",
            consistency_floor="CANONICAL_REQUIRED",
            max_limit=3,
        ),
        token_counter=counter,
        token_budget=milai_client.TokenBudget.for_class("STANDARD", counter=counter),
        task_budget=milai_client.TaskMemoryBudget(memory_deadline_ms=5_000),
        constraints=("保留相关 OpenIssue",),
    )

    assert prepared.status == "READY"
    assert prepared.delta is not None
    assert prepared.delta.delta.rendered_context is not None
    assert prepared.delta.metrics.actual_tokens is not None
    assert prepared.delta.metrics.actual_tokens <= 512


@pytest.mark.integration
def test_chat_builds_fixed_capsule_trace_and_recoverable_pointer(context_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"contexttoken{uuid4().hex}"
    claim = _create_claim(client, token)
    _run_worker(settings, worker_database)

    response = client.post("/v1/chat", headers=_headers(), json=_chat_payload(token))
    assert response.status_code == 200
    assert response.json["abstained"] is False
    assert response.json["used_claim_version_ids"] == [claim["claim_version_id"]]
    assert response.json["evidence_refs"] == [claim["evidence_id"]]
    assert response.json["retrieval_trace_id"]
    assert response.json["context_capsule_id"]
    assert response.json["chat_turn_id"]

    capsule = client.get(
        f"/v1/context-capsules/{response.json['context_capsule_id']}", headers=_headers()
    )
    assert capsule.status_code == 200
    assert list(capsule.json["protected_sections"]) == [
        "ACTIVE GOAL",
        "ACTIVE STATE",
        "CONSTRAINTS",
        "OPEN ISSUES",
        "RETRIEVED EVIDENCE",
        "TRACE POINTERS",
    ]
    pointer_id = capsule.json["protected_sections"]["RETRIEVED EVIDENCE"][0]["pointer_id"]
    recovered = client.get(f"/v1/context-pointers/{pointer_id}/recover", headers=_headers())
    assert recovered.status_code == 200
    assert recovered.json["content"] == f"context grounding {token}"
    assert recovered.json["evidence_id"] == claim["evidence_id"]

    chat_turn = client.get(f"/v1/chat-turns/{response.json['chat_turn_id']}", headers=_headers())
    assert chat_turn.status_code == 200
    assert token not in chat_turn.json["query_fingerprint"]
    assert len(chat_turn.json["query_fingerprint"]) == 64
    assert chat_turn.json["used_claim_version_ids"] == [claim["claim_version_id"]]
    assert chat_turn.json["retrieval_trace_id"] == response.json["retrieval_trace_id"]

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as api_connection:
        api_connection.execute(
            "SELECT set_config('milai.tenant_id', %s, false)", (str(settings.tenant_id),)
        )
        api_connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        with pytest.raises(psycopg.Error):
            api_connection.execute(
                "UPDATE milai.chat_turn SET answer_text = 'tampered' WHERE tenant_id = %s",
                (settings.tenant_id,),
            )


@pytest.mark.integration
def test_context_compresses_then_fails_when_protected_minimum_exceeds_budget(
    context_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"budgettoken{uuid4().hex}"
    _create_claim(client, token)
    _run_worker(settings, worker_database)
    chat = client.post("/v1/chat", headers=_headers(), json=_chat_payload(token))
    assert chat.status_code == 200
    trace_id = chat.json["retrieval_trace_id"]

    full = client.post(
        "/v1/context-capsules",
        headers=_headers(),
        json={
            "retrieval_trace_id": trace_id,
            "active_goal": "验证递归压缩",
            "constraints": ["硬约束必须保留"],
            "byte_budget": 100_000,
        },
    )
    assert full.status_code == 201
    assert full.json["compression_level"] == "FULL"
    compressed = client.post(
        "/v1/context-capsules",
        headers=_headers(),
        json={
            "retrieval_trace_id": trace_id,
            "active_goal": "验证递归压缩",
            "constraints": ["硬约束必须保留"],
            "byte_budget": full.json["byte_size"] - 1,
        },
    )
    assert compressed.status_code == 201
    assert compressed.json["compression_level"] in {"COMPACT", "MINIMAL"}
    assert compressed.json["protected_sections"]["ACTIVE GOAL"]["text"] == "验证递归压缩"

    infeasible = client.post(
        "/v1/context-capsules",
        headers=_headers(),
        json={
            "retrieval_trace_id": trace_id,
            "active_goal": "验证递归压缩",
            "constraints": ["硬约束必须保留"],
            "byte_budget": 64,
        },
    )
    assert infeasible.status_code == 422
    assert infeasible.json["error"]["code"] == "CONTEXT_BUDGET_INFEASIBLE"


@pytest.mark.integration
def test_capsule_preserves_live_open_issue_identity_branches_and_discharge_rule(
    context_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    conflicted = _create_claim(client, f"conflictedtoken{uuid4().hex}")
    issue_id = _open_conflict(client, conflicted)
    answer_token = f"answerabletoken{uuid4().hex}"
    _create_claim(client, answer_token)
    _run_worker(settings, worker_database)

    chat = client.post("/v1/chat", headers=_headers(), json=_chat_payload(answer_token))
    assert chat.status_code == 200
    assert chat.json["abstained"] is False
    assert issue_id in chat.json["open_issue_refs"]
    capsule = client.get(
        f"/v1/context-capsules/{chat.json['context_capsule_id']}", headers=_headers()
    )
    issues = capsule.json["protected_sections"]["OPEN ISSUES"]
    issue = next(item for item in issues if item["issue_id"] == issue_id)
    assert issue["target_claim_id"] == conflicted["claim_id"]
    assert issue["issue_type"] == "CONFLICT"
    assert issue["status"] == "OPEN"
    assert issue["revision"] >= 1
    assert issue["scope_predicate"] == SCOPE
    assert issue["required_authority"] == "ACTION_SAFE"
    assert issue["discharge_rule"]
    assert {branch["relation_type"] for branch in issue["branches"]} == {
        "CONTRADICT_BRANCH",
        "SUPPORT_BRANCH",
    }


@pytest.mark.integration
def test_revoke_invalidates_pointer_and_stale_chat_abstains(context_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"invalidatetoken{uuid4().hex}"
    claim = _create_claim(client, token)
    _run_worker(settings, worker_database)
    chat = client.post("/v1/chat", headers=_headers(), json=_chat_payload(token))
    capsule = client.get(
        f"/v1/context-capsules/{chat.json['context_capsule_id']}", headers=_headers()
    )
    pointer_id = capsule.json["protected_sections"]["RETRIEVED EVIDENCE"][0]["pointer_id"]

    revoke = client.post(
        f"/v1/evidence/{claim['evidence_id']}/revoke",
        headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202
    invalid = client.get(f"/v1/context-pointers/{pointer_id}/recover", headers=_headers())
    assert invalid.status_code == 409
    assert invalid.json["error"]["code"] == "CONTEXT_POINTER_INVALID"
    invalidated_capsule = client.get(
        f"/v1/context-capsules/{chat.json['context_capsule_id']}", headers=_headers()
    )
    assert invalidated_capsule.json["status"] == "INVALIDATED"

    stale = client.post("/v1/chat", headers=_headers(), json=_chat_payload(token))
    assert stale.status_code == 200
    assert stale.json["abstained"] is True
    assert stale.json["context_capsule_id"] is None
    assert stale.json["used_claim_version_ids"] == []


@pytest.mark.integration
def test_action_sensitive_chat_requires_live_confirmation_and_canonical_outage_abstains(
    context_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"actiontoken{uuid4().hex}"
    _create_claim(client, token)
    _run_worker(settings, worker_database)
    action = _chat_payload(
        token,
        action_sensitive=True,
        action_digest=canonical_sha256({"tool": "deploy", "arguments": {"environment": "staging"}}),
    )

    unconfirmed = client.post("/v1/chat", headers=_headers(), json=action)
    assert unconfirmed.status_code == 200
    assert unconfirmed.json["abstained"] is True
    assert unconfirmed.json["abstention_reason"] == "LIVE_CONFIRMATION_REQUIRED"
    assert unconfirmed.json["retrieval_trace_id"] is None

    confirmed = dict(action)
    confirmed["live_confirmation"] = "CONFIRM_ACTION"
    confirmation_evidence_id, confirmation_nonce = _live_confirmation(
        client, settings.tenant_id, confirmed
    )
    confirmed["confirmation_evidence_id"] = confirmation_evidence_id
    confirmed["confirmation_nonce"] = confirmation_nonce
    accepted = client.post("/v1/chat", headers=_headers(), json=confirmed)
    assert accepted.status_code == 200
    assert accepted.json["abstained"] is False
    assert accepted.json["live_confirmation"] is True
    assert confirmation_evidence_id in accepted.json["evidence_refs"]
    accepted_trace = client.get(
        f"/v1/retrieval-traces/{accepted.json['retrieval_trace_id']}", headers=_headers()
    )
    assert accepted_trace.json["query_plan"]["require_user_confirmation"] is True
    accepted_turn = client.get(
        f"/v1/chat-turns/{accepted.json['chat_turn_id']}", headers=_headers()
    )
    assert confirmation_evidence_id in accepted_turn.json["evidence_refs"]

    def unavailable_gate(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        raise DatabaseUnavailable("synthetic outage")

    monkeypatch.setattr(RetrievalRepository, "gate_and_hydrate", unavailable_gate)
    second_evidence_id, second_nonce = _live_confirmation(client, settings.tenant_id, confirmed)
    confirmed["confirmation_evidence_id"] = second_evidence_id
    confirmed["confirmation_nonce"] = second_nonce
    unavailable = client.post("/v1/chat", headers=_headers(), json=confirmed)
    assert unavailable.status_code == 503
    assert unavailable.json["abstained"] is True
    assert unavailable.json["abstention_reason"] == "CANONICAL_UNAVAILABLE"
    assert unavailable.json["answer"] == "Canonical 存储当前不可用, 无法安全作答。"


@pytest.mark.integration
def test_live_confirmation_replays_across_query_goal_and_scope(
    context_runtime,
) -> None:  # type: ignore[no-untyped-def]
    """Reproduce acceptance of one confirmation Evidence for other requests."""

    settings, app, worker_database = context_runtime
    client = app.test_client()
    token = f"confirmationreplay{uuid4().hex}"
    _create_claim(client, token)
    _run_worker(settings, worker_database)
    confirmed = _chat_payload(
        token,
        action_sensitive=True,
        action_digest=canonical_sha256({"tool": "deploy", "arguments": {"environment": "staging"}}),
        live_confirmation="CONFIRM_ACTION",
    )
    evidence_id, nonce = _live_confirmation(client, settings.tenant_id, confirmed)
    confirmed["confirmation_evidence_id"] = evidence_id
    confirmed["confirmation_nonce"] = nonce

    original = client.post("/v1/chat", headers=_headers(), json=confirmed)
    assert original.status_code == 200
    assert original.json["live_confirmation"] is True
    assert original.json["abstained"] is False

    def assert_confirmation_rejected(payload: dict[str, object]) -> None:
        response = client.post("/v1/chat", headers=_headers(), json=payload)
        assert response.status_code == 200
        assert response.json["live_confirmation"] is False
        assert response.json["abstained"] is True
        assert response.json["abstention_reason"] == "LIVE_CONFIRMATION_REQUIRED"

    assert_confirmation_rejected(
        confirmed | {"query": f"Use {token} for a different action request"}
    )
    assert_confirmation_rejected(confirmed | {"active_goal": "执行另一个目标"})
    assert_confirmation_rejected(
        confirmed | {"requested_scope": {"project_ids": ["different-project"]}}
    )
    assert_confirmation_rejected(confirmed | {"action_digest": "b" * 64})
    assert_confirmation_rejected(confirmed | {"confirmation_nonce": str(uuid4())})

    wrong_binding_id, wrong_binding_nonce = _live_confirmation(
        client,
        settings.tenant_id,
        confirmed,
        binding_digest="f" * 64,
    )
    assert_confirmation_rejected(
        confirmed
        | {
            "confirmation_evidence_id": wrong_binding_id,
            "confirmation_nonce": wrong_binding_nonce,
        }
    )

    expired_id, expired_nonce = _live_confirmation(
        client,
        settings.tenant_id,
        confirmed,
        observed_at=datetime.now(UTC) - timedelta(minutes=6),
    )
    assert_confirmation_rejected(
        confirmed
        | {
            "confirmation_evidence_id": expired_id,
            "confirmation_nonce": expired_nonce,
        }
    )

    revoked_id, revoked_nonce = _live_confirmation(client, settings.tenant_id, confirmed)
    revoked = client.post(
        f"/v1/evidence/{revoked_id}/revoke",
        headers=_headers(f"revoke-confirmation-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoked.status_code == 202
    assert_confirmation_rejected(
        confirmed
        | {
            "confirmation_evidence_id": revoked_id,
            "confirmation_nonce": revoked_nonce,
        }
    )

    unreadable_id, unreadable_nonce = _live_confirmation(
        client,
        settings.tenant_id,
        confirmed,
        readable=False,
    )
    assert_confirmation_rejected(
        confirmed
        | {
            "confirmation_evidence_id": unreadable_id,
            "confirmation_nonce": unreadable_nonce,
        }
    )


@pytest.mark.integration
def test_local_ui_exposes_review_correct_confirm_trace_and_revoke(context_runtime) -> None:  # type: ignore[no-untyped-def]
    _settings, app, _worker_database = context_runtime
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    page = response.get_data(as_text=True)
    for label in (
        "Correct",
        "Review",
        "CONFIRM_ACTION",
        "Action JSON",
        "Trace",
        "Revoke Evidence",
        "Episode Capture",
        "Settlement",
    ):
        assert label in page
    assert "NO-GO FOR SCHEMA FREEZE" in page
