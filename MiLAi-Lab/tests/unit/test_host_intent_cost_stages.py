"""Controller requests must not be charged to the Host-request stage."""

import json
import sys
from pathlib import Path

import pytest

from milai_lab.methods.laya_memory_policy import GenerativeMemoryPolicy
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from summarize_host_intent_retrieval import generation_stage, summarize


def test_actual_controller_schema_preserves_stage_even_for_truncated_response():
    captured = {}

    def call(purpose, messages, schema):
        assert purpose == "memory_control"
        captured["schema"] = schema
        return {"choice": "handoff"}

    state = MemoryControlState(task={"request": "current record", "query_time": ""})
    action = MemoryAction("handoff", "HANDOFF", "Reader", {})
    assert GenerativeMemoryPolicy(call).choose(state, [action]) == "handoff"
    event = {"request": {"response_format": {"json_schema": captured}},
             "receipt": {"choices": [{"finish_reason": "stop",
                 "message": {"content": json.dumps({"choice": "handoff"})}}]}}
    assert generation_stage(event) == "control_generation"
    event["receipt"]["choices"][0].update(finish_reason="length", message={"content": '{"cho'})
    assert generation_stage(event) == "control_generation"
    event["request"] = {}
    assert generation_stage(event) == "host_incomplete"
    event["receipt"]["choices"][0].update(
        finish_reason="stop", message={"content": json.dumps({"answer": "Supported."})})
    assert generation_stage(event) == "host_completion"


@pytest.mark.parametrize("new_call", [False, True])
@pytest.mark.parametrize("transport", ["json_action", "native"])
def test_continuous_host_history_does_not_recount_prior_tool_receipts(
        tmp_path, new_call, transport):
    def save(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    save("driver.json", {"status": "COMPLETED", "source_version": "test",
        "transport": transport, "wall_seconds": 1, "completed": [
            {"history": "stream", "policy": "generative", "request": "second"}]})
    save("budget-before.json", {"generation": {"known_tokens": 0},
        "embedding": {"known_tokens": 0}, "generation_requests": 0})
    save("budget-after.json", {"generation": {"known_tokens": 13},
        "embedding": {"known_tokens": 0}, "generation_requests": 1})
    save("fixture.json", {"histories": [{"id": "stream", "source_group": "group",
        "continuous": True, "requests": [{"id": "second"}]}]})
    tool = {"type": "tool", "name": "milai_retrieve", "status": "success"}
    attempt = {"type": "ai", "tool_calls": [{"name": "milai_retrieve"}]}
    save("generative/banks/bank/second-result.json", {
        "bank": "stream", "message_id": "second",
        "messages": [{"type": "human", "id": "first"}, tool,
                     {"type": "ai", "content": "Earlier answer"},
                     {"type": "human", "id": "second"},
                     *([attempt, tool] if new_call else []),
                     {"type": "ai", "content": "Current answer"}]})
    content = "Current answer" if transport == "native" else '{"answer":"Current answer"}'
    event = {"event": "vllm_response", "path": "chat/completions", "request": {},
             "receipt": {"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
             "usage": {"total_tokens": 13}, "wall_seconds": .1}
    (tmp_path / "generative/banks/bank/second-trace-0.jsonl").write_text(json.dumps(event) + "\n")
    result = summarize([tmp_path], [
        {"history": "stream", "policy": "generative", "request": "second", "grade": "C"}])
    assert result["positions"][0]["tool_attempts"] == int(new_call)
    assert result["positions"][0]["tool_returns"] == int(new_call)
    assert result["stages"]["host_completion"]["tokens"] == 13
    assert result["known_generation_tokens"] == 13


def test_native_tool_request_and_completion_keep_cost_stage_separate_from_outcome():
    event = {"request": {"tools": [{"type": "function"}]}, "receipt": {"choices": [
        {"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
            {"type": "function", "function": {"name": "milai_retrieve", "arguments": "{}"}}]}}]}}
    assert generation_stage(event) == "host_request"
    choice = event["receipt"]["choices"][0]
    choice["finish_reason"] = "length"
    assert generation_stage(event, "native") == "host_incomplete"
    choice["finish_reason"] = "stop"
    assert generation_stage(event, "native") == "unparsed_host_response"
    choice["message"] = {"content": "An answer attempt."}
    assert generation_stage(event, "native") == "host_completion"
    event["receipt"]["choices"] = []
    assert generation_stage(event, "native") == "unparsed_host_response"
    event["receipt"]["choices"] = [choice]
    event["request"] = {"response_format": {"json_schema": {
        "schema": {"properties": {"nodes": {"type": "array"}}}}}}
    choice["finish_reason"] = "length"
    assert generation_stage(event, "native") == "view_generation"
