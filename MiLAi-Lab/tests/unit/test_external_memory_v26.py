"""Narrow boundaries for the native external-memory adapter."""

from __future__ import annotations

import importlib
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


def test_u2_actual_mem0_archived_tool_data_scope_admission_and_read_only_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.baselines.benchmark_memories import GenerationAdmission

    cache = Path(os.environ.get("FASTEMBED_CACHE_PATH",
                                "artifacts/external-memory-v26/cache/fastembed")).resolve()
    assert cache.is_dir(), "The locked Mem0 sparse-model cache must be prepared"
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(cache))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("MEM0_TELEMETRY", "False")
    requests: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def send(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        requests.append({"path": request.url.path, **body})
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [
                {"index": index, "embedding": [0.02] * 1024}
                for index, _ in enumerate(body["input"])], "usage": {"total_tokens": 3}})
        return httpx.Response(200, json={"id": "actual-sdk-mock", "object": "chat.completion",
            "model": "host", "created": 1, "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps({"memory": [{
                "text": "Archived exact partial receipt REF-A", "attributed_to": "user"}]})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}})

    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
        generation_tokens=None, embedding_tokens=None), tmp_path / "budget.json")
    with VLLMClient(VLLMConfig("http://mock/v1/", "host", max_tokens=4096,
        enable_thinking=False), budget=budget, emit=events.append,
        transport=httpx.MockTransport(send)) as host, VLLMClient(VLLMConfig(
            "http://mock/v1/", "bge-m3"), budget=budget, emit=events.append,
            transport=httpx.MockTransport(send)) as embed:
        source = [{"role": "user", "id": "u", "content": "Original completed request"},
            {"role": "assistant", "id": "a", "content": "Proposal", "tool_calls": [
                {"id": "c", "name": "business", "args": {}}]},
            {"role": "tool", "id": "t", "tool_call_id": "c", "status": "success",
             "content": '{"ok":false,"status":"partial","actual_id":"REF-A"}'},
            {"role": "assistant", "id": "f", "content": "Actual partial outcome"}]
        admission = GenerationAdmission(1)
        native = Mem0NativeRuntime(tmp_path / "mem0", "r", "mem0_native", host, embed,
                                   admit_generation=admission)
        try:
            formed = native.add_archive("owner", source)
            assert formed["status"] == "COMPLETED" and formed["records_after"]
            assert native.snapshot("foreign") == []
            before = native.snapshot("owner")
            incomplete = native.add_archive("owner", source)
            assert incomplete["status"] == "MAINTENANCE_INCOMPLETE"
            assert incomplete["admission_rejections"]
            assert native.snapshot("owner") == before
            scope = FoundationScope("r", "mem0_native", "owner", "fresh-query")
            read_tool = native.archive_tools(scope)[0]
            searched = read_tool.invoke({"query": "REF-A"}, config=scope.config())
            assert json.loads(searched)["results"]
            with pytest.raises(ValueError, match="SCOPE_CHANGED"):
                read_tool.invoke({"query": "REF-A"}, config=FoundationScope(
                    "r", "mem0_native", "foreign", "fresh-query").config())
        finally:
            native.close()
        reopened = Mem0NativeRuntime(tmp_path / "mem0", "r", "mem0_native", host, embed)
        try:
            assert reopened.snapshot("owner") == before
            assert reopened.search_archive("owner", "REF-A")["results"]
            assert reopened.snapshot("owner") == before

            def store_failure(*_args: Any, **_kwargs: Any) -> Any:
                raise PermissionError("actual synthetic Store permission failure")

            monkeypatch.setattr(reopened.memory, "add", store_failure)
            with pytest.raises(PermissionError, match="Store permission"):
                reopened.add_archive("owner", source)
        finally:
            reopened.close()
        generations = [request for request in requests if "messages" in request]
        assert len(generations) == budget.state["generation_requests"] == 1
        extraction = json.dumps(generations[0]["messages"])
        assert "not current instructions" in extraction and "REF-A" in extraction
        assert all(json.dumps(row) in generations[0]["messages"][-1]["content"] for row in source)
        assert any(event.get("event") == "mem0_benchmark_archive_add"
                   and event["status"] == "MAINTENANCE_INCOMPLETE" for event in events)


