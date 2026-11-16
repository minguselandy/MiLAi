"""Directed regions and actual SQLite commits, with deterministic model responses."""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator, ValidationError
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.dependency_memory import dependency_region, query_support
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import maintain_event
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    decode_dependency_reads,
    dependency_read_request,
    fixed_history_candidates,
    open_evidence_packs,
    project_packs,
)
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def test_shared_prerequisite_is_context_until_it_is_the_changed_root():
    state = {"units": [{"unit_id": uid} for uid in ["A", "B", "confirm", "other"]],
             "relations": [
                 {"source_unit": "confirm", "target_unit": "A", "relation_type": "modifies"},
                 {"source_unit": "confirm", "target_unit": "B", "relation_type": "modifies"}]}
    result = dependency_region(state, ["A"])
    assert result["affected_units"] == ["A"]
    assert result["read_only_units"] == ["confirm"]
    assert query_support(state, ["A"])[0] == ["A", "confirm"]
    assert query_support(state, ["confirm"])[0] == ["A", "B", "confirm"]
    assert dependency_region(state, ["confirm"])["affected_units"] == ["A", "B", "confirm"]
    retained = dependency_region(state, ["confirm"], preserve=["B"])
    assert retained["affected_units"] == ["A", "confirm"]
    assert retained["read_only_units"] == ["B"]


