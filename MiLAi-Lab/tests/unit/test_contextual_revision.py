"""Distinct failure mechanisms of exact-version local support repair."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from milai_lab.methods.contextual_memory.deletion import DeletionLedger
from milai_lab.methods.contextual_memory.models import Observation, receipt_outcome
from milai_lab.methods.contextual_memory.operations import TaskEnvelope
from milai_lab.methods.contextual_user_memory import ContextualMemory


def memory(ledger: DeletionLedger | None = None) -> ContextualMemory:
    return ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, profile="support", deletion_ledger=ledger,
    )


def test_joint_and_alternate_support_survive_local_source_change(tmp_path: Path) -> None:
    ledger = DeletionLedger(tmp_path / "deletions.json", "alice")
    mem = memory(ledger)
    a = mem.publish(Observation("a", "first account", "user", "fixture"))
    b = mem.publish(Observation("b", "second account", "user", "fixture"))
    c = mem.publish(Observation("c", "alternate account", "user", "fixture"))
    proposal = {"groups": [{"reason_refs": [a], "operations": [
        {"op": "claim", "alias": "new:c1", "content": "Prefers quiet rooms"},
        {"op": "justification", "target_ref": "new:c1", "polarity": "support",
         "items": [{"ref": a, "start": 0, "end": 5}, {"ref": b}]},
    ]}, {"operations": [
        {"op": "justification", "target_ref": "new:c1", "polarity": "support",
         "items": [{"ref": c}]},
        {"op": "justification", "target_ref": "new:c1", "polarity": "oppose",
         "items": [{"ref": b}], "conditions": {"setting": "office"}},
    ]}]}
    result = mem.dispatch("memory_save", {"changeset": proposal})
    claim = result["changeset"]["aliases"]["new:c1"]
    assert receipt_outcome("memory_save", result).ok
    assert {a, b, c} <= mem.retained
    assert mem.read(claim)["support_status"] == "USABLE"
    assert mem.read(claim)["opposition_status"] == "PENDING"
    mem.advance_turn("Office conditions", conditions={"setting": "office"})
    assert mem.read(claim)["disputed"] is True
    before_replacement = mem.last_known_at
    replacement = mem.publish(
        Observation("a2", "corrected account", "user", "fixture", supersedes=a)
    )
    assert mem.read(a, known_at=before_replacement)["current_ref"] == a
    assert mem.read(a)["current_ref"] == replacement
    assert mem.read(claim, known_at=before_replacement)["justifications"][0]["status"] == "USABLE"
    view = mem.read(claim)
    support_states = [
        group["status"] for group in view["justifications"]
        if group["polarity"] == "support"
    ]
    assert support_states == [
        "UNUSABLE", "USABLE",
    ]
    assert view["support_status"] == "USABLE"
    restored = ContextualMemory.restore(
        mem.checkpoint(), user_id="alice", embed=mem.embed, deletion_ledger=ledger,
    )
    assert restored.read(claim)["support_status"] == "USABLE"
    envelope = TaskEnvelope(
        "alice", "", "lifecycle", frozenset({"delete"}), (b,),
        "delete-1", "delete_only", scope_id=str(ledger.path.parent.resolve()),
    )
    restored.bind_envelope(envelope)
    restored.forget([b], envelope=envelope)
    assert restored.read(claim)["support_status"] == "USABLE"
    assert all(b not in [item["ref"] for item in group["items"]]
               for group in restored.read(claim)["justifications"])


def test_failed_group_rolls_back_alias_and_version_slice_has_no_inherited_support() -> None:
    mem = memory()
    source = mem.publish(Observation("s", "independent observation", "user", "fixture"))
    result = mem.dispatch("memory_save", {"changeset": {"groups": [
        {"operations": [
            {"op": "claim", "alias": "new:lost", "content": "Temporary claim"},
            {"op": "justification", "target_ref": "new:lost", "polarity": "support",
             "items": [{"ref": "missing"}]},
        ]},
        {"operations": [
            {"op": "claim", "alias": "new:good", "content": "Stable claim"},
            {"op": "justification", "target_ref": "new:good", "polarity": "support",
             "items": [{"ref": source}]},
        ]},
        {"operations": [
            {"op": "justification", "target_ref": "new:lost", "polarity": "support",
             "items": [{"ref": source}]},
        ]},
    ]}})
    groups = result["changeset"]["groups"]
    assert [group["status"] for group in groups] == ["ERROR", "APPLIED", "ERROR"]
    assert "new:lost" not in result["changeset"]["aliases"]
    assert len(mem.workspace.cards) == 1
    claim = result["changeset"]["aliases"]["new:good"]
    assert mem.read(claim)["support_status"] == "USABLE"
    assert receipt_outcome("memory_save", result).completion == "partial_failure"
    newer = mem.save(target_ref=claim, content="Different claim")["record"]["ref"]
    assert newer != claim
    assert mem.read(newer)["support_status"] == "UNSUPPORTED"
    assert mem.read(claim)["status"] == "SUPERSEDED"


def test_cycle_rejected_and_condition_unknown_stays_pending() -> None:
    mem = memory()
    assert receipt_outcome(
        "memory_save", mem.dispatch("memory_save", {"changeset": {"groups": []}})
    ).ok
    a = mem.save(content="A")["record"]["ref"]
    b = mem.save(content="B")["record"]["ref"]
    mem.search("A")
    mem.update_state(coverage="SUFFICIENT")
    proposal = {"groups": [
        {"operations": [{"op": "justification", "target_ref": a, "polarity": "support",
                         "items": [{"ref": b}], "conditions": {"setting": "home"}}]},
        {"operations": [{"op": "justification", "target_ref": b, "polarity": "support",
                         "items": [{"ref": a}]}]},
    ]}
    result = mem.dispatch("memory_save", {"changeset": proposal})
    assert mem.state.coverage == "UNKNOWN"
    assert a in result["changeset"]["groups"][0]["affected_refs"]
    assert [group["status"] for group in result["changeset"]["groups"]] == ["APPLIED", "ERROR"]
    assert result["changeset"]["groups"][1]["error"] == "CYCLIC_JUSTIFICATION"
    assert mem.read(a)["support_status"] == "PENDING"
    mem.advance_turn("Office conditions", conditions={"setting": "office"})
    assert mem.read(a)["support_status"] == "UNUSABLE"
    assert len(mem.revisions.groups) == 1


def test_state_change_preserves_old_world_state_and_known_prefix() -> None:
    mem = memory()
    old_source = mem.publish(Observation("before", "Used the old route", "user", "fixture"))
    initial = mem.dispatch("memory_save", {"changeset": {"groups": [{"operations": [
        {"op": "claim", "alias": "new:old", "content": "Uses the old route",
         "valid_from": "2024-01-01"},
        {"op": "justification", "target_ref": "new:old", "polarity": "support",
         "items": [{"ref": old_source}]},
    ]}]}})
    old_ref = initial["changeset"]["aliases"]["new:old"]
    before_change = mem.last_known_at
    new_source = mem.publish(Observation("after", "Now uses the new route", "user", "fixture"))
    changed = mem.dispatch("memory_save", {"changeset": {"groups": [{
        "reason_refs": [new_source], "operations": [
            {"op": "state_change", "old_ref": old_ref, "valid_from": "2024-06-01",
             "content": "Uses the new route", "alias": "new:current"},
            {"op": "justification", "target_ref": "new:current", "polarity": "support",
             "items": [{"ref": new_source}]},
        ],
    }]}})
    outcome = changed["changeset"]["groups"][0]
    assert outcome["status"] == "APPLIED"
    closed_ref = outcome["operations"][0]["closed_ref"]
    current_ref = changed["changeset"]["aliases"]["new:current"]
    assert mem.read(closed_ref, valid_at="2024-03-01")["support_status"] == "USABLE"
    assert mem.read(closed_ref, valid_at="2024-07-01")["applicability"] == "UNUSABLE"
    assert mem.read(current_ref, valid_at="2024-07-01")["support_status"] == "USABLE"
    assert mem.read(current_ref, valid_at="2024-03-01")["applicability"] == "UNUSABLE"
    old_view = mem.read(old_ref, known_at=before_change, valid_at="2024-07-01")
    assert old_view["status"] == "CURRENT"
    assert old_view["support_status"] == "USABLE"
    assert old_view["current_ref"] == old_ref
    with pytest.raises(ValueError, match="REFERENCE_NOT_YET_KNOWN"):
        mem.read(new_source, known_at=before_change)
    historical = mem.search("route", known_at=before_change, valid_at="2024-07-01")
    historical_refs = {item["ref"] for item in historical["materials"]}
    assert old_ref in historical_refs
    assert new_source not in historical_refs and current_ref not in historical_refs
    present = mem.search("route", valid_at="2024-07-01")
    assert current_ref in {item["ref"] for item in present["materials"]}
    restored = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=mem.embed)
    assert restored.read(old_ref, known_at=before_change)["current_ref"] == old_ref
    assert restored.read(current_ref, valid_at="2024-07-01")["support_status"] == "USABLE"


def test_reinterpret_moves_only_selected_support_without_changing_source() -> None:
    mem = memory()
    source = mem.publish(Observation("s", "I was quoting my colleague", "user", "fixture"))
    created = mem.dispatch("memory_save", {"changeset": {"groups": [{"operations": [
        {"op": "claim", "alias": "new:mine", "content": "I prefer paper",
         "subject": "current_user"},
        {"op": "justification", "target_ref": "new:mine", "polarity": "support",
         "items": [{"ref": source, "start": 0, "end": 25}]},
    ]}]}})
    old_ref = created["changeset"]["aliases"]["new:mine"]
    group_id = created["changeset"]["groups"][0]["operations"][1]["group_id"]
    before = mem.last_known_at
    corrected = mem.dispatch("memory_save", {"changeset": {"groups": [{"operations": [
        {"op": "reinterpret", "target_ref": old_ref, "subject": "colleague",
         "content": "Colleague prefers paper", "group_ids": [group_id], "alias": "new:theirs"},
    ]}]}})
    actual = corrected["changeset"]["groups"][0]["operations"][0]
    assert actual["status"] == "REINTERPRETED"
    assert len(actual["explicit_group_transfers"]) == 1
    new_ref = corrected["changeset"]["aliases"]["new:theirs"]
    assert mem.read(new_ref)["subject"] == "colleague"
    assert mem.read(new_ref)["support_status"] == "USABLE"
    assert mem.read(old_ref, known_at=before)["support_status"] == "USABLE"
    assert mem.read(old_ref, known_at=before)["justifications"][0]["withdrawn_at"] == ""
    assert mem.read(old_ref)["support_status"] == "UNUSABLE"
    assert mem.read(source)["content"] == "I was quoting my colleague"


def test_task_override_expires_and_stays_out_of_durable_checkpoint() -> None:
    mem = memory()
    mem.start_task("first", "choose route")
    usual = mem.save(content="Usually use the bus")["record"]["ref"]
    before = mem.last_known_at
    receipt = mem.dispatch("memory_save", {"changeset": {"groups": [{"operations": [
        {"op": "task_override", "target_ref": usual,
         "content": "For this task, use the train"},
    ]}]}})
    assert receipt["changeset"]["groups"][0]["status"] == "APPLIED"
    assert "task_override" not in mem.read(usual, known_at=before)
    assert mem.read(usual)["task_override"]["content"] == "For this task, use the train"
    assert "For this task, use the train" not in json.dumps(mem.checkpoint(include_task=False))
    restored = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=mem.embed)
    assert restored.read(usual)["task_override"]["task_id"] == "first"
    restored.start_task("second", "new task", handoff=mem.handoff())
    assert "task_override" not in restored.read(usual)


def test_state_change_with_unknown_world_boundary_keeps_history_pending() -> None:
    mem = memory()
    old_ref = mem.save(content="Previously used the bus")["record"]["ref"]
    before = mem.last_known_at
    changed = mem.dispatch("memory_save", {"changeset": {"groups": [{"operations": [
        {"op": "state_change", "old_ref": old_ref,
         "content": "Now uses the train", "alias": "new:train"},
    ]}]}})
    operation = changed["changeset"]["groups"][0]["operations"][0]
    assert operation["valid_from"] == ""
    assert operation["event_known_at"]
    old_closed = operation["closed_ref"]
    new_ref = changed["changeset"]["aliases"]["new:train"]
    assert mem.read(old_closed)["applicability"] == "UNUSABLE"
    assert mem.read(new_ref)["applicability"] == "USABLE"
    assert mem.read(old_closed, valid_at="2024-01-01")["applicability"] == "PENDING"
    assert mem.read(new_ref, valid_at="2024-01-01")["applicability"] == "PENDING"
    assert mem.read(old_ref, known_at=before, valid_at="2024-01-01")["applicability"] == "USABLE"
    present_refs = {item["ref"] for item in mem.search("use", limit=8)["materials"]}
    assert new_ref in present_refs and old_closed not in present_refs
