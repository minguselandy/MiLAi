"""Offline preferences cannot change inputs or turn unreviewed actions into gold."""
import copy

import pytest

from milai_lab.methods.retrieval_supervision import annotate_decisions


def test_review_masks_and_inputs_are_preserved_without_teacher_imitation():
    rows = [{"state": {"task": {"retrieval_request": {"query": "first saved version"}}},
             "questions": {"next": {"criteria": {"read": "READ", "return": "HANDOFF"}}},
             "gold": {}, "metadata": {"event_id": str(i), "selected_teacher_action": "read"}}
            for i in range(3)]
    rows.append({**copy.deepcopy(rows[0]), "metadata": {"event_id": "forced"},
                 "questions": {"next": {"criteria": {"return": "HANDOFF"}}}})
    original = copy.deepcopy(rows)
    result = annotate_decisions(rows, [
        {"event_id": "0", "preferred_actions": ["return"], "basis": "Actual revision1 opened"},
        {"event_id": "1", "preferred_actions": [], "basis": "Generated view not adjudicated"},
        {"event_id": "forced", "preferred_actions": ["return"], "basis": "Only option"}])
    assert rows == original
    assert result[0]["gold"]["next"]["probabilities"] == {"read": 0.0, "return": 1.0}
    assert all(not row["gold"] for row in result[1:])
    assert [r["state"] for r in result] == [r["state"] for r in rows]
    assert [r["questions"] for r in result] == [r["questions"] for r in rows]
    with pytest.raises(ValueError, match="outside"):
        annotate_decisions(rows, [{"event_id": "0", "preferred_actions": ["invented"]}])


def test_source_preferences_add_missing_material_fit_budget_and_skip_redundant_search(tmp_path):
    from langgraph.store.sqlite import SqliteStore

    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.evidence_reading import build_evidence_packs, project_packs
    from milai_lab.methods.intent_retrieval import material_binding
    from milai_lab.methods.memory_control import MemoryControlState
    from milai_lab.methods.memory_control_learning import decision_example
    from milai_lab.methods.retrieval_supervision import (
        original_binding_material,
        original_witness_preferences,
    )

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("review", "owner"), "owner", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("a", "1", "Report A is unrelated.")
        target = service.capture_user(
            "b", "1", "Report B contains the required value.")["source_ref"]
        state = MemoryControlState(task={"request": "report", "query_time": ""},
                                   budget={"max_return_tokens": 10000,
                                           "remaining_control_steps": 8})

        def pool():
            native = service.search_sources("report", tokenization="unicode_v1")
            return build_evidence_packs(service, "report", "", native["source_materials"], [])

        packs = pool()
        ops = EvidenceOperations(service, state, load_pool=pool,
                                 search_pool=lambda _query, count: packs[:count],
                                 search_batch_sizes=(1, 2), refresh_call=lambda *_: {},
                                 fits=lambda _: True)
        sources = {s["event_id"]: s for s in service.sources()}

        def example():
            from dataclasses import asdict

            return decision_example({"before": state.project(),
                "actions": [asdict(a) for a in ops.actions(state)]}, {"event_id": "call/0",
                    "actual_bindings": {
                        "candidate_materials": [material_binding(m) for m in ops.materials],
                        "opened_materials": {str(i): material_binding(m)
                                             for i, m in ops.opened.items()},
                        "known_materials": []}})

        before_search = example()
        ops.execute(next(a for a in ops.actions(state) if a.id == "search_0_2"), state)
        candidates = [material_binding(m) for m in ops.materials]
        assert original_witness_preferences(before_search, proofs=[{target}], sources=sources,
            return_key="snapshot", token_count=len,
            observed_search=("search_0_2", candidates))[0] == ["search_0_2"]
        row = example()
        preferred, status = original_witness_preferences(row, proofs=[{target}], sources=sources,
            return_key="snapshot", token_count=len,
            observed_search=("search_0_1", candidates))
        target_index = next(i for i, m in enumerate(ops.materials)
                            if target in {s["source_ref"] for s in m["source_ranges"]})
        assert preferred == [f"read_{target_index}"]
        assert status == "reviewed_missing_original_progress"
        assert "refresh_view" not in preferred
        assert original_witness_preferences(row, proofs=[set()], sources=sources,
            return_key="snapshot", token_count=len)[0] == []
        row["state"]["budget"]["max_return_tokens"] = 1
        assert original_witness_preferences(row, proofs=[{target}], sources=sources,
            return_key="snapshot", token_count=len)[0] == []
        ops.execute(next(a for a in ops.actions(state) if a.id == preferred[0]), state)
        reconstructed = original_binding_material(
            material_binding(ops.opened[target_index]), sources)
        assert project_packs([reconstructed], [target_index]) == state.visible_evidence
        assert original_witness_preferences(example(), proofs=[{target}], sources=sources,
            return_key="snapshot", token_count=len)[0] == ["handoff"]
