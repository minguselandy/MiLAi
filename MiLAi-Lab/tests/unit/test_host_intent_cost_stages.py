"""Controller requests must not be charged to the Host-request stage."""

import json
import sys
from pathlib import Path

from milai_lab.methods.laya_memory_policy import GenerativeMemoryPolicy
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from summarize_host_intent_retrieval import generation_stage


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
