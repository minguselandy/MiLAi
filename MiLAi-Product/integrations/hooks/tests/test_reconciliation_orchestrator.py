from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest
from milai_client import ConflictError

from milai_hooks.reconciliation_orchestrator import (
    ReconciliationOrchestrationError,
    reconcile_working_state_explicit,
    reconciliation_runtime_operation_id,
)
from milai_hooks.state_reconciliation import StateDeltaError

_STATE_ID = "11111111-1111-4111-8111-111111111111"
_EVENT_ONE = "22222222-2222-4222-8222-222222222222"
_EVENT_TWO = "33333333-3333-4333-8333-333333333333"


def _state(
    *,
    status: str = "ACTIVE",
    state_id: str | None = _STATE_ID,
    version: int = 2,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "host-cognitive-state-v1",
        "schema_name": "codex-cognitive-state-v1",
        "status": status,
        "state_id": state_id,
        "state_version_id": "44444444-4444-4444-8444-444444444444",
        "version": version,
        "authority": "HOST_WORKING",
        "scope": "TASK",
        "payload": {"task": {"active_goal": "old"}} if payload is None else payload,
        "warnings": [],
    }


def _event(
    event_id: str,
    position: int,
    *,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "position": position,
        "event_family": "DIALOGUE",
        "event_type": "MESSAGE",
        "observed_at": "2026-09-05T01:00:00+00:00",
        "bounded_payload": {"role": "USER"},
        "evidence_refs": ["55555555-5555-4555-8555-555555555555"],
        "warnings": [] if warnings is None else warnings,
        "created_at": "2026-09-05T01:00:01+00:00",
    }


def _window(
    events: list[dict[str, Any]],
    *,
    after_position: int = 0,
    high_watermark: int | None = None,
    has_more: bool = False,
) -> dict[str, Any]:
    next_position = events[-1]["position"] if events else after_position
    return {
        "schema_version": "host-execution-event-v1",
        "status": "WINDOW",
        "after_position": after_position,
        "next_position": next_position,
        "visible_high_watermark": (next_position if high_watermark is None else high_watermark),
        "has_more": has_more,
        "events": events,
    }


def _delta(
    *,
    state_id: str | None = _STATE_ID,
    version: int = 2,
    no_material_change: bool = False,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "base_state_id": state_id,
        "base_version": version,
        "no_material_change": no_material_change,
        "changes": (
            []
            if no_material_change
            else [
                {
                    "field": "next_actions",
                    "op": "REPLACE",
                    "value": ["run the focused regression"],
                    "reason_event_ids": [_EVENT_ONE] if reasons is None else reasons,
                }
            ]
        ),
    }


