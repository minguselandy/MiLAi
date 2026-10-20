"""Real Store/View/ref paths; scripted choices verify wiring, not model quality."""
import json

import pytest
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import context, memory_at

from milai_lab.memory.functional_state import body_text
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.laya_memory_policy import GenerativeMemoryPolicy, operation_payload
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.query_structure import build_query_structure


def build_view(service, source):
    def generate(_messages, _schema):
        return {"scope": "Archive access", "nodes": [
            {"id": "n0", "text": "Card required", "kind": "reported", "evidence": ["e0"]},
            {"id": "n1", "text": "Evening access requires a reservation",
             "kind": "reported", "evidence": ["e0"]},
            {"id": "n2", "text": "Access permitted", "kind": "inferred", "evidence": ["e0"]}],
            "rules": [{"id": "g0", "target": "n2", "all": ["n0"],
                       "any": [["n1"]], "evidence": ["e0"]}],
            "remove": [], "remove_rules": [],
            "unresolved": ["Whether the visitor has a reservation is unknown."]}

    return build_query_structure(service, "Archive access?", "", [source],
                                 policy="incremental", call=generate, force_refresh=True)[0]


@pytest.mark.parametrize("projection", ["full", "shared"])
def test_view_semantics_reach_controller_wire_and_ref_opens_original(tmp_path, projection):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("intent-view", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        original = "A card is required. After 18:00, reserve a place before visiting."
        source = service.capture_user("history", "1", original)["source_ref"]
        view = build_view(service, source)
        wires = []
        phase = "use"

        def choose(_stage, messages, _schema):
            wire = json.loads(messages[-1]["content"])
            wires.append(wire)
            state = (expand_observation_state(wire["state"])
                     if projection == "shared" else wire["state"])
            assert state["views"][0]["interpretation"] == view["structure"]
            assert "model_interpretation" in state["views"][0]["interpretation_semantics"]
            if state["visible_evidence"]:
                return {"choice": "handoff"}
            if phase == "use":
                return {"choice": "use_view"}
            known = state["task"]["known_evidence"][0]
            assert known["revision"] == 1
            assert known["source_bindings"] == {"e0": "support_not_opened"}
            assert known["source_locations"]["e0"] == view["source_bindings"]["e0"]
            choices = wire["questions"]["next"]["criteria"]
            direct = next(key for key, text in choices.items()
                          if '"observed_source":' in text and source in text)
            return {"choice": direct}

        memory = memory_at(service)
        memory.control_policy = GenerativeMemoryPolicy(choose, projection)
        tool = memory.tools()[0]
        first = json.loads(tool.invoke({"type": "tool_call", "name": "milai_retrieve",
            "id": "view", "args": {"query": "Explain archive access."}},
            config=context(service)).content)
        assert len(first["evidence"]) == 1
        delivered = first["evidence"][0]
        assert delivered["kind"] == "query_structure"
        assert original not in json.dumps(delivered)
        assert delivered["source_bindings"] == {"e0": "support_not_opened"}
        assert delivered["source_locations"] == view["source_bindings"]

        # The saved receipt is revision 1 even after the persistent cache advances.
        view = build_view(service, source)
        assert view["revision"] == 2
        phase = "read"
        second = json.loads(tool.invoke({"type": "tool_call", "name": "milai_retrieve",
            "id": "original", "args": {"query": "Quote the evening condition exactly.",
                "task_context": {"known_evidence_refs": [delivered["ref"]]}}},
            config=context(service, "followup")).content)
        assert [item["kind"] for item in second["evidence"]] == ["original_source"]
        assert second["evidence"][0]["evidence"][0]["content"] == original
        assert len(wires) == 4  # USE/HANDOFF then direct READ/HANDOFF, no SEARCH.
        assert not service.records()


def test_known_view_binding_remains_readable_after_cache_eviction_and_not_after_forget(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("intent-view", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        text = "Evening visits require a reservation."
        source = service.capture_user("history", "1", text)["source_ref"]
        known = build_view(service, source)
        store.delete((*service.namespace, "query_structure_v1"), "current")
        state = MemoryControlState(task={"request": "Quote the condition.", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=lambda *_: {},
                                 fits=lambda _: True, known_materials=[known])
        action = next(a for a in ops.actions(state) if "observed_source" in a.parameters)
        assert action.parameters["observed_source"]["source_ref"] == source
        ops.execute(action, state)
        assert state.visible_evidence[0]["evidence"][0]["content"] == text
        assert not any("observed_source" in a.parameters for a in ops.actions(state))

        # Revocation removes both the body and its executable READ opportunity.
        handle = service.source_fragment_range(source, 0, len(text))["fragment_handle"]
        service.forget("history", "forget", fragment_handles=[handle])
        assert not any("observed_source" in a.parameters for a in ops.actions(state))
        assert text not in json.dumps(state.visible_evidence)


def test_unavailable_view_body_never_enters_observation(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("intent-view", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        source = service.capture_user("history", "1", "Card required.")["source_ref"]
        build_view(service, source)
        handle = service.source_fragment_range(source, 0, len("Card required."))["fragment_handle"]
        service.forget("history", "forget", fragment_handles=[handle])
        state = MemoryControlState(task={"request": "Archive access?", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=lambda *_: {},
                                 fits=lambda _: True)
        wire = operation_payload(state, ops.actions(state), "shared")
        assert "Evening access" not in json.dumps(wire)
        assert state.views[0]["visibility"] == "support_unavailable"
        assert not any(a.kind == "USE_VIEW" or "observed_source" in a.parameters
                       for a in ops.actions(state))


def test_json_host_continues_with_its_actual_view_ref(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted, tool

    from milai_lab.runners.functional import message

    root = prepared(tmp_path, memory_method="milai_edit_m_v1", business_tools=[],
        evidence_policy="question_pack_v1", memory_view_mode="staged", retrieval_tool="rich",
        additional_reads=8, memory_control={"policy": "generative", "max_control_steps": 8,
                                          "state_projection": "shared"})
    original = "A card is required. After 18:00, reserve a place before visiting."
    packets, controller_inputs = [], []
    host_step = 0
    followup = False

    def reply(wire, _ordinal):
        nonlocal host_step
        schema = wire.get("response_format", {}).get("json_schema", {}).get("schema", {})
        properties = schema.get("properties", {})
        if "choice" in properties:
            payload = json.loads(wire["messages"][-1]["content"])
            state = expand_observation_state(payload["state"])
            controller_inputs.append(state)
            if state["visible_evidence"]:
                return {"choice": "handoff"}
            if not followup:
                return {"choice": "refresh_view"}
            assert state["views"][0]["interpretation"]["unresolved"] == [
                "Visitor reservation unknown."]
            assert state["task"]["known_evidence"][0]["source_locations"]
            return {"choice": next(key for key, value in
                payload["questions"]["next"]["criteria"].items() if '"observed_source":' in value)}
        if "nodes" in properties:
            payload = json.loads(wire["messages"][-1]["content"])
            source = next(s for s in payload["sources"] if s["text"] == original)
            return {"scope": "Archive access", "nodes": [{"id": "n0", "kind": "reported",
                "text": "Evening access requires a reservation.", "evidence": [source["id"]]}],
                "rules": [], "remove": [], "remove_rules": [],
                "unresolved": ["Visitor reservation unknown."]}
        host_step += 1
        if host_step == 1:
            if followup:
                assert packets[0] in [json.loads(m["content"]) for m in wire["messages"]
                                     if m["role"] == "tool"]
                return tool("milai_retrieve", query="Quote the evening condition.",
                    task_context={"known_evidence_refs": [packets[0]["evidence"][0]["ref"]]})
            return tool("milai_retrieve", query="Explain the archive access condition.")
        packet = json.loads(next(m["content"] for m in reversed(wire["messages"])
                                 if m["role"] == "tool"))
        packets.append(packet)
        if followup:
            assert packet["evidence"][0]["evidence"][0]["content"] == original
            return {"answer": original}
        assert packet["evidence"][0]["kind"] == "query_structure"
        return {"answer": "Evening access requires a reservation; yours is unknown."}

    wires = scripted(monkeypatch, reply)
    first = message(root, bank="stream", owner="alice", session="host", message_id="first",
        content="Explain the archive access condition.", incoming_sources=[{
            "event_key": "condition", "session_id": "history",
            "role": "user", "content": original}])
    assert first["status"] == "COMPLETED", first.get("error")
    followup, host_step = True, 0
    second = message(root, bank="stream", owner="alice", session="host", message_id="followup",
                     content="Now quote the original evening condition.",
                     previous_host_message="first")
    assert second["status"] == "COMPLETED", second.get("error")
    assert second["final_answer"] == original
    assert len(packets) == 2 and len(controller_inputs) == 4
    assert len(wires) == 9  # Four Host, four controller, one View generation.
    assert first["records"] == second["records"] == []

    # Earlier Host text remains subject to the existing source revocation semantics.
    freeze = json.loads((root / "input-freeze.json").read_text())
    bank_db = next((root / "banks").glob("*/memory.sqlite"))
    with SqliteStore.from_conn_string(str(bank_db)) as store:
        service = MemoryService(store, ("functional", freeze["run_id"], "stream", "alice"),
                                "alice", bank_db.parent / "memory.lock",
                                functional_contract="functional_v1")
        source = next(s for s in service.sources() if body_text(s) == original)
        handle = service.source_fragment_range(source["event_id"], 0, len(original))[
            "fragment_handle"]
        service.forget("history", "forget", fragment_handles=[handle])
    stopped = message(root, bank="stream", owner="alice", session="host", message_id="later",
                      content="Quote it again.", previous_host_message="followup")
    assert stopped["status"] == "VISIBILITY_REVOKED"
    assert stopped["messages"] == [] and len(wires) == 9
