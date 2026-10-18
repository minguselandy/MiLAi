"""Real Store/source transitions; scripted policies test the operation boundary only."""
import json
from dataclasses import dataclass

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.memory.functional_state import namespace
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory
from milai_lab.methods.laya_memory_policy import LayaMemoryPolicy, operation_payload
from milai_lab.methods.memory_control import (
    FixedMemoryPolicy,
    MemoryControlState,
    RulesMemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.query_structure import build_query_structure


def service_at(store, root):
    return MemoryService(store, ("dynamic-test", "alice"), "alice", root / "lock",
                         functional_contract="functional_v1")


def interpretation(messages, _schema):
    payload = json.loads(messages[-1]["content"])
    return {"scope": "Approval rules", "nodes": [{"id": "n" + s["id"][1:],
        "text": s["text"], "evidence": [s["id"]], "kind": "reported"}
        for s in payload["sources"]], "rules": [], "remove": [],
        "remove_rules": [], "unresolved": []}


def setup_operations(service, call=interpretation):
    state = MemoryControlState(task={"request": "What is the approval threshold?",
                                     "query_time": "2026-10-18"})

    def pool():
        found = service.search_sources(state.task["request"], limit=8,
                                       tokenization="unicode_v1", include_scope=True)
        return build_evidence_packs(service, state.task["request"], "2026-10-18",
                                    found["source_materials"], [],
                                    source_scope=found["source_scope"])

    return state, EvidenceOperations(service, state, load_pool=pool,
                                     refresh_call=call, fits=lambda items: True)


@dataclass
class Scripted:
    choices: list[str]

    def choose(self, state, actions):
        return self.choices.pop(0)


def test_actual_feedback_and_finite_id_mapping(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "1", "A approval threshold is 1000 until November 1.")
        state, ops = setup_operations(service)
        inputs = []

        def predict(payload):
            inputs.append(payload)
            return {"choice": ["search", "read_0", "handoff"][len(inputs) - 1]}

        trace_path = tmp_path / "trace.jsonl"
        result = run_memory_control(state, LayaMemoryPolicy(predict), ops,
                                    record=Trace(trace_path, "functional_v1"))
        trace = [json.loads(line) for line in trace_path.read_text().splitlines()]
        assert trace[-1]["phase"] == "decision_output"
        assert all(row["event"] == "memory_control_step" for row in trace)
        assert inputs[0]["state"]["pending_candidates"] == []
        assert inputs[1]["state"]["last_result"]["status"] == "searched"
        assert "1000" in json.dumps(inputs[2]["state"]["visible_evidence"])
        assert "gold" not in json.dumps(inputs)
        assert result["reason"] == "policy_handoff"
        assert operation_payload(state, ops.actions(state))["state"] == state.project()
        with pytest.raises(ValueError, match="Unknown memory operation"):
            run_memory_control(state, Scripted(["nonexistent"]), ops)


def test_budget_handoff_keeps_actual_evidence(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "1", "Approval is required above 1000.")
        state, ops = setup_operations(service)
        result = run_memory_control(state, FixedMemoryPolicy(), ops, max_steps=2)
        assert result["reason"] == "budget_exhausted"
        assert "1000" in json.dumps(ops.reader_evidence())
        assert not any(a.id == "read_0" for a in ops.actions(state))


def test_refresh_then_reopen_use_has_no_generation_and_forget_hides_view(tmp_path):
    calls = []

    def call(messages, schema):
        calls.append(messages)
        return interpretation(messages, schema)

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "1", "Approval threshold is 1000.")["source_ref"]
        state, ops = setup_operations(service, call)
        result = run_memory_control(state, RulesMemoryPolicy(), ops)
        assert [t["selected"] for t in result["trace"]] == [
            "search", "read_0", "refresh_view", "handoff"]
        assert len(calls) == 1
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        state, ops = setup_operations(service, call)
        result = run_memory_control(state, RulesMemoryPolicy(), ops)
        assert [t["selected"] for t in result["trace"]] == ["use_view", "handoff"]
        assert len(calls) == 1
        handle = service.source_fragment_range(ref, 0, len("Approval threshold is 1000."))[
            "fragment_handle"]
        service.forget("s", "forget", fragment_handles=[handle])
        assert "1000" not in json.dumps(ops.reader_evidence())
        assert ops.reader_evidence()[0]["visibility"] == "support_unavailable"


