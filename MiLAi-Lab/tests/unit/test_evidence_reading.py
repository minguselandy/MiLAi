"""Evidence packs use actual SQLite ranges, declared relations and one Reader budget."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    pack_candidate,
    project_pack,
    unit_closure,
)
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def service_at(store: SqliteStore, tmp_path: Path) -> MemoryService:
    return MemoryService(store, ("packs", "alice"), "alice", tmp_path / "lock",
                         functional_contract="functional_v1")


def test_exchange_context_is_complete_prefix_bound_and_visibility_aware(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        first = service.capture_user("meeting", "turn:0", "Notify Li about project A.")
        service.capture_assistant("meeting", "turn:1", "Does that include external notices?")
        second = service.capture_user("meeting", "turn:2", "No, those require prior confirmation.")
        service.capture_tool("meeting", "turn:3", "directory", "Li is the internal contact.", None)
        service.capture_user("meeting", "turn:4", "The unrelated lunch is at noon.")
        native = service.search_sources("external notices", tokenization="unicode_v1")
        packs = build_evidence_packs(service, "confirmation", "2030-01-01",
                                     native["source_materials"], [])
        pack = next(p for p in packs if p["focus_source_ranges"][0]["source_ref"]
                    == second["source_ref"])
        projected = project_pack(open_evidence_packs(service, [pack])[0], 0)
        assert [row["role"] for row in projected["evidence"]] == [
            "user", "assistant", "user", "tool"]
        assert "Notify Li" in str(projected) and "No, those" in str(projected)
        assert "lunch" not in str(projected)
        assert first["source_ref"] not in json.dumps(projected)
        service.capture_user("meeting", "turn:5", "LATER_SECRET must never enter the old prefix.")
        expanded = open_evidence_packs(service, [pack], expand_context=True)[0]
        assert "lunch" in expanded["text"] and "LATER_SECRET" not in expanded["text"]
        handle = service.source_fragments(second["source_ref"])[0]["fragment_handle"]
        assert service.forget("meeting", "forget", fragment_handles=[handle])["ok"]
        reopened = open_evidence_packs(service, [pack])[0]
        assert "No, those" not in reopened["text"] and reopened["visibility"] == "partial"
        assert "No, those" not in str(pack_candidate(reopened, 0))


def test_unit_closure_keeps_conditions_and_exceptions_without_unrelated_shared_targets() -> None:
    state = {"units": [{"unit_id": uid} for uid in ["A", "B", "confirm", "exception", "until"]],
             "relations": [
                 {"source_unit": "confirm", "target_unit": "A", "relation_type": "modifies"},
                 {"source_unit": "confirm", "target_unit": "B", "relation_type": "modifies"},
                 {"source_unit": "exception", "target_unit": "A", "relation_type": "overrides"},
                 {"source_unit": "until", "target_unit": "exception", "relation_type": "modifies"},
             ]}
    ids, relations = unit_closure(state, "A")
    assert ids == ["A", "confirm", "exception", "until"]
    assert len(relations) == 3
    assert unit_closure(state, "exception")[0] == ids
    assert "B" in unit_closure(state, "confirm")[0]


def execution_at(root: Path) -> BenchmarkRun:
    run = BenchmarkRun.__new__(BenchmarkRun)
    run.root = root
    run.settings = {"evidence_policy": "question_pack_v1", "reader_target": "original_question_v1",
                    "context_tokens": 7500, "model": {"max_tokens": 100},
                    "source_access": "independent_v1", "memory_view_mode": "direct"}
    run.client = SimpleNamespace(config=SimpleNamespace(max_calls=5))
    run.input_tokens = lambda messages, **_: len(json.dumps(messages, ensure_ascii=False))
    return run


def large_packs(service: MemoryService) -> list[dict[str, Any]]:
    for i in range(4):
        service.capture_user(f"session-{i}", "turn:0", f"TOPIC_{i}: " + "text " * 300)
        service.capture_assistant(f"session-{i}", "turn:1", "Acknowledged.")
    native = service.search_sources("TOPIC_0", tokenization="unicode_v1")
    return build_evidence_packs(service, "TOPIC_0", "2030-01-01", native["source_materials"], [])


def selection(indices: list[int], *, answer: str | None = None, gap: str | None = None,
              context: list[int] | None = None, task: str = "lookup") -> str:
    return json.dumps({"item_indices": indices, "answer": answer,
                       "expand_context": context or [], "gap": gap,
                       "task": task, "candidate_page": 0})


def test_lookup_selects_short_pack_and_stops_with_unread_candidates(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        run = execution_at(tmp_path)
        write_json(tmp_path / "pool.json", {"materials": packs})
        attempts = []

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            assert run.input_tokens(messages) <= 6888
            payload = json.loads(messages[1]["content"])
            attempts.append(payload)
            assert payload["question"] == "TOPIC_0 only, retain any limits."
            if len(attempts) == 1:
                assert payload["memories"] == [] and payload["candidates"]
                return selection([0], gap="Need the original statement and its reply.")
            assert len(payload["memories"]) == 1
            assert payload["unopened_candidates"] == 3
            assert "source_ref" not in str(payload["memories"])
            return selection([], answer="Supported answer.")

        run.call = call
        answer, used = run.answer_material("TOPIC_0 only, retain any limits.", "2030-01-01", "q",
                                           packs, snapshot_id="pool.json",
                                           material_reader=lambda items: run._live_materials(
                                               service, items))
        assert answer == "Supported answer." and len(used) == 1 and len(attempts) == 2
        saved = read_json(tmp_path / "http/q/memory-view.json")
        assert saved["resident_refs"][0]["item_index"] == 0
        assert saved["delivery_plan"]["body_delivered"]


def test_small_direct_pool_has_one_call_and_no_selection(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("short", "turn:0", "The passcode is violet; only for today.")
        packs = build_evidence_packs(service, "passcode", "2030-01-01",
                                     service.search_sources("passcode")["source_materials"], [])
        run = execution_at(tmp_path)
        calls = []

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            assert not kwargs["structured"]
            assert "only for today" in str(messages) and "candidates" not in str(messages)
            calls.append(key)
            return "Violet, only for today."

        run.call = call
        write_json(tmp_path / "pool.json", {"materials": packs})
        result = run.answer_material("Passcode?", "2030-01-01", "q", packs,
                                     snapshot_id="pool.json",
                                     material_reader=lambda items: run._live_materials(
                                         service, items))
        assert result[0] == "Violet, only for today." and calls == ["q"]


def test_semantic_hit_opens_its_conditions_and_actual_supports(tmp_path: Path) -> None:
    from milai_lab.methods.functional_edit_memory import FunctionalEditMemory

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        memory = FunctionalEditMemory(service, len, interface_version="I2")
        other = service.capture_user("story", "old", "Project B notifies Wang.")
        current = service.capture_user("story", "save", "Project A notifies Li after confirmation.")
        memory.context("story", "save", "packs-v1")
        config = {"configurable": {"user_id": "alice", "v13_session": "story",
                                    "v13_turn_id": "save", "v13_config_version": "packs-v1"}}
        a = [service.source_fragments(current["source_ref"])[0]["fragment_handle"]]
        b = [service.source_fragments(other["source_ref"])[0]["fragment_handle"]]
        saved = memory.save_edit(config, "save-op", units=[
            {"text": "Project A notifies Li.", "role": "content", "evidence": a},
            {"text": "Only after confirmation.", "role": "condition", "evidence": a},
            {"text": "Project B notifies Wang.", "role": "content", "evidence": b},
        ], relations=[{"source": 1, "target": 0, "relation_type": "modifies", "evidence": a}])
        assert saved["ok"]
        row = service.read(saved["id"])
        units = row["value"]["edit_state"]["units"]
        row["retrieval_navigation"] = {"unit_id": units[0]["unit_id"], "key_kind": "unit"}
        packs = build_evidence_packs(service, "A notice", "2030-01-01", [], [row])
        assert packs[0]["selected_unit_ids"] == [unit["unit_id"] for unit in units[:2]]
        projected = project_pack(open_evidence_packs(service, packs)[0], 0)
        assert "Project A" in str(projected) and "Only after confirmation" in str(projected)
        assert "Project B" not in str(projected)
        assert {span["source_ref"] for span in packs[0]["revision_evidence"]} == {
            current["source_ref"]}
        assert len(service.read(saved["id"])["value"]["edit_state"]["units"]) == 3


def test_budget_exclusions_return_to_reader_and_empty_retry_does_not_loop(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        run = execution_at(tmp_path)
        run.client.config.max_calls = 4
        calls = []
        write_json(tmp_path / "pool.json", {"materials": packs})

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            payload = json.loads(messages[1]["content"])
            calls.append(payload)
            assert run.input_tokens(messages) <= 6888
            if len(calls) == 1:
                return selection([0, 1, 2, 3],
                                 gap="Need comparison of these reports.", task="range")
            if len(calls) == 2:
                assert payload["excluded_indices"] and payload["task"] == "range"
                assert payload["coverage"] == "retrieved_pool_only_not_full_history"
                return selection(payload["admitted_indices"], gap=None, task="range")
            assert not kwargs["structured"]
            assert "No further evidence was requested" in messages[0]["content"]
            return "Partial answer; some reports did not fit."

        run.call = call
        answer, _ = run.answer_material("Compare all reports", "2030-01-01", "q", packs,
                                        snapshot_id="pool.json",
                                        material_reader=lambda items: run._live_materials(
                                            service, items))
        assert answer.startswith("Partial") and len(calls) == 3
        state = read_json(tmp_path / "http/q/memory-view.json")
        assert state["steps"] == 3 and not state["coverage_complete"]
