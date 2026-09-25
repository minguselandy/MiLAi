from __future__ import annotations

from pathlib import Path

from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.models import receipt_outcome
from milai_lab.methods.contextual_memory.operations import TaskEnvelope
from milai_lab.methods.contextual_memory.revision import maintenance_records
from milai_lab.methods.contextual_user_memory import ContextualMemory, Observation


def test_known_invalidation_is_immediate_while_semantic_reviews_are_bounded(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "user")
    memory = ContextualMemory(
        "user", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, profile="support", deletion_ledger=ledger,
    )
    source = memory.publish(Observation("source", "Office access changed", "user", "test"))
    parent = memory.save(changeset={"groups": [{"operations": [
        {"op": "claim", "alias": "new:parent", "content": "Office access"},
        {"op": "justification", "target_ref": "new:parent", "polarity": "support",
         "items": [{"ref": source}]},
    ]}]})["changeset"]["aliases"]["new:parent"]
    descendants = []
    for number in range(6):
        result = memory.save(changeset={"groups": [{"operations": [
            {"op": "claim", "alias": "new:child", "content": f"Office plan {number}"},
            {"op": "justification", "target_ref": "new:child", "polarity": "support",
             "items": [{"ref": parent}]},
        ]}]})
        descendants.append(result["changeset"]["aliases"]["new:child"])
    result = memory.save(changeset={"groups": [{"operations": [
        {"op": "claim", "target_ref": parent, "content": "Office access ended"},
    ]}]})
    assert set(memory.revisions.pending) == set(descendants)
    assert receipt_outcome("memory_save", result).completion == "pending"
    assert all(memory.read(ref)["support_status"] == "UNUSABLE" for ref in descendants)
    assert len(maintenance_records(memory, "office", max_bytes=100000)) == 6
    memory.maintenance_mode = "pending"
    selected = maintenance_records(memory, "office", max_bytes=100000)
    assert len(selected) == 4
    restored = ContextualMemory.restore(memory.checkpoint(), user_id="user", embed=memory.embed)
    assert set(restored.revisions.pending) == set(descendants)
    memory.save(changeset={"groups": [{"operations": [
        {"op": "review", "target_ref": selected[0]["ref"], "decision": "keep"},
    ]}]})
    assert len(memory.revisions.pending) == 5
    assert memory.read(selected[0]["ref"])["support_status"] == "UNUSABLE"
    memory.start_task("lifecycle", "")
    envelope = TaskEnvelope(
        "user", "lifecycle", "lifecycle", frozenset({"delete"}), (source,),
        "delete-office-source", "delete_only", scope_id=str(tmp_path.resolve()),
    )
    memory.bind_envelope(envelope)
    memory.forget([source], envelope=envelope)
    assert memory.revisions.pending == {}
