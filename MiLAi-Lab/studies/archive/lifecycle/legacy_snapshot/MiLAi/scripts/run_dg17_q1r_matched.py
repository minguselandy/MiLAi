#!/usr/bin/env python3
"""Run Q1R fresh paired Reader calls from a sealed same-snapshot Context archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg14.benchmark import _atomic_json
from evals.dg14.provider import (
    DG14ProviderError,
    MatchedVllmProvider,
    ProviderResult,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg17.q1r_causality import (
    GENERATION_ARCHIVE_SCHEMA,
    POLICIES,
    Q1RCausalityError,
    audit_generation_pairs,
    build_generation_schedule,
    planned_stability_diagnostics,
    validate_context_archive,
)
from evals.paper.provider import MODEL_ID, prompt_contract_sha256
from evals.paper.scorers.longmemeval import score_answer

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/q1r"
PREVIOUSLY_CORRECT_2048 = frozenset({"9a707b82", "a82c026e"})


class Q1RRunError(RuntimeError):
    """The Q1R sealed input, Provider execution, or denominator failed."""


def run(
    *,
    run_id: str,
    output_root: Path,
    context_archive: Path,
    context_archive_sha256: str,
    reader_url: str,
) -> dict[str, Any]:
    if output_root.exists():
        raise Q1RRunError("output exists; choose a fresh run ID")
    raw = context_archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != context_archive_sha256:
        raise Q1RRunError("Q1R Context archive identity drifted")
    archive = json.loads(raw)
    if not isinstance(archive, dict):
        raise Q1RRunError("Q1R Context archive is malformed")
    cases, selection = load_public_dev_cases()
    case_ids = [str(case.case_id) for case in cases]
    try:
        contexts = validate_context_archive(archive, case_ids=case_ids)
        schedule = build_generation_schedule(
            contexts,
            case_ids=case_ids,
            planned_window_id=run_id,
        )
    except Q1RCausalityError as exc:
        raise Q1RRunError("Q1R Context archive failed preflight") from exc

    output_root.mkdir(parents=True)
    started = time.perf_counter()
    execution_plan = {
        "schema": "milai.dg17.q1r-reader-execution-plan.v0.1",
        "status": "SEALED_BEFORE_PROVIDER",
        "classification": "LABEL_FREE_PROVIDER_EXECUTION_PLAN",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "historical_answer_reuse": False,
        "automatic_retries": 0,
        "context_archive": {
            "path": str(context_archive),
            "sha256": context_archive_sha256,
        },
        "planned_call_count": len(schedule),
        "schedule": schedule,
    }
    _atomic_json(output_root / "execution-plan.json", execution_plan)
    by_cell = {
        (str(row["case_id"]), int(row["token_budget"]), str(row["policy"])): row
        for row in contexts
    }
    case_by_id = {str(case.case_id): case for case in cases}
    provider = MatchedVllmProvider(reader_url)
    generations: list[dict[str, Any]] = []
    _write_progress(
        output_root,
        run_id=run_id,
        planned_call_count=len(schedule),
        generations=generations,
    )
    for scheduled in schedule:
        case_id = str(scheduled["case_id"])
        budget = int(scheduled["token_budget"])
        policy = str(scheduled["policy"])
        context = by_cell[(case_id, budget, policy)]
        case = case_by_id[case_id]
        try:
            answer = provider.answer(
                run_id=run_id,
                case_id=case_id,
                method_id=policy,
                question=case.question,
                question_as_of=case.question_at,
                memory_context=str(context["context"]),
                token_budget=budget,
            )
        except DG14ProviderError as exc:
            _write_progress(
                output_root,
                run_id=run_id,
                planned_call_count=len(schedule),
                generations=generations,
                failed_call=scheduled,
            )
            _atomic_json(
                output_root / "failure-receipt.json",
                {
                    "schema": "milai.dg17.q1r-provider-failure.v0.1",
                    "status": "FAILED_NOT_SCOREABLE",
                    "classification": "PRIMARY_PROVIDER_EXECUTION_FAILURE",
                    "run_id": run_id,
                    "formal_holdout_consumed": False,
                    "labels_loaded": False,
                    "historical_answer_reuse": False,
                    "automatic_retries": 0,
                    "planned_call_count": len(schedule),
                    "completed_call_count": len(generations),
                    "failed_call": dict(scheduled),
                    "failure": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "context_archive": {
                        "path": str(context_archive),
                        "sha256": context_archive_sha256,
                    },
                    "execution_plan_sha256": _sha256(
                        output_root / "execution-plan.json"
                    ),
                    "progress_sha256": _sha256(output_root / "progress.json"),
                    "elapsed_ms": round(
                        (time.perf_counter() - started) * 1_000, 6
                    ),
                },
            )
            raise Q1RRunError(
                "Q1R Provider call failed; see the sealed failure receipt"
            ) from exc
        generations.append(
            {
                **dict(context),
                "answer": answer.answer,
                "generation_source": "FRESH_PROVIDER_CALL",
                "automatic_retries": 0,
                "planned_window_id": run_id,
                "call_ordinal": int(scheduled["ordinal"]),
                "provider": _provider_record(answer),
            }
        )
        _write_progress(
            output_root,
            run_id=run_id,
            planned_call_count=len(schedule),
            generations=generations,
        )
    if len(generations) != 40:
        raise Q1RRunError("Q1R fresh Provider denominator drifted")
    questions = {
        str(case.case_id): (str(case.question), str(case.question_at)) for case in cases
    }
    try:
        pair_audits = audit_generation_pairs(generations, questions=questions)
    except Q1RCausalityError as exc:
        raise Q1RRunError("Q1R Provider pair audit failed") from exc
    generation_archive = {
        "schema": GENERATION_ARCHIVE_SCHEMA,
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "historical_answer_reuse": False,
        "planned_window_id": run_id,
        "record_count": len(generations),
        "schedule": schedule,
        "records": generations,
    }
    _atomic_json(output_root / "generations.json", generation_archive)
    _write_progress(
        output_root,
        run_id=run_id,
        planned_call_count=len(schedule),
        generations=generations,
        generation_archive_sha256=_sha256(output_root / "generations.json"),
    )

    # Scoring labels are opened only after the fresh main generations are sealed.
    scoring_labels, scoring_identity = load_public_dev_labels(tuple(case_ids))
    scored = []
    for row in generations:
        label = scoring_labels[str(row["case_id"])]
        scored.append(
            {
                **row,
                "answer_score": score_answer(str(row["answer"]), label["answers"]),
            }
        )
    diagnostics_plan = planned_stability_diagnostics(
        scored,
        pair_audits,
        previously_correct_2048=PREVIOUSLY_CORRECT_2048,
    )
    diagnostics = _run_diagnostics(
        provider=provider,
        run_id=run_id,
        plans=diagnostics_plan,
        generations=scored,
        case_by_id=case_by_id,
    )
    summaries = _summaries(scored)
    causally_valid_count = sum(
        audit["quality_attribution"] == "CAUSALLY_VALID" for audit in pair_audits
    )
    gate = {
        "status": "PASS" if causally_valid_count == len(pair_audits) else "FAIL",
        "checks": {
            "same_snapshot_pair_count": len(pair_audits) == 20,
            "fresh_provider_calls": len(generations) == 40,
            "historical_answer_reuse_zero": True,
            "automatic_retries_zero": True,
            "causally_valid_cells_100_percent": causally_valid_count
            == len(pair_audits),
            "unexplained_prompt_diff_zero": all(
                not audit["invariant_failures"] for audit in pair_audits
            ),
            "diagnostic_primary_replacement_zero": True,
        },
        "causally_valid_count": causally_valid_count,
        "pair_count": len(pair_audits),
    }
    receipt = {
        "schema": "milai.dg17.q1r-matched-causality.v0.1",
        "status": (
            "Q1R_CONTEXT_STABILITY_PASS"
            if gate["status"] == "PASS"
            else "Q1R_CONTEXT_STABILITY_FAIL"
        ),
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "configuration": {
            "case_count": 10,
            "token_budgets": [512, 2048],
            "policies": list(POLICIES),
            "reader_model_id": MODEL_ID,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "generation_contract": full_provider_contract(),
            "generation_contract_sha256": full_provider_contract_sha256(),
            "provider_main_calls": len(generations),
            "automatic_retries": 0,
            "diagnostic_repeats_per_triggered_frozen_prompt": 3,
        },
        "selection": selection,
        "context_archive": {
            "path": str(context_archive),
            "sha256": context_archive_sha256,
        },
        "generation_archive": {
            "path": str(output_root / "generations.json"),
            "sha256": _sha256(output_root / "generations.json"),
        },
        "scoring_label_source": scoring_identity,
        "summaries": summaries,
        "pair_audits": pair_audits,
        "stability_diagnostic_plan": diagnostics_plan,
        "stability_diagnostics": diagnostics,
        "gate": gate,
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _provider_record(value: ProviderResult) -> dict[str, Any]:
    raw = asdict(value)
    fitted_context = str(raw.pop("context"))
    raw["context_sha256"] = hashlib.sha256(fitted_context.encode()).hexdigest()
    raw["prompt_contract_sha256"] = prompt_contract_sha256()
    raw["generation_contract_sha256"] = full_provider_contract_sha256()
    return raw


def _write_progress(
    output_root: Path,
    *,
    run_id: str,
    planned_call_count: int,
    generations: list[dict[str, Any]],
    failed_call: dict[str, Any] | None = None,
    generation_archive_sha256: str | None = None,
) -> None:
    """Persist primary-call progress without making it a scoreable archive."""
    status = "IN_PROGRESS_NOT_SCOREABLE"
    if failed_call is not None:
        status = "FAILED_NOT_SCOREABLE"
    elif generation_archive_sha256 is not None:
        status = "SUCCEEDED_GENERATION_ARCHIVE_SEALED"
    _atomic_json(
        output_root / "progress.json",
        {
            "schema": "milai.dg17.q1r-provider-progress.v0.1",
            "status": status,
            "classification": "UNSCORED_PRIMARY_PROVIDER_PROGRESS",
            "run_id": run_id,
            "formal_holdout_consumed": False,
            "labels_loaded": False,
            "historical_answer_reuse": False,
            "automatic_retries": 0,
            "planned_call_count": planned_call_count,
            "completed_call_count": len(generations),
            "failed_call": failed_call,
            "generation_archive_sha256": generation_archive_sha256,
            "records": generations,
        },
    )


def _run_diagnostics(
    *,
    provider: MatchedVllmProvider,
    run_id: str,
    plans: list[dict[str, Any]],
    generations: list[dict[str, Any]],
    case_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    by_prompt = {
        (
            str(row["case_id"]),
            int(row["token_budget"]),
            str(row["provider"]["prompt_sha256"]),
        ): row
        for row in generations
    }
    results: list[dict[str, Any]] = []
    for plan in plans:
        key = (
            str(plan["case_id"]),
            int(plan["token_budget"]),
            str(plan["prompt_sha256"]),
        )
        primary = by_prompt[key]
        case = case_by_id[key[0]]
        repeats = []
        for repeat in range(1, 4):
            answer = provider.answer(
                run_id=f"{run_id}:stability:{key[0]}:{key[1]}:{repeat}",
                case_id=key[0],
                method_id=f"Q1R-STABILITY-{repeat}",
                question=case.question,
                question_as_of=case.question_at,
                memory_context=str(primary["context"]),
                token_budget=key[1],
            )
            provider_receipt = _provider_record(answer)
            if provider_receipt["prompt_sha256"] != key[2]:
                raise Q1RRunError("Q1R diagnostic prompt was not frozen")
            repeats.append({"repeat": repeat, "answer": answer.answer, "provider": provider_receipt})
        answer_counts: defaultdict[str, int] = defaultdict(int)
        for repeat_record in repeats:
            answer_counts[str(repeat_record["answer"])] += 1
        results.append(
            {
                **plan,
                "status": "DIAGNOSTIC_COMPLETE_NOT_PRIMARY",
                "repeat_count": len(repeats),
                "answers": repeats,
                "answer_agreement": round(max(answer_counts.values()) / 3, 9),
                "unique_answer_count": len(answer_counts),
                "primary_result_replaced": False,
            }
        )
    return results


def _summaries(records: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for policy in POLICIES:
        summaries[policy] = {}
        for budget in (512, 2048):
            cells = [
                row
                for row in records
                if row["policy"] == policy and row["token_budget"] == budget
            ]
            if len(cells) != 10:
                raise Q1RRunError("Q1R summary denominator drifted")
            summaries[policy][str(budget)] = {
                "case_count": 10,
                "exact_match_count": sum(
                    int(row["answer_score"]["exact_match"]) for row in cells
                ),
                "normalized_f1": round(
                    mean(float(row["answer_score"]["normalized_f1"]) for row in cells),
                    9,
                ),
                "query_latency_ms_mean": round(
                    mean(float(row["query_latency_ms"]) for row in cells), 6
                ),
                "provider_latency_ms_mean": round(
                    mean(float(row["provider"]["provider_latency_ms"]) for row in cells),
                    6,
                ),
                "answer_path_latency_ms_mean": round(
                    mean(
                        float(row["query_latency_ms"])
                        + float(row["provider"]["tokenize_latency_ms"])
                        + float(row["provider"]["provider_latency_ms"])
                        for row in cells
                    ),
                    6,
                ),
                "provider_calls": 10,
                "automatic_retries": 0,
            }
    return summaries


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--context-archive", type=Path, required=True)
    parser.add_argument("--context-archive-sha256", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        context_archive=args.context_archive,
        context_archive_sha256=args.context_archive_sha256,
        reader_url=args.reader_url,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path),
                "receipt_sha256": _sha256(receipt_path),
                "gate": receipt["gate"],
                "summaries": receipt["summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
