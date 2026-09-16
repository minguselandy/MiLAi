#!/usr/bin/env python3
"""Same full-A0 container boundary, with profile observation and no extra Codex execution."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    home = Path(os.environ["CODEX_HOME"])
    workspace = Path(os.environ["V02_WORKSPACE"])
    args = sys.argv[1:]
    observer = Path(os.environ["V02_OBSERVER"])
    profile = args[args.index("-p") + 1]
    observer.joinpath("host-profile.toml").write_text(
        home.joinpath(f"{profile}.config.toml").read_text(), encoding="utf-8")
    observer.joinpath("host-phase-times.json").write_text(json.dumps({
        "input_export_performed": False, "model_exec_dispatched_at": time.time(),
        "scope": "Normal launcher/MCP/bootstrap and exec only; profile retained; "
                 "initial and later per-request model inputs UNOBSERVED"}))
    command = [
        "docker", "run", "--rm", "--name", os.environ["V02_CONTAINER_NAME"],
        "--network", "host", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=128m",  # noqa: S108
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
    os.execvp(command[0], [*command, *args])  # noqa: S606 -- fixed Docker with pinned binary


if __name__ == "__main__":
    main()
