"""Owned native-WMA public service lifecycle; importing performs no effects."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path

INSTALL = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-e0-public-completion-v1/product-install-source"
)
LOCK = INSTALL.parent / "product-install.lock.json"
RAW = Path("/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/service")
RUNTIME = INSTALL / "runtime"
PROJECT = "v0224-wma-owned"
PORTS = (25433, 28081, 27338)
ENV_FILE = RAW / "runtime.env"
REGISTRY = RAW / "secrets/users.json"
OPS = RUNTIME / ".venv/bin/milai-ops"
API = RUNTIME / ".venv/bin/milai-api"
MCP = INSTALL / "integrations/mcp/.venv/bin/milai-codex-full-mcp"
ISSUE = MCP.with_name("milai-codex-user")
COMPOSE = [
    "/usr/bin/docker",
    "compose",
    "--project-name",
    PROJECT,
    "--env-file",
    str(ENV_FILE),
    "-f",
    str(RUNTIME / "compose.yaml"),
]


def save(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
    os.replace(temp, path)


def base_env() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "UV_OFFLINE": "1",
        "HF_HUB_OFFLINE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def parse_env(path: Path) -> dict[str, str]:
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("runtime environment must be private regular file")
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if not key.startswith("MILAI_") or key in result:
            raise ValueError("invalid runtime environment assignment")
        result[key] = value
    expected = {
        "MILAI_POSTGRES_PORT": "25433",
        "MILAI_BIND_PORT": "28081",
        "MILAI_BIND_HOST": "127.0.0.1",
        "MILAI_BASE_URL": "http://127.0.0.1:28081",
        "MILAI_BLOB_ROOT": str(RAW / "blobs"),
        "MILAI_DATA_MODE": "SYNTHETIC_ONLY",
    }
    if any(result.get(k) != v for k, v in expected.items()):
        raise ValueError("runtime environment isolation mismatch")
    return result


def marker(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except FileNotFoundError:
        return None


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def process_command(pid: int) -> str:
    return Path(f"/proc/{pid}/cmdline").read_bytes().hex()


def terminate_owned(row: dict) -> None:
    pid = row["pid"]

    def verify() -> None:
        if (
            row["boot_id"] != boot_id()
            or marker(pid) != row["starttime"]
            or process_command(pid) != row["cmdline_hex"]
        ):
            raise RuntimeError("process ownership mismatch")

    if marker(pid) is None:
        return
    verify()
    os.kill(pid, signal.SIGTERM)
    until = time.monotonic() + 10
    while marker(pid) == row["starttime"] and time.monotonic() < until:
        time.sleep(0.1)
    if marker(pid) == row["starttime"]:
        verify()
        os.kill(pid, signal.SIGKILL)
        until = time.monotonic() + 5
        while marker(pid) == row["starttime"] and time.monotonic() < until:
            time.sleep(0.1)
        if marker(pid) == row["starttime"]:
            raise RuntimeError("owned process did not terminate")


class Service:
    def __init__(self, action: str):
        self.output = RAW / (action + "-" + str(time.time_ns()))
        self.output.mkdir(parents=True)
        self.state_path = RAW / "owned-state.json"
        self.state = {"project": PROJECT, "processes": {}, "container_id": None}
        self.rows = []

    def command(
        self,
        name: str,
        argv: list[str],
        *,
        env=None,
        timeout=120,
        private_stdout: Path | None = None,
        check=True,
    ) -> bytes:
        started = time.monotonic()
        output = private_stdout or self.output / (name + ".stdout")
        with output.open("xb") as out, (self.output / (name + ".stderr")).open("xb") as err:
            child = subprocess.Popen(  # noqa: S603 - fixed owned public CLI argv, no shell
                argv,
                cwd=RUNTIME,
                env=env or base_env(),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            row = {
                "name": name,
                "argv": argv,
                "pid": child.pid,
                "starttime": marker(child.pid),
                "boot_id": boot_id(),
                "exit_code": None,
            }
            save(self.output / (name + ".start.json"), row)
            try:
                row["exit_code"] = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # This foreground CLI is our own unreaped child; its PID cannot be reused.
                os.killpg(child.pid, signal.SIGKILL)
                row["exit_code"] = child.wait()
                row["timeout"] = True
            finally:
                row["elapsed_seconds"] = time.monotonic() - started
                self.rows.append(row)
                save(self.output / (name + ".terminal.json"), row)
        if check and row["exit_code"] != 0:
            raise RuntimeError(f"{name} failed; see private logs")
        return b"" if private_stdout else output.read_bytes()

    def spawn(self, name: str, argv: list[str], env: dict[str, str]) -> None:
        with (
            (self.output / (name + ".stdout")).open("xb") as out,
            (self.output / (name + ".stderr")).open("xb") as err,
        ):
            child = subprocess.Popen(  # noqa: S603 - fixed public service argv, no shell
                argv,
                cwd=RUNTIME,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        row = {
            "pid": child.pid,
            "starttime": marker(child.pid),
            "boot_id": boot_id(),
            "argv": argv,
            "started_monotonic": time.monotonic(),
            "cmdline_hex": process_command(child.pid),
            "exit_code": None,
        }
        self.state["processes"][name] = row
        save(self.state_path, self.state)
        if row["starttime"] is None:
            raise RuntimeError("service immediately exited")

    def wait_tcp(self, port: int, *, seconds=60, process: str | None = None) -> None:
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            if (
                process
                and marker(self.state["processes"][process]["pid"])
                != self.state["processes"][process]["starttime"]
            ):
                raise RuntimeError("service exited before readiness")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    save(
                        self.output / f"tcp-{port}.json",
                        {"port": port, "elapsed_seconds": time.monotonic() - started},
                    )
                    return
            except OSError:
                time.sleep(0.2)
        raise TimeoutError("TCP readiness exhausted")

    def start(self) -> None:
        from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock

        verification = verify_product_lock(load_product_lock(LOCK), INSTALL)
        save(self.output / "product-verification.json", verification.to_dict())
        if not verification.valid:
            raise RuntimeError("public product lock verification failed")
        if self.state_path.exists() or ENV_FILE.exists() or REGISTRY.exists():
            raise RuntimeError("fresh service instance required")
        for port in PORTS:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        self.command(
            "init",
            [
                str(OPS),
                "init",
                "--env-file",
                str(ENV_FILE),
                "--blob-root",
                str(RAW / "blobs"),
                "--postgres-port",
                "25433",
                "--api-port",
                "28081",
            ],
        )
        runtime = {**base_env(), **parse_env(ENV_FILE)}
        existing = self.command("existing-containers", [*COMPOSE, "ps", "-aq"]).strip()
        volumes = self.command(
            "existing-volume",
            [
                "/usr/bin/docker",
                "volume",
                "ls",
                "--filter",
                "name=^v0224-wma-owned_milai_postgres_data$",
                "--format",
                "{{.Name}}",
            ],
        ).strip()
        if existing or volumes:
            raise RuntimeError("owned project or volume already exists")
        save(self.state_path, self.state)
        self.command("postgres-up", [*COMPOSE, "up", "-d", "postgres"], check=False)
        up_failed = self.rows[-1]["exit_code"] != 0
        self.state["container_id"] = (
            self.command("postgres-id", [*COMPOSE, "ps", "-q", "postgres"]).decode().strip()
        )
        if not self.state["container_id"]:
            raise RuntimeError("missing owned postgres container")
        save(self.state_path, self.state)
        if up_failed:
            raise RuntimeError("postgres startup failed; owned container retained for stop")
        self.wait_tcp(25433)
        self.command(
            "migration",
            [str(RUNTIME / ".venv/bin/alembic"), "upgrade", "head"],
            env=runtime,
            timeout=180,
        )
        self.spawn("api", [str(API)], runtime)
        self.wait_tcp(28081, process="api")
        (RAW / "secrets").mkdir(mode=0o700, exist_ok=True)
        mcp_env = {
            **runtime,
            "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [PROJECT]}),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_CODEX_DATA_CLASSIFICATION": "SYNTHETIC",
            "MILAI_CODEX_TOKEN": secrets.token_urlsafe(48),
            "MILAI_CODEX_PRINCIPAL_ID": "wma-bootstrap-owned",
            "MILAI_CODEX_USER_REGISTRY": str(REGISTRY),
            "MILAI_MCP_HTTP_PUBLIC_BASE_URL": "http://127.0.0.1:27338",
        }
        for index in range(1, 5):
            self.command(
                f"issue-{index}",
                [
                    str(ISSUE),
                    "--registry-file",
                    str(REGISTRY),
                    "issue",
                    "--agent-id",
                    f"wma-root-{index:02d}",
                    "--url",
                    "http://127.0.0.1:27338/mcp",
                ],
                env=mcp_env,
                private_stdout=RAW / f"secrets/root-{index:02d}.json",
            )
        self.spawn(
            "mcp",
            [
                str(MCP),
                "--host",
                "127.0.0.1",
                "--port",
                "27338",
                "--catalog",
                "ordinary-memory-v1",
                "--max-retries",
                "0",
            ],
            mcp_env,
        )
        self.wait_tcp(27338, process="mcp")
        self.state["status"] = "TCP_READY_NOT_INTEGRATION_VALIDATED"
        save(self.state_path, self.state)

    def stop(self) -> None:
        self.state = json.loads(self.state_path.read_text())
        if self.state["project"] != PROJECT:
            raise RuntimeError("project ownership mismatch")
        for name in ("mcp", "api"):
            row = self.state["processes"].get(name)
            if row:
                started = time.monotonic()
                terminate_owned(row)
                save(
                    self.output / (name + "-stop.json"),
                    {
                        "pid": row["pid"],
                        "starttime": row["starttime"],
                        "elapsed_seconds": time.monotonic() - started,
                        "process_gone": marker(row["pid"]) is None,
                        "exit_code": None,
                        "note": "separate stop process cannot reap original service exit",
                    },
                )
        container = self.state["container_id"]
        if container:
            actual = (
                self.command("postgres-id-before-stop", [*COMPOSE, "ps", "-aq", "postgres"])
                .decode()
                .strip()
            )
            if actual != container:
                raise RuntimeError("postgres ownership mismatch")
            self.command("postgres-stop", [*COMPOSE, "stop", "postgres"])
        self.state["status"] = "STOPPED_DATA_RETAINED"
        save(self.state_path, self.state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop"))
    args = parser.parse_args()
    os.umask(0o077)
    service = Service(args.action)
    started = time.monotonic()
    try:
        getattr(service, args.action)()
    except BaseException as exc:
        save(
            service.output / "terminal.json",
            {
                "status": "FAILED",
                "error_type": type(exc).__name__,
                "elapsed_seconds": time.monotonic() - started,
                "logs_retained": True,
            },
        )
        raise SystemExit(1) from None
    save(
        service.output / "terminal.json",
        {
            "status": "COMPLETE",
            "action": args.action,
            "elapsed_seconds": time.monotonic() - started,
        },
    )


if __name__ == "__main__":
    main()
