"""Internal View ablation uses actual Store/source paths without deleting caller knowledge."""
import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore
from test_given_retrieval import no_http, prepared_given, source
from test_host_intent_view import build_view
from test_intent_retrieval import context, memory_at
from test_memory_control import service_at, setup_operations

from milai_lab.harness.artifact_io import read_json
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory
from milai_lab.methods.laya_memory_policy import LayaMemoryPolicy, payload_actions
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, RulesMemoryPolicy
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import frozen, message


def seeded_views(service):
    text = "Original archive report: a card is required."
    ref = service.capture_user("history", "1", text)["source_ref"]
    writer = FunctionalEditMemory(service, len, interface_version="I2")
    writer.context("history", "1", "seed")
    cfg = {"configurable": {"user_id": "alice", "v13_session": "history",
            "v13_turn_id": "1", "v13_config_version": "seed"}}
    handle = service.source_fragments(ref)[0]["fragment_handle"]
    saved = writer.save_edit(cfg, "save", units=[{"text": "SEMANTIC_VIEW_ONLY_SENTINEL",
        "role": "content", "evidence": [handle]}])
    assert saved["ok"]
    view = build_view(service, ref)
    return ref, text, saved["id"], view


@pytest.mark.parametrize("capacity", [1, 4])
def test_disabling_internal_views_skips_stored_cache_and_semantic_search_but_keeps_sources(
    tmp_path, monkeypatch, capacity,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        _, text, record_id, view = seeded_views(service)
        records = copy.deepcopy(service.records())
        monkeypatch.setattr("milai_lab.methods.evidence_control.cached_structures", no_http)
        monkeypatch.setattr(service, "search", no_http)
        seen = []

        def choose(payload):
            seen.append(payload)
            state = expand_observation_state(payload["state"])
            actions = payload_actions(payload)
            assert not state["views"]
            assert {a.kind for a in actions} <= {"SEARCH", "READ", "HANDOFF"}
            assert "SEMANTIC_VIEW_ONLY_SENTINEL" not in json.dumps(payload)
            assert "Evening access requires a reservation" not in json.dumps(payload)
            kind = "HANDOFF" if state["visible_evidence"] else (
                "READ" if state["pending_candidates"] else "SEARCH")
            return {"choice": next(a.id for a in actions if a.kind == kind)}

        memory = memory_at(service, control_internal_views=False,
            control_view_capacity=capacity, dependency_read_call=no_http)
        memory.control_policy = LayaMemoryPolicy(choose, "shared_actions")
        result = memory.retrieve(context(service), "request",
                                 RetrievalRequest(query="archive card"))
        assert result["ok"] and seen
        assert all(item["kind"] == "original_source" for item in result["evidence"])
        assert text in json.dumps(result["evidence"])
        assert service.records() == records and service.read(record_id)["ok"]
        assert store.get((*service.namespace, "query_structure_v1"), "current").value == view


@pytest.mark.parametrize("dynamic_search", [False, True])
def test_executor_filters_all_internal_derived_candidates_and_cannot_directly_execute_view(
    tmp_path, dynamic_search,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        _, _, record, view = seeded_views(service)
        native = service.search_sources("archive", limit=8, tokenization="unicode_v1")
        pool = build_evidence_packs(service, "archive", "", native["source_materials"],
                                    [service.read(record)])
        assert any(item["kind"] == "semantic_view" for item in pool)
        pool.extend([{"kind": "query_structure", "id": view["id"]},
                     {"kind": "stored_revision", "record_id": record, "revision": 1}])
        state = MemoryControlState(task={"request": "archive", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: pool,
            search_pool=(lambda query, limit: pool) if dynamic_search else None,
            refresh_call=no_http, fits=lambda _: True, internal_views=False)
        ops.execute(next(a for a in ops.actions(state) if a.kind == "SEARCH"), state)
        assert ops.materials and all(item["kind"] == "original_source" for item in ops.materials)
        assert not any(a.parameters.get("history_directory") for a in ops.actions(state))
        for kind in ("USE_VIEW", "REFRESH_VIEW"):
            with pytest.raises(ValueError, match="Non-executable"):
                ops.execute(MemoryAction("unoffered", kind, "unprovided View"), state)


def test_checkpoint_mode_is_explicit_and_enabled_default_keeps_legacy_configuration(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "1", "Archive card required.")
        _, normal = setup_operations(service)
        assert set(normal.checkpoint()["configuration"]) == {
            "view_capacity", "view_policy", "search_batch_sizes", "max_searches",
            "delivery_selection", "source_observation_tokens"}
        state = MemoryControlState(task={"request": "archive", "query_time": ""})
        args = {"load_pool": lambda: [], "refresh_call": no_http, "fits": lambda _: True}
        ops = EvidenceOperations(service, state, internal_views=False, **args)
        saved = ops.checkpoint()
        assert saved["configuration"]["internal_views"] is False
        restored = EvidenceOperations(service, copy.deepcopy(state), checkpoint=saved,
                                       internal_views=False, **args)
        assert [asdict(a) for a in restored.actions(state)] == [
            asdict(a) for a in ops.actions(state)]
        with pytest.raises(ValueError, match="CONFIGURATION_CHANGED"):
            EvidenceOperations(service, copy.deepcopy(state), checkpoint=saved, **args)


def test_caller_provided_view_ref_is_preserved_and_not_confused_with_internal_cache_access(
    tmp_path, monkeypatch,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("history", "1", "Archive visits need a card.")["source_ref"]
        build_view(service, ref)
        full = memory_at(service)
        full.control_policy = LayaMemoryPolicy(lambda p: {"choice":
            "handoff" if p["state"]["visible_evidence"] else "use_view"})
        first_context = context(service, "first")
        first = full.retrieve(first_context, "first", RetrievalRequest(query="archive"))
        supplied = [item["ref"] for item in first["evidence"]]
        assert supplied and first["evidence"][0]["kind"] == "query_structure"
        monkeypatch.setattr("milai_lab.methods.evidence_control.cached_structures", no_http)
        seen = []
        disabled = memory_at(service, control_internal_views=False, dependency_read_call=no_http)
        disabled.control_policy = LayaMemoryPolicy(
            lambda p: seen.append(p) or {"choice": "handoff"})
        # A cached earlier receipt is not a new control opportunity and must not be rewritten.
        assert disabled.retrieve(first_context, "first", RetrievalRequest(query="archive")) == first
        assert not seen
        request = RetrievalRequest.model_validate({"query": "archive",
            "task_context": {"known_evidence_refs": supplied}})
        result = disabled.retrieve(context(service, "second"), "second", request)
        assert result["ok"] and result["usage"]["known_reference_reads"] == 1
        assert seen[0]["state"]["task"]["retrieval_request"] == request.project()
        assert not seen[0]["state"]["views"]
        assert seen[0]["state"]["task"]["known_evidence"][0]["kind"] == "query_structure"


def test_classic_controller_read_path_also_avoids_derived_record_and_dependency_reads(
    tmp_path, monkeypatch,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        _, text, _, _ = seeded_views(service)
        cfg = context(service)
        monkeypatch.setattr("milai_lab.methods.evidence_control.cached_structures", no_http)
        monkeypatch.setattr(service, "search", no_http)
        monkeypatch.setattr(service, "records", no_http)
        memory = FunctionalEditMemory(service, len, material_limit=10000, read_limit=8,
            evidence_policy="question_pack_v1", source_access="independent_v1",
            source_tokenization="unicode_v1", control_policy=RulesMemoryPolicy(),
            control_internal_views=False, dependency_reading=True, dependency_read_call=no_http)
        packet = memory.model_material(cfg)
        assert text in json.dumps(packet["evidence"])
        assert all(item["kind"] == "original_source" for item in packet["evidence"])


def test_host_config_wires_native_policy_and_post_step_replay_without_view_generation(
    tmp_path, monkeypatch,
):
    root = prepared_given(tmp_path, policy={"policy": "laya", "checkpoint": "scripted",
        "state_projection": "shared_actions", "device": "cpu", "max_control_steps": 4,
        "delivery_selection": True, "internal_views": False, "source_observation_tokens": 2000})
    seen = []

    class Model:
        def __init__(self, *args, **kwargs):
            self.counters = {"forwards": 0, "input_tokens": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            self.counters["input_tokens"] += 1  # Synthetic test counter,not real model tokens.
            state = expand_observation_state(payload["state"])
            actions = payload_actions(payload)
            seen.append(state)
            assert not state["views"]
            assert {a.kind for a in actions} <= {"SEARCH", "READ", "HANDOFF"}
            kind = "HANDOFF" if state["visible_evidence"] else (
                "READ" if state["pending_candidates"] else "SEARCH")
            return {"choice": next(a.id for a in actions if a.kind == kind)}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    captures = tmp_path / "captures"
    request = {"query": "Cedar code", "limits": {"max_control_steps": 4}}
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported code", incoming_sources=[source()],
        given_retrieval_request=request, retrieval_snapshots=captures,
        retrieval_step_snapshots=True)
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["retrieval_result"]["evidence"][0]["kind"] == "original_source"
    assert not result["records"] and len(seen) == 3
    ledger = read_json(Path(frozen(root)["config"]["budget_path"]))
    assert ledger["generation_requests"] == 0
    assert ledger["compute"]["dynamic_memory_laya"]["forwards"] == 3
    step = next(p.parent for p in captures.glob("*/steps/step-0001/call.json"))
    saved_config = read_json(step / "control.json")["operations"]["configuration"]
    assert saved_config["internal_views"] is False
    replay = replay_call(step, tmp_path / "replay", {"policy": "fixed_context", "reads": 1},
                         source_version="mechanical")
    assert replay["status"] == "COMPLETED", replay.get("error")
    assert replay["frozen_initial_observation_and_actions_equal"]
    assert read_json(tmp_path / "replay/replay.json")["prefix_operations_reexecuted"] == 0
    assert all(item["kind"] == "original_source" for item in replay["retrieval_result"]["evidence"])


def test_normal_host_history_reuses_its_actual_original_receipt_and_never_creates_views(
    tmp_path, monkeypatch,
):
    from test_frozen_retrieval import native_request
    from test_v13_5_functional_integration import scripted

    root = prepared_given(tmp_path, policy={"policy": "laya", "checkpoint": "scripted",
        "state_projection": "shared_actions", "device": "cpu", "max_control_steps": 4,
        "internal_views": False, "source_observation_tokens": 2000})
    known = []
    loaded = []

    class Model:
        def __init__(self, *args, **kwargs):
            loaded.append(args)
            self.counters = {"forwards": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            state = expand_observation_state(payload["state"])
            actions = payload_actions(payload)
            assert not state["views"]
            assert not any(a.kind in {"USE_VIEW", "REFRESH_VIEW"} for a in actions)
            if state["task"]["known_evidence"] or state["visible_evidence"]:
                return {"choice": "handoff"}
            kind = "READ" if state["pending_candidates"] else "SEARCH"
            return {"choice": next(a.id for a in actions if a.kind == kind)}

    def host(wire, number):
        assert "response_format" not in wire  # No query-structure generation request.
        if number in (1, 3):
            return native_request({"query": "Cedar code", "task_context": {
                "known_evidence_refs": copy.deepcopy(known)}}, call_id=f"call-{number}")
        receipts = [json.loads(m["content"]) for m in wire["messages"] if m["role"] == "tool"]
        if number == 2:
            assert all(i["kind"] == "original_source" for i in receipts[-1]["evidence"])
            known.extend(i["ref"] for i in receipts[-1]["evidence"])
        else:
            assert receipts[-1]["usage"]["known_reference_reads"] == len(known) == 1
            assert not receipts[-1]["evidence"]
            assert "4312" in json.dumps(receipts[:-1])
        return {"role": "assistant", "content": "The recorded Cedar code is 4312."}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    wires = scripted(monkeypatch, host, native=True)
    pool = {}
    for index in range(2):
        result = message(root, bank="bank", owner="alice", session="host",
            message_id=f"q{index}", content="What is the recorded Cedar code?",
            incoming_sources=[source()] if index == 0 else [], control_models=pool,
            previous_host_message="q0" if index else None)
        assert result["status"] == "COMPLETED", result.get("error")
        assert result["final_answer"] == "The recorded Cedar code is 4312."
        assert not result["records"]
    assert len(wires) == 4 and len(loaded) == 1
    ledger = read_json(Path(frozen(root)["config"]["budget_path"]))
    assert ledger["generation_requests"] == 4  # Host costs are retained.
    assert ledger["compute"]["dynamic_memory_laya"]["forwards"] == 4
