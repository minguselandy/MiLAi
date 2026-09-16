from __future__ import annotations

import pytest

from milai_client import TaskIdentityState, TaskMemoryBinding, TaskMemoryState


def _payload(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "task-orchid-release",
        "active_goal_id": "goal-orchid-release",
        "active_goal_version": 1,
        "active_goal_summary": "Prepare the governed release candidate.",
        "project_scope": {"project_ids": ["synthetic-orchid"]},
        "profile_identity": "reader-lite",
        "execution_lane_id": "lane-release",
        "task_generation": 1,
        "binding_generation": 1,
    }
    value.update(updates)
    return value


def test_host_task_state_keeps_current_utterance_out_of_binding() -> None:
    state = TaskMemoryState.from_host_payload(
        _payload(),
        fallback_task_id="unused",
        fallback_scope={},
        fallback_profile_id="reader-lite",
    )

    assert state.active_goal_summary == "Prepare the governed release candidate."
    assert isinstance(state.identity, TaskIdentityState)
    assert isinstance(state.memory_binding, TaskMemoryBinding)
    assert state.identity.execution_lane_id == "lane-release"
    assert (
        state.binding_digest
        == TaskMemoryState.from_host_payload(
            _payload(),
            fallback_task_id="unused",
            fallback_scope={},
            fallback_profile_id="reader-lite",
        ).binding_digest
    )


def test_identity_binding_digest_changes_only_with_host_identity() -> None:
    original = TaskMemoryState.from_host_payload(
        _payload(),
        fallback_task_id="unused",
        fallback_scope={},
        fallback_profile_id="reader-lite",
    )

    rebound = TaskMemoryState.from_host_payload(
        _payload(active_goal_version=2, binding_generation=2),
        fallback_task_id="unused",
        fallback_scope={},
        fallback_profile_id="reader-lite",
    )
    hints_only = TaskMemoryState.from_host_payload(
        _payload(known_claim_ids=["11111111-1111-1111-1111-111111111111"]),
        fallback_task_id="unused",
        fallback_scope={},
        fallback_profile_id="reader-lite",
    )

    assert rebound.binding_digest != original.binding_digest
    assert hints_only.binding_digest == original.binding_digest


def test_host_state_rejects_unknown_fields_and_non_uuid_hints() -> None:
    with pytest.raises(ValueError, match="field set"):
        TaskMemoryState.from_host_payload(
            _payload(user_marker="not trusted"),
            fallback_task_id="unused",
            fallback_scope={},
            fallback_profile_id="reader-lite",
        )


def test_host_state_rejects_generation_and_identity_binding_mismatch() -> None:
    with pytest.raises(ValueError, match="task_generation"):
        TaskMemoryState.from_host_payload(
            _payload(task_generation=0),
            fallback_task_id="unused",
            fallback_scope={},
            fallback_profile_id="reader-lite",
        )
    with pytest.raises(ValueError, match="field set"):
        TaskMemoryState.from_host_payload(
            _payload(profile_id="reader-lite"),
            fallback_task_id="unused",
            fallback_scope={},
            fallback_profile_id="reader-lite",
        )
    with pytest.raises(ValueError, match="UUIDs"):
        TaskMemoryState.from_host_payload(
            _payload(known_claim_ids=["not-a-uuid"]),
            fallback_task_id="unused",
            fallback_scope={},
            fallback_profile_id="reader-lite",
        )
