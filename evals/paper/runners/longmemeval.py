"""LongMemEval context, answer, and deterministic scoring pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from tokenizers import Tokenizer

from evals.paper.adapters import (
    CustomLexicalTop1Adapter,
    FullHistoryAdapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
    OracleAdapter,
)
from evals.paper.answer_runner import PaperAnswerRunner
from evals.paper.contracts import (
    ContextRecord,
    MemoryAdapter,
    MemoryEvent,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.longmemeval import (
    LongMemEvalCase,
    labels_from_dataset,
    load_inputs,
)
from evals.paper.freeze import (
    DEFAULT_MANIFEST,
    require_paper_evaluation_ready,
)
from evals.paper.identity import sha256_file
from evals.paper.parallelism import ANSWER_PROVIDER_LANE, WORKER_CHOICES
from evals.paper.provider import FrozenVllmClient
from evals.paper.schedules import counterbalanced_order
from evals.paper.scorers.longmemeval import score_answer, score_retrieval
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FULL_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
DEFAULT_HOLDOUT_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-holdout-inputs.json"
DEFAULT_DATASET = Path(
    "/cra/memory/mx_memory/benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
)
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
CONTROLLED_METHODS = (
    "CTRL-NONE",
    "CTRL-CUSTOM-LEX1",
    "LME-BM25-S",
    "LME-BM25-T",
)
CHARACTERIZATION_METHODS = ("CTRL-FULL", "CTRL-TRUNC-FULL")
ORACLE_METHODS = ("LME-ORACLE",)
TRACKS = {
    "CTRL-NONE": "CONTROLLED",
    "CTRL-CUSTOM-LEX1": "CONTROLLED",
    "LME-BM25-S": "CONTROLLED",
    "LME-BM25-T": "CONTROLLED",
    "LME-DENSE": "CONTROLLED",
    "DG10-FROZEN": "CONTROLLED",
    "DG11-FULL": "CONTROLLED",
    "MEM0-OSS": "NATIVE",
    "HINDSIGHT-OSS": "NATIVE",
    "GRAPHITI-OSS": "NATIVE",
    "REME-OSS": "NATIVE",
    "LME-ORACLE": "UPPER_BOUND",
    "CTRL-FULL": "LONG_CONTEXT_CHARACTERIZATION",
    "CTRL-TRUNC-FULL": "LONG_CONTEXT_CHARACTERIZATION",
}


class LongMemEvalRunnerError(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _write_generation_once(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Keep completed raw generations append-only across safe resume attempts."""

    if not path.exists():
        _atomic_json(path, value)
        return value
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LongMemEvalRunnerError("existing generation archive is invalid") from exc
    if not isinstance(existing, dict):
        raise LongMemEvalRunnerError("existing generation archive is not an object")
    comparable_existing = {
        key: item for key, item in existing.items() if key != "finished_at"
    }
    comparable_value = {
        key: item for key, item in value.items() if key != "finished_at"
    }
    if comparable_existing != comparable_value:
        raise LongMemEvalRunnerError(
            "completed generation archive differs from the resumed result"
        )
    return existing


def _methods(value: str) -> tuple[str, ...]:
    methods = tuple(item.strip() for item in value.split(",") if item.strip())
    if not methods or len(set(methods)) != len(methods):
        raise LongMemEvalRunnerError("method list must be non-empty and unique")
    unknown = set(methods).difference(TRACKS)
    if unknown:
        raise LongMemEvalRunnerError(f"unknown LongMemEval methods: {sorted(unknown)}")
    return methods


def memory_events(case: LongMemEvalCase) -> tuple[MemoryEvent, ...]:
    events: list[MemoryEvent] = []
    for session in case.sessions:
        for turn_index, turn in enumerate(session.turns):
            events.append(
                MemoryEvent(
                    event_id=f"{session.session_id}:{turn_index}",
                    content=turn.content,
                    observed_at=session.observed_at,
                    actor=turn.role,
                    scope="dg11-paper-public-benchmark",
                    metadata={
                        "session_id": session.session_id,
                        "turn_index": turn_index,
                    },
                )
            )
    return tuple(events)


