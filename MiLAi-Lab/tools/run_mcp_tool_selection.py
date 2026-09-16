#!/usr/bin/env python3
"""Run one preregistered, zero-Skill MiLA MCP tool-selection arm."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALL_TOOLS = (
    "milai_memory_resolve",
    "milai_memory_get",
    "milai_evidence_capture",
    "milai_proposal_create",
    "milai_proposals_list",
    "milai_proposal_get",
    "milai_memory_review",
    "milai_evidence_revoke",
    "milai_deletion_status_get",
    "milai_namespace_cleanup_submit",
    "milai_namespace_cleanup_status",
    "milai_working_state_get",
    "milai_working_state_update",
)
READ_ONLY_TOOLS = (
    "milai_memory_resolve",
    "milai_memory_get",
    "milai_proposals_list",
    "milai_proposal_get",
    "milai_deletion_status_get",
    "milai_namespace_cleanup_status",
    "milai_working_state_get",
)
IMPLICIT_PROMPT = (
    "Continue the previous work in this repository. Determine the current highest-priority "
    "unfinished objective and report the next concrete action. This is a read-only audit: do not "
    "edit files or change services."
)
EXPLICIT_PROMPT = (
    "Call milai_working_state_get exactly once with TASK scope. Do not use shell, files, web, or "
    "any other tool. Return only its status and version."
)


@dataclass(frozen=True, slots=True)
class Arm:
    prompt: str
    enabled_tools: tuple[str, ...] | None
    expected_tool: str


ARMS = {
    "s0": Arm(EXPLICIT_PROMPT, ALL_TOOLS, "milai_working_state_get"),
    "s1": Arm(
        IMPLICIT_PROMPT,
        ("milai_working_state_get", "milai_working_state_update"),
        "milai_working_state_get",
    ),
    "s2": Arm(
        IMPLICIT_PROMPT,
        (
            "milai_memory_resolve",
            "milai_working_state_get",
            "milai_working_state_update",
        ),
        "milai_working_state_get",
    ),
    "s3": Arm(IMPLICIT_PROMPT, None, "milai_working_state_get"),
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _events(stdout: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed.append(value)
    return parsed


def _item(event: dict[str, Any]) -> dict[str, Any] | None:
    direct = event.get("item")
    if isinstance(direct, dict):
        return direct
    wrapped = event.get("event")
    if isinstance(wrapped, dict) and isinstance(wrapped.get("item"), dict):
        return dict(wrapped["item"])
    return None


def _event_type(event: dict[str, Any]) -> str | None:
    direct = event.get("type")
    if isinstance(direct, str):
        return direct
    wrapped = event.get("event")
    if isinstance(wrapped, dict) and isinstance(wrapped.get("type"), str):
        return str(wrapped["type"])
    return None


def _summary(events: list[dict[str, Any]], expected_tool: str) -> dict[str, Any]:
    started_actions: list[dict[str, Any]] = []
    completed_mcp: list[dict[str, Any]] = []
    for event in events:
        item = _item(event)
        if item is None:
            continue
        event_type = _event_type(event)
        item_type = item.get("type")
        if event_type == "item.started" and item_type in {
            "mcp_tool_call",
            "command_execution",
        }:
            started_actions.append(
                {
                    "type": item_type,
                    "server": item.get("server"),
                    "tool": item.get("tool"),
                    "status": item.get("status"),
                }
            )
        if event_type == "item.completed" and item_type == "mcp_tool_call":
            completed_mcp.append(
                {
                    "server": item.get("server"),
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                }
            )
    expected = [call for call in completed_mcp if call["tool"] == expected_tool]
    return {
        "first_action": started_actions[0] if started_actions else None,
        "started_action_count": len(started_actions),
        "completed_mcp_calls": completed_mcp,
        "mcp_call_count": len(completed_mcp),
        "expected_tool_selected": bool(expected),
        "expected_tool_succeeded": any(call["status"] == "completed" for call in expected),
    }


def _skill_diagnostics(events: list[dict[str, Any]], stderr: str) -> dict[str, Any]:
    """Separate repository text echoed by shell commands from injected Skill context."""
    command_output_echoes = 0
    non_command_event_hits = 0
    for event in events:
        serialized = json.dumps(event, ensure_ascii=False)
        if "<skills_instructions>" not in serialized:
            continue
        item = _item(event)
        if item is not None and item.get("type") == "command_execution":
            command_output_echoes += 1
        else:
            non_command_event_hits += 1
    warning = "Exceeded skills context budget" in (
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + stderr
    )
    return {
        "skill_instruction_block": non_command_event_hits > 0,
        "skill_instruction_block_observation": (
            "NON_COMMAND_EVENT_OBSERVED"
            if non_command_event_hits
            else "NOT_OBSERVED_IN_CODEX_EVENTS"
        ),
        "skill_literal_command_output_echo_count": command_output_echoes,
        "skill_literal_non_command_event_count": non_command_event_hits,
        "skill_context_budget_warning": warning,
    }


def _result(
    *,
    arm_name: str,
    arm: Arm,
    stdout: str,
    stderr: str,
    process_exit_code: int,
) -> dict[str, Any]:
    events = _events(stdout)
    summary = _summary(events, arm.expected_tool)
    diagnostics = _skill_diagnostics(events, stderr)
    return {
        "schema_version": "milai-mcp-tool-selection-run-v0.2",
        "arm": arm_name.upper(),
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "prompt_sha256": _sha256(arm.prompt),
        "enabled_tools": list(arm.enabled_tools) if arm.enabled_tools else "ALL_13",
        "automatic_host_prefetch": False,
        "automatic_host_checkpoint": False,
        **diagnostics,
        "process_exit_code": process_exit_code,
        "events_sha256": _sha256(stdout),
        "stderr_sha256": _sha256(stderr),
        "valid": (
            process_exit_code == 0
            and not diagnostics["skill_instruction_block"]
            and not diagnostics["skill_context_budget_warning"]
        ),
        **summary,
    }


def _command(
    *,
    codex: str,
    arm: Arm,
    mcp_url: str,
    output: Path,
) -> list[str]:
    command = [
        codex,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "skill_search",
        "--disable",
        "recommended_plugins",
        "--disable",
        "enable_mcp_apps",
        "--disable",
        "multi_agent",
        "-m",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="xhigh"',
        "-c",
        'approval_policy="never"',
        "-c",
        f"mcp_servers.milai.url={json.dumps(mcp_url)}",
        "-c",
        'mcp_servers.milai.bearer_token_env_var="MILAI_SELECTION_TOKEN"',
        "-c",
        "mcp_servers.milai.required=true",
        "-c",
        'mcp_servers.milai.default_tools_approval_mode="prompt"',
        "-c",
        "skills.include_instructions=false",
        "-c",
        "skills.bundled.enabled=false",
        "-s",
        "read-only",
        "-C",
        "/cra/memory/mx_memory/MiLAi-Product",
        "--json",
        "--output-last-message",
        str(output / "last-message.txt"),
    ]
    if arm.enabled_tools is not None:
        command.extend(
            [
                "-c",
                "mcp_servers.milai.enabled_tools="
                + json.dumps(list(arm.enabled_tools), separators=(",", ":")),
            ]
        )
    for tool in READ_ONLY_TOOLS:
        if arm.enabled_tools is None or tool in arm.enabled_tools:
            command.extend(
                [
                    "-c",
                    f'mcp_servers.milai.tools.{tool}.approval_mode="approve"',
                ]
            )
    command.append(arm.prompt)
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--mcp-url")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=480)
    parser.add_argument(
        "--reanalyze",
        action="store_true",
        help="Rebuild run.json from an existing immutable events.jsonl/stderr.log pair.",
    )
    args = parser.parse_args()

    arm = ARMS[args.arm]
    if args.reanalyze:
        stdout = (args.output / "events.jsonl").read_text(encoding="utf-8")
        stderr = (args.output / "stderr.log").read_text(encoding="utf-8")
        previous = json.loads((args.output / "run.json").read_text(encoding="utf-8"))
        result = _result(
            arm_name=args.arm,
            arm=arm,
            stdout=stdout,
            stderr=stderr,
            process_exit_code=int(previous["process_exit_code"]),
        )
        (args.output / "run.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(0 if result["valid"] else 1)

    if args.mcp_url is None or args.token_file is None:
        raise SystemExit("--mcp-url and --token-file are required unless --reanalyze is used")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True, mode=0o700)
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("selection-test bearer token is missing or too short")
    codex = shutil.which("codex")
    if codex is None:
        raise SystemExit("codex executable not found")

    command = _command(codex=codex, arm=arm, mcp_url=args.mcp_url, output=args.output)
    environment = dict(os.environ)
    environment["MILAI_SELECTION_TOKEN"] = token
    completed = subprocess.run(  # noqa: S603 - explicit resolved Codex executable
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
        timeout=args.timeout_seconds,
        check=False,
    )
    (args.output / "events.jsonl").write_text(completed.stdout, encoding="utf-8")
    (args.output / "stderr.log").write_text(completed.stderr, encoding="utf-8")

    result = _result(
        arm_name=args.arm,
        arm=arm,
        stdout=completed.stdout,
        stderr=completed.stderr,
        process_exit_code=completed.returncode,
    )
    (args.output / "run.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
