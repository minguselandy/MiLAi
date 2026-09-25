from __future__ import annotations

import hashlib
import json
from typing import Any

from milai_lab.methods.contextual_user_memory import ContextualMemory, Observation
from milai_lab.runners.contextual_delivery import DeliveryLedger


def source(start: int, end: int, ref: str = "user/source:a") -> dict[str, Any]:
    return {
        "ref": ref, "kind": "source", "content": "abcdefghij"[start:end],
        "page": {"start": start, "end": end, "total_chars": 10,
                 "content_sha256": hashlib.sha256(b"abcdefghij").hexdigest()},
        "status": "CURRENT",
    }


def test_delta_uses_exact_ranges_and_keeps_new_restrictions() -> None:
    ledger = DeliveryLedger("turn-1")
    first = {"materials": [source(0, 4), source(6, 8)]}
    message = {"role": "tool", "content": json.dumps(first)}
    ledger.record(message, first)
    current = source(2, 10)
    current["status"] = "SUPERSEDED"
    current["current_ref"] = "user/source:b"
    current["associated_materials"] = [{"restriction": "applies only at home"}]
    rendered, omitted = ledger.deliver(current, [message])
    assert rendered["delivered_spans"] == [
        {"start": 4, "end": 6, "content": "ef"},
        {"start": 8, "end": 10, "content": "ij"},
    ]
    assert omitted == 4
    assert rendered["status"] == "SUPERSEDED"
    assert rendered["associated_materials"] == current["associated_materials"]
    assert ledger.deliver(source(0, 4, "user/source:b"), [message])[1] == 0


def test_compaction_and_new_host_require_redelivery() -> None:
    first = source(0, 10)
    message = {"role": "tool", "content": json.dumps(first)}
    ledger = DeliveryLedger("turn-1")
    ledger.record(message, first)
    assert ledger.deliver(first, [message])[1] == 10
    assert DeliveryLedger("turn-2").deliver(first, [message])[1] == 0
    message["content"] = "compressed summary only"
    assert ledger.deliver(first, [message])[1] == 0
    ledger.record(message, first)
    assert ledger.deliver(first, [])[1] == 0


def test_actual_relation_and_condition_changes_keep_fresh_status_with_old_body() -> None:
    memory = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, state_policy="off", profile="support", material_mode="linked",
    )
    memory.start_task("one", "At home now?", task_conditions={"setting": "home"})
    source_ref = memory.publish(Observation("a", "I meet clients", "user", "fixture"))
    created = memory.save(changeset={"groups": [{"operations": [
        {"op": "claim", "alias": "new:c", "content": "Meets clients at home"},
        {"op": "justification", "target_ref": "new:c", "polarity": "support",
         "items": [{"ref": source_ref}], "conditions": {"setting": "home"}},
    ]}]})["changeset"]
    group_id = created["groups"][0]["operations"][1]["group_id"]
    claim = created["aliases"]["new:c"]
    initial = memory.read(source_ref, include_sources=False)
    assert initial["associated_materials"][0]["support_status"] == "USABLE"
    ledger = DeliveryLedger("same-transcript")
    message = {"role": "tool", "content": json.dumps(initial)}
    ledger.record(message, initial)

    memory.read(claim, condition_evidence=[{
        "key": "setting", "value": "office", "basis": "inference",
        "reason": "A later instruction suggests an office meeting.",
    }])
    changed = memory.read(source_ref, include_sources=False)
    rendered, omitted = ledger.deliver(changed, [message])
    assert omitted > 0 and "content" not in rendered
    assert rendered["associated_materials"][0]["support_status"] == "PENDING"
    assert rendered["associated_materials"][0]["justifications"][0]["scope_status"] == "PENDING"

    memory.save(changeset={"groups": [{"operations": [
        {"op": "retract_justification", "group_id": group_id},
    ]}]})
    withdrawn = memory.read(source_ref, include_sources=False)
    rendered, _ = ledger.deliver(withdrawn, [message])
    assert rendered["associated_materials"][0]["support_status"] == "UNUSABLE"

    replacement = memory.publish(Observation(
        "b", "Correction: I no longer meet clients", "user", "fixture",
        supersedes=source_ref,
    ))
    corrected = memory.read(source_ref, include_sources=False)
    rendered, _ = ledger.deliver(corrected, [message])
    assert rendered["status"] == "SUPERSEDED"
    assert rendered["current_ref"] == replacement
    assert replacement in {item["ref"] for item in rendered["associated_materials"]}
