"""Visible literal witnesses, not Store availability or self-generated answers."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from audit_host_witnesses import audit_witnesses
from milai_lab.methods.intent_retrieval import retrieval_packet

BANK = ["functional", "study", "bank", "alice"]


def event(ref, key, text="The code is 4312."):
    return {"event_id": ref, "owner": "alice", "session": "history", "capture_key": key,
            "role": "user", "origin": "public_user_message", "content": text,
            "source_revision": 1, "observed_at": "2030-01-01T00:00:00Z"}


def material(source, start=0, end=None):
    end = len(source["content"]) if end is None else end
    turn = {"source_ref": source["event_id"], "source_revision": 1, "role": source["role"],
            "origin": source["origin"], "range": [start, end],
            "content": source["content"][start:end], "observed_at": source["observed_at"]}
    return {"kind": "original_source", "id": source["event_id"], "visibility": "visible",
            "body_delivered": True, "text": json.dumps([turn]), "source_ranges": [{
                "source_ref": source["event_id"], "source_revision": 1,
                "start": start, "end": end}]}


def fixture(sources, materials, *, visible=True):
    public = event("public", "target", "What is the code?")
    sources = [public, *sources]
    indices = list(range(len(materials)))
    packet = retrieval_packet("receipt", materials, indices, indices, "policy_handoff", {})
    saved = {"schema": "milai_retrieval_snapshot_v1", "status": "completed",
             "materials": materials, "indices": indices, "reason": "policy_handoff", "usage": {},
             "delivered_indices": [item["ref"]["item_index"] for item in packet["evidence"]]}
    rows = [{"namespace": [*BANK, "v13_1_sources"], "key": e["event_id"], "value": e}
            for e in sources]
    rows.append({"namespace": [*BANK, "v13_5_functional"], "key": "receipt", "value": saved})
    messages = [{"type": "human", "content": "What is the code?"}]
    if visible:
        messages.insert(0, {"type": "tool", "name": "milai_retrieve",
                            "content": json.dumps(packet)})
    capture = {"schema": "frozen_host_message_v1", "status": "CAPTURED_PRE_HOST", "bank": "bank",
        "public_message": {"owner": "alice", "message_id": "target"},
        "ready_state": {"public_source_ref": "public", "memory_store_values": rows,
                        "initial_messages": copy.deepcopy(messages)},
        "initial_baseline_context": messages}
    witness = sources[1]
    case = {"bank": "bank", "request_id": "target", "witnesses": [{
        "identity": ["history", witness["capture_key"], "user"], "content": witness["content"]}]}
    return capture, case


def test_store_or_correct_assistant_answer_without_visible_receipt_is_not_known_witness():
    source = event("a", "a")
    capture, case = fixture([source], [material(source)], visible=False)
    capture["initial_baseline_context"].append({"type": "ai", "content": source["content"]})
    result = audit_witnesses(capture, case)
    assert result["status"] == "WITNESS_REVIEW_REQUIRED"
    assert result["witnesses"][0]["source_present"]
    assert not result["all_declared_raw_slices_visible"]


def test_actual_source_binding_distinguishes_identical_text_and_ignores_unprojected_messages():
    first, other = event("a", "a"), event("b", "b")
    capture, case = fixture([first, other], [material(other)])
    assert not audit_witnesses(capture, case)["all_declared_raw_slices_visible"]
    case["witnesses"][0]["identity"] = ["history", "b", "user"]
    assert audit_witnesses(capture, case)["all_declared_raw_slices_visible"]
    capture["initial_baseline_context"] = [{"type": "human", "content": "After projection"}]
    assert not audit_witnesses(capture, case)["all_declared_raw_slices_visible"]


def test_body_scope_union_and_duplicate_delivery_aliases_follow_actual_packet():
    source = event("a", "a")
    capture, case = fixture([source], [material(source, 0, 8)])
    assert not audit_witnesses(capture, case)["all_declared_raw_slices_visible"]
    case["witnesses"][0]["range"] = [0, 8]
    assert audit_witnesses(capture, case)["all_declared_raw_slices_visible"]
    capture, case = fixture([source], [material(source, 0, 8), material(source, 8)])
    assert audit_witnesses(capture, case)["all_declared_raw_slices_visible"]
    capture, case = fixture([source], [material(source), material(source)])
    assert audit_witnesses(capture, case)["all_declared_raw_slices_visible"]


@pytest.mark.parametrize("fault", [
    "revoked", "not_delivered", "wrong_body", "no_body", "wrong_clock"])
def test_unverified_or_hidden_receipt_never_certifies_a_witness(fault):
    source = event("a", "a")
    capture, case = fixture([source], [material(source)])
    rows = capture["ready_state"]["memory_store_values"]
    packet = json.loads(capture["initial_baseline_context"][0]["content"])
    if fault == "revoked":
        rows.append({"namespace": [*BANK, "v13_5_functional"], "key": "visibility",
                     "value": {"sources": ["a"]}})
    elif fault == "not_delivered":
        rows[-1]["value"]["delivered_indices"] = []
    elif fault == "wrong_body":
        packet["evidence"][0]["evidence"][0]["content"] = "A fabricated replacement"
    elif fault == "wrong_clock":
        # Even a receipt consistent with its stored copy must preserve Source clocks.
        body = rows[-1]["value"]["materials"][0]
        turns = json.loads(body["text"])
        turns[0]["occurred_at"] = "2040-02-03"
        body["text"] = json.dumps(turns)
        packet["evidence"][0]["evidence"][0]["reported_at"] = "2040-02-03"
    else:
        packet["evidence"][0].pop("evidence")
        packet["evidence"][0].update(body_delivered=False, visibility="revoked")
    capture["initial_baseline_context"][0]["content"] = json.dumps(packet)
    result = audit_witnesses(capture, case)
    assert not result["all_declared_raw_slices_visible"]


def test_view_source_locations_are_not_original_body_delivery():
    source = event("a", "a")
    view = {"kind": "query_structure", "id": "v", "visibility": "visible", "body_delivered": True,
        "structure": {"scope": "View", "nodes": {"n0": {"text": source["content"],
            "kind": "reported", "evidence": ["e0"]}}, "rules": {}, "unresolved": []},
        "source_bindings": {"e0": {"source_ref": "a", "source_revision": 1}},
        "revision": 1, "query_time": "", "semantics": "model-derived"}
    capture, case = fixture([source], [view])
    result = audit_witnesses(capture, case)
    assert result["status"] == "WITNESS_REVIEW_REQUIRED"
    assert result["other_materials_requiring_review"][0]["kind"] == "query_structure"


def test_witness_definition_is_bound_to_actual_request_and_literal_source():
    source = event("a", "a")
    capture, case = fixture([source], [material(source)])
    case["request_id"] = "another"
    with pytest.raises(ValueError, match="actual request"):
        audit_witnesses(capture, case)
    case["request_id"] = "target"
    case["witnesses"][0]["content"] = "Different source claim"
    with pytest.raises(ValueError, match="content differs"):
        audit_witnesses(capture, case)
