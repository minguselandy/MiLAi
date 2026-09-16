from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "var/dg13/runs"
TMP_ROOT = ROOT / "var/dg13/tmp"
UV_BUILD_CACHE_SEED = ROOT / "var/dg13/cache/uv-build-seed"
CONTRACT = ROOT / "contracts/agent/v1/dg13u-u0-run.md"
PROVIDER_INVENTORY = ROOT / "contracts/agent/v1/dg13u-current-provider-inventory.md"
CANDIDATE_FIXTURE = ROOT / "contracts/agent/v1/dg13u-u1-candidate-fixture.json"
OPENWORKER_PROJECT = ROOT / "integrations/openworker-mcp"
OPENWORKER_IMAGE = "milai-openworker:dg13u-u0-current-local"
RUNTIME_PROJECT = ROOT / "runtime"
VLLM_BASE_URL = "http://127.0.0.1:7860"
VLLM_MODEL_ROOT = Path("/cra/qwen36-35B")

SUPPORTED_CASES = frozenset({"U0-IDENTITY-READINESS", "U0-CURRENT-PREFETCH"})
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_TRACE_STAGES = (
    "OPENWORKER",
    "ADAPTER_PARSE",
    "TASK",
    "NEED",
    "UDS",
    "MCP_HANDLER",
    "RUNTIME",
    "CANONICAL_GATE",
    "CONTEXT_COMPILE",
    "PROVIDER",
    "RECONCILIATION",
    "CLEANUP",
)
_IDENTITY_NOT_RUN = {
    "TASK",
    "NEED",
    "UDS",
    "MCP_HANDLER",
    "CANONICAL_GATE",
    "CONTEXT_COMPILE",
}
_SOURCE_INPUTS = (
    "integrations/python-client/pyproject.toml",
    "integrations/python-client/uv.lock",
    "integrations/python-client/src",
    "integrations/mcp/pyproject.toml",
    "integrations/mcp/uv.lock",
    "integrations/mcp/src",
    "integrations/openworker-mcp/pyproject.toml",
    "integrations/openworker-mcp/uv.lock",
    "integrations/openworker-mcp/src",
    "integrations/openworker-mcp/openworker",
    "integrations/openworker-mcp/policy",
    "integrations/openworker-mcp/broker/milai_mcp_broker.py",
    "integrations/openworker-mcp/relay/milai_mcp_relay.py",
    "runtime/pyproject.toml",
    "runtime/uv.lock",
    "runtime/src",
    "runtime/migrations",
    "evals/agent_integration/mcp_host.py",
    "contracts/agent/v1/dg13u-u0-run.md",
    "contracts/agent/v1/dg13u-current-provider-inventory.md",
    "contracts/agent/v1/dg13u-gateway-header-inspection.md",
    "contracts/agent/v1/dg13u-u1-candidate-fixture.json",
    "contracts/agent/v1/openworker-task-metadata-headers.md",
    "scripts/probe_dg13u_openworker_headers.py",
    "scripts/run_dg13u_openworker.py",
)
_IGNORED_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "dist"}
)
_MAX_COMMAND_OUTPUT = 1024 * 1024
_PACKAGE_PROJECTS = {
    "client": (ROOT / "integrations/python-client", "milai_client"),
    "mcp": (ROOT / "integrations/mcp", "milai_mcp"),
    "runtime": (ROOT / "runtime", "milai_runtime"),
    "openworker": (ROOT / "integrations/openworker-mcp", "milai_openworker_mcp"),
}
_EXPECTED_ENTRYPOINTS = {
    "milai-mcp": "milai_mcp.server:main",
    "milai-mcp-broker": "milai_openworker_mcp.broker:main",
    "milai-mcp-relay": "milai_openworker_mcp.relay:main",
    "milai-openworker-adapter": "milai_openworker_mcp.host_adapter:main",
}
_TASK_PRODUCER_MARKERS = (
    "chat.headers",
    "X-MiLAi-Host-Instance",
    "X-MiLAi-Task-Session",
    "X-MiLAi-Task-Operation",
    "sessionID",
    "message.id",
)
T = TypeVar("T")


class DG13URunnerError(RuntimeError):
    """A bounded operator-run failure."""


class DG13UBlocked(DG13URunnerError):
    """The current product cannot compose the selected real path."""


