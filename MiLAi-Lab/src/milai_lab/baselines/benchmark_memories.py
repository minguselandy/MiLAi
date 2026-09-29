"""U2 archive backends: complete history, actual rolling summary and raw hybrid RAG."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from milai_lab.harness.contextual_artifacts import digest, read_json, write_json
from milai_lab.integrations.memory.mem0 import MEM0_SOURCE_COMMIT as MEM0_SOURCE_COMMIT
from milai_lab.integrations.memory.mem0 import mem0_dependency_identity as mem0_dependency_identity
from milai_lab.methods.contextual_memory.retrieval import IndexEntry, hybrid_order
from milai_lab.methods.local_state_attention.controller import ControlResponseError
from milai_lab.methods.local_state_attention.summary import parse_summary, summary_request
from milai_lab.providers.contextual_capacity import CapacityExceeded

U2_ARMS = {"full_history", "strong_raw_rag", "rolling_summary", "ordinary_milai", "mem0_native",
           "simplemem_text"}
SUMMARY_POLICY = {"window_completed_turns": 2, "content_max_chars": 16000, "max_tokens": 2048}
RAG_POLICY = {"chunk_chars": 2048, "chunk_step": 1792, "bm25_k1": 1.2,
              "bm25_b": 0.75, "rrf_k": 60, "top_k": 10, "material_max_chars": 16000}
MEM0_POLICY = {"infer": True, "top_k": 20, "threshold": 0.1, "rerank": False}
SUMMARY_CAPACITY_CONTRACT = "one attempt per complete archive batch or public turn; shared live 12"


def validate_u2(config: dict[str, Any]) -> None:
    policy = config.get("benchmark_memory")
    if (not isinstance(policy, dict) or policy != {
        "summary": SUMMARY_POLICY, "raw_rag": RAG_POLICY, "mem0": MEM0_POLICY}
            or config.get("history_mode") != "archive_access"
            or config.get("history", {}).get("enabled") is not True):
        raise ValueError("BENCHMARK_U2_CONFIG_INVALID")


def backend_identity(arm: str) -> dict[str, Any]:
    if arm not in U2_ARMS | {"raw_dialogue"}:
        raise ValueError("BENCHMARK_U2_ARM_INVALID")
    if arm == "simplemem_text":
        from milai_lab.integrations.memory.simplemem import POLICY

        return {"profile": "unified_u2_second_external", "backend": arm, "policy": POLICY,
                "query_policy": "current Human; native planning/reflection; shared12 with reader",
                "write": "complete closed past turn; native final flush; no wrapper retry",
                "reader": "common benchmark reader; native AnswerGenerator replaced"}
    return {"profile": "unified_u2", "backend": arm,
            "summary": SUMMARY_POLICY, "raw_rag": RAG_POLICY, "mem0": MEM0_POLICY,
            "summary_capacity": SUMMARY_CAPACITY_CONTRACT,
            "archive_generation_limits": {"ordinary": 12, "mem0_add": 12,
                                          "summary_per_batch": 1},
            "live_generation_limit": "12 shared task/summary/Mem0 generations",
            "mem0_write": "pinned infer=True ADD-only; closed past data",
            "query_policy": "complete current public Human only",
            "raw_history_escape": "same lawful owner read_history; actual escapes traced"}




@contextmanager
def phase(client: Any, name: str) -> Iterator[None]:
    if client.emit is not None:
        client.emit({"event": "benchmark_phase", "phase": name})
    try:
        yield
    finally:
        if client.emit is not None:
            client.emit({"event": "benchmark_phase", "phase": "task_host"})


@contextmanager
def summary_output(client: Any) -> Iterator[Any]:
    """Reuse the same HTTP client and Budget, restoring its Host config on every exit."""
    original = client.config
    client.config = replace(original, max_tokens=2048)
    try:
        yield client
    finally:
        client.config = original


class GenerationAdmission:
    """An archive-only call cap; live adapters instead share the actual Host counter."""

    def __init__(self, limit: int = 12) -> None:
        self.limit, self.calls = limit, 0

    def __call__(self) -> None:
        if self.calls >= self.limit:
            raise ValueError("BENCHMARK_ARCHIVE_GENERATION_CAPACITY_EXCEEDED")
        self.calls += 1


def archived_turns(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]],
                                                             list[dict[str, Any]]]:
    """Mechanical role boundaries only; never interpret archived text as commands."""
    turns: list[dict[str, Any]] = []
    unclosed: list[dict[str, Any]] = []
    starts = [index for index, row in enumerate(records) if row["role"] == "user"]
    if not starts:
        return [], list(records)
    if starts[0]:
        unclosed.extend(records[:starts[0]])
    for start, end in zip(starts, [*starts[1:], len(records)], strict=True):
        rows = list(records[start:end])
        if rows[-1]["role"] == "assistant":
            turns.append({"ordinal": len(turns), "messages": rows,
                          "source_ids": [row["event_id"] for row in rows]})
        else:
            unclosed.extend(rows)
    return turns, unclosed


def rolling_archive(client: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Capacity-bounded whole-turn batches; the question cannot enter this interface."""
    turns, unclosed = archived_turns(records)
    older, recent = turns[:-2], turns[-2:]
    summary, cursor = "", -1
    updates: list[dict[str, Any]] = []
    while cursor + 1 < len(older):
        chosen: list[dict[str, Any]] = []
        for row in older[cursor + 1:]:
            messages, _schema = summary_request(summary, [*chosen, row], 16000)
            try:
                if client.capacity is not None:
                    client.capacity.check(messages, 2048)
            except CapacityExceeded:
                if not chosen:
                    raise
                break
            chosen.append(row)
        messages, schema = summary_request(summary, chosen, 16000)
        started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            with phase(client, "summary_build"), summary_output(client):
                receipt = client.chat(messages, response_format=schema)
            updated = parse_summary(receipt, 16000)
        except (ControlResponseError, httpx.TimeoutException) as error:
            if client.emit is not None:
                client.emit({"event": "benchmark_summary_update", "status": "DEGRADED",
                    "source_turn_ordinals": [row["ordinal"] for row in chosen],
                    "covered_ordinal": cursor, "reason": type(error).__name__,
                    "wall_ns": time.perf_counter_ns() - started_wall,
                    "cpu_ns": time.process_time_ns() - started_cpu})
            return {"summary": summary, "covered_ordinal": cursor, "degraded": True,
                    "reason": str(error), "updates": updates,
                    "fallback": "complete original archive; final capacity still enforced"}
        cursor = chosen[-1]["ordinal"]
        summary = updated
        updates.append({"source_turn_ordinals": [row["ordinal"] for row in chosen],
                        "covered_ordinal": cursor, "summary": summary,
                        "wall_ns": time.perf_counter_ns() - started_wall,
                        "cpu_ns": time.process_time_ns() - started_cpu})
        if client.emit is not None:
            client.emit({"event": "benchmark_summary_update", "status": "COMMITTED",
                         **updates[-1]})
    return {"summary": summary, "covered_ordinal": cursor, "degraded": False,
            "updates": updates, "recent_turns": recent, "unclosed": unclosed}


