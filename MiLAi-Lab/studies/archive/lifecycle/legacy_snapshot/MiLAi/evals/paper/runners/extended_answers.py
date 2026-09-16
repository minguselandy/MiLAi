"""Common-answer runner for BEAM, HorizonBench, and CUPID contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.answer_runner import PaperAnswerRunner
from evals.paper.contracts import ContextRecord, read_context_archive
from evals.paper.datasets.extended import load_extended_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.parallelism import ANSWER_PROVIDER_LANE, WORKER_CHOICES
from evals.paper.provider import FrozenVllmClient
from evals.paper.schedules import counterbalanced_order
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[3]
METHODS = ("CTRL-NONE", "LME-BM25-S", "CTRL-TRUNC-FULL", "DG11-FULL")


class ExtendedAnswerError(RuntimeError):
    pass


def _methods(value: str) -> tuple[str, ...]:
    methods = tuple(item.strip() for item in value.split(",") if item.strip())
    if not methods or len(set(methods)) != len(methods):
        raise ExtendedAnswerError("extended method list must be non-empty and unique")
    unknown = set(methods).difference(METHODS)
    if unknown:
        raise ExtendedAnswerError(f"unknown extended methods: {sorted(unknown)}")
    return methods


def _atomic_json_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise ExtendedAnswerError("extended generation archive is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _contexts(
    archives: Sequence[Path], expected: set[tuple[str, str]]
) -> dict[tuple[str, str], ContextRecord]:
    records: dict[tuple[str, str], ContextRecord] = {}
    for archive in archives:
        envelope = json.loads(archive.read_text(encoding="utf-8"))
        if (
            not isinstance(envelope, dict)
            or envelope.get("paper_labels_opened") is not False
            or envelope.get("labels_accessed") is not False
        ):
            raise ExtendedAnswerError("extended context label boundary drifted")
        for record in read_context_archive(archive):
            key = (record.case_id, record.method_id)
            if key in records:
                raise ExtendedAnswerError(f"duplicate extended context: {key}")
            if record.terminal_status != "SUCCEEDED":
                raise ExtendedAnswerError(f"non-success extended context: {key}")
            records[key] = record
    if set(records) != expected:
        raise ExtendedAnswerError("extended answer context denominator drifted")
    return records


def run(
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
    ANSWER_PROVIDER_LANE.validate(workers)
    if memory_token_budget <= 0:
        raise ExtendedAnswerError("extended memory token budget must be positive")
    partition, cases = load_extended_inputs(input_path)
    if allow_unfrozen_smoke:
        if "SMOKE" not in partition:
            raise ExtendedAnswerError("unfrozen extended answers require smoke inputs")
    else:
        require_paper_evaluation_ready(freeze_manifest)
    expected = {(case.case_id, method) for case in cases for method in methods}
    contexts = _contexts(context_archives, expected)
    client = FrozenVllmClient(prompt_token_budget=prompt_token_budget)
    prepared = []
    fitted_contexts = {}
    ordinal = 0
    for case_ordinal, case in enumerate(cases):
        for method in counterbalanced_order(
            methods,
            case_ordinal=case_ordinal,
            namespace=f"milai-dg11-paper-v1:{partition}:answer",
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
                "category": cases_by_id[case_id].category,
                "context_sha256": hashlib.sha256(fitted.context.encode()).hexdigest(),
                "context_truncated_by_final_recount": fitted.truncated,
                "memory_tokens": fitted.accounting.memory_tokens,
                "question": cases_by_id[case_id].question,
                "question_at": cases_by_id[case_id].question_at,
                "retrieval_latency_ms": context.latency_ms,
                "retrieval_trace": [dict(item) for item in context.trace],
                "source_ids": list(context.source_ids),
                "track": context.track,
                "usage": dict(context.usage),
            }
        )
    verification = ledger.verify()
    expected_calls = len(cases) * len(methods)
    payload: dict[str, Any] = {
        "answer_model": "Qwen3.6-35B-A3B-FP8",
        "benchmark_id": partition,
        "case_count": len(cases),
        "context_archive_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path) for path in context_archives
        },
        "development_ai_reviews": 0,
        "expected_answer_calls": expected_calls,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": sha256_file(input_path),
        "ledger_root_sha256": verification.root_sha256,
        "methods": list(methods),
        "paper_labels_opened": False,
        "raw_records": raw_records,
        "record_count": len(raw_records),
        "run_id": run_id,
        "runner_source_sha256": sha256_file(Path(__file__)),
        "schema": "milai.dg11.paper-extended-generations.v1",
        "status": "PASS" if len(raw_records) == expected_calls else "FAIL",
        "workers": workers,
    }
    _atomic_json_once(output_dir / "raw-generations.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument(
        "--workers",
        type=int,
        choices=WORKER_CHOICES,
        default=ANSWER_PROVIDER_LANE.default_workers,
    )
    parser.add_argument("--memory-token-budget", type=int, default=512)
    parser.add_argument("--prompt-token-budget", type=int, default=32_768)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        context_archives=[path.resolve() for path in args.contexts],
        output_dir=args.output_dir.resolve(),
        methods=_methods(args.methods),
        workers=args.workers,
        memory_token_budget=args.memory_token_budget,
        prompt_token_budget=args.prompt_token_budget,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
    )
    print(
        json.dumps(
            {
                "record_count": result["record_count"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
