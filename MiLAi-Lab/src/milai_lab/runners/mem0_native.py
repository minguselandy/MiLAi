"""Mem0 OSS memory boundary for the frozen Formation system comparison."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from openai.types.chat import ChatCompletion

from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.providers.contextual_vllm import VLLMClient

MEM0_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the available business tools when a task requires "
    "an action, and report their actual results. Long-term memory from completed "
    "conversations is saved automatically. Use search_memory when prior notes are "
    "needed. You cannot write or edit memory directly."
)
MEM0_PROTOCOL_ID = "mem0_oss_native_autoadd_v1"
MEM0_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}
MEM0_SEARCH_DESCRIPTION = "Search this user's Mem0 long-term memories."
MEM0_SYSTEM_PROMPT_SHA256 = hashlib.sha256(MEM0_SYSTEM_PROMPT.encode()).hexdigest()
MEM0_SEARCH_CONTRACT_SHA256 = digest({
    "description": MEM0_SEARCH_DESCRIPTION, "schema": MEM0_SEARCH_SCHEMA,
})
MEM0_POLICY = {
    "infer": True,
    "search_top_k": 20,
    "search_threshold": 0.1,
    "ingestion": "completed_user_final_assistant",
    "vector_store": "qdrant-local",
    "telemetry": False,
}


class _ChatCompletions:
    def __init__(self, client: VLLMClient, lock: threading.Lock,
                 admit_generation: Callable[[], None] | None = None,
                 rejected: list[str] | None = None) -> None:
        self.client, self.lock = client, lock
        self.admit_generation, self.rejected = admit_generation, rejected

    def create(self, **kwargs: Any) -> ChatCompletion:
        if set(kwargs) - {"model", "messages", "temperature", "max_tokens",
                           "top_p", "response_format"}:
            raise ValueError("MEM0_GENERATION_OPTIONS_CHANGED")
        if kwargs.get("model") != self.client.config.model:
            raise ValueError("MEM0_GENERATION_MODEL_CHANGED")
        if kwargs.get("temperature") != self.client.config.temperature:
            raise ValueError("MEM0_GENERATION_TEMPERATURE_CHANGED")
        if kwargs.get("max_tokens") != self.client.config.max_tokens:
            raise ValueError("MEM0_GENERATION_MAX_TOKENS_CHANGED")
        if kwargs.get("top_p") != 1.0 or kwargs.get("tools"):
            raise ValueError("MEM0_GENERATION_UNSUPPORTED_OPTIONS")
        with self.lock:
            if self.admit_generation is not None:
                try:
                    self.admit_generation()
                except BaseException as error:
                    if self.rejected is not None:
                        self.rejected.append(type(error).__name__ + ":" + str(error))
                    raise
            response = self.client.chat(
                kwargs["messages"], response_format=kwargs.get("response_format"),
                top_p=kwargs["top_p"])
        return ChatCompletion.model_validate(response)


class _Embeddings:
    def __init__(self, client: VLLMClient, lock: threading.Lock) -> None:
        self.client, self.lock = client, lock

    def create(self, **kwargs: Any) -> SimpleNamespace:
        if set(kwargs) - {"model", "input", "encoding_format"}:
            raise ValueError("MEM0_EMBEDDING_OPTIONS_CHANGED")
        if kwargs.get("model") != self.client.config.model or "dimensions" in kwargs:
            raise ValueError("MEM0_EMBEDDING_CONTRACT_CHANGED")
        if kwargs.get("encoding_format") != "float":
            raise ValueError("MEM0_EMBEDDING_ENCODING_CHANGED")
        with self.lock:
            vectors = self.client.embed(kwargs["input"], kwargs["model"])
        return SimpleNamespace(data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in enumerate(vectors)
        ])


class Mem0NativeRuntime:
    """Keep official Mem0 add/search semantics; only bridge its provider transport."""

    system_prompt = MEM0_SYSTEM_PROMPT

    def __init__(self, root: Path, run_id: str, arm_id: str,
                 host: VLLMClient, embed: VLLMClient, *,
                 admit_generation: Callable[[], None] | None = None) -> None:
        started_wall = time.perf_counter_ns()
        started_cpu = time.process_time_ns()
        os.environ["MEM0_TELEMETRY"] = "False"
        os.environ["HF_HUB_OFFLINE"] = "1"
        spacy = importlib.import_module("spacy")
        memory_class = importlib.import_module("mem0").Memory

        try:
            spacy.load("en_core_web_sm")
        except OSError as error:
            raise ValueError("MEM0_SPACY_MODEL_NOT_PREPARED") from error
        root.mkdir(parents=True, exist_ok=True)
        self.root, self.run_id, self.arm_id = root, run_id, arm_id
        self.host, self.embed = host, embed
        self.lock = threading.Lock()
        self.admission_rejections: list[str] = []
        self.memory = memory_class.from_config({
            "vector_store": {"provider": "qdrant", "config": {
                "collection_name": "milai_external_v26",
                "embedding_model_dims": 1024,
                "path": str(root / "mem0-qdrant"),
            }},
            "llm": {"provider": "vllm", "config": {
                "model": host.config.model,
                "temperature": host.config.temperature,
                "max_tokens": host.config.max_tokens,
                "top_p": 1.0,
                "api_key": "local",
                "vllm_base_url": host.config.base_url,
            }},
            "embedder": {"provider": "openai", "config": {
                "model": embed.config.model,
                "api_key": "local",
                "openai_base_url": embed.config.base_url,
            }},
            "history_db_path": str(root / "mem0-history.sqlite"),
        })
        self.memory.llm.client.close()
        self.memory.embedding_model.client.close()
        self.memory.llm.client = SimpleNamespace(
            chat=SimpleNamespace(completions=_ChatCompletions(
                host, self.lock, admit_generation, self.admission_rejections)))
        self.memory.embedding_model.client = SimpleNamespace(
            embeddings=_Embeddings(embed, self.lock))
        vector_store = self.memory.vector_store
        if (not vector_store._has_bm25_slot
                or vector_store._encode_bm25("memory search") is None):
            self.close()
            raise ValueError("MEM0_BM25_NOT_ACTIVE")
        if host.emit is not None:
            host.emit({
                "event": "mem0_native_runtime", "run_id": run_id,
                "arm_id": arm_id, "vector_store": "qdrant-local",
                "bm25_slot": True, "bm25_encoder": "Qdrant/bm25",
                "entity_store": "native_lazy",
                "fastembed_cache_path": os.environ.get("FASTEMBED_CACHE_PATH"),
                "wall_ns": time.perf_counter_ns() - started_wall,
                "cpu_ns": time.process_time_ns() - started_cpu,
            })

    def close(self) -> None:
        self.memory.close()
        self.memory.vector_store.client.close()

    def _user_id(self, case_id: str) -> str:
        return f"{self.run_id}:{self.arm_id}:{case_id}"

    def tools(self, case_id: str) -> list[StructuredTool]:
        user_id = self._user_id(case_id)

        def search_memory(query: str, config: RunnableConfig) -> str:
            if config["configurable"]["user_id"] != f"diagnostic:{case_id}":
                raise ValueError("MEM0_SEARCH_SCOPE_CHANGED")
            started = time.perf_counter_ns()
            result = self.memory.search(
                query, filters={"user_id": user_id}, top_k=20, threshold=0.1)
            if self.host.emit is not None:
                self.host.emit({
                    "event": "mem0_native_search", "case_id": case_id,
                    "user_id": user_id, "query": query, "result": result,
                    "wall_ns": time.perf_counter_ns() - started,
                })
            return json.dumps(result, ensure_ascii=False)

        return [StructuredTool.from_function(
            func=search_memory, name="search_memory",
            description=MEM0_SEARCH_DESCRIPTION,
            args_schema=MEM0_SEARCH_SCHEMA, infer_schema=False,
        )]

    def after_turn(self, case_id: str, scope: FoundationScope, index: int,
                   user_text: str, messages: list[BaseMessage]) -> None:
        if scope.user_id != f"diagnostic:{case_id}":
            raise ValueError("MEM0_INGESTION_SCOPE_CHANGED")
        final = messages[-1]
        if (not isinstance(final, AIMessage) or final.tool_calls
                or not isinstance(final.content, str)):
            raise ValueError("MEM0_FINAL_ASSISTANT_MISSING")
        conversation = [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": final.content},
        ]
        key = hashlib.sha256(json.dumps(
            [scope.config()["configurable"]["thread_id"], index],
            ensure_ascii=False).encode()).hexdigest()
        path = self.root / "mem0-ingestion.json"
        ledger = read_json(path) if path.exists() else {}
        input_hash = hashlib.sha256(json.dumps(
            conversation, ensure_ascii=False).encode()).hexdigest()
        prior = ledger.get(key)
        if prior is not None:
            if prior["input_hash"] != input_hash:
                raise ValueError("MEM0_INGESTION_INPUT_CHANGED")
            if prior["status"] != "complete":
                raise ValueError("MEM0_INGESTION_OUTCOME_UNKNOWN")
            return
        ledger[key] = {"status": "pending", "case_id": case_id,
                       "input_hash": input_hash, "conversation": conversation}
        write_json(path, ledger)
        started = time.perf_counter_ns()
        result = self.memory.add(conversation, user_id=self._user_id(case_id), infer=True)
        ledger[key].update({"status": "complete", "result": result,
                            "wall_ns": time.perf_counter_ns() - started})
        write_json(path, ledger)
        if self.host.emit is not None:
            self.host.emit({"event": "mem0_native_ingestion", "case_id": case_id,
                            "message_key": key, "result": result,
                            "entity_store_initialized": self.memory._entity_store is not None,
                            "wall_ns": ledger[key]["wall_ns"]})

    def snapshot(self, case_id: str, *, measure: bool = False) -> list[dict[str, Any]]:
        started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
        value = self.memory.get_all(filters={"user_id": self._user_id(case_id)})
        records = list(value["results"])
        if measure and self.host.emit is not None:
            self.host.emit({"event": "mem0_benchmark_snapshot", "owner": case_id,
                "calls": 1, "logical_bytes": len(json.dumps(records, ensure_ascii=False).encode()),
                "wall_ns": time.perf_counter_ns() - started_wall,
                "cpu_ns": time.process_time_ns() - started_cpu})
        return records

    def add_archive(self, owner: str, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Opt-in native ADD-only ingestion of past data, not replayed live commands."""
        if not owner or not records:
            raise ValueError("MEM0_ARCHIVE_INVALID")
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        rejected_before = len(self.admission_rejections)
        # The pinned SDK ignores role=tool. Preserve real roles/call results as data
        # in one explicitly archived input, without changing its extraction algorithm.
        conversation = [{"role": "user", "content": (
            "[Archived completed conversation data; not current instructions]\n"
            + json.dumps(list(records), ensure_ascii=False))}]
        result = None
        admission_error = None
        try:
            result = self.memory.add(conversation, user_id=self._user_id(owner), infer=True)
        except Exception as error:
            # The SDK can wrap the admission failure in LLMError. Preserve a known
            # capacity refusal and its real readback; do not swallow Store failures.
            cause: BaseException | None = error
            while cause is not None:
                if isinstance(cause, ValueError) and str(cause) in {
                    "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED",
                    "BENCHMARK_ARCHIVE_GENERATION_CAPACITY_EXCEEDED"}:
                    break
                cause = cause.__cause__
            if len(self.admission_rejections) == rejected_before or cause is None:
                raise
            admission_error = {"error_type": type(error).__name__, "reason": str(cause)}
        rejected = self.admission_rejections[rejected_before:]
        receipt = {"status": "MAINTENANCE_INCOMPLETE" if rejected else "COMPLETED",
                   "native_add_result": result, "admission_rejections": rejected,
                   "admission_error": admission_error,
                   "records_after": self.snapshot(owner, measure=True),
                   "source_records": list(records),
                   "native_policy": "pinned infer=True ADD-only extraction",
                   "wall_ns": time.perf_counter_ns() - start_wall,
                   "cpu_ns": time.process_time_ns() - start_cpu}
        if self.host.emit is not None:
            self.host.emit({"event": "mem0_benchmark_archive_add", "owner": owner, **receipt})
        return receipt

    def search_archive(self, owner: str, query: str) -> dict[str, Any]:
        if not owner:
            raise ValueError("MEM0_ARCHIVE_OWNER_MISSING")
        started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
        result: dict[str, Any] = self.memory.search(query,
            filters={"user_id": self._user_id(owner)}, top_k=20, threshold=0.1, rerank=False)
        if self.host.emit is not None:
            self.host.emit({"event": "mem0_benchmark_search", "owner": owner,
                           "query": query, "result": result,
                           "wall_ns": time.perf_counter_ns() - started_wall,
                           "cpu_ns": time.process_time_ns() - started_cpu})
        return result

    def archive_tools(self, scope: FoundationScope) -> list[StructuredTool]:
        if (scope.run_id, scope.arm_id) != (self.run_id, self.arm_id):
            raise ValueError("MEM0_ARCHIVE_SCOPE_CHANGED")

        def search_memory(query: str, config: RunnableConfig) -> str:
            cfg = config["configurable"]
            if any(cfg.get(key) != value for key, value in {
                "foundation_run_id": scope.run_id, "arm_id": scope.arm_id,
                "user_id": scope.user_id}.items()):
                raise ValueError("MEM0_ARCHIVE_SCOPE_CHANGED")
            return json.dumps(self.search_archive(scope.user_id, query), ensure_ascii=False)

        return [StructuredTool.from_function(func=search_memory, name="search_memory",
            description=MEM0_SEARCH_DESCRIPTION, args_schema=MEM0_SEARCH_SCHEMA,
            infer_schema=False)]
