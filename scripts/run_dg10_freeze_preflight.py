from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import lme_product_smoke as benchmark
from evals.serving import minimal_baseline
from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native
from scripts import run_dg10_minimal_serving as serving_runner
from scripts.run_dg10_lme_product_smoke import (
    CONFIRMATION_CONSUMPTION,
    DEFAULT_DATASET,
    FREEZE_ROOT,
    confirmation_code_identity,
)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise state.F0Error(f"required evidence is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise state.F0Error(f"required evidence is not an object: {path}")
    return value


def _result(run_id: str) -> tuple[Path, dict[str, Any]]:
    path = state.RUNS_ROOT / run_id / "result.json"
    value = _json(path)
    if value.get("run_id") != run_id or value.get("status") != "PASS":
        raise state.F0Error(f"blocking run did not pass: {run_id}")
    return path, value


def _wheel_product_files(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if ".dist-info/" not in name
        }


def _package_delta(
    measured_package_run_id: str,
    frozen_package_run_id: str,
) -> dict[str, Any]:
    measured_paths, _ = native._package_artifact_map(measured_package_run_id)
    frozen_paths, _ = native._package_artifact_map(frozen_package_run_id)
    changed: dict[str, list[str]] = {}
    content_manifests: dict[str, Any] = {}
    for artifact in (
        "client_wheel",
        "mcp_wheel",
        "openworker_wheel",
        "runtime_wheel",
    ):
        before = _wheel_product_files(measured_paths[artifact])
        after = _wheel_product_files(frozen_paths[artifact])
        changed[artifact] = sorted(
            name
            for name in set(before).union(after)
            if before.get(name) != after.get(name)
        )
        content_manifests[artifact] = {
            "measured_wheel_sha256": state._sha256(measured_paths[artifact]),
            "frozen_wheel_sha256": state._sha256(frozen_paths[artifact]),
            "measured_product_files": before,
            "frozen_product_files": after,
        }
    expected = {
        "client_wheel": [],
        "mcp_wheel": [],
        "openworker_wheel": ["milai_openworker_mcp/adapter.py"],
        "runtime_wheel": ["milai/adapters/provider_execution.py"],
    }
    if changed != expected:
        raise state.F0Error("frozen package differs from measured package outside declared fix")
    return {
        "measured_package_run_id": measured_package_run_id,
        "frozen_package_run_id": frozen_package_run_id,
        "changed_product_files": changed,
        "content_manifests": content_manifests,
        "classification": "CLOSED_TEST_AUTHORIZATION_PLUS_HOST_OWNED_ROUTE_FIX",
        "impact": {
            "runtime_wheel": "closed-test confirmation authorization only",
            "openworker_wheel": (
                "remove user-text marker routing and preserve the original recall query; "
                "covered by successor F1/T2/hardened/Serving runs"
            ),
            "longmemeval_retrieval_or_context_bytes_changed": False,
        },
    }


def run_preflight(
    run_id: str,
    *,
    package_run_id: str,
    measured_package_run_id: str,
    f0_native_run_id: str,
    f1_run_id: str,
    t2_run_id: str,
    hardened_run_id: str,
    lme_dev_run_id: str,
    serving_run_id: str,
    serving_baseline_run_id: str,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    freeze_path = FREEZE_ROOT / "freeze-manifest-003.json"
    if freeze_path.exists() or CONFIRMATION_CONSUMPTION.exists():
        raise state.F0Error("DG-10 successor freeze or confirmation consumption exists")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, mode=0o700)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc

    evidence_paths: dict[str, Path] = {}
    package_result_path, _package_result = _result(package_run_id)
    evidence_paths[package_run_id] = package_result_path
    required = {
        f0_native_run_id: ("package_run_id", package_run_id),
        f1_run_id: ("package_run_id", package_run_id),
        t2_run_id: ("package_run_id", package_run_id),
        hardened_run_id: ("package_run_id", package_run_id),
    }
    for evidence_run_id, (field, expected) in required.items():
        path, value = _result(evidence_run_id)
        if value.get(field) != expected:
            raise state.F0Error(f"blocking run package drifted: {evidence_run_id}")
        evidence_paths[evidence_run_id] = path
    hardened = _json(evidence_paths[hardened_run_id])
    if hardened.get("f1_run_id") != f1_run_id:
        raise state.F0Error("hardened run F1 binding drifted")

    lme_dir = state.RUNS_ROOT / lme_dev_run_id
    lme_result_path, lme_result = _result(lme_dev_run_id)
    lme_report = _json(lme_dir / "report.json")
    lme_manifest = _json(lme_dir / "benchmark-manifest.json")
    if (
        lme_manifest.get("package_run_id") != measured_package_run_id
        or lme_report.get("quality_gate_status") != "PASS"
        or lme_result.get("provider_requests") != 150
        or (lme_result.get("provider_ledger") or {}).get("status") != "VALID"
    ):
        raise state.F0Error("LongMemEval DEV evidence is incomplete")
    evidence_paths[lme_dev_run_id] = lme_result_path
    evidence_paths[f"{lme_dev_run_id}:report"] = lme_dir / "report.json"

    serving_dir = state.RUNS_ROOT / serving_run_id
    serving_manifest = _json(serving_dir / "serving-manifest.json")
    serving_result = _json(serving_dir / "result.json")
    serving_report = _json(serving_dir / "report.json")
    aggregates = serving_result.get("aggregates") or {}
    baseline = serving_runner._baseline_report(
        serving_baseline_run_id,
        dataset_digest=str(serving_manifest["dataset_contract_sha256"]),
        prompt_digest=str(serving_manifest["prompt_contract_sha256"]),
    )
    comparison = serving_runner._comparison(
        serving_baseline_run_id,
        baseline,
        serving_report,
    )
    if (
        serving_manifest.get("package_run_id") != package_run_id
        or serving_result.get("status") != "PASS"
        or serving_result.get("provider_requests") != 124
        or comparison.get("decision") != "KEEP_EFFICIENCY"
        or comparison.get("terminal_failures") != 0
        or (serving_result.get("memory_control_target") or {}).get("status")
        != "PASS"
        or any(
            (aggregates.get(tier) or {}).get("failure_count") != 0
            or (aggregates.get(tier) or {}).get("request_count")
            != minimal_baseline.REPETITIONS
            for tier in minimal_baseline.TIERS
        )
    ):
        raise state.F0Error("minimal Serving evidence is incomplete")
    evidence_paths[f"{serving_run_id}:result"] = serving_dir / "result.json"
    evidence_paths[f"{serving_run_id}:report"] = serving_dir / "report.json"

    package_delta = _package_delta(measured_package_run_id, package_run_id)
    package_paths, package_artifacts = native._package_artifact_map(package_run_id)
    frozen_package_artifacts = {
        name: package_artifacts[name] for name in sorted(package_paths)
    }
    for name, artifact in frozen_package_artifacts.items():
        if state._sha256(package_paths[name]) != artifact["sha256"]:
            raise state.F0Error("frozen package artifact digest drifted")

    dataset_digest = state._sha256(DEFAULT_DATASET)
    manifest = {
        "schema": "milai.dg10.freeze-manifest.v1",
        "status": "FROZEN",
        "run_id": run_id,
        "frozen_at": state._now(),
        "package_run_id": package_run_id,
        "package_artifacts": frozen_package_artifacts,
        "package_delta_from_measured_product": package_delta,
        "model_id": benchmark.MODEL_ID,
        "prompt_contract_sha256": benchmark.prompt_contract_sha256(),
        "dataset_path": str(DEFAULT_DATASET),
        "dataset_sha256": dataset_digest,
        "dev_source_ids_sha256": hashlib.sha256(
            benchmark._canonical(benchmark.DEV_SOURCE_IDS)
        ).hexdigest(),
        "confirmation_source_ids_sha256": benchmark.CONFIRMATION_SOURCE_IDS_SHA256,
        "confirmation_case_ids_sha256": benchmark.CONFIRMATION_CASE_IDS_SHA256,
        "confirmation_case_count": len(benchmark.CONFIRMATION_SOURCE_IDS),
        "confirmation_code_identity": confirmation_code_identity(),
        "confirmation_consumption_path": CONFIRMATION_CONSUMPTION.relative_to(
            ROOT
        ).as_posix(),
        "thresholds": {
            "overall_f1_delta_min": 0,
            "overall_em_delta_min": 0,
            "knowledge_update_f1_delta_min": 0,
            "temporal_reasoning_f1_delta_min": 0,
            "memory_tokens_max": benchmark.MEMORY_TOKEN_BUDGET,
            "prompt_ratio_max": 2,
            "warm_memory_control_p95_ms_max": 250,
            "terminal_success_rate": 1.0,
        },
        "blocking_run_ids": {
            "f0_package": package_run_id,
            "f0_native": f0_native_run_id,
            "f1": f1_run_id,
            "t2": t2_run_id,
            "hardened": hardened_run_id,
            "lme_dev": lme_dev_run_id,
            "serving": serving_run_id,
            "serving_baseline": serving_baseline_run_id,
        },
        "serving_comparison": comparison,
        "evidence_sha256": {
            name: state._sha256(path) for name, path in sorted(evidence_paths.items())
        },
        "release_profile": "MILAI_PREFETCH_AGENT_READY",
        "dynamic_tool_profile": "NOT_CLAIMED",
        "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
        "runtime_status": "0.1.x CANDIDATE",
        "development_ai_audits": 0,
    }
    FREEZE_ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(FREEZE_ROOT, 0o700)
    state._atomic_write(freeze_path, manifest)
    result = {
        "schema": "milai.dg10.freeze-preflight-result.v1",
        "run_id": run_id,
        "status": "PASS",
        "cases": {
            "RM04": "PASS",
            "RM06": "PASS",
            "RM08": "PASS",
            "RM12": "PASS",
            "T0": "PASS",
            "T1": "PASS",
            "T2": "PASS",
            "T3a": "PASS",
        },
        "package_run_id": package_run_id,
        "freeze_manifest": str(freeze_path),
        "freeze_manifest_sha256": state._sha256(freeze_path),
        "provider_requests": 0,
        "development_ai_audits": 0,
        "error": None,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-14",
        "rm_ids": ["RM-04", "RM-06", "RM-08", "RM-12", "RM-14"],
        "rm_statuses": {
            "RM-04": "PASS",
            "RM-06": "PASS",
            "RM-08": "PASS",
            "RM-12": "PASS",
            "RM-14": "IN_PROGRESS",
        },
        "hypothesis": "all blocking development evidence is complete before held-out access",
        "code_identity": manifest["confirmation_code_identity"],
        "model_identity": benchmark.MODEL_ID,
        "dataset_identity": dataset_digest,
        "prompt_identity": manifest["prompt_contract_sha256"],
        "budget": {"native_requests": 0},
        "expected_delta": "freeze without product, prompt, data, threshold, or evidence drift",
        "functional_gate": "FREEZE_PREFLIGHT",
        "functional_cases_passed": list(result["cases"]),
        "functional_cases_failed": [],
        "actual_quality_delta": lme_result["deltas_vs_strongest_baseline"][
            "normalized_f1"
        ],
        "actual_token_delta": lme_result["deltas_vs_strongest_baseline"][
            "prompt_tokens_mean"
        ],
        "actual_latency_delta": comparison["t3a_warm_e2e_mean_delta_ms"],
        "prepare_context_calls": minimal_baseline.REPETITIONS,
        "full_recall_calls": len(benchmark.DEV_SOURCE_IDS),
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": 1.0,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 0,
        "decision": "FREEZE",
        "next_action": "consume the one-time held-out confirmation capability",
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze DG-10 before held-out confirmation")
    parser.add_argument(
        "--run-id",
        default=(
            "freeze-preflight-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--measured-package-run-id", required=True)
    parser.add_argument("--f0-native-run-id", required=True)
    parser.add_argument("--f1-run-id", required=True)
    parser.add_argument("--t2-run-id", required=True)
    parser.add_argument("--hardened-run-id", required=True)
    parser.add_argument("--lme-dev-run-id", required=True)
    parser.add_argument("--serving-run-id", required=True)
    parser.add_argument("--serving-baseline-run-id", required=True)
    args = parser.parse_args()
    result = run_preflight(
        args.run_id,
        package_run_id=args.package_run_id,
        measured_package_run_id=args.measured_package_run_id,
        f0_native_run_id=args.f0_native_run_id,
        f1_run_id=args.f1_run_id,
        t2_run_id=args.t2_run_id,
        hardened_run_id=args.hardened_run_id,
        lme_dev_run_id=args.lme_dev_run_id,
        serving_run_id=args.serving_run_id,
        serving_baseline_run_id=args.serving_baseline_run_id,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
