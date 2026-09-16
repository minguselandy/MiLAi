#!/usr/bin/env python3
"""Versioned readable container environment; paid launch stays disabled for the C0-C2 increment."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
CAPABILITIES = (
    "Container tools: python and python3 (standard library), jq, rg. "
    "For bounded UTF-8 file output use `milai-read PATH` (workspace-relative; "
    "4096 response bytes by default). Continue using --offset and --sha256 from next. "
    "Full source files and normal tools remain available."
)


def load_environment() -> dict:
    value = json.loads((LAB / "configs/v02-readable-environment.json").read_text())
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_id"]) is None:
        raise ValueError("IMMUTABLE_IMAGE_ID_REQUIRED")
    for name, expected in value["source_sha256"].items():
        if hashlib.sha256((LAB / name).read_bytes()).hexdigest() != expected:
            raise ValueError("READABLE_ENVIRONMENT_SOURCE_CHANGED")
    return value


def augment_profile(text: str) -> str:
    first, newline, rest = text.partition("\n")
    if not newline or not first.startswith("developer_instructions = "):
        raise ValueError("PINNED_LAUNCHER_PROFILE_FORMAT_REQUIRED")
    # The pinned launcher emits a JSON-quoted string on this first TOML line.
    # Keep the remaining bytes unchanged; the host's python3 need not provide tomllib.
    instructions = json.loads(first.partition("=")[2].strip()) + "\n" + CAPABILITIES
    result = ("developer_instructions = " + json.dumps(instructions, ensure_ascii=False)
              + "\n" + rest)
    return result


def docker_command(image: str, workspace: Path, home: Path, binary: Path, rg_binary: Path,
                   name: str, *, network: str = "host",
                   entrypoint: str = "/opt/codex/bin/codex") -> list[str]:
    return [
        "docker", "run", "--rm", "--pull=never", "--name", name,
        "--network", network, "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=128m",  # noqa: S108
        "--memory", "2g", "--cpus", "2",
        "--mount", f"type=bind,src={home},dst={home}",
        "--mount", f"type=bind,src={workspace},dst={workspace}",
        "--mount", f"type=bind,src={workspace / 'sources'},dst={workspace / 'sources'},readonly",
        "--mount", f"type=bind,src={binary.parent},dst=/opt/codex/bin,readonly",
        "--mount", "type=bind,src=/etc/ssl/certs,dst=/etc/ssl/certs,readonly",
        "--mount", f"type=bind,src={rg_binary},dst=/usr/local/bin/rg,readonly",
        "--env", f"CODEX_HOME={home}", "--env", f"V02_WORKSPACE={workspace}",
        "--env", "MILAI_CODEX_LAUNCHER_TOKEN",
        "--env", "HTTPS_PROXY", "--env", "HTTP_PROXY", "--env", "NO_PROXY",
        "--env", "https_proxy", "--env", "http_proxy", "--env", "no_proxy",
        "--workdir", str(workspace), "--entrypoint", entrypoint, image,
    ]


def main() -> None:
    config = load_environment()
    if not config["model_execution_authorized"] or not config["provider_cost_control_verified"]:
        raise RuntimeError("C3_NOT_AUTHORIZED_OR_COST_CONTROL_UNVERIFIED")
    home, workspace = Path(os.environ["CODEX_HOME"]), Path(os.environ["V02_WORKSPACE"])
    args = sys.argv[1:]
    profile = home / (args[args.index("-p") + 1] + ".config.toml")
    profile.write_text(augment_profile(profile.read_text()))
    command = docker_command(config["image_id"], workspace, home,
                             Path(os.environ["V02_CODEX_BINARY"]),
                             Path(os.environ["V02_RG_BINARY"]), os.environ["V02_CONTAINER_NAME"])
    os.execvp(command[0], [*command, *args])  # noqa: S606 -- fixed isolated Docker command


if __name__ == "__main__":
    main()
