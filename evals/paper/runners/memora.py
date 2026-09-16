"""Memora controlled-context and common-answer runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer  # type: ignore[import-not-found]

from evals.paper.adapters import NoMemoryAdapter, OfficialBM25Adapter
from evals.paper.answer_runner import PaperAnswerRunner
from evals.paper.contracts import (
    ContextRecord,
    MemoryAdapter,
    MemoryEvent,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.parallelism import ANSWER_PROVIDER_LANE, WORKER_CHOICES
from evals.paper.provider import FrozenVllmClient
from evals.paper.schedules import counterbalanced_order
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
CONTROLLED_METHODS = ("CTRL-NONE", "LME-BM25-S")
NATIVE_METHODS = ("MEM0-OSS", "HINDSIGHT-OSS", "GRAPHITI-OSS", "REME-OSS")
ALL_METHODS = (*CONTROLLED_METHODS, "DG11-FULL", *NATIVE_METHODS)


class MemoraRunnerError(RuntimeError):
    pass


def _methods(value: str, *, allowed: tuple[str, ...]) -> tuple[str, ...]:
    methods = tuple(item.strip() for item in value.split(",") if item.strip())
    if not methods or len(set(methods)) != len(methods):
        raise MemoraRunnerError("method list must be non-empty and unique")
    unknown = set(methods).difference(allowed)
    if unknown:
        raise MemoraRunnerError(f"unknown Memora methods: {sorted(unknown)}")
    return methods


def _adapter(method: str, tokenizer: Tokenizer) -> MemoryAdapter:
    token_counter = lambda text: len(tokenizer.encode(text).ids)
    if method == "CTRL-NONE":
        return NoMemoryAdapter(token_counter=token_counter)
    if method == "LME-BM25-S":
        return OfficialBM25Adapter(
            granularity="session", top_k=3, token_counter=token_counter
        )
    raise MemoraRunnerError(f"method requires an imported context archive: {method}")


def _events(cohort: MemoraCohort) -> tuple[MemoryEvent, ...]:
    events = []
    for session in cohort.sessions:
        for turn_index, turn in enumerate(session.turns):
            events.append(
                MemoryEvent(
                    event_id=f"{session.session_id}:{turn_index}",
                    content=turn.content,
                    observed_at=session.observed_at,
                    actor=turn.actor,
                    scope="dg11-paper-public-memora",
                    metadata={
                        "cohort_id": cohort.cohort_id,
                        "session_id": session.session_id,
                        "turn_index": turn_index,
                    },
                )
            )
    return tuple(events)


def _require_inputs(path: Path, *, allow_unfrozen_smoke: bool) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MemoraRunnerError("Memora input artifact is invalid")
    if allow_unfrozen_smoke:
        if (
            value.get("test_data_only") is not True
            or not 1 <= value.get("case_count", 0) <= 10
        ):
            raise MemoraRunnerError("unfrozen Memora smoke requires synthetic inputs")
    elif value.get("test_data_only") is True:
        raise MemoraRunnerError("formal Memora run cannot use synthetic inputs")


def prepare_contexts(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    methods: tuple[str, ...],
    token_budget: int,
    tokenizer_path: Path,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    cohorts, cases = load_inputs(input_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    cohort_by_id = {cohort.cohort_id: cohort for cohort in cohorts}
    cases_by_cohort: dict[str, list[tuple[int, MemoraCase]]] = {
        cohort.cohort_id: [] for cohort in cohorts
    }
    for ordinal, case in enumerate(cases):
        if case.cohort_id not in cases_by_cohort:
            raise MemoraRunnerError("Memora case references an unknown cohort")
        cases_by_cohort[case.cohort_id].append((ordinal, case))
    records_by_key: dict[tuple[str, str], ContextRecord] = {}
    cohort_stats: list[dict[str, Any]] = []
    for cohort_id, cohort_cases in cases_by_cohort.items():
        cohort = cohort_by_id[cohort_id]
        events = _events(cohort)
        adapters = {method: _adapter(method, tokenizer) for method in methods}
        try:
            for method, adapter in adapters.items():
                adapter.reset(run_id, cohort_id)
                for event in events:
                    adapter.ingest(event)
                adapter.finalize()
                stats = adapter.stats()
                cohort_stats.append(
                    {
                        "cohort_id": cohort_id,
                        "ingested_events": stats.ingested_events,
                        "method": method,
                        "provider_calls": dict(stats.provider_calls),
                        "storage_bytes": stats.storage_bytes,
                    }
                )
            for case_ordinal, case in cohort_cases:
                for method in counterbalanced_order(
                    methods,
                    case_ordinal=case_ordinal,
                    namespace="milai-dg11-paper-v1:MEMORA:retrieval",
                ):
                    adapter = adapters[method]
                    result = adapter.query(
                        case.question,
                        case.question_at,
                        token_budget,
                        "CONTROLLED",
                    )
                    records_by_key[(case.case_id, method)] = ContextRecord(
                        case_id=case.case_id,
                        method_id=method,
                        track="CONTROLLED",
                        context=result.context,
                        source_ids=result.source_ids,
                        trace=result.trace,
                        declared_tokens=result.declared_tokens,
                        latency_ms=result.latency_ms,
                        usage=dict(result.usage),
                    )
        finally:
            for adapter in adapters.values():
                adapter.close()
    records = [
        records_by_key[(case.case_id, method)]
        for case_ordinal, case in enumerate(cases)
        for method in counterbalanced_order(
            methods,
            case_ordinal=case_ordinal,
            namespace="milai-dg11-paper-v1:MEMORA:retrieval",
        )
    ]
    if len(records) != len(cases) * len(methods):
        raise MemoraRunnerError("Memora controlled context denominator drifted")
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id="MEMORA-PREREGISTERED-60",
        records=records,
        metadata={
            "cohort_stats": cohort_stats,
            "labels_accessed": False,
            "paper_labels_opened": False,
        },
    )
    if not isinstance(payload, dict):
        raise MemoraRunnerError("Memora context archive writer drifted")
    return payload


def _atomic_json_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise MemoraRunnerError("existing Memora generation archive is invalid")
        left = {key: item for key, item in existing.items() if key != "finished_at"}
        right = {key: item for key, item in value.items() if key != "finished_at"}
        if left != right:
            raise MemoraRunnerError("completed Memora generation archive drifted")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def run_answers(
    *,
    run_id: str,
    input_path: Path,
    context_archives: Sequence[Path],
    output_dir: Path,
    methods: tuple[str, ...],
    workers: int,
    memory_token_budget: int,
    prompt_token_budget: int,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    _cohorts, cases = load_inputs(input_path)
    contexts = {}
    for archive in context_archives:
        for record in read_context_archive(archive):
            key = (record.case_id, record.method_id)
            if key in contexts:
                raise MemoraRunnerError(f"duplicate Memora context: {key}")
            contexts[key] = record
    expected = {(case.case_id, method) for case in cases for method in methods}
    if set(contexts) != expected:
        raise MemoraRunnerError("Memora answer context denominator drifted")
    client = FrozenVllmClient(prompt_token_budget=prompt_token_budget)
    prepared = []
    fitted_contexts = {}
    ordinal = 0
    for case_ordinal, case in enumerate(cases):
        for method in counterbalanced_order(
            methods,
            case_ordinal=case_ordinal,
            namespace="milai-dg11-paper-v1:MEMORA:answer",
        ):
            context = contexts[(case.case_id, method)]
            fitted = client.fit_memory(
                question=case.question,
                question_as_of=case.question_at,
                memory_context=context.context,
                max_memory_tokens=memory_token_budget,
            )
            logical_id = f"{run_id}-{case_ordinal + 1:04d}-{method.casefold()}"
            prepared.append(
                client.prepare(
                    ordinal=ordinal,
                    logical_request_id=logical_id,
                    case_id=case.case_id,
                    method_id=method,
                    question=case.question,
                    question_as_of=case.question_at,
                    memory_context=fitted.context,
                    max_memory_tokens=memory_token_budget,
                )
            )
            fitted_contexts[(case.case_id, method)] = fitted
            ordinal += 1
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = UsageLedger(output_dir / "usage-ledger.jsonl")
    terminals = PaperAnswerRunner(
        ledger, max_workers=workers, max_memory_tokens=memory_token_budget
    ).execute(prepared, client.complete)
    cases_by_id = {case.case_id: case for case in cases}
    raw_records = []
    for terminal in terminals:
        case_id = str(terminal["case_id"])
        method = str(terminal["method_id"])
        fitted = fitted_contexts[(case_id, method)]
        context = contexts[(case_id, method)]
        raw_records.append(
            {
                **dict(terminal),
                "context_sha256": hashlib.sha256(fitted.context.encode()).hexdigest(),
                "context_truncated_by_final_recount": fitted.truncated,
                "memory_tokens": fitted.accounting.memory_tokens,
                "question": cases_by_id[case_id].question,
                "question_at": cases_by_id[case_id].question_at,
                "retrieval_latency_ms": context.latency_ms,
                "retrieval_trace": [dict(item) for item in context.trace],
                "source_ids": list(context.source_ids),
                "task": cases_by_id[case_id].task,
                "track": context.track,
                "usage": dict(context.usage),
            }
        )
    verification = ledger.verify()
    payload: dict[str, Any] = {
        "benchmark_id": "MEMORA-PREREGISTERED-60",
        "case_count": len(cases),
        "expected_answer_calls": len(cases) * len(methods),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ledger_root_sha256": verification.root_sha256,
        "methods": list(methods),
        "paper_labels_opened": False,
        "raw_records": raw_records,
        "record_count": len(raw_records),
        "run_id": run_id,
        "schema": "milai.dg11.paper-memora-generations.v1",
        "status": "PASS" if len(raw_records) == len(cases) * len(methods) else "FAIL",
        "workers": workers,
    }
    _atomic_json_once(output_dir / "raw-generations.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    contexts = subparsers.add_parser("contexts")
    contexts.add_argument("--run-id", required=True)
    contexts.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    contexts.add_argument("--output", type=Path, required=True)
    contexts.add_argument("--methods", default=",".join(CONTROLLED_METHODS))
    contexts.add_argument("--token-budget", type=int, default=512)
    contexts.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    contexts.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    contexts.add_argument("--allow-unfrozen-smoke", action="store_true")
    answers = subparsers.add_parser("answers")
    answers.add_argument("--run-id", required=True)
    answers.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    answers.add_argument("--contexts", type=Path, action="append", required=True)
    answers.add_argument("--output-dir", type=Path, required=True)
    answers.add_argument("--methods", default=",".join(ALL_METHODS))
    answers.add_argument(
        "--workers",
        type=int,
        choices=WORKER_CHOICES,
        default=ANSWER_PROVIDER_LANE.default_workers,
    )
    answers.add_argument("--memory-token-budget", type=int, default=512)
    answers.add_argument("--prompt-token-budget", type=int, default=32768)
    answers.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    answers.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    if args.command == "contexts":
        result = prepare_contexts(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            output=args.output.resolve(),
            methods=_methods(args.methods, allowed=CONTROLLED_METHODS),
            token_budget=args.token_budget,
            tokenizer_path=args.tokenizer.resolve(),
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        )
    else:
        result = run_answers(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            context_archives=[path.resolve() for path in args.contexts],
            output_dir=args.output_dir.resolve(),
            methods=_methods(args.methods, allowed=ALL_METHODS),
            workers=args.workers,
            memory_token_budget=args.memory_token_budget,
            prompt_token_budget=args.prompt_token_budget,
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        )
    print(json.dumps({"schema": result["schema"], "status": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
