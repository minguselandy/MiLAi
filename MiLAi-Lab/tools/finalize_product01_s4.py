#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.longmemeval_gate import (  # noqa: E402
    ArmMetrics,
    admission_checks,
    canonical_sha256,
    paired_bootstrap_interval,
    percentile,
)
from milai_lab.product_adapter.manifest import (  # noqa: E402
    load_product_lock,
    verify_product_lock,
)
from run_product01_s1_context_preflight import (  # noqa: E402
    RuntimeHttpClient,
    _load_env,
    _sha256_file,
)
from run_product01_s4_longmemeval import (  # noqa: E402
    ARMS,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    EXPECTED_PRODUCT_COMMIT,
    EXPECTED_PRODUCT_LOCK_DIGEST,
    S4Error,
    _dataset_path,
    _load_population,
    _load_rows,
    _select,
    _selection_identity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Finalize sealed Product-01 S4 cells after a terminal-only protocol failure"
    )
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-lock", type=Path, default=ROOT / "product.lock.json")
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument("--b0-env-file", type=Path, required=True)
    parser.add_argument("--b1-env-file", type=Path, required=True)
    parser.add_argument("--b0-base-url", required=True)
    parser.add_argument("--b1-base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-count", type=int, choices=(128, 500), required=True)
    return parser


def _validate_seal(rows: list[dict[str, Any]], case_count: int) -> None:
    expected = case_count * len(ARMS) * 3
    if len(rows) != expected:
        raise S4Error(f"sealed row denominator is {len(rows)}, expected {expected}")
    keys = [(str(row.get("stage")), str(row.get("arm")), str(row.get("case_id"))) for row in rows]
    if len(set(keys)) != expected:
        raise S4Error("sealed rows contain duplicate stage/arm/case identities")
    stage_positions = {
        stage: [index for index, row in enumerate(rows) if row.get("stage") == stage]
        for stage in ("context", "answer", "judge")
    }
    if any(len(indexes) != case_count * len(ARMS) for indexes in stage_positions.values()):
        raise S4Error("sealed stage denominator drifted")
    if not (
        max(stage_positions["context"]) < min(stage_positions["answer"])
        and max(stage_positions["answer"]) < min(stage_positions["judge"])
    ):
        raise S4Error("answers-before-judges phase ordering was not sealed")


async def _runtime_health(args: argparse.Namespace) -> bool:
    clients: list[RuntimeHttpClient] = []
    try:
        for env_path, base_url in (
            (args.b0_env_file, args.b0_base_url),
            (args.b1_env_file, args.b1_base_url),
        ):
            env = _load_env(env_path)
            client = RuntimeHttpClient(base_url, env["MILAI_AGENT_READER_TOKEN"], max_connections=1)
            clients.append(client)
            capabilities = await client.request("GET", "/v1/capabilities")
            if capabilities.get("contract_version") != "agent.v1":
                return False
        return True
    finally:
        for client in clients:
            await client.close()


