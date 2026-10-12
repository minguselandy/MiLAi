"""Patch proposals through actual maintenance and SQLite; synthetic, without HTTP."""

from __future__ import annotations

import copy
import json
import socket
from contextlib import contextmanager
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.edit_units import read_retained_support, read_revision_evidence
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.reader_projection import expand_record
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures, compile_semantic_operations
from milai_lab.methods.edit_maintenance import maintain_event
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.runners.edit_benchmarks import BenchmarkRun

FEATURES = EditFeatures(True, True, True, True, True, temporal_scope=True, patch_text=True)
ORIGINAL = "Project A needs three reminders weekly; Project B needs one; confirm external notices."


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("SYNTHETIC_ENGINEERING_NO_HTTP")

    monkeypatch.setattr(socket.socket, "connect", denied)


@contextmanager
def opened(path, arm="M", maintenance_mode="legacy"):
    with SqliteStore.from_conn_string(str(path / "patch.sqlite")) as store:
        service = MemoryService(
            store, ("patch", "alice"), "alice", path / "lock",
            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
        )
        yield service, EditMemory(
            service, arm, interface_version="I2", features=FEATURES,
            maintenance_mode=maintenance_mode,
        )


def delivered(service, method, key, text, records=()):
    ref = service.capture_user("s", key, text, occurred_at="2026-10-13")["source_ref"]
    service.bind_source_boundary("s", key, [ref])
    return method.prepare([ref], text, selected_records=list(records)), ref


def seed(service, method, text=ORIGINAL):
    delivery, ref = delivered(service, method, "initial", text + " Only on weekdays.")
    view = method.writer_request(delivery, request_id="initial")
    assertion = {"source_evidence": "e1", "kind": "reported"}
    clause = {"text": text, "evidence": ["e1"], "assertion": assertion}
    if method.conditioned:
        clause["conditions"] = [{
            "text": "Only on weekdays.", "evidence": ["e1"], "assertion": assertion,
            "binding": {"evidence": ["e1"]},
        }]
    proposal = {"action": "create", "matter": "Project reminders", "clauses": [clause]}
    receipt = method.apply("s", "initial", method.decode_proposal(proposal, view["mapping"]))
    assert receipt["ok"]
    return receipt["id"], ref


def patch(record="r1", unit="u1", evidence="e1", old_text="three", new_text="two"):
    return {
        "action": "edit", "target": record,
        "edits": [{
            "operation": "patch_text", "target_unit": unit,
            "old_text": old_text, "new_text": new_text, "evidence": [evidence],
            "assertion": {"source_evidence": evidence, "kind": "reported",
                          "applicability": {"scope": "Project reminders"}},
        }],
    }


@pytest.mark.parametrize("arm", ["B1", "M"])
@pytest.mark.parametrize("maintenance_mode", ["legacy", "event_delta_v1"])
def test_patch_maintenance_preserves_other_requirements_support_and_history(
    tmp_path, arm, maintenance_mode,
):
    with opened(tmp_path, arm, maintenance_mode) as (service, method):
        record_id, old_ref = seed(service, method)
        before = copy.deepcopy(service.read(record_id)["value"])
        delivery, new_ref = delivered(
            service, method, "update", "For Project A, use two reminders weekly.",
            [service.read(record_id)],
        )
        responses = []

        def writer(stage, messages, schema):
            assert stage == "edit" and "patch_text" in messages[0]["content"]
            assert "old_text and new_text" in messages[0]["content"]
            assert "own delivered h support" in messages[0]["content"]
            if maintenance_mode == "event_delta_v1":
                assert messages[0]["content"].startswith("Maintain the meaning changed")
            packet = json.loads(messages[1]["content"])["delivery"]
            record = packet["records"][0]
            evidence = packet["evidence"][0]["id"]
            proposal = patch(record["id"], record["clauses"][0]["id"], evidence)
            proposal.pop("target")
            envelope = {"creates": [], "records": {record["id"]: proposal}}
            Draft202012Validator(schema).validate(envelope)
            responses.append(envelope)
            return envelope

        result = maintain_event(
            method, delivery, session="s", request_id="update", date="2026-10-13",
            recipe="single_pass", model_call=writer, selected_record_ids=[record_id],
        )
        assert result["status"] == "completed" and result["semantic_write_performed"]
        assert len(responses) == 1
        current = service.read(record_id)["value"]
        old_unit = before["edit_state"]["units"][0]
        unit = current["edit_state"]["units"][0]
        assert unit["text"] == ORIGINAL.replace("three", "two")
        assert unit["unit_id"] == old_unit["unit_id"]
        assert unit["assertion"]["source_ref"] == new_ref
        assert unit["assertion"]["applicability"] == {"scope": "Project reminders"}
        assert {ref["source_ref"] for ref in unit["evidence_refs"]} == {old_ref, new_ref}
        assert current["edit_state"]["units"][1:] == before["edit_state"]["units"][1:]
        assert current["edit_state"]["relations"] == before["edit_state"]["relations"]
        # Retained support is not falsely promoted to this revision's new witness.
        assert {row["source_ref"] for row in read_revision_evidence(service, current)} == {new_ref}
        retained = read_retained_support(service, current)
        assert {row["source_ref"] for row in retained} == {old_ref}
        assert retained[0]["support_role"] == "retained_support"
        assert retained[0]["content"] == ORIGINAL + " Only on weekdays."
        assert read_retained_support(service, before) == []
        assert service.read(record_id, 1)["value"] == before
        execution = BenchmarkRun.__new__(BenchmarkRun)
        execution.settings = {
            "edit_features": FEATURES.settings(), "memory_view_mode": "direct",
            "maintenance_recipe": "single_pass", "reader_projection": "semantic_units_v1",
            "evidence_variant": "S2", "context_tokens": 100000, "model": {"max_tokens": 1000},
        }
        execution.input_tokens = lambda messages, **kwargs: len(json.dumps(messages))
        semantic = execution._record_materials(service, [service.read(record_id)], "2026-10-13")
        expanded = expand_record(semantic[0])
        assert expanded["retained_support"] == retained
        assert {row["source_ref"] for row in expanded["revision_evidence"]} == {new_ref}
        native = {"source_materials": []}
        materials = execution._source_first_materials(
            service, "What are the current reminder requirements?", "2026-10-13",
            native, semantic, snapshot_id="synthetic/current",
        )
        originals = [row for row in materials if row["kind"] == "original_source"]
        assert {span["source_ref"] for row in originals for span in row["source_ranges"]} == {
            old_ref, new_ref,
        }
        assert native["material_assembly"]["linked_original_candidates"] == 2
        assert native["material_assembly"]["semantic_materials"] == 1
        assert {row["source_ref"] for row in expand_record(materials[-1])["retained_support"]} == {
            old_ref,
        }
        assert maintain_event(
            method, delivery, session="s", request_id="update", date="2026-10-13",
            recipe="single_pass", model_call=writer, selected_record_ids=[record_id],
        ) == result
        assert len(responses) == 1
    with opened(tmp_path, arm) as (service, _):
        assert service.read(record_id)["value"] == current
        assert service.read(record_id, 1)["value"] == before
        assert read_retained_support(service, service.read(record_id)["value"]) == retained


