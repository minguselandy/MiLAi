"""Model-visible locality preserves the full binding and explicit support boundary."""
import copy
import json

import pytest

from milai_lab.methods.writer_locality import local_writer_view


def test_partial_view_omits_unrelated_body_but_retains_shared_read_only_support():
    packet = {"records": [{"id": "r1", "representation": "conditioned_v1",
        "matter": "A, B and unrelated facts", "scope": {}, "clauses": [
            {"id": "u1", "text": "A uses Lin", "support": ["h1"], "conditions": [
                {"id": "u3", "text": "Approval required", "support": ["h3"],
                 "binding": {"support": ["h4"]}}]},
            {"id": "u2", "text": "UNRELATED_OLD_BODY", "support": ["h2"], "conditions": []}]}],
        "evidence": [
            {"id": "e1", "source": "s1", "range": [0, 10], "text": "A now Wu",
             "delivery_kind": "current"},
            {"id": "e2", "source": "s2", "range": [0, 30], "text": "A uses Lin; approval required",
             "delivery_kind": "redelivered_support"},
            {"id": "e3", "source": "s3", "range": [0, 30], "text": "UNRELATED_SOURCE_BODY",
             "delivery_kind": "redelivered_support"}],
        "historical_support": [
            {"id": "h1", "record": "r1", "unit": "u1",
             "ranges": [{"source": "s2", "range": [0, 10]}]},
            {"id": "h2", "record": "r1", "unit": "u2",
             "ranges": [{"source": "s3", "range": [0, 30]}]},
            {"id": "h3", "record": "r1", "unit": "u3",
             "ranges": [{"source": "s2", "range": [11, 30]}]},
            {"id": "h4", "record": "r1", "source": "u3", "target": "u1",
             "ranges": [{"source": "s2", "range": [0, 30]}]}],
        "source_table": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
        "time_choices": [{"id": "t1", "evidence": "e3", "quote": "UNRELATED_TIME_BODY"}]}
    mapping = {"records": {"r1": {"complete": "UNRELATED_OLD_BODY"}},
        "units": {u: {"record": "r1"} for u in ("u1", "u2", "u3")},
        "support": {h: {} for h in ("h1", "h2", "h3", "h4")},
        "evidence": {e: {"source_ref": s} for e, s in zip(
            ("e1", "e2", "e3"), ("source1", "source2", "source3"), strict=True)}}
    prior = [{"source_ref": "source3", "text": "UNRELATED_PRIOR_BODY"}]
    original = copy.deepcopy((packet, mapping, prior))
    regions = {"r1": {"context_units": ["u1", "u3"], "support_update_targets": ["u1"]}}
    projected = local_writer_view(packet, mapping, regions, prior)
    assert (packet, mapping, prior) == original
    assert projected["schema_mapping"]["records"] is mapping["records"]
    assert set(projected["schema_mapping"]["units"]) == {"u1", "u3"}
    assert projected["packet"]["records"][0]["view"] == "partial_units"
    assert projected["packet"]["records"][0]["omitted_units"] == 1
    assert "Approval required" in json.dumps(projected["packet"])
    assert "UNRELATED_" not in json.dumps(projected["packet"])
    assert projected["prior_context"] == []
    assert projected["selection"]["support"] == ["h1", "h3", "h4"]
    # Current new facts remain available even with no old target.
    empty = local_writer_view(packet, mapping,
                              {"r1": {"context_units": [], "support_update_targets": []}}, prior)
    assert [e["id"] for e in empty["packet"]["evidence"]] == ["e1"]
    assert empty["packet"]["records"][0]["clauses"] == []
    assert empty["schema_mapping"]["records"] is mapping["records"]


