"""Cross-record premises use actual source-bound records and sequential receipts."""

import copy
from pathlib import Path

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.external_support import dependent_record_candidates, inspect_external_unit
from milai_lab.memory.service import MemoryService
from milai_lab.methods.dependency_memory import plan_regions
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    project_packs,
)


@pytest.fixture
def case(tmp_path: Path):
    with SqliteStore.from_conn_string(str(tmp_path / "cross.sqlite")) as store:
        service = MemoryService(store, ("cross", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        method = EditMemory(service, "M", interface_version="I2", features=EditFeatures(
            bound_references=True, dependency_groups=True, cross_record_dependencies=True))

        def request(key, text, records):
            ref = service.capture_user("story", key, text)["source_ref"]
            service.bind_public_turn("story", key, ref, config_version="cross", phase="start")
            return method.writer_request(method.prepare([ref], "", selected_records=records,
                redelivered_ranges=method.target_support_ranges(records)), request_id=key)

        def clause(text):
            return {"text": text, "conditions": [], "evidence": ["e1"]}

        view = request("credentials", "Card and voucher are valid. Desk labels stay blue.", [])
        credentials = method.apply("story", "credentials", method.decode_proposal({
            "action": "create", "clauses": [clause(t) for t in (
                "Card valid.", "Voucher valid.", "Desk labels blue.")],
        }, view["mapping"]))
        first = service.read(credentials["id"])
        view = request("eligibility", "Training is complete. Either valid card or voucher, "
                       "together with training, suffices for eligibility.", [first])
        eligibility = method.apply("story", "eligibility", method.decode_proposal({
            "action": "create", "clauses": [clause("Training complete."), clause("Eligible.")],
            "support_groups": [{"target_unit": 1, "alternatives": [
                [{"record": "r1", "unit": "u1"}, 0],
                [{"record": "r1", "unit": "u2"}, 0]], "evidence": ["e1"]}],
        }, view["mapping"]))
        assert credentials["ok"] and eligibility["ok"], eligibility
        yield service, method, request, credentials["id"], eligibility["id"]


def test_cross_record_group_bindings_global_region_and_selected_route(case):
    service, _method, request, credential_id, target_id = case
    first, second = service.read(credential_id), service.read(target_id)
    state = second["value"]["edit_state"]
    group = state["support_groups"][0]
    assert len(group["external_units"]) == 2
    assert {x["record_id"] for x in group["external_units"].values()} == {credential_id}
    assert {x["revision"] for x in group["external_units"].values()} == {1}
    assert {r["id"] for r in dependent_record_candidates(service, [first])} == {
        credential_id, target_id}
    view = request("change", "Card expires, voucher and training remain valid.", [first, second])
    region = plan_regions(view["mapping"], {"roots": ["u1"], "preserve": []})
    assert region["r1"]["affected_units"] == ["u1"]
    assert region["r2"]["affected_units"] == ["u5"]
    assert "u2" in region["r1"]["read_only_units"]
    assert "u4" in region["r2"]["read_only_units"]
    kept = plan_regions(view["mapping"], {"roots": ["u1"], "preserve": ["u5"]})
    assert kept["r2"]["affected_units"] == []
    assert kept["r2"]["support_update_targets"] == ["u5"]
    target = state["units"][1]["unit_id"]
    selection = {target_id: {"roots": [target], "excluded": [], "history_revisions": [],
                              "support_choices": {target: [1]}}}
    packs = build_evidence_packs(service, "Eligible?", "2031-01-01", [], [second],
                                 dependency_selections=selection)
    assert len(packs) == 2
    opened = open_evidence_packs(service, packs)
    projected = project_packs(opened, [0, 1])
    assert "Voucher valid." in str(projected) and "Card valid." not in str(
        [p.get("units", []) for p in projected])
    external = projected[0]["support_groups"][0]["external_references"][0]
    assert external["current_pack_index"] == 1 and external["status"] == "unchanged"
    assert external["current_unit"] == "u0"
    unopened = project_packs(open_evidence_packs(service, packs[:1]), [0])[0]
    assert unopened["support_groups"][0]["external_references"][0][
        "current_body_delivered"] is False
    assert credential_id not in str(projected)


def test_sequential_group_reset_binds_confirmed_foreign_revision(case):
    service, method, request, credential_id, target_id = case
    first, second = service.read(credential_id), service.read(target_id)
    view = request("expire", "Card is invalid. Voucher and training still support eligibility.",
                   [first, second])
    envelope = {"proposals": [
        {"action": "edit", "target": "r2", "edits": [], "support_groups": [{
            "target_unit": "u5", "alternatives": [[{"record": "r1", "unit": "u2"}, "u4"]],
            "evidence": ["e1"]}]},
        {"action": "edit", "target": "r1", "edits": [{"operation": "replace",
            "target_unit": "u1", "text": "Card invalid.", "evidence": ["e1"]}]},
    ]}
    proposals = method.envelope_proposals(envelope, view["mapping"])
    assert [p["target"] for p in proposals] == ["r1", "r2"]
    receipts = []
    for i, proposal in enumerate(proposals):
        receipts.append(method.apply("story", f"expire:{i}", method.decode_proposal(
            proposal, view["mapping"]), dependency_receipts=receipts))
    assert all(r["ok"] for r in receipts), receipts
    current = service.read(target_id)
    group = current["value"]["edit_state"]["support_groups"][0]
    binding = next(iter(group["external_units"].values()))
    assert binding["revision"] == 2
    assert inspect_external_unit(service, binding)["status"] == "unchanged"
    assert current["value"]["edit_state"]["units"] == second["value"]["edit_state"]["units"]
    assert service.read(target_id, 1)["value"] == second["value"]
    assert service.read(credential_id, 1)["value"] == first["value"]


def test_partial_commit_remains_visible_and_history_uses_bound_premise(case):
    from milai_lab.methods.edit_maintenance import maintain_event

    service, method, _request, credential_id, target_id = case
    first, second = service.read(credential_id), service.read(target_id)
    prior_target = copy.deepcopy(second["value"])
    ref = service.capture_user("story", "withdraw", "Card withdrawn; voucher remains.")[
        "source_ref"]
    service.bind_public_turn("story", "withdraw", ref, config_version="cross", phase="start")
    delivery = method.prepare([ref], "", selected_records=[])

    def call(stage, messages, schema):
        assert stage.startswith("edit")
        return {"proposals": [
            {"action": "edit", "target": "r2", "edits": [], "support_groups": [{
                "target_unit": "u5", "alternatives": [[{"record": "r1", "unit": "u1"}, "u4"]],
                "evidence": ["e1"]}]},
            {"action": "edit", "target": "r1", "edits": [{"operation": "retract",
                "target_unit": "u1", "evidence": ["e1"]}]},
        ]}

    result = maintain_event(method, delivery, session="story", request_id="partial",
        date="2031-01-02", recipe="single_pass", model_call=call,
        selected_record_ids=[credential_id])
    assert result["status"] == "incomplete", result
    assert result["receipts"][0]["status"] == "committed"
    assert result["receipts"][1]["reason"] == "EDIT_EXTERNAL_PREMISE_RETRACTED"
    assert service.read(credential_id)["value"]["revision"] == 2
    assert service.read(target_id)["value"] == prior_target
    current = service.read(target_id)
    packs = build_evidence_packs(service, "Why eligible?", "2031-01-02", [], [current])
    projected = project_packs(open_evidence_packs(service, packs), list(range(len(packs))))
    references = projected[0]["support_groups"][0]["external_references"]
    assert {r["status"] for r in references} == {"retracted", "unchanged"}
    assert any(r.get("bound_body_delivered") for r in references)
    assert "Card withdrawn" in str(projected)
    assert "Card valid." in str(projected)  # actual old-version evidence, not current truth
    historical = {**current, "historical_selection": True}
    old_packs = build_evidence_packs(service, "Previously?", "2031-01-01", [], [historical])
    old_bodies = project_packs(open_evidence_packs(service, old_packs), list(range(len(old_packs))))
    assert "Card withdrawn" not in str(old_bodies)
    assert "Card valid." in str(old_bodies)
    assert service.read(credential_id, 1)["value"] == first["value"]


def test_external_source_visibility_and_snapshot_change(case):
    service, method, request, credential_id, target_id = case
    first, second = service.read(credential_id), service.read(target_id)
    card = first["value"]["edit_state"]["units"][0]["unit_id"]
    binding = next(ref for ref in second["value"]["edit_state"]["support_groups"][0][
        "external_units"].values() if ref["unit_id"] == card)
    original_pool = build_evidence_packs(service, "Eligible?", "2031-01-01", [], [second])
    view = request("invalid", "Card is now invalid.", [first])
    receipt = method.apply("story", "invalid", method.decode_proposal({
        "action": "edit", "target": "r1", "edits": [{"operation": "replace",
            "target_unit": "u1", "text": "Card invalid.", "evidence": ["e1"]}],
    }, view["mapping"]))
    assert receipt["ok"]
    assert inspect_external_unit(service, binding)["status"] == "changed"
    assert inspect_external_unit(service, binding, historical=True)["status"] == "historical"
    next_view = request("recheck", "Review the existing support after the card change.",
                        [service.read(credential_id), service.read(target_id)])
    displayed = next_view["packet"]["records"][1]["support_groups"][0]["external_bindings"]
    assert all(ref["bound_revision"] == 1 and ref["delivered_revision"] == 2 for ref in displayed)
    refreshed = open_evidence_packs(service, original_pool, refresh_current=True)
    assert refreshed[0]["external_support_refresh"] == "new_dependency_pool_required"
    references = project_packs(refreshed, list(range(len(refreshed))))[0][
        "support_groups"][0]["external_references"]
    assert "changed" in {ref["status"] for ref in references}
    original_source = first["value"]["edit_state"]["units"][0]["evidence_refs"][0]["source_ref"]
    handle = service.source_fragments(original_source)[0]["fragment_handle"]
    assert service.forget("story", "forget", fragment_handles=[handle])["ok"]
    assert inspect_external_unit(service, binding)["status"] == "unavailable"
    assert not service.read(target_id)["ok"]
    assert not service.read(target_id, 1)["ok"]
