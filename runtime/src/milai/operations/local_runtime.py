from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from alembic import command

from milai.config import SettingsError, load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations.migrations import alembic_config
from milai.operations.smoke import run_isolated_smoke
from milai.persistence import Database

_RUNTIME_ROOT = Path(__file__).resolve().parents[3]
_RUN_ROOT = _RUNTIME_ROOT / "var" / "run"
_STATE_FILE = _RUN_ROOT / "local-runtime.json"
_COMPOSE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class LocalRuntimeError(SettingsError):
    pass


def load_runtime_environment(path: Path) -> None:
    """Load missing MiLAi settings from a local environment file."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.startswith("MILAI_") and name not in os.environ:
            os.environ[name] = value


class LocalRuntimeSupervisor:
    """Product-owned lifecycle facade for one configured local deployment."""

    def __init__(self, env_file: Path, *, compose_project: str = "milai-lean-v1") -> None:
        self.env_file = env_file
        self.compose_project = compose_project
        self.state = "STOPPED"

    def start(self, *, background: bool = True) -> dict[str, object]:
        self.state = "STARTING"
        try:
            load_runtime_environment(self.env_file)
            result = start_local(
                self.env_file,
                background=background,
                compose_project=self.compose_project,
            )
        except Exception:
            self.state = "FAILED"
            raise
        self.state = "READY" if result["status"] in {"RUNNING", "ALREADY_RUNNING"} else "STOPPED"
        return result

    def ready(self) -> bool:
        load_runtime_environment(self.env_file)
        settings = load_settings()
        available = local_profile_running(settings.bind_host, settings.bind_port)
        self.state = "READY" if available else "STOPPED"
        return available

    def stop(self) -> dict[str, object]:
        self.state = "DRAINING"
        result = stop_local(self.env_file)
        self.state = "STOPPED"
        return result

    def close(self) -> None:
        if self.state != "STOPPED":
            self.stop()

    def __enter__(self) -> LocalRuntimeSupervisor:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _entrypoint(name: str) -> str:
    candidate = Path(sys.executable).with_name(name)
    if not candidate.is_file():
        raise LocalRuntimeError(f"{name} is not installed beside the active Python interpreter")
    return str(candidate)


def _safe_child_environment(*, worker: bool) -> dict[str, str]:
    result = dict(os.environ)
    forbidden = {
        "MILAI_MIGRATION_DATABASE_URL",
        "MILAI_AUDIT_DATABASE_URL",
        "MILAI_RESTORE_DATABASE_URL",
        "MILAI_OWNER_DB_PASSWORD",
        "MILAI_AUDIT_DB_PASSWORD",
        "MILAI_TEST_DATABASE_URL",
        "MILAI_TEST_API_DATABASE_URL",
        "MILAI_TEST_STEWARD_DATABASE_URL",
        "MILAI_TEST_WORKER_DATABASE_URL",
        "MILAI_TEST_AUDIT_DATABASE_URL",
    }
    if not worker:
        forbidden.update({"MILAI_WORKER_DATABASE_URL", "MILAI_WORKER_DB_PASSWORD"})
    for name in forbidden:
        result.pop(name, None)
    return result


def _run(arguments: list[str], *, env: dict[str, str] | None = None, timeout: int = 60) -> None:
    try:
        completed = subprocess.run(  # noqa: S603 -- fixed local orchestration argv only
            arguments,
            cwd=_RUNTIME_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalRuntimeError("local profile command could not be executed") from exc
    if completed.returncode != 0:
        raise LocalRuntimeError("local profile command failed without exposing subprocess output")


def _compose(env_file: Path, compose_project: str, *arguments: str) -> None:
    if not _COMPOSE_PROJECT.fullmatch(compose_project):
        raise LocalRuntimeError("Compose project must use safe lowercase local characters")
    _run(
        [
            "docker",
            "compose",
            "--project-name",
            compose_project,
            "--env-file",
            str(env_file.resolve()),
            *arguments,
        ],
        timeout=90,
    )


def _migrate() -> None:
    command.upgrade(alembic_config(), "head")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _wait_ready(host: str, port: int, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/health/ready"
    while time.monotonic() < deadline:
        try:
            request = Request(url)
            with urlopen(request, timeout=1) as response:  # noqa: S310 -- loopback only
                value = json.loads(response.read().decode("utf-8"))
            if (
                response.status == 200
                and isinstance(value, dict)
                and value.get("status") == "ready"
            ):
                return
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise LocalRuntimeError("local API did not become ready within 30 seconds")


def _process_marker(pid: int) -> str | None:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    closing = raw.rfind(")")
    fields = raw[closing + 2 :].split() if closing >= 0 else []
    return fields[19] if len(fields) > 19 else None


def _alive(pid: int, marker: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    current = _process_marker(pid)
    return marker is None or current == marker


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_state() -> dict[str, Any] | None:
    if not _STATE_FILE.is_file():
        return None
    try:
        value = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalRuntimeError("local profile state file is invalid") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "api",
        "worker",
        "postgres_mode",
        "compose_project",
    }:
        raise LocalRuntimeError("local profile state file has an unknown shape")
    if value.get("postgres_mode") not in {"MANAGED", "ADOPTED"}:
        raise LocalRuntimeError("local profile PostgreSQL state is invalid")
    if not isinstance(value.get("compose_project"), str) or not _COMPOSE_PROJECT.fullmatch(
        value["compose_project"]
    ):
        raise LocalRuntimeError("local profile Compose project state is invalid")
    for name in ("api", "worker"):
        process = value.get(name)
        if (
            not isinstance(process, dict)
            or not isinstance(process.get("pid"), int)
            or process.get("pid", 0) <= 1
            or not isinstance(process.get("marker"), (str, type(None)))
        ):
            raise LocalRuntimeError("local profile process state is invalid")
    return value


def _state_is_alive(state: dict[str, Any]) -> bool:
    return all(_alive(int(state[name]["pid"]), state[name]["marker"]) for name in ("api", "worker"))


def _write_state(
    api: subprocess.Popen[bytes],
    worker: subprocess.Popen[bytes],
    postgres_mode: str,
    compose_project: str,
) -> None:
    _RUN_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    _RUN_ROOT.chmod(0o700)
    value = {
        "schema": "milai.local-runtime-state.v1",
        "postgres_mode": postgres_mode,
        "compose_project": compose_project,
        "api": {"pid": api.pid, "marker": _process_marker(api.pid)},
        "worker": {"pid": worker.pid, "marker": _process_marker(worker.pid)},
    }
    descriptor = os.open(_STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _remove_state() -> None:
    if _STATE_FILE.is_file():
        _STATE_FILE.unlink()


def _log_handle(name: str) -> IO[bytes]:
    _RUN_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(_RUN_ROOT / f"{name}.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    return os.fdopen(descriptor, "ab", closefd=True)


def _spawn(
    name: str,
    *,
    env: dict[str, str],
    background: bool,
) -> subprocess.Popen[bytes]:
    log: IO[bytes] | None = _log_handle(name) if background else None
    try:
        return subprocess.Popen(  # noqa: S603 -- fixed installed entrypoint only
            [_entrypoint(f"milai-{name}")],
            cwd=_RUNTIME_ROOT,
            env=env,
            stdin=subprocess.DEVNULL if background else None,
            stdout=log,
            stderr=subprocess.STDOUT if background else None,
            start_new_session=background,
        )
    finally:
        if log is not None:
            log.close()


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _stop_state_processes(state: dict[str, Any]) -> None:
    processes = [(int(state[name]["pid"]), state[name]["marker"]) for name in ("api", "worker")]
    if any(
        _pid_exists(pid) and marker is not None and _process_marker(pid) != marker
        for pid, marker in processes
    ):
        raise LocalRuntimeError("refusing to stop a process whose identity marker changed")
    for pid, marker in processes:
        if _alive(pid, marker):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and any(_alive(pid, marker) for pid, marker in processes):
        time.sleep(0.1)
    for pid, marker in processes:
        if _alive(pid, marker):
            os.kill(pid, signal.SIGKILL)


def _database_ready() -> bool:
    try:
        settings = load_settings()
        database = Database(settings, expected_role="milai_api")
        try:
            database.ping()
        finally:
            database.close()
        return True
    except Exception:
        return False


def local_profile_running(host: str, port: int) -> bool:
    """Return whether the managed state or configured API endpoint is live."""
    state = _read_state()
    return (state is not None and _state_is_alive(state)) or _port_open(host, port)


def managed_process_status() -> dict[str, object]:
    """Return content-free process identity for the product-owned local profile."""

    state = _read_state()
    if state is None:
        return {"managed": False, "api": None, "worker": None}
    return {
        "managed": True,
        "api": {
            "pid": int(state["api"]["pid"]),
            "alive": _alive(int(state["api"]["pid"]), state["api"]["marker"]),
        },
        "worker": {
            "pid": int(state["worker"]["pid"]),
            "alive": _alive(int(state["worker"]["pid"]), state["worker"]["marker"]),
        },
    }


def start_local(
    env_file: Path, *, background: bool, compose_project: str = "milai-lean-v1"
) -> dict[str, object]:
    if not _COMPOSE_PROJECT.fullmatch(compose_project):
        raise LocalRuntimeError("Compose project must use safe lowercase local characters")
    existing = _read_state()
    if existing is not None:
        if _state_is_alive(existing):
            return {"status": "ALREADY_RUNNING", "mode": "background"}
        _remove_state()

    settings = load_settings()
    if _port_open(settings.bind_host, settings.bind_port):
        raise LocalRuntimeError("API port is already in use by an unmanaged process")

    postgres_mode = "ADOPTED" if _database_ready() else "MANAGED"
    if postgres_mode == "MANAGED":
        _compose(env_file, compose_project, "up", "-d", "--wait", "postgres")
    api_process: subprocess.Popen[bytes] | None = None
    worker_process: subprocess.Popen[bytes] | None = None
    keep_running = False
    try:
        _migrate()
        prepare_runtime_directories(settings)
        database = Database(settings, expected_role="milai_api")
        try:
            database.ping()
        finally:
            database.close()

        worker_environment = _safe_child_environment(worker=True)
        _run([_entrypoint("milai-worker"), "--once"], env=worker_environment)
        worker_process = _spawn("worker", env=worker_environment, background=background)
        api_process = _spawn(
            "api", env=_safe_child_environment(worker=False), background=background
        )
        _write_state(api_process, worker_process, postgres_mode, compose_project)
        _wait_ready(settings.bind_host, settings.bind_port)
        smoke = run_isolated_smoke()
        if smoke.get("status") != "PASS":
            raise LocalRuntimeError("isolated post-start smoke failed")

        started = {
            "status": "RUNNING",
            "mode": "background" if background else "foreground",
            "api_pid": api_process.pid,
            "worker_pid": worker_process.pid,
            "health": f"http://{settings.bind_host}:{settings.bind_port}/health/ready",
            "smoke_report": smoke["report"],
            "owner_credential_in_api": False,
            "owner_credential_in_worker": False,
            "volume_policy": "PRESERVE_ON_STOP",
            "postgres_mode": postgres_mode,
            "compose_project": compose_project,
        }
        if background:
            keep_running = True
            return started

        try:
            while api_process.poll() is None and worker_process.poll() is None:
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        if api_process.poll() not in {None, 0} or worker_process.poll() not in {None, 0}:
            raise LocalRuntimeError("a foreground Runtime process exited unexpectedly")
        return {**started, "status": "STOPPED"}
    except LocalRuntimeError:
        raise
    except Exception as exc:
        raise LocalRuntimeError("local profile startup validation failed") from exc
    finally:
        if not keep_running:
            if api_process is not None:
                _terminate_process(api_process)
            if worker_process is not None:
                _terminate_process(worker_process)
            _remove_state()
            if postgres_mode == "MANAGED":
                _compose(env_file, compose_project, "stop", "postgres")


def stop_local(env_file: Path) -> dict[str, object]:
    state = _read_state()
    if state is None:
        return {"status": "NOT_RUNNING", "volume_policy": "PRESERVED"}
    _stop_state_processes(state)
    _remove_state()
    if state["postgres_mode"] == "MANAGED":
        _compose(env_file, state["compose_project"], "stop", "postgres")
    stopped = ["api", "worker"]
    if state["postgres_mode"] == "MANAGED":
        stopped.append("postgres")
    return {
        "status": "STOPPED",
        "processes": stopped,
        "postgres_mode": state["postgres_mode"],
        "compose_project": state["compose_project"],
        "volume_policy": "PRESERVED",
    }