def _adapter(method_id: str, token_counter: Callable[[str], int]) -> MemoryAdapter:
    if method_id == "CTRL-NONE":
        return NoMemoryAdapter(token_counter=token_counter)
    if method_id == "CTRL-CUSTOM-LEX1":
        return CustomLexicalTop1Adapter(token_counter=token_counter)
    if method_id == "LME-BM25-S":
        return OfficialBM25Adapter(
            granularity="session", top_k=3, token_counter=token_counter
        )
    if method_id == "LME-BM25-T":
        return OfficialBM25Adapter(
            granularity="turn", top_k=3, token_counter=token_counter
        )
    if method_id == "CTRL-FULL":
        return FullHistoryAdapter(truncate=False, token_counter=token_counter)
    if method_id == "CTRL-TRUNC-FULL":
        return FullHistoryAdapter(truncate=True, token_counter=token_counter)
    if method_id == "LME-ORACLE":
        return OracleAdapter(token_counter=token_counter)
    raise LongMemEvalRunnerError(
        f"method requires an imported context archive: {method_id}"
    )


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
    labels: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if allow_unfrozen_smoke:
        if labels is not None:
            raise LongMemEvalRunnerError(
                "unfrozen smoke cannot construct oracle contexts"
            )
        require_unfrozen_smoke_inputs(input_path)
    else:
        require_paper_evaluation_ready(freeze_manifest)
    partition, cases = load_inputs(input_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    token_counter = lambda text: len(tokenizer.encode(text).ids)
    records: list[ContextRecord] = []
    for case_ordinal, case in enumerate(cases):
        for method_id in counterbalanced_order(
            methods,
            case_ordinal=case_ordinal,
            namespace=f"milai-dg11-paper-v1:{partition}:retrieval",
        ):
            adapter = _adapter(method_id, token_counter)
            adapter.reset(run_id, case.source_id)
            if isinstance(adapter, OracleAdapter):
                if labels is None:
                    raise LongMemEvalRunnerError(
                        "oracle contexts require explicit labels"
                    )
                raw_ids = labels[case.source_id].get("answer_session_ids")
                if not isinstance(raw_ids, list):
                    raise LongMemEvalRunnerError("oracle evidence labels are invalid")
                adapter.set_oracle_source_ids(str(item) for item in raw_ids)
            for event in memory_events(case):
                adapter.ingest(event)
            adapter.finalize()
            try:
                result = adapter.query(
                    case.question,
                    case.question_at,
                    token_budget,
                    (
                        "ORACLE_UPPER_BOUND"
                        if method_id == "LME-ORACLE"
                        else TRACKS[method_id]
                    ),
                )
                record = ContextRecord(
                    case_id=case.source_id,
                    method_id=method_id,
                    track=TRACKS[method_id],
                    context=result.context,
                    source_ids=result.source_ids,
                    trace=result.trace,
                    declared_tokens=result.declared_tokens,
                    latency_ms=result.latency_ms,
                    usage={
                        **dict(result.usage),
                        "adapter_storage_bytes": adapter.stats().storage_bytes,
                    },
                )
            except ValueError as exc:
                if method_id != "CTRL-FULL" or "exceeds" not in str(exc):
                    raise
                record = ContextRecord(
                    case_id=case.source_id,
                    method_id=method_id,
                    track=TRACKS[method_id],
                    context="",
                    source_ids=(),
                    trace=(),
                    declared_tokens=0,
                    latency_ms=0,
                    usage={"failure": "CONTEXT_LIMIT_EXCEEDED"},
                    terminal_status="CAPABILITY_UNSUPPORTED",
                )
            records.append(record)
            adapter.close()
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=records,
        metadata={
            "labels_accessed": "ORACLE_UPPER_BOUND_ONLY" if labels else False,
            "paper_labels_opened": labels is not None,
        },
    )
    return payload


def merge_contexts(
    *, run_id: str, benchmark_id: str, inputs: Sequence[Path], output: Path
) -> dict[str, Any]:
    records: list[ContextRecord] = []
    for path in inputs:
        records.extend(read_context_archive(path))
    return write_context_archive(
        output, run_id=run_id, benchmark_id=benchmark_id, records=records
    )


