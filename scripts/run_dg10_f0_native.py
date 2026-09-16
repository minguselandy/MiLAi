from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_f0 as f0  # noqa: E402

RUNTIME_PYTHON = ROOT / "runtime/.venv/bin/python"
NATIVE_E2E = ROOT / "evals/agent_integration/e2e.py"


def _package_artifact_map(
    package_run_id: str,
) -> tuple[dict[str, Path], dict[str, Any]]:
    package_dir = f0.RUNS_ROOT / package_run_id
    try:
        result = json.loads((package_dir / "result.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise f0.F0Error(f"package run is unreadable: {package_run_id}") from exc
    if result.get("status") != "PASS" or result.get("cases") != {
        "F0-01": "PASS",
        "F0-02": "PASS",
    }:
        raise f0.F0Error(f"package run has not passed F0-01/F0-02: {package_run_id}")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        raise f0.F0Error("package run artifact manifest is missing")

    def resolve(name: str) -> Path:
        entry = artifacts.get(name)
        if not isinstance(entry, dict):
            raise f0.F0Error(f"package run is missing {name}")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise f0.F0Error(f"package run is missing {name}")
        path = (package_dir / raw_path).resolve()
        if (
            not path.is_relative_to(package_dir.resolve())
            or not path.is_file()
            or f0._sha256(path) != entry.get("sha256")
        ):
            raise f0.F0Error(f"package artifact identity drift: {name}")
        return path

    resolved = {
        name: resolve(name)
        for name in (
            "client_wheel",
            "mcp_wheel",
            "runtime_wheel",
            "openworker_wheel",
        )
        if name in artifacts
    }
    return resolved, artifacts


def _package_artifacts(package_run_id: str) -> tuple[Path, Path, dict[str, Any]]:
    resolved, artifacts = _package_artifact_map(package_run_id)
    try:
        return resolved["client_wheel"], resolved["mcp_wheel"], artifacts
    except KeyError as exc:  # pragma: no cover - validated legacy package boundary
        raise f0.F0Error("package run lacks core client/MCP wheels") from exc


def run_f0_native(run_id: str, package_run_id: str) -> dict[str, Any]:
    if f0._RUN_ID.fullmatch(run_id) is None:
        raise f0.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    if not RUNTIME_PYTHON.is_file():
        raise f0.F0Error("Runtime environment is not installed")
    client_wheel, mcp_wheel, package_artifacts = _package_artifacts(package_run_id)
    run_dir = f0.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise f0.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    code_identity = f0._tree_identity(
        [
            ROOT / "runtime/src",
            ROOT / "runtime/migrations",
            ROOT / "integrations/mcp/src",
            ROOT / "integrations/python-client/src",
            NATIVE_E2E,
            Path(__file__).resolve(),
        ]
    )
    manifest = {
        "schema": "milai.dg10.functional-run-manifest.v1",
        "run_id": run_id,
        "phase": "functional_f0",
        "cases": [f"F0-{index:02d}" for index in range(3, 11)],
        "created_at": f0._now(),
        "code_identity": code_identity,
        "package_run_id": package_run_id,
        "package_artifacts": {
            name: package_artifacts[name]
            for name in ("client_wheel", "mcp_wheel")
        },
        "data_boundary": "SYNTHETIC_ONLY",
        "database_boundary": "ISOLATED_EPHEMERAL_DATABASE",
        "provider": None,
        "max_native_requests": 0,
        "closed_test_access": False,
        "development_ai_audits": 0,
    }
    f0._atomic_write(run_dir / "manifest.json", manifest)
    trace: list[dict[str, Any]] = []
    started = time.monotonic()
    status = "FAILED"
    error: str | None = None
    native_report: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
            workspace = Path(temporary).resolve() / "installed-product"
            install = f0._probe_install(
                kind="wheel",
                client_artifact=client_wheel,
                mcp_artifact=mcp_wheel,
                workspace=workspace,
                trace=trace,
            )
            report_path = run_dir / "native-e2e.json"
            environment = dict(os.environ)
            environment["DG10_MCP_HOST_PYTHON"] = install["python"]
            f0._run(
                [
                    str(RUNTIME_PYTHON),
                    str(NATIVE_E2E),
                    "--env-file",
                    str(ROOT / "runtime/.env"),
                    "--report",
                    str(report_path),
                ],
                cwd=ROOT,
                env=environment,
                trace=trace,
                timeout=300,
            )
            native_report = json.loads(report_path.read_text(encoding="utf-8"))
        expected_cases = {f"F0-{index:02d}": "PASS" for index in range(3, 11)}
        if native_report.get("status") != "PASS":
            raise f0.F0Error("native E2E did not finish with PASS")
        if native_report.get("functional_cases") != expected_cases:
            raise f0.F0Error("native E2E functional-case matrix is incomplete")
        if (native_report.get("cleanup") or {}).get("status") != "PASS":
            raise f0.F0Error("native E2E database cleanup is incomplete")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    cases = {
        f"F0-{index:02d}": (
            "PASS"
            if status == "PASS"
            else (native_report.get("functional_cases") or {}).get(
                f"F0-{index:02d}", "FAILED"
            )
        )
        for index in range(3, 11)
    }
    result = {
        "schema": "milai.dg10.functional-run-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": cases,
        "package_run_id": package_run_id,
        "provider_requests": 0,
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "error": error,
        "finished_at": f0._now(),
    }
    f0._atomic_write(run_dir / "trace.json", {"commands": trace})
    f0._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-03",
        "rm_ids": ["RM-03", "RM-09", "RM-13"],
        "hypothesis": (
            "the installed MCP product preserves governed memory across sessions, "
            "conflict, revoke, restart, isolation failures, and disconnect"
        ),
        "code_identity": code_identity,
        "model_identity": None,
        "dataset_identity": "SYNTHETIC_ISOLATED_POSTGRESQL",
        "prompt_identity": None,
        "budget": {"native_requests": 0, "deadline_seconds": 300},
        "expected_delta": "F0-03 through F0-10 PASS",
        "functional_gate": "F0",
        "functional_cases_passed": [case for case, value in cases.items() if value == "PASS"],
        "functional_cases_failed": [case for case, value in cases.items() if value != "PASS"],
        "actual_quality_delta": None,
        "actual_token_delta": 0,
        "actual_latency_delta": None,
        "prepare_context_calls": 0,
        "full_recall_calls": 0,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": sum(
            phase.get("status") == "PASS"
            and phase.get("session") in {2, "runtime-disconnected"}
            for phase in native_report.get("phases", [])
            if isinstance(phase, dict)
        ),
        "status": status,
    }
    f0._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DG-10 F0-03/F0-10 on the installed MCP product and real PostgreSQL"
    )
    parser.add_argument(
        "--run-id",
        default=f"f0-native-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
    )
    parser.add_argument("--package-run-id", required=True)
    args = parser.parse_args()
    result = run_f0_native(args.run_id, args.package_run_id)
    print(
        json.dumps(
            {"run_id": result["run_id"], "status": result["status"], "cases": result["cases"]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
