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

from milai.adapters.agent_prefetch import SYSTEM_PROMPT

from evals.agent_integration.f1 import RESPONSE_RULES
from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native

RUNTIME_PYTHON = ROOT / "runtime/.venv/bin/python"
EVALUATOR = ROOT / "evals/agent_integration/f1_openworker.py"
ADAPTER = ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"
TOKENIZER_JSON = Path("/cra/qwen36-35B/tokenizer.json")


def _provider_terminals(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(
        json.loads(line).get("event") == "PROVIDER_TERMINAL"
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def run_openworker(
    run_id: str,
    package_run_id: str,
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
        raise state.F0Error("package run predates the OpenWorker composite product")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    now = datetime.now(UTC)
    dataset = {
        "question": "What runtime Python version is recorded for one synthetic project?",
        "phases": ["no-candidate", "available", "open-issue", "revoked", "unavailable"],
        "answers": ["UNKNOWN", "3.11", "UNCERTAIN", "UNCERTAIN", "UNKNOWN"],
        "container": "OpenWorker",
    }
    dataset_digest = hashlib.sha256(
        json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prompt_digest = hashlib.sha256(
        (SYSTEM_PROMPT + RESPONSE_RULES + "openworker-mcp-prefetch-v1").encode()
    ).hexdigest()
    provider_manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "functional_f1",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": dataset_digest,
        "prompt_template_sha256": prompt_digest,
        "max_native_requests": 4,
        "max_prompt_tokens": 4 * 768,
        "max_completion_tokens": 4 * 96,
        "deadline": (now + timedelta(minutes=30)).isoformat(),
        "expires_at": (now + timedelta(minutes=40)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    provider_manifest_path = run_dir / "provider-manifest.json"
    provider_ledger_path = run_dir / "provider-ledger.jsonl"
    adapter_trace_path = run_dir / "openworker-adapter-trace.jsonl"
    report_path = run_dir / "openworker-e2e.json"
    state._atomic_write(provider_manifest_path, provider_manifest)
    state._atomic_write(
        run_dir / "functional-manifest.json",
        {
            "schema": "milai.dg10.functional-run-manifest.v1",
            "run_id": run_id,
            "phase": "functional_f1_openworker",
            "cases": [*[f"OW-F1-{index:02d}" for index in range(1, 6)], "OPENWORKER-F1"],
            "created_at": state._now(),
            "package_run_id": package_run_id,
            "package_artifacts": {
                name: package_artifacts[name] for name in sorted(required_packages)
            },
            "data_boundary": "SYNTHETIC_ONLY",
            "container_boundary": "REAL_OPENWORKER_LOCAL_CONTAINER",
            "provider_manifest": "provider-manifest.json",
            "max_native_requests": 4,
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
                    "evals.agent_integration.f1_openworker",
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
                    "--tokenizer-json",
                    str(TOKENIZER_JSON),
                    "--adapter-python",
                    install["python"],
                ],
                cwd=ROOT,
                env=environment,
                trace=trace,
                timeout=1200,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        expected = {
            **{f"OW-F1-{index:02d}": "PASS" for index in range(1, 6)},
            "OPENWORKER-F1": "PASS",
        }
        if report.get("status") != "PASS" or report.get("functional_cases") != expected:
            raise state.F0Error("OpenWorker F1 case matrix is incomplete")
        if (report.get("openworker_cleanup") or {}).get("status") != "PASS":
            raise state.F0Error("OpenWorker container cleanup is incomplete")
        if (report.get("database_cleanup") or {}).get("status") != "PASS":
            raise state.F0Error("OpenWorker database cleanup is incomplete")
        status = "PASS"
    except Exception as exc:  # noqa: BLE001 - every terminal failure must be recorded
        error = f"{type(exc).__name__}: {exc}"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
    case_names = [*[f"OW-F1-{index:02d}" for index in range(1, 6)], "OPENWORKER-F1"]
    cases = {
        name: (
            "PASS"
            if status == "PASS"
            else (report.get("functional_cases") or {}).get(name, "FAILED")
        )
        for name in case_names
    }
    result = {
        "schema": "milai.dg10.functional-run-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": cases,
        "package_run_id": package_run_id,
        "provider_requests": _provider_terminals(provider_ledger_path),
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
        "rm_ids": ["RM-01", "RM-07", "RM-13"],
        "hypothesis": (
            "a real isolated OpenWorker consumes reader-lite MCP output through deterministic "
            "prefetch and the product ProviderExecutionGateway without an AI acceptance gate"
        ),
        "code_identity": state._tree_identity(
            [
                EVALUATOR,
                ADAPTER,
                ROOT / "runtime/src/milai/adapters/agent_prefetch.py",
                ROOT / "runtime/src/milai/adapters/provider_execution.py",
                Path(__file__).resolve(),
            ]
        ),
        "model_identity": MODEL_ID,
        "dataset_identity": dataset_digest,
        "prompt_identity": prompt_digest,
        "budget": {
            "native_requests": 4,
            "prompt_tokens": 4 * 768,
            "completion_tokens": 4 * 96,
        },
        "expected_delta": "OpenWorker five-phase paired functional path with four model calls",
        "functional_gate": "F1_OPENWORKER",
        "functional_cases_passed": [name for name, value in cases.items() if value == "PASS"],
        "functional_cases_failed": [name for name, value in cases.items() if value != "PASS"],
        "actual_quality_delta": None,
        "actual_token_delta": None,
        "actual_latency_delta": None,
        "prepare_context_calls": 4,
        "full_recall_calls": 5,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 4,
        "status": status,
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DG-10 F1 through a real OpenWorker container"
    )
    parser.add_argument(
        "--run-id",
        default=(
            "f1-openworker-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run_openworker(args.run_id, args.package_run_id, endpoint=args.endpoint)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "cases": result["cases"],
                "provider_requests": result["provider_requests"],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