async def _run(args: argparse.Namespace) -> int:
    run_path = args.output / "run.json"
    cases_path = args.output / "cases.jsonl"
    if not run_path.is_file() or not cases_path.is_file():
        raise S4Error("run and sealed cases must exist before finalization")
    if (args.output / "metrics.json").exists() or (args.output / "terminal.json").exists():
        raise S4Error("finalizer refuses to overwrite an existing terminal")

    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise S4Error("Product pin failed: " + "; ".join(verification.errors))
    if lock.git_commit != EXPECTED_PRODUCT_COMMIT or lock.digest != EXPECTED_PRODUCT_LOCK_DIGEST:
        raise S4Error("Product identity is outside the sealed S4 contract")

    run_payload = json.loads(run_path.read_text(encoding="utf-8"))
    if (
        not isinstance(run_payload, dict)
        or run_payload.get("schema_version") != "milai-product01-s4-run-v1"
        or run_payload.get("case_count") != args.case_count
        or run_payload.get("product_commit") != lock.git_commit
        or run_payload.get("product_lock_digest") != lock.digest
    ):
        raise S4Error("run identity differs from the requested finalization")

    dataset_path, dataset_sha256 = _dataset_path(args.dataset_manifest)
    population = _load_population(dataset_path)
    selected = _select(population, args.case_count)
    if run_payload.get("dataset_sha256") != dataset_sha256 or run_payload.get(
        "selection_sha256"
    ) != _selection_identity(population, args.case_count):
        raise S4Error("dataset or selection identity differs from the sealed run")

    rows = _load_rows(cases_path)
    _validate_seal(rows, args.case_count)
    final_runtime_health = await _runtime_health(args)
    context_rows = [row for row in rows if row["stage"] == "context"]
    answer_rows = [row for row in rows if row["stage"] == "answer"]
    judge_rows = [row for row in rows if row["stage"] == "judge"]
    judge_by_key = {(str(row["arm"]), str(row["case_id"])): row for row in judge_rows}

    arm_metrics: dict[str, ArmMetrics] = {}
    arm_payloads: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        contexts = [row for row in context_rows if row["arm"] == arm]
        judgments = [row for row in judge_rows if row["arm"] == arm]
        succeeded = [row for row in contexts if row["status"] == "SUCCEEDED"]
        latencies = [float(row["resolve_latency_ms"]) for row in succeeded] or [float("inf")]
        metrics = ArmMetrics(
            case_count=args.case_count,
            system_context_success_rate=len(succeeded) / args.case_count,
            session_recall_at_5=sum(
                float(row["retrieval"]["session_recall_at_5"]) for row in succeeded
            )
            / args.case_count,
            session_ndcg_at_5=sum(float(row["retrieval"]["session_ndcg_at_5"]) for row in succeeded)
            / args.case_count,
            all_required_evidence_group_coverage=sum(
                int(row["coverage"]["all_required_evidence_group_coverage"]) for row in succeeded
            )
            / args.case_count,
            reader_visible_gold_session_coverage=sum(
                float(row["coverage"]["reader_visible_gold_session_coverage"])
                for row in succeeded
            )
            / args.case_count,
            qwen_judge_accuracy=sum(bool(row["correct"]) for row in judgments) / args.case_count,
            strict_wrong_complete=sum(int(row["strict_wrong_complete"]) for row in contexts),
            p50_latency_ms=percentile(latencies, 0.50),
            p95_latency_ms=percentile(latencies, 0.95),
            leak_count=sum(int(row["contamination_count"]) for row in contexts),
        )
        arm_metrics[arm] = metrics
        arm_payloads[arm] = {
            **asdict(metrics),
            "reader_visible_trace_exactness": sum(
                row.get("reader_visible_trace_exact") is True for row in contexts
            )
            / args.case_count,
            "canonical_mutation_count": sum(
                int(row.get("canonical_mutation_count", 0)) for row in contexts
            ),
            "context_failure_counts": dict(
                Counter(
                    str(row.get("failure_class"))
                    for row in contexts
                    if row["status"] != "SUCCEEDED"
                )
            ),
            "answer_success_count": sum(
                row["arm"] == arm and row["status"] == "SUCCEEDED" for row in answer_rows
            ),
            "judge_success_count": sum(row["status"] == "SUCCEEDED" for row in judgments),
        }

    b0_judges = [
        bool(judge_by_key[(ARMS[0], str(record["question_id"]))]["correct"]) for record in selected
    ]
    b1_judges = [
        bool(judge_by_key[(ARMS[1], str(record["question_id"]))]["correct"]) for record in selected
    ]
    ci_low, ci_high = paired_bootstrap_interval(
        b0_judges, b1_judges, samples=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED
    )
    deltas = {
        "evidence_group_coverage": (
            arm_metrics[ARMS[1]].all_required_evidence_group_coverage
            - arm_metrics[ARMS[0]].all_required_evidence_group_coverage
        ),
        "qwen_judge_accuracy": (
            arm_metrics[ARMS[1]].qwen_judge_accuracy - arm_metrics[ARMS[0]].qwen_judge_accuracy
        ),
        "p95_latency_ratio": (
            arm_metrics[ARMS[1]].p95_latency_ms / arm_metrics[ARMS[0]].p95_latency_ms
        ),
        "paired_judge_ci_95": [ci_low, ci_high],
        "paired_wins": sum(
            right and not left for left, right in zip(b0_judges, b1_judges, strict=True)
        ),
        "paired_losses": sum(
            left and not right for left, right in zip(b0_judges, b1_judges, strict=True)
        ),
    }
    formal = args.case_count == 500
    entry_checks = {
        "ProductManifestAndLabPin": True,
        "PriorS0IsolatedPostgresWorker": True,
        "PriorS1IdentityVisibility": True,
        "SystemContextSuccessRate": min(
            arm_metrics[arm].system_context_success_rate for arm in ARMS
        )
        >= (0.99 if formal else 0.98),
        "SystemicWorkerExit": final_runtime_health,
        "CrossSessionContamination": all(
            metrics.leak_count == 0 for metrics in arm_metrics.values()
        ),
        "ReaderVisibleTraceExactness": all(
            arm_payloads[arm]["reader_visible_trace_exactness"] == 1.0 for arm in ARMS
        ),
        "StrictWrongComplete": all(
            metrics.strict_wrong_complete == 0 for metrics in arm_metrics.values()
        ),
        "CandidateFeatureDefaultOff": True,
    }
    final_checks = (
        admission_checks(arm_metrics[ARMS[0]], arm_metrics[ARMS[1]], paired_ci_lower=ci_low)
        if formal
        else {}
    )
    passed = all(entry_checks.values()) and (not formal or all(final_checks.values()))
    metrics_payload = {
        "schema_version": "milai-product01-s4-metrics-v1",
        "run_id": run_payload["run_id"],
        "status": "PASS" if passed else "FAIL",
        "arms": arm_payloads,
        "deltas": deltas,
        "entry_checks": entry_checks,
        "candidate_admission_checks": final_checks,
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED},
        "same_qwen_self_judge": True,
        "leaderboard_equivalence_claimed": False,
        "semantic_retries": 0,
        "technical_retries_used": 0,
        "votes": 0,
        "terminal_only_protocol_recovery": {
            "cause": "ASYNC_GENERATOR_FINAL_HEALTH_AGGREGATION",
            "sealed_rows_reused": len(rows),
            "context_calls_repeated": 0,
            "answer_calls_repeated": 0,
            "judge_calls_repeated": 0,
            "finalizer_sha256": _sha256_file(Path(__file__)),
        },
    }
    artifacts = RunArtifacts(args.output)
    artifacts.write_json("metrics.json", metrics_payload)
    started_at = datetime.fromisoformat(str(run_payload["started_at"]))
    finished_at = datetime.now(UTC)
    terminal = {
        "schema_version": "milai-product01-s4-terminal-v1",
        "run_id": run_payload["run_id"],
        "status": (
            "PASS_S4_LONGMEMEVAL_CONFIRMED"
            if passed and formal
            else "PASS_S4_128_ENTRY_READY_FOR_FORMAL_500"
            if passed
            else "FAIL_S4_REPAIR_OR_KEEP_BASELINE"
        ),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
        "case_count": args.case_count,
        "formal_holdout_consumed": formal,
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "selection_sha256": run_payload["selection_sha256"],
        "run_sha256": canonical_sha256(run_payload),
        "cases_sha256": _sha256_file(cases_path),
        "metrics_sha256": canonical_sha256(metrics_payload),
        "candidate_default_enabled": False,
        "terminal_only_protocol_recovery": True,
        "selected_disposition": (
            "B1_SIMPLE_RECALL"
            if passed and formal
            else "PENDING_FORMAL_500"
            if passed
            else "KEEP_BASELINE_OR_REPAIR"
        ),
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"S4 finalization failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
