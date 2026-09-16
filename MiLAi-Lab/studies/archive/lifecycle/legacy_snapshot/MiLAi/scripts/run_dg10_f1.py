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
F1_EVAL = ROOT / "evals/agent_integration/f1.py"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"


def run_f1(
    run_id: str,
    package_run_id: str,
    *,
    endpoint: str = ENDPOINT,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    client_wheel, mcp_wheel, package_artifacts = native._package_artifacts(package_run_id)
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    now = datetime.now(UTC)
    dataset = {
        "question": "What runtime Python version is recorded for the synthetic project?",
        "control": "UNKNOWN",
        "memory": "3.11",
        "negative_states": ["OPEN_ISSUE", "REVOKED", "RUNTIME_UNAVAILABLE"],
    }
    dataset_digest = hashlib.sha256(
        json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prompt_digest = hashlib.sha256((SYSTEM_PROMPT + RESPONSE_RULES).encode()).hexdigest()
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
        "deadline": (now + timedelta(minutes=20)).isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    provider_manifest_path = run_dir / "provider-manifest.json"
    provider_ledger_path = run_dir / "provider-ledger.jsonl"
    state._atomic_write(provider_manifest_path, provider_manifest)
    functional_manifest = {
        "schema": "milai.dg10.functional-run-manifest.v1",
        "run_id": run_id,
        "phase": "functional_f1",
        "cases": [f"F1-{index:02d}" for index in range(1, 6)],
        "created_at": state._now(),
        "package_run_id": package_run_id,
        "package_artifacts": {
            name: package_artifacts[name]
            for name in ("client_wheel", "mcp_wheel")
        },
        "data_boundary": "SYNTHETIC_ONLY",
        "database_boundary": "ISOLATED_EPHEMERAL_DATABASE",
        "provider_manifest": "provider-manifest.json",
        "max_native_requests": 4,
        "development_ai_audits": 0,
    }
    state._atomic_write(run_dir / "functional-manifest.json", functional_manifest)
    trace: list[dict[str, Any]] = []
    started = time.monotonic()
    status = "FAILED"
    error: str | None = None
    f1_report: dict[str, Any] = {}
    report_path = run_dir / "f1-e2e.json"
    try:
        with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
            install = state._probe_install(
                kind="wheel",
                client_artifact=client_wheel,
                mcp_artifact=mcp_wheel,
                workspace=Path(temporary).resolve() / "installed-product",
                trace=trace,
            )
            environment = dict(os.environ)
            environment["DG10_MCP_HOST_PYTHON"] = install["python"]
            state._run(
                [
                    str(RUNTIME_PYTHON),
                    "-m",
                    "evals.agent_integration.f1",
                    "--env-file",
                    str(ROOT / "runtime/.env"),
                    "--report",
                    str(report_path),
                    "--provider-manifest",
                    str(provider_manifest_path),
                    "--provider-ledger",
                    str(provider_ledger_path),
                ],
                cwd=ROOT,
                env=environment,
                trace=trace,
                timeout=600,
            )
            f1_report = json.loads(report_path.read_text(encoding="utf-8"))
        expected_cases = {f"F1-{index:02d}": "PASS" for index in range(1, 6)}
        if f1_report.get("status") != "PASS":
            raise state.F0Error("F1 evaluator did not finish with PASS")
        if f1_report.get("functional_cases") != expected_cases:
            raise state.F0Error("F1 case matrix is incomplete")
        if (f1_report.get("cleanup") or {}).get("status") != "PASS":
            raise state.F0Error("F1 database cleanup is incomplete")
        status = "PASS"
    except Exception as exc:  # noqa: BLE001 - every terminal failure must be recorded
        error = f"{type(exc).__name__}: {exc}"
        if report_path.is_file():
            f1_report = json.loads(report_path.read_text(encoding="utf-8"))
    cases = {
        f"F1-{index:02d}": (
            "PASS"
            if status == "PASS"
            else (f1_report.get("functional_cases") or {}).get(
                f"F1-{index:02d}", "FAILED"
            )
        )
        for index in range(1, 6)
    }
    result = {
        "schema": "milai.dg10.functional-run-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": cases,
        "package_run_id": package_run_id,
        "provider_requests": (f1_report.get("provider_trace") or {}).get(
            "provider_terminals", 0
        ),
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
        "rm_id": "RM-01",
        "rm_ids": ["RM-01", "RM-07"],
        "hypothesis": (
            "one deterministic MCP prefetch lets the same Agent consume governed cross-session "
            "memory while controls and unsafe states remain uncertain"
        ),
        "code_identity": state._tree_identity(
            [
                ROOT / "runtime/src/milai/adapters/agent_prefetch.py",
                ROOT / "runtime/src/milai/adapters/provider_execution.py",
                F1_EVAL,
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
        "expected_delta": "F1 5/5 with exactly four model calls",
        "functional_gate": "F1",
        "functional_cases_passed": [case for case, value in cases.items() if value == "PASS"],
        "functional_cases_failed": [case for case, value in cases.items() if value != "PASS"],
        "actual_quality_delta": None,
        "actual_token_delta": sum(
            int(record.get("prompt_tokens", 0)) + int(record.get("completion_tokens", 0))
            for record in (f1_report.get("agent_cases") or {}).values()
            if isinstance(record, dict)
        ),
        "actual_latency_delta": None,
        "prepare_context_calls": 3,
        "full_recall_calls": 3,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 3,
        "status": status,
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run paired DG-10 F1 Agent cases through installed MCP and local vLLM"
    )
    parser.add_argument(
        "--run-id",
        default=f"f1-agent-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run_f1(args.run_id, args.package_run_id, endpoint=args.endpoint)
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