def require_unfrozen_smoke_inputs(input_path: Path) -> None:
    _partition, cases = load_inputs(input_path)
    _holdout_partition, holdout = load_inputs(DEFAULT_HOLDOUT_INPUTS)
    holdout_ids = {case.source_id for case in holdout}
    if len(cases) > 10 or any(case.source_id in holdout_ids for case in cases):
        raise LongMemEvalRunnerError("unfrozen smoke must use at most ten opened cases")


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
    if allow_unfrozen_smoke:
        require_unfrozen_smoke_inputs(input_path)
    else:
        require_paper_evaluation_ready(freeze_manifest)
    partition, cases = load_inputs(input_path)
    all_contexts: dict[tuple[str, str], ContextRecord] = {}
    for archive in context_archives:
        for record in read_context_archive(archive):
            key = (record.case_id, record.method_id)
            if key in all_contexts:
                raise LongMemEvalRunnerError(f"duplicate context pair: {key}")
            all_contexts[key] = record
    expected = {(case.source_id, method) for case in cases for method in methods}
    if set(all_contexts) != expected:
        missing = sorted(expected.difference(all_contexts))[:10]
        extra = sorted(set(all_contexts).difference(expected))[:10]
        raise LongMemEvalRunnerError(
            f"context denominator differs from answer plan; missing={missing}, extra={extra}"
        )
    if any(record.terminal_status != "SUCCEEDED" for record in all_contexts.values()):
        raise LongMemEvalRunnerError(
            "answer plan contains a non-success context terminal"
        )
    client = FrozenVllmClient(prompt_token_budget=prompt_token_budget)
    prepared = []
    fitted_contexts: dict[tuple[str, str], tuple[str, int, bool]] = {}
    ordinal = 0
    for case_ordinal, case in enumerate(cases):
        for method_id in counterbalanced_order(
            methods,
            case_ordinal=case_ordinal,
            namespace=f"milai-dg11-paper-v1:{partition}:answer",
        ):
            context_record = all_contexts[(case.source_id, method_id)]
            fitted = client.fit_memory(
                question=case.question,
                question_as_of=case.question_at,
                memory_context=context_record.context,
                max_memory_tokens=memory_token_budget,
            )
            logical_id = f"{run_id}-{case_ordinal + 1:04d}-{method_id.casefold()}"
            prepared.append(
                client.prepare(
                    ordinal=ordinal,
                    logical_request_id=logical_id,
                    case_id=case.source_id,
                    method_id=method_id,
                    question=case.question,
                    question_as_of=case.question_at,
                    memory_context=fitted.context,
                    max_memory_tokens=memory_token_budget,
                )
            )
            fitted_contexts[(case.source_id, method_id)] = (
                fitted.context,
                fitted.accounting.memory_tokens,
                fitted.truncated,
            )
            ordinal += 1
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = UsageLedger(output_dir / "usage-ledger.jsonl")
    runner = PaperAnswerRunner(
        ledger,
        max_workers=workers,
        max_memory_tokens=memory_token_budget,
    )
    terminal_records = runner.execute(prepared, client.complete)
    case_by_id = {case.source_id: case for case in cases}
    raw_records: list[dict[str, Any]] = []
    for terminal in terminal_records:
        case_id = str(terminal["case_id"])
        method_id = str(terminal["method_id"])
        context_record = all_contexts[(case_id, method_id)]
        fitted_context, fitted_tokens, truncated = fitted_contexts[(case_id, method_id)]
        raw_records.append(
            {
                **dict(terminal),
                "category": case_by_id[case_id].category,
                "context": fitted_context,
                "context_sha256": hashlib.sha256(fitted_context.encode()).hexdigest(),
                "context_truncated_by_final_recount": truncated,
                "memory_tokens": fitted_tokens,
                "question": case_by_id[case_id].question,
                "question_at": case_by_id[case_id].question_at,
                "retrieval_latency_ms": context_record.latency_ms,
                "retrieval_trace": [dict(item) for item in context_record.trace],
                "source_ids": list(context_record.source_ids),
                "track": context_record.track,
                "usage": dict(context_record.usage),
            }
        )
    verification = ledger.verify()
    payload: dict[str, Any] = {
        "benchmark_id": partition,
        "case_count": len(cases),
        "expected_answer_calls": len(cases) * len(methods),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ledger_root_sha256": verification.root_sha256,
        "methods": list(methods),
        "paper_labels_opened": False,
        "raw_records": raw_records,
        "record_count": len(raw_records),
        "run_id": run_id,
        "schema": "milai.dg11.paper-longmemeval-generations.v1",
        "status": "PASS" if len(raw_records) == len(cases) * len(methods) else "FAIL",
        "workers": workers,
    }
    return _write_generation_once(output_dir / "raw-generations.json", payload)


