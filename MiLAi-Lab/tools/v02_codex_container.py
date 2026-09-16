#!/usr/bin/env python3
"""Run the real Codex binary with only the session workspace and home mounted."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    wrapper_entered = time.time()
    home = Path(os.environ["CODEX_HOME"])
    workspace = Path(os.environ["V02_WORKSPACE"])
    name = os.environ["V02_CONTAINER_NAME"]
    command = [
        "docker", "run", "--rm", "--name", name, "--network", "host",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--tmpfs", "/tmp:rw,nosuid,size=128m",  # noqa: S108 -- private container tmpfs
        "--memory", "2g", "--cpus", "2",
        "--mount", f"type=bind,src={home},dst={home}",
        "--mount", f"type=bind,src={workspace},dst={workspace}",
        "--mount", f"type=bind,src={workspace / 'sources'},dst={workspace / 'sources'},readonly",
        "--mount",
        f"type=bind,src={Path(os.environ['V02_CODEX_BINARY']).parent},dst=/opt/codex/bin,readonly",
        "--mount", "type=bind,src=/etc/ssl/certs,dst=/etc/ssl/certs,readonly",
        "--mount", f"type=bind,src={os.environ['V02_RG_BINARY']},dst=/usr/local/bin/rg,readonly",
        "--env", "CODEX_HOME", "--env", "MILAI_CODEX_LAUNCHER_TOKEN",
        "--env", "HTTPS_PROXY", "--env", "HTTP_PROXY", "--env", "NO_PROXY",
        "--env", "https_proxy", "--env", "http_proxy", "--env", "no_proxy",
        "--workdir", str(workspace), "--entrypoint", "/opt/codex/bin/codex",
        "pgvector/pgvector:pg16",
    ]
    args = sys.argv[1:]
    # Capture the actual launcher-generated profile before it is removed. No credentials in it.
    profile = args[args.index("-p") + 1]
    observer = Path(os.environ["V02_OBSERVER"])
    observer.joinpath("host-profile.toml").write_text(
        home.joinpath(f"{profile}.config.toml").read_text(), encoding="utf-8"
    )
    prompt_args = [*args[:args.index("exec")], "debug", "prompt-input", args[-1]]
    debug_command = list(command)
    debug_command[debug_command.index(name)] = name + "-input"
    input_started = time.time()
    try:
        with observer.joinpath("initial-input.json").open("w") as output:
            result = subprocess.run(  # noqa: S603 -- fixed Docker wrapper, Host-generated args
                [*debug_command, *prompt_args], stdout=output, stderr=subprocess.PIPE,
                text=True, timeout=45, check=False,
            )
    except subprocess.TimeoutExpired:
        subprocess.run(  # noqa: S603 -- exact run-owned diagnostic container
            ["docker", "stop", "--time", "1", name + "-input"],  # noqa: S607
            capture_output=True, timeout=10, check=False,
        )
        observer.joinpath("input-status.json").write_text(json.dumps({"status": "TIMEOUT"}))
        return 1
    observer.joinpath("input-status.json").write_text(json.dumps({
        "returncode": result.returncode, "stderr": result.stderr,
        "scope": "Initial prompt assembly only; later per-request inputs not yet observed",
    }))
    if result.returncode:
        return result.returncode
    observer.joinpath("host-phase-times.json").write_text(json.dumps({
        "wrapper_entered_at": wrapper_entered,
        "input_export_started_at": input_started,
        "input_export_finished_at": time.time(),
        "model_exec_dispatched_at": time.time(),
        "scope": "Public launcher to wrapper includes MCP/bootstrap setup; "
                 "input export separate; later per-request timing unobserved",
    }))
    os.execvp(command[0], [*command, *args])  # noqa: S606 -- fixed Docker executable
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
