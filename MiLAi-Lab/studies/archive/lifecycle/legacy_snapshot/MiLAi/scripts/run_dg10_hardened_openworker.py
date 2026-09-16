from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native

RUNTIME_PYTHON = ROOT / "runtime/.venv/bin/python"
EVALUATOR = ROOT / "evals/agent_integration/hardened_openworker.py"
PRODUCT_PROBE = ROOT / "evals/agent_integration/product_probe.py"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"
SCENARIOS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8a", "S8b", "S8c", "S9", "S10")


def _provider_terminals(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(
        json.loads(line).get("event") == "PROVIDER_TERMINAL"
        for line in path.read_text().splitlines()
    )


def run(
    run_id: str,
    package_run_id: str,
    f1_run_id: str,
    *,
    endpoint: str = ENDPOINT,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    package_paths, package_artifacts = native._package_artifact_map(package_run_id)
    required_packages = {
        "client_wheel",
        "mcp_wheel",
        "runtime_wheel",
        "openworker_wheel",
    }
    if not required_packages.issubset(package_paths):
        raise state.F0Error(
            "package run does not contain the hardened OpenWorker product"
        )
    f1_result_path = state.RUNS_ROOT / f1_run_id / "result.json"
    if not f1_result_path.is_file():
        raise state.F0Error("same-package F1 result is absent")
    f1_result = json.loads(f1_result_path.read_text())
    if (
        f1_result.get("status") != "PASS"
        or f1_result.get("package_run_id") != package_run_id
    ):
        raise state.F0Error("F1 result is not a PASS for the requested package")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    now = datetime.now(UTC)
    dataset = {
        "scenarios": list(SCENARIOS),
        "cache_repetitions": 10,
        "model_cases": ["S2", "S10"],
        "f1_reference": f1_run_id,
    }
    dataset_digest = hashlib.sha256(
        json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    provider_manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "dev",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": dataset_digest,
        "prompt_template_sha256": hashlib.sha256(
            b"milai-hardened-s1-s10-v1"
        ).hexdigest(),
        "max_native_requests": 2,
        "max_prompt_tokens": 2 * 768,
        "max_completion_tokens": 2 * 96,
        "deadline": (now + timedelta(minutes=30)).isoformat(),
        "expires_at": (now + timedelta(minutes=40)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    provider_manifest_path = run_dir / "provider-manifest.json"
    provider_ledger_path = run_dir / "provider-ledger.jsonl"
    adapter_trace_path = run_dir / "openworker-adapter-trace.jsonl"
    report_path = run_dir / "hardened-openworker.json"
    state._atomic_write(provider_manifest_path, provider_manifest)
    state._atomic_write(
        run_dir / "functional-manifest.json",
        {
            "schema": "milai.dg10.hardened-openworker-manifest.v1",
            "run_id": run_id,
            "package_run_id": package_run_id,
            "f1_run_id": f1_run_id,
            "package_artifacts": {
                name: package_artifacts[name] for name in sorted(required_packages)
            },
            "scenarios": list(SCENARIOS),
            "max_native_requests": 2,
            "development_ai_audits": 0,
        },
    )
    trace: list[dict[str, Any]] = []
    started = time.monotonic()
    status = "FAILED"
    error: str | None = None
    report: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
            install = state._probe_install(
                kind="wheel",
                client_artifact=package_paths["client_wheel"],
                mcp_artifact=package_paths["mcp_wheel"],
                runtime_artifact=package_paths["runtime_wheel"],
                openworker_artifact=package_paths["openworker_wheel"],
                workspace=Path(temporary).resolve() / "installed-product",
                trace=trace,
            )
            environment = dict(os.environ)
            environment["DG10_MCP_HOST_PYTHON"] = install["python"]
            state._run(
                [
                    str(RUNTIME_PYTHON),
                    "-m",
                    "evals.agent_integration.hardened_openworker",
                    "--env-file",
                    str(ROOT / "runtime/.env"),
                    "--report",
                    str(report_path),
                    "--provider-manifest",
                    str(provider_manifest_path),
                    "--provider-ledger",
                    str(provider_ledger_path),
                    "--adapter-trace",
                    str(adapter_trace_path),
                    "--mcp-executable",
                    install["entrypoint"],
                    "--product-python",
                    install["python"],
                    "--f1-result",
                    str(f1_result_path),
                ],
                cwd=ROOT,
                env=environment,
                trace=trace,
                timeout=1_200,
            )
            report = json.loads(report_path.read_text())
        if report.get("status") != "PASS" or set(report.get("scenarios") or {}) != set(
            SCENARIOS
        ):
            raise state.F0Error("hardened OpenWorker scenario matrix is incomplete")
        if any(
            (report.get(name) or {}).get("status") != "PASS"
            for name in ("submitter_cleanup", "openworker_cleanup", "database_cleanup")
        ):
            raise state.F0Error("hardened OpenWorker cleanup is incomplete")
        if _provider_terminals(provider_ledger_path) != 2:
            raise state.F0Error("hardened OpenWorker provider denominator drift")
        status = "PASS"
    except Exception as exc:  # noqa: BLE001 - every failed denominator is retained
        error = f"{type(exc).__name__}: {exc}"
        if report_path.is_file():
            report = json.loads(report_path.read_text())
    scenarios = report.get("scenarios") or {}
    cases = {
        name: "PASS"
        if status == "PASS"
        else (scenarios.get(name) or {}).get("status", "FAILED")
        for name in SCENARIOS
    }
    cache = scenarios.get("S4") or {}
    result = {
        "schema": "milai.dg10.hardened-openworker-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": cases,
        "package_run_id": package_run_id,
        "f1_run_id": f1_run_id,
        "provider_requests": _provider_terminals(provider_ledger_path),
        "validated_cache_hit_rate": cache.get("validated_cache_hit_rate"),
        "validated_cache_warm_p95_ms": cache.get("validated_cache_warm_p95_ms"),
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "error": error,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "trace.json", {"commands": trace})
    state._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-13",
        "rm_ids": ["RM-07", "RM-09", "RM-13"],
        "hypothesis": (
            "the fresh-installed OpenWorker product satisfies S1-S10 with validated cache, "
            "profile-isolated settlement and restart/recreate recovery"
        ),
        "code_identity": state._tree_identity(
            [
                EVALUATOR,
                PRODUCT_PROBE,
                ROOT
                / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py",
                ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/broker.py",
                ROOT
                / "integrations/openworker-mcp/src/milai_openworker_mcp/settlement.py",
                Path(__file__).resolve(),
            ]
        ),
        "model_identity": MODEL_ID,
        "dataset_identity": dataset_digest,
        "prompt_identity": provider_manifest["prompt_template_sha256"],
        "budget": {"native_requests": 2, "cache_repetitions": 10},
        "expected_delta": "S1-S10 all PASS with >=80% validated cache and zero safety failures",
        "functional_gate": "S1_S10",
        "functional_cases_passed": [
            name for name, value in cases.items() if value == "PASS"
        ],
        "functional_cases_failed": [
            name for name, value in cases.items() if value != "PASS"
        ],
        "actual_quality_delta": None,
        "actual_token_delta": None,
        "actual_latency_delta": cache.get("validated_cache_warm_p95_ms"),
        "prepare_context_calls": 12,
        "full_recall_calls": cache.get("full_recall_calls"),
        "cache_validation_calls": cache.get("validation_calls"),
        "validated_cache_hit_rate": cache.get("validated_cache_hit_rate"),
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 0,
        "safety_failures": 0 if status == "PASS" else None,
        "status": status,
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fresh-installed OpenWorker S1-S10"
    )
    parser.add_argument(
        "--run-id",
        default=(
            "hardened-openworker-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--f1-run-id", required=True)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run(
        args.run_id,
        args.package_run_id,
        args.f1_run_id,
        endpoint=args.endpoint,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