def test_new_exception_outside_old_support_reaches_refresh(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "1", "A and B approval threshold is 1000.")
        state, ops = setup_operations(service)
        run_memory_control(state, RulesMemoryPolicy(), ops)
        service.capture_user("s", "2", "From November 1 only A travel threshold becomes 2000.")
        state, ops = setup_operations(service)
        assert state.views[0]["pending_events"]
        result = run_memory_control(state, RulesMemoryPolicy(), ops)
        assert "refresh_view" in [t["selected"] for t in result["trace"]]
        assert "2000" in json.dumps(ops.reader_evidence())


def test_host_reopen_does_not_repeat_control_or_use_query_as_fact(tmp_path):
    traces = []
    config = {"configurable": {"user_id": "alice", "thread_id": "t", "v13_session": "s",
              "v13_turn_id": "q", "v13_config_version": "dynamic-test"}}
    for reopen in (False, True):
        with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
            service = service_at(store, tmp_path)
            if not reopen:
                service.capture_user("s", "1", "A approval threshold is 1000.")
                ref = service.capture_user("s", "q", "Is A threshold 9000?")["source_ref"]
            service.bind_public_turn("s", "q", ref, config_version="dynamic-test",
                                     phase="resume" if reopen else "start")
            memory = FunctionalEditMemory(service, len, material_limit=30000, read_limit=8,
                arm="M", evidence_policy="question_pack_v1", source_access="independent_v1",
                source_tokenization="unicode_v1", control_policy=RulesMemoryPolicy(),
                control_record=traces.append,
                dependency_read_call=lambda _, m, s: interpretation(m, s))
            packet = memory.model_material(config)
            assert memory.control_handed_off
            assert "1000" in json.dumps(packet)
            assert "9000" not in json.dumps(packet["evidence"])
            assert len([t for t in traces if t.get("event") == "memory_control_handoff"]) == 1
            assert memory.read_allowance(config)["reads_remaining"] == 5


