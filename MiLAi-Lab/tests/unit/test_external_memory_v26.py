"""Narrow boundaries for the native external-memory adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from milai_lab.baselines.langmem_agent import FoundationScope
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, read_json
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.mem0_native import (
    MEM0_SEARCH_SCHEMA,
    Mem0NativeRuntime,
    _ChatCompletions,
    _Embeddings,
)


class _Memory:
    def __init__(self) -> None:
        self.adds: list[tuple[list[dict[str, str]], str, bool]] = []
        self.searches: list[tuple[str, dict[str, str], int, float]] = []
        self.fail_after_add = False

    def add(self, messages: list[dict[str, str]], *, user_id: str,
            infer: bool) -> dict[str, Any]:
        self.adds.append((messages, user_id, infer))
        if self.fail_after_add:
            raise RuntimeError("unknown provider outcome")
        return {"results": [{"id": "native-id", "memory": "actual content"}]}

    def search(self, query: str, *, filters: dict[str, str],
               top_k: int, threshold: float) -> dict[str, Any]:
        self.searches.append((query, filters, top_k, threshold))
        return {"results": [{"id": "native-id", "memory": "actual content"}]}


def _runtime(root: Path, memory: _Memory) -> Mem0NativeRuntime:
    runtime = Mem0NativeRuntime.__new__(Mem0NativeRuntime)
    runtime.root, runtime.run_id, runtime.arm_id = root, "run", "mem0_native_autoadd"
    runtime.memory = memory
    runtime.host = SimpleNamespace(emit=None)
    return runtime


def test_native_scope_and_completed_turn_ingested_once(tmp_path: Path) -> None:
    memory = _Memory()
    runtime = _runtime(tmp_path, memory)
    scope = FoundationScope("run", "mem0_native_autoadd", "diagnostic:f01", "session:first")
    tool = runtime.tools("f01")[0]
    assert tool.args == MEM0_SEARCH_SCHEMA["properties"]
    result = tool.invoke({"query": "reservation"}, config=scope.config())
    assert json.loads(result)["results"][0]["id"] == "native-id"
    assert memory.searches == [("reservation", {"user_id": "run:mem0_native_autoadd:f01"},
                                20, 0.1)]
    with pytest.raises(ValueError, match="MEM0_SEARCH_SCOPE_CHANGED"):
        tool.invoke({"query": "reservation"}, config=FoundationScope(
            "run", "mem0_native_autoadd", "diagnostic:f02", "session:first").config())
    final = [AIMessage(content="Confirmed 14 saplings are on hold until approval.")]
    runtime.after_turn("f01", scope, 0, "Hold 14 saplings until approval.", final)
    runtime.after_turn("f01", scope, 0, "Hold 14 saplings until approval.", final)
    assert memory.adds == [([
        {"role": "user", "content": "Hold 14 saplings until approval."},
        {"role": "assistant", "content": final[0].content},
    ], "run:mem0_native_autoadd:f01", True)]
    assert next(iter(read_json(tmp_path / "mem0-ingestion.json").values()))[
        "status"] == "complete"


def test_ambiguous_native_add_is_not_replayed(tmp_path: Path) -> None:
    memory = _Memory()
    memory.fail_after_add = True
    runtime = _runtime(tmp_path, memory)
    scope = FoundationScope("run", "mem0_native_autoadd", "diagnostic:f01", "session:first")
    final = [AIMessage(content="Done.")]
    with pytest.raises(RuntimeError, match="unknown provider outcome"):
        runtime.after_turn("f01", scope, 0, "Hold it.", final)
    with pytest.raises(ValueError, match="MEM0_INGESTION_OUTCOME_UNKNOWN"):
        runtime.after_turn("f01", scope, 0, "Hold it.", final)
    assert len(memory.adds) == 1
    assert next(iter(read_json(tmp_path / "mem0-ingestion.json").values()))[
        "status"] == "pending"


def test_provider_bridge_preserves_mem0_options_and_batch_order() -> None:
    requests: list[tuple[str, Any]] = []

    class FakeClient:
        config = SimpleNamespace(model="host", temperature=0, max_tokens=4096)

        def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
            requests.append(("chat", kwargs))
            return {"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
                    "model": "host", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"memory":[]}'}}]}

        def embed(self, inputs: Any, model: str) -> list[list[float]]:
            requests.append(("embed", (inputs, model)))
            return [[float(index)] for index, _ in enumerate(inputs)]

    import threading

    bridge = _ChatCompletions(FakeClient(), threading.Lock())
    response = bridge.create(model="host", messages=[{"role": "user", "content": "x"}],
                             temperature=0, max_tokens=4096, top_p=1.0,
                             response_format={"type": "json_object"})
    assert response.choices[0].message.content == '{"memory":[]}'
    assert requests[0] == ("chat", {"response_format": {"type": "json_object"},
                                    "top_p": 1.0})
    embeddings = _Embeddings(FakeClient(), threading.Lock()).create(
        model="host", input=["one", "two"], encoding_format="float")
    assert [(row.index, row.embedding) for row in embeddings.data] == [
        (0, [0.0]), (1, [1.0])]
    assert requests[-1] == ("embed", (["one", "two"], "host"))
    with pytest.raises(ValueError, match="MEM0_GENERATION_OPTIONS_CHANGED"):
        bridge.create(model="host", messages=[], temperature=0, max_tokens=4096,
                      top_p=1.0, seed=7)


def test_official_mem0_add_search_sparse_entities_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_TELEMETRY", "False")
    pytest.importorskip("mem0")
    pytest.importorskip("spacy")
    cache = Path("artifacts/external-memory-v26/cache/fastembed").resolve()
    if not cache.exists():
        pytest.skip("The isolated Mem0 sparse-model cache is not installed")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(cache))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    requests: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"path": request.url.path, "body": body})
        if request.url.path.endswith("/embeddings"):
            assert "dimensions" not in body
            return httpx.Response(200, json={
                "model": "bge-m3", "data": [
                    {"index": index, "embedding": [0.02] * 1024}
                    for index, _ in enumerate(body["input"])
                ], "usage": {"prompt_tokens": 3, "total_tokens": 3},
            })
        assert body["top_p"] == 1.0
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(200, json={
            "id": "chatcmpl-fake", "object": "chat.completion", "created": 1,
            "model": "host", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({"memory": [{
                    "text": "Alice plans to meet Microsoft in Seattle tomorrow.",
                    "attributed_to": "user",
                }]})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        })

    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       tmp_path / "budget.json")
    host = VLLMClient(VLLMConfig("http://fake/v1/", "host", max_tokens=4096,
                                  enable_thinking=False), emit=events.append,
                      transport=httpx.MockTransport(respond), budget=budget)
    embed = VLLMClient(VLLMConfig("http://fake/v1/", "bge-m3"), emit=events.append,
                       transport=httpx.MockTransport(respond), budget=budget)
    root = tmp_path / "native"
    scope = FoundationScope("run", "mem0_native_autoadd", "diagnostic:f01", "session:first")
    try:
        runtime = Mem0NativeRuntime(root, "run", "mem0_native_autoadd", host, embed)
        runtime.after_turn("f01", scope, 0, "I will meet Microsoft in Seattle tomorrow.",
                           [AIMessage(content="I understand your Seattle meeting.")])
        assert runtime.memory._entity_store is not None
        assert runtime.memory.entity_store.client is runtime.memory.vector_store.client
        records, _ = runtime.memory.vector_store.client.scroll(
            collection_name="milai_external_v26", limit=10, with_vectors=True)
        assert records and "bm25" in records[0].vector
        entities, _ = runtime.memory.entity_store.client.scroll(
            collection_name=runtime.memory.entity_store.collection_name, limit=10)
        assert entities and records[0].id in entities[0].payload["linked_memory_ids"]
        assert runtime.snapshot("f01")
        assert runtime.snapshot("f02") == []
        assert runtime.tools("f01")[0].invoke(
            {"query": "Microsoft Seattle"}, config=scope.config())
        runtime.close()

        restarted = Mem0NativeRuntime(root, "run", "mem0_native_autoadd", host, embed)
        assert restarted.snapshot("f01")
        restarted.after_turn("f01", scope, 0,
                             "I will meet Microsoft in Seattle tomorrow.",
                             [AIMessage(content="I understand your Seattle meeting.")])
        restarted.close()
    finally:
        host.close()
        embed.close()
    assert sum(event["path"].endswith("/chat/completions") for event in requests) == 1
    assert budget.state["generation_requests"] == 1
    assert budget.state["generation"]["known_tokens"] == 18
    assert budget.state["generation"]["unknown_usage"] == 0
    assert budget.state["embedding"]["known_tokens"] == 3 * sum(
        event["path"].endswith("/embeddings") for event in requests)
    assert budget.state["embedding"]["unknown_usage"] == 0
    assert any(event.get("event") == "mem0_native_runtime" and event["bm25_slot"]
               for event in events)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
