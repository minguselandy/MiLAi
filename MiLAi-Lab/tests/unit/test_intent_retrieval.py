"""Real SQLite and native tool messages; scripted policy checks mechanics, not semantics."""
import json
from types import SimpleNamespace

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.laya_memory_policy import LayaMemoryPolicy
from milai_lab.methods.memory_control import FixedMemoryPolicy, MemoryAction, MemoryControlState
from milai_lab.runners.memory_control import memory_policy


def context(service, message="query"):
    ref = service.capture_user("host", message, "Is the threshold 9000?")["source_ref"]
    service.bind_public_turn("host", message, ref, config_version="intent-test", phase="start")
    return {"configurable": {"user_id": "alice", "thread_id": "t", "v13_session": "host",
            "v13_turn_id": message, "v13_config_version": "intent-test"}}


def memory_at(service, **kwargs):
    return IntentRetrievalMemory(service, len, material_limit=10000, read_limit=12,
        evidence_policy="question_pack_v1", source_access="independent_v1",
        source_tokenization="unicode_v1", control_policy=FixedMemoryPolicy(), **kwargs)


def test_native_tool_call_query_only_and_rich_feedback(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("intent-test", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "1", "A travel approval threshold is 1000 before May 1.")
        cfg = context(service)
        inputs = []

        def choose(payload):
            inputs.append(payload)
            return {"choice": ("search" if len(inputs) == 1 else
                               "read_0" if len(inputs) == 2 else "handoff")}

        memory = memory_at(service)
        memory.control_policy = LayaMemoryPolicy(choose)
        assert inputs == [] and "evidence" not in memory.model_material(cfg)
        tool = next(t for t in memory.tools() if t.name == "milai_retrieve")
        request = {"query": "What is the travel approval threshold?",
            "read_goal": {"required_points": ["effective date"], "purpose": "cite the report"},
            "task_context": {"as_of": "2026-04-30", "target_scope": {"project": "A"}}}
        response = tool.invoke({"type": "tool_call", "name": "milai_retrieve",
                                "id": "rich", "args": request}, config=cfg)
        packet = json.loads(response.content)
        assert packet["termination_reason"] == "policy_handoff"
        assert packet["usage"]["control_steps"] == 3
        assert "1000" in json.dumps(packet["evidence"])
        assert "9000" not in json.dumps(packet["evidence"])
        assert inputs[0]["state"]["task"]["retrieval_request"] == request
        assert inputs[1]["state"]["last_result"]["status"] == "searched"
        assert inputs[2]["state"]["visible_evidence"]
        assert memory.control_handed_off is False  # Host may request a remaining gap.
        assert not service.records()

        inputs.clear()
        response = tool.invoke({"type": "tool_call", "name": "milai_retrieve",
                                "id": "simple", "args": {"query": "approval threshold"}}, cfg)
        assert json.loads(response.content)["evidence"]
        assert inputs[0]["state"]["task"]["retrieval_request"] == {"query": "approval threshold"}
        assert inputs[0]["state"]["task"]["query_time"] == ""


def test_delivered_reference_reopens_across_requests_and_checks_visibility(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("intent-test", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        ref = service.capture_user("history", "1", "A approval threshold is 1000.")["source_ref"]
        cfg = context(service)
        memory = memory_at(service)
        first = memory.retrieve(cfg, "first", RetrievalRequest(query="approval threshold"))
        refs = [row["ref"] for row in first["evidence"]]
        assert refs
        cfg2 = context(service, "followup")
        observed = []
        memory.control_policy = LayaMemoryPolicy(lambda payload: (
            observed.append(payload) or {"choice": "handoff"}))
        request = RetrievalRequest.model_validate({"query": "verify the effective date",
            "task_context": {"known_evidence_refs": refs}})
        memory.retrieve(cfg2, "follow", request)
        assert "1000" in json.dumps(observed[0]["state"]["task"]["known_evidence"])
        handle = service.source_fragment_range(ref, 0, len("A approval threshold is 1000."))[
            "fragment_handle"]
        service.forget("history", "forget", fragment_handles=[handle])
        # The original request was itself revoked by the existing exposure propagation.
        with pytest.raises(FunctionalRejection, match="ACTUAL_PUBLIC_TURN_REQUIRED"):
            memory.retrieve(cfg, "first", RetrievalRequest(query="approval threshold"))
        assert "1000" not in json.dumps(memory._known_materials(request))
        with pytest.raises(FunctionalRejection, match="REFERENCE_NOT_DELIVERED"):
            memory._known_materials(RetrievalRequest.model_validate({"query": "anything",
                "task_context": {"known_evidence_refs": [
                    {**refs[0], "snapshot_id": "not-a-delivery"}]}}))


def test_actual_return_budget_and_call_replay(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("intent-test", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "1", "approval threshold " + "x" * 2000)
        cfg = context(service)
        memory = memory_at(service, control_steps=3)
        request = RetrievalRequest.model_validate({"query": "approval threshold",
            "limits": {"max_return_tokens": 1000, "max_control_steps": 2}})
        packet = memory.retrieve(cfg, "small", request)
        assert len(json.dumps(packet, separators=(",", ":"), sort_keys=True)) <= 1000
        assert packet["termination_reason"] == "budget_exhausted"
        allowance = memory.read_allowance(cfg)
        assert memory.retrieve(cfg, "small", request) == packet
        assert memory.read_allowance(cfg) == allowance
        assert memory.retrieve(cfg, "zero", RetrievalRequest.model_validate({"query": "approval",
            "limits": {"max_control_steps": 0}}))["usage"]["control_steps"] == 0


def test_model_instance_shared_across_host_messages_but_calls_charged_separately(monkeypatch):
    import sys

    loaded, charges, admissions = [], [], []

    class Model:
        def __init__(self, *args, **kwargs):
            loaded.append((args, kwargs))
            self.counters = {"forwards": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            return {"choice": "handoff"}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    pool = {}
    for message in range(2):
        policy = memory_policy({"policy": "laya", "checkpoint": "test", "device": "cpu"},
            SimpleNamespace(record_compute=lambda phase, values: charges.append((phase, values))),
            call=lambda *_: {}, admit=lambda m=message: admissions.append(m), record=lambda _: None,
            models=pool)
        policy.choose(MemoryControlState(task={"request": "query"}), [
            MemoryAction("search", "SEARCH", "query"), MemoryAction("handoff", "HANDOFF", "Host")])
    assert len(loaded) == 1 and len(admissions) == 2
    assert sum(row[1].get("loads", 0) for row in charges) == 1
    assert sum(row[1].get("forwards", 0) for row in charges) == 2


def test_normal_host_runner_calls_tool_and_receives_evidence(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted

    from milai_lab.runners.functional import message

    root = prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich",
        memory_view_mode="staged", memory_control={"policy": "fixed", "max_control_steps": 4})

    def reply(wire, _number):
        tools = {t["function"]["name"] for t in wire.get("tools", [])}
        receipts = [m for m in wire["messages"] if m["role"] == "tool"]
        if not receipts:
            assert wire["tool_choice"] == {
                "type": "function", "function": {"name": "milai_retrieve"}}
            assert "milai_retrieve" in tools
            assert "read_evidence" not in tools and "search_memory" not in tools
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "retrieve-1",
                "type": "function", "function": {"name": "milai_retrieve", "arguments":
                    json.dumps({"query": "approval threshold", "read_goal": {
                        "purpose": "quote the original threshold"}})}}]}
        evidence = json.loads(receipts[-1]["content"])
        assert wire["tool_choice"] == "none"
        assert "1000" in json.dumps(evidence["evidence"])
        return {"role": "assistant", "content": "The reported approval threshold was 1000."}

    wires = scripted(monkeypatch, reply, native=True)
    from langchain_core.messages import ToolMessage

    def native_probe(messages):
        return ("none" if any(isinstance(m, ToolMessage) for m in messages) else
                {"type": "function", "function": {"name": "milai_retrieve"}})

    result = message(root, bank="intent", owner="alice", session="host", message_id="query",
        model_tool_choice=native_probe,
        content="What approval threshold did I report?", incoming_sources=[{
            "event_key": "reported-threshold", "session_id": "history", "role": "user",
            "content": "A approval threshold is 1000."}])
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["final_answer"] == "The reported approval threshold was 1000."
    assert len(wires) == 2
    assert result["records"] == []


def test_known_source_ranges_do_not_require_duplicate_read_and_view_sees_goal(tmp_path):
    from milai_lab.methods.memory_control import RulesMemoryPolicy

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("intent-test", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "1", "A approval threshold is 1000.")
        cfg = context(service)
        memory = memory_at(service)
        first = memory.retrieve(cfg, "first", RetrievalRequest(query="approval threshold"))
        refs = [row["ref"] for row in first["evidence"]]
        traces, refreshes = [], []
        memory.control_record = traces.append

        def refresh(_stage, messages, _schema):
            payload = json.loads(messages[-1]["content"])
            refreshes.append(payload)
            return {"scope": "approval", "nodes": [{"id": "n0", "kind": "reported",
                "text": "A threshold is 1000.", "evidence": [payload["sources"][0]["id"]]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        memory.control_policy = RulesMemoryPolicy()
        memory.dependency_read_call = refresh
        request = RetrievalRequest.model_validate({"query": "approval threshold",
            "read_goal": {"purpose": "apply the rule", "required_points": ["project scope"]},
            "task_context": {"known_evidence_refs": refs, "as_of": "2026-05-01"}})
        memory.retrieve(cfg, "known", request)
        assert refreshes[0]["retrieval_request"] == request.project()
        steps = [r for r in traces if r.get("phase") == "decision_output"]
        assert not any(r["selected"].startswith("read_") for r in steps)
        memory.retrieval_interface = "query_only"
        tool = next(t for t in memory.tools() if t.name == "milai_retrieve")
        assert set(tool.tool_call_schema.model_fields) == {"query"}
