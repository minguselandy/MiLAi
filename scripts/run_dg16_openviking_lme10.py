#!/usr/bin/env python3
"""Produce OpenViking-native find contexts for the public-dev LME10 lane."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import platform
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPENVIKING_ROOT = ROOT.parent / "OpenViking"
for candidate in (str(ROOT), str(OPENVIKING_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import openviking as ov  # type: ignore[import-not-found]
from openviking.models.rerank import RerankClient  # type: ignore[import-not-found]
from openviking_cli.client.sync_http import (  # type: ignore[import-not-found]
    SyncHTTPClient,
)
from openviking_cli.utils.config import (  # type: ignore[import-not-found]
    get_openviking_config,
)

_COMMON_SPEC = importlib.util.spec_from_file_location(
    "milai_external_lme10", ROOT / "evals/dg16/external_lme10.py"
)
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("external LME10 common module is unavailable")
_COMMON = importlib.util.module_from_spec(_COMMON_SPEC)
sys.modules[_COMMON_SPEC.name] = _COMMON
_COMMON_SPEC.loader.exec_module(_COMMON)
atomic_json = _COMMON.atomic_json
load_cases = _COMMON.load_cases
sha256_file = _COMMON.sha256_file

TOP_K = 10
SEARCH_LIMIT = 50
LONGMEMEVAL_TIME_FORMAT = "%Y/%m/%d (%a) %H:%M"


class OpenVikingLME10Error(RuntimeError):
    pass


def _sample_user_id(case_id: str) -> str:
    digest = hashlib.md5(f"user:{case_id}".encode()).hexdigest()[:12]
    return f"lm_user_{digest}"


def _messages(session: Any) -> list[dict[str, Any]]:
    return [
        {"role": turn.role, "text": turn.content, "index": index}
        for index, turn in enumerate(session.turns)
    ]


def _uri_values(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"uri", "path", "memory_uri", "context_uri"} and isinstance(
                item, str
            ) and item.startswith("viking://"):
                found.add(item)
            found.update(_uri_values(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_uri_values(item))
    return found


def _token_usage(task: dict[str, Any]) -> dict[str, int]:
    raw_result = task.get("result")
    result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
    raw_usage = result.get("token_usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    raw_embedding = usage.get("embedding")
    embedding: dict[str, Any] = (
        raw_embedding if isinstance(raw_embedding, dict) else {}
    )
    raw_llm = usage.get("llm")
    llm: dict[str, Any] = raw_llm if isinstance(raw_llm, dict) else {}
    return {
        "embedding_tokens": int(
            embedding.get("total", embedding.get("total_tokens", 0)) or 0
        ),
        "llm_input_tokens": int(llm.get("input", 0) or 0),
        "llm_output_tokens": int(llm.get("output", 0) or 0),
        "llm_total_tokens": int(
            llm.get("total", llm.get("total_tokens", 0)) or 0
        ),
    }


async def _submit_session(
    *,
    base_url: str,
    user_id: str,
    session: Any,
    submit_semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    try:
        base_time = datetime.strptime(
            session.observed_at, LONGMEMEVAL_TIME_FORMAT
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise OpenVikingLME10Error(
            f"invalid LongMemEval timestamp: {session.observed_at}"
        ) from exc
    async with submit_semaphore:
        client = ov.AsyncHTTPClient(url=base_url, user=user_id)
        await client.initialize()
        try:
            created = await client.create_session()
            session_id = str(created["session_id"])
            for index, message in enumerate(_messages(session)):
                await client.add_message(
                    session_id=session_id,
                    role=message["role"],
                    parts=[{"type": "text", "text": message["text"]}],
                    created_at=(base_time + timedelta(seconds=index)).isoformat(),
                )
            committed = await client.commit_session(session_id, telemetry=True)
            if committed.get("status") not in {"committed", "accepted"}:
                raise OpenVikingLME10Error(f"session commit failed: {committed}")
            return {
                "benchmark_session_id": session.session_id,
                "openviking_session_id": session_id,
                "task_id": committed.get("task_id"),
                "trace_id": committed.get("trace_id"),
            }
        finally:
            await client.close()


async def _wait_task(
    *,
    base_url: str,
    user_id: str,
    pending: dict[str, Any],
    wait_semaphore: asyncio.Semaphore,
    timeout_seconds: float,
) -> dict[str, Any]:
    task_id = pending.get("task_id")
    if not task_id:
        return {**pending, "task": {}, "token_usage": {}}
    async with wait_semaphore:
        client = ov.AsyncHTTPClient(url=base_url, user=user_id)
        await client.initialize()
        started = time.monotonic()
        try:
            while True:
                task = await client.get_task(str(task_id))
                status = task.get("status") if isinstance(task, dict) else "unknown"
                if status == "completed":
                    return {
                        **pending,
                        "task": task,
                        "token_usage": _token_usage(task),
                    }
                if status in {"failed", "unknown", "cancelled"}:
                    raise OpenVikingLME10Error(
                        f"task {task_id} terminated as {status}: {task}"
                    )
                if time.monotonic() - started > timeout_seconds:
                    raise OpenVikingLME10Error(f"task {task_id} readiness timeout")
                await asyncio.sleep(1)
        finally:
            await client.close()


def _iter_contexts(search_result: Any) -> list[Any]:
    if search_result is None:
        return []
    if isinstance(search_result, list):
        return search_result
    contexts: list[Any] = []
    for attribute in ("memories", "resources", "skills"):
        contexts.extend(getattr(search_result, attribute, []) or [])
    if contexts:
        return contexts
    try:
        return list(search_result)
    except TypeError:
        return []


def _query(
    *,
    base_url: str,
    user_id: str,
    question: str,
    uri_to_sessions: dict[str, set[str]],
    timeout_seconds: float,
) -> tuple[str, list[dict[str, Any]], list[str], float, dict[str, Any]]:
    started = time.perf_counter()
    client = SyncHTTPClient(url=base_url, user=user_id, timeout=int(timeout_seconds))
    try:
        client.initialize()
        target_uri = f"viking://user/{user_id}/memories"
        result = client.find(question, target_uri=target_uri, limit=SEARCH_LIMIT)
        candidates: list[dict[str, Any]] = []
        for raw_rank, context in enumerate(_iter_contexts(result), start=1):
            if raw_rank > SEARCH_LIMIT:
                break
            uri = str(getattr(context, "uri", "") or "")
            if not uri or uri.rstrip("/").rsplit("/", 1)[-1] in {
                ".abstract.md",
                ".overview.md",
            }:
                continue
            try:
                content = str(client.read(uri, offset=0, limit=-1))
            except Exception as exc:  # noqa: BLE001 - preserve native read failures
                content = f"[READ ERROR] {type(exc).__name__}: {exc}"
            candidates.append(
                {
                    "rank": raw_rank,
                    "uri": uri,
                    "score": float(getattr(context, "score", 0.0) or 0.0),
                    "content": content,
                }
            )
        reranker = RerankClient.from_config(get_openviking_config().rerank)
        rerank_scores = (
            reranker.rerank_batch(
                question,
                [candidate["content"] for candidate in candidates],
            )
            if reranker is not None and len(candidates) > 1
            else None
        )
        if rerank_scores and len(rerank_scores) == len(candidates):
            for candidate, score in zip(candidates, rerank_scores, strict=True):
                candidate["rerank_score"] = float(score)
            candidates.sort(
                key=lambda item: (item["rerank_score"], -item["rank"]),
                reverse=True,
            )
        candidates = candidates[:TOP_K]
    finally:
        client.close()
    blocks: list[str] = []
    trace: list[dict[str, Any]] = []
    selected_uris: list[str] = []
    for candidate in candidates:
        uri = candidate["uri"]
        selected_uris.append(uri)
        blocks.append(f"OpenViking Memory:\n{candidate['content']}")
        matched: set[str] = set()
        for source_uri, session_ids in uri_to_sessions.items():
            if uri == source_uri or uri.startswith(source_uri + "/") or source_uri.startswith(uri + "/"):
                matched.update(session_ids)
        if not matched:
            trace.append(
                {
                    "rank": len(trace) + 1,
                    "source_id": uri,
                    "score": candidate.get("rerank_score", candidate["score"]),
                }
            )
        else:
            for session_id in sorted(matched):
                trace.append(
                    {
                        "rank": len(trace) + 1,
                        "candidate_rank": candidate["rank"],
                        "session_id": session_id,
                        "source_id": uri,
                        "score": candidate.get("rerank_score", candidate["score"]),
                    }
                )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return (
        "\n\n".join(blocks),
        trace,
        selected_uris,
        elapsed_ms,
        {
            "contexts_returned": len(candidates),
            "find_limit": SEARCH_LIMIT,
            "rerank_enabled": bool(rerank_scores),
            "rerank_limit": TOP_K,
            "target_uri": target_uri,
        },
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise OpenVikingLME10Error("output exists; use a fresh run")
    cases, selection = load_cases()
    health_client = ov.AsyncHTTPClient(url=args.openviking_url)
    await health_client.initialize()
    try:
        health = await health_client.health()
    finally:
        await health_client.close()
    if not health:
        raise OpenVikingLME10Error("OpenViking health check failed")
    records: list[dict[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []
    all_usage = {
        "embedding_tokens": 0,
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
        "llm_total_tokens": 0,
    }
    started_all = time.perf_counter()
    submit_semaphore = asyncio.Semaphore(args.parallel)
    wait_semaphore = asyncio.Semaphore(args.parallel)
    for ordinal, case in enumerate(cases, start=1):
        user_id = _sample_user_id(case.case_id)
        ingest_started = time.perf_counter()
        pending = await asyncio.gather(
            *[
                _submit_session(
                    base_url=args.openviking_url,
                    user_id=user_id,
                    session=session,
                    submit_semaphore=submit_semaphore,
                )
                for session in case.sessions
            ]
        )
        completed = await asyncio.gather(
            *[
                _wait_task(
                    base_url=args.openviking_url,
                    user_id=user_id,
                    pending=item,
                    wait_semaphore=wait_semaphore,
                    timeout_seconds=args.readiness_timeout_seconds,
                )
                for item in pending
            ]
        )
        ingest_ms = (time.perf_counter() - ingest_started) * 1000
        uri_to_sessions: dict[str, set[str]] = {}
        case_usage = {key: 0 for key in all_usage}
        for item in completed:
            session_id = str(item["benchmark_session_id"])
            for uri in _uri_values(item.get("task")):
                uri_to_sessions.setdefault(uri, set()).add(session_id)
            for key in case_usage:
                value = int((item.get("token_usage") or {}).get(key, 0) or 0)
                case_usage[key] += value
                all_usage[key] += value
        context, trace, source_refs, query_ms, query_usage = await asyncio.to_thread(
            _query,
            base_url=args.openviking_url,
            user_id=user_id,
            question=case.question,
            uri_to_sessions=uri_to_sessions,
            timeout_seconds=args.query_timeout_seconds,
        )
        if not context:
            raise OpenVikingLME10Error(f"case {case.case_id} returned no context")
        records.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "method_id": "OPENVIKING-FIND",
                "context": context,
                "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                "query_latency_ms": query_ms,
                "retrieval_trace": trace,
                "selected_source_refs": source_refs,
                "usage": {
                    "memory_query_api_calls": 1,
                    **query_usage,
                },
            }
        )
        lifecycle.append(
            {
                "case_id": case.case_id,
                "session_count": len(case.sessions),
                "ingest_ms": ingest_ms,
                "query_ms": query_ms,
                "session_commit_calls": len(case.sessions),
                "session_commit_usage": case_usage,
                "memory_uri_count": len(uri_to_sessions),
            }
        )
        print(
            json.dumps(
                {
                    "stage": "openviking-context",
                    "case": ordinal,
                    "case_count": len(cases),
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(records) != 10:
        raise OpenVikingLME10Error("OpenViking context denominator is incomplete")
    artifact = {
        "schema": "milai.dg16.external-lme10-contexts.v1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "run_id": args.run_id,
        "method_id": "OPENVIKING-FIND",
        "record_count": len(records),
        "selection": selection,
        "configuration": {
            "source_commit": args.source_commit,
            "release": getattr(ov, "__version__", "0.4.16"),
            "top_k": TOP_K,
            "native_find_limit": SEARCH_LIMIT,
            "parallel": args.parallel,
            "retrieval": "native find-50 over extracted session memories + rerank-10",
            "reranker_enabled": True,
        },
        "lifecycle": lifecycle,
        "provider_accounting": {
            "session_commit_calls": sum(item["session_count"] for item in lifecycle),
            **all_usage,
        },
        "execution": {
            "hostname": platform.node(),
            "python": sys.version,
            "runner_sha256": sha256_file(Path(__file__)),
            "wall_ms": round((time.perf_counter() - started_all) * 1000, 6),
        },
        "records": records,
    }
    atomic_json(args.output, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--openviking-url", required=True)
    parser.add_argument("--parallel", type=int, choices=(1, 2, 4), default=4)
    parser.add_argument("--readiness-timeout-seconds", type=float, default=900)
    parser.add_argument("--query-timeout-seconds", type=float, default=300)
    parser.add_argument(
        "--source-commit",
        default="499995f3ed2e7f551a715179c4053772c51ff819",
    )
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