def test_unknown_result_ends_without_reexecuting(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        state, ops = setup_operations(service)
        ops.execute = lambda action, state: {"ok": False, "status": "read_outcome_unknown"}
        result = run_memory_control(state, FixedMemoryPolicy(), ops)
        assert result["reason"] == "operation_outcome_unknown"
        assert len(result["trace"]) == 1


def test_context_expansion_disappears_when_other_read_delivers_its_ranges(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "1", "A and B approval threshold is 1000.")
        service.capture_user("s", "2", "From November 1 only A becomes 2000.")
        state, ops = setup_operations(service)
        ops.execute(next(a for a in ops.actions(state) if a.kind == "SEARCH"), state)
        small = min(range(len(ops.materials)), key=lambda i: len(ops.materials[i]["source_ranges"]))
        ops.execute(next(a for a in ops.actions(state) if a.id == f"read_{small}"), state)
        assert any(a.id == f"context_{small}" for a in ops.actions(state))
        other = next(a for a in ops.actions(state) if a.kind == "READ"
                     and not a.parameters.get("expand_context"))
        ops.execute(other, state)
        assert not any(a.kind == "READ" for a in ops.actions(state))
        assert "2000" in json.dumps(state.visible_evidence)


def test_explicit_refresh_keeps_selected_originals_beside_new_assistant_context(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "original", "A becomes 2000 only from May 1.")["source_ref"]
        build_query_structure(service, "Which threshold?", "April 1", [ref],
                              policy="incremental", call=interpretation)
        service.capture_assistant("s", "answer", "A is 2000.")
        inputs = []

        def call(messages, schema):
            inputs.append(json.loads(messages[-1]["content"]))
            return interpretation(messages, schema)

        build_query_structure(service, "Which threshold before May?", "April 2", [ref],
                              policy="incremental", call=call, force_refresh=True)
        assert any(s["role"] == "user" and "only from May 1" in s["text"]
                   for s in inputs[0]["sources"])
        assert any(s["role"] == "assistant" for s in inputs[0]["sources"])


@pytest.mark.parametrize("forget", [False, True])
def test_history_directory_opens_actual_saved_version_and_respects_revocation(tmp_path, forget):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        memory = FunctionalEditMemory(service, len, interface_version="I2")

        def context(key, text):
            ref = service.capture_user("s", key, text)["source_ref"]
            memory.context("s", key, "history-test")
            cfg = {"configurable": {"user_id": "alice", "v13_session": "s",
                "v13_turn_id": key, "v13_config_version": "history-test"}}
            return cfg, [service.source_fragments(ref)[0]["fragment_handle"]]

        cfg, old_handles = context("first", "The start date is February 1.")
        saved = memory.save_edit(cfg, "save", units=[{
            "text": "The start date is February 1.", "role": "content", "evidence": old_handles}])
        assert saved["ok"]
        current = service.read(saved["id"])
        unit = current["value"]["edit_state"]["units"][0]["unit_id"]
        cfg, handles = context("correction", "Correct the start date to February 3.")
        corrected = memory.update_edit(cfg, "correct", current["candidate_handle"], [{
            "operation": "replace", "target_unit": unit,
            "text": "The start date is February 3.", "evidence": handles}])
        assert corrected["ok"]
        state = MemoryControlState(task={"request": "What date was originally stored?",
            "query_time": "2031-04-01", "read_goal": {"evidence": ["saved_history"]}})
        ops = EvidenceOperations(service, state,
            load_pool=lambda: build_evidence_packs(service, state.task["request"], "2031-04-01",
                                                   [], [service.read(saved["id"])]),
            refresh_call=interpretation, fits=lambda items: True)
        ops.execute(next(a for a in ops.actions(state) if a.kind == "SEARCH"), state)
        directory = next(a for a in ops.actions(state) if a.parameters.get("history_directory"))
        result = ops.execute(directory, state)
        assert result["revisions"] == [1, 2]
        assert state.visible_evidence == []  # A directory is not a stored body.
        if forget:
            service.forget("s", "forget", fragment_handles=old_handles)
        read = next(a for a in ops.actions(state) if a.id == "read_1")
        result = ops.execute(read, state)
        if forget:
            assert not result["ok"] and not state.visible_evidence
        else:
            historical = state.visible_evidence[0]
            assert historical["revision"] == 1
            assert historical["version_view"] == "historical_exact_revision"
            assert "February 1" in str(historical["units"])
            assert "February 3" not in str(historical["units"])


def test_controller_source_observation_is_exposed_but_not_automatically_sent_to_reader(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "fact", "The parcel is sealed.")["source_ref"]
        query = service.capture_user("s", "q", "May it ship?")["source_ref"]
        service.bind_public_turn("s", "q", query, config_version="observation-test", phase="start")
        cfg = {"configurable": {"user_id": "alice", "v13_session": "s", "v13_turn_id": "q",
                                "v13_config_version": "observation-test"}}
        memory = FunctionalEditMemory(service, len, material_limit=10000, read_limit=8,
            evidence_policy="question_pack_v1", control_policy=Scripted(["handoff"]))
        packet = memory.model_material(cfg)
        assert packet["evidence"] == []
        exposure = store.get(namespace(service), "exposure:" + query).value
        assert exposure["source_refs"] == [ref]
        assert exposure["meaning"] == "material_exposure_not_semantic_support"
