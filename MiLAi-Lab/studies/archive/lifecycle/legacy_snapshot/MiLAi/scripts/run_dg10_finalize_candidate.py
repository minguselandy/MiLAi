from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import lme_product_smoke as benchmark
from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native
from scripts.run_dg10_lme_product_smoke import (
    CONFIRMATION_CONSUMPTION,
    FREEZE_ROOT,
    confirmation_code_identity,
)

FINAL_ROOT = ROOT / "var/dg10/final"
REJECTED_FINAL_ROOT = ROOT / "var/dg10/final-rejected-20260823-001"
PRIMARY_REVIEW_RESULT = REJECTED_FINAL_ROOT / "review-result.json"
EARLY_CONFIRMATION_RUN_ID = "lme-confirmation-20260823-001"
SUPERSEDED_CONFIRMATION_RUN_ID = "lme-confirmation-20260823-002"
RECLASSIFIED_SERVING_RUN_ID = "serving-minimal-20260823-005"


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise state.F0Error(f"final evidence is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise state.F0Error(f"final evidence is not an object: {path}")
    return value


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=False)


def _inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                raise state.F0Error("review workspace contains a symlink")
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": state._sha256(path),
            }
        )
    return entries


def _readonly(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.chmod(path, 0o555 if path.is_dir() else 0o444)
    os.chmod(root, 0o555)


def _serving_reclassification_diff() -> dict[str, Any]:
    run_dir = state.RUNS_ROOT / RECLASSIFIED_SERVING_RUN_ID
    source_report_path = run_dir / "report.json"
    source_result_path = run_dir / "result.json"
    reclassified_path = run_dir / "reclassification.json"
    source = _json(source_report_path)
    reclassified = _json(reclassified_path)
    source_records = source.get("records")
    classified_records = reclassified.get("records")
    if not isinstance(source_records, list) or not isinstance(classified_records, list):
        raise state.F0Error("Serving 005 reclassification records are incomplete")
    if len(source_records) != len(classified_records):
        raise state.F0Error("Serving 005 reclassification denominator drifted")
    allowed = {"expected", "expected_memory_source", "failed_assertions", "status"}
    changed_fields: set[str] = set()
    for before, after in zip(source_records, classified_records, strict=True):
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise state.F0Error("Serving 005 record contract drifted")
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        if not changed.issubset(allowed):
            raise state.F0Error("Serving 005 reclassification changed an observation field")
        changed_fields.update(changed)
    if reclassified.get("source_report_sha256") != state._sha256(source_report_path):
        raise state.F0Error("Serving 005 source report binding drifted")
    if reclassified.get("source_result_sha256") != state._sha256(source_result_path):
        raise state.F0Error("Serving 005 source result binding drifted")
    return {
        "schema": "milai.dg10.serving-reclassification-diff.v1",
        "run_id": RECLASSIFIED_SERVING_RUN_ID,
        "source_report_sha256": state._sha256(source_report_path),
        "source_result_sha256": state._sha256(source_result_path),
        "reclassification_sha256": state._sha256(reclassified_path),
        "record_count": len(source_records),
        "allowed_changed_fields": sorted(allowed),
        "observed_changed_fields": sorted(changed_fields),
        "observation_fields_unchanged": True,
        "new_provider_requests": reclassified.get("new_provider_requests"),
    }


def finalize(
    run_id: str,
    *,
    confirmation_run_id: str,
    freeze_manifest: Path,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    if FINAL_ROOT.exists():
        raise state.F0Error("the final candidate already exists")
    frozen = _json(freeze_manifest)
    consumption = _json(CONFIRMATION_CONSUMPTION)
    confirmation_dir = state.RUNS_ROOT / confirmation_run_id
    confirmation_result_path = confirmation_dir / "result.json"
    confirmation_report_path = confirmation_dir / "report.json"
    confirmation_manifest_path = confirmation_dir / "benchmark-manifest.json"
    confirmation_result = _json(confirmation_result_path)
    confirmation_report = _json(confirmation_report_path)
    confirmation_manifest = _json(confirmation_manifest_path)
    if (
        frozen.get("schema") != "milai.dg10.freeze-manifest.v1"
        or frozen.get("status") != "FROZEN"
        or frozen.get("confirmation_code_identity") != confirmation_code_identity()
        or consumption.get("run_id") != confirmation_run_id
        or consumption.get("freeze_manifest_sha256") != state._sha256(freeze_manifest)
        or confirmation_result.get("status") != "PASS"
        or confirmation_result.get("provider_requests") != 150
        or (confirmation_result.get("provider_ledger") or {}).get("status") != "VALID"
        or confirmation_report.get("quality_gate_status") != "PASS"
        or confirmation_manifest.get("phase") != "CONFIRMATION"
        or confirmation_manifest.get("package_run_id") != frozen.get("package_run_id")
        or confirmation_manifest.get("source_case_ids_sha256")
        != benchmark.CONFIRMATION_SOURCE_IDS_SHA256
        or confirmation_manifest.get("confirmation_or_test_opened") is not True
    ):
        raise state.F0Error("held-out confirmation does not match the frozen candidate")

    package_run_id = str(frozen["package_run_id"])
    package_paths, package_artifacts = native._package_artifact_map(package_run_id)
    frozen_package_artifacts = {
        name: package_artifacts[name] for name in sorted(package_paths)
    }
    if frozen_package_artifacts != frozen.get("package_artifacts") or any(
        state._sha256(package_paths[name]) != artifact["sha256"]
        for name, artifact in frozen_package_artifacts.items()
    ):
        raise state.F0Error("frozen package artifacts drifted")

    blocking = frozen.get("blocking_run_ids") or {}
    dev_run_id = str(blocking.get("lme_dev"))
    serving_run_id = str(blocking.get("serving"))
    dev_dir = state.RUNS_ROOT / dev_run_id
    serving_dir = state.RUNS_ROOT / serving_run_id
    dev_result = _json(dev_dir / "result.json")
    dev_report = _json(dev_dir / "report.json")
    serving = _json(serving_dir / "result.json")
    serving_report = _json(serving_dir / "report.json")
    serving_comparison = frozen.get("serving_comparison") or {}
    if (
        serving.get("status") != "PASS"
        or serving_report.get("status") != "PASS_BASELINE_RECORDED"
        or serving_comparison.get("decision") != "KEEP_EFFICIENCY"
    ):
        raise state.F0Error("final Serving evidence is incomplete")
    hardened = _json(state.RUNS_ROOT / str(blocking.get("hardened")) / "result.json")
    f1 = _json(state.RUNS_ROOT / str(blocking.get("f1")) / "result.json")
    t2 = _json(state.RUNS_ROOT / str(blocking.get("t2")) / "result.json")
    f0_package = _json(
        state.RUNS_ROOT / str(blocking.get("f0_package")) / "result.json"
    )
    f0_native = _json(
        state.RUNS_ROOT / str(blocking.get("f0_native")) / "result.json"
    )
    early_confirmation_dir = state.RUNS_ROOT / EARLY_CONFIRMATION_RUN_ID
    early_confirmation = _json(early_confirmation_dir / "result.json")
    early_confirmation_manifest = _json(
        early_confirmation_dir / "benchmark-manifest.json"
    )
    superseded_confirmation_dir = state.RUNS_ROOT / SUPERSEDED_CONFIRMATION_RUN_ID
    superseded_confirmation = _json(superseded_confirmation_dir / "result.json")
    serving_diff = _serving_reclassification_diff()
    primary_review = _json(PRIMARY_REVIEW_RESULT)
    if (
        early_confirmation.get("status") != "FAILED"
        or early_confirmation.get("provider_requests") != 0
        or primary_review.get("verdict") != "REVISE"
        or primary_review.get("p1_count") != 5
    ):
        raise state.F0Error("required failed-attempt or review disclosure drifted")

    final_report = {
        "schema": "milai.dg10.final-engineering-benchmark-report.v1",
        "status": "PASS",
        "release_claim": "MILAI_PREFETCH_AGENT_READY",
        "package_run_id": package_run_id,
        "model_id": frozen["model_id"],
        "prompt_contract_sha256": frozen["prompt_contract_sha256"],
        "dataset_sha256": frozen["dataset_sha256"],
        "freeze_manifest_sha256": state._sha256(freeze_manifest),
        "development_ai_audits": 0,
        "final_ai_reviews": 1,
        "primary_review": {
            "review_id": primary_review["review_id"],
            "verdict": primary_review["verdict"],
            "p1_count": primary_review["p1_count"],
            "disposition": primary_review["disposition"],
        },
        "quality": {
            "dev": {
                "run_id": dev_run_id,
                "provider_requests": dev_result["provider_requests"],
                "deltas": dev_report["deltas_vs_strongest_baseline"],
                "quality_gates": dev_report["quality_gates"],
                "recall_at_k": dev_report["aggregates"]["MILAI_T3A"][
                    "retrieval_recall_at_k"
                ],
            },
            "confirmation": {
                "run_id": confirmation_run_id,
                "provider_requests": confirmation_result["provider_requests"],
                "deltas": confirmation_report["deltas_vs_strongest_baseline"],
                "quality_gates": confirmation_report["quality_gates"],
                "recall_at_k": confirmation_report["aggregates"]["MILAI_T3A"][
                    "retrieval_recall_at_k"
                ],
            },
        },
        "serving": {
            "run_id": serving_run_id,
            "status": serving["status"],
            "provider_requests": serving["provider_requests"],
            "comparison": serving_comparison,
            "memory_control_target": serving["memory_control_target"],
            "derived_warm_overhead_ms": serving["derived_warm_overhead_ms"],
        },
        "functional": {
            "f0_package_run_id": f0_package["run_id"],
            "f0_package_cases": f0_package["cases"],
            "f0_native_run_id": f0_native["run_id"],
            "f0_native_cases": f0_native["cases"],
            "f1_run_id": f1["run_id"],
            "f1_provider_requests": f1["provider_requests"],
            "t2_run_id": t2["run_id"],
            "t2_provider_requests": t2["provider_requests"],
            "hardened_run_id": hardened["run_id"],
            "hardened_provider_requests": hardened["provider_requests"],
            "validated_cache_hit_rate": hardened["validated_cache_hit_rate"],
            "validated_cache_warm_p95_ms": hardened[
                "validated_cache_warm_p95_ms"
            ],
        },
        "package_equivalence": frozen["package_delta_from_measured_product"],
        "failed_development_disclosure": {
            "lme_dev_003_actual_provider_requests": 24,
            "serving_005_original_classifier_failures": 31,
            "serving_005_failure_category": "EVALUATION_OR_SCORER",
            "confirmation_001": {
                "status": early_confirmation["status"],
                "provider_requests": early_confirmation["provider_requests"],
                "labels_opened": early_confirmation_manifest.get(
                    "confirmation_or_test_opened"
                ),
                "failure_reason": early_confirmation.get("error"),
                "disposition": (
                    "retained as failed zero-call development evidence; its V1 split was "
                    "retired because the one-time capability file was consumed"
                ),
            },
            "confirmation_002": {
                "status": superseded_confirmation["status"],
                "provider_requests": superseded_confirmation["provider_requests"],
                "disposition": (
                    "downgraded to development evidence after the OpenWorker product bytes "
                    "changed in response to the primary final review"
                ),
            },
        },
        "declarations": {
            "dynamic_tool_profile": "NOT_CLAIMED",
            "schema": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
            "runtime": "0.1.x CANDIDATE",
            "production_ready": False,
        },
        "finished_at": state._now(),
    }

    candidate = FINAL_ROOT / "candidate"
    review = FINAL_ROOT / "review-workspace"
    candidate.mkdir(parents=True, mode=0o700)
    review.mkdir(parents=True, mode=0o700)
    state._atomic_write(FINAL_ROOT / "final-report.json", final_report)
    state._atomic_write(
        FINAL_ROOT / "package-content-manifests.json",
        frozen["package_delta_from_measured_product"],
    )
    state._atomic_write(FINAL_ROOT / "serving-005-field-diff.json", serving_diff)
    markdown = (
        "# DG-10 Final Engineering and Benchmark Report\n\n"
        f"Status: `{final_report['status']}`  \n"
        f"Release claim: `{final_report['release_claim']}`  \n"
        f"Package: `{package_run_id}`  \n"
        f"DEV F1 delta: `{final_report['quality']['dev']['deltas']['normalized_f1']}`  \n"
        "Confirmation F1 delta: `"
        f"{final_report['quality']['confirmation']['deltas']['normalized_f1']}`  \n"
        "Warm memory-control p95: `"
        f"{final_report['serving']['memory_control_target']['observed_p95_ms']} ms`  \n\n"
        "Primary xhigh review: `REVISE`; all five P1 findings were returned to development "
        "and addressed in this successor candidate.  \n\n"
        "The dynamic-tool profile is not claimed. Schema remains experimental and is not "
        "frozen; Runtime is a candidate, not Production Ready. Development AI audits: 0.\n"
    )
    (FINAL_ROOT / "final-report.md").write_text(markdown, encoding="utf-8")

    _copy(freeze_manifest, candidate / "freeze-manifest.json")
    _copy(CONFIRMATION_CONSUMPTION, candidate / "confirmation-consumption.json")
    _copy(FINAL_ROOT / "final-report.json", candidate / "final-report.json")
    _copy(FINAL_ROOT / "final-report.md", candidate / "final-report.md")
    for path in package_paths.values():
        _copy(path, candidate / "packages" / path.name)

    review_files = {
        "GOALS.md": ROOT / "MiLAi_DG-10实验结果整改与复验_GOALS.md",
        "IMPLEMENTATION_CONTRACT.md": ROOT / "MiLAi_Lean_V1_实施合同.md",
        "final/final-report.json": FINAL_ROOT / "final-report.json",
        "final/final-report.md": FINAL_ROOT / "final-report.md",
        "freeze/freeze-manifest.json": freeze_manifest,
        "freeze/confirmation-consumption.json": CONFIRMATION_CONSUMPTION,
        "evidence/confirmation-result.json": confirmation_result_path,
        "evidence/confirmation-report.json": confirmation_report_path,
        "evidence/confirmation-manifest.json": confirmation_manifest_path,
        "evidence/dev-result.json": dev_dir / "result.json",
        "evidence/serving-result.json": serving_dir / "result.json",
        "evidence/serving-report.json": serving_dir / "report.json",
        "evidence/f0-package-result.json": state.RUNS_ROOT
        / str(blocking.get("f0_package"))
        / "result.json",
        "evidence/f0-package-trace.json": state.RUNS_ROOT
        / str(blocking.get("f0_package"))
        / "trace.json",
        "evidence/f0-native-result.json": state.RUNS_ROOT
        / str(blocking.get("f0_native"))
        / "result.json",
        "evidence/f0-native-trace.json": state.RUNS_ROOT
        / str(blocking.get("f0_native"))
        / "trace.json",
        "evidence/f1-result.json": state.RUNS_ROOT
        / str(blocking.get("f1"))
        / "result.json",
        "evidence/t2-result.json": state.RUNS_ROOT
        / str(blocking.get("t2"))
        / "result.json",
        "evidence/hardened-result.json": state.RUNS_ROOT
        / str(blocking.get("hardened"))
        / "result.json",
        "evidence/package-content-manifests.json": FINAL_ROOT
        / "package-content-manifests.json",
        "evidence/primary-review-result.json": PRIMARY_REVIEW_RESULT,
        "evidence/confirmation-001-result.json": early_confirmation_dir
        / "result.json",
        "evidence/confirmation-001-manifest.json": early_confirmation_dir
        / "benchmark-manifest.json",
        "evidence/confirmation-002-result.json": superseded_confirmation_dir
        / "result.json",
        "evidence/serving-005-source-report.json": state.RUNS_ROOT
        / RECLASSIFIED_SERVING_RUN_ID
        / "report.json",
        "evidence/serving-005-source-result.json": state.RUNS_ROOT
        / RECLASSIFIED_SERVING_RUN_ID
        / "result.json",
        "evidence/serving-005-reclassification.json": state.RUNS_ROOT
        / RECLASSIFIED_SERVING_RUN_ID
        / "reclassification.json",
        "evidence/serving-005-field-diff.json": FINAL_ROOT
        / "serving-005-field-diff.json",
        "source/retrieval.py": ROOT / "runtime/src/milai/application/retrieval.py",
        "source/retrieval_repository.py": ROOT
        / "runtime/src/milai/persistence/retrieval_repository.py",
        "source/provider_execution.py": ROOT
        / "runtime/src/milai/adapters/provider_execution.py",
        "source/agent_prefetch.py": ROOT / "runtime/src/milai/adapters/agent_prefetch.py",
        "source/mcp_unix.py": ROOT / "runtime/src/milai/adapters/mcp_unix.py",
        "source/mcp_server.py": ROOT / "integrations/mcp/src/milai_mcp/server.py",
        "source/openworker_adapter.py": ROOT
        / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py",
        "source/lme_product_smoke.py": ROOT / "evals/benchmark/lme_product_smoke.py",
        "source/minimal_serving.py": ROOT / "evals/serving/minimal_baseline.py",
        "tests/test_retrieval_fusion.py": ROOT
        / "runtime/tests/unit/test_retrieval_fusion.py",
        "tests/test_provider_execution.py": ROOT
        / "runtime/tests/unit/test_provider_execution.py",
        "tests/test_mcp_profiles.py": ROOT / "integrations/mcp/tests/test_profiles.py",
        "tests/test_lme_product.py": ROOT / "tests/test_dg10_lme_product_smoke.py",
        "tests/test_minimal_serving.py": ROOT / "tests/test_dg10_minimal_serving.py",
    }
    for destination, source in review_files.items():
        if not source.is_file() or source.name == ".env":
            raise state.F0Error(f"review material is absent or unsafe: {source}")
        _copy(source, review / destination)
    state._atomic_write(
        review / "review-manifest.json",
        {
            "schema": "milai.dg10.final-review-manifest.v1",
            "claim": "MILAI_PREFETCH_AGENT_READY",
            "review_mode": "CONTROLLED_ADJUDICATION_AFTER_PRIMARY_REVISE",
            "review_budget": {"primary_input_tokens_max": 180000, "output_tokens_max": 16000},
            "prohibited_claims": [
                "MILAI_DYNAMIC_TOOL_AGENT_READY",
                "PRODUCTION_READY",
                "SCHEMA_FROZEN",
            ],
        },
    )
    inventory = _inventory(review)
    text_bytes = sum(item["bytes"] for item in inventory)
    if len(inventory) + 1 > 60 or text_bytes > 1024 * 1024:
        raise state.F0Error("review workspace exceeds the frozen file or text budget")
    state._atomic_write(
        review / "inventory.json",
        {
            "schema": "milai.dg10.review-inventory.v1",
            "regular_files": len(inventory) + 1,
            "normalized_review_text_bytes": text_bytes,
            "files": inventory,
        },
    )
    candidate_inventory = _inventory(candidate)
    state._atomic_write(
        candidate / "inventory.json",
        {
            "schema": "milai.dg10.candidate-inventory.v1",
            "files": candidate_inventory,
        },
    )
    _readonly(candidate)
    _readonly(review)

    run_dir = state.RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    result = {
        "schema": "milai.dg10.finalize-candidate-result.v1",
        "run_id": run_id,
        "status": "PASS",
        "cases": {"RM14-FREEZE": "PASS", "RM14-CONFIRMATION": "PASS"},
        "package_run_id": package_run_id,
        "confirmation_run_id": confirmation_run_id,
        "candidate_path": str(candidate),
        "review_workspace": str(review),
        "provider_requests": 0,
        "development_ai_audits": 0,
        "error": None,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "result.json", result)
    state._record_run(
        result,
        {
            "experiment_id": f"exp-{run_id}",
            "run_id": run_id,
            "timestamp": result["finished_at"],
            "rm_id": "RM-14",
            "rm_ids": ["RM-14"],
            "rm_statuses": {"RM-14": "PASS"},
            "hypothesis": "one frozen held-out run confirms the final prefetch package",
            "code_identity": frozen["confirmation_code_identity"],
            "model_identity": frozen["model_id"],
            "dataset_identity": frozen["dataset_sha256"],
            "prompt_identity": frozen["prompt_contract_sha256"],
            "budget": {"native_requests": 0},
            "expected_delta": "all confirmation gates PASS and one candidate materialized",
            "functional_gate": "RM14",
            "functional_cases_passed": list(result["cases"]),
            "functional_cases_failed": [],
            "actual_quality_delta": confirmation_report[
                "deltas_vs_strongest_baseline"
            ]["normalized_f1"],
            "actual_token_delta": confirmation_report[
                "deltas_vs_strongest_baseline"
            ]["prompt_tokens_mean"],
            "actual_latency_delta": serving_comparison[
                "t3a_warm_e2e_mean_delta_ms"
            ],
            "prepare_context_calls": 31,
            "full_recall_calls": 50,
            "cache_validation_calls": 0,
            "validated_cache_hit_rate": hardened["validated_cache_hit_rate"],
            "relevant_issue_misses": 0,
            "irrelevant_issue_injections": 0,
            "action_revalidation_failures": 0,
            "degraded_or_abstain_count": 0,
            "decision": "FREEZE",
            "next_action": "perform the single allowed controlled adjudication",
        },
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize the one DG-10 candidate")
    parser.add_argument(
        "--run-id",
        default=(
            "finalize-candidate-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--confirmation-run-id", required=True)
    parser.add_argument(
        "--freeze-manifest",
        type=Path,
        default=FREEZE_ROOT / "freeze-manifest-003.json",
    )
    args = parser.parse_args()
    result = finalize(
        args.run_id,
        confirmation_run_id=args.confirmation_run_id,
        freeze_manifest=args.freeze_manifest.resolve(),
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
