import json

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryControlState,
    run_memory_control,
)
from milai_lab.runners.memory_control import dense_control_pool


def test_full_context_is_a_shared_action_and_fixed_policy_reads_one_complete_session(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("baseline", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        for i in range(8):
            service.capture_user("s", str(i), f"The record for topic {i} is value {i}.")
        state = MemoryControlState(task={"request": "What are the records?", "query_time": "2032"})

        def pool():
            source = service.search_sources(state.task["request"], include_scope=True)
            return build_evidence_packs(service, state.task["request"], "2032",
                source["source_materials"], [], source_scope=source["source_scope"])

        ops = EvidenceOperations(service, state, load_pool=pool,
            refresh_call=lambda *_: {}, fits=lambda items: True)
        result = run_memory_control(state, FixedContextMemoryPolicy(), ops)
        assert result["trace"][0]["selected"] == "search"
        assert result["trace"][1]["selected"].startswith("context_")
        assert len(result["trace"]) == 3
        assert all(f"topic {i}" in json.dumps(state.visible_evidence) for i in range(8))


def test_dense_order_uses_complete_bodies_and_preserves_reference_indices(tmp_path):
    class Embeddings:
        def __init__(self):
            self.inputs = []

        def embed_documents(self, texts):
            self.inputs.extend(texts)
            return [[1.0, 0.0] if "LATEST_MARKER" in text else [0.0, 1.0] for text in texts]

        def embed_query(self, query):
            return [1.0, 0.0]

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("dense", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("s", "old", "Old statement.")
        service.capture_user("other", "new", "Long context. " * 30 + "LATEST_MARKER")
        native = service.search_sources("statement", include_scope=True)
        materials = build_evidence_packs(service, "statement", "2032",
            native["source_materials"], [], source_scope=native["source_scope"])
        embeddings = Embeddings()
        traces = []
        ranked = dense_control_pool("latest", materials,
            retriever=SemanticRetriever(embeddings, 2), record=traces.append)
        assert [m["id"] for m in ranked] == [m["id"] for m in materials]
        assert any("LATEST_MARKER" in text for text in embeddings.inputs)
        state = MemoryControlState(task={"request": "latest", "query_time": "2032"})
        ops = EvidenceOperations(service, state, load_pool=lambda: ranked,
                                  refresh_call=lambda *_: {}, fits=lambda items: True)
        ops.execute(next(a for a in ops.actions(state) if a.kind == "SEARCH"), state)
        selected = FixedMemoryPolicy(1).choose(state, ops.actions(state))
        target = int(selected.split("_")[-1])
        assert "LATEST_MARKER" in materials[target]["text"]
        assert traces[0]["body_count"] == len(materials)
