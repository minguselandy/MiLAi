"""Real parent lifecycle and capacity through the common executor, not a second loop."""
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import project_packs
from milai_lab.methods.memory_control import MemoryControlState, run_memory_control
from milai_lab.methods.query_structure import build_query_structure, cached_structure


@pytest.fixture
def world(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("unit-delivery", "alice"), "alice", tmp_path / "lock",
            functional_contract="functional_v1",
            clock=lambda: datetime(2032, 5, 2, tzinfo=UTC))
        rules = service.capture_user("s", "rules",
            "Entry requires training and either a permit or a waiver with sponsor approval.")[
                "source_ref"]
        fee = service.capture_tool("s", "fee", "fees.preview", '{"fee":42,"paid":null}',
                                   None)["source_ref"]
        noise = service.capture_user("s", "room", "tentative preference " * 2000)["source_ref"]

        def build(messages, schema):
            aliases = [x["id"] for x in json.loads(messages[1]["content"])["sources"]]
            return {"scope": "Entry conditions, fee preview, and unrelated preferences",
                "nodes": [
                    {"id": "n0", "text": "Training completion is unknown.", "kind": "uncertain",
                     "evidence": [aliases[0]]},
                    {"id": "n1", "text": "Permit valid only until 2032-05-03.", "kind": "reported",
                     "evidence": [aliases[0]], "temporal": "Not valid after the literal date."},
                    {"id": "n2", "text": "Waiver status is unknown.", "kind": "uncertain",
                     "evidence": [aliases[0]]},
                    {"id": "n3", "text": "Sponsor approval is not established.",
                     "kind": "uncertain", "evidence": [aliases[0]]},
                    {"id": "n4", "text": "Entry needs training AND (permit OR waiver AND sponsor).",
                     "kind": "inferred", "evidence": [aliases[0]]},
                    {"id": "n5", "text": "Fee preview is 42, payment remains unknown.",
                     "kind": "reported", "evidence": [aliases[1]]},
                    {"id": "n6", "text": "tentative preference " * 2000,
                     "kind": "reported", "evidence": [aliases[2]]}],
                "rules": [{"id": "g0", "target": "n4", "all": ["n0"],
                           "any": [["n1"], ["n2", "n3"]], "evidence": [aliases[0]]}],
                "remove": [], "remove_rules": [], "unresolved": ["No executed entry confirmed."]}

        view, _ = build_query_structure(service, "Entry and fee?", "2032-05-02",
            [rules, fee, noise], policy="incremental", call=build)
        assert view is not None
        yield service, view, (rules, fee, noise)


def make_ops(service, *, units=True, saved=None, state=None):
    state = state or MemoryControlState(task={"request": "Entry and fee?",
        "query_time": "2032-05-02", "calendar_context": "UTC"})
    options = {"current": [["n0"], ["n5"]]} if units else None
    ops = EvidenceOperations(service, state, load_pool=lambda: [],
        refresh_call=lambda *_: pytest.fail("This fixture cannot refresh through a model"),
        fits=lambda evidence: len(json.dumps(controlled_reader_packet(evidence, "policy"),
                                             ensure_ascii=False)) <= 4000,
        view_updates=False, delivery_selection=True, source_directory_only=True,
        view_unit_selections=options, checkpoint=saved)
    return state, ops


def choose(ops, state, *, nodes=None, full=False):
    return next(a for a in ops.actions(state) if a.kind == "USE_VIEW"
        and not a.parameters.get("replace_delivery")
        and ("view_nodes" not in a.parameters if full else
             nodes <= set(a.parameters.get("view_nodes", []))))


def test_partial_delivery_closes_all_rules_then_monotonically_expands(world):
    service, view, _ = world
    original = copy.deepcopy(cached_structure(service))
    state, ops = make_ops(service)
    assert not ops.execute(choose(ops, state, full=True), state)["ok"]
    assert ops.reader_evidence() == []
    first = choose(ops, state, nodes={"n0"})
    assert first.parameters["view_revision"] == view["revision"]
    assert ops.execute(first, state)["ok"]
    packet = ops.reader_evidence()[0]
    assert list(packet["interpretation"]["nodes"]) == [f"n{i}" for i in range(5)]
    assert packet["interpretation"]["rules"] == view["structure"]["rules"]
    assert packet["unit_projection"]["partial"] is True
    assert packet["unit_projection"]["semantic_completeness"] == "not_certified"
    assert "n6" not in packet["interpretation"]["nodes"]
    second = choose(ops, state, nodes={"n5"})
    assert set(second.parameters["view_nodes"]) == {f"n{i}" for i in range(6)}
    assert ops.execute(second, state)["ok"]
    expanded = ops.reader_evidence()[0]
    assert list(expanded["interpretation"]["nodes"]) == [f"n{i}" for i in range(6)]
    assert len(ops.opened) == 1
    assert all(a.kind != "USE_VIEW" or a.parameters.get("replace_delivery")
               for a in ops.actions(state))
    assert cached_structure(service) == original


