import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_revision_attention as prep


def test_frozen_joint_manifest_preserves_old_data_and_caps(monkeypatch):
    old = json.loads(prep.OLD_ALLOCATION.read_text())
    checks = {
        prep.ALLOCATION: prep.ALLOCATION_SHA,
        prep.OLD_ALLOCATION: prep.OLD_SHA,
        prep.SPLIT: prep.SPLIT_SHA,
    }
    checks.update(
        {
            Path(p["exposure_receipt"]): p["exposure_receipt_sha256"]
            for positions in old["domains"].values()
            for p in positions
        }
    )
    monkeypatch.setattr(prep, "sha", checks.__getitem__)
    manifest = prep.verify_allocation()
    assert manifest["domains"] == old["domains"]
    assert manifest["limits"] == old["limits"]
    for mechanism in ("REVISION", "ATTENTION"):
        rows = [p for p in manifest["schedule"] if p["mechanism"] == mechanism]
        assert len(rows) == 16
        assert sum(p["repeat"] for p in rows) == 4
        assert len({(p["domain"], p["task_id"]) for p in rows}) == 12
        for repeated in (p for p in rows if p["repeat"]):
            original = next(
                p
                for p in rows
                if p["domain"] == repeated["domain"]
                and p["task_id"] == repeated["task_id"]
                and not p["repeat"]
            )
            assert repeated["arms"] == original["arms"][::-1]
            assert repeated["pair_index"] == original["pair_index"] + 2


def test_changed_allocation_is_rejected_before_source_reads(monkeypatch):
    monkeypatch.setattr(prep, "sha", lambda _: "changed")
    with pytest.raises(ValueError, match="FROZEN_JOINT_ALLOCATION_CHANGED"):
        prep.verify_allocation()


def test_review_binds_original_trace_and_transitive_clusters(tmp_path):
    bank = {
        "completed_tasks": ["fixture:1", "fixture:2", "fixture:3"],
        "records": [
            {"trace_ref": "trace:1", "task_id": "fixture:1", "handles": ["c1"]},
            {"trace_ref": "trace:2", "task_id": "fixture:2", "handles": ["c2"]},
        ],
        "cards": {
            "c1": {"revision": 1, "retired": False, "source_refs": ["trace:1"]},
            "c2": {"revision": 1, "retired": False, "source_refs": ["trace:2"]},
        },
        "sources": {"trace:1": "original", "trace:2": "derived", "tool:3": "visible"},
    }
    events = [
        [],
        [{"event": "MEMORY_RETRIEVED", "handles": ["c1"], "revisions": {"c1": 1}}],
        [
            {"event": "MEMORY_RETRIEVED", "handles": ["c2"], "revisions": {"c2": 1}},
            {"event": "MEMORY_SOURCE_ADDED", "kind": "tool", "ref": "tool:3"},
        ],
    ]
    for index, rows in enumerate(events, 1):
        directory = tmp_path / f"task-{index}"
        directory.mkdir()
        (directory / "memory-events.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    permitted = {str(i): {"id": str(i), "cluster": f"cluster:{i}"} for i in range(1, 5)}
    before = copy.deepcopy(bank)
    sources = {}
    rows = prep.review_bank(tmp_path, bank, permitted, list(permitted.values()), sources)
    assert bank == before
    assert len(sources) == 3
    assert len(rows) == 1
    assert rows[0]["formation_ancestry"] == ["fixture:1", "fixture:2", "fixture:3"]
    assert rows[0]["independent_revision_targets"] == ["4"]
    assert rows[0]["support"] == "NOT_REVIEWED"
    assert rows[0]["original_evidence"] == {"trace:2": "derived"}


def test_raw_review_output_cannot_be_created_in_repository(monkeypatch):
    monkeypatch.setattr(prep, "verify_allocation", lambda: {})
    with pytest.raises(ValueError, match="OUTSIDE_REPOSITORY"):
        prep.prepare(prep.LAB / "artifacts" / "forbidden-review-output")


@pytest.fixture
def query_cache(tmp_path, monkeypatch):
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"tasks": [{"domain": "fixture", "id": "1", "query": "question"}]}))
    instruction = tmp_path / "configs/policies/reasoning_bank/retrieval_instruction.txt"
    instruction.parent.mkdir(parents=True)
    instruction.write_text("retrieve relevant memories\n")
    monkeypatch.setattr(prep, "LAB", tmp_path)
    monkeypatch.setattr(prep, "OLD_INPUT", old)
    monkeypatch.setattr(prep, "OLD_INPUT_SHA", prep.sha(old))
    root = tmp_path / "history"
    embedding = root / "embedding"
    embedding.mkdir(parents=True)
    # Deliberately unreadable as JSON: own-task bank contents must never be a fallback.
    (root / "bank.json").write_text("must not read own-task bank")
    allocation = {
        "domains": {
            "fixture": [
                {
                    "id": "1",
                    "cluster": "cluster:1",
                    "exposure_receipt": str(root / "task-1/receipt.json"),
                }
            ]
        }
    }
    return allocation, embedding, "Instruct: retrieve relevant memories\nQuery: question"


@pytest.mark.parametrize("instructed", [False, True])
def test_query_cache_requires_exact_instructed_request(query_cache, instructed):
    allocation, directory, encoded = query_cache
    request = directory / "embedding-000001-request.json"
    response = directory / "embedding-000001-http.json"
    inputs = ["question", encoded] if instructed else ["question"]
    request.write_text(json.dumps({"model": "bge-m3", "input": inputs}))
    vectors = [[1.0] + [0.0] * 1023, [0.0, 1.0] + [0.0] * 1022]
    response.write_text(
        json.dumps(
            {
                "status_code": 200,
                "body": json.dumps(
                    {
                        "model": "bge-m3",
                        "data": [{"index": i, "embedding": vectors[i]} for i in range(len(inputs))],
                    }
                ),
            }
        )
    )
    sources = {}
    (row,) = prep.prepare_queries(allocation, sources)
    assert row["embedding_input"] == encoded
    if instructed:
        assert row["embedding"] == vectors[1]
        assert row["query_vector_origin"] == str(request)
        assert row["encoding_status"] == "EXACT_INSTRUCTED_QUERY_CACHE"
        assert sources[str(request)] == prep.sha(request)
        assert sources[str(response)] == prep.sha(response)
    else:
        assert row["embedding"] is None
        assert row["query_vector_origin"] is None
        assert row["encoding_status"] == "MISSING_INSTRUCTED_QUERY_CACHE"
        assert str(request) not in sources
    assert not any(path.endswith("bank.json") for path in sources)
