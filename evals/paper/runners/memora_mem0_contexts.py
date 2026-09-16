"""Memora native-context runner for a frozen Mem0 OSS installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, cast

# Mem0 reads this variable while importing ``mem0.memory.telemetry`` and creates
# a module-level PostHog client immediately.  Set it before importing Mem0 so a
# caller's ambient environment cannot enable outbound benchmark telemetry.
os.environ["MEM0_TELEMETRY"] = "false"

from mem0 import Memory  # type: ignore[import-not-found]
from mem0.memory import telemetry as mem0_telemetry  # type: ignore[import-not-found]
from tokenizers import Tokenizer  # type: ignore[import-not-found]

from evals.paper.contracts import ContextRecord, write_context_archive
from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.runners.memora import _require_inputs

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860/v1"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
MEMORY_TOKEN_BUDGET = 512
TOP_K = 50


class MemoraMem0Error(RuntimeError):
    pass


def _require_telemetry_disabled() -> None:
    if mem0_telemetry.MEM0_TELEMETRY is not False:
        raise MemoraMem0Error("Mem0 telemetry must be disabled before import")
    if mem0_telemetry.client_telemetry.posthog is not None:
        raise MemoraMem0Error("Mem0 PostHog client exists despite telemetry disablement")


def _session_messages(cohort: MemoraCohort, index: int) -> list[dict[str, str]]:
    return [
        {"role": turn.actor, "content": turn.content}
        for turn in cohort.sessions[index].turns
    ]


def _memory_config(workspace: Path, cohort_id: str) -> dict[str, Any]:
    collection = "pe05_" + hashlib.sha256(cohort_id.encode()).hexdigest()[:20]
    return {
        "embedder": {
            "config": {"embedding_dims": 384, "model": EMBEDDING_MODEL},
            "provider": "fastembed",
        },
        "history_db_path": str(workspace / "history.db"),
        "llm": {
            "config": {
                "api_key": "vllm-api-key",
                "max_tokens": 512,
                "model": MODEL_ID,
                "temperature": 0,
                "vllm_base_url": VLLM_BASE_URL,
            },
            "provider": "vllm",
        },
        "vector_store": {
            "config": {
                "collection_name": collection,
                "embedding_model_dims": 384,
                "path": str(workspace / "qdrant"),
            },
            "provider": "qdrant",
        },
    }


def _fit_results(
    results: list[dict[str, Any]], tokenizer: Tokenizer
) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...], int]:
    blocks: list[str] = []
    sources: list[str] = []
    trace: list[dict[str, Any]] = []
    declared_tokens = 0
    for rank, item in enumerate(results, start=1):
        memory = item.get("memory")
        if not isinstance(memory, str) or not memory.strip():
            continue
        metadata = item.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        session_id = str(metadata.get("session_id", item.get("id", "unknown")))
        observed_at = str(metadata.get("observed_at", "UNKNOWN"))
        block = f"Session Date: {observed_at}\nSession Content:\n{memory.strip()}"
        candidate = "\n\n".join([*blocks, block])
        candidate_tokens = len(tokenizer.encode(candidate).ids)
        if candidate_tokens > MEMORY_TOKEN_BUDGET:
            continue
        blocks.append(block)
        sources.append(session_id)
        score = item.get("score")
        trace.append(
            {
                "rank": rank,
                "score": float(score) if isinstance(score, int | float) else 0.0,
                "session_id": session_id,
                "source_id": session_id,
            }
        )
        declared_tokens = candidate_tokens
    return "\n\n".join(blocks), tuple(sources), tuple(trace), declared_tokens


def _query(
    *,
    memory: Memory,
    case: MemoraCase,
    user_id: str,
    tokenizer: Tokenizer,
) -> ContextRecord:
    started = time.perf_counter()
    response = memory.search(
        case.question,
        top_k=TOP_K,
        filters={"user_id": user_id},
        threshold=0,
    )
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list) or not all(
        isinstance(item, dict) for item in results
    ):
        raise MemoraMem0Error("Mem0 search response drifted")
    context, sources, trace, tokens = _fit_results(results, tokenizer)
    return ContextRecord(
        case_id=case.case_id,
        method_id="MEM0-OSS",
        track="NATIVE",
        context=context,
        source_ids=sources,
        trace=trace,
        declared_tokens=tokens,
        latency_ms=(time.perf_counter() - started) * 1000,
        usage={
            "documents_returned": len(results),
            "memory_query_model_calls": 0,
            "retriever_calls": 1,
        },
    )


def _run_cohort(
    *,
    run_id: str,
    cohort: MemoraCohort,
    cases: list[MemoraCase],
    workspace: Path,
    tokenizer: Tokenizer,
) -> tuple[list[ContextRecord], dict[str, Any]]:
    if workspace.exists():
        raise MemoraMem0Error("Mem0 cohort workspace must be fresh")
    workspace.mkdir(parents=True)
    memory: Memory | None = None
    completions: list[dict[str, Any]] = []
    user_id = (
        "pe05-"
        + hashlib.sha256(f"{run_id}\0{cohort.cohort_id}".encode()).hexdigest()[:24]
    )
    ingested_memories = 0
    ingest_started = time.perf_counter()
    try:
        memory = Memory.from_config(_memory_config(workspace, cohort.cohort_id))
        create = memory.llm.client.chat.completions.create

        def tracked_create(*args: Any, **kwargs: Any) -> Any:
            response = create(*args, **kwargs)
            usage = response.usage.model_dump() if response.usage is not None else {}
            completions.append(
                {
                    "completion_id": response.id,
                    "finish_reason": response.choices[0].finish_reason,
                    "model": response.model,
                    "usage": usage,
                }
            )
            return response

        memory.llm.client.chat.completions.create = tracked_create
        for index, session in enumerate(cohort.sessions):
            response = memory.add(
                _session_messages(cohort, index),
                user_id=user_id,
                metadata={
                    "observed_at": session.observed_at,
                    "sequence": index,
                    "session_id": session.session_id,
                },
                infer=True,
            )
            result_items = (
                response.get("results") if isinstance(response, dict) else None
            )
            if not isinstance(result_items, list):
                raise MemoraMem0Error("Mem0 add response drifted")
            ingested_memories += len(result_items)
        ingest_ms = (time.perf_counter() - ingest_started) * 1000
        records = [
            _query(memory=memory, case=case, user_id=user_id, tokenizer=tokenizer)
            for case in cases
        ]
        all_memories = memory.get_all(filters={"user_id": user_id})
        stored = all_memories.get("results") if isinstance(all_memories, dict) else None
        if not isinstance(stored, list):
            raise MemoraMem0Error("Mem0 get-all response drifted")
        usage_totals = {
            key: sum(
                int(item.get("usage", {}).get(key, 0) or 0) for item in completions
            )
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        stats = {
            "cohort_id": cohort.cohort_id,
            "completion_calls": len(completions),
            "completion_usage": usage_totals,
            "index_time_ms": round(ingest_ms, 3),
            "ingested_memories": ingested_memories,
            "question_count": len(cases),
            "session_count": len(cohort.sessions),
            "storage_bytes": sum(
                len(json.dumps(item, ensure_ascii=False).encode()) for item in stored
            ),
            "stored_memories": len(stored),
        }
        memory.delete_all(user_id=user_id)
        after = memory.get_all(filters={"user_id": user_id})
        if not isinstance(after, dict) or after.get("results") != []:
            raise MemoraMem0Error("Mem0 cleanup failed")
        return records, stats
    finally:
        if memory is not None:
            memory.close()
        shutil.rmtree(workspace, ignore_errors=False)


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    workspace_root: Path,
    tokenizer_path: Path,
    workers: int,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if workers != 1:
        raise MemoraMem0Error("Mem0 native runner requires one in-process worker")
    _require_telemetry_disabled()
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    if workspace_root.exists():
        raise MemoraMem0Error("Mem0 root workspace must be fresh")
    workspace_root.mkdir(parents=True)
    cohorts, cases = load_inputs(input_path)
    cases_by_cohort: dict[str, list[MemoraCase]] = {
        cohort.cohort_id: [] for cohort in cohorts
    }
    for case in cases:
        cases_by_cohort[case.cohort_id].append(case)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    records: list[ContextRecord] = []
    cohort_stats: list[dict[str, Any]] = []
    try:
        for ordinal, cohort in enumerate(cohorts):
            cohort_records, stats = _run_cohort(
                run_id=run_id,
                cohort=cohort,
                cases=cases_by_cohort[cohort.cohort_id],
                workspace=workspace_root / f"cohort-{ordinal:02d}",
                tokenizer=tokenizer,
            )
            records.extend(cohort_records)
            cohort_stats.append(stats)
    finally:
        shutil.rmtree(workspace_root, ignore_errors=False)
    by_key = {(record.case_id, record.method_id): record for record in records}
    ordered = [by_key[(case.case_id, "MEM0-OSS")] for case in cases]
    if len(ordered) != len(cases):
        raise MemoraMem0Error("Mem0 context denominator drifted")
    return cast(
        dict[str, Any],
        write_context_archive(
            output,
            run_id=run_id,
            benchmark_id="MEMORA-PREREGISTERED-60",
            records=ordered,
            metadata={
                "adapter_identity": {
                    "config_sha256": hashlib.sha256(
                        json.dumps(
                            _memory_config(Path("WORKSPACE"), "COHORT"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    "runner_sha256": sha256_file(Path(__file__)),
                },
                "cohort_stats": cohort_stats,
                "failure_count": 0,
                "labels_accessed": False,
                "paper_labels_opened": False,
                "status": "PASS",
                "telemetry": {
                    "disabled": True,
                    "mechanism": "MEM0_TELEMETRY=false before Mem0 import",
                    "posthog_client_created": False,
                },
                "worker_count": workers,
                "workspace_removed": not workspace_root.exists(),
            },
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--workers", type=int, choices=(1,), default=1)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        workspace_root=args.workspace_root.resolve(),
        tokenizer_path=args.tokenizer.resolve(),
        workers=args.workers,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
    )
    print(
        json.dumps(
            {
                "record_count": result["record_count"],
                "status": result["status"],
                "workspace_removed": result["workspace_removed"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