def test_unselected_parent_revoke_tombstones_and_cannot_be_hidden_by_projection(world):
    service, _, (_, _, noise) = world
    state, ops = make_ops(service)
    action = choose(ops, state, nodes={"n0"})
    assert ops.execute(action, state)["ok"]
    fragments = [x["fragment_handle"] for x in service.source_fragments(noise)]
    assert service.forget("s", "withdraw-omitted-parent", fragment_handles=fragments)["ok"]
    packet = ops.reader_evidence()[0]
    assert packet["visibility"] == "support_unavailable" and "interpretation" not in packet
    assert not any(a.kind == "USE_VIEW" for a in ops.actions(state))
    unavailable = ops.execute(action, state)
    assert not unavailable["ok"] and unavailable["status"] == "support_unavailable"


def test_renderer_parent_revision_and_action_node_bindings_cannot_drift(world):
    service, _, _ = world
    state, ops = make_ops(service)
    action = choose(ops, state, nodes={"n0"})
    with pytest.raises(ValueError, match="different parent revision"):
        ops.execute(replace(action, parameters={**action.parameters, "view_revision": 99}), state)
    with pytest.raises(ValueError, match="valid monotone"):
        ops.execute(replace(action, parameters={**action.parameters, "view_nodes": ["missing"]}),
                    state)
    assert ops.execute(action, state)["ok"]
    raw = copy.deepcopy(next(iter(ops.opened.values())))
    raw["reader_unit_selection"]["parent_revision"] += 1
    with pytest.raises(ValueError, match="different parent View"):
        project_packs([raw], [-1])
    with pytest.raises(ValueError, match="valid monotone"):
        ops.execute(replace(action, parameters={**action.parameters, "view_nodes": ["n5"]}), state)


def test_checkpoint_retains_partial_precision_attempts_and_rejects_changed_menu(world):
    service, _, _ = world
    state, ops = make_ops(service)
    result = ops.execute(choose(ops, state, full=True), state)
    assert result["status"] == "material_budget_exhausted"
    assert ops.execute(choose(ops, state, nodes={"n0"}), state)["ok"]
    saved = json.loads(json.dumps(ops.checkpoint()))
    restored_state, restored = make_ops(service, saved=saved,
        state=MemoryControlState(**copy.deepcopy(state.project())))
    assert restored.checkpoint() == ops.checkpoint()
    assert restored.actions(restored_state) == ops.actions(state)
    assert restored.reader_evidence() == ops.reader_evidence()
    with pytest.raises(ValueError, match="CHECKPOINT_CONFIGURATION_CHANGED"):
        make_ops(service, units=False, saved=saved)


def test_default_path_and_complete_parent_upgrade_are_unchanged(world):
    service, _, _ = world
    state, ops = make_ops(service, units=False)
    assert "view_unit_selections" not in ops.checkpoint_configuration
    assert not any("view_nodes" in a.parameters for a in ops.actions(state))
    assert not ops.execute(choose(ops, state, full=True), state)["ok"]
    state, ops = make_ops(service)
    ops.fits = lambda _: True
    assert ops.execute(choose(ops, state, nodes={"n0"}), state)["ok"]
    assert ops.execute(choose(ops, state, full=True), state)["ok"]
    full = ops.reader_evidence()[0]
    assert "unit_projection" not in full and "n6" in full["interpretation"]["nodes"]


def test_single_common_control_loop_records_actual_partial_and_expansion(world):
    service, _, _ = world
    state, ops = make_ops(service)

    class Policy:
        def choose(self, state, actions):
            wanted = "n0" if not state.visible_evidence else "n5"
            matching = [a for a in actions if a.kind == "USE_VIEW"
                and not a.parameters.get("replace_delivery")
                and wanted in a.parameters.get("view_nodes", [])]
            return matching[0].id if matching else "handoff"

    result = run_memory_control(state, Policy(), ops, max_steps=3)
    assert result["reason"] == "policy_handoff"
    assert [e["step"] for e in result["trace"]] == [0, 1, 2]
    assert [e["selected"] for e in result["trace"]][-1] == "handoff"
    assert len(ops.reader_evidence()[0]["interpretation"]["nodes"]) == 6


def test_oversized_whole_connected_component_is_rejected_without_truncation(world):
    service, _, (_, _, noise) = world
    parent = copy.deepcopy(cached_structure(service))
    alias = next(k for k, v in parent["source_bindings"].items() if v["source_ref"] == noise)
    parent["structure"]["rules"]["g1"] = {"target": "n4", "all": ["n6"],
        "any": [[]], "evidence": [alias]}
    service.store.put((*service.namespace, "query_structure_v1"), "current", parent, index=False)
    state, ops = make_ops(service)
    result = ops.execute(choose(ops, state, nodes={"n0"}), state)
    assert not result["ok"] and result["status"] == "material_budget_exhausted"
    assert ops.reader_evidence() == []
    observed = next(iter(ops.observed.values()))
    assert "n6" in observed["reader_unit_selection"]["nodes"]
    assert observed["structure"]["nodes"]["n6"] == parent["structure"]["nodes"]["n6"]