def test_u2_live_mem0_shares_twelve_host_generations_and_keeps_completed_business(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import ExitStack

    from langchain_core.tools import tool
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.store.memory import InMemoryStore

    from milai_lab.baselines.langmem_agent import invoke_public_message
    from milai_lab.baselines.langmem_benchmark import merit_adapters
    from milai_lab.harness.contextual_artifacts import write_json
    from milai_lab.providers.langmem_chat import VLLMChatModel

    cache = Path(os.environ.get("FASTEMBED_CACHE_PATH",
                                "artifacts/external-memory-v26/cache/fastembed")).resolve()
    assert cache.is_dir()
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(cache))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    sent: list[dict[str, Any]] = []
    effects: list[str] = []
    events: list[dict[str, Any]] = []

    @tool
    def business() -> str:
        """Perform one actual synthetic partial action."""
        effects.append("actual side effect")
        return '{"ok":false,"status":"partial","actual_id":"REAL-ID"}'

    def send(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [
                {"index": index, "embedding": [0.02] * 1024}
                for index, _ in enumerate(body["input"])], "usage": {"total_tokens": 3}})
        sent.append(body)
        number = len(sent)
        if number < 12:
            name = "business" if number == 1 else "read_history"
            args = {} if number == 1 else {"cursor": 0, "max_bytes": 16384}
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"actual-{number}", "type": "function", "function": {
                    "name": name, "arguments": json.dumps(args)}}]}
        else:
            message = {"role": "assistant", "content": "Actual partial REAL-ID retained."}
        return httpx.Response(200, json={"id": f"mock-{number}", "object": "chat.completion",
            "model": "host", "created": 1, "choices": [{"index": 0,
            "finish_reason": "tool_calls" if number < 12 else "stop", "message": message}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})

    write_json(tmp_path / "run_manifest.json", {"identity": {
        "run_id": "r", "arm_id": "mem0_native"}})
    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
        generation_tokens=None, embedding_tokens=None), tmp_path / "budget.json")
    with VLLMClient(VLLMConfig("http://mock/v1/", "host", tool_mode="native",
        max_tokens=4096, enable_thinking=False), budget=budget, emit=events.append,
        transport=httpx.MockTransport(send)) as host, VLLMClient(VLLMConfig(
            "http://mock/v1/", "bge-m3"), budget=budget, emit=events.append,
            transport=httpx.MockTransport(send)) as embed, SqliteSaver.from_conn_string(
                str(tmp_path / "checkpoints.sqlite")) as saver, ExitStack() as stack:
        model = VLLMChatModel(client=host)
        rt = SimpleNamespace(model=model, store=InMemoryStore(), checkpointer=saver,
                             observer=None, embedding_client=embed)
        config = {"host": {"timeout": 180}, "embedding": {"timeout": 180},
                  "history": {"page_max_bytes": 16384}}
        factory, completed = merit_adapters(rt, tmp_path, "r", "mem0_native", config,
                                            stack, backend="mem0_native")
        agent = factory(model, rt.store, saver, [business], user_id="owner",
                        environment_rules="Synthetic original domain", observer=None)
        scope = FoundationScope("r", "mem0_native", "owner", "public-turn")
        messages = invoke_public_message(agent, model, scope, "Perform the action once.", 0)
        completed(agent, scope, 0, "COMPLETED", [])
        assert messages[-1].content == "Actual partial REAL-ID retained."
        assert effects == ["actual side effect"] and model.calls_in_message == 12
        receipt = next(event for event in events if event.get("event") == "benchmark_public_turn")
        assert receipt["status"] == "COMPLETED"
        assert receipt["maintenance"]["status"] == "MAINTENANCE_INCOMPLETE"
        assert receipt["maintenance"]["admission_rejections"]
        assert len(sent) == budget.state["generation_requests"] == 12
        assert all("benchmark_phase" not in json.dumps(request) for request in sent)


def test_official_mem0_add_search_sparse_entities_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEM0_TELEMETRY", "False")
    importlib.import_module("mem0")
    importlib.import_module("spacy")
    cache = Path("artifacts/external-memory-v26/cache/fastembed").resolve()
    assert cache.is_dir(), "The isolated Mem0 sparse-model cache is not installed"
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
