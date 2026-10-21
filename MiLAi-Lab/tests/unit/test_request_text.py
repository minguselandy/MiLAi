"""Equal information, shared training/live input and real tool execution boundaries."""
import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from langgraph.store.sqlite import SqliteStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_intent_retrieval import context, memory_at

from audit_request_text import check_projection, recover_request_fields
from milai_lab.memory.request_text import project_request_text
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.laya_memory_policy import (
    GenerativeMemoryPolicy,
    LayaMemoryPolicy,
    operation_payload,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from retrieval_mixture import project_mixed_row


def test_prose_retains_extensions_types_empty_values_order_and_literals():
    request = {"query": '时点 "A"\nFor "x", the value is explicitly null.\u2028a\u2029b\u0085c',
               "read_goal": {"purpose": "", "required_points": ["x", "x", "y"],
                             "extensions": [{"a.b": None, "a": {"b": []}}, {}, True, 0, 0.5]},
               "task_context": {"as_of": None, "target_scope": {"project": "B"},
                                "known_evidence_refs": [
                                    {"snapshot_id": "s", "collection": "materials",
                                     "item_index": 2}]},
               "limits": {"max_return_tokens": 512, "max_control_steps": 0}}
    task = {"request": request["query"], "query_time": "", "read_goal": None,
            "retrieval_request": request, "mode": "retrieve", "known_evidence": ["actual material"]}
    row = {"state": {"task": task}, "gold": {"unchanged": True}, "metadata": {"private": "gold"}}
    before = copy.deepcopy(row)
    projected = project_request_text(row)
    prose = projected["state"]["task"]["request_text"]
    assert recover_request_fields(prose) == {
        key: value for key, value in task.items() if key not in {"mode", "known_evidence"}}
    assert 'For "max_control_steps", the value is the number 0.' in prose
    assert 'For "as_of", the value is explicitly null.' in prose
    assert projected["state"]["task"]["known_evidence"] == ["actual material"]
    assert "private" not in prose
    assert project_request_text(projected) == projected
    assert row == before


def test_live_export_mixture_and_generative_use_identical_text_with_feedback():
    state = MemoryControlState(
        task={"retrieval_request": {"query": "Which date?", "read_goal": "Cite original"}},
        new_events=[{"source_ref": "a", "content": "May 1"}],
        last_result={"ok": True, "status": "searched"}, budget={"remaining_control_steps": 3})
    actions = [MemoryAction("read", "READ", "candidate", {"index": 0}),
               MemoryAction("done", "HANDOFF", "Reader")]
    event = {"before": state.project(), "actions": [asdict(a) for a in actions]}
    row = decision_example(event, {"task": "memory_operation", "family": "one"})
    row["gold"] = {"next": {"probabilities": {"read": 1.0}}}
    training = project_mixed_row(row, "shared_request_text")
    check_projection(row, training)
    observed = []
    policy = LayaMemoryPolicy(lambda p: observed.append(p) or {"choice": "read"},
                              "shared_request_text")
    assert policy.choose(state, actions) == "read"
    assert observed[0] == {key: training[key] for key in ("state", "questions")}
    exported = decision_example(event, row["metadata"], projection="shared_request_text")
    assert observed[0] == {key: exported[key] for key in ("state", "questions")}
    calls = []
    generative = GenerativeMemoryPolicy(
        lambda phase, messages, schema: calls.append(messages) or {"choice": "read"},
        "shared_request_text")
    assert generative.choose(state, actions) == "read"
    assert json.loads(calls[0][1]["content"]) == observed[0]
    changed = copy.deepcopy(state)
    changed.last_result = {"ok": False, "status": "read_failed"}
    assert operation_payload(changed, actions, "shared_request_text") != observed[0]
    instruction = {"state": {"task": state.task, "candidate": {"text": "May 1"}},
                   "questions": {"applicability": {}}, "gold": {},
                   "metadata": {"task": "instruction_applicability"}}
    projected = project_mixed_row(instruction, "shared_request_text")
    check_projection(instruction, projected)
    assert "retrieval_request" not in projected["state"]["task"]
    assert project_mixed_row(instruction, "shared") == instruction


@pytest.mark.parametrize("projection", ["shared_request_text", "shared_actions_request_text"])
def test_text_policy_keeps_actual_tool_request_limits_delivery_and_references(tmp_path, projection):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("text-arm", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "1", "A approval threshold is 1000 before May 1.")
        cfg = context(service)
        memory = memory_at(service)
        first = memory.retrieve(cfg, "first", RetrievalRequest(query="approval threshold"))
        refs = [item["ref"] for item in first["evidence"]]
        assert refs
        observed = []
        memory.control_policy = LayaMemoryPolicy(
            lambda payload: observed.append(payload) or {"choice": "handoff"},
            projection)
        cfg = context(service, "second")
        request = RetrievalRequest.model_validate({
            "query": "verify effective date", "read_goal": {"required_points": ["date"]},
            "task_context": {"known_evidence_refs": refs, "as_of": "2026-04-30"},
            "limits": {"max_return_tokens": 512, "max_control_steps": 1}})
        response = memory.retrieve(cfg, "second", request)
        task = observed[0]["state"]["task"]
        recovered = recover_request_fields(task["request_text"])
        assert recovered["retrieval_request"] == request.project()
        assert "1000" in json.dumps(task["known_evidence"])
        assert response["usage"]["control_steps"] == 1
        assert observed[0]["state"]["budget"]["max_return_tokens"] == 512
        assert len(json.dumps(response, ensure_ascii=False, separators=(",", ":"))) <= 512
