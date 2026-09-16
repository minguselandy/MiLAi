"""Memora native-context runner for a frozen ReMe OSS installation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, cast

import httpx
from tokenizers import Tokenizer  # type: ignore[import-not-found]

from evals.paper.contracts import ContextRecord, write_context_archive
from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.runners.memora import _require_inputs

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
DEFAULT_REME_ROOT = Path("/cra/memory/mx_memory/ReMe")
DEFAULT_REME_EXECUTABLE = DEFAULT_REME_ROOT / ".venv/bin/reme"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860/v1"
MEMORY_TOKEN_BUDGET = 512
SEARCH_LIMIT = 50
REQUEST_WORKERS = 2


class MemoraReMeError(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _session_text(cohort: MemoraCohort, index: int) -> str:
    return "\n".join(
        f"{turn.actor.capitalize()}: {turn.content}"
        for turn in cohort.sessions[index].turns
    )


def _session_stem(session_id: str) -> str:
    return "session-" + hashlib.sha256(session_id.encode()).hexdigest()[:24]


def _response_object(response: httpx.Response, endpoint: str) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise MemoraReMeError(f"ReMe {endpoint} response is not JSON") from exc
    if response.status_code != 200 or not isinstance(value, dict):
        raise MemoraReMeError(
            f"ReMe {endpoint} failed with HTTP {response.status_code}"
        )
    if value.get("success") is not True:
        raise MemoraReMeError(f"ReMe {endpoint} returned success=false")
    return value


async def _post(
    client: httpx.AsyncClient, endpoint: str, payload: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(endpoint, json=payload)
    return _response_object(response, endpoint)


async def _wait_ready(
    process: subprocess.Popen[bytes], client: httpx.AsyncClient
) -> int:
    for attempts in range(1, 121):
        if process.poll() is not None:
            raise MemoraReMeError("ReMe server exited before readiness")
        try:
            await _post(client, "/health_check", {})
            return attempts
        except (httpx.HTTPError, MemoraReMeError):
            await asyncio.sleep(0.25)
    raise MemoraReMeError("ReMe server readiness timed out")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _graceful_shutdown_logged(path: Path) -> bool:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 131_072))
        tail = handle.read()
    return (
        b"Application shutdown complete." in tail
        and b"Finished server process" in tail
    )


def _fit_results(
    results: list[dict[str, Any]],
    *,
    tokenizer: Tokenizer,
    path_to_session: dict[str, str],
    session_dates: dict[str, str],
) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...], int]:
    blocks: list[str] = []
    sources: list[str] = []
    trace: list[dict[str, Any]] = []
    declared_tokens = 0
    for native_rank, item in enumerate(results, start=1):
        path = item.get("path")
        text = item.get("text")
        if not isinstance(path, str) or not isinstance(text, str) or not text.strip():
            continue
        session_id = path_to_session.get(path)
        if session_id is None:
            continue
        block = (
            f"Session Date: {session_dates[session_id]}\n"
            f"Session Content:\n{text.strip()}"
        )
        candidate = "\n\n".join([*blocks, block])
        candidate_tokens = len(tokenizer.encode(candidate).ids)
        if candidate_tokens > MEMORY_TOKEN_BUDGET:
            continue
        scores = item.get("scores")
        scores = scores if isinstance(scores, dict) else {}
        score = scores.get("score", item.get("score", 0.0))
        score = float(score) if isinstance(score, int | float) else 0.0
        blocks.append(block)
        sources.append(session_id)
        trace.append(
            {
                "chunk_id_sha256": hashlib.sha256(
                    str(item.get("id", "")).encode()
                ).hexdigest(),
                "end_line": int(item.get("end_line", 0) or 0),
                "native_rank": native_rank,
                "path_sha256": hashlib.sha256(path.encode()).hexdigest(),
                "rank": len(trace) + 1,
                "score": score,
                "score_kind": "REME_NATIVE_SEARCH_SCORE",
                "session_id": session_id,
                "source_id": session_id,
                "start_line": int(item.get("start_line", 0) or 0),
            }
        )
        declared_tokens = candidate_tokens
    return (
        "\n\n".join(blocks),
        tuple(dict.fromkeys(sources)),
        tuple(trace),
        declared_tokens,
    )


async def _query_case(
    *,
    client: httpx.AsyncClient,
    case: MemoraCase,
    tokenizer: Tokenizer,
    path_to_session: dict[str, str],
    session_dates: dict[str, str],
    semaphore: asyncio.Semaphore,
) -> ContextRecord:
    async with semaphore:
        started = time.perf_counter()
        response = await _post(
            client,
            "/search",
            {
                "limit": SEARCH_LIMIT,
                "min_score": 0.0,
                "query": case.question,
                "vector_weight": 0.0,
            },
        )
        latency_ms = (time.perf_counter() - started) * 1000
    metadata = response.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    results = metadata.get("results")
    if not isinstance(results, list) or not all(
        isinstance(item, dict) for item in results
    ):
        raise MemoraReMeError("ReMe search result contract drifted")
    counts = metadata.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    if int(counts.get("vector", 0) or 0) != 0:
        raise MemoraReMeError("ReMe BM25-only search unexpectedly used vectors")
    context, sources, trace, tokens = _fit_results(
        results,
        tokenizer=tokenizer,
        path_to_session=path_to_session,
        session_dates=session_dates,
    )
    return ContextRecord(
        case_id=case.case_id,
        method_id="REME-OSS",
        track="NATIVE",
        context=context,
        source_ids=sources,
        trace=trace,
        declared_tokens=tokens,
        latency_ms=latency_ms,
        usage={
            "keyword_results": int(counts.get("keyword", 0) or 0),
            "memory_query_model_calls": 0,
            "results_returned": len(results),
            "retriever_calls": 1,
            "vector_results": 0,
        },
    )


async def _run_cohort(
    *,
    cohort: MemoraCohort,
    cases: list[MemoraCase],
    workspace: Path,
    tokenizer: Tokenizer,
    reme_executable: Path,
    reme_root: Path,
    log_path: Path,
    workers: int,
) -> tuple[list[ContextRecord], dict[str, Any]]:
    if workspace.exists():
        raise MemoraReMeError("ReMe cohort workspace must be fresh")
    if log_path.exists():
        raise MemoraReMeError("ReMe server log path already exists")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = dict(os.environ)
    environment.update(
        {
            "LLM_API_KEY": "vllm-api-key",
            "LLM_BASE_URL": VLLM_BASE_URL,
            "LLM_MODEL_NAME": MODEL_ID,
            "NO_PROXY": "127.0.0.1,localhost",
        }
    )
    command = [
        str(reme_executable),
        "start",
        f"workspace_dir={workspace}",
        "service.backend=http",
        "service.host=127.0.0.1",
        f"service.port={port}",
        "service.web_enabled=false",
        "enable_logo=false",
        "log_to_file=false",
        "components.as_llm.default.max_retries=0",
        "components.as_llm.default.stream=false",
    ]
    process: subprocess.Popen[bytes] | None = None
    path_to_session: dict[str, str] = {}
    session_dates: dict[str, str] = {}
    ready_attempts = 0
    index_started = 0.0
    index_ms = 0.0
    storage_bytes = 0
    workspace_file_count = 0
    try:
        with log_path.open("xb") as log_handle:
            process = await asyncio.to_thread(
                subprocess.Popen,
                command,
                cwd=reme_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            limits = httpx.Limits(
                max_connections=workers,
                max_keepalive_connections=workers,
            )
            async with httpx.AsyncClient(
                base_url=base_url,
                limits=limits,
                timeout=httpx.Timeout(120, connect=5),
                trust_env=False,
            ) as client:
                ready_attempts = await _wait_ready(process, client)
                index_started = time.perf_counter()
                for index, session in enumerate(cohort.sessions):
                    day = session.observed_at[:10]
                    stem = _session_stem(session.session_id)
                    relative_path = f"daily/{day}/{stem}.md"
                    response = await _post(
                        client,
                        "/write",
                        {
                            "content": _session_text(cohort, index),
                            "description": "Memora chronological conversation session",
                            "name": stem,
                            "path": relative_path,
                        },
                    )
                    if response.get("metadata") not in ({}, None):
                        raise MemoraReMeError("ReMe write metadata contract drifted")
                    path_to_session[relative_path] = session.session_id
                    session_dates[session.session_id] = session.observed_at
                workspace_files = sorted((workspace / "daily").rglob("*.md"))
                if len(workspace_files) != len(cohort.sessions):
                    raise MemoraReMeError("ReMe workspace session denominator drifted")
                workspace_file_count = len(workspace_files)
                storage_bytes = sum(path.stat().st_size for path in workspace_files)
                await _post(client, "/reindex", {})
                index_ms = (time.perf_counter() - index_started) * 1000
                semaphore = asyncio.Semaphore(workers)
                records = await asyncio.gather(
                    *[
                        _query_case(
                            client=client,
                            case=case,
                            tokenizer=tokenizer,
                            path_to_session=path_to_session,
                            session_dates=session_dates,
                            semaphore=semaphore,
                        )
                        for case in cases
                    ]
                )
        assert process is not None
        await asyncio.to_thread(_stop, process)
        graceful_shutdown = _graceful_shutdown_logged(log_path)
        if process.returncode not in (0, -signal.SIGTERM) or not graceful_shutdown:
            raise MemoraReMeError(
                f"ReMe server shutdown failed with code {process.returncode}"
            )
        stats = {
            "cohort_id": cohort.cohort_id,
            "health_attempts": ready_attempts,
            "index_time_ms": round(index_ms, 3),
            "question_count": len(cases),
            "reindex_api_calls": 1,
            "search_api_calls": len(cases),
            "server_log": str(log_path.relative_to(ROOT)),
            "server_log_sha256": sha256_file(log_path),
            "server_returncode": process.returncode,
            "server_shutdown": "GRACEFUL_UVICORN_SIGTERM"
            if process.returncode == -signal.SIGTERM
            else "GRACEFUL_NORMAL_EXIT",
            "session_count": len(cohort.sessions),
            "storage_bytes": storage_bytes,
            "workspace_file_count": workspace_file_count,
            "write_api_calls": len(cohort.sessions),
        }
        return records, stats
    finally:
        if process is not None:
            await asyncio.to_thread(_stop, process)
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=False)


async def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    workspace_root: Path,
    tokenizer_path: Path,
    workers: int,
    reme_executable: Path,
    reme_root: Path,
    log_dir: Path,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if workers != REQUEST_WORKERS:
        raise MemoraReMeError("ReMe runner requires exactly two request workers")
    if not reme_executable.is_file():
        raise MemoraReMeError("ReMe executable is missing")
    if not reme_root.is_dir():
        raise MemoraReMeError("ReMe source root is missing")
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    if workspace_root.exists():
        raise MemoraReMeError("ReMe root workspace must be fresh")
    if output.exists():
        raise MemoraReMeError("ReMe context archive is write-once")
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
            cohort_records, stats = await _run_cohort(
                cohort=cohort,
                cases=cases_by_cohort[cohort.cohort_id],
                workspace=workspace_root / f"cohort-{ordinal:02d}",
                tokenizer=tokenizer,
                reme_executable=reme_executable,
                reme_root=reme_root,
                log_path=log_dir / f"{output.stem}-cohort-{ordinal:02d}.log",
                workers=workers,
            )
            records.extend(cohort_records)
            cohort_stats.append(stats)
    finally:
        if workspace_root.exists():
            shutil.rmtree(workspace_root, ignore_errors=False)
    by_key = {(record.case_id, record.method_id): record for record in records}
    ordered = [by_key[(case.case_id, "REME-OSS")] for case in cases]
    if len(ordered) != len(cases):
        raise MemoraReMeError("ReMe context denominator drifted")
    config = {
        "file_representation": "ONE_MARKDOWN_FILE_PER_SESSION",
        "memory_token_budget": MEMORY_TOKEN_BUDGET,
        "native_api": "OFFICIAL_FASTAPI_REST",
        "native_search": "BM25_WITH_LINK_EXPANSION",
        "request_workers": workers,
        "search_limit": SEARCH_LIMIT,
        "vector_weight": 0.0,
    }
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
                            config, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                    "runner_sha256": sha256_file(Path(__file__)),
                },
                "cohort_stats": cohort_stats,
                "failure_count": 0,
                "labels_accessed": False,
                "paper_labels_opened": False,
                "status": "PASS",
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
    parser.add_argument("--workers", type=int, choices=(2,), default=2)
    parser.add_argument("--reme-root", type=Path, default=DEFAULT_REME_ROOT)
    parser.add_argument(
        "--reme-executable", type=Path, default=DEFAULT_REME_EXECUTABLE
    )
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    result = asyncio.run(
        run(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            output=output,
            workspace_root=args.workspace_root.resolve(),
            tokenizer_path=args.tokenizer.resolve(),
            workers=args.workers,
            reme_executable=args.reme_executable.resolve(),
            reme_root=args.reme_root.resolve(),
            log_dir=(args.log_dir or output.parent / "raw").resolve(),
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        )
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
