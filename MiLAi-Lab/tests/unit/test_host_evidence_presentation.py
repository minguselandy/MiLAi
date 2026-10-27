"""Same visible metadata, actual Host wiring, and no implicit evidence acquisition."""
import copy
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_frozen_retrieval import native_request
from test_given_retrieval import prepared_given, source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_jsonl, write_json
from milai_lab.runners.functional import frozen, memory_effects, message, prepare
from milai_lab.runners.host_evidence_presentation import (
    INDEX_PREFIX,
    PRESENTATION,
    request_adjacent_metadata,
)


def receipt(*, hidden=False):
    item = {"label": "e0", "kind": "original_source", "ref": {
        "snapshot_id": "actual-return", "collection": "materials", "item_index": 0}}
    if hidden:
        item.update(visibility="revoked", body_delivered=False)
    else:
        item["evidence"] = [{"source": "s0", "role": "user", "content": "PRIVATE BODY",
            "capture_context": "given_retrieval_request", "source_characters": 120,
            "range": [0, 12], "reported_at": None, "captured_at": "2030-01-02T03:04:05Z"}]
    return ToolMessage(name="milai_retrieve", tool_call_id="HIDDEN_PROTOCOL_ID",
        content=json.dumps({"schema": "milai_retrieval_result_v1", "ok": not hidden,
                            "evidence": [item]}))


def test_literal_metadata_keeps_roles_clocks_and_question_without_promoting_body_or_protocol_id():
    messages = [HumanMessage(content="earlier"), receipt(), AIMessage(content="previous reply"),
                HumanMessage(content="Current question?", id="current")]
    originals = copy.deepcopy(messages)
    material = {"source_arrivals": {"new_visible_sources": 2,
                                   "semantics": "Count is not relevance or unread work."}}
    actual, audit = request_adjacent_metadata(messages, memory_effects(messages), material)
    assert messages == originals
    assert actual[:-1] == messages[:-1] and actual[-1].id == "current"
    assert actual[-1].content.startswith("Current question?" + INDEX_PREFIX)
    index = audit["index"]
    assert "PRIVATE BODY" not in json.dumps(index)
    assert "HIDDEN_PROTOCOL_ID" not in json.dumps(index)
    assert index["source_arrivals_as_shown"] == material["source_arrivals"]
    header, = index["visible_retrieval_receipt_metadata"][0]["source_headers_as_returned"]
    assert header["role"] == "user" and header["reported_at"] is None
    assert header["captured_at"] == "2030-01-02T03:04:05Z"
    assert header["capture_context"] == "given_retrieval_request"
    assert header["source_characters"] == 120 and header["range"] == [0, 12]
    assert index["current_request_receipt_fields"]["scope"] == (
        "visible_checkpoint_of_current_public_message")
    # No cached prior index survives a visibility-projected replacement conversation.
    projected = [HumanMessage(content="Current question?"), receipt(hidden=True)]
    after, audit = request_adjacent_metadata(projected, memory_effects(projected), {})
    indexed, = audit["index"]["visible_retrieval_receipt_metadata"]
    assert indexed["visibility"] == "revoked" and indexed["body_delivered"] is False
    assert "source_headers_as_returned" not in indexed
    assert "2030-01-02" not in str(after[0].content)
    assert after[1] == projected[1]


def test_error_receipts_remain_in_history_without_guessed_references_or_cross_tool_metadata():
    errors = [ToolMessage(name="milai_retrieve", tool_call_id="error",
                         content="Tool error: timeout", status="error"),
              ToolMessage(name="milai_retrieve", tool_call_id="failed", content='{"ok":false}'),
              receipt().model_copy(update={"name": "other_tool"})]
    messages = [HumanMessage(content="Question"), *errors]
    result, audit = request_adjacent_metadata(messages, memory_effects(messages), {})
    assert result[1:] == errors
    assert audit["unparsed_tool_message_indices"] == [1]
    assert audit["index"]["visible_retrieval_receipt_metadata"] == []
    assert "source_arrivals_as_shown" not in audit["index"]


def test_delivered_view_metadata_preserves_shared_alias_clocks_without_copying_interpretation():
    view = {"label": "e2", "kind": "query_structure", "revision": 4, "query_time": "latest",
        "interpretation": {"nodes": {"n0": {"text": "UNCERTIFIED INTERPRETATION"}}},
        "source_metadata": {"shared": {"reported_at": None},
                            "by_alias": {"s1": {"role": "user", "captured_at": "2030-01-02"}}},
        "source_metadata_semantics": "Capture clocks are not event times or validity.",
        "ref": {"snapshot_id": "actual-view", "collection": "materials", "item_index": 0}}
    messages = [HumanMessage(content="Current request"), ToolMessage(name="milai_retrieve",
        tool_call_id="view", content=json.dumps({"schema": "milai_retrieval_result_v1",
                                                "ok": True, "evidence": [view]}))]
    _, audit = request_adjacent_metadata(messages, memory_effects(messages), {})
    indexed, = audit["index"]["visible_retrieval_receipt_metadata"]
    assert indexed["source_metadata"] == view["source_metadata"]
    assert indexed["source_metadata_semantics"] == view["source_metadata_semantics"]
    assert indexed["revision"] == 4
    assert "UNCERTIFIED INTERPRETATION" not in json.dumps(indexed)


