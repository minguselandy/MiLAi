from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from milai_client import AgentMemory, CapturePolicy
from milai_client.models import EpisodeReceipt, EvidenceReceipt, ProposalReceipt


class _LifecycleClient:
    base_url = "http://127.0.0.1:18080"

    def __init__(self) -> None:
        self.captures: list[tuple[dict[str, Any], str]] = []
        self.episodes: list[dict[str, Any]] = []
        self.proposals: list[str] = []

    def health(self) -> Any:
        return SimpleNamespace(
            live=True,
            ready=True,
            schema_status="0.1.x EXPERIMENTAL",
            implementation_status="CANDIDATE",
        )

    def capabilities(self) -> Any:
        return SimpleNamespace(raw={"contract_version": "agent.v1"})

    def list_open_issues(self, status: str | None = None) -> list[Any]:
        return []

    def capture_evidence(self, payload: dict[str, Any], *, operation_id: str) -> EvidenceReceipt:
        self.captures.append((payload, operation_id))
        replayed = sum(item[1] == operation_id for item in self.captures) > 1
        return EvidenceReceipt(
            "11111111-1111-4111-8111-111111111111",
            "b1",
            "o1",
            replayed,
            {
                "evidence_id": "11111111-1111-4111-8111-111111111111",
                "replayed": replayed,
            },
        )

    def create_proposal(self, payload: Any, *, operation_id: str) -> ProposalReceipt:
        self.proposals.append(operation_id)
        return ProposalReceipt(
            "22222222-2222-4222-8222-222222222222",
            "PENDING_REVIEW",
            False,
            {"proposal_id": "22222222-2222-4222-8222-222222222222", "status": "PENDING_REVIEW"},
        )

    def create_episode(self, **payload: Any) -> EpisodeReceipt:
        self.episodes.append(payload)
        return EpisodeReceipt(
            "33333333-3333-4333-8333-333333333333",
            "OPEN",
            1,
            len(self.episodes) > 1,
            {"episode_id": "33333333-3333-4333-8333-333333333333", "status": "OPEN"},
        )


def test_off_ask_and_allowlisted_capture_modes_are_fail_closed() -> None:
    off_client = _LifecycleClient()
    off = AgentMemory(off_client, CapturePolicy())  # type: ignore[arg-type]
    denied = off.after_user_observation(
        session_id="s", turn_id="t", subject_id="subject", content="synthetic"
    )
    assert denied.capture_denied_reason == "CAPTURE_POLICY_OFF"
    assert off_client.captures == []

    ask_client = _LifecycleClient()
    ask = AgentMemory(
        ask_client,
        CapturePolicy(mode="ASK_EACH_TIME"),  # type: ignore[arg-type]
    )
    unconfirmed = ask.after_user_observation(
        session_id="s", turn_id="t", subject_id="subject", content="synthetic"
    )
    assert unconfirmed.capture_denied_reason == "CAPTURE_CONFIRMATION_REQUIRED"
    accepted = ask.after_user_observation(
        session_id="s",
        turn_id="t",
        subject_id="subject",
        content="synthetic",
        capture_confirmed=True,
        observed_at="2026-08-17T00:00:00Z",
        source_context={
            "session_id": "s",
            "turn_id": "t",
            "turn_ordinal": 1,
            "round_id": "r1",
            "round_ordinal": 1,
        },
    )
    assert accepted.evidence is not None
    assert ask_client.captures[0][0]["permission_snapshot"] == {
        "readable": True,
        "agent_capture": True,
        "scope": "local",
    }
    assert ask_client.captures[0][0]["speaker"] == "user"
    assert ask_client.captures[0][0]["source_context"]["turn_ordinal"] == 1

    allow_client = _LifecycleClient()
    allow = AgentMemory(
        allow_client,
        CapturePolicy(mode="ALLOWLISTED", allowed_tool_sources=frozenset({"verified_db"})),
    )  # type: ignore[arg-type]
    rejected = allow.after_tool_observation(
        session_id="s",
        call_id="c",
        tool_name="shell",
        subject_id="subject",
        content="synthetic",
    )
    assert rejected.capture_denied_reason == "SOURCE_NOT_ALLOWLISTED"
    accepted_tool = allow.after_tool_observation(
        session_id="s",
        call_id="c",
        tool_name="verified_db",
        subject_id="subject",
        content="synthetic",
        observed_at="2026-08-17T00:00:00Z",
        source_type="RUNTIME_OBSERVATION",
    )
    assert accepted_tool.evidence is not None
    assert allow_client.captures[0][0]["source_type"] == "RUNTIME_OBSERVATION"
    assert allow_client.captures[0][0]["speaker"] == "tool"


def test_sensitive_content_and_model_output_never_become_evidence() -> None:
    client = _LifecycleClient()
    memory = AgentMemory(
        client,
        CapturePolicy(mode="ALLOWLISTED", allowed_user_sources=frozenset({"user_statement"})),
    )  # type: ignore[arg-type]
    denied = memory.after_user_observation(
        session_id="s",
        turn_id="t",
        subject_id="subject",
        content="Authorization: Bearer do-not-store",
    )
    assert denied.capture_denied_reason == "SENSITIVE_SOURCE_REJECTED"
    result = memory.after_model("model answer", session_id="s")
    assert result["status"] == "MODEL_OUTPUT_NOT_EVIDENCE"
    assert client.captures == []


def test_duplicate_hook_replay_reuses_operation_and_payload_then_episode_is_idempotent() -> None:
    client = _LifecycleClient()
    memory = AgentMemory(
        client,
        CapturePolicy(mode="ASK_EACH_TIME"),
    )  # type: ignore[arg-type]
    kwargs = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "subject_id": "subject",
        "content": "synthetic observation",
        "capture_confirmed": True,
        "observed_at": "2026-08-17T00:00:00Z",
    }
    memory.after_user_observation(**kwargs)
    memory.after_user_observation(**kwargs)
    assert client.captures[0] == client.captures[1]
    memory.create_proposal(
        {
            "operation": "CREATE",
            "supporting_evidence_refs": ["11111111-1111-4111-8111-111111111111"],
            "requested_authority": "INFORMATIONAL",
            "scope_predicate": {"project_ids": ["milai"]},
            "model_id": "extractor-test",
            "template_version": "v1",
            "input_snapshot_hash": "a" * 64,
            "proposed_patch": {
                "subject_id": "subject",
                "predicate": "prefers",
                "claim_type": "FACT",
                "payload": {"value": "synthetic"},
                "authority": "INFORMATIONAL",
                "confidence": 0.8,
            },
        },
        session_id="session-1",
        candidate_id="candidate-1",
    )
    first = memory.on_session_end("session-1", subject_id="subject")
    second = memory.on_session_end("session-1", subject_id="subject")
    assert first["settlement_created"] is False
    assert first["pending_proposal_ids"] == ["22222222-2222-4222-8222-222222222222"]
    assert client.episodes[0] == client.episodes[1]
    assert second["episode"]["episode_id"] == first["episode"]["episode_id"]


def test_lifecycle_rejects_invalid_model_draft_before_client_call() -> None:
    client = _LifecycleClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        memory.create_proposal(
            {"operation": "CREATE"},
            session_id="session",
            candidate_id="invalid",
        )
    assert client.proposals == []
