"""Actual pinned author classes with synthetic counted callbacks and durable state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from milai_lab.integrations.memory.amem import SOURCE_COMMIT, AMemRuntime, _cosine

AUTHOR_SOURCE = Path("/cra/memory/mx_memory/reference-sources/milai-edit/A-mem")


@pytest.fixture
def author_source():
    if not (AUTHOR_SOURCE / "memory_layer.py").exists():
        pytest.skip("Pinned external A-MEM source checkout is unavailable")
    return AUTHOR_SOURCE


def callbacks():
    calls = []
    formations = 0
    evolutions = 0

    def completion(prompt, schema):
        nonlocal formations, evolutions
        calls.append(("completion", prompt, schema))
        if "keywords" in schema["properties"]:
            formations += 1
            return json.dumps(
                {
                    "keywords": ["trial", "weekly", "scope"],
                    "context": "Initial scope" if formations == 1 else "Night scope",
                    "tags": ["trial"],
                }
            )
        evolutions += 1
        return json.dumps(
            {
                "should_evolve": evolutions > 1,
                "actions": ["strengthen", "update_neighbor"] if evolutions > 1 else [],
                "suggested_connections": [0] if evolutions > 1 else [],
                "tags_to_update": ["night"],
                "new_context_neighborhood": ["General arrangement remains"],
                "new_tags_neighborhood": [["general"]],
            }
        )

    def encode(texts):
        calls.append(("embedding", list(texts)))
        return [[0.0, 1.0] if "night" in text.lower() else [1.0, 0.0] for text in texts]

    return completion, SimpleNamespace(encode=encode), calls


@pytest.mark.local_artifacts
def test_author_formation_evolution_consolidation_expansion_and_exact_reopen(
    tmp_path,
    author_source,
):
    completion, embedding, calls = callbacks()
    runtime = AMemRuntime(
        author_source,
        tmp_path,
        owner="alice",
        completion=completion,
        embedding=embedding,
        evo_threshold=1,
    )
    author_file = str(author_source / "memory_layer.py")
    for name, method in [
        ("MemoryNote", "analyze_content"),
        ("SimpleEmbeddingRetriever", "search"),
        ("AgenticMemorySystem", "process_memory"),
    ]:
        assert getattr(runtime.classes[name], method).__code__.co_filename == author_file
    first = runtime.ingest("actual-1", "General trial twice weekly.", role="user", observed_at="T1")
    second = runtime.ingest("actual-2", "Night trial four weekly.", role="user", observed_at="T2")
    assert first["status"] == second["status"] == "COMPLETED"
    notes = runtime.snapshot()
    assert notes[0]["content"] == "General trial twice weekly."
    assert notes[0]["context"] == "General arrangement remains"
    assert notes[1]["links"] == [0] and notes[1]["tags"] == ["night"]
    assert runtime.system.evo_cnt == 1
    assert "General arrangement remains" in runtime.system.retriever.corpus[0]
    answer = runtime.query("night", k=1)
    assert answer["status"] == "COMPLETED"
    assert "Night trial four weekly." in answer["context"]
    assert "General trial twice weekly." in answer["context"]  # Author link expansion exceeds k.
    assert answer["retrieved_note_ids"] == [second["note_id"]]
    assert answer["expanded_note_ids"] == [first["note_id"]]
    assert answer["occurrence_count"] == 2
    assert (
        "".join(answer["context"][row["start"] : row["end"]] for row in answer["occurrences"])
        == answer["context"]
    )
    assert answer["occurrences"][1]["source_ids"] == ["actual-1"]
    assert sum(call[0] == "completion" for call in calls) == 4
    count = len(calls)
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        runtime.ingest("actual-1", "Forged body", role="user", observed_at="T1")
    assert len(calls) == count
    assert runtime.ingest("actual-1", "General trial twice weekly.", role="user", observed_at="T1")[
        "replayed"
    ]
    assert len(calls) == count
    vectors = runtime.system.retriever.embeddings.copy()
    reopened = AMemRuntime(
        author_source,
        tmp_path,
        owner="alice",
        completion=completion,
        embedding=embedding,
        evo_threshold=1,
    )
    assert reopened.snapshot() == notes and len(calls) == count
    assert np.array_equal(reopened.system.retriever.embeddings, vectors)
    assert reopened.query("night", k=1)["context"] == answer["context"]
    assert reopened.persist()["binding"]["author_commit"] == SOURCE_COMMIT
    with pytest.raises(ValueError, match="PERSISTED_SCOPE_CHANGED"):
        AMemRuntime(
            author_source,
            tmp_path,
            owner="bob",
            completion=completion,
            embedding=embedding,
            evo_threshold=1,
        )
    with pytest.raises(ValueError, match="QUERY_INVALID"):
        reopened.query("night", k=11)


@pytest.mark.local_artifacts
def test_partial_embedding_failure_and_pending_reopen_never_repeat_callbacks(
    tmp_path,
    author_source,
):
    completion, _, calls = callbacks()

    def failed_embedding(texts):
        calls.append(("failed_embedding", texts))
        raise OSError("synthetic callback failure")

    embedding = SimpleNamespace(encode=failed_embedding)
    runtime = AMemRuntime(
        author_source, tmp_path, owner="alice", completion=completion, embedding=embedding
    )
    result = runtime.ingest("occurred", "An actual arrangement.", role="user", observed_at="T1")
    assert result["status"] == "INCOMPLETE" and result["native_effect"] == "partial_or_unknown"
    assert len(runtime.snapshot()) == 1  # Author assigned the note before embedding failed.
    count = len(calls)
    reopened = AMemRuntime(
        author_source, tmp_path, owner="alice", completion=completion, embedding=embedding
    )
    assert reopened.ingest("occurred", "An actual arrangement.", role="user", observed_at="T1")[
        "replayed"
    ]
    assert reopened.query("arrangement")["status"] == "INCOMPLETE"
    assert (
        reopened.ingest("later", "Later source.", role="user", observed_at="T2")["reason"]
        == "prior_ingest_unresolved"
    )
    assert len(calls) == count
    saved = reopened.persist()
    saved["ingestions"]["occurred"]["status"] = "pending"
    saved["ingestions"]["occurred"].pop("receipt")
    saved["blocked"] = None
    reopened.path.write_text(json.dumps(saved))
    interrupted = AMemRuntime(
        author_source, tmp_path, owner="alice", completion=completion, embedding=embedding
    )
    assert interrupted.blocked == "occurred" and len(calls) == count


def test_numpy_cosine_standard_operator_preserves_order_and_zero_rows():
    vectors = np.asarray([[3, 0], [0, 4], [3, 4], [0, 0]], dtype=np.float32)
    scores = _cosine([[1, 0]], vectors)[0]
    assert np.allclose(scores, [1, 0, 0.6, 0])
    assert np.argsort(scores)[-2:][::-1].tolist() == [0, 2]
