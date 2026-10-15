"""Source-bound support groups use existing SQLite revisions, never ideal truth graphs."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.dependency_groups import apply_support_groups, support_status
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.dependency_memory import (
    dependency_region,
    plan_regions,
    query_support,
    scoped_edit_schema,
)
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    decode_dependency_reads,
    dependency_read_request,
    open_evidence_packs,
    project_packs,
)


def test_or_of_and_has_no_single_premise_or_unknown_shortcut():
    group = {"alternatives": [["card", "training"], ["voucher", "training"]]}
    assert support_status(group, {"card": False, "voucher": True, "training": True}) == "supported"
    assert support_status(group, {"card": True, "voucher": True, "training": False}) == (
        "unsupported")
    assert support_status(group, {"card": False, "voucher": None, "training": True}) == "unknown"
    assert support_status({"alternatives": []}, {}) == "unsupported"


def test_removing_a_deleted_base_units_group_is_cleanup_not_a_new_dangling_group():
    old = {"units": [{"unit_id": "premise"}, {"unit_id": "target"}], "relations": [],
           "support_groups": [{"group_id": "g", "target_unit": "target",
                               "alternatives": [["premise"]], "evidence_refs": []}]}
    current = {"units": [{"unit_id": "premise"}], "relations": [],
               "support_groups": old["support_groups"]}
    apply_support_groups(current, [{"operation": "remove", "target": {"existing": "target"},
                                   "evidence_refs": []}], old=old)
    assert current["support_groups"] == []
    assert old["support_groups"][0]["target_unit"] == "target"
    with pytest.raises(FunctionalRejection, match="EDIT_SUPPORT_UNIT_UNAVAILABLE"):
        apply_support_groups(current, [{"operation": "set", "target": {"existing": "target"},
            "alternatives": [[{"existing": "premise"}]], "evidence_refs": []}], old=old)
    with pytest.raises(FunctionalRejection, match="EDIT_SUPPORT_UNIT_UNAVAILABLE"):
        apply_support_groups(current, [{"operation": "remove",
            "target": {"existing": "never-in-this-base"}, "evidence_refs": []}], old=old)


def test_groups_form_with_clause_indexes_and_survive_local_retraction(tmp_path: Path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("groups", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        method = EditMemory(service, "M", interface_version="I2",
            features=EditFeatures(bound_references=True, source_metadata=True,
                                  dependency_groups=True))

        def view(key, text, records):
            ref = service.capture_user("story", key, text)["source_ref"]
            service.bind_public_turn("story", key, ref, config_version="groups", phase="start")
            delivery = method.prepare([ref], "", selected_records=records,
                redelivered_ranges=method.target_support_ranges(records))
            return method.writer_request(delivery, request_id=key)

        def clause(text):
            return {"text": text, "evidence": ["e1"], "conditions": [],
                    "assertion": {"source_evidence": "e1", "kind": "reported"}}

        request = view("seed", "This quarter card and voucher are valid. Training is complete. "
            "Rare seeds need training and either card or voucher. Labels stay green.", [])
        clauses = [clause(text) for text in ["The card is valid.", "The voucher is valid.",
            "Training is complete.", "Rare seeds may be borrowed.", "Labels stay green."]]
        # An expanded condition between clauses must not shift the model's clause indexes.
        condition = clause("This quarter.")
        condition.pop("conditions")
        condition["binding"] = {"evidence": ["e1"]}
        clauses[0]["conditions"] = [condition]
        formed = method.apply("story", "form", method.decode_proposal({
            "action": "create", "clauses": clauses,
            "support_groups": [{"target_unit": 3, "alternatives": [[0, 2], [1, 2]],
                                "evidence": ["e1"]}],
        }, request["mapping"]))
        assert formed["ok"], formed
        first = service.read(formed["id"])
        state = first["value"]["edit_state"]
        ids = {unit["text"]: unit["unit_id"] for unit in state["units"]}
        card, voucher, training, eligible = [ids[text] for text in (
            "The card is valid.", "The voucher is valid.", "Training is complete.",
            "Rare seeds may be borrowed.")]
        group = state["support_groups"][0]
        assert group["target_unit"] == eligible
        assert group["alternatives"] == [[card, training], [voucher, training]]
        affected = dependency_region(state, [card])
        assert eligible in affected["affected_units"]
        kept = dependency_region(state, [card], preserve=[eligible])
        assert eligible not in kept["affected_units"]
        assert {voucher, training} <= set(kept["read_only_units"])
        selected, _ = query_support(state, [eligible], support_choices={eligible: [1]},
                                    excluded=[training])
        assert voucher in selected and training in selected and card not in selected
        choice = {formed["id"]: {"roots": [eligible], "excluded": [],
            "history_revisions": [], "support_choices": {eligible: [1]}}}
        old_pack = build_evidence_packs(service, "Can I borrow rare seeds?", "2031-01-02",
                                       [], [first], dependency_selections=choice)
        projected = project_packs(open_evidence_packs(service, old_pack), [0])[0]
        assert len(projected["support_groups"][0]["alternatives"]) == 1
        assert projected["support_groups"][0]["total_routes"] == 2

        request = view("card-invalid",
                       "The card is now invalid, while voucher and training remain.", [first])
        aliases = {unit["unit_id"]: alias for alias, unit in request["mapping"]["units"].items()}
        replaced = method.apply("story", "card-invalid", method.decode_proposal({
            "action": "edit", "target": "r1", "edits": [{
                "operation": "replace", "target_unit": aliases[card],
                "text": "The card is invalid.", "evidence": ["e1"],
                "assertion": {"source_evidence": "e1", "kind": "reported"}}],
        }, request["mapping"]))
        assert replaced["ok"], replaced
        current = service.read(formed["id"])
        changed_group = current["value"]["edit_state"]["support_groups"][0]
        assert changed_group["changed_premises"] == [card]
        assert support_status(changed_group, {card: True, voucher: False, training: True}) == (
            "unknown")
        assert support_status(changed_group, {card: False, voucher: True, training: True}) == (
            "supported")
        # Preserve the target's wording while still permitting its dependency repair.
        regions = plan_regions(request["mapping"], {"roots": [aliases[card]],
                                                    "preserve": [aliases[eligible]]})
        scoped = scoped_edit_schema(request["schema"], regions)
        repair = {"action": "edit", "target": "r1", "edits": [], "support_groups": [{
            "target_unit": aliases[eligible],
            "alternatives": [[aliases[voucher], aliases[training]]],
            "evidence": ["e1"]}]}
        Draft202012Validator(scoped).validate({"proposals": [repair]})
        for key, target in (("withdraw-card", card), ("withdraw-voucher", voucher)):
            request = view(key, key + "; training and labels stay unchanged.", [current])
            target_alias = next(alias for alias, unit in request["mapping"]["units"].items()
                                if unit["unit_id"] == target)
            saved = method.apply("story", key, method.decode_proposal({
                "action": "edit", "target": "r1", "edits": [{
                    "operation": "retract", "target_unit": target_alias, "evidence": ["e1"]}],
            }, request["mapping"]))
            assert saved["ok"], saved
            current = service.read(formed["id"])
            remaining = current["value"]["edit_state"]
            assert eligible in {unit["unit_id"] for unit in remaining["units"]}
            if target == card:
                assert remaining["support_groups"][0]["alternatives"] == [[voucher, training]]
                refreshed = open_evidence_packs(service, old_pack, refresh_current=True)[0]
                assert refreshed["support_selection_status"] == "new_revision_routes_reopened"
                assert refreshed["revision"] == 3
            else:
                assert remaining["support_groups"][0]["alternatives"] == []
        assert service.read(formed["id"], 1)["value"]["edit_state"] == state

        request = view("paper-permit", "A paper permit plus completed training is another "
                       "independent route for rare seeds. This permit is valid.", [current])
        aliases = {unit["unit_id"]: alias for alias, unit in request["mapping"]["units"].items()}
        saved = method.apply("story", "paper-permit", method.decode_proposal({
            "action": "edit", "target": "r1", "edits": [{"operation": "append",
                "text": "The paper permit is valid.", "role": "content", "evidence": ["e1"],
                "assertion": {"source_evidence": "e1", "kind": "reported"}}],
            "support_groups": [{"target_unit": aliases[eligible],
                "alternatives": [["n0", aliases[training]]], "evidence": ["e1"]}],
        }, request["mapping"]))
        assert saved["ok"], saved
        final = service.read(formed["id"])
        final_state = final["value"]["edit_state"]
        new = next(unit["unit_id"] for unit in final_state["units"]
                   if unit["text"] == "The paper permit is valid.")
        assert final_state["support_groups"][0]["alternatives"] == [[new, training]]
        query = dependency_read_request(service, "Can I borrow rare seeds?", "2031-01-03", [final])
        target_index = query["mapping"]["r0"]["units"].index(eligible)
        response = {"r0": {"roots": [target_index], "excluded": [], "history_revisions": [],
                           "support_choices": {f"u{target_index}": [0]}}}
        assert decode_dependency_reads(query, response)[formed["id"]]["support_choices"] == {
            eligible: [0]}
        assert "paper permit" in json.dumps(query["messages"])


def test_group_only_revision_keeps_its_own_source_and_respects_update_region(tmp_path: Path):
    with SqliteStore.from_conn_string(str(tmp_path / "groups-only.sqlite")) as store:
        service = MemoryService(store, ("groups", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        method = EditMemory(service, "M", interface_version="I2",
                            features=EditFeatures(bound_references=True, dependency_groups=True))
        original = service.capture_user(
            "story", "seed", "Training and permit are valid; eligible.")["source_ref"]
        service.bind_public_turn("story", "seed", original, config_version="groups", phase="start")
        request = method.writer_request(method.prepare([original], "", selected_records=[]))
        saved = method.apply("story", "seed", method.decode_proposal({
            "action": "create", "clauses": [
                {"text": text, "conditions": [], "evidence": ["e1"]} for text in (
                    "Training is complete.", "Permit is valid.", "Eligible for rare seeds.")],
        }, request["mapping"]))
        assert saved["ok"]
        before = service.read(saved["id"])
        ref = service.capture_user(
            "story", "explain", "Training AND permit jointly establish eligibility.")["source_ref"]
        service.bind_public_turn("story", "explain", ref, config_version="groups", phase="start")
        request = method.writer_request(method.prepare([ref], "", selected_records=[before]))
        proposal = {"action": "edit", "target": "r1", "edits": [], "support_groups": [{
            "target_unit": "u3", "alternatives": [["u1", "u2"]], "evidence": ["e1"]}]}
        # Normal edits and group-only edits are separate complete generation
        # variants. Their union still excludes an empty disguised edit/no-op.
        for empty in ({"action": "edit", "target": "r1", "edits": []},
                      {"action": "edit", "target": "r1", "edits": [], "support_groups": []}):
            with pytest.raises(ValidationError):
                Draft202012Validator(request["schema"]).validate({"proposals": [empty]})
        Draft202012Validator(request["schema"]).validate({"proposals": [proposal]})
        limited = scoped_edit_schema(request["schema"], {"r1": {"affected_units": ["u1"]}})
        with pytest.raises(ValidationError):
            Draft202012Validator(limited).validate({"proposals": [proposal]})
        receipt = method.apply(
            "story", "explain", method.decode_proposal(proposal, request["mapping"]))
        assert receipt["ok"], receipt
        after = service.read(saved["id"])
        assert after["value"]["revision"] == before["value"]["revision"] + 1
        assert after["value"]["edit_state"]["units"] == before["value"]["edit_state"]["units"]
        support = after["value"]["edit_state"]["support_groups"][0]["evidence_refs"][0]
        assert support["source_ref"] == ref
        packs = build_evidence_packs(service, "Why eligible?", "2031-01-01", [], [after])
        assert any(span["source_ref"] == ref for span in packs[0]["revision_evidence"])
        assert service.read(saved["id"], 1)["value"] == before["value"]
        removed_ref = service.capture_user("story", "remove", "That dependency was mistaken; "
            "the explicit eligibility grant stands independently.")["source_ref"]
        service.bind_public_turn("story", "remove", removed_ref,
                                 config_version="groups", phase="start")
        request = method.writer_request(method.prepare([removed_ref], "", selected_records=[after]))
        removed = method.apply("story", "remove", method.decode_proposal({
            "action": "edit", "target": "r1", "edits": [], "support_groups": [{
                "operation": "remove", "target_unit": "u3", "evidence": ["e1"]}],
        }, request["mapping"]))
        assert removed["ok"], removed
        assert service.read(saved["id"])["value"]["edit_state"]["support_groups"] == []
        assert service.read(saved["id"], 2)["value"] == after["value"]
        handle = service.source_fragments(ref)[0]["fragment_handle"]
        assert service.forget("story", "forget-explanation", fragment_handles=[handle])["ok"]
        assert not service.read(saved["id"])["ok"]
        # Existing forgetting hides the linked record, including its history.
        # Group-only support cannot bypass that visibility contract.
        assert not service.read(saved["id"], 1)["ok"]


def test_changed_target_does_not_reuse_old_proof_until_explicit_group_reset(tmp_path: Path):
    with SqliteStore.from_conn_string(str(tmp_path / "target.sqlite")) as store:
        service = MemoryService(store, ("target", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        method = EditMemory(service, "M", interface_version="I2",
                            features=EditFeatures(bound_references=True, dependency_groups=True))

        def view(key, text, records):
            ref = service.capture_user("story", key, text)["source_ref"]
            service.bind_public_turn("story", key, ref, config_version="target", phase="start")
            return method.writer_request(method.prepare([ref], "", selected_records=records))

        request = view("seed", "Training and permit are valid, so eligible for rare seeds.", [])
        receipt = method.apply("story", "seed", method.decode_proposal({
            "action": "create", "clauses": [
                {"text": text, "conditions": [], "evidence": ["e1"]} for text in (
                    "Training complete.", "Permit valid.", "Eligible for rare seeds.")],
            "support_groups": [{"target_unit": 2, "alternatives": [[0, 1]], "evidence": ["e1"]}],
        }, request["mapping"]))
        before = service.read(receipt["id"])
        request = view("change", "This entry now records a fee waiver instead of eligibility.",
                       [before])
        saved = method.apply("story", "change", method.decode_proposal({
            "action": "edit", "target": "r1", "edits": [{"operation": "replace",
                "target_unit": "u3", "text": "Fee waived.", "evidence": ["e1"]}],
        }, request["mapping"]))
        assert saved["ok"], saved
        after = service.read(receipt["id"])
        state = after["value"]["edit_state"]
        group = state["support_groups"][0]
        assert group["changed_target"] is True
        assert not group.get("changed_premises")
        applicable = {unit["unit_id"]: True for unit in state["units"]}
        assert support_status(group, applicable) == "unknown"
        packs = build_evidence_packs(service, "Fee?", "2031-01-01", [], [after])
        assert project_packs(open_evidence_packs(service, packs), [0])[0][
            "support_groups"][0]["changed_target"] is True
        request = view("confirm", "Training AND permit explicitly establish the fee waiver.",
                       [after])
        assert request["packet"]["records"][0]["support_groups"][0]["changed_target"] is True
        saved = method.apply("story", "confirm", method.decode_proposal({
            "action": "edit", "target": "r1", "edits": [], "support_groups": [{
                "target_unit": "u3", "alternatives": [["u1", "u2"]], "evidence": ["e1"]}],
        }, request["mapping"]))
        assert saved["ok"], saved
        confirmed = service.read(receipt["id"])["value"]["edit_state"]["support_groups"][0]
        assert not confirmed.get("changed_target")
        assert support_status(confirmed, applicable) == "supported"
        assert service.read(receipt["id"], 1)["value"] == before["value"]