def presentation_root(tmp_path, enabled):
    original = prepared_given(tmp_path, host_source_arrivals=True)
    if not enabled:
        return original
    settings = copy.deepcopy(frozen(original)["config"])
    settings["host_evidence_presentation"] = PRESENTATION
    config = tmp_path / "presentation.json"
    write_json(config, settings)
    root = tmp_path / "presentation"
    prepare(root, config, source_version="mechanical", run_id=frozen(original)["run_id"])
    return root


@pytest.mark.parametrize("enabled", [False, True])
def test_real_host_hook_indexes_only_delivered_receipt_and_does_not_accumulate_in_public_history(
    tmp_path, monkeypatch, enabled,
):
    root = presentation_root(tmp_path, enabled)
    question = "Find the reported Cedar code."
    indexes = []

    def reply(wire, ordinal):
        users = [m for m in wire["messages"] if m["role"] == "user"]
        assert sum(m["role"] == "system" for m in wire["messages"]) == 1
        if enabled:
            assert users[-1]["content"].count(INDEX_PREFIX) == 1
            body, encoded = users[-1]["content"].split(INDEX_PREFIX)
            assert body == (question if ordinal < 3 else "Keep the same reported code.")
            index = json.loads(encoded)
            indexes.append(index)
            assert "The reported Cedar code is 4312." not in encoded
            if ordinal == 1:
                assert index["source_arrivals_as_shown"]["new_visible_sources"] == 1
                assert index["visible_retrieval_receipt_metadata"] == []
            else:
                packet = json.loads(next(m["content"] for m in wire["messages"]
                    if m["role"] == "tool" and m.get("name") == "milai_retrieve"))
                assert [item["ref"] for item in index["visible_retrieval_receipt_metadata"]] == (
                    [item["ref"] for item in packet["evidence"]])
                assert all(INDEX_PREFIX not in m["content"] for m in users[:-1])
        else:
            assert all(INDEX_PREFIX not in m["content"] for m in users)
        if ordinal == 1:
            return native_request({"query": "Cedar code"})
        return {"role": "assistant", "content": "4312"}

    wires = scripted(monkeypatch, reply, native=True)
    common = {"bank": "bank", "owner": "alice", "session": "host"}
    first = message(root, **common, message_id="first", content=question,
                    incoming_sources=[source()])
    assert first["status"] == "COMPLETED", first.get("error")
    assert next(s for s in first["sources"] if s["event_id"] == first["capture"]["source_ref"])[
        "content"] == question
    later = message(root, **common, message_id="later", content="Keep the same reported code.",
                    previous_host_message="first")
    assert later["status"] == "COMPLETED", later.get("error")
    assert len(wires) == 3
    events = [e for path in root.glob("banks/*/*-trace-*.jsonl") for e in read_jsonl(path)
              if e["event"] == "host_evidence_presentation"]
    assert len(events) == (3 if enabled else 0)
    if enabled:
        assert indexes[-1]["source_arrivals_as_shown"]["new_visible_sources"] == 0
        assert len(indexes[-1]["visible_retrieval_receipt_metadata"]) > 0


def test_arrival_index_allows_direct_answer_without_acquiring_hidden_body(tmp_path, monkeypatch):
    root = presentation_root(tmp_path, True)

    def reply(wire, ordinal):
        assert ordinal == 1
        assert "UNOPENED_BODY" not in json.dumps(wire)
        text = next(m["content"] for m in wire["messages"] if m["role"] == "user")
        assert json.loads(text.split(INDEX_PREFIX)[1])[
            "source_arrivals_as_shown"]["new_visible_sources"] == 1
        return {"role": "assistant", "content": "Acknowledged."}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Acknowledge this update.",
        incoming_sources=[{**source(), "content": "UNOPENED_BODY"}])
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 1
    assert not any(row.get("tool_calls") for row in result["messages"])


def test_unknown_presentation_mode_is_not_silently_accepted(tmp_path):
    root = prepared_given(tmp_path)
    settings = copy.deepcopy(frozen(root)["config"])
    settings["host_evidence_presentation"] = "unknown"
    config = tmp_path / "invalid.json"
    write_json(config, settings)
    with pytest.raises(ValueError, match="DECLARED_MODE"):
        prepare(tmp_path / "invalid", config)
