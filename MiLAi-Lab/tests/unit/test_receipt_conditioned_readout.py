"""A constructed known condition contains exactly the actually referenced receipt items."""

import copy
import json

import pytest

from milai_lab.runners.given_host_readout import (
    given_packet_request,
    receipt_conditioned_packet_request,
)


def fixture():
    ref = {"snapshot_id": "actual-return", "collection": "materials", "item_index": 1}
    known = {"label": "e1", "ref": ref, "kind": "original_source",
             "evidence": [{"content": "Previously returned partial material", "range": [3, 39]}]}
    receipt = {"packet": {"evidence": [
        {"label": "e0", "ref": {**ref, "item_index": 0},
         "evidence": [{"content": "UNREFERENCED_SECRET_ANSWER"}]}, known]},
        "offline_gold": "HIDDEN_LABEL"}
    request = {"query": "question", "task_context": {"known_evidence_refs": [ref]}}
    settings = {"host": {"base_url": "http://localhost:7860/v1", "model": "test"},
                "capacity": {"enable_thinking": True}, "system_prompt": "Answer with evidence"}
    return request, receipt, known, settings


def test_only_referenced_actual_item_and_current_packet_enter_explicit_context():
    request, receipt, known, settings = fixture()
    original = copy.deepcopy(receipt)
    packet = {"ok": True, "evidence": [{"content": "New material"}]}
    wire = receipt_conditioned_packet_request(
        {"content": "question", "gold": "HIDDEN_PUBLIC_LABEL"}, request, packet, settings,
        [receipt])
    payload = json.loads(wire["messages"][1]["content"])
    assert payload["known_evidence"] == [known]
    assert payload["memory"] == packet
    assert payload["retrieval_request"] == request
    assert all(marker not in json.dumps(wire) for marker in (
        "UNREFERENCED_SECRET_ANSWER", "HIDDEN_LABEL", "HIDDEN_PUBLIC_LABEL"))
    assert [m["role"] for m in wire["messages"]] == ["system", "user"]
    assert receipt == original
    with pytest.raises(ValueError, match="CANNOT_RECONSTRUCT_PRIOR_HOST_KNOWLEDGE"):
        given_packet_request({"content": "question"}, request, packet, settings)


def test_missing_or_conflicting_reference_is_not_substituted():
    request, receipt, _, settings = fixture()
    with pytest.raises(ValueError, match="MISSING_REFERENCED"):
        receipt_conditioned_packet_request({"content": "question"}, request, {}, settings, [])
    changed = copy.deepcopy(receipt)
    changed["packet"]["evidence"][1]["evidence"][0]["content"] = "Different version"
    with pytest.raises(ValueError, match="CONFLICTING_RECEIPT"):
        receipt_conditioned_packet_request(
            {"content": "question"}, request, {}, settings, [receipt, changed])


def test_empty_known_baseline_uses_same_prompt_without_consuming_parent_material():
    request, receipt, _, settings = fixture()
    request["task_context"]["known_evidence_refs"] = []
    wire = receipt_conditioned_packet_request(
        {"content": "question"}, request, {}, settings, [receipt])
    payload = json.loads(wire["messages"][1]["content"])
    assert payload["known_evidence"] == []
    assert "UNREFERENCED_SECRET_ANSWER" not in json.dumps(wire)
