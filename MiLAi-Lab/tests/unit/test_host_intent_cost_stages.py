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
def test_continuous_host_history_does_not_recount_prior_tool_receipts(tmp_path, new_call):
    def save(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    save("driver.json", {"status": "COMPLETED", "source_version": "test",
        "transport": "json_action", "wall_seconds": 1, "completed": [
            {"history": "stream", "policy": "generative", "request": "second"}]})
    for name in ("budget-before.json", "budget-after.json"):
        save(name, {"generation": {"known_tokens": 0}, "generation_requests": 0})
    save("fixture.json", {"histories": [{"id": "stream", "source_group": "group",
        "continuous": True, "requests": [{"id": "second"}]}]})
    tool = {"type": "tool", "name": "milai_retrieve", "status": "success"}
    save("generative/banks/bank/second-result.json", {
        "bank": "stream", "message_id": "second",
        "messages": [{"type": "human", "id": "first"}, tool,
                     {"type": "ai", "content": "Earlier answer"},
                     {"type": "human", "id": "second"}, *([tool] if new_call else []),
                     {"type": "ai", "content": "Current answer"}]})
    (tmp_path / "generative/banks/bank/second-trace-0.jsonl").write_text("")
    result = summarize([tmp_path], [
        {"history": "stream", "policy": "generative", "request": "second", "grade": "C"}])
    assert result["positions"][0]["tool_attempts"] == int(new_call)