@dataclass(frozen=True)
class RawChunk:
    id: str
    source_id: str
    start: int
    end: int
    content: str


def raw_chunks(records: Sequence[dict[str, Any]]) -> list[RawChunk]:
    chunks = []
    for record in records:
        source_id = str(record.get("event_id") or record.get("id") or digest(record))
        text = json.dumps(record, ensure_ascii=False)
        for start in range(0, len(text), 1792):
            end = min(start + 2048, len(text))
            chunks.append(RawChunk(digest([source_id, start, end, text[start:end]]),
                                   source_id, start, end, text[start:end]))
            if end == len(text):
                break
    return chunks


def raw_index(records: Sequence[dict[str, Any]], embed: Callable[[list[str]], list[list[float]]],
              previous: dict[str, Any] | None = None,
              ) -> dict[str, Any]:
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    chunks = raw_chunks(records)
    retained = {row["id"]: vector for row, vector in zip(
        previous["chunks"], previous["vectors"], strict=True)} if previous else {}
    pending = [row for row in chunks if row.id not in retained]
    added = embed([row.content for row in pending]) if pending else []
    if len(added) != len(pending):
        raise ValueError("BENCHMARK_RAW_VECTORS_INVALID")
    retained.update({row.id: vector for row, vector in zip(pending, added, strict=True)})
    vectors = [retained[row.id] for row in chunks]
    if len(vectors) != len(chunks):
        raise ValueError("BENCHMARK_RAW_VECTORS_INVALID")
    return {"chunks": [asdict(row) for row in chunks], "vectors": vectors,
            "source_sha256": digest(list(records)),
            "new_embedding_chunks": len(pending),
            "wall_ns": time.perf_counter_ns() - started_wall,
            "cpu_ns": time.process_time_ns() - started_cpu}


