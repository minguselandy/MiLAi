"""Pinned SimpleMem core; native stages with metered injected providers."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from openai.types.chat import ChatCompletion

from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient

SOURCE_COMMIT = "db80b6a7c591e0ea730a058e9f5fc4eb06572299"
SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}
SEARCH_DESCRIPTION = (
    "Search this user's SimpleMem text memories with native planning and reflection."
)
POLICY = {
    "source_commit": SOURCE_COMMIT,
    "window_size": 40,
    "overlap_size": 2,
    "semantic_top_k": 25,
    "keyword_top_k": 5,
    "structured_top_k": 5,
    "enable_planning": True,
    "enable_reflection": True,
    "max_reflection_rounds": 2,
    "enable_parallel_processing": False,
    "enable_parallel_retrieval": False,
    "stage_temperature": "native",
    "generation_max_tokens": 4096,
    "enable_thinking": False,
    "streaming": False,
    "embedding_model": "bge-m3",
    "embedding_dimension": 1024,
    "normalize_embeddings": True,
    "writer_cadence": "archive_final_flush_or_closed_public_turn_flush",
    "archive_generation_limit": 12,
    "query_generation_limit": 12,
    "live_generation_limit": 12,
    "material_max_chars": 16000,
    "reader": "common_benchmark_reader",
    "retry_policy": "native_finite_retries_each_actual_request_charged_no_wrapper_retry",
}


def validate_simplemem(config: dict[str, Any]) -> dict[str, Any]:
    policy = config.get("second_external", {}).get("simplemem_text")
    if (
        not isinstance(policy, dict)
        or set(policy) != {*POLICY, "source_root"}
        or {key: policy[key] for key in POLICY} != POLICY
        or not isinstance(policy["source_root"], str)
        or config["embedding"]["model"] != "bge-m3"
        or config.get("embedding_dimension") != 1024
    ):
        raise ValueError("SIMPLEMEM_POLICY_INVALID")
    return policy


def dependency_identity(policy: dict[str, Any]) -> dict[str, Any]:
    root = Path(policy["source_root"]).resolve()
    actual = subprocess.check_output(  # noqa: S603 - fixed read-only command
        [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if actual != SOURCE_COMMIT:
        raise ValueError("SIMPLEMEM_SOURCE_NOT_PINNED")
    if subprocess.run(  # noqa: S603 - fixed read-only source verification
        [
            shutil.which("git") or "/usr/bin/git",
            "diff",
            "--quiet",
            SOURCE_COMMIT,
            "--",
            "simplemem",
        ],
        cwd=root,
        check=False,
    ).returncode:
        raise ValueError("SIMPLEMEM_SOURCE_CHANGED")
    sources = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "simplemem").rglob("*.py"))
    }
    return {
        "source_root": str(root),
        "source_commit": actual,
        "source_sha256": sources,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "lancedb",
                "pylance",
                "pyarrow",
                "dateparser",
                "tantivy",
                "numpy",
                "pydantic",
                "openai",
            )
        },
        "pipeline": "pinned core writer/LanceDB/Tantivy/planning/reflection; common final reader",
        "embedding_substitution": "bge-m3 API; normalized1024; no local encoder/fallback",
        "transport": "nonstreaming native finite retries; each HTTP shared Budget/admission",
    }


def entry_text(entry: dict[str, Any]) -> str:
    parts = ["Content: " + entry["lossless_restatement"]]
    for key, label in (
        ("timestamp", "Time"),
        ("location", "Location"),
        ("persons", "Persons"),
        ("entities", "Related Entities"),
        ("topic", "Topic"),
    ):
        value = entry.get(key)
        if value:
            parts.append(label + ": " + (", ".join(value) if isinstance(value, list) else value))
    return "\n".join(parts)


def material_rows(entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": entry["entry_id"], "value": {"content": entry_text(entry)}} for entry in entries]


class SimpleMemTextRuntime:
    """Only native components hold facts; outcomes are ephemeral operation observations."""

    def __init__(
        self,
        root: Path,
        run_id: str,
        arm: str,
        owner: str,
        host: VLLMClient,
        embed: VLLMClient,
        policy: dict[str, Any],
        *,
        admit_generation: Callable[[], None],
        archive_input_mode: str = "legacy",
    ) -> None:
        if archive_input_mode not in ("legacy", "trace_equal_v1"):
            raise ValueError("SIMPLEMEM_ARCHIVE_INPUT_MODE_INVALID")
        self.root, self.run_id, self.arm, self.owner = root, run_id, arm, owner
        self.host, self.embed, self.admit = host, embed, admit_generation
        self.archive_input_mode = archive_input_mode
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.sequence = 0
        self.dependency = dependency_identity(policy)
        self.policy = policy
        source = self.dependency["source_root"]
        package_dir = Path(source) / "simplemem"
        if "simplemem" not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                "simplemem",
                package_dir / "__init__.py",
                submodule_search_locations=[str(package_dir)],
            )
            if spec is None or spec.loader is None:
                raise ValueError("SIMPLEMEM_PACKAGE_SPEC_MISSING")
            package = importlib.util.module_from_spec(spec)
            sys.modules["simplemem"] = package
            spec.loader.exec_module(package)
        modules = {
            name: importlib.import_module("simplemem.core." + name)
            for name in (
                "memory_builder",
                "hybrid_retriever",
                "utils.llm_client",
                "database.vector_store",
                "database.vector_store_backend",
                "models.memory_entry",
                "settings",
            )
        }
        module_file = modules["memory_builder"].__file__
        if module_file is None or Path(module_file).resolve() != Path(source) / (
            "simplemem/core/memory_builder.py"
        ):
            raise ValueError("SIMPLEMEM_IMPORT_SOURCE_CHANGED")
        settings = modules["settings"].settings
        for name, value in {
            "OVERLAP_SIZE": 2,
            "USE_JSON_FORMAT": False,
            "WINDOW_SIZE": 40,
            "SEMANTIC_TOP_K": 25,
            "KEYWORD_TOP_K": 5,
            "STRUCTURED_TOP_K": 5,
        }.items():
            if getattr(settings, name) != value:
                raise ValueError("SIMPLEMEM_AMBIENT_SETTINGS_CHANGED")
        binding = {
            "run_id": run_id,
            "arm": arm,
            "owner": owner,
            "policy": policy,
            "dependency": self.dependency,
        }
        if archive_input_mode != "legacy":
            binding["archive_input_mode"] = archive_input_mode
        scope_path = root / "scope.json"
        if scope_path.exists():
            if read_json(scope_path) != binding:
                raise ValueError("SIMPLEMEM_SCOPE_CHANGED")
        elif root.exists() and any(root.iterdir()):
            raise ValueError("SIMPLEMEM_DATABASE_DIRTY")
        else:
            write_json(scope_path, binding)
        outer = self
        native_llm = modules["utils.llm_client"].LLMClient

        class ChatBridge:
            def create(self, **kwargs: Any) -> Any:
                if set(kwargs) - {"model", "messages", "temperature", "response_format"}:
                    raise ValueError("SIMPLEMEM_PROVIDER_OPTIONS_CHANGED")
                if kwargs["model"] != host.config.model:
                    raise ValueError("SIMPLEMEM_PROVIDER_MODEL_CHANGED")
                with outer.lock:
                    original = host.config
                    try:
                        outer.admit()
                        host.config = replace(original, temperature=kwargs["temperature"])
                        receipt = host.chat(
                            kwargs["messages"], response_format=kwargs.get("response_format")
                        )
                        result = ChatCompletion.model_validate(receipt)
                        if result.choices[0].finish_reason != "stop":
                            raise ValueError("SIMPLEMEM_GENERATION_INCOMPLETE")
                        outer.observe("provider_attempt", outcome="success")
                        return result
                    except Exception as error:
                        sticky = (
                            isinstance(error, CapacityExceeded)
                            or "CAPACITY_EXCEEDED" in str(error)
                            or "BudgetExceeded" == type(error).__name__
                        )
                        outer.observe(
                            "provider_attempt",
                            outcome="error",
                            sticky=sticky,
                            error_type=type(error).__name__,
                            reason=str(error),
                        )
                        raise
                    finally:
                        host.config = original

        class LLM(native_llm):  # type: ignore[valid-type,misc] # runtime pinned SDK class
            def __init__(self) -> None:
                self.model, self.base_url = host.config.model, host.config.base_url
                self.enable_thinking, self.use_streaming = False, False
                self.client = SimpleNamespace(chat=SimpleNamespace(completions=ChatBridge()))

            def chat_completion(self, *args: Any, **kwargs: Any) -> str:
                start = len(outer.events)
                try:
                    value = super().chat_completion(*args, **kwargs)
                except Exception as error:
                    outer.observe(
                        "completion", outcome="exhausted", error_type=type(error).__name__
                    )
                    raise
                attempts = outer.events[start:]
                outer.observe(
                    "completion",
                    outcome="recovered_retry"
                    if any(event.get("outcome") == "error" for event in attempts)
                    else "success",
                )
                return str(value)

            def extract_json(self, value: str) -> Any:
                try:
                    parsed = super().extract_json(value)
                except Exception as error:
                    outer.observe("parse", outcome="error", error_type=type(error).__name__)
                    raise
                outer.observe("parse", outcome="success", parsed=parsed)
                return parsed

        class Embeddings:
            dimension = 1024

            def encode_documents(self, texts: list[str]) -> Any:
                return self.encode(texts, False)

            def encode_single(self, text: str, is_query: bool = False) -> Any:
                return self.encode([text], is_query)[0]

            def encode(self, texts: list[str], is_query: bool) -> Any:
                with outer.lock:
                    try:
                        values = np.asarray(
                            embed.embed(texts, embed.config.model), dtype=np.float32
                        )
                        if (
                            values.shape != (len(texts), 1024)
                            or not np.isfinite(values).all()
                            or (np.linalg.norm(values, axis=1) == 0).any()
                        ):
                            raise ValueError("SIMPLEMEM_EMBEDDING_INVALID")
                        values /= np.linalg.norm(values, axis=1)[:, None]
                        outer.observe("embedding", outcome="success", is_query=is_query)
                        return values
                    except Exception as error:
                        outer.observe("embedding", outcome="error", error_type=type(error).__name__)
                        raise

        native_backend = modules["database.vector_store_backend"].LanceDBVectorStoreBackend

        class Backend(native_backend):  # type: ignore[valid-type,misc] # runtime pinned SDK class
            def _init_fts_index(self) -> None:
                super()._init_fts_index()
                if not self._fts_initialized:
                    outer.observe("fts", outcome="error", native_fallback=True)

        def measured(method: Any, channel: str) -> Any:
            def invoke(*args: Any, **kwargs: Any) -> Any:
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                try:
                    value = method(*args, **kwargs)
                except Exception as error:
                    outer.observe(
                        channel,
                        outcome="error",
                        error_type=type(error).__name__,
                        calls=1,
                        response_logical_bytes=None,
                        cpu_ns=time.process_time_ns() - cpu,
                        wall_ns=time.perf_counter_ns() - wall,
                    )
                    raise
                outer.observe(
                    channel,
                    outcome="success",
                    calls=1,
                    logical_bytes=len(
                        json.dumps(
                            args if channel == "insert" else value, default=str, ensure_ascii=False
                        ).encode()
                    ),
                    cpu_ns=time.process_time_ns() - cpu,
                    wall_ns=time.perf_counter_ns() - wall,
                )
                return value

            return invoke

        backend = Backend(str(root / "lancedb"), "memory_entries", 1024)
        for method in (
            "insert",
            "semantic_search",
            "keyword_search",
            "structured_search",
            "get_all",
        ):
            setattr(backend, method, measured(getattr(backend, method), method))
        self.vector = modules["database.vector_store"].VectorStore(
            embedding_model=Embeddings(), backend_factory=lambda _dimension: backend
        )
        self.llm = LLM()
        native_builder = modules["memory_builder"].MemoryBuilder

        class Builder(native_builder):  # type: ignore[valid-type,misc] # runtime pinned SDK class
            def _parse_llm_response(self, *args: Any, **kwargs: Any) -> Any:
                try:
                    value = super()._parse_llm_response(*args, **kwargs)
                except Exception as error:
                    outer.observe("writer_parse", outcome="error", error_type=type(error).__name__)
                    raise
                outer.observe("writer_parse", outcome="success", empty=not value)
                return value

            def _generate_memory_entries(self, *args: Any, **kwargs: Any) -> Any:
                start = len(outer.events)
                value = super()._generate_memory_entries(*args, **kwargs)
                attempts = [
                    event
                    for event in outer.events[start:]
                    if event["kind"] in {"writer_parse", "completion"}
                ]
                bad = bool(
                    attempts and attempts[-1]["outcome"] not in {"success", "recovered_retry"}
                )
                outer.observe(
                    "writer_window",
                    outcome="empty_due_to_error"
                    if bad
                    else "legal_empty"
                    if not value
                    else "success",
                    native_fallback=bad,
                    recovered_retry=not bad
                    and any(event["outcome"] in {"error", "exhausted"} for event in attempts),
                )
                return value

        self.builder = Builder(
            self.llm, self.vector, window_size=40, enable_parallel_processing=False
        )
        native_retriever = modules["hybrid_retriever"].HybridRetriever
        self.retriever = native_retriever(
            self.llm,
            self.vector,
            semantic_top_k=25,
            keyword_top_k=5,
            structured_top_k=5,
            enable_planning=True,
            enable_reflection=True,
            max_reflection_rounds=2,
            enable_parallel_retrieval=False,
        )
        # Observe native stage fallbacks without changing their return values or catches.
        for method in (
            "_analyze_information_requirements",
            "_generate_targeted_queries",
            "_analyze_query",
            "_analyze_information_completeness",
            "_generate_missing_info_queries",
        ):
            delegate = getattr(self.retriever, method)

            def stage(
                *args: Any, _delegate: Any = delegate, _name: str = method, **kwargs: Any
            ) -> Any:
                start = len(outer.events)
                result = _delegate(*args, **kwargs)
                attempts = [
                    event
                    for event in outer.events[start:]
                    if event["kind"] in {"parse", "completion"}
                ]
                bad = bool(
                    attempts and attempts[-1]["outcome"] not in {"success", "recovered_retry"}
                )
                parsed = [event["parsed"] for event in attempts if "parsed" in event]
                if parsed and _name in {
                    "_generate_targeted_queries",
                    "_generate_missing_info_queries",
                    "_analyze_information_completeness",
                }:
                    field = {
                        "_generate_targeted_queries": "queries",
                        "_generate_missing_info_queries": "targeted_queries",
                        "_analyze_information_completeness": "assessment",
                    }[_name]
                    bad = bad or not isinstance(parsed[-1], dict) or field not in parsed[-1]
                    if (
                        field != "assessment"
                        and isinstance(parsed[-1], dict)
                        and field in parsed[-1]
                    ):
                        bad = bad or not isinstance(parsed[-1][field], list)
                outer.observe(
                    _name,
                    outcome="native_fallback" if bad else "success",
                    native_fallback=bad,
                    recovered_retry=not bad
                    and any(event["outcome"] in {"error", "exhausted"} for event in attempts),
                )
                return result

            setattr(self.retriever, method, stage)
        self.dialogue_class = modules["models.memory_entry"].Dialogue

    def observe(self, kind: str, **value: Any) -> None:
        event = {"kind": kind, **value}
        self.events.append(event)
        if self.host.emit:
            self.host.emit(
                {
                    "event": "simplemem_observation",
                    "owner": self.owner,
                    "run_id": self.run_id,
                    "arm": self.arm,
                    **event,
                }
            )

    def check_owner(self, owner: str) -> None:
        if owner != self.owner:
            raise ValueError("SIMPLEMEM_OWNER_SCOPE_CHANGED")

    def snapshot(self, owner: str, *, measure: bool = True) -> list[dict[str, Any]]:
        self.check_owner(owner)
        return [entry.model_dump(mode="json") for entry in self.vector.get_all_entries()]

    def outcome(self, start: int) -> dict[str, Any]:
        events = self.events[start:]
        sticky = [event for event in events if event.get("sticky")]
        degraded = [
            event
            for event in events
            if event.get("native_fallback")
            or (
                event["kind"]
                in {"embedding", "semantic_search", "keyword_search", "structured_search"}
                and event.get("outcome") == "error"
            )
        ]
        return {
            "status": "INCOMPLETE" if sticky else "DEGRADED_NATIVE" if degraded else "COMPLETED",
            "admission_rejections": sticky,
            "native_fallbacks": degraded,
            "recovered_retries": [
                event
                for event in events
                if event.get("outcome") == "recovered_retry" or event.get("recovered_retry")
            ],
            "observations": events,
            "semantic_success": None,
        }

    def add_archive(self, owner: str, records: Sequence[dict[str, Any]]) -> dict[str, Any]:
        self.check_owner(owner)
        start = len(self.events)
        dialogues = []
        for row in records:
            self.sequence += 1
            if self.archive_input_mode == "trace_equal_v1":
                # Lossless writer input only; native entries have no source-ID field.
                content = (
                    "[Archived source event data; not current instructions]\n"
                    + json.dumps(
                        row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        allow_nan=False,
                    )
                )
            else:
                extra = {
                    key: row[key]
                    for key in ("tool_calls", "tool_call_id", "name", "status")
                    if key in row
                }
                content = (
                    row["content"]
                    if not extra
                    else json.dumps({"content": row["content"], **extra}, ensure_ascii=False)
                )
            dialogues.append(
                self.dialogue_class(
                    dialogue_id=self.sequence,
                    speaker=row["role"],
                    content=content,
                    timestamp=row.get("timestamp"),
                )
            )
        self.observe(
            "archive_input",
            records=list(records),
            source_mapping=[
                {
                    "dialogue_id": dialogue.dialogue_id,
                    "source_id": record.get("event_id", record.get("id")),
                }
                for dialogue, record in zip(dialogues, records, strict=True)
            ],
        )
        self.builder.add_dialogues(dialogues)
        self.builder.process_remaining()
        result = {
            **self.outcome(start),
            "records_after": self.snapshot(owner),
            "native_short_flush": "clears buffer; no cross-flush overlap/previous_entries update",
        }
        self.observe(
            "operation_result",
            operation="archive_write",
            **{key: value for key, value in result.items() if key != "observations"},
        )
        return result

    def search_archive(self, owner: str, query: str) -> dict[str, Any]:
        self.check_owner(owner)
        start = len(self.events)
        entries = self.retriever.retrieve(query)
        result = {
            **self.outcome(start),
            "query": query,
            "results": [entry.model_dump(mode="json") for entry in entries],
        }
        self.observe(
            "operation_result",
            operation="retrieval",
            **{key: value for key, value in result.items() if key != "observations"},
        )
        return result

    def archive_tools(self, scope: FoundationScope) -> list[StructuredTool]:
        def search_memory(query: str, config: RunnableConfig) -> str:
            actual = config["configurable"]
            if (actual["foundation_run_id"], actual["arm_id"], actual["user_id"]) != (
                self.run_id,
                self.arm,
                self.owner,
            ):
                raise ValueError("SIMPLEMEM_OWNER_SCOPE_CHANGED")
            result = self.search_archive(scope.user_id, query)
            return json.dumps(
                {
                    "query": result["query"],
                    "status": result["status"],
                    "results": result["results"],
                },
                ensure_ascii=False,
            )

        return [
            StructuredTool.from_function(
                func=search_memory,
                name="search_memory",
                description=SEARCH_DESCRIPTION,
                args_schema=SEARCH_SCHEMA,
                infer_schema=False,
            )
        ]

    def close(self) -> None:
        # LanceDB owns local handles; no SDK provider client was created by this adapter.
        pass


__all__ = [
    'POLICY',
    'SEARCH_DESCRIPTION',
    'SEARCH_SCHEMA',
    'SOURCE_COMMIT',
    'Any',
    'Callable',
    'CapacityExceeded',
    'ChatCompletion',
    'FoundationScope',
    'Path',
    'RunnableConfig',
    'Sequence',
    'SimpleMemTextRuntime',
    'SimpleNamespace',
    'StructuredTool',
    'VLLMClient',
    'dependency_identity',
    'entry_text',
    'hashlib',
    'importlib',
    'json',
    'material_rows',
    'np',
    'read_json',
    'replace',
    'shutil',
    'subprocess',
    'sys',
    'threading',
    'time',
    'validate_simplemem',
    'write_json',
]
