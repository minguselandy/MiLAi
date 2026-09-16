from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "var/dg13/runs"
TMP_ROOT = ROOT / "var/dg13/tmp"
UDS_ROOT = Path("/dev/shm/milai")

PLAN_SCHEMA = "milai.dg13u.u1-recovery-resource-plan.v1"
RECEIPT_SCHEMA = "milai.dg13u.u1-recovery-cleanup-receipt.v1"
PLAN_NAME = "recovery-resource-plan.json"
RECEIPT_NAME = "recovery-cleanup-receipt.json"
RUN_LABEL = "io.milai.dg13u.run-id"

_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_DATABASE = re.compile(r"milai_smoke_dg13u_[0-9a-f]{20}")
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
_DOCKER_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,127}")
_MARKER = re.compile(r"[0-9]{1,32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PROCESS_ROLES = {"runtime-api", "runtime-worker", "mcp-broker", "host-adapter"}
_ALLOWED_KINDS = {
    "external_vllm",
    "temporary_root",
    "uds_root",
    "database",
    "docker_network",
    "docker_container",
    "process",
}


class CleanupError(RuntimeError):
    """A fail-closed recovery-plan or cleanup failure."""


class CleanupBackend(Protocol):
    def process_marker(self, pid: int) -> str | None: ...

    def docker_labels(self, kind: str, name: str) -> Mapping[str, str] | None: ...

    def database_owner(self, owner_dsn: str, database_name: str) -> str | None: ...

    def external_vllm_matches(self, origin: str, model_id: str) -> bool: ...

    def terminate_process(self, pid: int, marker: str) -> None: ...

    def remove_container(self, name: str) -> None: ...

    def remove_network(self, name: str) -> None: ...

    def drop_database(self, owner_dsn: str, database_name: str) -> None: ...

    def remove_directory(self, path: Path) -> None: ...


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8") + b"\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID.fullmatch(run_id) is None:
        raise CleanupError("run_id must contain 8-96 lowercase URL-safe characters")


def _short_run_id(run_id: str) -> str:
    return "u1-" + hashlib.sha256(run_id.encode()).hexdigest()[:16]


def _require_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise CleanupError(f"{label} must be absolute")
    return path


def _reject_symlink_chain(path: Path, *, include_leaf: bool = True) -> None:
    current = path if include_leaf else path.parent
    while True:
        if (current.exists() or current.is_symlink()) and current.is_symlink():
            raise CleanupError("symlink paths are forbidden")
        if current == current.parent:
            return
        current = current.parent


def _exact_child(path: Path, parent: Path, name: str, label: str) -> None:
    expected = parent / name
    if path != expected or path.resolve(strict=False) != expected.resolve(strict=False):
        raise CleanupError(f"{label} escapes its exact parent")


def _expect_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise CleanupError(f"{label} has missing or unknown fields")


def _validate_resource(resource: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    kind = resource.get("kind")
    if kind not in _ALLOWED_KINDS:
        raise CleanupError("resource kind is unknown")
    if kind == "external_vllm":
        _expect_keys(
            resource,
            {"kind", "ownership", "origin", "model_id", "identity_sha256"},
            kind,
        )
        if resource["ownership"] != "PRESERVED_EXTERNAL":
            raise CleanupError("external vLLM must be PRESERVED_EXTERNAL")
        origin = resource["origin"]
        model_id = resource["model_id"]
        if (
            not isinstance(origin, str)
            or not origin.startswith("http://127.0.0.1:")
            or "/" in origin.removeprefix("http://127.0.0.1:")
            or not isinstance(model_id, str)
            or not model_id
            or _HEX64.fullmatch(str(resource["identity_sha256"])) is None
        ):
            raise CleanupError("external vLLM identity is incomplete")
    elif kind in {"temporary_root", "uds_root"}:
        _expect_keys(resource, {"kind", "ownership", "path"}, kind)
        if resource["ownership"] != "RUN_OWNED":
            raise CleanupError("cleanup path must be RUN_OWNED")
        path = _require_absolute(Path(str(resource["path"])), kind)
        parent = TMP_ROOT if kind == "temporary_root" else UDS_ROOT
        name = run_id if kind == "temporary_root" else _short_run_id(run_id)
        _exact_child(path, parent, name, kind)
    elif kind == "database":
        _expect_keys(
            resource,
            {"kind", "ownership", "database_name", "owner_dsn_ref"},
            kind,
        )
        exact_database_name = (
            "milai_smoke_dg13u_" + hashlib.sha256(run_id.encode()).hexdigest()[:20]
        )
        if (
            resource["ownership"] != "RUN_OWNED"
            or _DATABASE.fullmatch(str(resource["database_name"])) is None
            or resource["database_name"] != exact_database_name
            or resource["owner_dsn_ref"] != "MILAI_MIGRATION_DATABASE_URL"
        ):
            raise CleanupError("database identity is incomplete")
    elif kind in {"docker_container", "docker_network"}:
        _expect_keys(resource, {"kind", "ownership", "name", "required_labels"}, kind)
        labels = resource["required_labels"]
        if (
            resource["ownership"] != "RUN_OWNED"
            or _DOCKER_NAME.fullmatch(str(resource["name"])) is None
            or labels != {RUN_LABEL: run_id}
        ):
            raise CleanupError("Docker ownership identity is incomplete")
    elif kind == "process":
        _expect_keys(
            resource,
            {"kind", "ownership", "role", "pid", "proc_start_marker"},
            kind,
        )
        pid = resource["pid"]
        if (
            resource["ownership"] != "RUN_OWNED"
            or not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 1
            or resource["role"] not in _PROCESS_ROLES
            or _MARKER.fullmatch(str(resource["proc_start_marker"])) is None
        ):
            raise CleanupError("process identity is incomplete")
    return dict(resource)


def _resource_key(resource: Mapping[str, Any]) -> tuple[str, str]:
    kind = str(resource["kind"])
    if kind == "process":
        return kind, str(resource["role"])
    if kind.startswith("docker_"):
        return kind, str(resource["name"])
    if kind == "database":
        return kind, str(resource["database_name"])
    if kind in {"temporary_root", "uds_root"}:
        return kind, str(resource["path"])
    return kind, str(resource["origin"])


def _validate_plan(value: object, *, expected_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CleanupError("resource plan must be an object")
    _expect_keys(value, {"schema", "run_id", "run_dir", "resources"}, "resource plan")
    if value["schema"] != PLAN_SCHEMA:
        raise CleanupError("resource plan schema is unsupported")
    run_id = str(value["run_id"])
    _validate_run_id(run_id)
    if expected_run_id is not None and run_id != expected_run_id:
        raise CleanupError("resource plan run_id mismatch")
    run_dir = _require_absolute(Path(str(value["run_dir"])), "run_dir")
    _exact_child(run_dir, RUNS_ROOT, run_id, "run_dir")
    resources_raw = value["resources"]
    if not isinstance(resources_raw, list) or not resources_raw:
        raise CleanupError("resource plan resources must be a non-empty list")
    resources: list[dict[str, Any]] = []
    keys: set[tuple[str, str]] = set()
    kind_counts = {kind: 0 for kind in _ALLOWED_KINDS}
    for raw in resources_raw:
        if not isinstance(raw, Mapping):
            raise CleanupError("resource entry must be an object")
        resource = _validate_resource(raw, run_id)
        key = _resource_key(resource)
        if key in keys:
            raise CleanupError("duplicate resource identity")
        keys.add(key)
        kind_counts[resource["kind"]] += 1
        resources.append(resource)
    for exact_kind in (
        "external_vllm",
        "temporary_root",
        "uds_root",
        "database",
        "docker_network",
        "docker_container",
    ):
        if kind_counts[exact_kind] != 1:
            raise CleanupError(f"plan must contain exactly one {exact_kind}")
    return {
        "schema": PLAN_SCHEMA,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "resources": resources,
    }


def _read_json_file(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    _require_absolute(path, label)
    _reject_symlink_chain(path)
    try:
        current = path.lstat()
    except OSError as exc:
        raise CleanupError(f"{label} is absent") from exc
    if not stat.S_ISREG(current.st_mode):
        raise CleanupError(f"{label} must be a regular file")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanupError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CleanupError(f"{label} must contain an object")
    return value, raw


def _atomic_private_write(path: Path, value: object, *, replace: bool) -> dict[str, Any]:
    _require_absolute(path, "output path")
    _reject_symlink_chain(path, include_leaf=False)
    if not path.parent.is_dir():
        raise CleanupError("output parent must already exist")
    if path.exists() and not replace:
        raise CleanupError("refusing to overwrite existing artifact")
    if path.is_symlink():
        raise CleanupError("symlink output is forbidden")
    payload = _canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if not replace:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise CleanupError("refusing to overwrite existing artifact") from exc
            temporary.unlink()
        else:
            os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"path": str(path), "sha256": _sha256_bytes(payload), "bytes": len(payload)}


def write_resource_plan(
    plan_path: Path,
    *,
    run_id: str,
    run_dir: Path,
    resources: Sequence[Mapping[str, Any]],
    expected_previous_sha256: str | None = None,
) -> dict[str, Any]:
    """Create or compare-and-swap one exact recovery plan.

    The initial call refuses an existing path. Updates require the exact digest
    returned by the preceding call, preventing blind plan overwrite.
    """

    _validate_run_id(run_id)
    plan_path = _require_absolute(plan_path, "plan_path")
    run_dir = _require_absolute(run_dir, "run_dir")
    _exact_child(run_dir, RUNS_ROOT, run_id, "run_dir")
    if plan_path != run_dir / PLAN_NAME:
        raise CleanupError("plan_path must be the exact run-owned plan path")
    plan = _validate_plan(
        {
            "schema": PLAN_SCHEMA,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "resources": [dict(resource) for resource in resources],
        },
        expected_run_id=run_id,
    )
    replacing = expected_previous_sha256 is not None
    if replacing:
        if _HEX64.fullmatch(expected_previous_sha256 or "") is None:
            raise CleanupError("expected_previous_sha256 is invalid")
        _, old_raw = _read_json_file(plan_path, "existing resource plan")
        if _sha256_bytes(old_raw) != expected_previous_sha256:
            raise CleanupError("resource plan compare-and-swap digest mismatch")
    elif plan_path.exists() or plan_path.is_symlink():
        raise CleanupError("refusing to overwrite existing resource plan")
    return _atomic_private_write(plan_path, plan, replace=replacing)


def _load_env_file(path: Path) -> dict[str, str]:
    _require_absolute(path, "env_file")
    _reject_symlink_chain(path)
    if not path.is_file():
        raise CleanupError("env_file must be a regular file")
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CleanupError("env_file is unreadable") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise CleanupError("env_file contains an invalid assignment")
        name, value = stripped.split("=", 1)
        if _ENV_NAME.fullmatch(name) is None or name in values:
            raise CleanupError("env_file contains an invalid or duplicate name")
        values[name] = value
    return values


def _validate_live_resources(
    plan: Mapping[str, Any], env: Mapping[str, str], backend: CleanupBackend
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], bool]]:
    checks: list[dict[str, Any]] = []
    present: dict[tuple[str, str], bool] = {}
    for resource in plan["resources"]:
        kind = resource["kind"]
        key = _resource_key(resource)
        exists = True
        if kind == "external_vllm":
            if not backend.external_vllm_matches(resource["origin"], resource["model_id"]):
                raise CleanupError("external vLLM identity mismatch")
            checks.append({"kind": kind, "state": "preserved_external_identity_verified"})
            present[key] = True
            continue
        if kind == "process":
            marker = backend.process_marker(resource["pid"])
            exists = marker is not None
            if exists and marker != resource["proc_start_marker"]:
                raise CleanupError("process start marker mismatch")
        elif kind in {"docker_container", "docker_network"}:
            docker_kind = kind.removeprefix("docker_")
            labels = backend.docker_labels(docker_kind, resource["name"])
            exists = labels is not None
            if exists and labels.get(RUN_LABEL) != plan["run_id"]:
                raise CleanupError("Docker run-id label mismatch")
        elif kind == "database":
            ref = resource["owner_dsn_ref"]
            owner_dsn = env.get(ref)
            if not owner_dsn:
                raise CleanupError("owner DSN reference is absent from env_file")
            owner = backend.database_owner(owner_dsn, resource["database_name"])
            exists = owner is not None
            if exists and owner != "milai_owner":
                raise CleanupError("database owner mismatch")
        elif kind in {"temporary_root", "uds_root"}:
            path = Path(resource["path"])
            _reject_symlink_chain(path)
            exists = path.exists()
            if exists and not path.is_dir():
                raise CleanupError("cleanup root is not a directory")
        present[key] = exists
        checks.append({"kind": kind, "state": "owned_present" if exists else "already_absent"})
    return checks, present


def cleanup_from_plan(
    plan_path: Path,
    *,
    run_id: str,
    env_file: Path,
    execute_local: bool,
    backend: CleanupBackend | None = None,
) -> dict[str, Any]:
    """Validate every identity, then clean run-owned resources in reverse order."""

    if not execute_local:
        raise CleanupError("cleanup requires explicit execute_local=True")
    _validate_run_id(run_id)
    plan_path = _require_absolute(plan_path, "plan_path")
    env_file = _require_absolute(env_file, "env_file")
    expected_plan_path = RUNS_ROOT / run_id / PLAN_NAME
    if (
        plan_path != expected_plan_path
        or plan_path.resolve(strict=False) != expected_plan_path.resolve(strict=False)
    ):
        raise CleanupError("plan_path must be the exact run-owned plan path")
    _reject_symlink_chain(plan_path)
    receipt_path = plan_path.parent / RECEIPT_NAME
    if receipt_path.exists() or receipt_path.is_symlink():
        raise CleanupError("refusing to overwrite existing cleanup receipt")
    selected_backend: CleanupBackend = backend or LocalCleanupBackend()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "run_id": run_id,
        "status": "FAIL",
        "phase": "preflight",
        "automatic_retries": 0,
        "external_lifecycle_mutations": 0,
        "items": [],
    }
    try:
        raw_plan, raw = _read_json_file(plan_path, "resource plan")
        plan = _validate_plan(raw_plan, expected_run_id=run_id)
        if plan_path != Path(plan["run_dir"]) / PLAN_NAME:
            raise CleanupError("plan_path does not match the plan run_dir")
        env = _load_env_file(env_file)
        checks, present = _validate_live_resources(plan, env, selected_backend)
        receipt["plan_sha256"] = _sha256_bytes(raw)
        receipt["preflight"] = checks
        receipt["phase"] = "cleanup"
        failed = False
        items: list[dict[str, Any]] = []
        for resource in reversed(plan["resources"]):
            kind = resource["kind"]
            key = _resource_key(resource)
            if kind == "external_vllm":
                items.append(
                    {
                        "kind": kind,
                        "ownership": "PRESERVED_EXTERNAL",
                        "state": "preserved_external",
                        "attempts": 0,
                    }
                )
                continue
            if not present[key]:
                items.append(
                    {
                        "kind": kind,
                        "ownership": "RUN_OWNED",
                        "state": "already_absent",
                        "attempts": 0,
                    }
                )
                continue
            state = "removed"
            row: dict[str, Any] = {
                "kind": kind,
                "ownership": "RUN_OWNED",
                "attempts": 1,
            }
            try:
                if kind == "process":
                    selected_backend.terminate_process(
                        resource["pid"], resource["proc_start_marker"]
                    )
                elif kind == "docker_container":
                    selected_backend.remove_container(resource["name"])
                elif kind == "docker_network":
                    selected_backend.remove_network(resource["name"])
                elif kind == "database":
                    selected_backend.drop_database(
                        env[resource["owner_dsn_ref"]], resource["database_name"]
                    )
                elif kind in {"temporary_root", "uds_root"}:
                    selected_backend.remove_directory(Path(resource["path"]))
            except Exception as exc:  # noqa: BLE001 - redacted typed receipt
                failed = True
                state = "cleanup_failed"
                row["error_type"] = type(exc).__name__
            row["state"] = state
            items.append(row)
        receipt["items"] = items
        receipt["status"] = "FAIL" if failed else "PASS"
        receipt["phase"] = "complete"
    except Exception as exc:  # noqa: BLE001 - emit a receipt for every bounded failure
        receipt["reason_code"] = "RECOVERY_PREFLIGHT_REJECTED"
        receipt["error_type"] = type(exc).__name__
    _atomic_private_write(receipt_path, receipt, replace=False)
    return receipt