class DG13UNotRun(DG13URunnerError):
    """A typed readiness result prevented the case from starting."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _python_identity() -> dict[str, Any]:
    executable = Path(sys.executable).resolve()
    return {
        "implementation": sys.implementation.name,
        "version": list(sys.version_info[:3]),
        "executable": _file_identity(executable),
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_identity(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    current = path.lstat()
    if not stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode):
        raise DG13URunnerError(f"identity target is not a regular file: {path}")
    display = path.relative_to(relative_to).as_posix() if relative_to else str(path)
    return {"path": display, "bytes": current.st_size, "sha256": _sha256_file(path)}


def _directory_identity(path: Path) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink():
        raise DG13URunnerError(f"identity target is not a directory: {path}")
    rows: list[dict[str, Any]] = []
    for candidate in sorted(
        path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()
    ):
        relative = candidate.relative_to(path).as_posix()
        if candidate.is_symlink():
            rows.append(
                {"path": relative, "kind": "symlink", "target": os.readlink(candidate)}
            )
        elif candidate.is_file():
            rows.append({**_file_identity(candidate, relative_to=path), "kind": "file"})
    return {
        "path": str(path),
        "entry_count": len(rows),
        "sha256": _sha256_bytes(_canonical_bytes(rows)),
    }


def _atomic_write(path: Path, value: object) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _append_jsonl(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "ab") as handle:
        handle.write(_canonical_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _is_cra_path(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    return resolved == Path("/cra") or resolved.is_relative_to(Path("/cra"))


def _validate_selector(run_id: str, case_id: str) -> None:
    # Case validation intentionally precedes every filesystem and process action.
    if case_id not in SUPPORTED_CASES:
        raise DG13URunnerError(f"unsupported case_id: {case_id}")
    if _RUN_ID.fullmatch(run_id) is None:
        raise DG13URunnerError("run_id must be 8-96 lowercase URL-safe characters")
    _validate_python_version(sys.version_info[:2])


def _validate_python_version(version: tuple[int, int]) -> None:
    if not (3, 11) <= version < (3, 13):
        raise DG13URunnerError("runner requires Python >=3.11,<3.13")


def _prepare_paths(run_id: str) -> tuple[Path, Path]:
    expected_runs = ROOT / "var/dg13/runs"
    expected_tmp = ROOT / "var/dg13/tmp"
    if RUNS_ROOT.resolve(strict=False) != expected_runs.resolve(strict=False):
        raise DG13URunnerError("durable run root drift")
    if TMP_ROOT.resolve(strict=False) != expected_tmp.resolve(strict=False):
        raise DG13URunnerError("temporary run root drift")
    if not all(_is_cra_path(path) for path in (ROOT, RUNS_ROOT, TMP_ROOT)):
        raise DG13URunnerError("DG13U roots must reside on /cra")

    RUNS_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    TMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(RUNS_ROOT, 0o700)
    os.chmod(TMP_ROOT, 0o700)
    run_dir = RUNS_ROOT / run_id
    temp_dir = TMP_ROOT / run_id
    if run_dir.exists() or temp_dir.exists():
        raise DG13URunnerError(f"run_id already exists: {run_id}")
    try:
        temp_dir.mkdir(mode=0o700, exist_ok=False)
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except Exception:
        if temp_dir.exists() and not run_dir.exists():
            shutil.rmtree(temp_dir)
        raise
    os.chmod(run_dir, 0o700)
    os.chmod(temp_dir, 0o700)
    return run_dir, temp_dir


def _source_files() -> list[Path]:
    files: set[Path] = set()
    for relative in _SOURCE_INPUTS:
        target = ROOT / relative
        if target.is_file():
            files.add(target)
            continue
        if not target.is_dir():
            raise DG13URunnerError(f"source identity input absent: {relative}")
        for candidate in target.rglob("*"):
            if (
                candidate.is_file()
                and not candidate.is_symlink()
                and not _IGNORED_PARTS.intersection(candidate.parts)
                and candidate.suffix not in {".pyc", ".pyo"}
            ):
                files.add(candidate)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def _collect_source_identity() -> dict[str, Any]:
    entries = [_file_identity(path, relative_to=ROOT) for path in _source_files()]
    digest = hashlib.sha256()
    for entry in entries:
        relative = str(entry["path"]).encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(str(entry["sha256"])))
    runtime_entries = [
        entry for entry in entries if str(entry["path"]).startswith("runtime/")
    ]
    openworker_entries = [
        entry
        for entry in entries
        if str(entry["path"]).startswith("integrations/openworker-mcp/")
    ]
    return {
        "kind": "CONTENT_SHA256_NO_GIT_IDENTITY",
        "git_sha": None,
        "sha256": digest.hexdigest(),
        "file_count": len(entries),
        "total_bytes": sum(int(entry["bytes"]) for entry in entries),
        "entries": entries,
        "runtime_entries_sha256": _sha256_bytes(_canonical_bytes(runtime_entries)),
        "openworker_entries_sha256": _sha256_bytes(
            _canonical_bytes(openworker_entries)
        ),
    }


def _candidate_fixture_manifest() -> dict[str, Any]:
    try:
        value = json.loads(CANDIDATE_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG13URunnerError("candidate fixture is unreadable") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != "milai.dg13u.u1-candidate-fixture.v1"
        or value.get("status") != "U1_CANDIDATE_OWNER_ACCEPTANCE_REQUIRED"
        or not isinstance(value.get("families"), list)
        or len(value["families"]) != 3
    ):
        raise DG13URunnerError("candidate fixture contract is invalid")
    return {
        "kind": "CURRENT_PREFETCH_SINGLE_SYNTHETIC_CASE",
        "contract": _file_identity(CANDIDATE_FIXTURE, relative_to=ROOT),
        "schema": value["schema"],
        "status": value["status"],
        "families": value["families"],
    }


def _run_json(command: list[str], *, cwd: Path = ROOT, timeout: int = 30) -> Any:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DG13URunnerError(f"read-only command unavailable: {command[0]}") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout.encode()) > _MAX_COMMAND_OUTPUT
    ):
        raise DG13URunnerError(
            f"read-only command failed with status {completed.returncode}: {command[0]}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DG13URunnerError(
            f"read-only command returned invalid JSON: {command[0]}"
        ) from exc


def _run_command(
    command: list[str], *, cwd: Path = ROOT, timeout: int = 300
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DG13URunnerError(f"package command unavailable: {command[0]}") from exc
    if completed.returncode != 0:
        raise DG13URunnerError(
            f"package command failed with status {completed.returncode}: {command[0]}"
        )
    return {
        "argv_sha256": _sha256_bytes(_canonical_bytes(command)),
        "status": "PASS",
        "exit_code": 0,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "stdout_sha256": _sha256_bytes(completed.stdout.encode()),
        "stderr_sha256": _sha256_bytes(completed.stderr.encode()),
    }


@contextmanager
def _package_environment(temp_dir: Path) -> Iterator[dict[str, str]]:
    build_tmp = temp_dir / "build-tmp"
    uv_cache = temp_dir / "uv-cache"
    build_tmp.mkdir(mode=0o700)
    if not UV_BUILD_CACHE_SEED.is_dir() or UV_BUILD_CACHE_SEED.is_symlink():
        raise DG13URunnerError("offline UV build-cache seed is absent")
    shutil.copytree(UV_BUILD_CACHE_SEED, uv_cache, symlinks=True)
    os.chmod(uv_cache, 0o700)
    changes = {"TMPDIR": str(build_tmp), "UV_CACHE_DIR": str(uv_cache)}
    previous = {name: os.environ.get(name) for name in changes}
    os.environ.update(changes)
    try:
        yield changes
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _installed_identity(venv: Path) -> dict[str, Any]:
    python = venv / "bin/python"
    program = (
        "import importlib.metadata as m,json;"
        "names=['milai-client','milai-mcp','milai-openworker-mcp','milai-runtime'];"
        "ds={n:m.distribution(n) for n in names};"
        "print(json.dumps({'distributions':{n:{'version':d.version,"
        "'metadata':str(d.locate_file(next(f for f in d.files if "
        "str(f).endswith('.dist-info/METADATA')))),'root':str(d.locate_file(''))}"
        " for n,d in ds.items()},'entrypoints':{e.name:e.value for d in ds.values()"
        " for e in d.entry_points if e.group=='console_scripts'}}))"
    )
    value = _run_json([str(python), "-I", "-c", program], cwd=venv)
    if not isinstance(value, dict):
        raise DG13URunnerError("installed identity response is not an object")
    venv_root = venv.resolve()
    distributions: dict[str, Any] = {}
    for name, row in dict(value.get("distributions") or {}).items():
        if not isinstance(row, dict):
            raise DG13URunnerError(
                f"installed distribution identity is invalid: {name}"
            )
        metadata = Path(str(row.get("metadata"))).resolve()
        root = Path(str(row.get("root"))).resolve()
        if not metadata.is_relative_to(venv_root) or not root.is_relative_to(venv_root):
            raise DG13URunnerError(f"installed distribution escaped fresh venv: {name}")
        distributions[name] = {
            "version": row.get("version"),
            "root": str(root),
            "metadata": _file_identity(metadata),
        }
    entrypoint_values = dict(value.get("entrypoints") or {})
    if any(
        entrypoint_values.get(name) != expected
        for name, expected in _EXPECTED_ENTRYPOINTS.items()
    ):
        raise DG13URunnerError("installed console-script mapping drift")
    entrypoints: dict[str, Any] = {}
    for name, expected in _EXPECTED_ENTRYPOINTS.items():
        executable = venv / "bin" / name
        entrypoints[name] = {**_file_identity(executable), "value": expected}
    return {
        "inspection": "IMPORTLIB_METADATA_ONLY_NO_PRODUCT_MODULE_IMPORT",
        "distributions": distributions,
        "entrypoints": entrypoints,
    }


def _one_artifact(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise DG13URunnerError(
            f"expected exactly one {pattern} in current build output, found {len(matches)}"
        )
    return matches[0]


def _archive_files(path: Path) -> list[tuple[str, bytes]]:
    rows: list[tuple[str, bytes]] = []
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise DG13URunnerError("wheel contains an unsafe member path")
                if info.is_dir():
                    continue
                rows.append((info.filename, archive.read(info)))
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, mode="r:gz") as archive:
            for info in sorted(archive.getmembers(), key=lambda item: item.name):
                member = Path(info.name)
                if member.is_absolute() or ".." in member.parts:
                    raise DG13URunnerError("sdist contains an unsafe member path")
                if info.isdir():
                    continue
                if not info.isfile():
                    raise DG13URunnerError("sdist contains a non-regular member")
                extracted = archive.extractfile(info)
                if extracted is None:
                    raise DG13URunnerError("sdist member cannot be inspected")
                rows.append((info.name, extracted.read()))
    else:
        raise DG13URunnerError("unsupported package archive")
    if not rows:
        raise DG13URunnerError("package archive is empty")
    return rows


def _archive_identity(path: Path) -> dict[str, Any]:
    files = _archive_files(path)
    members = [
        {"path": name, "bytes": len(raw), "sha256": _sha256_bytes(raw)}
        for name, raw in files
    ]
    return {
        "member_count": len(members),
        "member_bytes": sum(int(row["bytes"]) for row in members),
        "members_sha256": _sha256_bytes(_canonical_bytes(members)),
        "member_names": [name for name, _raw in files],
    }


def _archive_member_identity(path: Path, suffix: str) -> dict[str, Any]:
    matches = [
        (name, raw) for name, raw in _archive_files(path) if name.endswith(suffix)
    ]
    if len(matches) != 1:
        raise DG13URunnerError(f"expected one package member ending {suffix}")
    name, raw = matches[0]
    return {"path": name, "bytes": len(raw), "sha256": _sha256_bytes(raw)}


def _task_producer_readiness(
    plugin: Path, entrypoint: Path, config: Path
) -> dict[str, Any]:
    paths = {"plugin": plugin, "entrypoint": entrypoint, "config": config}
    identities = {name: _file_identity(path) for name, path in paths.items()}
    contents = {name: path.read_bytes() for name, path in paths.items()}
    marker_presence = {
        marker: sorted(
            name for name, raw in contents.items() if marker.encode("utf-8") in raw
        )
        for marker in _TASK_PRODUCER_MARKERS
    }
    observed = sum(bool(locations) for locations in marker_presence.values())
    header_markers = _TASK_PRODUCER_MARKERS[1:4]
    has_producer_surface = bool(marker_presence["chat.headers"]) or any(
        marker_presence[marker] for marker in header_markers
    )
    if observed == len(_TASK_PRODUCER_MARKERS):
        status = "READY"
    elif not has_producer_surface:
        status = "ABSENT"
    else:
        status = "PARTIAL"
    evidence = {
        "rule": "ALL_CANDIDATE_HEADER_CONTRACT_AND_NATIVE_HOOK_MARKERS_PRESENT_IN_BAKED_PRODUCER_SURFACE",
        "files": identities,
        "marker_presence": marker_presence,
        "status": status,
    }
    return {
        "status": status,
        "observed_marker_count": observed,
        "required_marker_count": len(_TASK_PRODUCER_MARKERS),
        "marker_presence": marker_presence,
        "file_identities": identities,
        "native_evidence_sha256": _sha256_bytes(_canonical_bytes(evidence)),
        "provider_calls": 0,
    }


def _inspect_baked_openworker(
    run_id: str, run_dir: Path, temp_dir: Path, openworker_wheel: Path
) -> dict[str, Any]:
    container_name = f"milai-dg13u-inspect-{_sha256_bytes(run_id.encode())[:16]}"
    baked_root = temp_dir / "baked-openworker"
    baked_root.mkdir(mode=0o700)
    relay = baked_root / "milai-mcp-relay"
    config = baked_root / "opencode.json"
    plugin = baked_root / "openworker.js"
    entrypoint = baked_root / "entrypoint.sh"
    created = False
    removed = False
    failure: Exception | None = None
    cleanup_failure: Exception | None = None
    try:
        _run_command(
            [
                "docker",
                "create",
                "--name",
                container_name,
                "--network",
                "none",
                "--label",
                f"io.milai.dg13u.run-id={run_id}",
                "--entrypoint",
                "/bin/true",
                OPENWORKER_IMAGE,
            ]
        )
        created = True
        _run_command(
            [
                "docker",
                "cp",
                f"{container_name}:/usr/local/bin/milai-mcp-relay",
                str(relay),
            ]
        )
        _run_command(
            [
                "docker",
                "cp",
                f"{container_name}:/openworker/image/config/opencode.json",
                str(config),
            ]
        )
        _run_command(
            [
                "docker",
                "cp",
                f"{container_name}:/openworker/image/plugins/openworker.js",
                str(plugin),
            ]
        )
        _run_command(
            [
                "docker",
                "cp",
                f"{container_name}:/openworker/image/entrypoint.sh",
                str(entrypoint),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - cleanup receipt must survive inspection failure
        failure = exc
    finally:
        if created:
            try:
                _run_command(["docker", "rm", "-f", container_name], timeout=30)
                removed = True
            except Exception as exc:  # noqa: BLE001 - preserve both probe and cleanup state
                cleanup_failure = exc
        _atomic_write(
            run_dir / "baked-inspection-receipt.json",
            {
                "schema": "milai.dg13u.baked-image-inspection-receipt.v1",
                "container_name_sha256": _sha256_bytes(container_name.encode()),
                "created": created,
                "started": False,
                "removed": removed,
                "probe_error_type": type(failure).__name__ if failure else None,
                "cleanup_error_type": (
                    type(cleanup_failure).__name__ if cleanup_failure else None
                ),
            },
        )
    if cleanup_failure is not None:
        raise DG13URunnerError(
            "baked-image inspection container cleanup failed"
        ) from cleanup_failure
    if failure is not None:
        raise failure
    baked_relay = _file_identity(relay)
    baked_config = _file_identity(config)
    source_relay = _file_identity(
        OPENWORKER_PROJECT / "src/milai_openworker_mcp/relay.py", relative_to=ROOT
    )
    source_config = _file_identity(
        OPENWORKER_PROJECT / "openworker/opencode.json", relative_to=ROOT
    )
    packaged_relay = _archive_member_identity(
        openworker_wheel, "milai_openworker_mcp/relay.py"
    )
    producer = _task_producer_readiness(plugin, entrypoint, config)
    relay_current = (
        baked_relay["sha256"] == source_relay["sha256"] == packaged_relay["sha256"]
    )
    config_current = baked_config["sha256"] == source_config["sha256"]
    return {
        "baked_relay": baked_relay,
        "baked_config": baked_config,
        "current_source_relay": source_relay,
        "current_packaged_relay": packaged_relay,
        "current_source_config": source_config,
        "task_producer": producer,
        "relation": {
            "relay": "CURRENT" if relay_current else "STALE",
            "config": "CURRENT" if config_current else "STALE",
            "status": "CURRENT" if relay_current and config_current else "STALE",
        },
        "inspection_container": {
            "name_sha256": _sha256_bytes(container_name.encode()),
            "created": created,
            "removed": removed,
            "started": False,
        },
    }


_REVISION = re.compile(
    rb'^revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE
)
_DOWN_REVISION = re.compile(
    rb'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:["\']([^"\']+)["\']|None)',
    re.MULTILINE,
)


def _migration_head_from_archive(path: Path) -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    for name, raw in _archive_files(path):
        if "/migrations/versions/" not in name and "/_migrations/versions/" not in name:
            continue
        revision = _REVISION.search(raw)
        down_revision = _DOWN_REVISION.search(raw)
        if revision is None or down_revision is None:
            raise DG13URunnerError(
                f"migration metadata absent in archive member: {name}"
            )
        revisions.add(revision.group(1).decode())
        if down_revision.group(1) is not None:
            parents.add(down_revision.group(1).decode())
    heads = revisions - parents
    if len(heads) != 1:
        raise DG13URunnerError("package migration head is not unique")
    return heads.pop()


def _build_and_probe_packages(run_dir: Path, temp_dir: Path) -> dict[str, Any]:

    package_dir = run_dir / "packages"
    package_dir.mkdir(mode=0o700)
    install_venv = temp_dir / "installed-wheel"
    command_receipts: list[dict[str, Any]] = []
    cache_seed_identity = _directory_identity(UV_BUILD_CACHE_SEED)
    with _package_environment(temp_dir) as build_environment:
        artifacts: dict[str, Path] = {}
        for name, (project, distribution) in _PACKAGE_PROJECTS.items():
            output = package_dir / name
            output.mkdir(mode=0o700)
            command_receipts.append(
                _run_command(
                    [
                        "uv",
                        "build",
                        "--offline",
                        str(project),
                        "--out-dir",
                        str(output),
                    ],
                    cwd=ROOT,
                )
            )
            artifacts[f"{name}_wheel"] = _one_artifact(output, f"{distribution}-*.whl")
            artifacts[f"{name}_sdist"] = _one_artifact(
                output, f"{distribution}-*.tar.gz"
            )
        command_receipts.append(
            _run_command(
                [
                    "uv",
                    "venv",
                    "--python",
                    str(RUNTIME_PROJECT / ".venv/bin/python"),
                    str(install_venv),
                ],
                cwd=temp_dir,
            )
        )
        command_receipts.append(
            _run_command(
                [
                    "uv",
                    "pip",
                    "install",
                    "--no-deps",
                    "--offline",
                    "--python",
                    str(install_venv / "bin/python"),
                    *(str(artifacts[f"{name}_wheel"]) for name in _PACKAGE_PROJECTS),
                ],
                cwd=temp_dir,
            )
        )
        installed = _installed_identity(install_venv)

    artifact_rows: dict[str, Any] = {}
    for name, path in artifacts.items():
        os.chmod(path, 0o600)
        os.chmod(path.parent, 0o700)
        artifact_rows[name] = {
            **_file_identity(path, relative_to=run_dir),
            "archive": _archive_identity(path),
        }
    wheel_head = _migration_head_from_archive(artifacts["runtime_wheel"])
    sdist_head = _migration_head_from_archive(artifacts["runtime_sdist"])
    if wheel_head != sdist_head:
        raise DG13URunnerError("wheel and sdist migration heads differ")
    openworker_names = set(artifact_rows["openworker_wheel"]["archive"]["member_names"])
    for required in (
        "milai_openworker_mcp/host_adapter.py",
        "milai_openworker_mcp/broker.py",
        "milai_openworker_mcp/relay.py",
    ):
        if not any(name.endswith(required) for name in openworker_names):
            raise DG13URunnerError(f"current OpenWorker wheel lacks {required}")
    if any(
        name.endswith("milai_openworker_mcp/adapter.py") for name in openworker_names
    ):
        raise DG13URunnerError(
            "current OpenWorker wheel contains excluded legacy adapter"
        )
    return {
        "build_environment": {
            "TMPDIR": str(temp_dir / "build-tmp"),
            "UV_CACHE_DIR": str(temp_dir / "uv-cache"),
            "on_cra": all(
                _is_cra_path(Path(path)) for path in build_environment.values()
            ),
            "offline_cache_seed": cache_seed_identity,
        },
        "artifacts": artifact_rows,
        "fresh_wheel_install": installed,
        "install_policy": "UV_PIP_INSTALL_NO_DEPS",
        "migration_head": wheel_head,
        "command_receipts": command_receipts,
    }


def _probe_openworker(
    package_identity: dict[str, Any], run_id: str, run_dir: Path, temp_dir: Path
) -> dict[str, Any]:
    inspected = _run_json(["docker", "image", "inspect", OPENWORKER_IMAGE])
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise DG13URunnerError("OpenWorker image identity is ambiguous")
    image = inspected[0]
    if not isinstance(image, dict) or not isinstance(image.get("Id"), str):
        raise DG13URunnerError("OpenWorker image identity is incomplete")
    files = {
        "dockerfile": OPENWORKER_PROJECT / "openworker/Dockerfile",
        "opencode_config": OPENWORKER_PROJECT / "openworker/opencode.json",
        "relay_source": OPENWORKER_PROJECT / "src/milai_openworker_mcp/relay.py",
        "broker_source": OPENWORKER_PROJECT / "src/milai_openworker_mcp/broker.py",
        "mcp_host_source": ROOT / "evals/agent_integration/mcp_host.py",
    }
    installed = package_identity["fresh_wheel_install"]
    openworker_wheel = (
        run_dir / package_identity["artifacts"]["openworker_wheel"]["path"]
    )
    baked = _inspect_baked_openworker(run_id, run_dir, temp_dir, openworker_wheel)
    return {
        "image": {
            "reference": OPENWORKER_IMAGE,
            "id": image["Id"],
            "repo_digests": sorted(image.get("RepoDigests") or []),
            "created": image.get("Created"),
            "architecture": image.get("Architecture"),
            "os": image.get("Os"),
            "config_sha256": _sha256_bytes(_canonical_bytes(image.get("Config") or {})),
        },
        "source_files": {
            name: _file_identity(path, relative_to=ROOT) for name, path in files.items()
        },
        "installed_executables": installed["entrypoints"],
        "installed_distributions": installed["distributions"],
        "baked_composition": baked,
        "lifecycle_mutated": False,
    }


def _runtime_processes() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["ps", "-eo", "pid=,lstart=,etimes=,args="],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise DG13URunnerError("Runtime process inspection failed")
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if not ("/milai-api" in line or "/milai-worker" in line):
            continue
        parts = line.strip().split(None, 8)
        if len(parts) != 9:
            continue
        rows.append(
            {
                "pid": int(parts[0]),
                "started_at_ps": " ".join(parts[1:6]),
                "elapsed_seconds": int(parts[6]),
                "executable": parts[7],
                "argv_sha256": _sha256_bytes(parts[8].encode()),
                "ownership": "PRESERVED_EXTERNAL",
            }
        )
    return sorted(rows, key=lambda row: int(row["pid"]))


def _probe_runtime(package_identity: dict[str, Any]) -> dict[str, Any]:
    executable = RUNTIME_PROJECT / ".venv/bin/milai-ops"
    status = _run_json(
        [
            str(executable),
            "status",
            "--json",
            "--env-file",
            str(RUNTIME_PROJECT / ".env"),
        ],
        cwd=RUNTIME_PROJECT,
    )
    doctor = _run_json(
        [
            str(executable),
            "doctor",
            "--json",
            "--env-file",
            str(RUNTIME_PROJECT / ".env"),
        ],
        cwd=RUNTIME_PROJECT,
    )
    checks = doctor.get("checks") if isinstance(doctor, dict) else None
    if status.get("status") != "PASS" or not isinstance(checks, list):
        raise DG13URunnerError("Runtime readiness response is incomplete")
    alembic = next(
        (
            row
            for row in checks
            if isinstance(row, dict) and row.get("name") == "alembic"
        ),
        None,
    )
    if not isinstance(alembic, dict) or alembic.get("status") != "PASS":
        raise DG13URunnerError("Runtime migration readiness failed")
    migration_facts = alembic.get("facts")
    if not isinstance(migration_facts, dict):
        raise DG13URunnerError("Runtime migration facts are absent")
    packaged_head = package_identity["migration_head"]
    if (
        migration_facts.get("head") != packaged_head
        or migration_facts.get("current") != packaged_head
    ):
        raise DG13URunnerError("live Runtime migration differs from current package")
    processes = _runtime_processes()
    if not processes:
        raise DG13URunnerError("Runtime API/worker process identity is absent")
    return {
        "status": status,
        "doctor_status": doctor.get("status"),
        "migration": {
            "current": migration_facts.get("current"),
            "head": migration_facts.get("head"),
            "packaged_head": packaged_head,
        },
        "processes": processes,
        "lifecycle_mutated": False,
    }


def _probe_vllm() -> dict[str, Any]:
    eval_directory = ROOT / "evals/agent_efficiency"
    if str(eval_directory) not in sys.path:
        sys.path.insert(0, str(eval_directory))
    import vllm_local_identity as identity

    containers = _probe_vllm_container_rows()
    if len(containers) != 1 or not isinstance(containers[0], dict):
        raise DG13URunnerError("expected exactly one running vLLM container")
    container_id = str(containers[0].get("ID") or containers[0].get("Id") or "")
    if not container_id:
        raise DG13URunnerError("vLLM container ID is absent")
    inspected = _run_json(["docker", "container", "inspect", container_id])
    if (
        not isinstance(inspected, list)
        or len(inspected) != 1
        or not isinstance(inspected[0], dict)
        or not isinstance(inspected[0].get("Id"), str)
    ):
        raise DG13URunnerError("vLLM full container identity is absent")
    container_id = inspected[0]["Id"]
    binding = identity.collect_binding(
        container_id, VLLM_MODEL_ROOT.resolve(), VLLM_BASE_URL, progress=False
    )
    service = binding.get("service") or {}
    model = binding.get("model") or {}
    entries = model.get("entries") or []
    by_path = {row.get("path"): row for row in entries if isinstance(row, dict)}
    tokenizer = by_path.get("tokenizer.json")
    tokenizer_config = by_path.get("tokenizer_config.json")
    if not isinstance(tokenizer, dict) or not isinstance(tokenizer_config, dict):
        raise DG13URunnerError("tokenizer byte identity is absent from model closure")
    tokenizer_config_path = VLLM_MODEL_ROOT / "tokenizer_config.json"
    try:
        tokenizer_config_value = json.loads(tokenizer_config_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise DG13URunnerError("tokenizer config cannot be inspected") from exc
    template = tokenizer_config_value.get("chat_template")
    if not isinstance(template, str) or not template:
        raise DG13URunnerError("chat template is absent")
    return {
        "endpoint": VLLM_BASE_URL,
        "service": service,
        "container": binding.get("container"),
        "image": binding.get("image"),
        "model_byte_closure": {
            "host_path": model.get("host_path"),
            "file_count": model.get("file_count"),
            "total_bytes": model.get("total_bytes"),
            "entries_sha256": model.get("entries_sha256"),
        },
        "tokenizer": tokenizer,
        "tokenizer_config": tokenizer_config,
        "chat_template": {
            "bytes": len(template.encode("utf-8")),
            "sha256": _sha256_bytes(template.encode("utf-8")),
        },
        "read_only_http_get_count": 4,
        "completion_calls": 0,
        "lifecycle_mutated": False,
    }


def _probe_vllm_container_rows() -> list[dict[str, Any]]:
    completed = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--filter",
            "publish=7860",
            "--format",
            "{{json .}}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise DG13URunnerError("vLLM container lookup failed")
    try:
        rows = [
            json.loads(line) for line in completed.stdout.splitlines() if line.strip()
        ]
    except json.JSONDecodeError as exc:
        raise DG13URunnerError("vLLM container lookup returned invalid JSON") from exc
    return rows


def _trace_row(
    run_id: str,
    case_id: str,
    stage: str,
    status: str,
    reason_code: str,
    started_at: str,
    finished_at: str,
    duration_ms: float,
    *,
    output: object | None = None,
    native_identity: object | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": "milai.dg13u.stage-trace.v1",
        "run_id": run_id,
        "case_id": case_id,
        "stage": stage,
        "attempt": 1,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round(duration_ms, 3),
        "status": status,
        "reason_code": reason_code,
    }
    if output is not None:
        row["output_digest"] = _sha256_bytes(_canonical_bytes(output))
    if native_identity is not None:
        row["native_identity"] = native_identity
    return row


def _run_stage(
    trace_path: Path,
    run_id: str,
    case_id: str,
    stage: str,
    operation: Callable[[], T],
    reason_code: str,
) -> T:
    started_at = _now()
    started = time.monotonic()
    try:
        value = operation()
    except Exception as exc:
        finished_at = _now()
        failure_identity = {"error_type": type(exc).__name__}
        if isinstance(exc, DG13URunnerError):
            failure_identity["error_code"] = str(exc)
        _append_jsonl(
            trace_path,
            _trace_row(
                run_id,
                case_id,
                stage,
                "FAIL",
                f"{stage}_PROBE_FAILED",
                started_at,
                finished_at,
                (time.monotonic() - started) * 1000,
                native_identity=failure_identity,
            ),
        )
        raise
    finished_at = _now()
    _append_jsonl(
        trace_path,
        _trace_row(
            run_id,
            case_id,
            stage,
            "PASS",
            reason_code,
            started_at,
            finished_at,
            (time.monotonic() - started) * 1000,
            output=value,
        ),
    )
    return value


def _append_not_run(trace_path: Path, run_id: str, case_id: str, stage: str) -> None:
    observed = _now()
    _append_jsonl(
        trace_path,
        _trace_row(
            run_id,
            case_id,
            stage,
            "NOT_RUN",
            "IDENTITY_READINESS_ONLY",
            observed,
            observed,
            0.0,
        ),
    )


def _append_blocked(
    trace_path: Path, run_id: str, case_id: str, stage: str, reason_code: str
) -> None:
    observed = _now()
    _append_jsonl(
        trace_path,
        _trace_row(
            run_id,
            case_id,
            stage,
            "BLOCKED",
            reason_code,
            observed,
            observed,
            0.0,
        ),
    )


def _append_readiness_terminal(
    trace_path: Path,
    run_id: str,
    case_id: str,
    stage: str,
    status: str,
    reason_code: str,
    native_identity: dict[str, Any],
) -> None:
    observed = _now()
    _append_jsonl(
        trace_path,
        _trace_row(
            run_id,
            case_id,
            stage,
            status,
            reason_code,
            observed,
            observed,
            0.0,
            native_identity=native_identity,
        ),
    )


def _write_blocked_provider_receipts(
    run_dir: Path,
    run_id: str,
    case_id: str,
    reason_code: str,
    terminal_status: str,
) -> None:
    _atomic_write(
        run_dir / "provider-capability.json",
        {
            "schema": "milai.dg13u.provider-capability.v1",
            "run_id": run_id,
            "case_id": case_id,
            "provider": "existing_local_vllm",
            "endpoint": VLLM_BASE_URL,
            "maximum_completion_calls": 1,
            "automatic_retries": 0,
            "status": f"{terminal_status}_BEFORE_CALL",
            "reason_code": reason_code,
        },
    )
    _append_jsonl(
        run_dir / "provider-ledger.jsonl",
        {
            "schema": "milai.dg13u.provider-ledger.v1",
            "run_id": run_id,
            "case_id": case_id,
            "attempt": 0,
            "request_issued": False,
            "provider_native_request_id": None,
            "terminal": "NOT_ISSUED_READINESS_TERMINAL",
            "reason_code": reason_code,
        },
    )


def _read_trace_stages(trace_path: Path) -> set[str]:
    if not trace_path.exists():
        return set()
    return {
        str(json.loads(line)["stage"])
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _artifact_index(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in sorted(
        (path for path in run_dir.rglob("*") if path.is_dir()), reverse=True
    ):
        os.chmod(directory, 0o700)
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "report.json":
            continue
        os.chmod(path, 0o600)
        rows.append(_file_identity(path, relative_to=run_dir))
    return rows


def _cleanup(
    run_dir: Path,
    temp_dir: Path,
    runtime: dict[str, Any] | None,
    vllm: dict[str, Any] | None,
    openworker: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = temp_dir.resolve(strict=False)
    expected_parent = TMP_ROOT.resolve(strict=False)
    if resolved.parent != expected_parent or not _is_cra_path(resolved):
        raise DG13URunnerError("refusing cleanup outside the exact run-owned temp root")
    items: list[dict[str, Any]] = [
        {"kind": kind, "identity": None, "state": "not_created"}
        for kind in (
            "pid",
            "network",
            "database",
            "socket",
            "port",
            "ledger",
        )
    ]
    if resolved.exists():
        shutil.rmtree(resolved)
    items.append(
        {"kind": "temporary_path", "identity": str(resolved), "state": "removed"}
    )
    for process in (runtime or {}).get("processes", []):
        items.append(
            {
                "kind": "runtime_process",
                "identity": {"pid": process.get("pid")},
                "state": "preserved_external",
            }
        )
    container = (vllm or {}).get("container") or {}
    items.append(
        {
            "kind": "vllm",
            "identity": {
                "endpoint": VLLM_BASE_URL,
                "container_id": container.get("id"),
            },
            "state": "preserved_external",
        }
    )
    inspection = ((openworker or {}).get("baked_composition") or {}).get(
        "inspection_container"
    ) or {}
    receipt_path = run_dir / "baked-inspection-receipt.json"
    receipt: dict[str, Any] | None = None
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        inspection = {
            "name_sha256": receipt.get("container_name_sha256"),
            "created": receipt.get("created"),
            "removed": receipt.get("removed"),
        }
    retry = {"attempted": False, "status": "NOT_NEEDED"}
    inspection_invalid = inspection.get("created") not in (True, False) or (
        inspection.get("created") is True
        and inspection.get("removed") not in (True, False)
    )
    if inspection.get("created") is True and inspection.get("removed") is not True:
        container_name = (
            f"milai-dg13u-inspect-{_sha256_bytes(run_dir.name.encode())[:16]}"
        )
        expected_name_sha256 = _sha256_bytes(container_name.encode())
        retry = {"attempted": True, "status": "FAIL"}
        if inspection.get("name_sha256") == expected_name_sha256:
            try:
                _run_command(["docker", "rm", "-f", container_name], timeout=30)
                inspection["removed"] = True
                retry["status"] = "PASS"
            except Exception as exc:  # noqa: BLE001 - final receipt retains type only
                retry["error_type"] = type(exc).__name__
        else:
            retry["error_type"] = "IDENTITY_MISMATCH"
        if receipt is not None:
            receipt["cleanup_retry"] = retry
            receipt["removed"] = inspection.get("removed") is True
            _atomic_write(receipt_path, receipt)
    inspection_failed = inspection_invalid or (
        inspection.get("created") is True and inspection.get("removed") is not True
    )
    if inspection.get("created") is True:
        items.append(
            {
                "kind": "container",
                "identity": {"name_sha256": inspection.get("name_sha256")},
                "state": "removed" if not inspection_failed else "cleanup_failed",
                "retry": retry,
            }
        )
    else:
        items.append({"kind": "container", "identity": None, "state": "not_created"})
    return {
        "schema": "milai.dg13u.cleanup-receipt.v1",
        "finished_at": _now(),
        "items": items,
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
        "status": "FAIL" if inspection_failed else "PASS",
        "reason_code": (
            "INSPECTION_CONTAINER_CLEANUP_FAILED"
            if inspection_failed
            else "OWNED_RESOURCES_RECONCILED"
        ),
    }


def run_identity_readiness(run_id: str, case_id: str) -> dict[str, Any]:
    _validate_selector(run_id, case_id)
    run_dir, temp_dir = _prepare_paths(run_id)
    trace_path = run_dir / "stage-trace.jsonl"
    started_at = _now()
    observed_stages: set[str] = set()
    source: dict[str, Any] | None = None
    packages: dict[str, Any] | None = None
    openworker: dict[str, Any] | None = None
    runtime: dict[str, Any] | None = None
    vllm: dict[str, Any] | None = None
    error: Exception | None = None
    pre_report_error: Exception | None = None
    cleanup_error: Exception | None = None

    try:

        def openworker_preflight() -> dict[str, Any]:
            nonlocal source
            source = _collect_source_identity()
            return {"source_sha256": source["sha256"], "git_sha": None}

        _run_stage(
            trace_path,
            run_id,
            case_id,
            "OPENWORKER",
            openworker_preflight,
            "SOURCE_CONTENT_IDENTITY_CAPTURED",
        )
        observed_stages.add("OPENWORKER")

        def package_and_openworker_probe() -> dict[str, Any]:
            nonlocal packages, openworker
            packages = _build_and_probe_packages(run_dir, temp_dir)
            openworker = _probe_openworker(packages, run_id, run_dir, temp_dir)
            return packages

        packages = _run_stage(
            trace_path,
            run_id,
            case_id,
            "ADAPTER_PARSE",
            package_and_openworker_probe,
            "CURRENT_WHEEL_SDIST_AND_ENTRYPOINTS_VERIFIED",
        )
        observed_stages.add("ADAPTER_PARSE")

        if case_id == "U0-CURRENT-PREFETCH":
            composition = (openworker or {}).get("baked_composition") or {}
            relation = composition.get("relation") or {}
            producer = composition.get("task_producer") or {}
            producer_status = producer.get("status")
            if relation.get("status") != "CURRENT":
                terminal_status = "FAIL"
                reason_code = "CURRENT_IMAGE_COMPOSITION_STALE"
                exception: DG13URunnerError = DG13URunnerError(reason_code)
            elif producer_status == "ABSENT":
                terminal_status = "NOT_RUN"
                reason_code = "TASK_PRODUCER_ABSENT_OBSERVED"
                exception = DG13UNotRun(reason_code)
            elif producer_status == "PARTIAL":
                terminal_status = "FAIL"
                reason_code = "TASK_PRODUCER_PARTIAL_INVALID"
                exception = DG13URunnerError(reason_code)
            elif producer_status == "READY":
                terminal_status = "NOT_RUN"
                reason_code = "WAITING_OWNER_ACCEPTANCE"
                exception = DG13UNotRun(reason_code)
            else:
                terminal_status = "FAIL"
                reason_code = "TASK_PRODUCER_EVIDENCE_INVALID"
                exception = DG13URunnerError(reason_code)
            native_identity = {
                "composition_status": relation.get("status"),
                "composition_sha256": _sha256_bytes(_canonical_bytes(relation)),
                "task_producer_status": producer_status,
                "task_producer_native_evidence_sha256": producer.get(
                    "native_evidence_sha256"
                ),
            }
            _write_blocked_provider_receipts(
                run_dir,
                run_id,
                case_id,
                reason_code,
                terminal_status,
            )
            _append_readiness_terminal(
                trace_path,
                run_id,
                case_id,
                "TASK",
                terminal_status,
                reason_code,
                native_identity,
            )
            observed_stages.add("TASK")
            raise exception

        for stage in ("TASK", "NEED", "UDS", "MCP_HANDLER"):
            _append_not_run(trace_path, run_id, case_id, stage)
            observed_stages.add(stage)

        runtime = _run_stage(
            trace_path,
            run_id,
            case_id,
            "RUNTIME",
            lambda: _probe_runtime(packages),
            "LIVE_RUNTIME_AND_MIGRATION_READY",
        )
        observed_stages.add("RUNTIME")
        for stage in ("CANONICAL_GATE", "CONTEXT_COMPILE"):
            _append_not_run(trace_path, run_id, case_id, stage)
            observed_stages.add(stage)

        # The provider stage performs GET/inspect/hash only. It never calls completion/tokenize.
        vllm = _run_stage(
            trace_path,
            run_id,
            case_id,
            "PROVIDER",
            _probe_vllm,
            "READ_ONLY_VLLM_IDENTITY_NO_COMPLETION",
        )
        observed_stages.add("PROVIDER")

        assert source is not None and packages is not None
        fixture_contract = {"case_id": case_id, "kind": "IDENTITY_ONLY_NO_FIXTURE"}
        request_contract = {
            "case_id": case_id,
            "completion_calls": 0,
            "tokenize_calls": 0,
            "retry_count": 0,
            "data_boundary": "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED",
        }
        manifest = {
            "schema": "milai.dg13u.run-manifest.v1",
            "run_id": run_id,
            "case_id": case_id,
            "created_at": started_at,
            "baseline_label": "DG13U_U0_CURRENT_BASELINE",
            "data_boundary": "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED",
            "formal_evaluation_input": False,
            "runner_python": _python_identity(),
            "source_content_identity": source,
            "packages": packages,
            "openworker": openworker,
            "runtime": {
                "source_entries_sha256": source["runtime_entries_sha256"],
                **runtime,
            },
            "vllm": vllm,
            "fixture": {
                "kind": fixture_contract["kind"],
                "sha256": _sha256_bytes(_canonical_bytes(fixture_contract)),
            },
            "request_contract": {
                "sha256": _sha256_bytes(_canonical_bytes(request_contract)),
                **request_contract,
                "deadlines_seconds": {"command": 300, "readiness": 30},
                "provider_call_ceiling": 0,
                "token_ceiling": 0,
                "retry_policy": "NO_RETRY",
            },
            "accepted_owner_decision_receipt_digest": None,
            "owner_acceptance": None,
            "u1_product_usable": False,
        }
        _atomic_write(run_dir / "manifest.json", manifest)

        # This is the identity-only smoke and deliberately follows the manifest write.
        current_source = _collect_source_identity()
        if current_source != source:
            raise DG13URunnerError(
                "source content changed during package/readiness probe"
            )

        readiness = {
            "schema": "milai.dg13u.readiness.v1",
            "run_id": run_id,
            "case_id": case_id,
            "status": "PASS",
            "combined_e2e": False,
            "components": {
                "runtime": {"expected": True, "status": "PASS", "identity": runtime},
                "vllm": {"expected": True, "status": "PASS", "identity": vllm},
                "openworker": {
                    "expected": False,
                    "status": "NOT_RUN",
                    "reason_code": "IDENTITY_ONLY_IMAGE_INSPECTED_NOT_STARTED",
                    "identity": openworker,
                },
                "broker": {
                    "expected": False,
                    "status": "NOT_RUN",
                    "reason_code": "IDENTITY_ONLY_NOT_STARTED",
                    "socket": None,
                    "child_catalog": None,
                },
                "adapter": {
                    "expected": False,
                    "status": "NOT_RUN",
                    "reason_code": "IDENTITY_ONLY_NOT_STARTED",
                    "health": None,
                },
            },
        }
        _atomic_write(run_dir / "readiness.json", readiness)
        reconciliation = {
            "schema": "milai.dg13u.join-reconciliation.v1",
            "run_id": run_id,
            "case_id": case_id,
            "status": "PASS",
            "reason_code": "IDENTITY_ONLY_NO_OPENWORKER_TURN",
            "expected_turns": 0,
            "turns": [],
            "expected_mcp_calls": 0,
            "observed_mcp_calls": 0,
            "unaccounted_mcp_calls": 0,
            "expected_provider_calls": 0,
            "observed_provider_calls": 0,
            "unaccounted_provider_calls": 0,
        }
        _atomic_write(run_dir / "join-reconciliation.json", reconciliation)
        _run_stage(
            trace_path,
            run_id,
            case_id,
            "RECONCILIATION",
            lambda: {
                "source_stable": True,
                "provider_calls": 0,
                "mcp_calls": 0,
                "turns": 0,
            },
            "IDENTITY_EXPECTATIONS_RECONCILED",
        )
        observed_stages.add("RECONCILIATION")
    except Exception as exc:  # noqa: BLE001 - terminal receipt must survive probe failure
        error = exc
    finally:
        observed_stages.update(_read_trace_stages(trace_path))
        for stage in _TRACE_STAGES[:-1]:
            if stage not in observed_stages:
                _append_not_run(trace_path, run_id, case_id, stage)
        if not (run_dir / "manifest.json").exists():
            if isinstance(error, DG13UNotRun):
                manifest_status = "NOT_RUN"
            elif isinstance(error, DG13UBlocked):
                manifest_status = "BLOCKED"
            elif case_id == "U0-CURRENT-PREFETCH":
                manifest_status = "FAIL"
            else:
                manifest_status = "INCOMPLETE"
            _atomic_write(
                run_dir / "manifest.json",
                {
                    "schema": "milai.dg13u.run-manifest.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "created_at": started_at,
                    "status": manifest_status,
                    "baseline_label": "DG13U_U0_CURRENT_BASELINE",
                    "data_boundary": "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED",
                    "formal_evaluation_input": False,
                    "runner_python": _python_identity(),
                    "source_content_identity": source,
                    "packages": packages,
                    "openworker": openworker,
                    "runtime": runtime,
                    "vllm": vllm,
                    "current_provider_inventory": _file_identity(PROVIDER_INVENTORY),
                    "fixture": (
                        _candidate_fixture_manifest()
                        if case_id == "U0-CURRENT-PREFETCH"
                        else {"kind": "IDENTITY_ONLY_NO_FIXTURE"}
                    ),
                    "request_contract": {
                        "provider_call_ceiling": 1
                        if case_id == "U0-CURRENT-PREFETCH"
                        else 0,
                        "retry_policy": "NO_RETRY",
                    },
                    "accepted_owner_decision_receipt_digest": None,
                    "owner_acceptance": None,
                    "u1_product_usable": False,
                },
            )
        if not (run_dir / "readiness.json").exists():
            if isinstance(error, DG13UNotRun):
                readiness_status = "NOT_RUN"
            elif isinstance(error, DG13UBlocked):
                readiness_status = "BLOCKED"
            else:
                readiness_status = "FAIL"
            _atomic_write(
                run_dir / "readiness.json",
                {
                    "schema": "milai.dg13u.readiness.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "status": readiness_status,
                    "combined_e2e": False,
                    "reason_code": str(error)
                    if isinstance(error, DG13URunnerError)
                    else "IDENTITY_READINESS_INCOMPLETE",
                },
            )
        if not (run_dir / "join-reconciliation.json").exists():
            if isinstance(error, DG13UNotRun):
                reconciliation_status = "NOT_RUN"
            elif isinstance(error, DG13UBlocked):
                reconciliation_status = "BLOCKED"
            else:
                reconciliation_status = "FAIL"
            _atomic_write(
                run_dir / "join-reconciliation.json",
                {
                    "schema": "milai.dg13u.join-reconciliation.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "status": reconciliation_status,
                    "reason_code": str(error)
                    if isinstance(error, DG13URunnerError)
                    else "RUN_FAILED_BEFORE_RECONCILIATION",
                    "expected_turns": 0,
                    "turns": [],
                    "expected_mcp_calls": 0,
                    "observed_mcp_calls": 0,
                    "unaccounted_mcp_calls": 0,
                    "expected_provider_calls": 0,
                    "observed_provider_calls": 0,
                    "unaccounted_provider_calls": 0,
                },
            )
        try:
            _atomic_write(
                run_dir / "report.json",
                {
                    "schema": "milai.dg13u.run-report.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "status": "PASS" if error is None else "FAIL",
                    "phase": "PRE_CLEANUP_TERMINAL_REPORT",
                    "baseline_label": "DG13U_U0_CURRENT_BASELINE",
                    "u1_product_usable": False,
                    "owner_acceptance": None,
                    "written_at": _now(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - cleanup must still run
            pre_report_error = exc
        cleanup_started_at = _now()
        cleanup_started = time.monotonic()
        try:
            cleanup = _cleanup(run_dir, temp_dir, runtime, vllm, openworker)
            cleanup_status = str(cleanup["status"])
            cleanup_reason = str(cleanup["reason_code"])
            if cleanup_status != "PASS":
                cleanup_error = DG13URunnerError(cleanup_reason)
        except Exception as exc:  # noqa: BLE001 - cleanup failure needs a receipt
            cleanup_error = exc
            cleanup = {
                "schema": "milai.dg13u.cleanup-receipt.v1",
                "finished_at": _now(),
                "items": [],
                "existing_vllm_preserved": True,
                "external_lifecycle_mutations": 0,
                "status": "FAIL",
                "reason_code": "CLEANUP_FAILED",
                "error_type": type(exc).__name__,
            }
            cleanup_status = "FAIL"
            cleanup_reason = "CLEANUP_FAILED"
        _append_jsonl(
            trace_path,
            _trace_row(
                run_id,
                case_id,
                "CLEANUP",
                cleanup_status,
                cleanup_reason,
                cleanup_started_at,
                _now(),
                (time.monotonic() - cleanup_started) * 1000,
                output=cleanup,
            ),
        )
        _atomic_write(run_dir / "cleanup-receipt.json", cleanup)

        if not (run_dir / "manifest.json").exists():
            _atomic_write(
                run_dir / "manifest.json",
                {
                    "schema": "milai.dg13u.run-manifest.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "created_at": started_at,
                    "status": "INCOMPLETE",
                    "runner_python": _python_identity(),
                    "source_content_identity": source,
                    "packages": packages,
                    "openworker": openworker,
                    "runtime": runtime,
                    "vllm": vllm,
                    "accepted_owner_decision_receipt_digest": None,
                    "owner_acceptance": None,
                    "u1_product_usable": False,
                },
            )
        if not (run_dir / "readiness.json").exists():
            _atomic_write(
                run_dir / "readiness.json",
                {
                    "schema": "milai.dg13u.readiness.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "status": "FAIL",
                    "combined_e2e": False,
                    "reason_code": "IDENTITY_READINESS_INCOMPLETE",
                },
            )
        if not (run_dir / "join-reconciliation.json").exists():
            _atomic_write(
                run_dir / "join-reconciliation.json",
                {
                    "schema": "milai.dg13u.join-reconciliation.v1",
                    "run_id": run_id,
                    "case_id": case_id,
                    "status": "FAIL",
                    "reason_code": "RUN_FAILED_BEFORE_RECONCILIATION",
                    "expected_turns": 0,
                    "turns": [],
                    "expected_mcp_calls": 0,
                    "observed_mcp_calls": 0,
                    "unaccounted_mcp_calls": 0,
                    "expected_provider_calls": 0,
                    "observed_provider_calls": 0,
                    "unaccounted_provider_calls": 0,
                },
            )

        if error is None and pre_report_error is None and cleanup_error is None:
            status = "PASS"
        elif (
            isinstance(error, DG13UNotRun)
            and pre_report_error is None
            and cleanup_error is None
        ):
            status = "NOT_RUN"
        elif (
            isinstance(error, DG13UBlocked)
            and pre_report_error is None
            and cleanup_error is None
        ):
            status = "BLOCKED"
        else:
            status = "FAIL"
        trace_rows = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latency = [float(row["duration_ms"]) for row in trace_rows]
        ordered = sorted(latency)

        def percentile(fraction: float) -> float | None:
            if not ordered:
                return None
            return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]

        report = {
            "schema": "milai.dg13u.run-report.v1",
            "run_id": run_id,
            "case_id": case_id,
            "status": status,
            "baseline_label": "DG13U_U0_CURRENT_BASELINE",
            "u1_product_usable": False,
            "owner_acceptance": None,
            "started_at": started_at,
            "finished_at": _now(),
            "terminal_stages": {
                "preflight": "PASS" if source is not None else "FAIL",
                "package": "PASS" if packages is not None else "NOT_RUN",
                "start": (
                    "NOT_RUN"
                    if isinstance(error, DG13UNotRun)
                    else "BLOCKED"
                    if isinstance(error, DG13UBlocked)
                    else "FAIL"
                    if case_id == "U0-CURRENT-PREFETCH" and error is not None
                    else "NOT_RUN"
                ),
                "readiness": "PASS"
                if runtime is not None and vllm is not None
                else "NOT_RUN",
                "smoke": "PASS" if error is None else "NOT_RUN",
                "report": "PASS" if pre_report_error is None else "FAIL",
                "cleanup": cleanup_status,
            },
            "stage_latency_ms": {
                "n": len(ordered),
                "p50": percentile(0.50),
                "p95": percentile(0.95),
                "p99": percentile(0.99),
            },
            "calls": {
                "mcp": {"expected": 0, "observed": 0, "unaccounted": 0},
                "provider": {
                    "expected": 0,
                    "maximum": 1 if case_id == "U0-CURRENT-PREFETCH" else 0,
                    "observed": 0,
                    "unaccounted": 0,
                },
            },
            "visible_memory_tool_events": 0,
            "correctness": {
                "passed": 0,
                "denominator": 0,
                "status": "NOT_RUN",
            },
            "error": (
                None
                if error is None and pre_report_error is None and cleanup_error is None
                else {
                    "type": type(error or pre_report_error or cleanup_error).__name__,
                    "code": (
                        str(error or pre_report_error or cleanup_error)
                        if isinstance(
                            error or pre_report_error or cleanup_error,
                            DG13URunnerError,
                        )
                        else None
                    ),
                    "message_sha256": _sha256_bytes(
                        str(error or pre_report_error or cleanup_error).encode()
                    ),
                }
            ),
            "known_gaps": [
                (
                    "Current-prefetch stops before provider on an observed image-composition "
                    "failure, typed producer ABSENT/PARTIAL result, or pending owner acceptance."
                    if case_id == "U0-CURRENT-PREFETCH"
                    else "U0-CURRENT-PREFETCH has a separate fail-closed composition selector."
                ),
                "Identity/readiness PASS is not a combined OpenWorker/MCP E2E result.",
                "U1 product behavior and owner acceptance remain false/null.",
            ],
            "artifacts": _artifact_index(run_dir),
        }
        _atomic_write(run_dir / "report.json", report)
    return report


def run_case(run_id: str, case_id: str) -> dict[str, Any]:
    return run_identity_readiness(run_id, case_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one DG13U OpenWorker U0 case")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    try:
        report = run_identity_readiness(args.run_id, args.case_id)
    except DG13URunnerError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
