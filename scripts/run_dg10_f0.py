from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "var/dg10/runs"
CURRENT_STATE = ROOT / "var/dg10/current-state.json"
EXPERIMENTS = ROOT / "var/dg10/experiments.jsonl"
CLIENT_PROJECT = ROOT / "integrations/python-client"
MCP_PROJECT = ROOT / "integrations/mcp"
RUNTIME_PROJECT = ROOT / "runtime"
OPENWORKER_PROJECT = ROOT / "integrations/openworker-mcp"
MCP_HOST = ROOT / "evals/agent_integration/mcp_host.py"
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_SYNTHETIC_TOKEN = "dg10-f0-" + hashlib.sha256(b"synthetic-only").hexdigest()

_BASE_TOOLS = {
    "milai_status",
    "milai_recall",
    "milai_claim_get",
    "milai_open_issues_list",
    "milai_trace_get",
    "milai_evidence_metadata_get",
}
EXPECTED_CATALOGS = {
    "reader-lite": {"milai_recall"},
    "reader-detail": _BASE_TOOLS,
    "reader": _BASE_TOOLS,
    "submitter": _BASE_TOOLS | {"milai_evidence_capture", "milai_proposal_create"},
    "operator": _BASE_TOOLS | {"milai_evidence_revoke", "milai_deletion_status_get"},
}


