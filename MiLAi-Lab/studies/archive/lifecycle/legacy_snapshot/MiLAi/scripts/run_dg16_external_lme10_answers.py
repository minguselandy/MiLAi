#!/usr/bin/env python3
"""Answer and score frozen Graphiti/OpenViking LME10 context archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg16.external_lme10 import (
    BUDGETS,
    METHODS,
    ExternalLME10Error,
    atomic_json,
    load_cases,
    sha256_file,
    summarize_scored,
)
from evals.dg16.lme10 import load_public_dev_labels
from evals.paper.provider import MODEL_ID
from evals.paper.scorers.longmemeval import score_answer, score_retrieval


def _archive(path: Path, method: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "milai.dg16.external-lme10-contexts.v1"
        or value.get("status") != "SUCCEEDED"
        or value.get("method_id") != method
        or value.get("record_count") != 10
        or value.get("labels_loaded") is not False
        or value.get("formal_holdout_consumed") is not False
    ):
        raise ExternalLME10Error(f"invalid context archive: {path}")
    return value


def _provider_record(value: Any) -> dict[str, Any]:
    raw = asdict(value)
    context = str(raw.pop("context"))
    raw["context_sha256"] = hashlib.sha256(context.encode()).hexdigest()
    return raw


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output_root.exists():
        raise ExternalLME10Error("output root exists; use a fresh run")
    args.output_root.mkdir(parents=True)
    cases, selection = load_cases()
    graphiti = _archive(args.graphiti_contexts, "GRAPHITI-OSS")
    openviking = _archive(args.openviking_contexts, "OPENVIKING-FIND")
    if graphiti.get("selection") != selection or openviking.get("selection") != selection:
        raise ExternalLME10Error("external context selections differ")
    raw_records = [*graphiti["records"], *openviking["records"]]
    by_key = {(item["case_id"], item["method_id"]): item for item in raw_records}
    expected = {(case.case_id, method) for case in cases for method in METHODS}
    if set(by_key) != expected:
        raise ExternalLME10Error("external context denominator drifted")
    provider = MatchedVllmProvider(args.reader_url)
    generations: list[dict[str, Any]] = []
    schedule: list[dict[str, Any]] = []
    fitted_contexts: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    for case_ordinal, case in enumerate(cases):
        for budget_ordinal, budget in enumerate(BUDGETS):
            order = list(METHODS)
            if (case_ordinal + budget_ordinal) % 2:
                order.reverse()
            for method in order:
                raw = by_key[(case.case_id, method)]
                answer = provider.answer(
                    run_id=args.run_id,
                    case_id=case.case_id,
                    method_id=method,
                    question=case.question,
                    question_as_of=case.question_at,
                    memory_context=str(raw["context"]),
                    token_budget=budget,
                )
                context_record = {
                    **{key: value for key, value in raw.items() if key != "context"},
                    "token_budget": budget,
                    "context": answer.context,
                    "context_sha256": hashlib.sha256(answer.context.encode()).hexdigest(),
                    "context_tokens": answer.memory_tokens,
                }
                fitted_contexts.append(context_record)
                generations.append(
                    {
                        **{key: value for key, value in context_record.items() if key != "context"},
                        "answer": answer.answer,
                        "provider": _provider_record(answer),
                    }
                )
                schedule.append(
                    {
                        "ordinal": len(schedule),
                        "case_id": case.case_id,
                        "token_budget": budget,
                        "method_id": method,
                        "seed": answer.seed,
                    }
                )
        print(
            json.dumps(
                {
                    "stage": "generation",
                    "case": case_ordinal + 1,
                    "case_count": len(cases),
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(generations) != 40:
        raise ExternalLME10Error("external generation denominator drifted")
    context_archive = {
        "schema": "milai.dg16.external-lme10-fitted-contexts.v1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "record_count": len(fitted_contexts),
        "records": fitted_contexts,
    }
    generation_archive = {
        "schema": "milai.dg16.external-lme10-generations.v1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "record_count": len(generations),
        "schedule": schedule,
        "records": generations,
    }
    contexts_path = args.output_root / "contexts.json"
    generations_path = args.output_root / "generations.json"
    atomic_json(contexts_path, context_archive)
    atomic_json(generations_path, generation_archive)
    labels, label_identity = load_public_dev_labels(tuple(case.case_id for case in cases))
    scored: list[dict[str, Any]] = []
    for record in generations:
        label = labels[str(record["case_id"])]
        scored.append(
            {
                **record,
                "answer_score": score_answer(
                    str(record["answer"]), [str(item) for item in label["answers"]]
                ),
                "retrieval_score": score_retrieval(
                    record["retrieval_trace"],
                    [str(item) for item in label["answer_session_ids"]],
                ),
            }
        )
    summaries = summarize_scored(scored)
    baseline = json.loads(args.baseline_receipt.read_text(encoding="utf-8"))
    baseline_summaries = baseline.get("summaries")
    if not isinstance(baseline_summaries, dict):
        raise ExternalLME10Error("comparison baseline receipt has no summaries")
    comparisons: dict[str, Any] = {}
    for method in METHODS:
        comparisons[method] = {}
        for budget in BUDGETS:
            cell = summaries[method][str(budget)]
            comparisons[method][str(budget)] = {
                reference: {
                    "normalized_f1_delta": round(
                        float(cell["normalized_f1"])
                        - float(baseline_summaries[reference][str(budget)]["normalized_f1"]),
                        9,
                    ),
                    "exact_match_delta": round(
                        float(cell["exact_match"])
                        - float(baseline_summaries[reference][str(budget)]["exact_match"]),
                        9,
                    ),
                    "query_latency_ratio": round(
                        float(cell["query_latency_ms"]["mean"])
                        / float(
                            baseline_summaries[reference][str(budget)]["query_latency_ms"]["mean"]
                        ),
                        6,
                    ),
                }
                for reference in ("DG16-MILAI-MCP", "LME-BM25-T")
            }
    receipt = {
        "schema": "milai.dg16.external-lme10-comparison.v1",
        "status": "CHARACTERIZED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "run_id": args.run_id,
        "configuration": {
            "case_count": 10,
            "methods": list(METHODS),
            "token_budgets": list(BUDGETS),
            "record_count": 40,
            "reader_model_id": MODEL_ID,
            "automatic_retries": 0,
        },
        "selection": selection,
        "execution_identity": {
            "hostname": platform.node(),
            "reader_url": args.reader_url,
            "provider_contract": full_provider_contract(),
            "provider_contract_sha256": full_provider_contract_sha256(),
            "graphiti_contexts": {
                "path": str(args.graphiti_contexts.resolve()),
                "sha256": sha256_file(args.graphiti_contexts),
            },
            "openviking_contexts": {
                "path": str(args.openviking_contexts.resolve()),
                "sha256": sha256_file(args.openviking_contexts),
            },
        },
        "product_plane": {
            "labels_loaded": False,
            "contexts_sha256": sha256_file(contexts_path),
            "generations_sha256": sha256_file(generations_path),
        },
        "scoring_plane": {
            "labels_loaded_after_generation_record_count": len(generations),
            "label_source": label_identity,
            "scorer": "DG11_PAPER_DETERMINISTIC_NORMALIZED_EM_F1_V1",
        },
        "summaries": summaries,
        "comparisons": comparisons,
        "lifecycle": {
            "GRAPHITI-OSS": graphiti.get("lifecycle"),
            "OPENVIKING-FIND": openviking.get("lifecycle"),
        },
        "provider_accounting": {
            "GRAPHITI-OSS": graphiti.get("provider_accounting"),
            "OPENVIKING-FIND": openviking.get("provider_accounting"),
        },
        "records": sorted(
            scored,
            key=lambda item: (
                int(item["token_budget"]),
                str(item["case_id"]),
                str(item["method_id"]),
            ),
        ),
        "experiment_wall_ms": round((time.perf_counter() - started_all) * 1000, 6),
    }
    receipt_path = args.output_root / "receipt.json"
    atomic_json(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--graphiti-contexts", type=Path, required=True)
    parser.add_argument("--openviking-contexts", type=Path, required=True)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument(
        "--baseline-receipt",
        type=Path,
        default=ROOT
        / "var/dg16/lme10/dg16-lme10-compare-20260827-002/receipt-rescored.json",
    )
    args = parser.parse_args()
    receipt = run(args)
    output = args.output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(output.resolve()),
                "receipt_sha256": sha256_file(output),
                "summaries": receipt["summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