def raw_retrieve(index: dict[str, Any], query: str,
                 embed: Callable[[list[str]], list[list[float]]]) -> dict[str, Any]:
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    chunks = [RawChunk(**row) for row in index["chunks"]]
    if not chunks:
        return {"material": "", "delivered_ids": [], "omitted_ids": [], "ranked_ids": []}
    (query_vector,) = embed([query])
    order = hybrid_order([IndexEntry(row.id, row.id, row.content) for row in chunks],
                         query, index["vectors"], query_vector)
    chosen: list[dict[str, Any]] = []
    omitted = []
    for position in order[:10]:
        row = asdict(chunks[position])
        if len(json.dumps([*chosen, row], ensure_ascii=False)) > 16000:
            omitted.append(row["id"])
        else:
            chosen.append(row)
    return {"material": json.dumps(chosen, ensure_ascii=False) if chosen else "",
            "delivered_ids": [row["id"] for row in chosen], "omitted_ids": omitted,
            "ranked_ids": [chunks[position].id for position in order],
            "query": query, "wall_ns": time.perf_counter_ns() - started_wall,
            "cpu_ns": time.process_time_ns() - started_cpu}


def summary_material(built: dict[str, Any], records: list[dict[str, Any]]) -> str:
    if built["degraded"]:
        return "[SUMMARY DEGRADED - complete original archive fallback]\n" + json.dumps(
            records, ensure_ascii=False)
    return json.dumps({"model_generated_summary": built["summary"],
                       "covered_ordinal": built["covered_ordinal"],
                       "recent_completed_turns": built["recent_turns"],
                       "unclosed_archive_records": built["unclosed"]}, ensure_ascii=False)


def backend_artifact(path: Path, client: Any, value: dict[str, Any] | None = None,
                     ) -> dict[str, Any]:
    """Actual cache-file I/O, distinct from provider/Store timings and physical bytes."""
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    operation = "read" if value is None else "write"
    if value is None:
        value = read_json(path)
    else:
        write_json(path, value)
    if client.emit is not None:
        client.emit({"event": "benchmark_backend_artifact_io", "operation": operation,
            "path": str(path), "calls": 1, "logical_bytes": path.stat().st_size,
            "wall_ns": time.perf_counter_ns() - started_wall,
            "cpu_ns": time.process_time_ns() - started_cpu})
    return value


def trace_raw(client: Any, result: dict[str, Any], *, stage: str) -> None:
    if client.emit is not None:
        client.emit({"event": "benchmark_raw_" + stage,
            **{key: result[key] for key in ("source_sha256", "new_embedding_chunks",
                "delivered_ids", "omitted_ids", "ranked_ids", "query", "cpu_ns", "wall_ns")
               if key in result}, "chunks": len(result.get("chunks", [])),
            "material_bytes": len(result.get("material", "").encode())})
