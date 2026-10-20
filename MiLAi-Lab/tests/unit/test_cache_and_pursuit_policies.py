"""Real Store transitions and upstream selector; vector fixtures are not model evidence."""
import json
from types import SimpleNamespace

import pytest
from langgraph.store.sqlite import SqliteStore
from test_memory_control import service_at, setup_operations

from milai_lab.baselines.mempursuit import MemPursuitPool
from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy, text_overlap
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.memory_control import (
    MemoryAction,
    MemoryControlState,
    PursuitMemoryPolicy,
    run_memory_control,
)


def test_cache_builds_reuses_reads_bound_original_then_refreshes_actual_arrival(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "1", "The approval threshold is 1000.")
        policy = CacheMemoryPolicy()
        state, ops = setup_operations(service)
        first = run_memory_control(state, policy, ops)
        assert [e["selected"] for e in first["trace"]] == ["refresh_view", "handoff"]
        state, ops = setup_operations(service)
        warm = run_memory_control(state, policy, ops)
        assert [e["selected"] for e in warm["trace"]] == ["use_view", "handoff"]
        state, ops = setup_operations(service)
        state.task["read_goal"] = {"evidence": ["original_source"]}
        quote = run_memory_control(state, policy, ops)
        assert quote["trace"][0]["selected"].startswith("view_source_")
        assert quote["trace"][-1]["selected"] == "handoff"
        assert state.visible_evidence[0]["kind"] == "original_source"
        service.capture_user("history", "2", "The approval threshold is now 1200.")
        state, ops = setup_operations(service)
        changed = run_memory_control(state, policy, ops)
        assert changed["trace"][0]["selected"] == "refresh_view"
        assert "1200" in json.dumps(state.visible_evidence)


def test_cache_matches_scope_and_original_binding_without_case_specific_words():
    source_a, source_b = {"source_ref": "a"}, {"source_ref": "b"}
    view = {"id": "v", "slot": "current", "visibility": "visible", "pending_events": [],
        "built_for": "Read garden access policy", "scope": "garden access policy",
        "source_bindings": {"e0": source_a, "e1": source_b},
        "interpretation": {"nodes": {
            "n0": {"text": "garden access permission", "evidence": ["e0"]},
            "n1": {"text": "catering reservation meal", "evidence": ["e1"]}}}}
    state = MemoryControlState(task={"request": "garden access permission",
        "read_goal": {"evidence": ["original_source"]}}, views=[view])
    actions = [MemoryAction("b", "READ", "bound", {"observed_source": source_b}),
        MemoryAction("a", "READ", "bound", {"observed_source": source_a}),
        MemoryAction("use", "USE_VIEW", "v"),
        MemoryAction("refresh", "REFRESH_VIEW", "v", {"slot": "current"}),
        MemoryAction("end", "HANDOFF", "Host")]
    assert CacheMemoryPolicy().choose(state, actions) == "a"
    state.task = {"request": "unrelated shipment tracking numbers"}
    assert CacheMemoryPolicy().choose(state, actions) == "refresh"
    assert text_overlap("花园准入条件", "花园准入条件") == 1.0


def test_upstream_pursuit_reads_complementary_prefix_without_removing_other_actions(tmp_path):
    pytest.importorskip("mempursuit")

    class Vectors:
        def __init__(self):
            self.documents = 0

        def embed_documents(self, texts):
            self.documents += len(texts)
            return [[0.0, 1.0] if "axis-c" in t else [1.0, 0.0] for t in texts]

        def embed_query(self, _query):
            return [1.0, 1.0]

    vectors, measured, traces = Vectors(), [], []
    budget = SimpleNamespace(record_compute=lambda phase, counts: measured.append((phase, counts)))
    pool = MemPursuitPool(vectors, budget, selected_limit=2, adaptive=False, record=traces.append)
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        for name in ("axis-a", "axis-b", "axis-c"):
            service.capture_user(name, "1", name)

        def search(query, limit):
            found = service.search_sources(query, limit=limit, tokenization="unicode_v1")
            packs = build_evidence_packs(service, query, "", found["source_materials"], [],
                                         tokenization="unicode_v1")
            return pool(query, packs)

        state = MemoryControlState(task={"request": "axis", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: search("axis", 16),
            search_pool=search, refresh_call=lambda *_: pytest.fail("No View generation"),
            fits=lambda _: True)
        result = run_memory_control(state, PursuitMemoryPolicy(), ops)
        assert result["trace"][0]["selected"] == "search_0_16"
        assert traces[0]["stop_reason"] == "budget" and len(traces[0]["selected_indices"]) == 2
        offered = result["trace"][1]["actions"]
        assert {a["id"] for a in offered if a["kind"] == "READ"} >= {"read_0", "read_1", "read_2"}
        bodies = [source["content"] for item in state.visible_evidence
                  for source in item["evidence"]]
        assert len(bodies) == 2 and "axis-c" in bodies
        assert len(set(bodies) & {"axis-a", "axis-b"}) == 1
        assert vectors.documents == 3 and len(measured) == 1
        search("axis", 16)
        assert vectors.documents == 3  # Actual text reuse, without content digests.
        assert measured[-1][1]["candidate_embedding_cache_misses"] == 0


def test_pursuit_stops_at_selected_prefix_even_when_unselected_read_is_legal():
    state = MemoryControlState(task={"request": "query"}, last_result={"status": "opened"},
        pending_candidates=[{"item_index": 1, "control_pool_selected": False,
                             "control_pool_rank": 2}])
    actions = [MemoryAction("read", "READ", "candidate", {"index": 1}),
               MemoryAction("end", "HANDOFF", "Host")]
    assert PursuitMemoryPolicy().choose(state, actions) == "end"
