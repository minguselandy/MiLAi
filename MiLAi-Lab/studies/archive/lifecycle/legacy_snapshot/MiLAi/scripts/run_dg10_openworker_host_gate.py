from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-20"
BASE_IMAGE = "openworker-v2:2026.5.9.1"
BASE_IMAGE_ID = (
    "sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
)
DERIVED_IMAGE = "milai-openworker:dg10-candidate.1-local"
EXPECTED_OPENCODE_VERSION = "1.14.28"
EXPECTED_OPENCODE_SHA256 = (
    "c4847b3da969507d5cadf3321883c7b477e5ab75763014d688116a6795b63dce"
)
EXPECTED_PYTHON = "Python 3.12.13"
EXPECTED_UV = "uv 0.11.9 (x86_64-unknown-linux-musl)"
BROKER = ROOT / "integrations/openworker-mcp/broker/milai_mcp_broker.py"
RELAY = ROOT / "integrations/openworker-mcp/relay/milai_mcp_relay.py"
CONFIG = ROOT / "integrations/openworker-mcp/openworker/opencode.json"
CONTRACT = ROOT / "contracts/agent/v1/openworker-mcp-uds.md"
MCP_EXECUTABLE = ROOT / "integrations/mcp/.venv/bin/milai-mcp"
WHEELHOUSE = (
    ROOT
    / "integrations/openworker-mcp/wheelhouse/cp312-musllinux_1_2_x86_64-candidate.2"
)
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-openworker-mcp-host-gate-candidate.2-{DATE}.json"
)
_SECRET_NAMES = (
    "MILAI_AGENT_TOKEN",
    "MILAI_AGENT_READER_TOKEN",
    "MILAI_BASE_URL",
    "DATABASE_URL",
    "POSTGRES_DSN",
    "MILAI_PROVIDER_CREDENTIAL",
)


