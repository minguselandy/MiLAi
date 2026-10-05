"""Ordinary checkpoint source versions retain the existing audit ownership boundary."""

import copy

import pytest

from milai_lab.methods.memory_boundaries import operation_audit


def test_checkpoint_source_versions_and_body_are_preserved_without_dto_fingerprint() -> None:
    scope = {"run_id": "r", "arm_id": "ordinary", "user_id": "alice", "message_key": "turn"}
    messages = [
        {"type": "human", "id": "current", "content": "Remember the real receipt.",
         "source_revision": 4},
        {"type": "ai", "response_metadata": {"memory_turn": scope}, "tool_calls": [
            {"id": "call", "name": "manage_memory", "args": {"action": "create"}}]},
        {"type": "tool", "id": "receipt", "name": "manage_memory", "tool_call_id": "call",
         "content": '{"ok":true,"status":"created","id":"record"}', "source_revision": 7},
    ]
    originals = copy.deepcopy(messages)
    audit = operation_audit(messages, scope, "thread")
    assert [ref["source_revision"] for ref in audit["source_events"]] == [4, 7]
    assert all("content_sha256" not in ref for ref in audit["source_events"])
    assert audit["operations"][0]["created_from_event_ids"] == ["message:current"]
    assert audit["operations"][0]["receipt"]["content"] == messages[2]["content"]
    foreign = {**scope, "user_id": "bob"}
    assert not operation_audit(messages, foreign, "thread")["operations"]
    assert messages == originals
    assert operation_audit(
        [{"type": "human", "id": "immutable", "content": "Original SDK message."}],
        scope, "thread",
    )["source_events"][0]["source_revision"] == 1


@pytest.mark.parametrize("revision", [None, True, 0, -1, "2"])
def test_checkpoint_source_revision_rejects_invalid_adapter_versions(revision) -> None:
    with pytest.raises(ValueError, match="MEMORY_BOUNDARY_SOURCE_REVISION_INVALID"):
        operation_audit(
            [{"type": "human", "id": "actual", "content": "Actual source.",
              "source_revision": revision}],
            {"user_id": "alice"}, "thread",
        )