class F0Error(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_identity(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        else:
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file()
                and "__pycache__" not in item.parts
                and item.suffix not in {".pyc", ".pyo"}
                and "dist" not in item.parts
                and ".venv" not in item.parts
            )
    for path in sorted(files):
        relative = path.relative_to(ROOT).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        file_digest = bytes.fromhex(_sha256(path))
        digest.update(file_digest)
    return digest.hexdigest()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_text(value: str | bytes, *, limit: int = 4000) -> str:
    text = value.decode(errors="replace") if isinstance(value, bytes) else value
    return text.replace(_SYNTHETIC_TOKEN, "[REDACTED]")[-limit:]


def _run(
    command: list[str],
    *,
    cwd: Path,
    trace: list[dict[str, Any]],
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    record: dict[str, Any] = {
        "command": command,
        "cwd": str(cwd),
        "started_at": _now(),
        "timeout_seconds": timeout,
    }
    try:
        completed = subprocess.run(  # noqa: S603 - every command is locally constructed
            command,
            cwd=cwd,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        record.update(
            {
                "duration_seconds": round(time.monotonic() - started, 6),
                "status": "TIMEOUT",
                "stdout_tail": _safe_text(exc.stdout or ""),
                "stderr_tail": _safe_text(exc.stderr or ""),
            }
        )
        trace.append(record)
        raise F0Error(f"command timed out after {timeout}s: {command[0]}") from exc
    record.update(
        {
            "duration_seconds": round(time.monotonic() - started, 6),
            "exit_code": completed.returncode,
            "status": "PASS" if completed.returncode == 0 else "FAILED",
            "stdout_tail": _safe_text(completed.stdout),
            "stderr_tail": _safe_text(completed.stderr),
        }
    )
    trace.append(record)
    if completed.returncode != 0:
        raise F0Error(
            f"command failed ({completed.returncode}): {command[0]}; "
            f"stderr={_safe_text(completed.stderr, limit=1200)!r}"
        )
    return completed


def _one_artifact(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise F0Error(f"expected one {pattern} in {directory}, found {len(matches)}")
    return matches[0]


def _build_packages(artifacts: Path, trace: list[dict[str, Any]]) -> dict[str, Path]:
    client_out = artifacts / "python-client"
    mcp_out = artifacts / "mcp"
    runtime_out = artifacts / "runtime"
    openworker_out = artifacts / "openworker-mcp"
    client_out.mkdir(parents=True)
    mcp_out.mkdir(parents=True)
    runtime_out.mkdir(parents=True)
    openworker_out.mkdir(parents=True)
    _run(
        ["uv", "build", str(CLIENT_PROJECT), "--out-dir", str(client_out)],
        cwd=ROOT,
        trace=trace,
    )
    _run(
        ["uv", "build", str(MCP_PROJECT), "--out-dir", str(mcp_out)],
        cwd=ROOT,
        trace=trace,
    )
    _run(
        ["uv", "build", str(RUNTIME_PROJECT), "--out-dir", str(runtime_out)],
        cwd=ROOT,
        trace=trace,
    )
    _run(
        ["uv", "build", str(OPENWORKER_PROJECT), "--out-dir", str(openworker_out)],
        cwd=ROOT,
        trace=trace,
    )
    return {
        "client_wheel": _one_artifact(client_out, "milai_client-*.whl"),
        "client_sdist": _one_artifact(client_out, "milai_client-*.tar.gz"),
        "mcp_wheel": _one_artifact(mcp_out, "milai_mcp-*.whl"),
        "mcp_sdist": _one_artifact(mcp_out, "milai_mcp-*.tar.gz"),
        "runtime_wheel": _one_artifact(runtime_out, "milai_runtime-*.whl"),
        "runtime_sdist": _one_artifact(runtime_out, "milai_runtime-*.tar.gz"),
        "openworker_wheel": _one_artifact(openworker_out, "milai_openworker_mcp-*.whl"),
        "openworker_sdist": _one_artifact(
            openworker_out, "milai_openworker_mcp-*.tar.gz"
        ),
    }


def _validate_catalog(profile: str, payload: dict[str, Any]) -> None:
    if payload.get("protocol_version") != "2026-07-28":
        raise F0Error(f"{profile}: unexpected protocol version")
    names = payload.get("tools")
    if not isinstance(names, list) or set(names) != EXPECTED_CATALOGS[profile]:
        raise F0Error(f"{profile}: tool catalog drift: {names!r}")
    if names != sorted(names):
        raise F0Error(f"{profile}: tool catalog is not deterministic")
    catalog = payload.get("catalog")
    if not isinstance(catalog, list) or len(catalog) != len(names):
        raise F0Error(f"{profile}: full catalog payload is missing")
    for tool in catalog:
        if (
            not isinstance(tool, dict)
            or tool.get("name") not in EXPECTED_CATALOGS[profile]
        ):
            raise F0Error(f"{profile}: malformed tool descriptor")
        schema = tool.get("inputSchema")
        if (
            not isinstance(schema, dict)
            or schema.get("additionalProperties") is not False
        ):
            raise F0Error(f"{profile}/{tool.get('name')}: schema is not closed")


def _probe_install(
    *,
    kind: str,
    client_artifact: Path,
    mcp_artifact: Path,
    runtime_artifact: Path | None = None,
    runtime_extras: tuple[str, ...] = (),
    openworker_artifact: Path | None = None,
    workspace: Path,
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=False)
    venv = workspace / f"{kind}-venv"
    _run(["uv", "venv", "--python", "3.11", str(venv)], cwd=workspace, trace=trace)
    python = venv / "bin/python"
    install_artifacts = [str(client_artifact), str(mcp_artifact)]
    if runtime_extras and runtime_artifact is None:
        raise F0Error("runtime extras require a Runtime artifact")
    if any(
        re.fullmatch(r"[a-z0-9][a-z0-9-]*", extra) is None for extra in runtime_extras
    ):
        raise F0Error("runtime extra name is invalid")
    if runtime_artifact is not None:
        runtime_spec = str(runtime_artifact)
        if runtime_extras:
            runtime_spec += f"[{','.join(sorted(set(runtime_extras)))}]"
        install_artifacts.append(runtime_spec)
    if openworker_artifact is not None:
        install_artifacts.append(str(openworker_artifact))
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            *install_artifacts,
        ],
        cwd=workspace,
        trace=trace,
        timeout=300,
    )
    origin_imports = ["milai_client", "milai_mcp"]
    origin_entries = [
        "'client':milai_client.__file__",
        "'mcp':milai_mcp.__file__",
    ]
    if runtime_artifact is not None:
        origin_imports.append("milai")
        origin_entries.append("'runtime':milai.__file__")
    if openworker_artifact is not None:
        origin_imports.append("milai_openworker_mcp")
        origin_entries.append("'openworker':milai_openworker_mcp.__file__")
    origin_program = (
        f"import json,{','.join(origin_imports)};"
        f"print(json.dumps({{{','.join(origin_entries)}}}))"
    )
    origin_run = _run(
        [str(python), "-I", "-c", origin_program], cwd=workspace, trace=trace
    )
    origins = json.loads(origin_run.stdout)
    venv_root = venv.resolve()
    for name, raw_path in origins.items():
        origin = Path(raw_path).resolve()
        if not origin.is_relative_to(venv_root) or origin.is_relative_to(ROOT):
            raise F0Error(
                f"{kind}: {name} imported outside the fresh environment: {origin}"
            )

    migration_probe: dict[str, Any] | None = None
    if runtime_artifact is not None:
        migration_run = _run(
            [
                str(python),
                "-I",
                "-c",
                (
                    "import json;from alembic.script import ScriptDirectory;"
                    "from milai.operations.migrations import alembic_config,migration_layout;"
                    "l=migration_layout();c=alembic_config();"
                    "print(json.dumps({'config':str(l.config_path),'scripts':str(l.script_path),"
                    "'packaged':l.packaged,'head':ScriptDirectory.from_config(c).get_current_head()}))"
                ),
            ],
            cwd=workspace,
            trace=trace,
        )
        migration_probe = json.loads(migration_run.stdout)
        migration_paths = (
            Path(str(migration_probe.get("config", ""))).resolve(),
            Path(str(migration_probe.get("scripts", ""))).resolve(),
        )
        if (
            migration_probe.get("packaged") is not True
            or not isinstance(migration_probe.get("head"), str)
            or not migration_probe["head"]
            or any(not path.is_relative_to(venv_root) for path in migration_paths)
        ):
            raise F0Error(f"{kind}: Runtime migration resources are not installed")

    executable = venv / "bin/milai-mcp"
    _run([str(executable), "--help"], cwd=workspace, trace=trace, timeout=30)
    adapter_executable: Path | None = None
    broker_executable: Path | None = None
    if openworker_artifact is not None:
        adapter_executable = venv / "bin/milai-openworker-adapter"
        broker_executable = venv / "bin/milai-mcp-broker"
        _run(
            [str(adapter_executable), "--help"], cwd=workspace, trace=trace, timeout=30
        )
        _run([str(broker_executable), "--help"], cwd=workspace, trace=trace, timeout=30)
    probe_environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "",
        "MILAI_BASE_URL": "http://127.0.0.1:9",
        "MILAI_AGENT_TOKEN": _SYNTHETIC_TOKEN,
        "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["dg10-f0"]}',
        "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
        "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
        "MILAI_AGENT_MAX_LIMIT": "3",
    }
    catalogs: dict[str, Any] = {}
    for profile in EXPECTED_CATALOGS:
        completed = _run(
            [
                str(python),
                "-I",
                str(MCP_HOST),
                "--profile",
                profile,
                "--mode",
                "2026-07-28",
                "--include-catalog",
            ],
            cwd=workspace,
            env=probe_environment,
            input_text="{}\n",
            trace=trace,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
        _validate_catalog(profile, payload)
        installed_executable = Path(payload["server_executable"]).resolve()
        if installed_executable != executable.resolve():
            raise F0Error(
                f"{kind}/{profile}: MCP host launched an unexpected executable"
            )
        catalogs[profile] = {
            "protocol_version": payload["protocol_version"],
            "tools": payload["tools"],
            "schemas_closed": True,
        }
    return {
        "status": "PASS",
        "artifact_kind": kind,
        "non_repo_cwd": str(workspace),
        "python": str(python),
        "entrypoint": str(executable),
        "adapter_entrypoint": (
            str(adapter_executable) if adapter_executable is not None else None
        ),
        "broker_entrypoint": (
            str(broker_executable) if broker_executable is not None else None
        ),
        "package_origins": origins,
        "runtime_extras": sorted(set(runtime_extras)),
        "runtime_migrations": migration_probe,
        "catalogs": catalogs,
    }


def _initial_rm_state() -> dict[str, Any]:
    return {f"RM-{index:02d}": {"status": "NOT_STARTED"} for index in range(16)}


def _record_run(result: dict[str, Any], experiment: dict[str, Any]) -> None:
    EXPERIMENTS.parent.mkdir(parents=True, exist_ok=True)
    with EXPERIMENTS.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(experiment, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        if CURRENT_STATE.exists():
            state = json.loads(CURRENT_STATE.read_text(encoding="utf-8"))
        else:
            state = {
                "schema": "milai.dg10.current-state.v1",
                "goal": "MILAI_MCP_MEMORY_FUNCTIONAL",
                "rm": _initial_rm_state(),
                "functional_gates": {"F0": "NOT_STARTED", "F1": "NOT_STARTED"},
            }
        rm = state.setdefault("rm", _initial_rm_state())
        rm00 = rm.setdefault("RM-00", {})
        if rm00.get("status") != "PASS":
            rm00["status"] = "IN_PROGRESS"
        rm["RM-00"]["development_ai_audits"] = 0
        rm_ids = experiment.get("rm_ids", [experiment["rm_id"]])
        if not isinstance(rm_ids, list) or not all(
            isinstance(item, str) and item in rm for item in rm_ids
        ):
            raise F0Error("experiment rm_ids are invalid")
        for rm_id in rm_ids:
            rm[rm_id]["status"] = "PASS" if result["status"] == "PASS" else "FAILED"
            rm[rm_id]["last_run_id"] = result["run_id"]
        rm_statuses = experiment.get("rm_statuses", {})
        if not isinstance(rm_statuses, dict) or not all(
            isinstance(rm_id, str)
            and rm_id in rm
            and status in {"NOT_STARTED", "IN_PROGRESS", "PASS", "FAILED"}
            for rm_id, status in rm_statuses.items()
        ):
            raise F0Error("experiment rm_statuses are invalid")
        for rm_id, status in rm_statuses.items():
            rm[rm_id]["status"] = status
            rm[rm_id]["last_run_id"] = result["run_id"]
        state["functional_cases"] = {
            **state.get("functional_cases", {}),
            **result["cases"],
        }
        all_f0_pass = all(
            state["functional_cases"].get(f"F0-{index:02d}") == "PASS"
            for index in range(1, 11)
        )
        state.setdefault("functional_gates", {})["F0"] = (
            "PASS" if all_f0_pass else "IN_PROGRESS"
        )
        all_f1_pass = all(
            state["functional_cases"].get(f"F1-{index:02d}") == "PASS"
            for index in range(1, 6)
        )
        openworker_f1_pass = state["functional_cases"].get("OPENWORKER-F1") == "PASS"
        if all_f1_pass and openworker_f1_pass:
            state["functional_gates"]["F1"] = "PASS"
        elif all_f1_pass:
            state["functional_gates"]["F1"] = "GENERIC_PASS_OPENWORKER_PENDING"
        elif any(key.startswith("F1-") for key in result["cases"]):
            state["functional_gates"]["F1"] = "IN_PROGRESS"
        state["primary_milestone"] = {
            "name": "MILAI_MCP_MEMORY_FUNCTIONAL",
            "status": (
                "PASS"
                if state["functional_gates"].get("F0") == "PASS"
                and state["functional_gates"].get("F1") == "PASS"
                else "IN_PROGRESS"
            ),
        }
        state["last_run_id"] = result["run_id"]
        state["updated_at"] = _now()
        _atomic_write(CURRENT_STATE, state)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_f0_package(run_id: str) -> dict[str, Any]:
    if _RUN_ID.fullmatch(run_id) is None:
        raise F0Error("run_id must be 8-96 lowercase URL-safe characters")
    run_dir = RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    trace: list[dict[str, Any]] = []
    code_identity = _tree_identity(
        [
            CLIENT_PROJECT / "src",
            MCP_PROJECT / "src",
            RUNTIME_PROJECT / "src",
            OPENWORKER_PROJECT / "src",
            MCP_HOST,
            Path(__file__).resolve(),
        ]
    )
    manifest = {
        "schema": "milai.dg10.functional-run-manifest.v1",
        "run_id": run_id,
        "phase": "functional_f0",
        "cases": ["F0-01", "F0-02"],
        "created_at": _now(),
        "code_identity": code_identity,
        "data_boundary": "SYNTHETIC_ONLY",
        "provider": None,
        "max_native_requests": 0,
        "closed_test_access": False,
        "development_ai_audits": 0,
    }
    _atomic_write(run_dir / "manifest.json", manifest)
    started = time.monotonic()
    status = "FAILED"
    error: str | None = None
    installs: dict[str, Any] = {}
    artifacts_payload: dict[str, Any] = {}
    try:
        artifacts = _build_packages(run_dir / "artifacts", trace)
        artifacts_payload = {
            name: {
                "path": path.relative_to(run_dir).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for name, path in artifacts.items()
        }
        with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
            temporary_root = Path(temporary).resolve()
            if temporary_root.is_relative_to(ROOT):
                raise F0Error(
                    "fresh-install workspace unexpectedly resides inside the repository"
                )
            installs["wheel"] = _probe_install(
                kind="wheel",
                client_artifact=artifacts["client_wheel"],
                mcp_artifact=artifacts["mcp_wheel"],
                runtime_artifact=artifacts["runtime_wheel"],
                openworker_artifact=artifacts["openworker_wheel"],
                workspace=temporary_root / "wheel",
                trace=trace,
            )
            installs["sdist"] = _probe_install(
                kind="sdist",
                client_artifact=artifacts["client_sdist"],
                mcp_artifact=artifacts["mcp_sdist"],
                runtime_artifact=artifacts["runtime_sdist"],
                openworker_artifact=artifacts["openworker_sdist"],
                workspace=temporary_root / "sdist",
                trace=trace,
            )
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    cases = {
        "F0-01": "PASS" if status == "PASS" else "FAILED",
        "F0-02": "PASS" if status == "PASS" else "FAILED",
    }
    result = {
        "schema": "milai.dg10.functional-run-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": cases,
        "artifacts": artifacts_payload,
        "fresh_installs": installs,
        "provider_requests": 0,
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "error": error,
        "finished_at": _now(),
    }
    _atomic_write(run_dir / "trace.json", {"commands": trace})
    _atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-02",
        "rm_ids": ["RM-02"],
        "hypothesis": (
            "fresh wheel and sdist expose identical native stdio MCP catalogs "
            "outside the repository"
        ),
        "code_identity": code_identity,
        "model_identity": None,
        "dataset_identity": "SYNTHETIC_NO_DATA",
        "prompt_identity": None,
        "budget": {"native_requests": 0},
        "expected_delta": "F0-01/F0-02 PASS",
        "functional_gate": "F0",
        "functional_cases_passed": [
            case for case, value in cases.items() if value == "PASS"
        ],
        "functional_cases_failed": [
            case for case, value in cases.items() if value != "PASS"
        ],
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
        "degraded_or_abstain_count": 0,
        "status": status,
    }
    _record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DG-10 F0-01/F0-02 without audit/candidate/receipt dependencies"
    )
    parser.add_argument(
        "--run-id",
        default=f"f0-package-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
    )
    args = parser.parse_args()
    result = run_f0_package(args.run_id)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "cases": result["cases"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