class _Client:
    def __init__(
        self,
        *,
        state: dict[str, Any] | None = None,
        window: dict[str, Any] | None = None,
    ) -> None:
        self.state = _state() if state is None else state
        self.window = (
            _window([_event(_EVENT_ONE, 3), _event(_EVENT_TWO, 9)]) if window is None else window
        )
        self.get_state_calls: list[dict[str, Any]] = []
        self.get_window_calls: list[dict[str, Any]] = []
        self.update_calls: list[tuple[dict[str, Any], str]] = []
        self.conflict = False

    def get_working_state(self, binding: Mapping[str, Any]) -> dict[str, Any]:
        self.get_state_calls.append(dict(binding))
        return deepcopy(self.state)

    def get_host_execution_event_window(
        self,
        binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.get_window_calls.append(dict(binding))
        return deepcopy(self.window)

    def update_working_state(
        self,
        payload: Mapping[str, Any],
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        self.update_calls.append((deepcopy(dict(payload)), operation_id))
        if self.conflict:
            raise ConflictError(
                "synthetic stale state",
                status_code=409,
                code="STALE_WORKING_STATE",
            )
        state_id = payload["state_id"] or _STATE_ID
        return _state(
            state_id=str(state_id),
            version=int(payload["expected_version"]) + 1,
            payload=deepcopy(payload["payload"]),
        )


def _reconcile(
    client: _Client,
    raw_delta: Mapping[str, Any],
    **options: Any,
) -> dict[str, Any]:
    return reconcile_working_state_explicit(
        client,
        principal_binding_digest="a" * 64,
        project_id="project-one",
        task_ref="task-one",
        raw_delta=raw_delta,
        operation_id="reconcile-one",
        expected_event_high_watermark=options.pop("expected_event_high_watermark", 9),
        **options,
    )


def test_explicit_reconciliation_reads_exact_bindings_and_writes_one_cas_version() -> None:
    client = _Client()

    result = _reconcile(client, _delta())

    assert result["status"] == "UPDATED"
    assert result["state"]["version"] == 3
    assert result["state"]["payload"] == {
        "task": {"active_goal": "old"},
        "next_actions": ["run the focused regression"],
    }
    assert result["event_window"] == {
        "after_position": 0,
        "through_position": 9,
        "visible_high_watermark": 9,
        "event_count": 2,
        "eligible_event_count": 2,
        "ineligible_event_ids": [],
        "has_more": False,
    }
    assert result["basis_candidate"] == {"event_position": 9, "persisted": False}
    assert result["canonical_mutation"] is False
    assert client.get_state_calls == [
        {
            "principal_binding_digest": "a" * 64,
            "project_id": "project-one",
            "scope_type": "TASK",
            "scope_ref": "task-one",
        }
    ]
    assert client.get_window_calls == [
        {
            "principal_binding_digest": "a" * 64,
            "project_id": "project-one",
            "task_ref": "task-one",
            "after_position": 0,
            "limit": 100,
        }
    ]
    assert client.update_calls == [
        (
            {
                "principal_binding_digest": "a" * 64,
                "project_id": "project-one",
                "scope_type": "TASK",
                "scope_ref": "task-one",
                "state_id": _STATE_ID,
                "expected_version": 2,
                "payload": result["state"]["payload"],
            },
            reconciliation_runtime_operation_id(
                principal_binding_digest="a" * 64,
                project_id="project-one",
                task_ref="task-one",
                public_operation_id="reconcile-one",
            ),
        )
    ]
    assert result["operation_id"] == "reconcile-one"


def test_public_operation_id_is_namespaced_to_the_exact_host_binding() -> None:
    common = {
        "project_id": "project-one",
        "task_ref": "task-one",
        "public_operation_id": "same-public-operation",
    }
    first = reconciliation_runtime_operation_id(
        principal_binding_digest="a" * 64,
        **common,
    )
    replay = reconciliation_runtime_operation_id(
        principal_binding_digest="a" * 64,
        **common,
    )
    other_principal = reconciliation_runtime_operation_id(
        principal_binding_digest="b" * 64,
        **common,
    )
    other_task = reconciliation_runtime_operation_id(
        principal_binding_digest="a" * 64,
        **{**common, "task_ref": "task-two"},
    )

    assert first == replay
    assert first.startswith("host-state-reconcile-v1:")
    assert first != other_principal
    assert first != other_task


def test_absent_state_creates_v1_only_after_a_material_delta() -> None:
    client = _Client(state=_state(status="ABSENT", state_id=None, version=0, payload={}))

    result = _reconcile(client, _delta(state_id=None, version=0))

    assert result["status"] == "UPDATED"
    assert result["state"]["version"] == 1
    assert client.update_calls[0][0]["state_id"] is None
    assert client.update_calls[0][0]["expected_version"] == 0


def test_no_material_change_does_not_write_or_persist_a_basis() -> None:
    client = _Client()

    result = _reconcile(client, _delta(no_material_change=True))

    assert result["status"] == "NO_MATERIAL_CHANGE"
    assert result["working_state_mutation"] is False
    assert result["basis_candidate"]["persisted"] is False
    assert client.update_calls == []


def test_numeric_event_position_gaps_are_legal() -> None:
    client = _Client(window=_window([_event(_EVENT_ONE, 3), _event(_EVENT_TWO, 19)]))

    result = _reconcile(client, _delta(), expected_event_high_watermark=19)

    assert result["status"] == "UPDATED"
    assert result["event_window"]["through_position"] == 19


def test_incomplete_event_window_never_writes_state() -> None:
    client = _Client(
        window=_window(
            [_event(_EVENT_ONE, 3)],
            high_watermark=9,
            has_more=True,
        )
    )

    with pytest.raises(ReconciliationOrchestrationError) as captured:
        _reconcile(client, _delta(), event_limit=1)

    assert captured.value.code == "EVENT_WINDOW_INCOMPLETE"
    assert client.update_calls == []


def test_late_event_changes_watermark_and_forces_delta_regeneration() -> None:
    client = _Client(window=_window([_event(_EVENT_ONE, 3), _event(_EVENT_TWO, 12)]))

    with pytest.raises(ReconciliationOrchestrationError) as captured:
        _reconcile(client, _delta(), expected_event_high_watermark=9)

    assert captured.value.code == "EVENT_WINDOW_CHANGED"
    assert client.update_calls == []


def test_event_cursor_cannot_advance_beyond_the_visible_high_watermark() -> None:
    client = _Client(window=_window([], after_position=100, high_watermark=9))

    with pytest.raises(ReconciliationOrchestrationError) as captured:
        _reconcile(
            client,
            _delta(no_material_change=True),
            after_position=100,
            expected_event_high_watermark=9,
        )

    assert captured.value.code == "INVALID_RUNTIME_RESPONSE"
    assert client.update_calls == []


def test_revoked_or_unreadable_event_reference_is_not_eligible() -> None:
    warning = {
        "code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE",
        "evidence_id": "55555555-5555-4555-8555-555555555555",
    }
    client = _Client(window=_window([_event(_EVENT_ONE, 3, warnings=[warning])]))

    with pytest.raises(ReconciliationOrchestrationError) as captured:
        _reconcile(client, _delta(), expected_event_high_watermark=3)

    assert captured.value.code == "EVENT_REFERENCE_NOT_ELIGIBLE"
    assert client.update_calls == []


@pytest.mark.parametrize("status", ["EXPIRED", "REVOKED"])
def test_unusable_working_state_never_falls_back_to_fabricated_freshness(status: str) -> None:
    client = _Client(state=_state(status=status))

    with pytest.raises(ReconciliationOrchestrationError) as captured:
        _reconcile(client, _delta())

    assert captured.value.code == "WORKING_STATE_NOT_USABLE"
    assert client.get_window_calls == []
    assert client.update_calls == []


def test_delta_must_target_the_runtime_head() -> None:
    client = _Client()

    with pytest.raises(StateDeltaError) as captured:
        _reconcile(client, _delta(version=1))

    assert captured.value.code == "BASE_MISMATCH"
    assert client.update_calls == []


def test_runtime_cas_conflict_propagates_without_a_false_success_receipt() -> None:
    client = _Client()
    client.conflict = True

    with pytest.raises(ConflictError) as captured:
        _reconcile(client, _delta())

    assert captured.value.code == "STALE_WORKING_STATE"
    assert len(client.update_calls) == 1


def test_malformed_runtime_window_is_rejected_before_state_write() -> None:
    client = _Client(
        window=_window(
            [_event(_EVENT_ONE, 9), _event(_EVENT_TWO, 3)],
            high_watermark=9,
        )
    )

    with pytest.raises(ReconciliationOrchestrationError) as captured:
        _reconcile(client, _delta())

    assert captured.value.code == "INVALID_RUNTIME_RESPONSE"
    assert client.update_calls == []
