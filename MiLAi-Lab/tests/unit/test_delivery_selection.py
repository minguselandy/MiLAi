"""Real Store/packet/reference tests; scripted choices do not measure policy quality."""
import json

import pytest
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import context

from milai_lab.memory.functional_state import FunctionalRejection, canonical, namespace
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.retrieval_supervision import original_witness_preferences


class Choices:
    def __init__(self, choices):
        self.choices = iter(choices)
        self.states = []
        self.actions = []

    def choose(self, state, actions):
        self.states.append(state.project())
        self.actions.append(actions)
        choice = next(self.choices)
        return choice(state, actions) if callable(choice) else choice


def retrieve_setup(tmp_path, store, choices, *, size=1600, reads=8):
    service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                            functional_contract="functional_v1")
    sources = [service.capture_user(f"source-{i}", "1", text)["source_ref"]
               for i, text in enumerate([
                   "Record A requires review. | " + "a " * 250,
                   "Record B has an exception. | " + "b " * 250])]
    traces, generations = [], []

    def generate(_stage, messages, _schema):
        payload = json.loads(messages[-1]["content"])
        generations.append(payload)
        return {"scope": "Recorded requirements", "nodes": [
            {"id": "n" + source["id"][1:], "kind": "reported",
             "text": source["text"].split(" | ")[0], "evidence": [source["id"]]}
            for source in payload["sources"]], "rules": [], "remove": [],
            "remove_rules": [], "unresolved": []}

    policy = Choices(choices)
    memory = IntentRetrievalMemory(service, len, material_limit=size, read_limit=reads,
        evidence_policy="question_pack_v1", source_access="independent_v1",
        source_tokenization="unicode_v1", control_policy=policy, control_steps=8,
        control_delivery_selection=True, control_record=traces.append,
        dependency_read_call=generate)
    return service, memory, policy, traces, generations, sources