@pytest.mark.parametrize("text,old_text", [
    ("A: three. B: three.", "three"),
    ("A: three.", "missing"),
    ("An overlapping value aaa.", "aa"),
])
def test_patch_nonunique_match_keeps_existing_rejection_receipt(tmp_path, text, old_text):
    with opened(tmp_path) as (service, method):
        record_id, _ = seed(service, method, text)
        before = copy.deepcopy(service.read(record_id)["value"])
        delivery, _ = delivered(service, method, "update", "Set A to two.")

        def writer(stage, messages, schema):
            proposal = patch(old_text=old_text)
            proposal.pop("target")
            return {"creates": [], "records": {"r1": proposal}}

        result = maintain_event(
            method, delivery, session="s", request_id="update", date="2026-10-13",
            recipe="single_pass", model_call=writer, selected_record_ids=[record_id],
        )
        assert result["status"] == "incomplete"
        assert result["receipts"][0]["reason"] == "EDIT_PATCH_TEXT_MATCH_NOT_UNIQUE"
        assert not result["semantic_write_performed"]
        assert service.read(record_id)["value"] == before


def test_patch_current_assertion_and_actual_target_support_are_bound(tmp_path):
    assert "patch_text" not in EditFeatures().settings()
    with opened(tmp_path) as (service, method):
        record_id, _ = seed(service, method)
        delivery, _ = delivered(
            service, method, "update", "Set A to two.", [service.read(record_id)],
        )
        view = method.writer_request(delivery, request_id="update")
        proposal = patch()
        original = copy.deepcopy(proposal)
        compiled = compile_semantic_operations(proposal, view["mapping"])
        assert proposal == original
        assert compiled["edits"][0]["keep_support"] == ["h1"]
        assert compiled["edits"][0]["assertion"]["source"] == "e1"
        for for_generation in (False, True):
            schema = method.proposal_schema(mapping=view["mapping"], for_generation=for_generation)
            Draft202012Validator(schema).validate(proposal)
            retained = copy.deepcopy(proposal)
            retained["edits"][0]["assertion"] = {"keep": "h1"}
            assert not Draft202012Validator(schema).is_valid(retained)
        for target in ("u2", "u99"):
            with pytest.raises(FunctionalRejection, match="PROPOSAL_INVALID"):
                method.decode_proposal(patch(unit=target), view["mapping"])
        for operation in ("patch_text", "replace"):
            repeated = copy.deepcopy(proposal)
            second = copy.deepcopy(proposal["edits"][0])
            if operation == "replace":
                second["operation"] = operation
                second["text"] = ORIGINAL
                second.pop("old_text")
                second.pop("new_text")
            repeated["edits"].append(second)
            with pytest.raises(FunctionalRejection, match="EDIT_PATCH_TEXT_TARGET_REPEATED"):
                method.decode_proposal(repeated, view["mapping"])
        legacy = EditMemory(
            service, "M", interface_version="I2", features=replace(FEATURES, patch_text=False),
        )
        assert "patch_text" not in json.dumps(legacy.proposal_schema(mapping=view["mapping"]))
