"""Keep real structural rejection and bounded feedback while forbidding SHA calls."""
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate
from pydantic import ValidationError as PydanticValidationError
from pydantic import create_model

from milai_lab.contracts import tool_schema_communication as communication


def forbid_fingerprints(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Fingerprint generation is disabled for this path")

    monkeypatch.setattr(communication, "_sha", denied)
    monkeypatch.setattr(communication.hashlib, "sha256", denied)


def test_rejected_enum_keeps_public_constraint_without_hashes(monkeypatch):
    schema = {"type": "object", "properties": {"evidence": {
        "type": "array", "items": {"enum": ["original_source", "saved_history"]}}}}
    with pytest.raises(ValidationError) as caught:
        validate({"evidence": ["PRIVATE_UNSUPPORTED_VALUE"]}, schema)
    forbid_fingerprints(monkeypatch)
    result = communication.jsonschema_feedback(caught.value, schema, fingerprints=False)
    assert result["tool_executed"] is False
    assert result["error"]["keyword"] == "enum"
    assert result["error"]["path"]["segments"] == ["evidence", 0]
    assert result["error"]["expected"] == ["original_source", "saved_history"]
    assert "sha256" not in communication.feedback_text(result)
    assert "PRIVATE_UNSUPPORTED_VALUE" not in communication.feedback_text(result)


def test_large_jsonschema_and_pydantic_errors_stay_bounded_without_hashing(monkeypatch):
    key = "字段" * 100
    instance = "PRIVATE_VALUE"
    schema = {"type": "integer"}
    for _ in range(18):
        instance = {key: instance}
        schema = {"type": "object", "properties": {key: schema}}
    public = {"oneOf": [schema for _ in range(12)]}
    error = next(Draft202012Validator(public).iter_errors(instance))
    model = create_model("Leaf", value=(int, ...))
    body = {"value": "PRIVATE_VALUE"}
    for i in range(18):
        model = create_model(f"Nested{i}", **{key: (model, ...)})
        body = {key: body}
    with pytest.raises(PydanticValidationError) as caught:
        model.model_validate(body)
    forbid_fingerprints(monkeypatch)
    for result in (communication.jsonschema_feedback(error, public, fingerprints=False),
                   communication.pydantic_feedback(caught.value, fingerprints=False)):
        text = communication.feedback_text(result)
        assert len(text.encode()) <= 4096
        assert "sha256" not in text and "PRIVATE_VALUE" not in text
        assert "omitted" in text


def test_normal_retrieval_host_rejects_then_executes_without_fingerprints(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted

    from milai_lab.runners.functional import message

    forbid_fingerprints(monkeypatch)
    root = prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        memory_view_mode="staged", memory_control={"policy": "fixed", "max_control_steps": 4})
    def reply(wire, _number):
        receipts = [m for m in wire["messages"] if m["role"] == "tool"]
        if len(receipts) < 2:
            if receipts:
                feedback = json.loads(receipts[-1]["content"])
                assert feedback["tool_executed"] is False
                assert feedback["error"]["keyword"] == "enum"
                assert "sha256" not in receipts[-1]["content"]
            return {"role": "assistant", "content": "", "tool_calls": [{
                "id": f"read-{len(receipts)}", "type": "function", "function": {
                    "name": "milai_retrieve", "arguments": json.dumps({
                        "query": "approval threshold", "read_goal": {"evidence": [
                            "original_source" if receipts else "preference"]}})}}]}
        evidence = json.loads(receipts[-1]["content"])
        assert "1000" in json.dumps(evidence["evidence"])
        return {"role": "assistant", "content": "The reported threshold was 1000."}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root, bank="test", owner="alice", session="host", message_id="query",
        content="What threshold did I report?", incoming_sources=[{
            "event_key": "threshold", "session_id": "history", "role": "user",
            "content": "The approval threshold is 1000."}])
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 3
    receipts = [m for m in result["messages"] if m.get("type") == "tool"]
    assert [m["status"] for m in receipts] == ["error", "success"]
    assert result["records"] == []
