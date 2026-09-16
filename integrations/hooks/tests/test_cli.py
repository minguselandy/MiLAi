from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from milai_client import AgentMemory, CapturePolicy
from milai_client.models import RecallEnvelope

from milai_hooks.cli import _optimized_context, _policy


class _Client:
    base_url = "http://127.0.0.1:18080"

    def __init__(self) -> None:
        self.recall_count = 0

    def recall(self, query: str, **options: Any) -> RecallEnvelope:
        self.recall_count += 1
        return RecallEnvelope.from_api(
            {
                "results": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "predicate": "project.status",
                        "payload": {"value": "synthetic"},
                    }
                ],
                "open_issue_ids": [],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-1",
                "consistency": options["consistency"],
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    def system_watermarks(self) -> Any:
        return SimpleNamespace(canonical_snapshot=7)

    def list_open_issues(self, status: str | None = None) -> list[Any]:
        return []


def _payload() -> dict[str, Any]:
    return {
        "session_id": "session-1",
        "query": "project status",
    }


def test_cross_process_slot_checkpoint_yields_validated_cache_without_second_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["milai"]}')
    client = _Client()
    first_memory = AgentMemory(client, CapturePolicy())  # type: ignore[arg-type]
    first = _optimized_context(first_memory, _payload())
    assert first["route"] == "L1"
    assert first["delta"]["status"] == "REPLACE"
    assert first["metrics"]["token_budget_verified"] is False
    assert isinstance(first["memory_slot"], dict)

    second_memory = AgentMemory(client, CapturePolicy())  # type: ignore[arg-type]
    next_payload = {**_payload(), "memory_slot": first["memory_slot"]}
    second = _optimized_context(second_memory, next_payload)
    assert second["route"] == "CACHE"
    assert second["delta"]["status"] == "UNCHANGED"
    assert second["context"] is None
    assert client.recall_count == 1


def test_hook_policy_requires_scope_for_action_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MILAI_AGENT_SCOPE_JSON", raising=False)
    monkeypatch.delenv("MILAI_AGENT_REQUIRED_AUTHORITY", raising=False)
    with pytest.raises(ValueError, match="non-empty host scope"):
        _policy({})


def test_hook_payload_cannot_override_host_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["milai"]}')
    with pytest.raises(PermissionError, match="cannot override"):
        _policy({"recall_scope": {"project_ids": ["attacker"]}})
    client = _Client()
    memory = AgentMemory(client, CapturePolicy())  # type: ignore[arg-type]
    with pytest.raises(PermissionError, match="cannot override"):
        _optimized_context(memory, {**_payload(), "budget_class": "HIGH"})


def test_hook_checkpoint_is_bound_to_current_host_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    monkeypatch.setenv("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["milai"]}')
    first = _optimized_context(AgentMemory(client, CapturePolicy()), _payload())  # type: ignore[arg-type]
    monkeypatch.setenv("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["other"]}')
    second = _optimized_context(  # type: ignore[arg-type]
        AgentMemory(client, CapturePolicy()),
        {**_payload(), "memory_slot": first["memory_slot"]},
    )
    assert second["route"] == "L1"
    assert client.recall_count == 2
