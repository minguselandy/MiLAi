"""Actual scoped SQLite retrieval and metered transport; synthetic vectors only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.embeddings import Embeddings
from langgraph.store.sqlite import SqliteStore
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, RunLimits
from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.memory.service import MemoryService
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.runners.edit_benchmarks import BenchmarkRun


class Vectors(Embeddings):
    def __init__(self) -> None:
        self.documents: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [[1.0, 0.0] if "tea" in text else [0.0, 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def seed(service: MemoryService, key: str, body: str, *, render: str = "") -> None:
    source = service.capture_user("synthetic", key, body)["source_ref"]
    current = {
        "revision": 1,
        "content": render or body,
        "source_ref": source,
        "source_refs": [source],
        "edit_state": {"matter_description": "", "units": [{"text": body}]},
    }
    service.store.put(
        service.namespace,
        key,
        {
            "_v13_1": {"owner": service.owner, "current": current, "history": [current]},
        },
        index=False,
    )


def test_metadata_misses_and_full_lexical_page_use_the_same_visible_bank(tmp_path: Path) -> None:
    vectors = Vectors()
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(store, ("memory", "alice"), "alice", tmp_path / "lock")
        seed(service, "food", "Green tea is preferred.", render="Unmatched display metadata")
        seed(service, "travel", "Airplane travel.", render="Collection date 14")
        before = service.records()
        frozen = service.search("14 refreshment", include_raw=False)["records"]
        assert [row["id"] for row in frozen] == ["travel"]
        service.semantic_retriever = SemanticRetriever(vectors, 2)
        result = service.search("14 refreshment", limit=1, include_raw=False)
        assert [row["id"] for row in result["records"]] == ["food"]
        assert vectors.documents == ["\nGreen tea is preferred.", "\nAirplane travel."]
        assert service.records() == before
        seed(service, "dated", "Tea only on 2030-02-01.")
        dated = service.search("2030", limit=1, include_raw=False)["records"]
        assert dated[0]["id"] == "dated"
        assert dated[0]["value"]["edit_state"]["units"][0]["text"] == "Tea only on 2030-02-01."
        for ordinal in range(10):
            seed(service, f"a{ordinal}", "slot information")
        other = MemoryService(store, ("memory", "bob"), "bob", tmp_path / "other-lock")
        seed(other, "foreign", "Green tea is preferred.")
        rows = service.search("slot refreshment", limit=4, include_raw=False)["records"]
        assert len(rows) == 4 and len({row["id"] for row in rows}) == 4
        assert "food" in {row["id"] for row in rows}
        assert "foreign" not in {row["id"] for row in rows}


def test_cache_tracks_current_body_and_withdrawal_without_erasing_history(tmp_path: Path) -> None:
    vectors = Vectors()
    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(
            store,
            ("memory", "alice"),
            "alice",
            tmp_path / "lock",
            functional_contract="functional_v1",
            semantic_retriever=SemanticRetriever(vectors, 2),
        )
        seed(service, "a", "Green tea is preferred.")
        seed(service, "b", "Music interests.")
        assert service.search("refreshment", limit=1, include_raw=False)["records"][0]["id"] == "a"
        service.search("refreshment", limit=1, include_raw=False)
        assert len(vectors.documents) == 2
        item = store.get(service.namespace, "a")
        assert item is not None
        value = item.value
        old = value["_v13_1"]["current"]
        current = {
            **old,
            "revision": 2,
            "edit_state": {"matter_description": "", "units": [{"text": "Music instead."}]},
        }
        value["_v13_1"]["current"] = current
        value["_v13_1"]["history"] = [old, current]
        store.put(service.namespace, "a", value, index=False)
        service.search("refreshment", limit=1, include_raw=False)
        assert vectors.documents[-1] == "\nMusic instead."
        current["retracted"] = True
        store.put(service.namespace, "a", value, index=False)
        rows = service.search("refreshment", limit=2, include_raw=False)["records"]
        assert [row["id"] for row in rows] == ["b"]
        assert (
            service.read("a", 1)["value"]["edit_state"]["units"][0]["text"]
            == "Green tea is preferred."
        )


def test_embedding_failure_is_not_silent_lexical_success_or_a_memory_write(tmp_path: Path) -> None:
    class Failed(Vectors):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise ConnectionError("synthetic embedding failure")

    with SqliteStore.from_conn_string(str(tmp_path / "store.sqlite")) as store:
        service = MemoryService(
            store,
            ("memory", "alice"),
            "alice",
            tmp_path / "lock",
            semantic_retriever=SemanticRetriever(Failed(), 2),
        )
        seed(service, "a", "Green tea is preferred.")
        before, sources = service.records(), service.sources()
        with pytest.raises(ConnectionError, match="synthetic embedding failure"):
            service.search("tea", include_raw=False)
        assert service.records() == before and service.sources() == sources


def test_each_embedding_batch_is_recorded_before_http_and_billed_once(tmp_path: Path) -> None:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    trace = BenchmarkRun.__new__(BenchmarkRun)
    trace.root, trace._embedding_serial = tmp_path, 0
    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    sent: list[dict[str, Any]] = []

    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        path = tmp_path / "http/embedding" / f"{len(sent) + 1:06d}" / "request.json"
        assert json.loads(path.read_text()) == body
        sent.append(body)
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": [1, 0]} for i, _ in enumerate(body["input"])],
                "usage": {"total_tokens": len(body["input"])},
            },
        )

    with VLLMClient(
        VLLMConfig("http://synthetic.invalid/v1", "synthetic"),
        emit=trace._embedding_trace,
        transport=httpx.MockTransport(provider),
        budget=budget,
    ) as client:
        embeddings = MeteredEmbeddings(
            client,
            "synthetic",
            {"tokenizer_path": str(tmp_path / "tokenizer.json"), "context_tokens": 128},
            dimension=2,
            batch_size=2,
        )
        assert len(embeddings.embed_documents(["a", "b", "c"])) == 3
    assert len(sent) == 2 and budget.state["embedding"]["known_tokens"] == 3
    assert budget.state["embedding"]["unknown_usage"] == 0
    assert budget.state["generation_requests"] == 0
    assert len(list((tmp_path / "http/embedding").glob("*/response.json"))) == 2


def test_embedding_budget_rejection_is_recorded_as_not_sent(tmp_path: Path) -> None:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    trace = BenchmarkRun.__new__(BenchmarkRun)
    trace.root, trace._embedding_serial = tmp_path, 0
    budget = RunBudget(RunLimits(embedding_tokens=0), tmp_path / "budget.json")

    def denied(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Budget rejected input must not reach HTTP")

    with VLLMClient(
        VLLMConfig("http://synthetic.invalid/v1", "synthetic"),
        emit=trace._embedding_trace,
        transport=httpx.MockTransport(denied),
        budget=budget,
    ) as client:
        embeddings = MeteredEmbeddings(
            client,
            "synthetic",
            {"tokenizer_path": str(tmp_path / "tokenizer.json"), "context_tokens": 128},
            dimension=2,
            batch_size=2,
        )
        with pytest.raises(BudgetExceeded):
            embeddings.embed_query("input")
    failure = json.loads((tmp_path / "http/embedding/000001/failure.json").read_text())
    assert failure["event"] == "vllm_budget_rejected" and failure["request_sent"] is False
    assert budget.state["embedding"]["charged_tokens"] == 0
    assert budget.state["embedding"]["unknown_usage"] == 0
