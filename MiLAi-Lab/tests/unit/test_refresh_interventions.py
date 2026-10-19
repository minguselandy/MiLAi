import importlib.util
import json
from pathlib import Path

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.query_structure import build_query_structure, cached_structure


def module():
    spec = importlib.util.spec_from_file_location("refresh_interventions", Path(__file__).parents[2]
        / "tools/run_memory_refresh_interventions.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def interpretation(messages, schema):
    value = json.loads(messages[-1]["content"])
    return {"scope": "Sample dispatch", "nodes": [
        {"id": "n" + s["id"][1:], "text": s["text"], "evidence": [s["id"]],
         "kind": "reported"} for s in value["sources"]],
        "rules": [], "remove": [], "remove_rules": [], "unresolved": []}


def actual_before(tmp_path):
    database = tmp_path / "base.sqlite"
    with SqliteStore.from_conn_string(str(database)) as store:
        service = MemoryService(store, ("intervention", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        old = service.capture_user("s", "old", "Samples may use air transport.")["source_ref"]
        prior, _ = build_query_structure(service, "Which transport?", "2032-07-02", [old],
            policy="incremental", call=interpretation)
        update = service.capture_user("s", "update",
            "Samples containing batteries now require ground transport.")["source_ref"]
        sources = service.sources()
        future = service.capture_user("s", "future", "FUTURE_NOT_AVAILABLE.")["source_ref"]
    return {"family": "example", "step": "change", "namespace": ["intervention", "alice"],
            "owner": "alice", "actual_before": {"task": {"request": "Which transport?",
            "query_time": "2032-07-02"}}, "actual_prior_view": prior,
            "before_sources": sources, "old_binding_refs": [old],
            "all_available_refs": [old, update], "source_cut": "actual before future arrival",
            "base_database": str(database)}, future


def test_all_input_branches_match_sources_and_scope_restriction_cannot_see_future(
    tmp_path, monkeypatch,
):
    runner = module()
    before, future = actual_before(tmp_path)
    source_method = MemoryService.source

    def source(self, ref):
        assert ref != future
        return source_method(self, ref)

    def no_inventory(self):
        raise AssertionError("The branch must use its explicit source cut")

    monkeypatch.setattr(MemoryService, "source", source)
    monkeypatch.setattr(MemoryService, "sources", no_inventory)
    inputs, results = {}, {}
    for arm in runner.ARMS:
        def call(messages, schema, arm=arm):
            inputs[arm] = json.loads(messages[-1]["content"])
            return interpretation(messages, schema)

        results[arm] = runner.execute_branch(before, arm, tmp_path / arm, call=call,
                                             token_count=len, material_limit=30000)
    texts = {arm: {(s["role"], s["text"]) for s in value["sources"]}
             for arm, value in inputs.items()}
    assert texts["rebuild_all_available"] == texts["incremental_all_available"]
    assert len(texts["incremental_old_bindings_only"]) == 1
    assert inputs["rebuild_all_available"]["previous"] == {}
    assert (inputs["incremental_all_available"]["previous"]
            == before["actual_prior_view"]["structure"])
    assert all("FUTURE_NOT_AVAILABLE" not in json.dumps(value) for value in inputs.values())
    assert all(r["generator_status"] == "completed" for r in results.values())
    with SqliteStore.from_conn_string(before["base_database"]) as store:
        service = MemoryService(store, tuple(before["namespace"]), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        assert cached_structure(service) == before["actual_prior_view"]


def test_rejection_keeps_prior_without_supplying_it_as_new_reader_evidence(tmp_path):
    runner = module()
    before, _ = actual_before(tmp_path)
    calls = []

    def invalid(messages, schema):
        calls.append(messages)
        response = interpretation(messages, schema)
        response["rules"] = [{"id": "g0", "target": "n999", "all": [], "any": [[]],
                              "evidence": [response["nodes"][0]["evidence"][0]]}]
        return response

    result = runner.execute_branch(before, "incremental_all_available", tmp_path / "rejected",
                                   call=invalid, token_count=len, material_limit=30000)
    assert len(calls) == 1 and result["generator_status"] == "rejected"
    assert result["actual_cached_after"] == before["actual_prior_view"]
    assert result["reader_packet"]["evidence"] == []
    assert result["reader_attempted"] is False
