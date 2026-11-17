"""Real range/delivery boundaries and permutation-safe object computation."""
import copy
import json

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.compute_profile import ComputeProfile
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import build_evidence_packs, open_evidence_packs
from milai_lab.methods.memory_control import (
    FixedMemoryPolicy,
    MemoryControlState,
    run_memory_control,
)
from milai_lab.methods.memory_object_policy import build_object_head, object_control_texts
from milai_lab.methods.source_ranges import evidence_unit_packs


def test_R2_R3_reopen_exact_units_keep_qualifier_and_directory_is_not_body(tmp_path):
    body = "中🙂 prefix\n\nAlice may ship 14 units.\n\nExcept on Friday: no shipments."
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("compute", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        ref = service.capture_tool("session", "event", "original", body, None)["source_ref"]

        def pool():
            found = service.search_sources("Alice ship", limit=4, include_scope=True)
            return build_evidence_packs(service, "Alice ship", "2026-11-17",
                found["source_materials"], [], evidence_units=True)

        state = MemoryControlState(task={"request": "What may Alice ship on Friday?",
                                         "query_time": "2026-11-17"})
        ops = EvidenceOperations(service, state, load_pool=pool, refresh_call=lambda *_: {},
            fits=lambda _: True, internal_views=False, view_updates=False,
            delivery_selection=True, source_directory_only=True)
        assert body not in json.dumps(state.project(), ensure_ascii=False)
        assert all("content" not in event for event in state.new_events)
        ops.execute(next(a for a in ops.actions(state) if a.kind == "SEARCH"), state)
        candidate = next(c for c in state.pending_candidates if "Alice" in c["excerpt"])
        index = candidate["item_index"]
        assert candidate["evidence_representation"]["level"] == "R2"
        read = next(a for a in ops.actions(state) if a.id == f"read_{index}_observe")
        assert ops.execute(read, state)["ok"]
        assert not state.visible_evidence and state.observed_evidence
        assert "Except on Friday" not in json.dumps(state.observed_evidence)
        expand = next(a for a in ops.actions(state) if a.id == f"context_{index}")
        assert ops.execute(expand, state)["ok"]
        actual = ops.reader_evidence()
        assert body in json.dumps(actual, ensure_ascii=False).replace("\\n", "\n")
        assert ops.observed[index]["evidence_representation"]["level"] == "R3"
        assert controlled_reader_packet(actual, "test")["evidence"] == actual
        restored = EvidenceOperations(service, copy.deepcopy(state), load_pool=pool,
            refresh_call=lambda *_: {}, fits=lambda _: True, internal_views=False,
            view_updates=False, delivery_selection=True, source_directory_only=True,
            checkpoint=ops.checkpoint())
        assert restored.reader_evidence() == actual
        handle = service.source_fragment_range(ref, 0, len(body))["fragment_handle"]
        service.forget("session", "forget", fragment_handles=[handle])
        ops.actions(state)
        assert "Except on Friday" not in json.dumps(state.project())
        assert "Alice may ship" not in json.dumps(ops.reader_evidence())


def test_evidence_units_cover_exact_nonzero_unicode_range_and_do_not_cut_long_paragraph(tmp_path):
    body = "prefix" + "否定不得删除。" * 100 + "\n\nEND condition."
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("units", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        ref = service.capture_tool("s", "e", "original", body, None)["source_ref"]
        material = service.read_source_materials([{"kind": "original_source", "id": "source",
            "session_id": "s", "turn_range": [4, 5], "source_ranges": [{
                "source_ref": ref, "source_revision": 1, "start": 6, "end": len(body)}]}])[0]
        units = evidence_unit_packs(material)
        assert len(units) == 2
        opened = open_evidence_packs(service, units)
        pieces = [json.loads(item["text"])[0]["content"] for item in opened]
        assert "".join(pieces) == body[6:]
        assert len(pieces[0]) > 512
        assert units[0]["source_ranges"][0]["start"] == 6
        expanded = open_evidence_packs(service, [units[1]], expand_context=True)[0]
        assert json.loads(expanded["text"])[0]["content"] == body[6:]


def test_R3_budget_failure_preserves_R2_delivery_but_records_actual_observation(tmp_path):
    body = "Alice quota is fourteen.\n\n" + "Context includes an exception. " * 200
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("budget", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_tool("s", "e", "original", body, None)

        def pool():
            found = service.search_sources("Alice quota", limit=4)
            return build_evidence_packs(service, "Alice quota", "2026-11-17",
                                        found["source_materials"], [], evidence_units=True)

        state = MemoryControlState(task={"request": "Alice quota", "query_time": "2026-11-17"})
        ops = EvidenceOperations(service, state, load_pool=pool, refresh_call=lambda *_: {},
            fits=lambda items: len(json.dumps(controlled_reader_packet(items, "policy"))) < 1500,
            internal_views=False, view_updates=False, source_directory_only=True,
            delivery_selection=True)
        ops.execute(next(a for a in ops.actions(state) if a.kind == "SEARCH"), state)
        index = next(c["item_index"] for c in state.pending_candidates
                     if c["excerpt"].startswith("Alice quota"))
        assert ops.execute(next(a for a in ops.actions(state) if a.id == f"read_{index}"), state)[
            "ok"]
        before = copy.deepcopy(state.visible_evidence)
        result = ops.execute(next(a for a in ops.actions(state) if a.id == f"context_{index}"),
                             state)
        assert result["ok"] is False and result["status"] == "material_budget_exhausted"
        assert state.visible_evidence == before
        assert state.observed_materials[0]["selected"] is False
        assert state.observed_materials[0]["evidence_representation"]["level"] == "R3"
        assert "Context includes an exception" in json.dumps(state.observed_evidence)
        assert "Context includes an exception" not in json.dumps(ops.reader_evidence())


def test_adjacent_source_context_opens_real_role_version_ranges_and_excludes_outside_pool(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("adjacent", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        refs = [service.capture_user("s", "prior", "The quota concerns only Alice.")["source_ref"],
                service.capture_tool("s", "current", "registry", "The quota is 14.", None)[
                    "source_ref"],
                service.capture_user("s", "next", "Except on Friday: do not ship.")["source_ref"]]
        service.capture_user("other", "outside", "Outside pool secret must not appear.")
        bodies = [service.source(ref)["content"] for ref in refs]
        material = service.read_source_materials([{"kind": "original_source", "id": "captured",
            "session_id": "s", "turn_range": [7, 10], "source_ranges": [
                {"source_ref": ref, "source_revision": 1, "start": 0, "end": len(body)}
                for ref, body in zip(refs, bodies, strict=True)]}])[0]
        units = evidence_unit_packs(material, context_turn_radius=1)
        middle = units[1]
        r2 = open_evidence_packs(service, [middle])[0]
        assert [t["content"] for t in json.loads(r2["text"])] == [bodies[1]]
        r3 = open_evidence_packs(service, [middle], expand_context=True)[0]
        actual = json.loads(r3["text"])
        assert [t["content"] for t in actual] == bodies
        assert [t["role"] for t in actual] == ["user", "tool", "user"]
        assert [t["source_ref"] for t in actual] == refs
        assert all(t["source_revision"] == 1 for t in actual)
        assert r3["turn_range"] == [7, 10] and r2["turn_range"] == [8, 9]
        assert "Outside pool secret" not in r3["text"]
        handle = service.source_fragment_range(refs[2], 0, len(bodies[2]))["fragment_handle"]
        service.forget("s", "forget", fragment_handles=[handle])
        current = open_evidence_packs(service, [middle], expand_context=True)[0]
        assert bodies[2] not in current["text"]
        assert service.source(refs[0]) is not None


def test_object_projection_excludes_offline_data_but_retains_all_public_collections():
    online = {"observation": MemoryControlState(task={"request": "Who?"},
        pending_candidates=[{"item_index": 0, "excerpt": "Alice; not Bob"}],
        observed_materials=[{"item_index": 7, "selected": False}],
        observed_evidence=[{"label": "e7", "content": "actual observation"}]).project(),
        "actions": [{"id": "read", "kind": "READ", "target": "candidate", "parameters": {
            "index": 0, "observe_only": True}}, {"id": "handoff", "kind": "HANDOFF",
            "target": "Reader", "parameters": {}}]}
    before = copy.deepcopy(online)
    objects, actions = object_control_texts({**online, "offline_only": {"answer": "SECRET"},
        "offline_supervision": {"answer": "SECRET"}, "group_id": "SECRET"})
    assert "SECRET" not in str((objects, actions))
    assert len(objects) == 5 and '"selected":false' in str(objects)
    renamed = copy.deepcopy(online)
    renamed["actions"].reverse()
    for i, action in enumerate(renamed["actions"]):
        action["id"] = "renamed" + str(i)
    assert object_control_texts(renamed) == (objects, actions[::-1])
    assert online == before


@pytest.mark.parametrize("architecture", ["object_mlp", "latent_pointer"])
def test_object_head_ragged_binding_order_padding_and_gradients(architecture):
    torch = pytest.importorskip("torch")
    torch.set_num_threads(2)
    torch.manual_seed(19)
    head = build_object_head(8, architecture=architecture, width=12, heads=3,
                             slots=3, blocks=2, ffn_width=24, dropout=0.)
    state = torch.randn(2, 5, 8)
    state[0, 4] = 0
    actions = torch.randn(5, 8)
    owners = torch.tensor([0, 0, 1, 1, 1])
    head.eval()
    scores = head(state, actions, owners)
    reordered = state[:, [0, 1, 3, 2, 4]]
    permutation = torch.tensor([1, 0, 4, 2, 3])
    assert torch.allclose(head(reordered, actions[permutation], owners), scores[permutation],
                          atol=2e-7)
    padded = torch.cat((state, torch.zeros(2, 3, 8)), dim=1)
    assert torch.allclose(head(padded, actions, owners), scores, atol=2e-7)
    scores.square().sum().backward()
    assert sum(float(p.grad.abs().sum()) for p in head.parameters() if p.grad is not None) > 0
    if architecture == "latent_pointer":
        assert head.cross[0].in_proj_weight.grad.abs().sum() > 0
        assert head.pointer.in_proj_weight.grad.abs().sum() > 0


def test_profile_keeps_inclusive_hierarchy_failure_and_real_selection():
    profile = ComputeProfile()
    class Operations:
        def actions(self, state):
            from milai_lab.methods.memory_control import MemoryAction
            return [MemoryAction("handoff", "HANDOFF", "Reader")]

    with profile.span("retrieval"):
        result = run_memory_control(MemoryControlState(task={}), FixedMemoryPolicy(),
                                    Operations(), profile=profile)
    assert result["trace"][0]["selection_mode"] == "only_available_action"
    intervals = profile.report()["intervals"]
    assert intervals[0]["parent"] is None
    assert all(e["parent"] == 0 for e in intervals[1:])
    assert intervals[0]["wall_seconds"] >= sum(e["wall_seconds"] for e in intervals[1:])
    with pytest.raises(ValueError, match="original failure"), profile.span("failing"):
        raise ValueError("original failure")
    assert profile.report()["intervals"][-1]["status"] == "FAILED"