class GateError(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise GateError(
            f"command failed with status {completed.returncode}; "
            f"stdout_tail={completed.stdout[-1000:]!r}; stderr_tail={completed.stderr[-1000:]!r}"
        )
    return completed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _image(target: str) -> dict[str, Any]:
    value = json.loads(_run(["docker", "image", "inspect", target]).stdout)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise GateError("unexpected image inspection response")
    return value[0]


def _validate_static_identity() -> dict[str, Any]:
    base = _image(BASE_IMAGE)
    derived = _image(DERIVED_IMAGE)
    if base.get("Id") != BASE_IMAGE_ID:
        raise GateError("base image identity drift")
    if base.get("Os") != "linux" or base.get("Architecture") != "amd64":
        raise GateError("base image platform drift")
    labels = (derived.get("Config") or {}).get("Labels") or {}
    if labels.get("io.milai.dg10.base-image-id") != BASE_IMAGE_ID:
        raise GateError("derived image base label drift")
    base_layers = (base.get("RootFS") or {}).get("Layers") or []
    derived_layers = (derived.get("RootFS") or {}).get("Layers") or []
    if derived_layers[: len(base_layers)] != base_layers:
        raise GateError("derived image does not preserve the base layer prefix")
    versions = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            DERIVED_IMAGE,
            "-c",
            (
                "set -eu; opencode --version; python3 --version; uv --version; "
                "sha256sum /usr/local/bin/opencode /usr/local/bin/milai-mcp-relay "
                "/openworker/image/config/opencode.json"
            ),
        ]
    ).stdout
    if EXPECTED_OPENCODE_VERSION not in versions or EXPECTED_PYTHON not in versions:
        raise GateError("derived runtime version drift")
    if EXPECTED_UV not in versions or EXPECTED_OPENCODE_SHA256 not in versions:
        raise GateError("derived executable identity drift")
    if _sha256(RELAY) not in versions or _sha256(CONFIG) not in versions:
        raise GateError("derived relay/config bytes differ from source")
    manifest = json.loads((WHEELHOUSE / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "LOCAL_CANDIDATE_REVIEW_REQUIRED":
        raise GateError("wheelhouse is not a completed local candidate")
    if (manifest.get("offline_clean_install") or {}).get("status") != "PASS":
        raise GateError("wheelhouse offline clean install is not PASS")
    return {
        "base_image_id": BASE_IMAGE_ID,
        "derived_image_id": derived.get("Id"),
        "platform": "linux/amd64",
        "base_layer_count": len(base_layers),
        "derived_layer_count": len(derived_layers),
        "opencode_version": EXPECTED_OPENCODE_VERSION,
        "opencode_sha256": EXPECTED_OPENCODE_SHA256,
        "python": EXPECTED_PYTHON.removeprefix("Python "),
        "uv": EXPECTED_UV.removeprefix("uv "),
        "relay_sha256": _sha256(RELAY),
        "broker_sha256": _sha256(BROKER),
        "config_template_sha256": _sha256(CONFIG),
        "contract_sha256": _sha256(CONTRACT),
        "wheelhouse_manifest_sha256": _sha256(WHEELHOUSE / "manifest.json"),
        "wheelhouse_root_sha256": manifest["canonical_entries_sha256"],
    }


def _policy(workspace: Path, token: str) -> tuple[Path, Path, Path]:
    socket_directory = workspace / "reader-lite"
    socket_directory.mkdir(mode=0o700)
    socket_path = socket_directory / "reader-lite.sock"
    policy = {
        "allowed_peer_uids": [0],
        "base_url": "http://127.0.0.1:18080",
        "child_shutdown_seconds": 5,
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_connections": 8,
        "max_limit": 3,
        "mcp_executable": str(MCP_EXECUTABLE),
        "mcp_executable_sha256": _sha256(MCP_EXECUTABLE),
        "profile": "reader-lite",
        "required_authority": "ACTION_SAFE",
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "scope": {"project_ids": ["milai"]},
        "socket_mode": "0600",
        "socket_path": str(socket_path),
    }
    policy_path = workspace / "reader-lite-policy.json"
    policy_path.write_text(json.dumps(policy, sort_keys=True), encoding="utf-8")
    policy_path.chmod(0o600)
    token_path = workspace / "reader.token"
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)
    return policy_path, token_path, socket_path


def _start_broker(
    policy: Path, token: Path, socket_path: Path
) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable,
            str(BROKER),
            "--policy",
            str(policy),
            "--token-file",
            str(token),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise GateError(f"broker exited before ready: {stderr[-1000:]}")
        if socket_path.exists():
            return process
        time.sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    raise GateError("broker readiness timeout")


def _stop_broker(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
    try:
        _, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate(timeout=5)
    return stderr


def _container_command(name: str, image: str, socket_path: Path | None) -> list[str]:
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--ulimit",
        "core=0:0",
        "--tmpfs",
        "/openworker/data:rw,nosuid,nodev,noexec,size=128m,mode=0700",
        "--env",
        "OPENWORKER_KEY=synthetic-openworker-key",
        "--env",
        "OPENWORKER_URL=http://127.0.0.1:9",
    ]
    if socket_path is not None:
        command.extend(
            [
                "--mount",
                (
                    f"type=bind,src={socket_path},"
                    "dst=/run/milai-mcp/reader-lite.sock,readonly"
                ),
            ]
        )
    command.append(image)
    return command


def _start_container(name: str, image: str, socket_path: Path | None) -> None:
    _run(_container_command(name, image, socket_path))
    _wait_ready(name)


def _wait_ready(name: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status = _run(
            ["docker", "inspect", name, "--format", "{{.State.Status}}"], check=False
        )
        if status.returncode != 0 or status.stdout.strip() != "running":
            logs = _run(["docker", "logs", name], check=False).stdout
            raise GateError(f"container stopped before ready: {logs[-1000:]}")
        health = _run(
            [
                "docker",
                "exec",
                name,
                "curl",
                "-sf",
                "-u",
                "opencode:openworker-local",
                "http://127.0.0.1:4096/global/health",
            ],
            check=False,
            timeout=10,
        )
        logs = _run(["docker", "logs", name], check=False).stdout
        if health.returncode == 0 and "OC config schema OK" in logs:
            return
        time.sleep(0.5)
    raise GateError("OpenWorker/OpenCode readiness timeout")


def _mcp_list(name: str, *, expect_connected: bool) -> str:
    result = _run(
        [
            "docker",
            "exec",
            "--workdir",
            "/openworker/runtime",
            "--env",
            "OPENCODE_CONFIG_DIR=/openworker/runtime",
            name,
            "opencode",
            "mcp",
            "list",
        ],
        check=False,
        timeout=30,
    )
    normalized = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
    connected = "milai" in normalized.lower() and "connected" in normalized.lower()
    if connected != expect_connected:
        raise GateError(f"unexpected MCP state: {normalized[-1000:]}")
    return hashlib.sha256(normalized.encode()).hexdigest()


def _wire_catalog(name: str, protocol: str) -> dict[str, Any]:
    script = f'''import json
import selectors
import subprocess
import time

process = subprocess.Popen(
    ["/usr/local/bin/milai-mcp-relay", "/run/milai-mcp/reader-lite.sock"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
    bufsize=1,
)
assert process.stdin is not None and process.stdout is not None
next_id = 1

def send(value):
    process.stdin.write(json.dumps(value, separators=(",", ":")) + "\\n")
    process.stdin.flush()

def request(method, params):
    global next_id
    request_id = next_id
    next_id += 1
    send({{"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}})
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if not selector.select(0.25):
                continue
            message = json.loads(process.stdout.readline())
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("MCP request error")
                return message["result"]
    finally:
        selector.close()
    raise TimeoutError("MCP request timeout")

client_info = {{"name": "dg10-openworker-wire", "version": "0.1"}}
if "{protocol}" == "2026-07-28":
    meta = {{
        "io.modelcontextprotocol/protocolVersion": "{protocol}",
        "io.modelcontextprotocol/clientInfo": client_info,
        "io.modelcontextprotocol/clientCapabilities": {{}},
    }}
    discovered = request("server/discover", {{"_meta": meta}})
    if "{protocol}" not in discovered.get("supportedVersions", []):
        raise RuntimeError("modern protocol is not advertised")
    negotiated = "{protocol}"
    catalog = request("tools/list", {{"_meta": meta}})
else:
    initialized = request("initialize", {{
        "protocolVersion": "{protocol}",
        "capabilities": {{}},
        "clientInfo": client_info,
    }})
    send({{"jsonrpc": "2.0", "method": "notifications/initialized"}})
    negotiated = initialized.get("protocolVersion")
    catalog = request("tools/list", {{}})
print(json.dumps({{
    "protocol": negotiated,
    "tools": [tool["name"] for tool in catalog.get("tools", [])],
    "schemas_strict": all(
        tool.get("inputSchema", {{}}).get("additionalProperties") is False
        for tool in catalog.get("tools", [])
    ),
}}, sort_keys=True))
process.stdin.close()
process.terminate()
process.wait(timeout=5)
'''
    completed = _run(
        ["docker", "exec", "--interactive", name, "python3", "-"],
        input_text=script,
        timeout=30,
    )
    value: dict[str, Any] = json.loads(completed.stdout)
    if (
        value.get("protocol") != protocol
        or value.get("tools") != ["milai_recall"]
        or value.get("schemas_strict") is not True
    ):
        raise GateError("reader-lite catalog or schema drift")
    return value


def _rendered_config(name: str) -> tuple[str, dict[str, Any]]:
    digest = _run(
        ["docker", "exec", name, "sha256sum", "/openworker/runtime/opencode.json"]
    ).stdout.split()[0]
    script = """import json
value = json.load(open("/openworker/runtime/opencode.json", encoding="utf-8"))
print(json.dumps(value.get("mcp"), sort_keys=True, separators=(",", ":")))
"""
    mcp = json.loads(
        _run(
            ["docker", "exec", "--interactive", name, "python3", "-"],
            input_text=script,
        ).stdout
    )
    expected = json.loads(CONFIG.read_text(encoding="utf-8"))["mcp"]
    if mcp != expected:
        raise GateError("rendered MCP config drift")
    return digest, mcp


def _require_same_digest(*, label: str, expected: str, actual: str) -> None:
    if actual != expected:
        raise GateError(
            f"{label} changed: expected_sha256={expected}; actual_sha256={actual}"
        )


def _adversarial_scan(name: str, token: str) -> dict[str, Any]:
    inspect = json.loads(_run(["docker", "container", "inspect", name]).stdout)[0]
    host = inspect["HostConfig"]
    mounts = inspect.get("Mounts") or []
    mount_summary = [
        {
            "type": item.get("Type"),
            "destination": item.get("Destination"),
            "rw": item.get("RW"),
        }
        for item in mounts
        if item.get("Type") == "bind"
    ]
    if host.get("NetworkMode") != "none" or host.get("Privileged") is not False:
        raise GateError("container network/privileged boundary drift")
    if "ALL" not in (host.get("CapDrop") or []):
        raise GateError("container capabilities were not dropped")
    if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
        raise GateError("no-new-privileges is absent")
    ulimits = host.get("Ulimits") or []
    if ulimits != [{"Name": "core", "Hard": 0, "Soft": 0}]:
        raise GateError("core dump ulimit is not zero")
    if mount_summary != [
        {"type": "bind", "destination": "/run/milai-mcp/reader-lite.sock", "rw": False}
    ]:
        raise GateError("unexpected container bind mount")

    env = "\n".join((inspect.get("Config") or {}).get("Env") or [])
    config_bytes = _run(
        ["docker", "exec", name, "sh", "-c", "cat /openworker/runtime/opencode.json"]
    ).stdout
    debug_config = _run(
        [
            "docker",
            "exec",
            name,
            "curl",
            "-sf",
            "-u",
            "opencode:openworker-local",
            "http://127.0.0.1:4096/config",
        ]
    ).stdout
    log_result = _run(["docker", "logs", name], check=False)
    logs = log_result.stdout + log_result.stderr
    if token in env or token in config_bytes or token in debug_config or token in logs:
        raise GateError("synthetic broker token reflected into Worker state")
    if any(
        value in env or value in config_bytes or value in debug_config or value in logs
        for value in _SECRET_NAMES
    ):
        raise GateError("MiLAi secret/DSN variable reflected into Worker state")

    proc_script = """from pathlib import Path
patterns = (b"MILAI_AGENT_TOKEN", b"MILAI_BASE_URL", b"DATABASE_URL", b"postgresql://")
matches = 0
for suffix in ("environ", "cmdline"):
    for path in Path("/proc").glob(f"[0-9]*/{suffix}"):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        matches += sum(pattern in raw for pattern in patterns)
print(matches)
"""
    proc_matches = int(
        _run(
            ["docker", "exec", "--interactive", name, "python3", "-"],
            input_text=proc_script,
        ).stdout.strip()
    )
    if proc_matches:
        raise GateError("MiLAi token/URL/DSN name found in Worker /proc")
    file_scan_script = """from pathlib import Path
patterns = (b"MILAI_AGENT_TOKEN", b"MILAI_BASE_URL", b"DATABASE_URL", b"postgresql://")
roots = (Path("/openworker/image/skills"), Path("/openworker/data/skills"), Path("/openworker/data/workspace"))
matches = 0
cores = 0
for root in roots:
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            continue
        raw = path.read_bytes()
        matches += sum(pattern in raw for pattern in patterns)
        cores += path.name == "core" or path.name.startswith("core.")
print(f"{matches} {cores}")
"""
    file_matches, core_files = (
        _run(
            ["docker", "exec", "--interactive", name, "python3", "-"],
            input_text=file_scan_script,
        )
        .stdout.strip()
        .split()
    )
    if int(file_matches) or int(core_files):
        raise GateError(
            "MiLAi secret name or crash dump found in Skill/workspace files"
        )
    direct_loopback = _run(
        [
            "docker",
            "exec",
            name,
            "curl",
            "-sf",
            "--max-time",
            "2",
            "http://127.0.0.1:18080/v1/capabilities",
        ],
        check=False,
        timeout=10,
    )
    bridge = _run(
        [
            "docker",
            "exec",
            name,
            "curl",
            "-sf",
            "--max-time",
            "2",
            "http://172.17.0.1:18080/v1/capabilities",
        ],
        check=False,
        timeout=10,
    )
    if direct_loopback.returncode == 0 or bridge.returncode == 0:
        raise GateError("Worker unexpectedly reached a Runtime route")
    return {
        "environment_secret_names": "ABSENT",
        "config_secret_names": "ABSENT",
        "debug_api_secret_names": "ABSENT",
        "proc_secret_names": "ABSENT",
        "skill_workspace_secret_names": "ABSENT",
        "log_secret_names": "ABSENT",
        "crash_dumps": "DISABLED_CORE_ULIMIT_ZERO_AND_ABSENT",
        "runtime_loopback_direct": "BLOCKED",
        "runtime_bridge_direct": "BLOCKED",
        "network_mode": host["NetworkMode"],
        "privileged": host["Privileged"],
        "cap_drop": host["CapDrop"],
        "security_opt": host["SecurityOpt"],
        "ulimits": ulimits,
        "mounts": mount_summary,
        "docker_socket_mounted": False,
        "host_secret_directory_mounted": False,
        "postgres_socket_mounted": False,
    }


def _remove_container(name: str) -> None:
    _run(["docker", "rm", "--force", name], check=False, timeout=30)


def _broker_event_summary(stderr: str, token: str) -> dict[str, Any]:
    if token in stderr or any(value in stderr for value in _SECRET_NAMES):
        raise GateError("broker operational log contains a secret name/value")
    events: dict[str, int] = {}
    for line in stderr.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateError("broker emitted a non-JSON diagnostic") from exc
        event = str(value.get("event", "UNKNOWN"))
        events[event] = events.get(event, 0) + 1
    return {"secret_scan": "PASS", "events": events}


def _write_report(path: Path, value: dict[str, Any]) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the DG-10 local OpenWorker MCP host gate"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    identity = _validate_static_identity()
    token = secrets.token_urlsafe(48)
    container_name = f"milai-dg10-{uuid4().hex[:12]}"
    rollback_name = f"milai-dg10-rollback-{uuid4().hex[:12]}"
    broker_process: subprocess.Popen[str] | None = None
    broker_logs: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="milai-dg10-host-gate-") as temporary:
            workspace = Path(temporary)
            workspace.chmod(0o700)
            policy, token_path, socket_path = _policy(workspace, token)
            policy_digest = _sha256(policy)
            broker_process = _start_broker(policy, token_path, socket_path)
            _start_container(container_name, DERIVED_IMAGE, socket_path)
            first_config_digest, mcp_config = _rendered_config(container_name)
            first_list_digest = _mcp_list(container_name, expect_connected=True)
            current_catalog = _wire_catalog(container_name, "2026-07-28")
            legacy_catalog = _wire_catalog(container_name, "2025-11-25")
            adversarial = _adversarial_scan(container_name, token)

            before_restart = json.loads(
                _run(["docker", "container", "inspect", container_name]).stdout
            )[0]["State"]["StartedAt"]
            _run(["docker", "restart", container_name], timeout=60)
            _wait_ready(container_name)
            after_restart = json.loads(
                _run(["docker", "container", "inspect", container_name]).stdout
            )[0]["State"]["StartedAt"]
            restart_config_digest, _ = _rendered_config(container_name)
            restart_list_digest = _mcp_list(container_name, expect_connected=True)
            if before_restart == after_restart:
                raise GateError("container restart was not observed")
            _require_same_digest(
                label="rendered config after restart",
                expected=first_config_digest,
                actual=restart_config_digest,
            )

            _remove_container(container_name)
            _start_container(container_name, DERIVED_IMAGE, socket_path)
            recreate_config_digest, _ = _rendered_config(container_name)
            recreate_list_digest = _mcp_list(container_name, expect_connected=True)
            _require_same_digest(
                label="rendered config after recreate",
                expected=first_config_digest,
                actual=recreate_config_digest,
            )

            broker_logs.append(_stop_broker(broker_process))
            broker_process = None
            _mcp_list(container_name, expect_connected=False)
            broker_process = _start_broker(policy, token_path, socket_path)
            _remove_container(container_name)
            _start_container(container_name, DERIVED_IMAGE, socket_path)
            recovered_list_digest = _mcp_list(container_name, expect_connected=True)

            _remove_container(container_name)
            _start_container(rollback_name, BASE_IMAGE, None)
            rollback_list_digest = _mcp_list(rollback_name, expect_connected=False)
            rollback_config = _run(
                [
                    "docker",
                    "exec",
                    rollback_name,
                    "cat",
                    "/openworker/runtime/opencode.json",
                ]
            ).stdout
            if '"milai"' in rollback_config or "milai-mcp-relay" in rollback_config:
                raise GateError("base image rollback retained MiLAi MCP config")
            broker_logs.append(_stop_broker(broker_process))
            broker_process = None

            report = {
                "schema": "milai.dg10.openworker-mcp-host-gate.v1",
                "candidate": "candidate.2",
                "date": DATE,
                "status": "LOCAL_CANDIDATE_REVIEW_REQUIRED",
                "provider_requests": 0,
                "provider_cost": 0,
                "data_boundary": "SYNTHETIC_ONLY",
                "release_boundary": (
                    "LOCAL_ONLY; upstream Worker source/redistribution license not established"
                ),
                "runtime_banner": "0.1.x CANDIDATE",
                "schema_banner": "0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE",
                "identity": identity,
                "actual_policy_sha256": policy_digest,
                "actual_mcp_executable_sha256": _sha256(MCP_EXECUTABLE),
                "rendered_mcp_config": mcp_config,
                "rendered_config_sha256": first_config_digest,
                "protocol_catalogs": {
                    "2026-07-28": current_catalog,
                    "2025-11-25": legacy_catalog,
                },
                "openworker_discovery": {
                    "initial_list_sha256": first_list_digest,
                    "restart_list_sha256": restart_list_digest,
                    "recreate_list_sha256": recreate_list_digest,
                    "recovered_list_sha256": recovered_list_digest,
                    "all_connected": True,
                    "reader_lite_tools": ["milai_recall"],
                },
                "restart_recreate": {
                    "restart_observed": True,
                    "restart_config_unchanged": restart_config_digest
                    == first_config_digest,
                    "recreate_config_unchanged": recreate_config_digest
                    == first_config_digest,
                    "broker_stop_failed_closed": True,
                    "new_socket_required_worker_recreate": True,
                    "recovery_after_broker_restart_and_remount": True,
                },
                "credential_and_network_adversary": adversarial,
                "rollback": {
                    "base_image_id": BASE_IMAGE_ID,
                    "mcp_absent": True,
                    "list_sha256": rollback_list_digest,
                },
                "gate_results": {
                    "MCG-00": "PASS_LOCAL_REVERIFY",
                    "MCG-01": "PASS_LOCAL_REVERIFY",
                    "MCG-02": "PASS_LOCAL_REVERIFY",
                    "OWG-00": "PASS_LOCAL_CANDIDATE",
                    "OWG-01": "PASS_LOCAL_CANDIDATE",
                    "OWG-02": "PASS_LOCAL_CANDIDATE",
                    "AIG-00": "NO_GO_REAL_PROVIDER_NOT_AUTHORIZED",
                    "AIG-01": "NO_GO_INDEPENDENT_REVIEW_ABSENT",
                },
                "known_limits": [
                    "No real Provider/model, billing object, or charge-bearing request was used.",
                    "OpenWorker Worker source and redistribution permission remain unavailable.",
                    "Runtime-backed recall/OpenIssue/revocation scenarios passed the PV-LOCAL Agent E2E, but no external Provider Agent was authorized.",
                    "This author gate is not an independent review and cannot close OE-F06.",
                ],
            }
            _write_report(output, report)
    finally:
        _remove_container(container_name)
        _remove_container(rollback_name)
        if broker_process is not None:
            broker_logs.append(_stop_broker(broker_process))
        for stderr in broker_logs:
            _broker_event_summary(stderr, token)

    report = json.loads(output.read_text(encoding="utf-8"))
    report["broker_log_summary"] = {
        "secret_scan": "PASS",
        "segments": [_broker_event_summary(stderr, token) for stderr in broker_logs],
    }
    _write_report(output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
