"""Protocol-v3 LongMemEval denominator and answer execution.

Context production remains method-owned. This coordinator accepts one or more
strict context archives, requires every frozen method/case pair exactly once,
uses the literal frozen schedule, and retains context failures as zero-score
terminals without calling the answer provider.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from evals.paper.answer_runner import PreparedAnswer, prompt_sha256
from evals.paper.archive import ArchiveError, scan_archive
from evals.paper.contracts import ContextRecord, read_context_archive
from evals.paper.datasets.longmemeval import labels_from_dataset, load_inputs
from evals.paper.parallelism import ANSWER_PROVIDER_LANE
from evals.paper.scorers.longmemeval import SCORER_ID, score_answer, score_retrieval
from evals.paper.usage_ledger import UsageLedger

from .freeze import (
    require_formal_execution_ready,
    require_paper_v3_ready,
    sha256_file,
)
from .plan import build_lme_plan

ROOT = Path(__file__).resolve().parents[3]
HOLDOUT_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-holdout-inputs.json"
HOLDOUT_CONSUMPTION = ROOT / "var/dg11/splits/v1/paper-test-v1/consumption.json"


class FormalRunnerError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class RetainingAnswerRunner:
    """One-attempt runner that retains every provider failure in the denominator."""

    def __init__(
        self, ledger: UsageLedger, *, max_workers: int, max_memory_tokens: int
    ):
        if max_memory_tokens <= 0:
            raise ValueError("answer runner resource ceiling is invalid")
        ANSWER_PROVIDER_LANE.validate(max_workers)
        self._ledger = ledger
        self._max_workers = max_workers
        self._max_memory_tokens = max_memory_tokens

    def execute(
        self, prepared: Sequence[PreparedAnswer], answer_call: Any
    ) -> tuple[dict[str, Any], ...]:
        request_ids = tuple(item.logical_request_id for item in prepared)
        if len(request_ids) != len(set(request_ids)):
            raise FormalRunnerError("logical request IDs are not unique")
        if any(item.memory_tokens > self._max_memory_tokens for item in prepared):
            raise FormalRunnerError("prepared answer exceeds memory ceiling")
        summary = scan_archive(self._ledger.path, request_ids)
        if summary.manual_reconciliation:
            raise ArchiveError(
                "provider start without a terminal requires manual reconciliation"
            )
        prior: dict[str, dict[str, Any]] = {}
        for envelope in self._ledger.verify().events:
            event = envelope["event"]
            if not isinstance(event, dict) or event.get("type") != "TERMINAL":
                continue
            request_id = str(event["logical_request_id"])
            if request_id in request_ids:
                prior[request_id] = {
                    key: value for key, value in event.items() if key != "type"
                }
        runnable_ids = set(summary.safe_to_resume + summary.missing)
        initially_missing = set(summary.missing)
        runnable = [
            item for item in prepared if item.logical_request_id in runnable_ids
        ]
        results = dict(prior)

        def run_one(item: PreparedAnswer) -> dict[str, Any]:
            if item.logical_request_id in initially_missing:
                self._ledger.append(
                    {
                        "case_id": item.case_id,
                        "logical_request_id": item.logical_request_id,
                        "method_id": item.method_id,
                        "prompt_sha256": prompt_sha256(item.prompt),
                        "type": "RESERVED",
                    }
                )
            self._ledger.append(
                {
                    "logical_request_id": item.logical_request_id,
                    "type": "PROVIDER_STARTED",
                }
            )
            try:
                completion = answer_call(item)
                if completion.prompt_tokens != item.prompt_tokens:
                    raise FormalRunnerError(
                        "native prompt usage differs from preflight"
                    )
                record = {
                    "answer": completion.answer,
                    "case_id": item.case_id,
                    "completion_tokens": completion.completion_tokens,
                    "finish_reason": completion.finish_reason,
                    "logical_request_id": item.logical_request_id,
                    "memory_tokens": item.memory_tokens,
                    "method_id": item.method_id,
                    "native_request_id": completion.native_request_id,
                    "ordinal": item.ordinal,
                    "prompt_sha256": prompt_sha256(item.prompt),
                    "prompt_tokens": completion.prompt_tokens,
                    "status": "SUCCEEDED",
                }
            except Exception as exc:  # noqa: BLE001 - one attempt, terminal retained
                record = {
                    "answer": "",
                    "case_id": item.case_id,
                    "completion_tokens": 0,
                    "failure_class": type(exc).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                    "finish_reason": "PROVIDER_FAILURE",
                    "logical_request_id": item.logical_request_id,
                    "memory_tokens": item.memory_tokens,
                    "method_id": item.method_id,
                    "native_request_id": "",
                    "ordinal": item.ordinal,
                    "prompt_sha256": prompt_sha256(item.prompt),
                    "prompt_tokens": item.prompt_tokens,
                    "status": "FAILED",
                }
            self._ledger.append({**record, "type": "TERMINAL"})
            return record

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(run_one, item): item.logical_request_id
                for item in runnable
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        if set(results) != set(request_ids):
            raise FormalRunnerError("answer denominator is incomplete")
        return tuple(sorted(results.values(), key=lambda item: int(item["ordinal"])))


def load_complete_context_denominator(
    *, plan: dict[str, Any], context_archives: Sequence[Path]
) -> dict[tuple[str, str], ContextRecord]:
    if (
        plan.get("schema") != "milai.dg12.paper-lme-plan.v3"
        or plan.get("status") != "LABEL_FREE_PLAN_COMPLETE"
        or not isinstance(plan.get("cells"), list)
    ):
        raise FormalRunnerError("DG12 plan is invalid")
    records: dict[tuple[str, str], ContextRecord] = {}
    for archive in context_archives:
        for record in read_context_archive(archive):
            key = (record.case_id, record.method_id)
            if key in records:
                raise FormalRunnerError(f"duplicate context pair: {key}")
            records[key] = record
    expected = {
        (str(cell["case_id"]), str(cell["method_id"])) for cell in plan["cells"]
    }
    if set(records) != expected:
        missing = sorted(expected.difference(records))[:10]
        extra = sorted(set(records).difference(expected))[:10]
        raise FormalRunnerError(
            f"context denominator drifted; missing={missing}, extra={extra}"
        )
    return records


def denominator_summary(
    *, plan: dict[str, Any], contexts: dict[tuple[str, str], ContextRecord]
) -> dict[str, Any]:
    by_terminal: dict[str, int] = {}
    by_method_terminal: dict[str, dict[str, int]] = {}
    for cell in plan["cells"]:
        record = contexts[(str(cell["case_id"]), str(cell["method_id"]))]
        by_terminal[record.terminal_status] = (
            by_terminal.get(record.terminal_status, 0) + 1
        )
        method = by_method_terminal.setdefault(record.method_id, {})
        method[record.terminal_status] = method.get(record.terminal_status, 0) + 1
    return {
        "schema": "milai.dg12.context-denominator.v3",
        "status": "COMPLETE_WITH_RETAINED_TERMINALS",
        "cell_count": len(plan["cells"]),
        "terminal_counts": by_terminal,
        "method_terminal_counts": by_method_terminal,
        "non_success_cells_retained": sum(
            count for status, count in by_terminal.items() if status != "SUCCEEDED"
        ),
        "paper_labels_opened": False,
    }


def run_answers(
    *,
    run_id: str,
    input_path: Path,
    schedule_path: Path,
    context_archives: Sequence[Path],
    output_dir: Path,
    workers: int,
    memory_token_budget: int,
    prompt_token_budget: int,
    freeze_manifest: Path,
    execution_authorization: Path,
) -> dict[str, Any]:
    """Run one answer call for each successful context and retain all failures."""

    freeze = require_paper_v3_ready(freeze_manifest)
    require_formal_execution_ready(freeze_manifest, execution_authorization)
    ANSWER_PROVIDER_LANE.validate(
        workers, frozen_ceiling=int(freeze["execution"]["answer_workers_max"])
    )
    # Import only on the provider-bearing path so label-free preflight has no
    # tokenizer/provider dependency or side effect.
    from evals.paper.provider import FrozenVllmClient

    plan = build_lme_plan(input_path=input_path, schedule_path=schedule_path)
    contexts = load_complete_context_denominator(
        plan=plan, context_archives=context_archives
    )
    partition, cases = load_inputs(input_path)
    case_by_id = {case.source_id: case for case in cases}
    client = FrozenVllmClient(prompt_token_budget=prompt_token_budget)
    prepared = []
    success_meta: dict[str, dict[str, Any]] = {}
    terminal_without_call: dict[int, dict[str, Any]] = {}
    for cell in plan["cells"]:
        ordinal = int(cell["ordinal"])
        case_id = str(cell["case_id"])
        method_id = str(cell["method_id"])
        context = contexts[(case_id, method_id)]
        logical_id = f"{run_id}-{ordinal + 1:06d}-{method_id.casefold()}"
        if context.terminal_status != "SUCCEEDED":
            terminal_without_call[ordinal] = {
                "answer": "",
                "answer_terminal_status": "NOT_CALLED_CONTEXT_TERMINAL",
                "case_id": case_id,
                "completion_tokens": 0,
                "context_terminal_status": context.terminal_status,
                "finish_reason": "NOT_CALLED_CONTEXT_TERMINAL",
                "logical_request_id": logical_id,
                "memory_tokens": 0,
                "method_id": method_id,
                "native_request_id": "",
                "ordinal": ordinal,
                "prompt_sha256": None,
                "prompt_tokens": 0,
                "provider_called": False,
            }
            continue
        case = case_by_id[case_id]
        fitted = client.fit_memory(
            question=case.question,
            question_as_of=case.question_at,
            memory_context=context.context,
            max_memory_tokens=memory_token_budget,
        )
        item = client.prepare(
            ordinal=ordinal,
            logical_request_id=logical_id,
            case_id=case_id,
            method_id=method_id,
            question=case.question,
            question_as_of=case.question_at,
            memory_context=fitted.context,
            max_memory_tokens=memory_token_budget,
        )
        prepared.append(item)
        success_meta[logical_id] = {
            "context": fitted.context,
            "context_truncated_by_final_recount": fitted.truncated,
            "context_record": context,
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = UsageLedger(output_dir / "usage-ledger.jsonl")
    runner = RetainingAnswerRunner(
        ledger, max_workers=workers, max_memory_tokens=memory_token_budget
    )
    called = runner.execute(prepared, client.complete) if prepared else ()
    terminal_by_ordinal = dict(terminal_without_call)
    for terminal in called:
        ordinal = int(terminal["ordinal"])
        logical_id = str(terminal["logical_request_id"])
        context_record = success_meta[logical_id]["context_record"]
        terminal_by_ordinal[ordinal] = {
            **dict(terminal),
            "answer_terminal_status": str(terminal["status"]),
            "context_terminal_status": context_record.terminal_status,
            "provider_called": True,
        }
    if set(terminal_by_ordinal) != set(range(len(plan["cells"]))):
        raise FormalRunnerError("answer terminal denominator is incomplete")
    raw_records: list[dict[str, Any]] = []
    for cell in plan["cells"]:
        ordinal = int(cell["ordinal"])
        case_id = str(cell["case_id"])
        method_id = str(cell["method_id"])
        context = contexts[(case_id, method_id)]
        terminal = terminal_by_ordinal[ordinal]
        rendered = (
            str(success_meta[str(terminal["logical_request_id"])]["context"])
            if terminal["provider_called"]
            else ""
        )
        raw_records.append(
            {
                **terminal,
                "category": case_by_id[case_id].category,
                "context": rendered,
                "context_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                "question": case_by_id[case_id].question,
                "question_at": case_by_id[case_id].question_at,
                "retrieval_latency_ms": context.latency_ms,
                "retrieval_trace": [dict(item) for item in context.trace],
                "source_ids": list(context.source_ids),
                "track": context.track,
                "usage": dict(context.usage),
            }
        )
    verification = ledger.verify()
    payload = {
        "schema": "milai.dg12.paper-longmemeval-generations.v3",
        "status": "COMPLETE_WITH_RETAINED_TERMINALS",
        "benchmark_id": partition,
        "run_id": run_id,
        "case_count": len(cases),
        "method_count": plan["method_count"],
        "planned_cells": len(plan["cells"]),
        "answer_calls": len(called),
        "context_terminal_without_answer_call": len(terminal_without_call),
        "record_count": len(raw_records),
        "workers": workers,
        "schedule_namespace": plan["schedule_namespace"],
        "paper_labels_opened": False,
        "ledger_root_sha256": verification.root_sha256,
        "raw_records": raw_records,
    }
    generation_path = output_dir / "raw-generations.json"
    if generation_path.exists():
        if json.loads(generation_path.read_text(encoding="utf-8")) != payload:
            raise FormalRunnerError("completed generation archive drifted")
    else:
        _atomic_json(generation_path, payload)
    return payload


def _aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise FormalRunnerError("cannot aggregate an empty score group")
    return {
        "cell_count": len(records),
        "answer_failure_count": sum(
            record["answer_terminal_status"] != "SUCCEEDED" for record in records
        ),
        "context_failure_count": sum(
            record["context_terminal_status"] != "SUCCEEDED" for record in records
        ),
        "exact_match_mean": round(
            mean(float(record["answer_score"]["exact_match"]) for record in records), 9
        ),
        "normalized_f1_mean": round(
            mean(float(record["answer_score"]["normalized_f1"]) for record in records),
            9,
        ),
        "hit_at_k_mean": round(
            mean(float(record["retrieval_score"]["hit_at_k"]) for record in records), 9
        ),
        "ndcg_at_k_mean": round(
            mean(float(record["retrieval_score"]["ndcg_at_k"]) for record in records),
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


def consume_holdout_labels(
    *,
    run_id: str,
    input_path: Path,
    label_dataset: Path,
    expected_label_sha256: str,
    first_purpose: str,
) -> Path:
    """Create the one-way audit record immediately before the first label read."""

    if input_path.resolve() != HOLDOUT_INPUTS.resolve():
        raise FormalRunnerError("formal labels require the frozen paper holdout")
    if not label_dataset.is_file():
        raise FormalRunnerError("LongMemEval label source is absent")
    _partition, cases = load_inputs(input_path)
    payload = {
        "schema": "milai.dg12.paper-test-consumption.v3",
        "status": "LABELS_OPENED_FOR_FORMAL_ORACLE_OR_SCORING",
        "run_id": run_id,
        "input_path": str(input_path.resolve()),
        "input_sha256": sha256_file(input_path),
        "label_dataset_path": str(label_dataset.resolve()),
        "label_dataset_sha256": expected_label_sha256,
        "holdout_case_count": len(cases),
        "first_purpose": first_purpose,
        "labels_opened_at": datetime.now(timezone.utc).isoformat(),
    }
    if HOLDOUT_CONSUMPTION.exists():
        prior = json.loads(HOLDOUT_CONSUMPTION.read_text(encoding="utf-8"))
        keys = set(payload).difference({"labels_opened_at", "first_purpose"})
        if any(prior.get(key) != payload[key] for key in keys):
            raise FormalRunnerError("paper holdout was already consumed by another run")
    else:
        _atomic_json(HOLDOUT_CONSUMPTION, payload)
    if sha256_file(label_dataset) != expected_label_sha256:
        raise FormalRunnerError("LongMemEval label source drifted from the freeze")
    return HOLDOUT_CONSUMPTION


def score_generations(
    *,
    run_id: str,
    input_path: Path,
    generation_path: Path,
    label_dataset: Path,
    output_dir: Path,
    freeze_manifest: Path,
    execution_authorization: Path,
) -> dict[str, Any]:
    """Open labels once after the v3 freeze and score the complete denominator."""

    freeze = require_paper_v3_ready(freeze_manifest)
    require_formal_execution_ready(freeze_manifest, execution_authorization)
    execution = freeze["execution"]
    if input_path.resolve() != HOLDOUT_INPUTS.resolve():
        raise FormalRunnerError("formal scoring requires the frozen paper holdout")
    partition, cases = load_inputs(input_path)
    generations = json.loads(generation_path.read_text(encoding="utf-8"))
    raw_records = (
        generations.get("raw_records") if isinstance(generations, dict) else None
    )
    if (
        not isinstance(generations, dict)
        or generations.get("schema") != "milai.dg12.paper-longmemeval-generations.v3"
        or generations.get("status") != "COMPLETE_WITH_RETAINED_TERMINALS"
        or generations.get("run_id") != run_id
        or generations.get("case_count") != len(cases)
        or generations.get("method_count") != 11
        or not isinstance(raw_records, list)
        or len(raw_records) != len(cases) * 11
    ):
        raise FormalRunnerError("generation archive is not v3 score-ready")
    expected_pairs = {
        (case.source_id, method)
        for case in cases
        for method in execution["longmemeval_methods"]
    }
    actual_pairs = {
        (str(record["case_id"]), str(record["method_id"])) for record in raw_records
    }
    if actual_pairs != expected_pairs or len(actual_pairs) != len(raw_records):
        raise FormalRunnerError("generation denominator differs from the freeze")

    consumption = consume_holdout_labels(
        run_id=run_id,
        input_path=input_path,
        label_dataset=label_dataset,
        expected_label_sha256=str(execution["label_dataset_sha256"]),
        first_purpose="DETERMINISTIC_SCORING",
    )
    labels = labels_from_dataset(label_dataset, tuple(case.source_id for case in cases))
    scored: list[dict[str, Any]] = []
    for record in raw_records:
        case_id = str(record["case_id"])
        label = labels[case_id]
        context_succeeded = record["context_terminal_status"] == "SUCCEEDED"
        answer_succeeded = record["answer_terminal_status"] == "SUCCEEDED"
        answer_score = (
            score_answer(str(record["answer"]), label["answers"])
            if answer_succeeded
            else {"exact_match": 0, "normalized_f1": 0.0, "scorer": SCORER_ID}
        )
        retrieval_score = (
            score_retrieval(record["retrieval_trace"], label["answer_session_ids"])
            if context_succeeded
            else {
                "hit_at_k": 0,
                "ndcg_at_k": 0.0,
                "relevant_coverage_at_k": 0.0,
                "retrieved_k": 0,
            }
        )
        scored.append(
            {**record, "answer_score": answer_score, "retrieval_score": retrieval_score}
        )

    by_method: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    by_category: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in scored:
        method = str(record["method_id"])
        by_method[method].append(record)
        by_category[(method, str(record["category"]))].append(record)
    metrics = {
        "schema": "milai.dg12.paper-longmemeval-metrics.v3",
        "status": "COMPLETE_WITH_RETAINED_FAILURES",
        "benchmark_id": partition,
        "run_id": run_id,
        "case_count": len(cases),
        "method_count": 11,
        "raw_denominator": len(scored),
        "generation_sha256": sha256_file(generation_path),
        "consumption_path": str(consumption),
        "paper_labels_opened": True,
        "methods": {
            method: {
                "overall": _aggregate(records),
                "by_category": {
                    category: _aggregate(group)
                    for (candidate, category), group in sorted(by_category.items())
                    if candidate == method
                },
                "track": str(records[0]["track"]),
            }
            for method, records in sorted(by_method.items())
        },
    }
    _atomic_json(output_dir / "scored-records.json", {"records": scored})
    _atomic_json(output_dir / "metrics.json", metrics)
    return metrics
