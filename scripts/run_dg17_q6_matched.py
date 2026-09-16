#!/usr/bin/env python3
"""Run DG-17 Q6 deterministic matched confirmation with a bound Q3C shadow."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

from evals.dg14.benchmark import (
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    _atomic_json,
    _local_token_counter,
)
from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg16.lme10 import BUDGETS, load_public_dev_cases, load_public_dev_labels
from evals.dg17.measurement import (
    DG16_RECEIPT_PATH,
    DG16_RECEIPT_SHA256,
    load_answer_bearing_labels,
)
from evals.dg17.q6_matched import (
    METHOD_ID,
    evaluate_development_gate,
    score_matched_records,
    summarize_matched_records,
)
from evals.paper.provider import MODEL_ID
from scripts.run_dg16_lme10_compare import _run_milai_case
from scripts.run_dg16_q6 import _process_identity, _provider_record, _reader_models

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/q6"
MATCHED_PROVIDER_RUN_ID = "dg16-lme10-compare-20260827-002"


class Q6RunError(RuntimeError):
    """The live Q6 denominator, bound shadow, or product execution failed."""


def run(
    *,
    run_id: str,
    output_root: Path,
    preflight: Path,
    preflight_sha256: str,
    q3c_shadow_report: Path,
    reader_url: str,
    tokenizer_path: Path,
    env_file: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise Q6RunError("output exists; choose a fresh run ID")
    bound_preflight = _load_bound(
        preflight,
        preflight_sha256,
        "Q6_PREFLIGHT_COMPLETE_EXTERNAL_EXECUTION_PAUSED",
    )
    if bound_preflight.get("execution_authorized") is not True:
        raise Q6RunError("bound Q6 preflight does not authorize external execution")
    if _sha256(DG16_RECEIPT_PATH) != DG16_RECEIPT_SHA256:
        raise Q6RunError("frozen DG16 baseline drifted")
    output_root.mkdir(parents=True)
    started = time.perf_counter()

    # Product execution opens only label-free public-development inputs.
    cases, selection = load_public_dev_cases()
    token_counter = _local_token_counter(tokenizer_path)
    contexts: list[dict[str, Any]] = []
    lifecycle_records: list[dict[str, Any]] = []
    case_receipts: list[dict[str, Any]] = []
    for ordinal, case in enumerate(cases, start=1):
        case_root = output_root / "cases" / case.case_id
        case_root.mkdir(parents=True)
        case_contexts, lifecycle, receipt = _run_milai_case(
            case=case,
            run_id=run_id,
            case_root=case_root,
            token_counter=token_counter,
            env_file=env_file,
            mcp_concurrency=mcp_concurrency,
            projection_batch_size=projection_batch_size,
            cleanup_timeout_seconds=90.0,
            cleanup_readiness_timeout_ms=60_000,
            allowed_statuses=frozenset({"HIT", "PARTIAL", "ABSTAINED"}),
            verify_wrong_scope=True,
        )
        for context in case_contexts:
            context["method_id"] = METHOD_ID
        contexts.extend(case_contexts)
        lifecycle["method_id"] = METHOD_ID
        lifecycle_records.append(lifecycle)
        case_receipts.append(receipt)
        print(
            json.dumps(
                {
                    "stage": "contexts",
                    "case": ordinal,
                    "case_count": 10,
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(contexts) != 20:
        raise Q6RunError("Q6 context denominator drifted")
    _atomic_json(
        output_root / "contexts.json",
        {
            "schema": "milai.dg17.q6-contexts.v0.1",
            "status": "SUCCEEDED",
            "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
            "formal_holdout_consumed": False,
            "label_fields_available": False,
            "record_count": 20,
            "records": contexts,
        },
    )

    # The deterministic arm is generated and sealed before any scoring label is opened.
    provider = MatchedVllmProvider(reader_url)
    by_cell = {
        (str(context["case_id"]), int(context["token_budget"])): context
        for context in contexts
    }
    generations: list[dict[str, Any]] = []
    for ordinal, case in enumerate(cases, start=1):
        for budget in BUDGETS:
            context = by_cell[(case.case_id, budget)]
            answer = provider.answer(
                run_id=MATCHED_PROVIDER_RUN_ID,
                case_id=case.case_id,
                method_id=METHOD_ID,
                question=case.question,
                question_as_of=case.question_at,
                memory_context=str(context["context"]),
                token_budget=budget,
            )
            generations.append(
                {
                    **dict(context),
                    "answer": answer.answer,
                    "provider": _provider_record(answer),
                }
            )
        print(
            json.dumps(
                {
                    "stage": "reader",
                    "case": ordinal,
                    "case_count": 10,
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(generations) != 20:
        raise Q6RunError("Q6 generation denominator drifted")
    _atomic_json(
        output_root / "generations.json",
        {
            "schema": "milai.dg17.q6-generations.v0.1",
            "status": "SUCCEEDED",
            "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
            "formal_holdout_consumed": False,
            "labels_loaded": False,
            "record_count": 20,
            "records": generations,
        },
    )

    # Evaluation-plane labels and the separately executed Q3C shadow enter only now.
    _envelope, labeled_cases, labels = load_answer_bearing_labels()
    if tuple(case.case_id for case in labeled_cases) != tuple(
        case.case_id for case in cases
    ):
        raise Q6RunError("Q6 label case order drifted")
    source_ids = tuple(case.case_id for case in cases)
    scoring_labels, scoring_identity = load_public_dev_labels(source_ids)
    plans = {}
    planner = QueryPlanner()
    for case in cases:
        reference_time = datetime.fromisoformat(
            normalize_lme_timestamp(case.question_at)
        )
        plans[case.case_id] = planner.plan(
            RetrievalRequest(
                route="L1",
                query=case.question,
                as_of=reference_time,
                system_as_of=reference_time,
            )
        )
    scored = score_matched_records(
        generations,
        cases=cases,
        labels=labels,
        scoring_labels=scoring_labels,
        plans=plans,
    )
    summaries = summarize_matched_records(scored)
    gate = evaluate_development_gate(summaries, scored)
    shadow = _load_shadow(q3c_shadow_report)
    semantic_cost_overlay = _shadow_cost_overlay(shadow, summaries)
    governance_safety = _aggregate_governance_safety(case_receipts, contexts)
    baseline = json.loads(DG16_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict):
        raise Q6RunError("frozen DG16 baseline is malformed")
    q3d = (
        "ELIGIBLE_NOT_EXECUTED"
        if shadow["q3d_gate"]["eligible"] is True
        else "PARKED_NOT_NEEDED"
    )
    receipt = {
        "schema": "milai.dg17.q6-matched-confirmation.v0.1",
        "status": "Q6_MATCHED_PASS" if gate["status"] == "PASS" else "CHARACTERIZED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "configuration": {
            "case_count": 10,
            "token_budgets": list(BUDGETS),
            "reader_model_id": MODEL_ID,
            "provider_seed_run_id": MATCHED_PROVIDER_RUN_ID,
            "same_provider_prompt_generation": True,
            "automatic_retries": 0,
            "mcp_concurrency": mcp_concurrency,
            "projection_batch_size": projection_batch_size,
            "dense_enabled": False,
            "reranker_enabled": False,
        },
        "selection": selection,
        "execution_identity": {
            "hostname": platform.node(),
            "reader_url": reader_url,
            "reader_models": _reader_models(reader_url),
            "reader_process": _process_identity(7860),
            "provider_contract": full_provider_contract(),
            "provider_contract_sha256": full_provider_contract_sha256(),
        },
        "product_plane": {
            "label_fields_available": False,
            "runtime_context_owner": "RUNTIME",
            "eval_context_selection_rules": 0,
            "record_count": 20,
            "reader_calls": 20,
            "semantic_assist_calls": 0,
            "semantic_repair_calls": 0,
            "canonical_claim_count": sum(
                int(receipt["adapter_stats"]["claim_count"])
                for receipt in case_receipts
            ),
        },
        "scoring_plane": {
            "labels_loaded_after_product_record_count": 20,
            "label_source": scoring_identity,
            "preflight_path": str(preflight),
            "preflight_sha256": preflight_sha256,
            "q3c_shadow_path": str(q3c_shadow_report),
            "q3c_shadow_sha256": _sha256(q3c_shadow_report),
        },
        "arms": {
            "DG16_CURRENT": baseline["summaries"]["DG16-MILAI-MCP"],
            "BM25_T": baseline["summaries"]["LME-BM25-T"],
            "DG17_DETERMINISTIC_ONLY": summaries,
            "DG17_ONE_CALL_SEMANTIC_REPAIR": {"status": q3d},
        },
        "counterfactual_cost_overlays": {
            "DG17_MINIMAL_SEMANTIC_QUERY_HINT_SHADOW_COST": semantic_cost_overlay,
        },
        "records": scored,
        "gate": gate,
        "governance_safety": governance_safety,
        "reader_exact_match_stability": {
            "strict_em_boundary_candidate_count_512": summaries["512"][
                "strict_em_boundary_candidate_count"
            ],
            "strict_em_boundary_candidate_count_2048": summaries["2048"][
                "strict_em_boundary_candidate_count"
            ],
            "diagnostic_policy": (
                "report candidates; do not rescore, retry, or trigger retrieval rework"
            ),
        },
        "lifecycle_records": lifecycle_records,
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "release_claim_authorized": False,
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _aggregate_governance_safety(
    case_receipts: list[dict[str, Any]], contexts: list[dict[str, Any]]
) -> dict[str, Any]:
    names = (
        "wrong_scope",
        "wrong_principal_write",
        "revoked_evidence",
        "canonical_promotion",
        "silent_fallback",
    )
    counters: dict[str, dict[str, Any]] = {
        name: {
            "denominator": sum(
                int(receipt["safety"][name]["denominator"]) for receipt in case_receipts
            ),
            "accepted": sum(
                int(receipt["safety"][name]["accepted"]) for receipt in case_receipts
            ),
        }
        for name in names
    }
    selected_refs = [
        (str(context.get("case_id", "")), str(source_ref))
        for context in contexts
        for source_ref in context.get("selected_source_refs", [])
        if isinstance(source_ref, str)
    ]
    counters["cross_case_contamination"] = {
        "denominator": len(selected_refs),
        "accepted": sum(
            not source_ref.startswith(f"{case_id}:")
            for case_id, source_ref in selected_refs
        ),
        "measurement": "SELECTED_SOURCE_REF_CASE_PREFIX",
    }
    counters["label_leakage"] = {
        "denominator": len(contexts),
        "accepted": sum(_contains_evaluation_label(context) for context in contexts),
        "measurement": "RECURSIVE_FORBIDDEN_EVALUATION_KEY_SCAN",
    }
    counters["denied_evidence"] = {
        "denominator": 0,
        "accepted": 0,
        "status": "PENDING_SUCCESSOR_LIVE_DENOMINATOR",
    }
    nonzero = [
        counter for counter in counters.values() if int(counter["denominator"]) > 0
    ]
    return {
        "status": (
            "PARTIAL_DENIED_EVIDENCE_LIVE_DENOMINATOR_PENDING"
            if all(int(counter["accepted"]) == 0 for counter in nonzero)
            else "FAIL"
        ),
        "zero_denominator_is_pass": False,
        "counters": counters,
    }


def _shadow_cost_overlay(
    shadow: dict[str, Any], summaries: dict[str, Any]
) -> dict[str, Any]:
    rows = [
        row
        for row in shadow["rows"]
        if str(row.get("case_id", "")).startswith("current10:")
    ]
    receipts = [row["minimal_hint"]["receipt"] for row in rows]
    successful = [receipt for receipt in receipts if isinstance(receipt, dict)]
    latencies = [float(receipt["timing"]["total_ms"]) for receipt in successful]
    prompt_tokens = [int(receipt["prompt_tokens"]) for receipt in successful]
    completion_tokens = [int(receipt["completion_tokens"]) for receipt in successful]
    wrong_promoted = sum(
        bool(row.get("minimal_hint", {}).get("wrong_promoted")) for row in rows
    )
    invalid_schema_or_span = sum(
        row.get("minimal_hint", {}).get("receipt") is None for row in rows
    )
    budgets: dict[str, Any] = {}
    for budget in ("512", "2048"):
        assist_ms = mean(latencies) if latencies else 0.0
        deterministic = summaries[budget]
        budgets[budget] = {
            "source_arm": "DG17_DETERMINISTIC_ONLY",
            "source_normalized_f1_reference": deterministic["normalized_f1"],
            "source_answer_path_latency_ms_mean": deterministic[
                "answer_path_latency_ms_mean"
            ],
            "semantic_hint_call_rate": round(len(successful) / len(rows), 9),
            "semantic_hint_prompt_tokens_mean": (
                round(mean(prompt_tokens), 3) if prompt_tokens else None
            ),
            "semantic_hint_completion_tokens_mean": (
                round(mean(completion_tokens), 3) if completion_tokens else None
            ),
            "semantic_hint_latency_ms_mean": round(assist_ms, 6),
            "counterfactual_quality_per_second_if_cost_added": round(
                float(deterministic["normalized_f1"])
            / (
                (float(deterministic["answer_path_latency_ms_mean"]) + assist_ms)
                / 1_000
            ),
            9,
            ),
        }
    return {
        "schema": "milai.dg17.semantic-hint-shadow-cost-overlay.v0.1",
        "status": "COUNTERFACTUAL_COST_OVERLAY_NOT_EXECUTED_ARM",
        "classification": "SHADOW_COST_ONLY / NO_QUALITY_EFFECT_MEASURED",
        "executed_product_arm": False,
        "quality_effect_measured": False,
        "coverage_delta_after_hint": None,
        "queries_changed_by_hint": None,
        "current10_denominator": len(rows),
        "wrong_promoted_hint_current10": wrong_promoted,
        "invalid_schema_or_span_current10": invalid_schema_or_span,
        "automatic_retries": 0,
        "product_route_changes": 0,
        "budgets": budgets,
    }


def _load_shadow(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    aggregate = value.get("aggregate", {}) if isinstance(value, dict) else {}
    wrong_promoted = aggregate.get("wrong_promoted_hint")
    q3d_gate = value.get("q3d_gate", {}) if isinstance(value, dict) else {}
    if (
        not isinstance(value, dict)
        or value.get("status") != "Q3C_SHADOW_CHARACTERIZED"
        or value.get("teacher_target_in_prompt") is not False
        or value.get("deterministic_requirement_ids_in_prompt") is not False
        or value.get("fixture_split") != "AUTHORED_DEV_NO_HELDOUT_CLAIM"
        or aggregate.get("case_count") != 29
        or not isinstance(wrong_promoted, int)
        or wrong_promoted < 0
        or (wrong_promoted > 0 and q3d_gate.get("eligible") is not False)
        or not isinstance(value.get("rows"), list)
        or len(value["rows"]) != 29
    ):
        raise Q6RunError("Q3C live shadow report is not a valid Q6 characterization")
    return value


_FORBIDDEN_EVALUATION_LABEL_KEYS = frozenset(
    {
        "answers",
        "answer_session_ids",
        "atoms",
        "gold_ir",
        "gold_operator",
        "required_slots",
        "join_relations",
        "expected_route",
        "expected_family",
        "scoring_labels",
    }
)


def _contains_evaluation_label(value: object) -> bool:
    if isinstance(value, dict):
        if _FORBIDDEN_EVALUATION_LABEL_KEYS.intersection(value):
            return True
        return any(_contains_evaluation_label(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_evaluation_label(item) for item in value)
    return False


def _load_bound(
    path: Path, expected_sha256: str, expected_status: str
) -> dict[str, Any]:
    if _sha256(path) != expected_sha256:
        raise Q6RunError(f"bound artifact drifted: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("status") != expected_status:
        raise Q6RunError(f"bound artifact status drifted: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--q3c-shadow-report", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=32)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        preflight=args.preflight,
        preflight_sha256=args.preflight_sha256,
        q3c_shadow_report=args.q3c_shadow_report,
        reader_url=args.reader_url,
        tokenizer_path=args.tokenizer,
        env_file=args.env_file,
        mcp_concurrency=args.mcp_concurrency,
        projection_batch_size=args.projection_batch_size,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": _sha256(receipt_path),
                "gate": receipt["gate"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
