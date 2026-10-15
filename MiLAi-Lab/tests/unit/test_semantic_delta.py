"""Real SQLite effects for compact deltas; model responses here are scripted."""

import copy
import json

import pytest
from jsonschema import ValidationError
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.dependency_groups import support_status
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import maintain_event
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.methods.semantic_delta import compile_delta, indexed_target


def delta_method(service, mode="semantic_delta_v1"):
    return EditMemory(service, "M", interface_version="I2", maintenance_mode=mode,
        features=EditFeatures(matter_organization=True, bound_references=True,
            source_metadata=True, temporal_scope=True, proposition_updates=True,
            dependency_groups=True, single_record_changes=True))


@pytest.mark.parametrize("mode", ["semantic_delta_v1", "semantic_delta_v2"])
def test_one_call_delta_forms_shared_rule_then_preserves_non_target_and_history(tmp_path, mode):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("delta", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        method = delta_method(service, mode)
        calls = []

        def run(key, text, response, rows):
            ref = service.capture_user("s", key, text)["source_ref"]
            service.bind_public_turn("s", key, ref, config_version="delta", phase="start")
            delivery = method.prepare([ref], "", selected_records=rows,
                                      redelivered_ranges=method.target_support_ranges(rows))
            delivery["materialize_selected_support"] = True

            def model_call(stage, messages, schema):
                calls.append(stage)
                assert stage == "edit"
                assert "only the semantic changes" in messages[0]["content"]
                assert json.loads(messages[1]["content"])["response_schema"] == schema
                return indexed_target(response) if mode == "semantic_delta_v2" else response

            return maintain_event(method, delivery, session="s", request_id=key,
                date="2035-01-01", recipe="single_pass", model_call=model_call,
                selected_record_ids=[row["id"] for row in rows])

        texts = ["The card is valid.", "The voucher is valid.", "Training is complete.",
                 "Borrowing requires training and either a valid card or voucher.",
                 "Labels stay green."]
        formed = run("form", " ".join(texts), {"creates": [{
            "matter": "Borrowing", "nodes": [
                {"id": f"n{i}", "text": text, "basis": "e1", "kind": "reported"}
                for i, text in enumerate(texts)],
            "rules": [{"target": "n3", "all": ["n2"], "any": [["n0"], ["n1"]],
                       "basis": "e1"}]}], "changes": {}}, [])
        assert formed["status"] == "completed", formed
        first = service.read(formed["receipts"][0]["id"])
        initial = copy.deepcopy(first["value"]["edit_state"])
        ids = {unit["text"]: unit["unit_id"] for unit in initial["units"]}
        group = initial["support_groups"][0]
        assert group["alternatives"] == [[ids[texts[2]], ids[texts[0]]],
                                          [ids[texts[2]], ids[texts[1]]]]
        assert support_status(group, {ids[texts[0]]: False, ids[texts[1]]: None,
                                      ids[texts[2]]: True}) == "unknown"
        changed = run("card", "The card is invalid; the voucher and training still hold.", {
            "creates": [], "changes": {"r1": {
                "replace": {"u1": {"text": "The card is invalid.", "basis": "e1",
                                   "kind": "reported"}},
                "rules": [{"target": "u4", "all": ["u3"], "any": [["u2"]],
                           "basis": "e1", "also": ["e2"]}]
            }}}, [first])
        assert changed["status"] == "completed", changed
        current = service.read(first["id"])["value"]["edit_state"]
        assert current["units"][1:] == initial["units"][1:]
        assert current["support_groups"][0]["alternatives"] == [[ids[texts[2]], ids[texts[1]]]]
        references = current["support_groups"][0]["evidence_refs"]
        assert len({ref["source_ref"] for ref in references}) == 2
        assert initial["support_groups"][0]["evidence_refs"][0]["source_ref"] in {
            ref["source_ref"] for ref in references}
        assert service.read(first["id"], 1)["value"]["edit_state"] == initial
        assert calls == ["edit", "edit"]
        # Reopening the same operation consumes its persisted receipt, not a new generation.
        saved = store.get((*service.namespace, "edit_maintenance"), json.dumps(["s", "card"]))
        assert saved.value["phase"] == "complete"


def test_new_aliases_bind_append_positions_and_rule_only_updates():
    mapping = {"allow_create": True, "evidence": {"e1": {}}, "records": {"r1": {}},
               "units": {"u1": {"record": "r1"}, "u2": {"record": "r1"}}}
    payload = {"creates": [], "changes": {"r1": {
        "replace": {"u1": {"text": "Credential expired.", "basis": "e1", "kind": "reported"}},
        "append": [{"id": "n7", "text": "A paper permit is valid.", "basis": "e1",
                    "kind": "reported"}],
        "rules": [{"target": "u2", "all": [], "any": [["n7"]], "basis": "e1"}]}}}
    proposal = compile_delta(payload, mapping)[0]
    assert proposal["support_groups"][0]["alternatives"] == [["n0"]]
    assert [edit["operation"] for edit in proposal["edits"]] == ["replace", "append"]
    payload["changes"]["r1"] = {"rules": [{"target": "u2", "all": [], "any": [], "basis": "e1"}]}
    proposal = compile_delta(payload, mapping)[0]
    assert proposal["edits"] == [] and proposal["support_groups"][0]["alternatives"] == []


@pytest.mark.parametrize("field,value,error", [
    ("basis", "missing", ValidationError),
    ("target", "n404", FunctionalRejection),
])
def test_unbound_names_never_become_persistent_ids(field, value, error):
    mapping = {"allow_create": True, "evidence": {"e1": {}}, "records": {}, "units": {}}
    rule = {"target": "n1", "all": [], "any": [["n0"]], "basis": "e1", field: value}
    payload = {"creates": [{"matter": "test", "nodes": [
        {"id": "n0", "text": "A", "basis": "e1", "kind": "reported"},
        {"id": "n1", "text": "B", "basis": "e1", "kind": "reported"}],
        "rules": [rule]}], "changes": {}}
    with pytest.raises(error):
        compile_delta(payload, mapping)


def test_text_without_rules_and_no_change_are_legal():
    mapping = {"allow_create": True, "evidence": {"e1": {}}, "records": {}, "units": {}}
    assert compile_delta({"creates": [], "changes": {}}, mapping) == []
    result = compile_delta({"creates": [{"matter": "Plan",
        "nodes": [{"id": "n0", "text": "No date is confirmed for the proposed trip.",
                   "basis": "e1", "kind": "reported"}]}], "changes": {}}, mapping)
    assert "support_groups" not in result[0]
    assert result[0]["clauses"][0]["text"].startswith("No date")


def test_indexed_append_binds_generated_units_without_model_names_or_labels():
    mapping = {"allow_create": True, "evidence": {"e1": {}}, "records": {"r1": {}},
               "units": {"u1": {"record": "r1"}}}
    payload = {"creates": [], "changes": {"r1": {
        "append": [{"text": "Training is complete.", "basis": "e1", "kind": "reported"}],
        "rules": [{"target": "u1", "all": [0], "any": [[]], "basis": "e1"}]}}}
    proposal = compile_delta(payload, mapping, indexed=True)[0]
    assert proposal["support_groups"][0]["alternatives"] == [["n0"]]
    payload["changes"]["r1"]["rules"][0]["all"] = [1]
    with pytest.raises(FunctionalRejection, match="DELTA_RULE_INDEX_UNAVAILABLE"):
        compile_delta(payload, mapping, indexed=True)
