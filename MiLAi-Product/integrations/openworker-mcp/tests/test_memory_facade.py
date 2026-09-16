from __future__ import annotations

from typing import Any

import pytest

from milai_openworker_mcp import (
    OpenWorkerMemoryFacade,
    decode_memory_support_lineage,
)


class _Reader:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.payload = payload

    def resolve_memory(
        self, query: str, *, previous_context_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((query, previous_context_id))
        if self.payload is not None:
            return self.payload
        return {
            "status": "PARTIAL",
            "context_receipt": {
                "context_capsule_id": "context-1",
                "receipt_mapping": [
                    {
                        "alias": "E1",
                        "evidence_ids": ["evidence-original"],
                        "source_turn_refs": ["source-original"],
                        "claim_versions": [],
                    }
                ],
            },
        }


class _Submitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def capture_evidence(self, payload):  # type: ignore[no-untyped-def]
        self.calls.append(dict(payload))
        sequence = len(self.calls)
        return {
            "evidence_id": f"captured-{sequence}",
            "outbox_id": f"outbox-{sequence}",
            "replayed": False,
        }

    def create_proposal(self, payload):  # type: ignore[no-untyped-def]
        raise AssertionError(f"facade must not create a Proposal: {payload}")


def _facade(reader: _Reader, submitter: _Submitter) -> OpenWorkerMemoryFacade:
    return OpenWorkerMemoryFacade(
        reader,
        submitter=submitter,
        subject_id="local-user",
        permission_snapshot={"readable": True, "project_ids": ["personal-memory"]},
        data_classification="PERSONAL",
    )


def test_facade_recalls_then_settles_exact_user_and_assistant_turns() -> None:
    reader = _Reader()
    submitter = _Submitter()
    facade = _facade(reader, submitter)

    recall = facade.recall_for_operation("What did I say?")
    receipt = facade.settle_exchange(
        task_epoch="task-epoch-1",
        session_id="ses-1",
        user_message_id="msg-7",
        assistant_message_id="msg-8",
        user_content="What did I say?",
        assistant_content="You said the marker is cedar.",
        user_observed_at="2026-09-02T14:00:00+00:00",
        assistant_observed_at="2026-09-02T14:00:01+00:00",
        round_ordinal=3,
        context_sha256="a" * 64,
        support_aliases=("E1",),
        recall=recall,
    )

    assert reader.calls == [("What did I say?", None)]
    assert receipt.outbox_ids == ("outbox-1", "outbox-2")
    assert [call["speaker"] for call in submitter.calls] == ["user", "assistant"]
    assert [call["content"] for call in submitter.calls] == [
        "What did I say?",
        "You said the marker is cedar.",
    ]
    user, assistant = submitter.calls
    assert user["source_context"] == {
        "session_id": "ses-1",
        "turn_id": "msg-7",
        "turn_ordinal": 6,
        "round_id": "msg-7",
        "round_ordinal": 3,
        "next_turn_id": "msg-8",
    }
    assert assistant["source_context"]["previous_turn_id"] == "msg-7"
    assert assistant["source_context"]["turn_id"] == "msg-8"
    assert assistant["source_context"]["turn_ordinal"] == 7
    assert assistant["permission_snapshot"] == {
        "readable": True,
        "project_ids": ["personal-memory"],
    }
    assert receipt.memory_support is not None
    assert receipt.memory_support.evidence_ids == ("evidence-original",)
    assert decode_memory_support_lineage(assistant["source_ref"]) == receipt.memory_support


def test_facade_does_not_capture_context_system_or_secret_bearing_provider_input() -> None:
    reader = _Reader()
    submitter = _Submitter()
    facade = _facade(reader, submitter)
    recall = facade.recall_for_operation("Remember cedar")

    facade.settle_exchange(
        task_epoch="task-epoch-1",
        session_id="ses-1",
        user_message_id="msg-8",
        assistant_message_id="msg-9",
        user_content="Remember cedar; token=super-secret-value-123456",
        assistant_content="I will remember cedar.",
        user_observed_at="2026-09-02T14:01:00+00:00",
        assistant_observed_at="2026-09-02T14:01:01+00:00",
        round_ordinal=4,
        recall=recall,
    )

    captured = "\n".join(call["content"] for call in submitter.calls)
    assert "MILAI_CONTEXT" not in captured
    assert "system prompt" not in captured
    assert "super-secret-value" not in captured
    assert "[REDACTED]" in submitter.calls[0]["content"]


def test_facade_rejects_non_visible_support_alias_without_writing() -> None:
    reader = _Reader()
    submitter = _Submitter()
    facade = _facade(reader, submitter)
    recall = facade.recall_for_operation("Remember cedar")

    with pytest.raises(ValueError, match="not Reader-visible"):
        facade.settle_exchange(
            task_epoch="task-epoch-1",
            session_id="ses-1",
            user_message_id="msg-8",
            assistant_message_id="msg-9",
            user_content="Remember cedar",
            assistant_content="Cedar.",
            user_observed_at="2026-09-02T14:01:00+00:00",
            assistant_observed_at="2026-09-02T14:01:01+00:00",
            round_ordinal=4,
            context_sha256="b" * 64,
            support_aliases=("E2",),
            recall=recall,
        )

    assert submitter.calls == []


def test_facade_restart_replay_uses_same_persistent_idempotency_keys() -> None:
    reader = _Reader()
    first_lane = _Submitter()
    first = _facade(reader, first_lane)
    recall = first.recall_for_operation("Remember cedar")
    first.settle_exchange(
        task_epoch="first-process",
        session_id="ses-1",
        user_message_id="msg-stable",
        assistant_message_id="msg-assistant-stable",
        user_content="Remember cedar",
        assistant_content="Cedar.",
        user_observed_at="2026-09-02T14:01:00+00:00",
        assistant_observed_at="2026-09-02T14:01:01+00:00",
        round_ordinal=0,
        context_sha256="c" * 64,
        support_aliases=("E1",),
        recall=recall,
    )

    restarted_lane = _Submitter()
    restarted = _facade(reader, restarted_lane)
    restarted.settle_exchange(
        task_epoch="second-process",
        session_id="ses-1",
        user_message_id="msg-stable",
        assistant_message_id="msg-assistant-stable",
        user_content="Remember cedar",
        assistant_content="Cedar.",
        user_observed_at="2026-09-02T14:01:00+00:00",
        assistant_observed_at="2026-09-02T14:01:01+00:00",
        round_ordinal=0,
        context_sha256="c" * 64,
        support_aliases=("E1",),
        recall=recall,
    )

    assert [call["operation_id"] for call in restarted_lane.calls] == [
        call["operation_id"] for call in first_lane.calls
    ]


def test_memory_derived_assistant_support_is_rebased_to_original_evidence() -> None:
    first_reader = _Reader()
    first_lane = _Submitter()
    first = _facade(first_reader, first_lane)
    initial_recall = first.recall_for_operation("What is the marker?")
    first.settle_exchange(
        task_epoch="first-process",
        session_id="ses-1",
        user_message_id="msg-user-1",
        assistant_message_id="msg-assistant-1",
        user_content="What is the marker?",
        assistant_content="The marker is cedar.",
        user_observed_at="2026-09-02T14:01:00+00:00",
        assistant_observed_at="2026-09-02T14:01:01+00:00",
        round_ordinal=0,
        context_sha256="d" * 64,
        support_aliases=("E1",),
        recall=initial_recall,
    )
    derived_source_ref = first_lane.calls[1]["source_ref"]

    second_reader = _Reader(
        {
            "status": "PARTIAL",
            "context_receipt": {
                "context_capsule_id": "context-2",
                "receipt_mapping": [
                    {
                        "alias": "E1",
                        "evidence_ids": ["derived-assistant"],
                        "source_turn_refs": [derived_source_ref],
                        "claim_versions": [],
                    }
                ],
            },
        }
    )
    second_lane = _Submitter()
    second = _facade(second_reader, second_lane)
    second_recall = second.recall_for_operation("Repeat the marker")
    receipt = second.settle_exchange(
        task_epoch="second-process",
        session_id="ses-2",
        user_message_id="msg-user-2",
        assistant_message_id="msg-assistant-2",
        user_content="Repeat the marker",
        assistant_content="The marker is cedar.",
        user_observed_at="2026-09-02T14:02:00+00:00",
        assistant_observed_at="2026-09-02T14:02:01+00:00",
        round_ordinal=0,
        context_sha256="e" * 64,
        support_aliases=("E1",),
        recall=second_recall,
    )

    assert receipt.memory_support is not None
    assert receipt.memory_support.evidence_ids == ("evidence-original",)
    assert "derived-assistant" not in receipt.memory_support.evidence_ids
    assert decode_memory_support_lineage(second_lane.calls[1]["source_ref"]) == (
        receipt.memory_support
    )


def test_facade_requires_submitter_and_host_subject_for_settlement() -> None:
    reader = _Reader()
    with pytest.raises(ValueError, match="subject_id"):
        OpenWorkerMemoryFacade(reader, submitter=_Submitter())
    read_only = OpenWorkerMemoryFacade(reader)
    assert read_only.settlement_enabled is False
