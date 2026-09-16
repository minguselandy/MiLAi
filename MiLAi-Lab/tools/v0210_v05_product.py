"""Owned pinned-delivery PostgreSQL/MCP environment for zero-model recovery checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import tarfile
from contextlib import contextmanager
from pathlib import Path

import run_v02_memory_flow as base
from check_v0210_control import LAB, verify_baseline, write


def prepare(root: Path) -> None:
    baseline = json.loads((LAB / "configs/v0210-control-e1.json").read_text())
    write(root / "product-pin.json", verify_baseline(baseline))
    bundle = root / "milai-mcp-delivery-0.1.15"
    with tarfile.open(bundle / "runtime/packages/milai_runtime-0.1.4.tar.gz") as archive:
        archive.extractall(root, filter="data")
    runtime = root / "milai_runtime-0.1.4"
    binary = root / "runtime-venv/bin"
    if not (root / "runtime.env").exists():
        base._command([str(binary / "milai-ops"), "init", "--env-file", str(root / "runtime.env"),
                       "--blob-root", str(root / "blobs"),
                       "--postgres-port", str(base._free_port()),
                       "--api-port", str(base._free_port())], cwd=runtime)
    env = base._load_environment(root / "runtime.env")
    # This host exhausted Docker's allocation pool. Loopback PG needs no private network.
    override = root / "compose-loopback.yaml"
    override.write_text("services:\n  postgres:\n    network_mode: bridge\n")
    compose = ["docker", "compose", "--project-name", "v0210-v05-e3-pg", "--env-file",
               str(root / "runtime.env"), "--file", str(runtime / "compose.yaml"),
               "--file", str(override)]
    write(root / "compose-command.json", compose)
    base._command([*compose, "up", "--detach", "--wait", "postgres"], cwd=runtime, timeout=120)
    result = base._command([str(binary / "alembic"), "-c", "alembic.ini", "upgrade", "head"],
                           cwd=runtime, env=base._clean_environment(env), timeout=180)
    (root / "migration.log").write_text(result.stdout + result.stderr)
    group = base.ProcessGroup(root)
    api = group.start("api", [str(binary / "milai-api")], cwd=root,
                      env=base._clean_environment(env))
    write(root / "services.json", {"api": api.pid})
    base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
    # The runtime and its deployment/migrations both come from the verified delivery.
    write(root / "prepared.json", {"status": "READY", "worker": "NOT_REQUIRED_FOR_STATE",
                                    "runtime": "0.1.4", "mcp": "0.1.15", "client": "0.1.3"})


@contextmanager
def observer(root: Path, directory: Path, *, task: str, principal: str, project: str):
    base.assert_services(root)
    directory.mkdir(parents=True, exist_ok=True)
    env = base._load_environment(root / "runtime.env")
    token, port = secrets.token_urlsafe(32), base._free_port()
    env.update(MILAI_CODEX_PRINCIPAL_ID=principal, MILAI_CODEX_TASK_REF=task,
               MILAI_AGENT_SCOPE_JSON=json.dumps({"project_ids": [project]}),
               MILAI_CODEX_TOKEN=token,
               MILAI_MCP_HTTP_PUBLIC_BASE_URL=f"http://127.0.0.1:{port}")
    group = base.ProcessGroup(directory)
    try:
        server = group.start("compact-mcp", [str(root / "mcp-venv/bin/milai-codex-full-mcp"),
                             "--port", str(port), "--catalog", "compact-memory-v1"],
                             cwd=root, env=base._clean_environment(env))
        base._wait_http(f"http://127.0.0.1:{port}/readyz", server)

        def call(tool, arguments):
            value = asyncio.run(base.mcp_call(f"http://127.0.0.1:{port}/mcp", token,
                                              tool, arguments))
            return value if tool is None else base.structured(value)

        yield call
    finally:
        group.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root.resolve())
    print("OWNED_PINNED_PRODUCT_READY")
