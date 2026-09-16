"""Minimal exactly-once runner for the GDPM B0 context-only canary."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.gdpm.b0_canary_contract import (
    CANARY_CASE_COUNT,
    CanaryAuthorityReceipt,
    CanaryCaseMetadata,
    authorize_then_load,
    freeze_canary_manifest,
)

EVIDENCE_TOKEN_BUDGET = 4096
EXPECTED_METRICS: dict[str, float | int] = {
    "SessionIdentityIntegrity": 1.0,
    "CrossSourceSessionAdjacencyExpansion": 0,
    "ReaderVisibleTraceExactness": 1.0,
    "ContextSerializationReplayEquivalence": 1.0,
    "SystemFailureAsSemanticAbstention": 0,
    "ReaderCallsDuringContextPreflight": 0,
    "AtomicUnitTruncationCount": 0,
    "LongTurnSplitCount": 0,
    "RankFirstPrefixViolationCount": 0,
}
_TRACE_KEYS = {
    "admitted_evidence_trace",
    "raw_retrieval_trace",
    "reader_context",
    "reader_visible_trace",
}


class B0CanaryRunnerError(RuntimeError):
    """The context-only canary orchestration contract failed closed."""


@dataclass(frozen=True, slots=True)
class CanarySelectionInputs:
    metadata_pool: tuple[CanaryCaseMetadata, ...]
    parent_128_source_ids: tuple[str, ...]
    population_500_source_ids: tuple[str, ...]
    parent_128_manifest: Mapping[str, Any]
    population_500_manifest: Mapping[str, Any]
    required_query_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanaryContextCell:
    case_id: str
    status: str
    metrics: Mapping[str, float | int]
    trace: Mapping[str, object]
    reader_calls: int = 0
    answer_calls: int = 0
    judge_calls: int = 0
    canonical_mutation_count: int = 0
    failure_class: str | None = None
    semantic_abstention: bool = False


MetadataLoader = Callable[[], CanarySelectionInputs]
CaseLoader = Callable[[tuple[str, ...]], Mapping[str, object]]
ContextExecutor = Callable[[str, object, int], CanaryContextCell]


@dataclass(frozen=True, slots=True)
class CanaryBatchResult:
    cells: tuple[CanaryContextCell, ...]
    execution_receipt: Mapping[str, object]


BatchContextExecutor = Callable[
    [tuple[tuple[str, object], ...], int], CanaryBatchResult
]


def run_b0_context_only_canary(
    *,
    run_id: str,
    output_root: Path,
    master_path: Path,
    goal_path: Path,
    metadata_loader: MetadataLoader,
    case_loader: CaseLoader,
    context_executor: ContextExecutor | None = None,
    context_batch_executor: BatchContextExecutor | None = None,
    execution_plan: Mapping[str, object] | None = None,
    tokenizer_path: Path,
    tokenizer_sha256: str,
    chat_template_path: Path,
    chat_template_sha256: str,
    code_paths: Sequence[Path],
    authority_validator: Callable[..., CanaryAuthorityReceipt] | None = None,
    evidence_token_budget: int = EVIDENCE_TOKEN_BUDGET,
    scope_identity: str = "B0_24_CASE_CONTEXT_ONLY_CANARY",
    pass_terminal_status: str = "PASS_B0_24_CONTEXT_ONLY_CANARY_READY_FOR_128",
    fail_terminal_status: str = "FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED",
    pass_next_scope: str = "B0_128_CASE_UNTREATED_BASELINE",
    fail_next_scope: str = "B0_24_CASE_CONTEXT_ONLY_CANARY_REPAIR",
) -> dict[str, Any]:
    """Run exactly 24 context cells after authority and identity preflight."""

    if output_root.exists():
        raise B0CanaryRunnerError("run output already exists")
    _validate_run_parameters(
        evidence_token_budget=evidence_token_budget,
        scope_identity=scope_identity,
        pass_terminal_status=pass_terminal_status,
        fail_terminal_status=fail_terminal_status,
        pass_next_scope=pass_next_scope,
        fail_next_scope=fail_next_scope,
        execution_plan=execution_plan,
    )
    if (context_executor is None) == (context_batch_executor is None):
        raise B0CanaryRunnerError(
            "exactly one scalar or batch context executor is required"
        )
    if authority_validator is None:
        authority, selection = authorize_then_load(
            master_path=master_path,
            goal_path=goal_path,
            loader=metadata_loader,
        )
    else:
        authority = authority_validator(
            master_path=master_path,
            goal_path=goal_path,
        )
        _validate_authority_receipt(authority, scope_identity)
        selection = metadata_loader()
    _validate_authority_receipt(authority, scope_identity)
    _validate_execution_identity(
        tokenizer_path,
        tokenizer_sha256,
        "tokenizer",
    )
    _validate_execution_identity(
        chat_template_path,
        chat_template_sha256,
        "chat template",
    )
    case_manifest = freeze_canary_manifest(
        cases=selection.metadata_pool,
        parent_128_source_ids=selection.parent_128_source_ids,
        population_500_source_ids=selection.population_500_source_ids,
        parent_128_manifest=selection.parent_128_manifest,
        population_500_manifest=selection.population_500_manifest,
        required_query_capabilities=selection.required_query_capabilities,
    )
    case_ids = tuple(str(item["source_id"]) for item in case_manifest["cases"])
    cases = case_loader(case_ids)
    if set(cases) != set(case_ids) or len(cases) != CANARY_CASE_COUNT:
        raise B0CanaryRunnerError("case loader returned a different 24-case set")
    code_identity = _code_identity(code_paths)
    started_at = _now()
    output_root.mkdir(parents=True)
    trace_root = output_root / "trace-bundle"
    trace_root.mkdir()
    run_lock = _run_lock(
        run_id=run_id,
        created_at=started_at,
        authority=authority,
        master_path=master_path,
        goal_path=goal_path,
        case_manifest=case_manifest,
        parent_128_manifest=selection.parent_128_manifest,
        population_500_manifest=selection.population_500_manifest,
        tokenizer_path=tokenizer_path,
        tokenizer_sha256=tokenizer_sha256,
        chat_template_path=chat_template_path,
        chat_template_sha256=chat_template_sha256,
        code_identity=code_identity,
        execution_plan=execution_plan or {"mode": "SEQUENTIAL", "workers": 1},
        evidence_token_budget=evidence_token_budget,
        scope_identity=scope_identity,
    )
    _atomic_json(output_root / "run-lock.json", run_lock)

    attempts: Counter[str] = Counter()
    for case_id in case_ids:
        attempts[case_id] += 1
        if attempts[case_id] != 1:
            raise B0CanaryRunnerError("logical context cell executed more than once")
    execution_receipt: Mapping[str, object] = {
        "status": "PASS",
        "mode": "SEQUENTIAL",
    }
    if context_batch_executor is not None:
        try:
            batch = context_batch_executor(
                tuple((case_id, cases[case_id]) for case_id in case_ids),
                evidence_token_budget,
            )
            cells = list(batch.cells)
            execution_receipt = dict(batch.execution_receipt)
        except Exception as exc:  # noqa: BLE001 - terminalize every planned cell
            cells = [_failure_cell(case_id, exc) for case_id in case_ids]
            execution_receipt = {
                "status": "FAIL",
                "failure_class": type(exc).__name__,
                "failure_message": str(exc)[:500],
            }
    else:
        assert context_executor is not None
        cells = []
        for case_id in case_ids:
            try:
                cell = context_executor(
                    case_id, cases[case_id], evidence_token_budget
                )
            except Exception as exc:  # noqa: BLE001 - seal typed per-cell failure
                cell = _failure_cell(case_id, exc)
            cells.append(cell)
    if len(cells) != CANARY_CASE_COUNT or {cell.case_id for cell in cells} != set(
        case_ids
    ):
        raise B0CanaryRunnerError("context executor returned a different 24-case set")
    cells_by_id = {cell.case_id: cell for cell in cells}
    cells = [cells_by_id[case_id] for case_id in case_ids]
    for case_id, cell in zip(case_ids, cells, strict=True):
        if cell.case_id != case_id:
            raise B0CanaryRunnerError("context executor returned the wrong case identity")

    trace_payload = {
        "schema_version": "mila-gdpm-b0-canary-trace-v0.1",
        "run_id": run_id,
        "case_count": len(cells),
        "cells": [
            {
                "case_id": cell.case_id,
                "status": cell.status,
                "failure_class": cell.failure_class,
                "semantic_abstention": cell.semantic_abstention,
                "trace": dict(cell.trace),
            }
            for cell in cells
        ],
        "execution_receipt": dict(execution_receipt),
    }
    trace_path = trace_root / "contexts.json"
    _atomic_json(trace_path, trace_payload)
    violations = {
        cell.case_id: _cell_violations(cell)
        for cell in cells
        if _cell_violations(cell)
    }
    execution_violations = (
        [] if execution_receipt.get("status") == "PASS" else ["EXECUTION_RECEIPT_FAIL"]
    )
    passed = (
        not violations
        and not execution_violations
        and len(cells) == CANARY_CASE_COUNT
    )
    metrics = _aggregate_metrics(cells)
    results = {
        "schema_version": "mila-gdpm-b0-canary-results-v0.1",
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "scope": scope_identity,
        "case_count": len(cells),
        "logical_attempt_count": sum(attempts.values()),
        "per_case_attempt_counts": dict(sorted(attempts.items())),
        "reader_calls": sum(cell.reader_calls for cell in cells),
        "answer_calls": sum(cell.answer_calls for cell in cells),
        "judge_calls": sum(cell.judge_calls for cell in cells),
        "canonical_mutation_count": sum(
            cell.canonical_mutation_count for cell in cells
        ),
        "formal_holdout_consumed": False,
        "metrics": metrics,
        "expected": EXPECTED_METRICS,
        "violations": violations,
        "execution_violations": execution_violations,
        "execution_receipt": dict(execution_receipt),
        "cases": [
            {
                "case_id": cell.case_id,
                "status": cell.status,
                "metrics": dict(cell.metrics),
                "reader_calls": cell.reader_calls,
                "answer_calls": cell.answer_calls,
                "judge_calls": cell.judge_calls,
                "canonical_mutation_count": cell.canonical_mutation_count,
                "failure_class": cell.failure_class,
                "semantic_abstention": cell.semantic_abstention,
            }
            for cell in cells
        ],
        "failure_class_counts": dict(
            sorted(
                Counter(
                    cell.failure_class
                    for cell in cells
                    if cell.failure_class is not None
                ).items()
            )
        ),
        "trace_bundle_sha256": _directory_digest(trace_root),
    }
    results_path = output_root / "results.json"
    _atomic_json(results_path, results)
    terminal = {
        "schema_version": "mila-gdpm-b0-canary-terminal-v0.1",
        "run_id": run_id,
        "status": (
            pass_terminal_status if passed else fail_terminal_status
        ),
        "block_complete": False,
        "goal_complete": False,
        "next_active_scope": (
            pass_next_scope if passed else fail_next_scope
        ),
        "case_count": len(cells),
        "reader_answer_judge_calls": sum(
            cell.reader_calls + cell.answer_calls + cell.judge_calls
            for cell in cells
        ),
        "formal_holdout_consumed": False,
        "run_lock_sha256": _sha256(output_root / "run-lock.json"),
        "results_sha256": _sha256(results_path),
        "trace_bundle_sha256": _directory_digest(trace_root),
        "completed_at": _now(),
    }
    _atomic_json(output_root / "terminal.json", terminal)
    return terminal


def _run_lock(
    *,
    run_id: str,
    created_at: str,
    authority: CanaryAuthorityReceipt,
    master_path: Path,
    goal_path: Path,
    case_manifest: Mapping[str, Any],
    parent_128_manifest: Mapping[str, Any],
    population_500_manifest: Mapping[str, Any],
    tokenizer_path: Path,
    tokenizer_sha256: str,
    chat_template_path: Path,
    chat_template_sha256: str,
    code_identity: Mapping[str, str],
    execution_plan: Mapping[str, object],
    evidence_token_budget: int,
    scope_identity: str,
) -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema_version": "mila-gdpm-b0-canary-run-lock-v0.1",
        "run_id": run_id,
        "created_at": created_at,
        "authority": {
            **asdict(authority),
            "master_path": str(master_path),
            "goal_path": str(goal_path),
        },
        "scope": {
            "identity": scope_identity,
            "case_count": CANARY_CASE_COUNT,
            "evidence_token_budget": evidence_token_budget,
            "reader_answer_judge_calls_authorized": False,
            "formal_holdout_authorized": False,
            "automatic_retry_count": 0,
        },
        "case_manifest": dict(case_manifest),
        "manifest_hierarchy": {
            "parent_128": dict(parent_128_manifest),
            "population_500": dict(population_500_manifest),
        },
        "reader_accounting": {
            "tokenizer_path": str(tokenizer_path),
            "tokenizer_sha256": tokenizer_sha256,
            "chat_template_path": str(chat_template_path),
            "chat_template_sha256": chat_template_sha256,
        },
        "code_artifacts": dict(sorted(code_identity.items())),
        "execution_plan": dict(execution_plan),
    }
    return {**material, "run_lock_digest": _digest(material)}


def _cell_violations(cell: CanaryContextCell) -> list[str]:
    violations: list[str] = []
    if cell.status != "PASS":
        violations.append("CELL_STATUS_NOT_PASS")
        if cell.failure_class not in {
            "INFRASTRUCTURE",
            "PROTOCOL_IMPLEMENTATION",
        }:
            violations.append("UNTYPED_CELL_FAILURE")
    elif cell.failure_class is not None:
        violations.append("FAILURE_CLASS_ON_PASS_CELL")
    if set(cell.metrics) != set(EXPECTED_METRICS):
        violations.append("METRIC_SCHEMA_DRIFT")
    else:
        violations.extend(
            f"METRIC_MISS:{name}"
            for name, expected in EXPECTED_METRICS.items()
            if cell.metrics[name] != expected
        )
    if set(cell.trace) != _TRACE_KEYS:
        violations.append("TRACE_SCHEMA_DRIFT")
    if cell.reader_calls or cell.answer_calls or cell.judge_calls:
        violations.append("FORBIDDEN_MODEL_CALL")
    if cell.canonical_mutation_count:
        violations.append("CANONICAL_MUTATION")
    if cell.failure_class in {"INFRASTRUCTURE", "PROTOCOL_IMPLEMENTATION"} and (
        cell.semantic_abstention
    ):
        violations.append("SYSTEM_FAILURE_MISCLASSIFIED_AS_SEMANTIC_ABSTENTION")
    return violations


def _failure_cell(case_id: str, error: Exception) -> CanaryContextCell:
    failure_class = (
        "INFRASTRUCTURE"
        if isinstance(error, (ConnectionError, OSError, TimeoutError))
        else "PROTOCOL_IMPLEMENTATION"
    )
    metrics = {
        name: 0 if expected == 1.0 else expected
        for name, expected in EXPECTED_METRICS.items()
    }
    return CanaryContextCell(
        case_id=case_id,
        status="FAILED",
        metrics=metrics,
        trace={
            "raw_retrieval_trace": {
                "failure_class": failure_class,
                "failure_type": type(error).__name__,
                "message": str(error)[:500],
            },
            "admitted_evidence_trace": {},
            "reader_visible_trace": {"reader_call_count": 0},
            "reader_context": "",
        },
        failure_class=failure_class,
        semantic_abstention=False,
    )


def _aggregate_metrics(cells: Sequence[CanaryContextCell]) -> dict[str, float | int]:
    if not cells:
        return dict(EXPECTED_METRICS)
    return {
        name: (
            min(float(cell.metrics.get(name, 0)) for cell in cells)
            if expected == 1.0
            else sum(int(cell.metrics.get(name, 1)) for cell in cells)
        )
        for name, expected in EXPECTED_METRICS.items()
    }


def _validate_run_parameters(
    *,
    evidence_token_budget: int,
    scope_identity: str,
    pass_terminal_status: str,
    fail_terminal_status: str,
    pass_next_scope: str,
    fail_next_scope: str,
    execution_plan: Mapping[str, object] | None,
) -> None:
    if type(evidence_token_budget) is not int or evidence_token_budget <= 0:
        raise B0CanaryRunnerError("evidence token budget must be a positive integer")
    labels = {
        "scope identity": scope_identity,
        "pass terminal status": pass_terminal_status,
        "fail terminal status": fail_terminal_status,
        "pass next scope": pass_next_scope,
        "fail next scope": fail_next_scope,
    }
    empty = sorted(label for label, value in labels.items() if not value.strip())
    if empty:
        raise B0CanaryRunnerError(f"run identity fields are empty: {empty}")
    if execution_plan is not None and (
        execution_plan.get("evidence_token_budget") != evidence_token_budget
    ):
        raise B0CanaryRunnerError(
            "execution plan evidence budget differs from the canary budget"
        )


def _validate_authority_receipt(
    receipt: CanaryAuthorityReceipt,
    scope_identity: str,
) -> None:
    if not isinstance(receipt, CanaryAuthorityReceipt):
        raise B0CanaryRunnerError("authority validator returned an invalid receipt")
    if (
        receipt.scope != scope_identity
        or receipt.case_count != CANARY_CASE_COUNT
        or receipt.reader_answer_judge_calls != 0
        or receipt.formal_holdout_consumed
    ):
        raise B0CanaryRunnerError("authority receipt differs from the canary scope")


def _validate_execution_identity(path: Path, expected: str, label: str) -> None:
    if _sha256(path) != expected:
        raise B0CanaryRunnerError(f"{label} identity drifted")


def _code_identity(paths: Sequence[Path]) -> dict[str, str]:
    if not paths or len({str(path.resolve()) for path in paths}) != len(paths):
        raise B0CanaryRunnerError("code identity paths are empty or duplicated")
    return {str(path.resolve()): _sha256(path) for path in paths}


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_canonical(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory_digest(path: Path) -> str:
    files = {
        str(item.relative_to(path)): _sha256(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }
    return _digest(files)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