def test_rejected_append_can_be_selected_without_rereading_or_resetting_read_quota(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, policy, traces, _, _ = retrieve_setup(
            tmp_path, store, ["search_0_8", "read_0", "read_1", "handoff_select_1"], reads=3)
        cfg = context(service)
        packet = memory.retrieve(cfg, "select", RetrievalRequest(query="record"))
        assert packet["usage"]["read_operations"] == 2
        assert packet["usage"]["control_steps"] == 4
        assert packet["usage"]["material_budget_rejections"] == 1
        assert memory.read_allowance(cfg)["reads_remaining"] == 0
        assert all(a.kind == "HANDOFF" for a in policy.actions[-1])
        assert len(policy.states[-1]["visible_evidence"]) == 1
        assert len(policy.states[-1]["observed_evidence"]) == 1
        assert [m["selected"] for m in policy.states[-1]["observed_materials"]] == [True, False]
        assert len(canonical(packet)) <= 1600
        assert packet["evidence"][0]["label"] == "e1"
        ref = packet["evidence"][0]["ref"]
        assert ref["item_index"] == 0  # Delivered position, not the old pool index.
        saved = store.get(namespace(service), ref["snapshot_id"]).value
        assert saved["indices"] == [1] and saved["delivered_indices"] == [0]
        assert len(saved["materials"]) == 1
        reopened = memory._known_materials(RetrievalRequest.model_validate({
            "query": "same original", "task_context": {"known_evidence_refs": [ref]}}))
        assert json.loads(reopened[0]["text"])[0]["content"] == (
            packet["evidence"][0]["evidence"][0]["content"])
        with pytest.raises(FunctionalRejection, match="REFERENCE_NOT_DELIVERED"):
            memory._known_materials(RetrievalRequest.model_validate({
                "query": "unselected original", "task_context": {"known_evidence_refs": [
                    {**ref, "item_index": 1}]}}))
        selected = [e for e in traces if e.get("phase") == "operation_result"
                    and e["selected"] == "handoff_select_1"]
        assert selected[0]["result"]["status"] == "delivery_selected"
        before = [e for e in traces if e.get("phase") == "decision_input"][-1]
        row = decision_example(before, {"event_id": "delivery/3", "actual_bindings": {
            k: before[k] for k in ("candidate_materials", "opened_materials",
                                  "known_materials", "observed_materials")}})
        witness = before["observed_materials"][1]["source_ranges"][0]["source_ref"]
        preferred, status = original_witness_preferences(row, proofs=[{witness}],
            sources={s["event_id"]: s for s in service.sources()},
            return_key=ref["snapshot_id"], token_count=len)
        assert preferred == ["handoff_select_1"]
        assert status == "reviewed_observed_originals_deliverable"


def test_observation_only_reads_feed_refresh_without_entering_host_packet(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, policy, _, generated, sources = retrieve_setup(tmp_path, store, [
            "search_0_8", "read_0_observe", "read_1_observe", "refresh_view", "handoff"])
        packet = memory.retrieve(context(service), "view", RetrievalRequest(query="record"))
        before_refresh = policy.states[3]
        assert not before_refresh["visible_evidence"]
        assert len(before_refresh["observed_evidence"]) == 2
        assert not any(a.id.startswith("read_") for a in policy.actions[3])
        refresh = next(a for a in policy.actions[3] if a.id == "refresh_view")
        assert set(refresh.parameters["source_refs"]) == set(sources)
        assert len(generated) == 1 and len(generated[0]["sources"]) == 2
        assert [item["kind"] for item in packet["evidence"]] == ["query_structure"]
        assert "a a a a" not in canonical(packet) and "b b b b" not in canonical(packet)
        assert packet["usage"]["read_operations"] == 2
        assert packet["usage"]["material_budget_rejections"] == 0
        assert len(canonical(packet)) <= 1600


def test_generated_view_can_replace_full_original_packet_only_by_explicit_handoff(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        def compact(state, actions):
            view = next(m for m in state.observed_materials if m["kind"] == "query_structure")
            assert not view["selected"]
            assert state.last_result["status"] == "material_budget_exhausted"
            assert all(item["kind"] == "original_source" for item in state.visible_evidence)
            return next(a.id for a in actions
                        if a.parameters.get("delivery_indices") == [view["item_index"]])

        service, memory, policy, traces, generated, sources = retrieve_setup(tmp_path, store, [
            "search_0_8", "read_0", "read_1", "refresh_view", compact], size=2200)
        packet = memory.retrieve(context(service), "compact", RetrievalRequest(query="record"))
        assert len(policy.states[3]["visible_evidence"]) == 2
        assert [m["kind"] for m in packet["evidence"]] == ["query_structure"]
        assert packet["usage"]["read_operations"] == 2 and len(generated) == 1
        assert packet["usage"]["material_budget_rejections"] == 1
        assert packet["usage"]["control_steps"] == 5
        assert len(canonical(packet)) <= 2200
        before = [e for e in traces if e.get("phase") == "decision_input"][-1]
        row = decision_example(before, {"event_id": "delivery/4", "actual_bindings": {
            k: before[k] for k in ("candidate_materials", "opened_materials",
                                  "known_materials", "observed_materials")}})
        preferred, _ = original_witness_preferences(row, proofs=[set(sources)],
            sources={s["event_id"]: s for s in service.sources()},
            return_key=packet["evidence"][0]["ref"]["snapshot_id"], token_count=len)
        assert "handoff" in preferred and "handoff_select_-1" not in preferred


def original_pool(service, refs):
    return service.read_source_materials([{"kind": "original_source", "id": f"item-{i}",
        "session_id": service.source(ref)["session"], "turn_range": [0, 1],
        "source_ranges": [{"source_ref": ref, "source_revision": 1, "start": 0,
                           "end": len(service.source(ref)["content"])}]}
        for i, ref in enumerate(refs)])


def test_refresh_keeps_older_acquired_view_as_a_distinct_delivery_choice(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.memory_control import MemoryControlState
    from milai_lab.methods.query_structure import cached_structure

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, _, _, _, _, refs = retrieve_setup(tmp_path, store, [])
        state = MemoryControlState(task={"request": "record", "query_time": ""})
        generations = []

        def generate(messages, _schema):
            payload = json.loads(messages[-1]["content"])
            generations.append(payload)
            return {"scope": f"Generation {len(generations)}", "nodes": [
                {"id": "n" + s["id"][1:], "text": s["text"].split(" | ")[0],
                 "kind": "reported", "evidence": [s["id"]]} for s in payload["sources"]],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        ops = EvidenceOperations(service, state, load_pool=lambda: original_pool(service, refs),
            refresh_call=generate, fits=lambda _: True, delivery_selection=True)
        for name in ("search", "read_0", "refresh_view", "read_1", "refresh_view"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        views = {i: item for i, item in ops.observed.items() if item["kind"] == "query_structure"}
        assert {item["revision"] for item in views.values()} == {1, 2}
        old = next(i for i, item in views.items() if item["revision"] == 1)
        assert old not in ops.opened and cached_structure(service)["revision"] == 2
        choice = next(a for a in ops.actions(state)
                      if a.parameters.get("delivery_indices") == [old])
        ops.execute(choice, state)
        assert ops.reader_evidence()[0]["revision"] == 1
        assert cached_structure(service)["revision"] == 2


def test_revocation_removes_controller_only_body_before_further_decisions(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.memory_control import MemoryControlState

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        body = "PRIVATE_CONTROLLER_ONLY"
        ref = service.capture_user("source", "1", body)["source_ref"]
        state = MemoryControlState(task={"request": "record", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: original_pool(service, [ref]),
            refresh_call=lambda *_: {}, fits=lambda _: True, delivery_selection=True)
        for name in ("search", "read_0_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        assert not state.visible_evidence and body in canonical(state.project())
        handle = service.source_fragment_range(ref, 0, len(body))["fragment_handle"]
        service.forget("source", "forget", fragment_handles=[handle])
        ops.actions(state)
        assert body not in canonical(state.project())


def test_use_view_can_explicitly_replace_selected_original_without_generation(tmp_path):
    from milai_lab.methods.query_structure import build_query_structure

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, policy, _, generated, refs = retrieve_setup(tmp_path, store, [
            "search_0_8", "read_0", "use_view_only", "handoff"])
        build_query_structure(service, "record", "", refs, policy="incremental",
            call=lambda messages, schema: memory.dependency_read_call(
                "query_structure", messages, schema))
        packet = memory.retrieve(context(service), "reuse", RetrievalRequest(query="record"))
        assert len(generated) == 1  # Only the earlier construction, no new generation.
        assert policy.states[2]["visible_evidence"][0]["kind"] == "original_source"
        assert policy.states[3]["visible_evidence"][0]["kind"] == "query_structure"
        assert policy.states[3]["observed_evidence"][0]["kind"] == "original_source"
        assert [m["kind"] for m in packet["evidence"]] == ["query_structure"]
        assert packet["usage"]["read_operations"] == 1


def test_normal_json_host_receives_view_without_controller_only_original(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted, tool

    from milai_lab.runners.functional import message

    root = prepared(tmp_path, memory_method="milai_edit_m_v1", business_tools=[],
        evidence_policy="question_pack_v1", memory_view_mode="staged", retrieval_tool="rich",
        additional_reads=8, memory_control={"policy": "generative", "max_control_steps": 8,
                                          "delivery_selection": True})
    choices = iter(["search_0_8", "read_0_observe", "refresh_view", "handoff"])
    control_inputs = []
    source_text = "The threshold is 1000. " + "PRIVATE_RAW_DETAIL " * 100
    host_calls = []

    def reply(wire, _number):
        properties = wire.get("response_format", {}).get("json_schema", {}).get(
            "schema", {}).get("properties", {})
        if "choice" in properties:
            payload = json.loads(wire["messages"][-1]["content"])
            control_inputs.append(payload)
            return {"choice": next(choices)}
        if "nodes" in properties:
            payload = json.loads(wire["messages"][-1]["content"])
            assert payload["sources"][0]["text"] == source_text
            return {"scope": "Threshold", "nodes": [{"id": "n0", "kind": "reported",
                "text": "The threshold is 1000.", "evidence": [payload["sources"][0]["id"]]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}
        host_calls.append(wire)
        assert "PRIVATE_RAW_DETAIL" not in json.dumps(wire["messages"])
        if len(host_calls) == 1:
            return tool("milai_retrieve", query="What threshold was reported?")
        packet = json.loads(next(m["content"] for m in wire["messages"] if m["role"] == "tool"))
        assert [item["kind"] for item in packet["evidence"]] == ["query_structure"]
        assert packet["evidence"][0]["ref"]["item_index"] == 0
        return {"answer": "The threshold is 1000."}

    wires = scripted(monkeypatch, reply)
    result = message(root, bank="delivery", owner="alice", session="host", message_id="q",
        content="What threshold was reported?", incoming_sources=[{
            "session_id": "history", "event_key": "report", "role": "user",
            "content": source_text}])
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["final_answer"] == "The threshold is 1000."
    assert not control_inputs[2]["state"]["visible_evidence"]
    assert "PRIVATE_RAW_DETAIL" in json.dumps(control_inputs[2]["state"]["observed_evidence"])
    assert len(wires) == 7  # Four control, one Writer, two Host requests.