def _aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise LongMemEvalRunnerError("cannot aggregate an empty record group")
    return {
        "case_count": len(records),
        "exact_match_mean": round(
            mean(float(record["answer_score"]["exact_match"]) for record in records),
            9,
        ),
        "hit_at_k_mean": round(
            mean(float(record["retrieval_score"]["hit_at_k"]) for record in records),
            9,
        ),
        "ndcg_at_k_mean": round(
            mean(float(record["retrieval_score"]["ndcg_at_k"]) for record in records),
            9,
        ),
        "normalized_f1_mean": round(
            mean(float(record["answer_score"]["normalized_f1"]) for record in records),
            9,
        ),
        "relevant_coverage_at_k_mean": round(
            mean(
                float(record["retrieval_score"]["relevant_coverage_at_k"])
                for record in records
            ),
            9,
        ),
    }


def _consume_holdout(
    *, run_id: str, generation_path: Path, holdout_ids: set[str]
) -> Path:
    consumption = ROOT / "var/dg11/splits/v1/paper-test-v1/consumption.json"
    generation_sha256 = sha256_file(generation_path)
    payload = {
        "generation_path": str(generation_path.resolve()),
        "generation_sha256": generation_sha256,
        "holdout_case_count": len(holdout_ids),
        "labels_opened_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "schema": "milai.dg11.paper-test-consumption.v1",
        "status": "LABELS_OPENED_FOR_DETERMINISTIC_SCORING",
    }
    if consumption.exists():
        prior = json.loads(consumption.read_text(encoding="utf-8"))
        comparable = {
            key: value for key, value in payload.items() if key != "labels_opened_at"
        }
        prior_comparable = {
            key: value for key, value in prior.items() if key != "labels_opened_at"
        }
        if prior_comparable != comparable:
            raise LongMemEvalRunnerError(
                "paper holdout was already consumed by another run"
            )
        return consumption
    _atomic_json(consumption, payload)
    return consumption