class LocalCleanupBackend:
    """Bounded local implementation. Every destructive method issues one attempt."""

    def process_marker(self, pid: int) -> str | None:
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return None
        closing = raw.rfind(")")
        fields = raw[closing + 2 :].split() if closing >= 0 else []
        return fields[19] if len(fields) > 19 else None

    def docker_labels(self, kind: str, name: str) -> Mapping[str, str] | None:
        command = ["docker", "inspect", "--type", kind, name]
        completed = subprocess.run(command, capture_output=True, check=False, timeout=15)
        if completed.returncode != 0:
            return None
        try:
            value = json.loads(completed.stdout)
            labels = value[0]["Config" if kind == "container" else "Labels"]
            if kind == "container":
                labels = labels["Labels"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise CleanupError("Docker inspect response is invalid") from exc
        return dict(labels or {})

    def database_owner(self, owner_dsn: str, database_name: str) -> str | None:
        import psycopg

        with psycopg.connect(owner_dsn, autocommit=True, connect_timeout=5) as owner:
            role = owner.execute("SELECT current_user").fetchone()
            if role is None or role[0] != "milai_owner":
                raise CleanupError("owner DSN does not authenticate as milai_owner")
            row = owner.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                (database_name,),
            ).fetchone()
        return None if row is None else str(row[0])

    def external_vllm_matches(self, origin: str, model_id: str) -> bool:
        request = urllib.request.Request(origin + "/v1/models")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=3) as response:
                value = json.loads(response.read(1_048_577))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False
        rows = value.get("data") if isinstance(value, Mapping) else None
        return response.status == 200 and isinstance(rows, list) and any(
            isinstance(row, Mapping) and row.get("id") == model_id for row in rows
        )

    def terminate_process(self, pid: int, marker: str) -> None:
        if self.process_marker(pid) != marker:
            raise CleanupError("process marker changed after preflight")
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process_marker(pid) is None:
                return
            time.sleep(0.05)
        raise CleanupError("process did not exit after the single SIGTERM attempt")

    def remove_container(self, name: str) -> None:
        subprocess.run(
            ["docker", "rm", "-f", name], capture_output=True, check=True, timeout=30
        )

    def remove_network(self, name: str) -> None:
        subprocess.run(
            ["docker", "network", "rm", name],
            capture_output=True,
            check=True,
            timeout=30,
        )

    def drop_database(self, owner_dsn: str, database_name: str) -> None:
        import psycopg
        from psycopg import sql

        with psycopg.connect(owner_dsn, autocommit=True, connect_timeout=5) as owner:
            connections = owner.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            ).fetchone()
            if connections is None or int(connections[0]) != 0:
                raise CleanupError("database still has active connections")
            owner.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))

    def remove_directory(self, path: Path) -> None:
        shutil.rmtree(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DG13-U1 run-owned recovery cleanup")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute-local", action="store_true", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = cleanup_from_plan(
            args.plan,
            run_id=args.run_id,
            env_file=args.env_file,
            execute_local=args.execute_local,
        )
    except CleanupError as exc:
        print(f"dg13u_u1_cleanup: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
