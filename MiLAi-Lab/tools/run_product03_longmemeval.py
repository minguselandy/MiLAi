#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from argparse import Namespace
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import run_product02_longmemeval as product02  # noqa: E402
from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.longmemeval_gate import canonical_sha256  # noqa: E402
from milai_lab.product02_decision import sealed_strict_wrong_complete  # noqa: E402
from milai_lab.product_adapter.manifest import (  # noqa: E402
    load_product_lock,
    verify_product_lock,
)

A0 = "B0_B1_DEFAULT_FTS"
B1 = "B1_EXPLICIT_DEFAULT_ALIAS"
T1 = "T1_FTS_DENSE_UNION"
EXPECTED_LABEL_SHA256 = "6238c10cb7d6203715043a1437add55e3cd8114d20cec9e7ceded11c92831412"


class Product03LongRunError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Product-03 opened LongMemEval development gate"
    )
    parser.add_argument("--stage", choices=("P3_64", "P4_128"), required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-lock", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--label-manifest", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--a0-base-url", required=True)
    parser.add_argument("--t1-base-url", required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--micro-metrics", type=Path, required=True)
    parser.add_argument("--context24-metrics", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-concurrency", type=int, default=8)
    parser.add_argument("--answer-concurrency", type=int, default=8)
    parser.add_argument("--judge-concurrency", type=int, default=8)
    return parser


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Product03LongRunError(f"{name} is missing or invalid")
    return value


async def _resolve_arm(
    arm: str,
    record: Mapping[str, Any],
    *,
    reader: Any,
    identities: Mapping[str, Mapping[str, str]],
    sealed: Any,
    tokenizer: Any,
    evidence_token_budget: int,
) -> dict[str, Any]:
    case_id = str(record["question_id"])
    started = time.perf_counter()
    try:
        result = await reader.request(
            "POST",
            "/v1/memory/resolve",
            {
                "query": record["question"],
                "requested_scope": {
                    "project_ids": [product02._case_project(case_id)]
                },
                "required_authority": "INFORMATIONAL",
                "required_freshness": "CURRENT",
                "consistency_mode": "CANONICAL_REQUIRED",
                "reference_time": product02._observed_at(record["question_date"]),
                "budget": {
                    "max_results": 50,
                    "max_candidates": 120,
                    "max_context_tokens": evidence_token_budget,
                    "max_latency_ms": 2_000,
                },
            },
        )
        resolve_ms = (time.perf_counter() - started) * 1_000
        trace = product02._trace_context(
            result,
            record=record,
            identities=identities,
            tokenizer=tokenizer,
            evidence_token_budget=evidence_token_budget,
        )
        answer_evidence, label_trace = product02._visible_answer_metrics(result, sealed)
        memory_context = _mapping(result.get("memory_context"), "MemoryContext")
        compile_trace = _mapping(memory_context.get("compile_trace"), "compile trace")
        acquired = _mapping(
            compile_trace.get("acquired_candidate_trace"), "acquired candidate trace"
        )
        bound = _mapping(
            compile_trace.get("bound_evidence_trace"), "bound Evidence trace"
        )
        visible = _mapping(
            compile_trace.get("reader_visible_trace"), "Reader-visible trace"
        )
        search_trace = _mapping(result.get("search_trace"), "search trace")
        dispositions_raw = search_trace.get("acquisition_probe_dispositions")
        dispositions = (
            [item for item in dispositions_raw if isinstance(item, Mapping)]
            if isinstance(dispositions_raw, list)
            else []
        )
        channels = {str(item.get("channel")) for item in dispositions}
        executed_channels = {
            str(item.get("channel"))
            for item in dispositions
            if item.get("status") == "EXECUTED"
        }
        lean_recall_mode = compile_trace.get("lean_recall_mode")
        boundary = compile_trace.get("reader_evidence_boundary")
        boundary_exact = (
            boundary == "DECISION_ACCEPTED_ONLY"
            if lean_recall_mode == "STRICT"
            else boundary == "GOVERNANCE_ADMITTED_SOFT_RANKED"
        )
        treatment_exact = (
            not executed_channels.intersection({"EVIDENCE_DENSE", "ADJACENT_TURNS"})
            if arm == A0
            else "EVIDENCE_DENSE" in channels
            and "ADJACENT_TURNS" not in executed_channels
        )
        configuration_exact = (
            boundary_exact
            and treatment_exact
            and isinstance(acquired.get("trace_sha256"), str)
            and isinstance(bound.get("trace_sha256"), str)
            and isinstance(visible.get("reader_context_sha256"), str)
        )
        if not configuration_exact:
            raise Product03LongRunError(
                f"{arm} trace does not prove the frozen Product-03 treatment"
            )
        accepted_raw = result.get("accepted_binding_evidence_refs")
        if not isinstance(accepted_raw, list) or any(
            not isinstance(value, str) for value in accepted_raw
        ):
            raise Product03LongRunError("accepted Binding identity is invalid")
        accepted_source_refs = {
            identities[evidence_id]["source_ref"]
            for evidence_id in accepted_raw
            if evidence_id in identities
        }
        strict_wrong_complete, missing_required_roles = sealed_strict_wrong_complete(
            lean_recall_mode=(
                lean_recall_mode if isinstance(lean_recall_mode, str) else None
            ),
            sufficiency_status=(
                str(trace["sufficiency_status"])
                if trace.get("sufficiency_status") is not None
                else None
            ),
            accepted_source_turn_refs=tuple(accepted_source_refs),
            evidence=sealed,
        )
        return {
            "stage": "context",
            "arm": arm,
            "case_id": case_id,
            "status": "SUCCEEDED",
            "runtime_called": True,
            "resolve_latency_ms": round(resolve_ms, 6),
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
            "reader_evidence_boundary": boundary,
            "lean_recall_mode": lean_recall_mode,
            "configuration_trace_exact": configuration_exact,
            "acquired_candidate_trace_sha256": acquired["trace_sha256"],
            "bound_evidence_trace_sha256": bound["trace_sha256"],
            "answer_evidence": answer_evidence,
            "label_trace": label_trace,
            **trace,
            "accepted_source_turn_refs": sorted(accepted_source_refs),
            "missing_required_roles": list(missing_required_roles),
            "strict_wrong_complete": strict_wrong_complete,
        }
    except Exception as exc:
        return {
            "stage": "context",
            "arm": arm,
            "case_id": case_id,
            "status": "FAILED",
            "runtime_called": True,
            "failure_class": type(exc).__name__,
            "failure_message": str(exc)[:500],
            "resolve_latency_ms": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
            "reader_visible_trace_exact": False,
            "configuration_trace_exact": False,
            "strict_wrong_complete": 0,
            "contamination_count": 0,
            "canonical_mutation_count": 0,
        }


def _json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, str(path))


def _a2_metrics(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    comparison = _mapping(payload.get("comparison"), "mechanism comparison")
    return _mapping(comparison.get("A2_FTS_DENSE_UNION"), "A2 metrics")


def _evaluate(
    *,
    stage: str,
    source: Mapping[str, Any],
    micro: Mapping[str, Any],
    context24: Mapping[str, Any] | None,
) -> dict[str, Any]:
    arms = _mapping(source.get("arms"), "source arms")
    baseline = _mapping(arms.get(B1), "baseline arm")
    candidate = _mapping(arms.get(T1), "T1 arm")
    delta = _mapping(source.get("deltas_b2_minus_b1"), "paired deltas")
    micro_a2 = _a2_metrics(micro)
    selected_recovery = float(micro_a2["selected_family_role_recovery"])
    safety = {
        "StrictWrongComplete": int(baseline["strict_wrong_complete"]) == 0
        and int(candidate["strict_wrong_complete"]) == 0,
        "ScopeRevocationWrongRelationLeak": int(baseline["contamination_count"]) == 0
        and int(candidate["contamination_count"]) == 0,
        "CanonicalMutationFromRead": int(baseline["canonical_mutation_count"]) == 0
        and int(candidate["canonical_mutation_count"]) == 0,
        "SystemSuccess": float(baseline["system_context_success_rate"]) == 1.0
        and float(candidate["system_context_success_rate"]) == 1.0,
        "ReaderVisibleTraceExactness": float(
            baseline["reader_visible_trace_exactness"]
        )
        == 1.0
        and float(candidate["reader_visible_trace_exactness"]) == 1.0,
        "TreatmentConfigurationTraceExactness": float(
            baseline["configuration_trace_exactness"]
        )
        == 1.0
        and float(candidate["configuration_trace_exactness"]) == 1.0,
    }
    checks: dict[str, bool] = {
        "SelectedFamilyRoleRecovery": selected_recovery >= 0.25,
        **safety,
    }
    if stage == "P3_64":
        if context24 is None:
            raise Product03LongRunError("P3_64 requires context24 metrics")
        context_a2 = _a2_metrics(context24)
        checks.update(
            {
                "Context24NewObligations": int(
                    context_a2["new_required_role_group_count"]
                )
                >= 2,
                "Context24Regression": int(
                    context_a2["lost_required_role_group_count"]
                )
                <= 1,
                "JudgePairedWinsGreaterThanLosses": int(delta["paired_wins"])
                > int(delta["paired_losses"]),
                "GlobalExactTurnCoverageNonRegression": float(
                    delta["reader_visible_answer_turn_coverage"]
                )
                >= 0.0,
                "GlobalRequiredRoleCoverageNonRegression": float(
                    delta["required_role_coverage"]
                )
                >= 0.0,
                "P95LatencyRatio": float(delta["p95_latency_ratio"]) <= 1.20,
            }
        )
    else:
        ci = delta.get("paired_judge_ci_95")
        if not isinstance(ci, list) or len(ci) != 2:
            raise Product03LongRunError("paired judge CI is invalid")
        checks.update(
            {
                "GlobalExactTurnCoverageNonRegression": float(
                    delta["reader_visible_answer_turn_coverage"]
                )
                >= 0.0,
                "GlobalRequiredRoleCoverageNonRegression": float(
                    delta["required_role_coverage"]
                )
                >= 0.0,
                "QwenJudgePointEstimateNonRegression": float(
                    delta["qwen_judge_accuracy"]
                )
                >= 0.0,
                "PairedJudgeNonInferiorityCI": float(ci[0]) >= -0.03,
            }
        )
    return {
        "schema_version": "milai-product03-longmemeval-metrics-v1",
        "stage": stage,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "arms": {B1: baseline, T1: candidate},
        "deltas_t1_minus_b0_b1": dict(delta),
        "selected_family_role_recovery": selected_recovery,
        "checks": checks,
        "formal_holdout_consumed": False,
        "leaderboard_equivalence_claimed": False,
        "semantic_retries": 0,
        "votes": 0,
    }


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise Product03LongRunError("output already exists")
    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise Product03LongRunError(
            "Product pin failed: " + "; ".join(verification.errors)
        )
    label_sha256 = product02._sha256_file(args.label_manifest)
    if label_sha256 != EXPECTED_LABEL_SHA256:
        raise Product03LongRunError("label manifest identity drifted")
    case_count = 64 if args.stage == "P3_64" else 128
    source_output = args.output / "source_product02_compat"

    product02.B0 = A0
    product02.B1 = B1
    product02.B2 = T1
    product02.ARMS = (A0, B1, T1)
    product02.EXECUTED_ARMS = (A0, T1)
    product02.B1_ALIAS_SOURCE = A0
    product02.EXPECTED_PRODUCT_COMMIT = lock.git_commit
    product02.EXPECTED_PRODUCT_TREE = lock.tree_sha256
    product02.EXPECTED_PRODUCT_LOCK_DIGEST = lock.digest
    product02.EXPECTED_LABEL_MANIFEST_SHA256 = label_sha256
    product02._resolve_arm = _resolve_arm

    source_args = Namespace(
        product_root=args.product_root,
        product_lock=args.product_lock,
        dataset_manifest=args.dataset_manifest,
        label_manifest=args.label_manifest,
        env_file=args.env_file,
        b0_base_url=args.a0_base_url,
        b2_base_url=args.t1_base_url,
        tokenizer_root=args.tokenizer_root,
        vllm_base_url=args.vllm_base_url,
        output=source_output,
        case_count=case_count,
        capture_concurrency=args.capture_concurrency,
        answer_concurrency=args.answer_concurrency,
        judge_concurrency=args.judge_concurrency,
        entry_terminal=None,
        formal_holdout_authorization=None,
    )
    source_exit = await product02._run(source_args)
    source_metrics = _json(source_output / "metrics.json")
    micro = _json(args.micro_metrics)
    context24 = _json(args.context24_metrics) if args.context24_metrics else None
    metrics = _evaluate(
        stage=args.stage,
        source=source_metrics,
        micro=micro,
        context24=context24,
    )
    artifacts = RunArtifacts(args.output)
    source_run = _json(source_output / "run.json")
    run = {
        "schema_version": "milai-product03-longmemeval-run-v1",
        "run_id": f"product03-{args.stage.lower()}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "stage": args.stage,
        "case_count": case_count,
        "arms": [A0, B1, T1],
        "executed_arms": [A0, T1],
        "b1_alias": {"source": A0, "reason": "explicit default equals B0"},
        "t1": {
            "retrieval_evidence_dense_enabled": True,
            "retrieval_type_directed_acquisition_enabled": False,
            "retrieval_deterministic_recovery_enabled": False,
            "fusion": "existing independent quota plus deterministic RRF",
        },
        "product_commit": lock.git_commit,
        "product_tree_sha256": lock.tree_sha256,
        "product_lock_digest": lock.digest,
        "selection_sha256": source_run["selection_sha256"],
        "selection_kind": f"HASH_FIXED_OPENED_{case_count}_DEVELOPMENT",
        "model": source_run["model"],
        "tokenizer": source_run["tokenizer"],
        "generation": source_run["generation"],
        "concurrency": source_run["concurrency"],
        "formal_holdout_consumed": False,
        "source_compatibility_harness": "source_product02_compat",
        "source_metadata_superseded_by_this_run": True,
        "claim_ceiling": "opened development acceptance; not unseen validation",
    }
    artifacts.write_json("run.json", run)
    artifacts.write_json("metrics.json", metrics)
    terminal = {
        "schema_version": "milai-product03-longmemeval-terminal-v1",
        "run_id": run["run_id"],
        "status": (
            f"PASS_PRODUCT03_{args.stage}_DEVELOPMENT_GATE"
            if metrics["status"] == "PASS" and source_exit == 0
            else f"FAIL_PRODUCT03_{args.stage}_DEVELOPMENT_GATE"
        ),
        "case_count": case_count,
        "formal_holdout_consumed": False,
        "product_lock_digest": lock.digest,
        "selection_sha256": run["selection_sha256"],
        "run_sha256": canonical_sha256(run),
        "source_cases_sha256": product02._sha256_file(source_output / "cases.jsonl"),
        "metrics_sha256": canonical_sha256(metrics),
        "candidate_default_enabled": False,
        "public_api_authorized": False,
        "schema_change_authorized": False,
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if terminal["status"].startswith("PASS_") else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(
            f"Product-03 LongMemEval failed closed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
