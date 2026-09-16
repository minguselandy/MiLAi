"""Independent-evaluator runner and deterministic FAMA aggregation for Memora."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.paper.archive import ArchiveError, scan_archive
from evals.paper.datasets.memora import load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.judge_provider import (
    FrozenJudgeClient,
    JudgeCompletion,
    PreparedJudge,
    prompt_contract_sha256,
)
from evals.paper.parallelism import JUDGE_PROVIDER_LANE, WORKER_CHOICES
from evals.paper.schedules import counterbalanced_order
from evals.paper.scorers.memora import (
    DEFAULT_DATA_ROOT,
    MemoraCriterion,
    aggregate_judgments,
    load_official_criteria,
)
from evals.paper.usage_ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_GENERATIONS = ROOT / "var/dg11/paper/results/memora/raw-generations.json"
DEFAULT_OUTPUT_DIR = ROOT / "var/dg11/paper/results/memora"
JudgeCall = Callable[[PreparedJudge], JudgeCompletion]


class MemoraJudgeRunnerError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoraJudgeRunnerError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise MemoraJudgeRunnerError(f"expected JSON object: {path}")
    return value


def _atomic_json_equal(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        existing = _object(path)
        left = {key: item for key, item in existing.items() if key != "finished_at"}
        right = {key: item for key, item in value.items() if key != "finished_at"}
        if left != right:
            raise MemoraJudgeRunnerError("completed Memora score artifact drifted")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return value


def _prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def _successful_terminals(ledger: UsageLedger) -> dict[str, Mapping[str, Any]]:
    terminals: dict[str, Mapping[str, Any]] = {}
    for envelope in ledger.verify().events:
        event = envelope["event"]
        if (
            not isinstance(event, dict)
            or event.get("type") != "TERMINAL"
            or event.get("status") != "SUCCEEDED"
        ):
            continue
        request_id = str(event["logical_request_id"])
        terminals[request_id] = {
            key: value for key, value in event.items() if key not in {"status", "type"}
        }
    return terminals


class MemoraJudgeRunner:
    def __init__(
        self,
        ledger: UsageLedger,
        *,
        max_workers: int = JUDGE_PROVIDER_LANE.default_workers,
    ) -> None:
        JUDGE_PROVIDER_LANE.validate(max_workers)
        self.ledger = ledger
        self.max_workers = max_workers

    def execute(
        self, prepared: Sequence[PreparedJudge], judge_call: JudgeCall
    ) -> tuple[Mapping[str, Any], ...]:
        request_ids = tuple(item.logical_request_id for item in prepared)
        if len(request_ids) != len(set(request_ids)):
            raise MemoraJudgeRunnerError("judge logical request IDs are not unique")
        summary = scan_archive(self.ledger.path, request_ids)
        if summary.failed or summary.manual_reconciliation:
            raise ArchiveError(
                "judge archive contains failures or an ambiguous provider start"
            )
        results: dict[str, Mapping[str, Any]] = dict(_successful_terminals(self.ledger))
        initially_missing = set(summary.missing)
        runnable = [
            item
            for item in prepared
            if item.logical_request_id in set(summary.safe_to_resume + summary.missing)
        ]

        def run_one(item: PreparedJudge) -> Mapping[str, Any]:
            if item.logical_request_id in initially_missing:
                self.ledger.append(
                    {
                        "case_id": item.case_id,
                        "criterion_id": item.criterion_id,
                        "logical_request_id": item.logical_request_id,
                        "method_id": item.method_id,
                        "prompt_sha256": _prompt_sha256(item.prompt),
                        "type": "RESERVED",
                    }
                )
            self.ledger.append(
                {
                    "logical_request_id": item.logical_request_id,
                    "type": "PROVIDER_STARTED",
                }
            )
            try:
                completion = judge_call(item)
            except Exception as exc:
                self.ledger.append(
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                        "logical_request_id": item.logical_request_id,
                        "status": "FAILED",
                        "type": "TERMINAL",
                    }
                )
                raise
            if completion.prompt_tokens != item.prompt_tokens:
                raise MemoraJudgeRunnerError(
                    "native judge usage differs from tokenizer preflight"
                )
            record = {
                "case_id": item.case_id,
                "completion_tokens": completion.completion_tokens,
                "confidence": completion.confidence,
                "criterion_id": item.criterion_id,
                "evaluation_type": item.evaluation_type,
                "expected_answer": item.expected_answer,
                "explanation_sha256": completion.explanation_sha256,
                "finish_reason": completion.finish_reason,
                "is_correct": completion.judge_answer == item.expected_answer,
                "judge_answer": completion.judge_answer,
                "logical_request_id": item.logical_request_id,
                "method_id": item.method_id,
                "native_request_id": completion.native_request_id,
                "ordinal": item.ordinal,
                "prompt_sha256": _prompt_sha256(item.prompt),
                "prompt_tokens": completion.prompt_tokens,
            }
            self.ledger.append({**record, "status": "SUCCEEDED", "type": "TERMINAL"})
            return record

        with ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="paper-memora-judge"
        ) as executor:
            futures = {
                executor.submit(run_one, item): item.logical_request_id
                for item in runnable
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        if set(results) != set(request_ids):
            raise MemoraJudgeRunnerError("judge denominator is incomplete")
        return tuple(sorted(results.values(), key=lambda item: int(item["ordinal"])))


def _generation_answers(
    value: dict[str, Any], *, case_ids: set[str]
) -> tuple[tuple[str, ...], dict[tuple[str, str], str]]:
    methods = value.get("methods")
    records = value.get("raw_records")
    if (
        value.get("schema") != "milai.dg11.paper-memora-generations.v1"
        or value.get("status") != "PASS"
        or not isinstance(methods, list)
        or not methods
        or len(set(methods)) != len(methods)
        or not all(isinstance(method, str) for method in methods)
        or not isinstance(records, list)
    ):
        raise MemoraJudgeRunnerError("Memora generation envelope drifted")
    result: dict[tuple[str, str], str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise MemoraJudgeRunnerError("Memora generation record is invalid")
        key = (str(record.get("case_id")), str(record.get("method_id")))
        answer = record.get("answer")
        if (
            key in result
            or key[0] not in case_ids
            or key[1] not in methods
            or not isinstance(answer, str)
            or not answer
        ):
            raise MemoraJudgeRunnerError("Memora generation denominator drifted")
        result[key] = answer
    expected = {(case_id, method) for case_id in case_ids for method in methods}
    if set(result) != expected:
        raise MemoraJudgeRunnerError("Memora generation pairs are incomplete")
    return tuple(methods), result


def _prepare_requests(
    *,
    run_id: str,
    cases: Sequence[Any],
    methods: tuple[str, ...],
    criteria: Sequence[MemoraCriterion],
    answers: Mapping[tuple[str, str], str],
    client: FrozenJudgeClient,
) -> tuple[PreparedJudge, ...]:
    criteria_by_case: dict[str, list[MemoraCriterion]] = {}
    for criterion in criteria:
        criteria_by_case.setdefault(criterion.case_id, []).append(criterion)
    prepared: list[PreparedJudge] = []
    ordinal = 0
    for case_ordinal, case in enumerate(cases):
        ordered_methods = counterbalanced_order(
            methods,
            case_ordinal=case_ordinal,
            namespace="milai-dg11-paper-v1:MEMORA:judge",
        )
        for method in ordered_methods:
            for criterion_ordinal, criterion in enumerate(
                criteria_by_case.get(str(case.case_id), [])
            ):
                logical_id = (
                    f"{run_id}-{case_ordinal + 1:04d}-{method.casefold()}-"
                    f"{criterion_ordinal + 1:04d}"
                )
                prepared.append(
                    client.prepare(
                        ordinal=ordinal,
                        logical_request_id=logical_id,
                        case_id=str(case.case_id),
                        method_id=method,
                        criterion_id=criterion.criterion_id,
                        evaluation_type=criterion.evaluation_type,
                        expected_answer=criterion.expected_answer,
                        model_response=answers[(str(case.case_id), method)],
                        evaluation_question=criterion.evaluation_question,
                    )
                )
                ordinal += 1
    if len(prepared) != len(methods) * len(criteria):
        raise MemoraJudgeRunnerError("prepared judge denominator drifted")
    return tuple(prepared)


def run(
    *,
    run_id: str,
    input_path: Path,
    generation_path: Path,
    data_root: Path,
    output_dir: Path,
    workers: int,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    _cohorts, cases = load_inputs(input_path)
    criteria = load_official_criteria(
        input_path=input_path,
        data_root=data_root,
        freeze_manifest=freeze_manifest,
        allow_unfrozen_smoke=allow_unfrozen_smoke,
    )
    methods, answers = _generation_answers(
        _object(generation_path), case_ids={case.case_id for case in cases}
    )
    client = FrozenJudgeClient()
    prepared = _prepare_requests(
        run_id=run_id,
        cases=cases,
        methods=methods,
        criteria=criteria,
        answers=answers,
        client=client,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = UsageLedger(output_dir / "judge-usage-ledger.jsonl")
    records = MemoraJudgeRunner(ledger, max_workers=workers).execute(
        prepared, client.complete
    )
    verification = ledger.verify()
    judgments: dict[str, Any] = {
        "case_count": len(cases),
        "criterion_count_per_method": len(criteria),
        "expected_judge_calls": len(methods) * len(criteria),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "judge_calls": len(records),
        "judge_identity": "Qwen3.5-27B-FP8-INDEPENDENT-EVALUATOR",
        "judge_prompt_contract_sha256": prompt_contract_sha256(),
        "ledger_root_sha256": verification.root_sha256,
        "methods": list(methods),
        "paper_labels_opened": True,
        "records": list(records),
        "run_id": run_id,
        "schema": "milai.dg11.paper-memora-judgments.v1",
        "status": "PASS" if len(records) == len(methods) * len(criteria) else "FAIL",
        "workers": workers,
    }
    metrics = {
        **aggregate_judgments(
            cases=cases,
            methods=methods,
            criteria=criteria,
            judgments=records,
        ),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "judge_identity": judgments["judge_identity"],
        "paper_labels_opened": True,
        "run_id": run_id,
        "status": judgments["status"],
    }
    return (
        _atomic_json_equal(output_dir / "judgments.json", judgments),
        _atomic_json_equal(output_dir / "metrics.json", metrics),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--generations", type=Path, default=DEFAULT_GENERATIONS)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--workers",
        type=int,
        choices=WORKER_CHOICES,
        default=JUDGE_PROVIDER_LANE.default_workers,
    )
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    judgments, metrics = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        generation_path=args.generations.resolve(),
        data_root=args.data_root.resolve(),
        output_dir=args.output_dir.resolve(),
        workers=args.workers,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
    )
    print(
        json.dumps(
            {
                "judge_calls": judgments["judge_calls"],
                "status": metrics["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