@pytest.mark.parametrize("use_laya", [False, True])
@pytest.mark.parametrize("wrong_target", [False, True])
@pytest.mark.parametrize("full_features", [False, True])
def test_region_constrains_actual_editor_and_keeps_other_claims(
    tmp_path: Path, wrong_target: bool, full_features: bool, use_laya: bool,
):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("dep", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        seed = EditMemory(service, "M")
        ref = service.capture_user("s0", "first", "A uses Lin. B uses Gao. Both need approval.")[
            "source_ref"]
        service.bind_public_turn("s0", "first", ref, config_version="test", phase="start")
        evidence = seed.prepare([ref], "", selected_records=[])["sources"][0]["evidence_id"]
        receipt = seed.apply("s0", "seed", {
            "action": "create", "units": [
                {"text": "A uses Lin.", "evidence": [evidence]},
                {"text": "B uses Gao.", "evidence": [evidence]},
                {"text": "Approval is needed.", "role": "condition", "evidence": [evidence]}],
            "relations": [{"source": 2, "target": target, "relation_type": "modifies",
                           "evidence": [evidence]} for target in (0, 1)]})
        assert receipt["ok"], receipt
        before = service.read(receipt["id"])["value"]
        features = (EditFeatures(matter_organization=True, semantic_operations=True,
                                bound_references=True, single_record_changes=True,
                                source_metadata=True, temporal_scope=True,
                                proposition_updates=True, dependency_updates=True)
                    if full_features else
                    EditFeatures(dependency_updates=True))
        method = EditMemory(service, "M", interface_version="I2", features=features)
        changed = service.capture_user("s1", "change", "A now uses Wu. Keep B and approval.")[
            "source_ref"]
        service.bind_public_turn("s1", "change", changed, config_version="test", phase="start")
        delivery = method.prepare([changed], "", selected_records=[])
        calls = []

        def call(stage, messages, schema):
            calls.append(stage)
            if stage == "impact":
                assert "Approval" in messages[1]["content"]
                return {"roots": ["u1"], "preserve": []}
            payload = json.loads(messages[1]["content"])
            region = payload["dependency_regions"]["r1"]
            assert region["affected_units"] == ["u1"]
            assert region["read_only_units"] == ["u3"]
            proposal = {"action": "edit", "target": "r1", "edits": [{
                "operation": "replace",
                "target_unit": "u2" if wrong_target else "u1",
                "text": "A uses Wu.", "evidence": ["e1"]}]}
            if full_features:
                proposal["edits"][0]["assertion"] = {"source_evidence": "e1", "kind": "reported"}
                proposal.pop("target")
            envelope = ({"creates": [], "records": {"r1": proposal}} if full_features
                        else {"proposals": [proposal]})
            if wrong_target:
                with pytest.raises(ValidationError):
                    Draft202012Validator(schema).validate(envelope)
            else:
                Draft202012Validator(schema).validate(envelope)
            return envelope

        dispatched = call
        if use_laya:
            from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
            from milai_lab.runners.laya_impact import impact_model_call

            def decisions(request):
                payload = json.loads(request.content)
                return httpx.Response(200, json={"answers": {
                    q: {"choice": "direct_root" if i == 0 else "other"}
                    for i, q in enumerate(payload["questions"])},
                    "usage": {"input_tokens": 100, "output_tokens": 0}})

            dispatched = impact_model_call(call, {"laya_impact": {
                "http_client": httpx.Client(transport=httpx.MockTransport(decisions))}},
                budget=RunBudget(RunLimits(), tmp_path / "budget.json"), root=tmp_path / "typed")

        result = maintain_event(method, delivery, session="s1", request_id="change",
                                date="2031-01-02", recipe="single_pass", model_call=dispatched,
                                selected_record_ids=[receipt["id"]])
        assert calls == (["edit"] if use_laya else ["impact", "edit"])

        assert result["dependency_regions"]["r1"]["affected_units"] == ["u1"]
        after = service.read(receipt["id"])["value"]
        if wrong_target:
            assert result["status"] == "incomplete"
            assert after == before
        else:
            assert result["status"] == "completed", result
            assert after["edit_state"]["units"][0]["text"] == "A uses Wu."
            assert after["edit_state"]["units"][1:] == before["edit_state"]["units"][1:]
            assert after["edit_state"]["relations"] == before["edit_state"]["relations"]
            assert service.read(receipt["id"], before["revision"])["value"] == before
        # Same request uses the durable result, without regenerating the plan.
        again = maintain_event(method, delivery, session="s1", request_id="change",
                               date="2031-01-02", recipe="single_pass", model_call=call,
                               selected_record_ids=[receipt["id"]])
        assert again == result
        assert calls == (["edit"] if use_laya else ["impact", "edit"])


def test_history_selection_delivers_withdrawn_clause_and_actual_cancellation(tmp_path: Path):
    with SqliteStore.from_conn_string(str(tmp_path / "history.sqlite")) as store:
        service = MemoryService(store, ("history", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        memory = FunctionalEditMemory(service, len, interface_version="I2")

        def source(key, text):
            ref = service.capture_user("story", key, text)["source_ref"]
            memory.context("story", key, "dep-test")
            cfg = {"configurable": {"user_id": "alice", "v13_session": "story",
                "v13_turn_id": key, "v13_config_version": "dep-test"}}
            return cfg, [service.source_fragments(ref)[0]["fragment_handle"]]

        cfg, handles = source("seed", "The desk opens at nine, but at ten on renovation day.")
        saved = memory.save_edit(cfg, "save", units=[
            {"text": "The desk opens at nine.", "role": "content", "evidence": handles},
            {"text": "The desk opens at ten.", "role": "content", "evidence": handles},
            {"text": "On renovation day.", "role": "condition", "evidence": handles},
        ], relations=[{"source": 2, "target": 1, "relation_type": "modifies", "evidence": handles},
                      {"source": 1, "target": 0, "relation_type": "overrides",
                       "evidence": handles}])
        assert saved["ok"]
        old = service.read(saved["id"])
        exception = old["value"]["edit_state"]["units"][1]["unit_id"]
        exception_pack = build_evidence_packs(service, "exception", "2031-01-02", [], [old],
            dependency_selections={saved["id"]: {"roots": [exception], "excluded": [],
                                                  "history_revisions": []}})
        cfg, handles = source(
            "cancel", "The renovation was abandoned, so withdraw the ten-o'clock exception.")
        receipt = memory.update_edit(cfg, "cancel", old["candidate_handle"], [
            {"operation": "retract", "target_unit": exception, "evidence": handles}])
        assert receipt["ok"]
        assert open_evidence_packs(service, exception_pack, refresh_current=True)[0][
            "body_delivered"] is False
        current = service.read(saved["id"])
        request = dependency_read_request(service, "Why was the exception withdrawn?",
                                          "2031-01-03", [current])
        # The model selects existing versions, not evaluator-supplied old text.
        selections = decode_dependency_reads(request, {
            "r0": {"roots": [0], "excluded": [], "history_revisions": [1]}})
        packs = build_evidence_packs(service, "Why was the exception withdrawn?", "2031-01-03",
                                     [], [current], dependency_selections=selections)
        assert len(packs) == 2
        opened = open_evidence_packs(service, packs)
        assert any("renovation was abandoned" in turn["content"]
                   for item in opened for turn in item["support_turns"])
        historical = next(item for item in opened
                          if item["version_view"] == "historical_exact_revision")
        assert historical["revision"] == 1
        assert exception in historical["selected_unit_ids"]
        assert "opens at ten" in json.dumps(project_packs(opened, [0, 1]))
        assert service.read(saved["id"])["value"] == current["value"]
        # An explicit historical pack never refreshes into the current version.
        assert open_evidence_packs(service, [historical], refresh_current=True)[0]["revision"] == 1
        run = BenchmarkRun.__new__(BenchmarkRun)
        run.root = tmp_path / "run"
        run.settings = {"evidence_policy": "question_pack_v1", "dependency_reading": True,
                        "context_tokens": 100000, "model": {"max_tokens": 100},
                        "source_access": "independent_v1"}
        run.client = SimpleNamespace(config=SimpleNamespace(max_calls=2))
        run.input_tokens = lambda messages, **_: len(json.dumps(messages))
        calls = []

        def call(key, messages, **kwargs):
            calls.append(key)
            assert json.loads(messages[1]["content"])["question"] == (
                "Why was the exception withdrawn?")
            if key.startswith("dependency-selection/"):
                return json.dumps({"r0": {"roots": [0], "excluded": [], "history_revisions": [1]}})
            assert "renovation was abandoned" in messages[1]["content"]
            return "The renovation was abandoned, so the exception was withdrawn."

        run.call = call
        native = service.search_sources("renovation", include_scope=True)
        native["records"] = [current]
        materials = run._source_first_materials(
            service, "Why was the exception withdrawn?", "2031-01-03", native, [],
            snapshot_id="snapshot.json")
        answer, _ = run._answer_evidence_pack(
            "Why was the exception withdrawn?", "2031-01-03", "answer", materials,
            snapshot_id="snapshot.json",
            material_reader=lambda items: open_evidence_packs(service, items))
        assert "renovation was abandoned" in answer
        assert len(calls) == 2
        assert materials[0]["pre_read_calls"] == 1


def test_fixed_history_pool_equalizes_versions_and_witnesses_without_future_leak(tmp_path: Path):
    with SqliteStore.from_conn_string(str(tmp_path / "fixed.sqlite")) as store:
        service = MemoryService(store, ("fixed", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        memory = FunctionalEditMemory(service, len, interface_version="I2")

        def source(key, text):
            ref = service.capture_user("story", key, text)["source_ref"]
            memory.context("story", key, "fixed-test")
            cfg = {"configurable": {"user_id": "alice", "v13_session": "story",
                   "v13_turn_id": key, "v13_config_version": "fixed-test"}}
            return cfg, [service.source_fragments(ref)[0]["fragment_handle"]]

        cfg, first = source("seed", "The desk opens at nine; a temporary desk opens at noon.")
        saved = memory.save_edit(cfg, "save", units=[
            {"text": "The desk opens at nine.", "role": "content", "evidence": first},
            {"text": "A temporary desk opens at noon.", "role": "content", "evidence": first},
        ], relations=[])
        old = service.read(saved["id"])
        root, exception = [u["unit_id"] for u in old["value"]["edit_state"]["units"]]
        cfg, cancel = source("cancel", "Withdraw the temporary desk because renovation ended.")
        assert memory.update_edit(cfg, "cancel", old["candidate_handle"], [
            {"operation": "retract", "target_unit": exception, "evidence": cancel}])["ok"]
        checkpoint = service.read(saved["id"])
        cfg, later = source("later", "LATER_SECRET: the desk now opens at eight.")
        assert memory.update_edit(cfg, "later", checkpoint["candidate_handle"], [
            {"operation": "replace", "target_unit": root,
             "text": "LATER_SECRET: the desk now opens at eight.", "evidence": later}])["ok"]
        current_before = service.read(saved["id"])
        # Duplicate unit hits do not duplicate versions; the actual checkpoint
        # bounds available history even when the live bank has a later revision.
        hit = {**checkpoint, "retrieval_navigation": {"unit_id": root}}
        pool = fixed_history_candidates(service, [hit, hit])
        assert [row["value"]["revision"] for row in pool] == [2, 1]
        assert all("retrieval_navigation" not in row for row in pool)
        request = dependency_read_request(service, "Why was noon withdrawn?", "2031-01-02", pool)
        history = json.loads(request["messages"][1]["content"])["history"]
        assert history["r0"]["revisions"] == [2, 1]
        assert history["r0"]["current_revision"] == 2
        chosen = decode_dependency_reads(request, {
            "r0": {"roots": [0], "excluded": [], "history_revisions": [1]}})
        flat = build_evidence_packs(service, "Why?", "2031-01-02", [], pool)
        directed = build_evidence_packs(service, "Why?", "2031-01-02", [], pool,
                                        dependency_selections=chosen)
        assert [(p["record_id"], p["revision"]) for p in flat] == [
            (p["record_id"], p["revision"]) for p in directed]
        assert len(flat) == len(directed) == 2
        # Availability is shared before selection. R1 may omit an old version;
        # a fixed candidate pool must not force an unselected history body open.
        current_only = decode_dependency_reads(request, {
            "r0": {"roots": [0], "excluded": [], "history_revisions": []}})
        filtered = build_evidence_packs(service, "Current?", "2031-01-02", [], pool,
                                        dependency_selections=current_only)
        assert [p["revision"] for p in filtered] == [2]
        assert [row["value"]["revision"] for row in pool] == [2, 1]
        for packs in (flat, directed):
            opened = open_evidence_packs(service, packs)
            body = json.dumps(project_packs(opened, [0, 1]))
            assert "temporary desk" in body and "renovation ended" in body
            assert "LATER_SECRET" not in body
        assert service.read(saved["id"]) == current_before
        assert service.forget("story", "forget", fragment_handles=first)["ok"]
        assert fixed_history_candidates(service, [checkpoint]) == []
