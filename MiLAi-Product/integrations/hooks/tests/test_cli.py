from __future__ import annotations

import json
import sys
from io import StringIO
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from milai_client import AgentMemory, CapturePolicy, MilaiClientError
from milai_client.models import RecallEnvelope

from milai_hooks.cli import _optimized_context, _policy, main


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


class _JournalCliClient:
    instances: ClassVar[list[_JournalCliClient]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.capture_calls = 0
        self.journal_calls = 0
        self.closed = False
        self.fail_journal = False
        type(self).instances.append(self)

    def capture_evidence(self, payload: Any, *, operation_id: str) -> Any:
        self.capture_calls += 1
        return SimpleNamespace(
            raw={
                "evidence_id": "11111111-1111-4111-8111-111111111111",
                "replayed": False,
            }
        )

    def append_host_execution_event(
        self,
        payload: Any,
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        self.journal_calls += 1
        if self.fail_journal:
            raise MilaiClientError(
                "synthetic journal failure",
                code="ENDPOINT_UNAVAILABLE",
                retryable=True,
            )
        return {"status": "APPENDED"}

    def close(self) -> None:
        self.closed = True


class _ReconcileCliClient:
    instances: ClassVar[list[_ReconcileCliClient]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.update_calls: list[tuple[dict[str, Any], str]] = []
        self.closed = False
        type(self).instances.append(self)

    def get_working_state(self, binding: Any) -> dict[str, Any]:
        return {
            "schema_version": "host-cognitive-state-v1",
            "schema_name": "codex-cognitive-state-v1",
            "status": "ACTIVE",
            "state_id": "11111111-1111-4111-8111-111111111111",
            "state_version_id": "22222222-2222-4222-8222-222222222222",
            "version": 2,
            "authority": "HOST_WORKING",
            "scope": "TASK",
            "payload": {"task": {"active_goal": "old"}},
            "warnings": [],
        }

    def get_host_execution_event_window(self, binding: Any) -> dict[str, Any]:
        return {
            "schema_version": "host-execution-event-v1",
            "status": "WINDOW",
            "after_position": binding["after_position"],
            "next_position": 7,
            "visible_high_watermark": 7,
            "has_more": False,
            "events": [
                {
                    "event_id": "33333333-3333-4333-8333-333333333333",
                    "position": 7,
                    "warnings": [],
                }
            ],
        }

    def update_working_state(
        self,
        payload: Any,
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        self.update_calls.append((dict(payload), operation_id))
        return {
            "schema_version": "host-cognitive-state-v1",
            "schema_name": "codex-cognitive-state-v1",
            "status": "ACTIVE",
            "state_id": "11111111-1111-4111-8111-111111111111",
            "state_version_id": "44444444-4444-4444-8444-444444444444",
            "version": 3,
            "authority": "HOST_WORKING",
            "scope": "TASK",
            "payload": payload["payload"],
            "warnings": [],
        }

    def close(self) -> None:
        self.closed = True


def _payload() -> dict[str, Any]:
    return {
        "session_id": "session-1",
        "query": "project status",
    }


def _agent_event_payload() -> dict[str, Any]:
    return {
        "schema_version": "host-agent-event-v1",
        "event_id": "event-cli-1",
        "event_type": "USER_MESSAGE",
        "session_id": "session-cli-1",
        "source_id": "codex:session-cli-1:turn-1",
        "subject_id": "user-cli-1",
        "observed_at": "2026-09-05T02:00:00+08:00",
        "content": "Continue the prior task.",
        "turn_id": "turn-1",
        "turn_ordinal": 1,
    }


def _configure_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MILAI_HOST_EVENT_CAPTURE", "ON")
    monkeypatch.setenv("MILAI_HOST_EVENT_JOURNAL", "SHADOW")
    monkeypatch.setenv("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["project-one"]}')
    monkeypatch.setenv("MILAI_HOST_PROJECT_ID", "project-one")
    monkeypatch.setenv("MILAI_HOST_TASK_REF", "task-one")
    monkeypatch.setenv("MILAI_HOST_PRINCIPAL_BINDING_DIGEST", "a" * 64)
    monkeypatch.setattr("milai_hooks.cli.MilaiClient", _JournalCliClient)
    monkeypatch.setattr(sys, "argv", ["milai-hook", "AgentEvent"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(_agent_event_payload())))


def _configure_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_version: int = 2,
) -> None:
    event_id = "33333333-3333-4333-8333-333333333333"
    monkeypatch.setenv("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["project-one"]}')
    monkeypatch.setenv("MILAI_HOST_PROJECT_ID", "project-one")
    monkeypatch.setenv("MILAI_HOST_TASK_REF", "task-one")
    monkeypatch.setenv("MILAI_HOST_PRINCIPAL_BINDING_DIGEST", "a" * 64)
    monkeypatch.setattr("milai_hooks.cli.MilaiClient", _ReconcileCliClient)
    monkeypatch.setattr(sys, "argv", ["milai-hook", "ReconcileState"])
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(
            json.dumps(
                {
                    "operation_id": "reconcile-cli-one",
                    "expected_event_high_watermark": 7,
                    "delta": {
                        "base_state_id": "11111111-1111-4111-8111-111111111111",
                        "base_version": base_version,
                        "no_material_change": False,
                        "changes": [
                            {
                                "field": "next_actions",
                                "op": "REPLACE",
                                "value": ["run tests"],
                                "reason_event_ids": [event_id],
                            }
                        ],
                    },
                }
            )
        ),
    )


def test_explicit_reconciliation_cli_runs_host_bound_cas(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ReconcileCliClient.instances.clear()
    _configure_reconciliation(monkeypatch)

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "UPDATED"
    assert output["state"]["version"] == 3
    assert output["basis_candidate"] == {"event_position": 7, "persisted": False}
    client = _ReconcileCliClient.instances[0]
    assert client.update_calls[0][0]["scope_type"] == "TASK"
    assert client.update_calls[0][0]["scope_ref"] == "task-one"
    assert client.update_calls[0][1].startswith("host-state-reconcile-v1:")
    assert output["operation_id"] == "reconcile-cli-one"
    assert client.closed is True


def test_explicit_reconciliation_cli_returns_actionable_delta_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ReconcileCliClient.instances.clear()
    _configure_reconciliation(monkeypatch, base_version=1)

    with pytest.raises(SystemExit) as captured:
        main()

    assert captured.value.code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "REJECTED"
    assert output["error"]["code"] == "BASE_MISMATCH"
    assert output["error"]["problem"]
    assert output["error"]["fix"]
    client = _ReconcileCliClient.instances[0]
    assert client.update_calls == []
    assert client.closed is True


def test_explicit_reconciliation_cli_explains_invalid_evidence_reference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ReconcileCliClient.instances.clear()
    _configure_reconciliation(monkeypatch)

    def reject_invalid_evidence(
        self: _ReconcileCliClient,
        payload: Any,
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        self.update_calls.append((dict(payload), operation_id))
        raise MilaiClientError(
            "Working State contains an invalid Evidence reference.",
            status_code=409,
            code="EVIDENCE_REFERENCE_INVALID",
            details={"evidence_id": "55555555-5555-4555-8555-555555555555"},
        )

    monkeypatch.setattr(_ReconcileCliClient, "update_working_state", reject_invalid_evidence)

    with pytest.raises(SystemExit) as captured:
        main()

    assert captured.value.code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "REJECTED"
    assert output["error"]["code"] == "EVIDENCE_REFERENCE_INVALID"
    assert "remove stale or unreadable Evidence refs" in output["error"]["fix"]
    assert output["error"]["details"] == {"evidence_id": "55555555-5555-4555-8555-555555555555"}
    client = _ReconcileCliClient.instances[0]
    assert len(client.update_calls) == 1
    assert client.closed is True


def test_reconciliation_does_not_depend_on_recall_authority_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ReconcileCliClient.instances.clear()
    _configure_reconciliation(monkeypatch)
    monkeypatch.setenv("MILAI_AGENT_REQUIRED_AUTHORITY", "NOT_A_RECALL_AUTHORITY")

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "UPDATED"


def test_shadow_configuration_is_validated_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _JournalCliClient.instances.clear()
    _configure_shadow(monkeypatch)
    monkeypatch.setenv("MILAI_HOST_PROJECT_ID", "outside-host-scope")

    with pytest.raises(PermissionError, match="project binding"):
        main()

    client = _JournalCliClient.instances[0]
    assert client.capture_calls == 0
    assert client.journal_calls == 0
    assert client.closed is True


def test_dynamic_journal_failure_reports_committed_evidence_and_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _JournalCliClient.instances.clear()
    _configure_shadow(monkeypatch)
    original_init = _JournalCliClient.__init__

    def failing_init(self: _JournalCliClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.fail_journal = True

    monkeypatch.setattr(_JournalCliClient, "__init__", failing_init)
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PARTIAL_EVIDENCE_CAPTURED_JOURNAL_PENDING_RETRY"
    assert output["receipt"]["evidence_id"] == "11111111-1111-4111-8111-111111111111"
    assert output["journal"] == {
        "status": "PENDING_RETRY",
        "reason_code": "ENDPOINT_UNAVAILABLE",
        "runtime_retryable": True,
        "event_retry_safe": True,
    }
    client = _JournalCliClient.instances[0]
    assert client.capture_calls == 1
    assert client.journal_calls == 1
    assert client.closed is True


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