@pytest.mark.parametrize("selected_index", [0, 1, None])
def test_local_writer_commits_with_full_map_and_preserves_hidden_unit(tmp_path, selected_index):
    from jsonschema import Draft202012Validator, ValidationError
    from langgraph.store.sqlite import SqliteStore

    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.edit_features import EditFeatures
    from milai_lab.methods.edit_maintenance import maintain_event
    from milai_lab.methods.edit_memory import EditMemory

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("local", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        seed = EditMemory(service, "M")
        ref = service.capture_user("seed", "t0", "A uses Lin. B uses Gao. Approval required.")[
            "source_ref"]
        service.bind_public_turn("seed", "t0", ref, config_version="test", phase="start")
        evidence = seed.prepare([ref], "", selected_records=[])["sources"][0]["evidence_id"]
        saved = seed.apply("seed", "save", {"action": "create", "units": [
            {"text": "A uses Lin", "evidence": [evidence]},
            {"text": "B uses Gao", "evidence": [evidence]},
            {"text": "Approval required", "role": "condition", "evidence": [evidence]}],
            "relations": [{"source": 2, "target": i, "relation_type": "modifies",
                           "evidence": [evidence]} for i in (0, 1)]})
        assert saved["ok"]
        before = service.read(saved["id"])["value"]
        features = EditFeatures(matter_organization=True, semantic_operations=True,
            bound_references=True, single_record_changes=True, source_metadata=True,
            temporal_scope=True, proposition_updates=True, dependency_updates=True)
        method = EditMemory(service, "M", interface_version="I2", features=features,
                            maintenance_mode="event_delta_v1", writer_input="dependency_region_v1")
        name = "ABC"[2 if selected_index is None else selected_index]
        current = service.capture_user(
            "update", "t1", f"{name} now uses Wu; other facts unchanged.")["source_ref"]
        service.bind_public_turn("update", "t1", current, config_version="test", phase="start")
        delivery = method.prepare([current], "", selected_records=[])
        calls = []

        def call(stage, messages, schema):
            calls.append(stage)
            payload = json.loads(messages[-1]["content"])
            if stage == "impact":
                assert len(payload["delivery"]["records"][0]["clauses"]) == 2
                return {"roots": [] if selected_index is None else [f"u{selected_index + 1}"],
                        "preserve": []}
            record = payload["delivery"]["records"][0]
            assert record["view"] == "partial_units"
            targets = [] if selected_index is None else [f"u{selected_index + 1}"]
            assert [c["id"] for c in record["clauses"]] == targets
            if selected_index is not None:
                assert record["clauses"][0]["conditions"][0]["id"] == "u3"
            operation = ({"operation": "append", "role": "content"} if selected_index is None
                         else {"operation": "replace", "target_unit": targets[0]})
            proposal = {"creates": [], "records": {"r1": {"action": "edit", "edits": [{
                **operation, "text": name + " uses Wu", "evidence": ["e1"],
                "assertion": {"source_evidence": "e1", "kind": "reported"}}]}}}
            Draft202012Validator(schema).validate(proposal)
            hidden_change = copy.deepcopy(proposal)
            hidden_edit = hidden_change["records"]["r1"]["edits"][0]
            hidden_edit.pop("role", None)
            hidden_edit.update(operation="replace",
                               target_unit="u2" if selected_index == 0 else "u1")
            with pytest.raises(ValidationError):
                Draft202012Validator(schema).validate(hidden_change)
            return proposal

        result = maintain_event(method, delivery, session="update", request_id="update",
            date="2032-06-02", recipe="single_pass", model_call=call,
            selected_record_ids=[saved["id"]])
        assert result["status"] == "completed", result
        after = service.read(saved["id"])["value"]
        if selected_index is None:
            assert after["edit_state"]["units"][:-1] == before["edit_state"]["units"]
            assert after["edit_state"]["units"][-1]["text"] == "C uses Wu"
        else:
            assert after["edit_state"]["units"][selected_index]["text"] == name + " uses Wu"
            for i, original in enumerate(before["edit_state"]["units"]):
                if i != selected_index:
                    assert after["edit_state"]["units"][i] == original
        assert service.read(saved["id"], before["revision"])["value"] == before
        assert calls == ["impact", "edit"]
        assert result["writer_projection"]["visible_units"] == (
            [] if selected_index is None else [f"u{selected_index + 1}", "u3"])
