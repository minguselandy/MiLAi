from __future__ import annotations

import json
from pathlib import Path

import pytest

from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.operations import TaskEnvelope
from milai_lab.methods.contextual_user_memory import ContextualMemory, Observation


def lifecycle(ref: str, scope_id: str, operation_id: str = "delete-1") -> TaskEnvelope:
    return TaskEnvelope(
        "alice", "lifecycle", "lifecycle", frozenset({"delete"}),
        (ref,), operation_id, "delete_only", scope_id=scope_id,
    )


def test_external_deletion_survives_old_checkpoint_and_republication(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "alice-deletions.json", "alice")
    memory = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, deletion_ledger=ledger,
    )
    source = Observation("event", "Private old preference", "user", "archive")
    ref = memory.publish(source)
    first = memory.save(content="Private inference", source_ref=ref)["record"]["ref"]
    newer = memory.save(content="Revised private inference", target_ref=first)["record"]["ref"]
    memory.vectors[first] = [1.0, 0.0]
    memory.state.context = "Private task note"
    memory.state.intentions = [newer]
    old = memory.checkpoint()
    old_handoff = memory.handoff()
    memory.state.task_id = "lifecycle"
    envelope = lifecycle(ref, str(ledger.path.parent.resolve()))
    memory.bind_envelope(envelope)
    memory.forget([ref], envelope=envelope)
    assert memory.vectors == {}
    restored = ContextualMemory.restore(
        old, user_id="alice", embed=memory.embed, deletion_ledger=ledger,
    )
    assert restored.sources == {}
    assert restored.workspace.cards == {}
    assert "Private" not in json.dumps(restored.checkpoint())
    assert restored.publish(source) == ref
    assert ref not in restored.sources
    with pytest.raises(ValueError, match="HANDOFF_PRECEDES_FORGET"):
        restored.start_task("another", "Continue", handoff=old_handoff)
    created = restored.save(content="Unrelated idea")["record"]["ref"]
    assert created not in ledger.read().refs
    assert "Private" not in ledger.path.read_text()
    with pytest.raises(ValueError, match="USER_OR_VERSION_MISMATCH"):
        DeletionLedger(ledger.path, "bob").read()


def test_empty_mixed_and_unauthorized_delete_have_no_side_effects(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "alice")
    memory = ContextualMemory("alice", host_id="host", embed=lambda texts: [],
                              deletion_ledger=ledger)
    memory.start_task("answer", "Keep answering")
    ref = memory.publish(Observation("event", "Private", "user", "archive"))
    before = json.dumps(memory.checkpoint(), sort_keys=True)
    assert memory.save(forget_refs=[])["decision"] == "NO_CHANGE"
    assert memory.dispatch("memory_save", {"forget_refs": []})["decision"] == "NO_CHANGE"
    assert memory.dispatch("memory_save", {"content": "New", "forget_refs": []})[
        "decision"
    ] == "REJECTED"
    assert memory.dispatch("memory_save", {"forget_refs": [ref]})[
        "decision"
    ] == "REJECTED"
    assert json.dumps(memory.checkpoint(), sort_keys=True) == before
    assert ledger.read().generation == 0
    assert not ledger.path.exists()


def test_committed_delete_resumes_effects_without_new_generation(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "alice")
    memory = ContextualMemory("alice", host_id="host", embed=lambda texts: [],
                              deletion_ledger=ledger)
    ref = memory.publish(Observation("event", "Private", "user", "archive"))
    memory.save(source_ref=ref)
    old = memory.checkpoint()
    memory.start_task("lifecycle", "")
    memory.bind_envelope(lifecycle(ref, str(ledger.path.parent.resolve())))
    receipt = memory.forget(
        [ref], envelope=lifecycle(ref, str(ledger.path.parent.resolve())),
        cleanup_effects=("history_artifacts",),
    )
    assert receipt["completion"] == "pending"
    assert ledger.read().generation == 1
    assert ledger.read().operations["delete-1"].pending_effects == ("history_artifacts",)
    restored = ContextualMemory.restore(
        old, user_id="alice", embed=memory.embed, deletion_ledger=ledger,
    )
    assert ref not in restored.sources
    assert ledger.read().generation == 1
    done = ledger.complete_effect("delete-1", "history_artifacts")
    assert done.pending_effects == ()
    memory.forget([ref], envelope=lifecycle(ref, str(ledger.path.parent.resolve())),
                  cleanup_effects=("history_artifacts",))
    assert ledger.read().generation == 1
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        memory.forget([ref], envelope=lifecycle(ref, str(ledger.path.parent.resolve())),
                      cleanup_effects=("answer_artifacts",))