def score_generations(
    *,
    run_id: str,
    input_path: Path,
    generation_path: Path,
    dataset: Path,
    output_dir: Path,
    freeze_manifest: Path,
) -> dict[str, Any]:
    require_paper_evaluation_ready(freeze_manifest)
    partition, cases = load_inputs(input_path)
    generations = json.loads(generation_path.read_text(encoding="utf-8"))
    if (
        not isinstance(generations, dict)
        or generations.get("schema") != "milai.dg11.paper-longmemeval-generations.v1"
        or generations.get("status") != "PASS"
        or not isinstance(generations.get("raw_records"), list)
    ):
        raise LongMemEvalRunnerError("generation archive is not score-ready")
    source_ids = tuple(case.source_id for case in cases)
    _holdout_partition, holdout_cases = load_inputs(DEFAULT_HOLDOUT_INPUTS)
    holdout_ids = {case.source_id for case in holdout_cases}
    if holdout_ids.issubset(source_ids):
        consumption = _consume_holdout(
            run_id=run_id,
            generation_path=generation_path,
            holdout_ids=holdout_ids,
        )
    else:
        consumption = None
    labels = labels_from_dataset(dataset, source_ids)
    scored: list[dict[str, Any]] = []
    for record in generations["raw_records"]:
        if not isinstance(record, dict):
            raise LongMemEvalRunnerError("generation record is invalid")
        case_id = str(record["case_id"])
        label = labels[case_id]
        trace = record.get("retrieval_trace")
        if not isinstance(trace, list) or not all(
            isinstance(item, dict) for item in trace
        ):
            raise LongMemEvalRunnerError("retrieval trace is invalid")
        scored.append(
            {
                **record,
                "answer_score": score_answer(
                    str(record["answer"]),
                    [str(item) for item in label["answers"]],
                ),
                "retrieval_score": score_retrieval(
                    trace,
                    [str(item) for item in label["answer_session_ids"]],
                ),
            }
        )
    by_method: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    by_category: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in scored:
        method = str(record["method_id"])
        by_method[method].append(record)
        by_category[(method, str(record["category"]))].append(record)
    metrics: dict[str, Any] = {
        "benchmark_id": partition,
        "case_count": len(cases),
        "consumption_path": str(consumption) if consumption else None,
        "generation_sha256": sha256_file(generation_path),
        "methods": {
            method: {
                "overall": _aggregate(records),
                "by_category": {
                    category: _aggregate(group)
                    for (candidate, category), group in sorted(by_category.items())
                    if candidate == method
                },
                "track": TRACKS[method],
            }
            for method, records in sorted(by_method.items())
        },
        "paper_labels_opened": True,
        "raw_denominator": len(scored),
        "run_id": run_id,
        "schema": "milai.dg11.paper-longmemeval-metrics.v1",
        "status": "PASS",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "scored-records.json", {"records": scored})
    _atomic_json(output_dir / "metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    contexts = subparsers.add_parser("contexts")
    contexts.add_argument("--run-id", required=True)
    contexts.add_argument("--inputs", type=Path, default=DEFAULT_FULL_INPUTS)
    contexts.add_argument("--output", type=Path, required=True)
    contexts.add_argument("--methods", default=",".join(CONTROLLED_METHODS))
    contexts.add_argument("--token-budget", type=int, default=512)
    contexts.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    contexts.add_argument("--oracle-dataset", type=Path)
    contexts.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    contexts.add_argument("--allow-unfrozen-smoke", action="store_true")
    merge = subparsers.add_parser("merge-contexts")
    merge.add_argument("--run-id", required=True)
    merge.add_argument("--benchmark-id", required=True)
    merge.add_argument("--input", action="append", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    answers = subparsers.add_parser("answers")
    answers.add_argument("--run-id", required=True)
    answers.add_argument("--inputs", type=Path, default=DEFAULT_FULL_INPUTS)
    answers.add_argument("--context-archive", action="append", type=Path, required=True)
    answers.add_argument("--output-dir", type=Path, required=True)
    answers.add_argument("--methods", required=True)
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
    score = subparsers.add_parser("score")
    score.add_argument("--run-id", required=True)
    score.add_argument("--inputs", type=Path, default=DEFAULT_FULL_INPUTS)
    score.add_argument("--generations", type=Path, required=True)
    score.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    score.add_argument("--output-dir", type=Path, required=True)
    score.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    if args.command == "contexts":
        selected_methods = _methods(args.methods)
        labels = None
        if args.oracle_dataset is not None:
            require_paper_evaluation_ready(args.freeze_manifest.resolve())
            _partition, cases = load_inputs(args.inputs.resolve())
            labels = labels_from_dataset(
                args.oracle_dataset.resolve(), tuple(case.source_id for case in cases)
            )
        result = prepare_contexts(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            output=args.output.resolve(),
            methods=selected_methods,
            token_budget=args.token_budget,
            tokenizer_path=args.tokenizer.resolve(),
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
            labels=labels,
        )
    elif args.command == "merge-contexts":
        result = merge_contexts(
            run_id=args.run_id,
            benchmark_id=args.benchmark_id,
            inputs=[path.resolve() for path in args.input],
            output=args.output.resolve(),
        )
    elif args.command == "answers":
        result = run_answers(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            context_archives=[path.resolve() for path in args.context_archive],
            output_dir=args.output_dir.resolve(),
            methods=_methods(args.methods),
            workers=args.workers,
            memory_token_budget=args.memory_token_budget,
            prompt_token_budget=args.prompt_token_budget,
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        )
    else:
        result = score_generations(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            generation_path=args.generations.resolve(),
            dataset=args.dataset.resolve(),
            output_dir=args.output_dir.resolve(),
            freeze_manifest=args.freeze_manifest.resolve(),
        )
    print(
        json.dumps(
            {
                "run_id": result.get("run_id", args.run_id),
                "status": result.get("status", "PASS"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
