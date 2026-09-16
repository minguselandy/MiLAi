"""Controlled context runner for DG11 extended benchmark inputs."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, cast

from tokenizers import Tokenizer

from evals.paper.adapters import (
    FullHistoryAdapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
)
from evals.paper.contracts import (
    ContextRecord,
    MemoryAdapter,
    MemoryEvent,
    write_context_archive,
)
from evals.paper.datasets.extended import ExtendedCase, load_extended_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.parallelism import STATELESS_CONTEXT_LANE, WORKER_CHOICES

DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
METHODS = ("CTRL-NONE", "LME-BM25-S", "CTRL-TRUNC-FULL")


class ExtendedContextError(RuntimeError):
    pass


def _adapter(method_id: str, tokenizer: Tokenizer) -> MemoryAdapter:
    counter = lambda value: len(tokenizer.encode(value).ids)
    if method_id == "CTRL-NONE":
        return NoMemoryAdapter(token_counter=counter)
    if method_id == "LME-BM25-S":
        return OfficialBM25Adapter(
            granularity="session",
            top_k=3,
            token_counter=counter,
            method_id=method_id,
        )
    if method_id == "CTRL-TRUNC-FULL":
        return FullHistoryAdapter(truncate=True, token_counter=counter)
    raise ExtendedContextError(f"unknown extended method: {method_id}")


def _events(case: ExtendedCase) -> tuple[MemoryEvent, ...]:
    events = []
    for session_ordinal, session in enumerate(case.sessions):
        for turn_ordinal, turn in enumerate(session.turns):
            events.append(
                MemoryEvent(
                    event_id=(
                        f"{case.case_id}:{session_ordinal:04d}:{turn_ordinal:04d}"
                    ),
                    content=turn.content,
                    observed_at=session.observed_at,
                    actor=turn.role,
                    scope="paper-extended",
                    metadata={
                        "session_id": session.session_id,
                        "turn_index": turn_ordinal,
                    },
                )
            )
    return tuple(events)


def _context(
    *,
    run_id: str,
    case: ExtendedCase,
    method_id: str,
    tokenizer: Tokenizer,
    token_budget: int,
) -> ContextRecord:
    adapter = _adapter(method_id, tokenizer)
    try:
        adapter.reset(run_id, case.case_id)
        events = _events(case)
        for event in events:
            adapter.ingest(event)
        adapter.finalize()
        result = adapter.query(
            case.question,
            case.question_at,
            token_budget if method_id != "CTRL-NONE" else 0,
            "CONTROLLED",
        )
        stats = adapter.stats()
        usage = dict(result.usage)
        usage.update(
            {
                "answer_calls": 0,
                "history_events": len(events),
                "ingest_extraction_calls": 0,
                "judge_calls": 0,
                "memory_query_model_calls": 0,
                "reflection_consolidation_calls": 0,
                "storage_bytes": stats.storage_bytes,
            }
        )
        return ContextRecord(
            case_id=case.case_id,
            method_id=method_id,
            track="CONTROLLED",
            context=result.context,
            source_ids=result.source_ids,
            trace=result.trace,
            declared_tokens=result.declared_tokens,
            latency_ms=result.latency_ms,
            usage=usage,
        )
    finally:
        adapter.close()


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    method_ids: tuple[str, ...],
    tokenizer_path: Path,
    token_budget: int,
    workers: int,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if output.exists():
        raise ExtendedContextError("extended context output is write-once")
    if not method_ids or len(set(method_ids)) != len(method_ids):
        raise ExtendedContextError("extended method list is empty or duplicated")
    if any(method not in METHODS for method in method_ids):
        raise ExtendedContextError("extended method list contains an unknown method")
    STATELESS_CONTEXT_LANE.validate(workers)
    if token_budget <= 0:
        raise ExtendedContextError("extended context token budget must be positive")
    partition, cases = load_extended_inputs(input_path)
    if allow_unfrozen_smoke:
        if "SMOKE" not in partition:
            raise ExtendedContextError(
                "unfrozen execution is restricted to smoke inputs"
            )
    else:
        require_paper_evaluation_ready(freeze_manifest)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    planned = [(case, method_id) for case in cases for method_id in method_ids]
    records: list[ContextRecord | None] = [None] * len(planned)
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="paper-extended"
    ) as pool:
        futures = {
            pool.submit(
                _context,
                run_id=run_id,
                case=case,
                method_id=method_id,
                tokenizer=tokenizer,
                token_budget=token_budget,
            ): index
            for index, (case, method_id) in enumerate(planned)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                records[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - retain every planned terminal
                case, method_id = planned[index]
                records[index] = ContextRecord(
                    case_id=case.case_id,
                    method_id=method_id,
                    track="CONTROLLED",
                    context="",
                    source_ids=(),
                    trace=(),
                    declared_tokens=0,
                    latency_ms=0,
                    usage={"failure_class": type(exc).__name__},
                    terminal_status="INFRASTRUCTURE_FAILURE",
                )
    finalized = tuple(record for record in records if record is not None)
    if len(finalized) != len(planned):
        raise ExtendedContextError("extended runner lost a request terminal")
    failures = sum(record.terminal_status != "SUCCEEDED" for record in finalized)
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=finalized,
        metadata={
            "answer_calls": 0,
            "development_ai_reviews": 0,
            "failure_count": failures,
            "input_sha256": sha256_file(input_path),
            "labels_accessed": False,
            "maximum_concurrent_requests": workers,
            "paper_labels_opened": False,
            "runner_source_sha256": sha256_file(Path(__file__)),
            "status": "PASS" if failures == 0 else "FAIL",
            "token_budget": token_budget,
            "tokenizer_sha256": sha256_file(tokenizer_path),
        },
    )
    return cast(dict[str, Any], payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", action="append", choices=METHODS, required=True)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--token-budget", type=int, default=512)
    parser.add_argument(
        "--workers",
        type=int,
        choices=WORKER_CHOICES,
        default=STATELESS_CONTEXT_LANE.default_workers,
    )
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        method_ids=tuple(args.method),
        tokenizer_path=args.tokenizer.resolve(),
        token_budget=args.token_budget,
        workers=args.workers,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
    )
    print(
        json.dumps(
            {
                "failure_count": result["failure_count"],
                "record_count": result["record_count"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
