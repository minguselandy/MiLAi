"""Evidence packs use actual SQLite ranges, declared relations and one Reader budget."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    pack_candidate,
    project_pack,
    project_packs,
    unit_closure,
)
from milai_lab.runners.edit_benchmarks import BenchmarkRun


@pytest.mark.parametrize("max_calls,expected_complete", [(10, True), (3, False)])
@pytest.mark.parametrize("classify_task", [False, True])
def test_range_aggregation_covers_chunks_or_reports_the_unread_remainder(
    tmp_path: Path, max_calls: int, expected_complete: bool, classify_task: bool,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        service.capture_user("future", "turn:0", "FUTURE_TOPIC_99 must not enter the saved pool.")
        run = execution_at(tmp_path)
        run.settings["evidence_selection_policy"] = (
            "range_aggregate_v2" if classify_task else "range_aggregate_v1")
        run.client.config.max_calls = max_calls
        write_json(tmp_path / "pool.json", {"materials": packs})
        calls = []

        def call(key, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            calls.append(key)
            assert run.input_tokens(messages) <= 6888
            assert "FUTURE_TOPIC_99" not in json.dumps(messages)
            if payload.get("response_schema", {}).get("title") == "reader_task_v1":
                assert "memories" not in payload and "candidates" not in payload
                return json.dumps({"task": "range"})
            if payload.get("chunk_only"):
                facts = []
                for material in payload["memories"]:
                    for number in set(re.findall(r"TOPIC_(\d+)", json.dumps(material))):
                        facts.append({"text": f"TOPIC_{number} is one event.",
                                      "source_indices": [int(material["label"][1:])]})
                return json.dumps({"facts": facts, "unresolved": []})
            if "range_aggregation" not in payload:
                assert payload["task"] is None
                return selection([0], gap="Count the whole captured range.", task="range")
            coverage = payload["range_aggregation"]
            assert coverage["summary_coverage"]["complete"] is expected_complete
            assert coverage["planned_chunks"] > 1
            topics = set(re.findall(r"TOPIC_(\d+)", json.dumps(payload["memories"])))
            assert (topics == {"0", "1", "2", "3"}) is expected_complete
            assert all(m["kind"] == "range_summary" for m in payload["memories"])
            return "Four events." if expected_complete else "Partial range only."

        run.call = call
        answer, _ = run.answer_material("Count all TOPIC events", "2030-01-01", "q", packs,
            snapshot_id="pool.json",
            material_reader=lambda items: run._live_materials(service, items))
        assert answer == ("Four events." if expected_complete else "Partial range only.")
        assert len(calls) <= max_calls
        state = read_json(tmp_path / "http/q/memory-view.json")
        assert state["coverage_complete"] is expected_complete
        previous = len(calls)
        run.answer_material("Count all TOPIC events", "2030-01-01", "q", packs,
            snapshot_id="pool.json",
            material_reader=lambda items: run._live_materials(service, items))
        assert len(calls) == previous


def test_range_summaries_do_not_reveal_a_source_forgotten_after_mapping(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        run = execution_at(tmp_path)
        run.settings["evidence_selection_policy"] = "range_aggregate_v1"
        run.client.config.max_calls = 10
        write_json(tmp_path / "pool.json", {"materials": packs})
        maps = 0

        def call(key, messages, **kwargs):
            nonlocal maps
            payload = json.loads(messages[1]["content"])
            if payload.get("chunk_only"):
                indices = kwargs["response_format"]["json_schema"]["schema"][
                    "properties"]["facts"]["items"]["properties"]["source_indices"]["items"]["enum"]
                maps += 1
                secret = maps == 1
                if secret:
                    ref = packs[indices[0]]["source_ranges"][0]["source_ref"]
                    handle = service.source_fragments(ref)[0]["fragment_handle"]
                    assert service.forget("forget", "0", fragment_handles=[handle])["ok"]
                return json.dumps({"facts": [{
                    "text": "SECRET_MAPPED_FACT" if secret else "Visible.",
                                              "source_indices": indices}],
                                   "unresolved": ["SECRET_MAPPED_GAP"] if secret else []})
            if "range_aggregation" not in payload:
                return selection([0], gap="Need all topics.", task="range")
            assert "SECRET_MAPPED" not in json.dumps(messages)
            assert payload["range_aggregation"]["source_unavailable_chunks"] == [0]
            assert not payload["range_aggregation"]["summary_coverage"]["complete"]
            return "A source is no longer available; only a partial result is supported."

        run.call = call
        answer, _ = run.answer_material("Count topics", "2030-01-01", "q", packs,
            snapshot_id="pool.json",
            material_reader=lambda items: run._live_materials(service, items))
        assert "partial" in answer and maps > 1


def test_summary_overflow_keeps_raw_and_summary_coverage_separate(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        run = execution_at(tmp_path)
        run.settings["evidence_selection_policy"] = "range_aggregate_v1"
        run.client.config.max_calls = 10
        write_json(tmp_path / "pool.json", {"materials": packs})

        def call(key, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            if payload.get("chunk_only"):
                indices = [int(m["label"][1:]) for m in payload["memories"]]
                return json.dumps({"facts": [{"text": "Long fact " * 900,
                                              "source_indices": indices}], "unresolved": []})
            if "range_aggregation" not in payload:
                return selection([0], gap="Need all topics.", task="range")
            assert payload["range_aggregation"]["raw_input_coverage"]["complete"]
            assert not payload["range_aggregation"]["summary_coverage"]["complete"]
            assert run.input_tokens(messages) <= 6888
            return "Mapped facts exceed final capacity; no exact total is justified."

        run.call = call
        answer, _ = run.answer_material("Count topics", "2030-01-01", "q", packs,
            snapshot_id="pool.json",
            material_reader=lambda items: run._live_materials(service, items))
        assert "no exact total" in answer
        state = read_json(tmp_path / "http/q/memory-view.json")
        assert state["range_aggregation"]["unpresented_chunks"]


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


@pytest.mark.parametrize("reported_at", ["1998-03-14", "2041-07-09T10:00:00+08:00", None])
def test_source_and_semantic_packs_distinguish_report_and_storage_clocks(
    tmp_path: Path, reported_at: str | None,
) -> None:
    from milai_lab.methods.edit_features import EditFeatures
    from milai_lab.methods.edit_memory import EditMemory

    with SqliteStore.from_conn_string(str(tmp_path / "clocks.sqlite")) as store:
        service = service_at(store, tmp_path)
        source = service.capture_user("story", "entry", "The desk is open.",
                                      occurred_at=reported_at, calendar_context="Asia/Shanghai")
        service.bind_public_turn("story", "entry", source["source_ref"],
                                 config_version="clock-test", phase="start")
        method = EditMemory(service, "M", interface_version="I2",
                            features=EditFeatures(bound_references=True, source_metadata=True))
        request = method.writer_request(method.prepare([source["source_ref"]], ""))
        saved = method.apply("story", "entry", method.decode_proposal({
            "action": "create", "clauses": [{"text": "The desk is open.",
                "conditions": [], "evidence": ["e1"],
                "assertion": {"source_evidence": "e1", "kind": "reported"}}],
        }, request["mapping"]))
        assert saved["ok"]
        original_source = service.source(source["source_ref"])
        original_record = service.read(saved["id"])
        native = service.search_sources("desk", include_scope=True)
        packs = build_evidence_packs(service, "Is the desk open?", "2041-07-09",
                                     native["source_materials"], [original_record])
        projected = project_packs(open_evidence_packs(service, packs), list(range(len(packs))))
        evidence = [e for pack in projected for e in pack["evidence"]]
        assertions = [u["assertion"] for pack in projected for u in pack.get("units", [])]
        assert evidence and assertions
        for value in [*evidence, *assertions]:
            assert value["reported_at"] == reported_at
            assert value["captured_at"] == original_source["observed_at"]
            assert value["captured_at"] != reported_at
            assert not {"occurred_at", "observed_at", "report_time"}.intersection(value)
        assert sum(bool(pack.get("reused_sources")) for pack in projected) >= 1
        assert service.source(source["source_ref"]) == original_source
        assert service.read(saved["id"]) == original_record


def test_expanded_hits_share_exact_parent_body_without_merging_distinct_sources(
    tmp_path: Path,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        for session in ("first", "independent-copy"):
            service.capture_user(session, "turn:0", "Project A uses the amber marker.")
            service.capture_assistant(session, "turn:1", "Does this include external notices?")
            service.capture_user(session, "turn:2", "No. External notices require confirmation.")
        native = service.search_sources("marker", include_scope=True)
        packs = build_evidence_packs(service, "marker", "2030-01-01",
                                     native["source_materials"], [])
        first = [item for item in packs if item["session_id"] == "first"]
        other = next(item for item in packs if item["session_id"] == "independent-copy")
        expanded = open_evidence_packs(service, [*first, other], expand_context=True)
        projected = project_packs(expanded, [4, 8, 12])
        assert len(projected) == 2
        assert projected[0]["label"] == "e4" and projected[0]["also_selected_as"] == ["e8"]
        assert projected[1]["label"] == "e12" and "also_selected_as" not in projected[1]
        assert [x["content"] for x in projected[0]["evidence"]] == [
            x["content"] for x in projected[1]["evidence"]]
        assert len(projected[0]["evidence"]) == 3
        assert projected[0]["evidence"][2]["content"].startswith("No.")
        assert projected[0]["evidence"][0]["source"] != projected[1]["evidence"][0]["source"]
        # Ordinary overlapping hits are not identical full-parent ranges.
        overlapping = project_packs(open_evidence_packs(service, first), [4, 8])
        assert len(overlapping) == 2
        assert sum(len(item["evidence"]) for item in overlapping) == 3
        assert overlapping[1]["reused_sources"] or overlapping[0].get("reused_sources")
        turn = json.loads(expanded[0]["text"])[0]
        semantic = {"kind": "semantic_view", "revision": 1, "scope": {},
                    "matter_description": "Marker", "support_turns": [turn],
                    "applicability": {"units": [{"unit_id": "amber", "text": "A uses amber.",
                        "role": "content", "assertion": {"source_ref": turn["source_ref"],
                            "source_revision": 1, "kind": "reported"}}], "relations": []}}
        combined = project_packs([expanded[0], semantic], [4, 20])
        source = combined[0]["evidence"][0]["source"]
        assert combined[1]["evidence"] == [] and combined[1]["reused_sources"] == [source]
        assert combined[1]["units"][0]["assertion"]["source_ref"] == source
        semantic["support_turns"] = [{**turn, "source_revision": 2}]
        different_version = project_packs([expanded[0], semantic], [4, 20])
        assert different_version[1]["evidence"][0]["source"] != source
        assert different_version[1]["units"][0]["assertion"]["source_ref"] == "support_not_opened"
        semantic["support_turns"] = []
        unopened = project_packs([expanded[0], semantic], [4, 20])
        assert unopened[1]["units"][0]["assertion"]["source_ref"] == "support_not_opened"
        source = first[0]["source_ranges"][0]["source_ref"]
        handle = service.source_fragments(source)[0]["fragment_handle"]
        assert service.forget("first", "hide", fragment_handles=[handle])["ok"]
        hidden = open_evidence_packs(service, first, expand_context=True)
        assert all(item["visibility"] == "partial" for item in hidden)
        assert len(project_packs(hidden, [4, 8])) == 2


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
    native = service.search_sources("TOPIC_0", tokenization="unicode_v1", include_scope=True)
    return build_evidence_packs(service, "TOPIC_0", "2030-01-01", native["source_materials"], [],
                                 source_scope=native["source_scope"])


def selection(indices: list[int], *, answer: str | None = None, gap: str | None = None,
              context: list[int] | None = None, task: str = "lookup") -> str:
    return json.dumps({"item_indices": indices, "answer": answer,
                       "expand_context": context or [], "gap": gap,
                       "task": task, "candidate_page": 0})


@pytest.mark.parametrize("selection_thinking", [None, False])
@pytest.mark.parametrize("repeat_target", [False, True])
@pytest.mark.parametrize("aggregate_ranges", [False, True])
@pytest.mark.parametrize("classify_task", [False, True])
def test_lookup_selects_short_pack_and_stops_with_unread_candidates(
    tmp_path: Path, selection_thinking: bool | None, repeat_target: bool, aggregate_ranges: bool,
    classify_task: bool,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        run = execution_at(tmp_path)
        if aggregate_ranges:
            run.settings["evidence_selection_policy"] = "range_aggregate_v1"
        if classify_task:
            run.settings["evidence_selection_policy"] = (
                "range_aggregate_v2" if aggregate_ranges else "task_first_v1")
        run.settings["stage_enable_thinking"] = {"reader": True}
        if selection_thinking is not None:
            run.settings["stage_enable_thinking"]["select"] = selection_thinking
        write_json(tmp_path / "pool.json", {"materials": packs})
        attempts = []

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            assert run.input_tokens(messages) <= 6888
            payload = json.loads(messages[1]["content"])
            if payload.get("response_schema", {}).get("title") == "reader_task_v1":
                assert "memories" not in payload and "candidates" not in payload
                assert kwargs["enable_thinking"] is (True if selection_thinking is None else False)
                return json.dumps({"task": "lookup"})
            attempts.append(payload)
            assert payload["question"] == "TOPIC_0 only, retain any limits."
            if len(attempts) == 1:
                assert payload["task"] == ("lookup" if classify_task else None)
                assert kwargs["enable_thinking"] is (True if selection_thinking is None else False)
                assert payload["memories"] == [] and payload["candidates"]
                assert payload["response_schema"]["properties"]["answer"] == {"type": "null"}
                assert kwargs["response_format"]["json_schema"]["schema"]["properties"][
                    "answer"] == {"type": "null"}
                return selection([0, 0] if repeat_target else [0],
                    context=[0, 0] if repeat_target else [],
                    gap="Need the original statement and its reply.")
            assert kwargs["enable_thinking"] is True
            assert payload["task"] == "lookup"
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
        assert saved["steps"] == 2 + int(classify_task)
        assert [ref["item_index"] for ref in saved["resident_refs"]] == [0]
        assert saved["context_indices"] == ([0] if repeat_target else [])
        assert saved["delivery_plan"]["body_delivered"]


@pytest.mark.parametrize("policy", ["standard", "task_first_v1", "range_aggregate_v2"])
def test_small_direct_pool_has_one_call_and_no_selection(tmp_path: Path, policy: str) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("short", "turn:0", "The passcode is violet; only for today.")
        native = service.search_sources("passcode", include_scope=True)
        packs = build_evidence_packs(service, "passcode", "2030-01-01",
                                     native["source_materials"], [],
                                     source_scope=native["source_scope"])
        run = execution_at(tmp_path)
        run.settings["evidence_selection_policy"] = policy
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
            assert payload["excluded_indices"]
            assert not payload["range_coverage"]["complete"]
            assert payload["coverage"] == "retrieved_pool_only_not_full_history"
            assert not kwargs["structured"]
            assert "No further evidence was requested" in messages[0]["content"]
            return "Partial answer; some reports did not fit."

        run.call = call
        answer, _ = run.answer_material("Compare all reports", "2030-01-01", "q", packs,
                                        snapshot_id="pool.json",
                                        material_reader=lambda items: run._live_materials(
                                            service, items))
        assert answer.startswith("Partial") and len(calls) == 2
        state = read_json(tmp_path / "http/q/memory-view.json")
        assert state["steps"] == 2 and not state["coverage_complete"]


def test_range_reads_captured_scope_beyond_top_k_without_future_sources(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        for i in range(3):
            service.capture_user(f"notice-{i}", "turn:0", f"Project {i} sends exactly one notice.")
        native = service.search_sources("Project 0", limit=1, include_scope=True)
        packs = build_evidence_packs(service, "Count all notices", "2030-01-01",
                                     native["source_materials"], [],
                                     source_scope=native["source_scope"])
        assert len(packs) == 3 and sum(p.get("scope_only", False) for p in packs) == 2
        service.capture_user("future", "turn:0", "FUTURE_NOTICE was not captured at the query.")
        run = execution_at(tmp_path)
        write_json(tmp_path / "pool.json", {"materials": packs})
        calls = []

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            payload = json.loads(messages[1]["content"])
            assert "FUTURE_NOTICE" not in str(messages)
            calls.append(payload)
            if len(calls) == 1:
                assert payload["task"] is None
                assert len(payload["candidates"]) == 1
                return selection([0], gap="Count every captured notice.", task="range")
            assert payload["range_coverage"]["complete"]
            assert payload["task"] == "range"
            assert len(payload["memories"]) == 3
            return selection([], answer="Three notices in the captured scope.", task="range")

        run.call = call
        answer, _ = run.answer_material("Count all notices", "2030-01-01", "q", packs,
                                        snapshot_id="pool.json",
                                        material_reader=lambda items: run._live_materials(
                                            service, items))
        assert answer.startswith("Three") and len(calls) == 2
        state = read_json(tmp_path / "http/q/memory-view.json")
        assert state["coverage_complete"]


def test_functional_host_uses_shared_pack_admission_and_read_allowance(tmp_path: Path) -> None:
    from milai_lab.methods.functional_edit_memory import FunctionalEditMemory

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        for i in range(3):
            service.capture_user(f"notice-{i}", "turn:0", f"Project {i} sends exactly one notice.")
        query = service.capture_user("ask", "q", "Count the previous project notices.")
        memory = FunctionalEditMemory(
            service, lambda text: len(text) // 4, interface_version="I2",
            evidence_policy="question_pack_v1", source_access="independent_v1",
            source_tokenization="unicode_v1", source_top_k=1, memory_view_mode="state_driven",
            material_limit=5000, read_limit=1)
        memory.context("ask", "q", "pack-host")
        config = {"configurable": {"user_id": "alice", "v13_session": "ask",
                                    "v13_turn_id": "q", "v13_config_version": "pack-host"}}
        first = memory.model_material(config)
        assert not first["range_coverage"]["complete"] and not first["evidence"]
        assert len(first["candidates"]) == 1
        assert query["source_ref"] not in json.dumps(first)
        tool = next(t for t in memory.tools() if t.name == "read_evidence")
        navigation = first["candidates"][0]["evidence_read"]
        assert navigation["tool"] == tool.name
        result = tool.invoke({"type": "tool_call", "name": "read_evidence", "id": "r1",
                              "args": {**navigation["arguments"], "task": "range",
                                       "gap": "Need the whole captured scope."}}, config=config)
        packet = json.loads(result.content)
        assert packet["ok"] and packet["range_coverage"]["complete"]
        assert len(packet["evidence"]) == 3
        assert len(memory.model_material(config)["evidence"]) == 3
        replay = tool.invoke({"type": "tool_call", "name": "read_evidence", "id": "r1",
                              "args": {"item_indices": [0], "task": "range",
                                       "gap": "Need the whole captured scope."}}, config=config)
        assert replay.content == result.content
        denied = tool.invoke({"type": "tool_call", "name": "read_evidence", "id": "r2",
                              "args": {"item_indices": [0]}}, config=config)
        assert json.loads(denied.content)["status"] == "read_limit_exhausted"
        projected = memory.project_model_messages(config, [result])
        assert "evidence" not in json.loads(projected[0].content)


def test_empty_captured_scope_is_known_empty_without_a_spurious_read(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        native = service.search_sources("How many reports?", include_scope=True)
        write_json(tmp_path / "pool.json", {"materials": [], "native_return": native})
        run = execution_at(tmp_path)
        calls = []

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            payload = json.loads(messages[1]["content"])
            assert not kwargs["structured"]
            assert payload["source_coverage"]["complete"]
            assert payload["source_coverage"]["required_source_ranges"] == 0
            calls.append(key)
            return "No reports in the currently visible captured scope."

        run.call = call
        answer, used = run.answer_material("How many reports?", "2030-01-01", "q", [],
                                           snapshot_id="pool.json")
        assert answer.startswith("No reports") and calls == ["q"] and used == []


def test_final_gap_answer_does_not_report_unopened_bodies_as_delivered(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        packs = large_packs(service)
        run = execution_at(tmp_path)
        write_json(tmp_path / "pool.json", {"materials": packs})
        calls = []

        def call(key: str, messages: Any, **kwargs: Any) -> str:
            calls.append(key)
            payload = json.loads(messages[1]["content"])
            assert payload["memories"] == []
            return (selection([], gap="No evidence was selected.") if kwargs["structured"]
                    else "No evidence was opened to answer this question.")

        run.call = call
        answer, used = run.answer_material("TOPIC_0", "2030-01-01", "q", packs,
            snapshot_id="pool.json", material_reader=lambda items: run._live_materials(
                service, items))
        assert answer.startswith("No evidence") and used == [] and len(calls) == 2
        saved = read_json(tmp_path / "http/q/memory-view.json")
        assert saved["complete"] and not saved["delivery_plan"]["body_delivered"]


def test_host_retains_prior_context_when_opening_a_second_subject(tmp_path: Path) -> None:
    from milai_lab.methods.functional_edit_memory import FunctionalEditMemory

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("orion", "0", "Orion's contact is Morgan.")
        service.capture_user("orion", "1", "They must confirm external notices first.")
        service.capture_user("vega", "0", "Vega's internal notices need no approval.")
        service.capture_user("ask", "q", "Compare Orion and Vega notices.")
        memory = FunctionalEditMemory(
            service, len, interface_version="I2", evidence_policy="question_pack_v1",
            source_top_k=1, material_limit=12000, read_limit=3)
        memory.context("ask", "q", "retain-context")
        cfg = {"configurable": {"user_id": "alice", "v13_session": "ask",
                               "v13_turn_id": "q", "v13_config_version": "retain-context"}}
        tool = next(t for t in memory.tools() if t.name == "read_evidence")
        _, pool = memory._evidence_pool(cfg)
        orion = next(i for i, p in enumerate(pool["materials"])
                     if p["session_id"] == "orion")
        vega = next(i for i, p in enumerate(pool["materials"])
                    if p["session_id"] == "vega")

        def read(indices: list[int], call_id: str, expand: list[int]) -> dict[str, Any]:
            result = tool.invoke({"type": "tool_call", "name": tool.name, "id": call_id,
                "args": {"item_indices": indices, "expand_context": expand}}, config=cfg)
            return json.loads(result.content)

        first = read([orion], "first", [orion])
        assert len(first["evidence"][0]["evidence"]) == 2
        second = read([vega], "second", [])
        assert second["admitted_indices"] == [vega, orion]
        body = memory.model_material(cfg)
        assert {row["content"] for p in body["evidence"] for row in p.get("evidence", [])} == {
            "Orion's contact is Morgan.", "They must confirm external notices first.",
            "Vega's internal notices need no approval."}
        assert body["range_coverage"]["complete"] and body["excluded_indices"] == []
        page = read([], "page", [])
        assert page["evidence"] == body["evidence"]


def test_state_views_refresh_only_explicit_changed_dependencies_and_freeze_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.methods.functional_edit_memory import FunctionalEditMemory

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        memory = FunctionalEditMemory(service, len, interface_version="I2")

        def context(key: str, text: str) -> tuple[dict[str, Any], list[str]]:
            ref = service.capture_user("story", key, text)["source_ref"]
            memory.context("story", key, "dependencies-v1")
            cfg = {"configurable": {"user_id": "alice", "v13_session": "story",
                                     "v13_turn_id": key, "v13_config_version": "dependencies-v1"}}
            return cfg, [service.source_fragments(ref)[0]["fragment_handle"]]

        cfg, handles = context("seed", "A uses amber after confirmation; B uses blue.")
        saved = memory.save_edit(cfg, "save", units=[
            {"text": "A uses amber.", "role": "content", "evidence": handles},
            {"text": "After confirmation.", "role": "condition", "evidence": handles},
            {"text": "B uses blue.", "role": "content", "evidence": handles},
        ], relations=[{"source": 1, "target": 0, "relation_type": "modifies",
                        "evidence": handles}])
        row = service.read(saved["id"])
        unit_ids = [unit["unit_id"] for unit in row["value"]["edit_state"]["units"]]
        packs = []
        for index in (0, 2):
            selected = {**row, "retrieval_navigation": {"unit_id": unit_ids[index]}}
            packs.append(build_evidence_packs(service, "colors", "2030-01-01", [], [selected])[0])

        cfg, handles = context("change-b", "B now uses cyan; A stays unchanged.")
        current = service.read(saved["id"])
        result = memory.update_edit(cfg, "update-b", current["candidate_handle"], [{
            "operation": "replace", "target_unit": unit_ids[2],
            "text": "B uses cyan.", "evidence": handles,
        }])
        assert result["ok"]
        refreshed = open_evidence_packs(service, packs, refresh_current=True)
        assert refreshed[0]["dependency_status"] == "retained_units_unchanged"
        assert refreshed[0]["revision"] == 1
        assert refreshed[1]["dependency_status"] == "refreshed_explicit_dependencies"
        assert refreshed[1]["revision"] == 2
        assert "cyan" in str(project_pack(refreshed[1], 1))

        actual_read = service.read
        with monkeypatch.context() as frozen:
            def old_only(identifier: str, revision: int | None = None) -> dict[str, Any]:
                assert revision == 1, "A saved replay inspected the final bank's future revision"
                return actual_read(identifier, revision)

            frozen.setattr(service, "read", old_only)
            original = open_evidence_packs(service, packs)
            historical = open_evidence_packs(service, [
                {**packs[1], "version_view": "historical_exact_revision"},
            ], refresh_current=True)[0]
            assert historical["version_view"] == "historical_exact_revision"
            assert historical["dependency_status"] == "frozen_historical"
            assert historical["revision"] == 1
        assert "B uses blue." in str(project_pack(original[1], 1))
        assert "cyan" not in str(project_pack(original[1], 1))

        cfg, handles = context("change-condition", "A needs supervisor confirmation.")
        current = service.read(saved["id"])
        result = memory.update_edit(cfg, "update-condition", current["candidate_handle"], [{
            "operation": "replace", "target_unit": unit_ids[1],
            "text": "After supervisor confirmation.", "evidence": handles,
        }])
        assert result["ok"]
        updated = open_evidence_packs(service, [packs[0]], refresh_current=True)[0]
        assert updated["revision"] == 3
        assert "After supervisor confirmation." in str(project_pack(updated, 0))
        assert service.read(saved["id"], 1)["ok"]

        service.capture_user("history", "ask", "Read the first saved A and B colors.")
        host = FunctionalEditMemory(
            service, len, interface_version="I2", evidence_policy="question_pack_v1",
            source_access="independent_v1", memory_view_mode="state_driven",
            read_interface="explicit_selectors_v1", material_limit=30000)
        host.context("history", "ask", "history-navigation-v1")
        config = {"configurable": {"user_id": "alice", "v13_session": "history",
                                    "v13_turn_id": "ask",
                                    "v13_config_version": "history-navigation-v1"}}
        material = host.model_material(config)
        candidate = next(row for row in material["candidates"]
                         if row["kind"] == "semantic_view")
        assert saved["id"] not in json.dumps(candidate)
        target = candidate["history_read"]["arguments"]["target"]
        assert candidate["history_read"]["tool"] == "read_memory_history"
        navigation = host.resolve_request_target(config, target)
        assert navigation["kind"] == "read_only_navigation"
        assert navigation["credentials"] == {}
        tool = next(t for t in host.tools() if t.name == "read_memory_revision")
        result = tool.invoke({"type": "tool_call", "name": tool.name, "id": "history-read",
                              "args": {"target": target, "revision": 1}}, config=config)
        packet = json.loads(result.content)
        assert packet["ok"]
        assert "B uses blue." in result.content
        assert "B uses cyan." not in result.content
        assert "historical_exact_revision" in result.content
        assert host.project_model_messages(config, [result])[0].content == result.content


def test_answer_only_context_keeps_actual_history_and_effects_not_navigation() -> None:
    from milai_lab.methods.evidence_reading import answer_only_context

    material = {"evidence": [{"label": "e0", "content": "Current rule requires confirmation."}],
                "candidates": [{"excerpt": "UNOPENED_CANDIDATE"}],
                "range_coverage": {"complete": False}, "gap": "One source unavailable."}
    tools = [{"name": "read_memory_revision", "memory_read": True, "result": {
        "items": [{"type": "record", "version_view": "historical_exact_revision",
                   "content": "The old rule did not require confirmation."}],
        "candidates": [{"excerpt": "OTHER_UNOPENED"}]}},
        {"name": "reserve_and_label", "result": {"status": "partial", "reserved": True,
                                                    "label_completed": False}}]
    effects = {"semantic_memory": {"status": "committed"}, "business": {"status": "partial"}}
    messages = answer_only_context(
        "What changed and what remains undone?", material, effects, tools)
    payload = json.loads(messages[1]["content"])
    assert payload["question"] == "What changed and what remains undone?"
    assert "UNOPENED" not in messages[1]["content"]
    assert "old rule did not require" in messages[1]["content"]
    assert payload["confirmed_results"] == effects
    assert payload["observed_tool_results"][1]["result"]["label_completed"] is False
    assert payload["evidence"]["range_coverage"]["complete"] is False
    assert material["candidates"]  # Projection did not edit the saved packet.
