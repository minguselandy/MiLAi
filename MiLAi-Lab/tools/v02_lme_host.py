"""Reuse the full v0.2 Host profile and container, with LME phase receipts."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import run_v02_memory_flow as base


def watch_process(process: subprocess.Popen[Any], events: Path, started: float,
                  timeout_seconds: float, tool_limit: int,
                  stop: Callable[[], None]) -> str | None:
    while process.poll() is None:
        reason = None
        if time.perf_counter() - started > timeout_seconds:
            reason = "SESSION_TIMEOUT"
        elif base.tool_action_count(base.parse_events(events)) >= tool_limit:
            reason = "TOOL_WATCHDOG"
        if reason:
            stop()
            process.wait(timeout=15)
            return reason
        time.sleep(0.2)
    return None


def run_host(root: Path, observation: Path, workspace: Path, environment: dict[str, str],
             config: dict[str, Any], prompt: str, task: str, project: str,
             before: dict[str, Any], call: Callable[..., dict[str, Any]],
             timeout_seconds: float, opportunity: str | None = None) -> dict[str, Any]:
    home = workspace.parent / "home"
    home.mkdir(mode=0o700)
    auth = home / "auth.json"
    shutil.copyfile(Path.home() / ".codex/auth.json", auth)
    auth.chmod(0o600)
    try:
        cache = Path.home() / ".codex/models_cache.json"
        shutil.copyfile(cache, home / "models_cache.json")
        base.write_json(observation / "model-catalog-identity.json", {
            "sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
            "selected_model": config["model"],
            "selected_metadata": [m for m in base.read_json(cache)["models"]
                                  if m.get("slug") == config["model"]],
        })
        base.write_json(observation / "host-paths.json", {"home": str(home),
                                                        "workspace": str(workspace)})
        (home / "config.toml").write_text(base.codex_config(config, opportunity))
        shutil.copyfile(home / "config.toml", observation / "host-config.toml")
        (observation / "user-prompt.txt").write_text(prompt, encoding="utf-8")
        name = "v02-host-" + secrets.token_hex(8)
        environment.update({"CODEX_HOME": str(home), "V02_WORKSPACE": str(workspace),
                            "V02_OBSERVER": str(observation), "V02_CONTAINER_NAME": name,
                            "V02_CODEX_BINARY": str(Path(shutil.which("codex") or "").resolve()),
                            "V02_RG_BINARY": str(Path(shutil.which("rg") or "").resolve())})
        args = [str(base.MCP / ".venv/bin/milai"), "codex", "--cwd", str(workspace),
                "--project-id", project, "--principal-id", "v02-lme-host", "--task-ref", task,
                "--codex-bin", str(base.LAB / config.get(
                    "codex_wrapper", "tools/v02_codex_container.py")),
                "--mcp-server-bin", str(base.MCP / ".venv/bin/milai-codex-full-mcp"),
                "--", "exec", "--ephemeral", "--skip-git-repo-check", "--json",
                "--output-last-message", str(workspace / "answer.txt"), prompt]
        started = time.perf_counter()
        start_wall = time.time()
        stop_reason = None
        with (observation / "events.jsonl").open("w") as output, (
            observation / "host.stderr"
        ).open("w") as errors:
            process = subprocess.Popen(  # noqa: S603 -- pinned public launcher
                args, env=base._clean_environment(environment), stdout=output, stderr=errors,
                text=True, start_new_session=True,
            )
            base.write_json(observation / "process.json", {"pid": process.pid, "container": name,
                                                          "launched_at": start_wall})
            def stop() -> None:
                base._command(["docker", "stop", "--time", "1", name], check=False)
                os.killpg(process.pid, signal.SIGTERM)

            stop_reason = watch_process(process, observation / "events.jsonl", started,
                                        timeout_seconds, config["tool_call_watchdog"], stop)
            process.wait(timeout=15)
        host_done = time.perf_counter()
        after = call("milai_working_state_get", {"scope": "TASK"})
        base.write_json(observation / "after.json", after)
        events = [e for e in base.parse_events(observation / "events.jsonl")
                  if e.get("item", {}).get("type") != "reasoning"]
        (observation / "events.jsonl").write_text("".join(
            json.dumps(e, ensure_ascii=False) + "\n" for e in events
        ), encoding="utf-8")
        usage = [e.get("usage") for e in events if e.get("type") == "turn.completed"]
        result = {"returncode": process.returncode, "stop_reason": stop_reason,
                  "elapsed_seconds": time.perf_counter() - started,
                  "phase_seconds": {"host_online": host_done - started,
                                    "after_state_confirmation": time.perf_counter() - host_done},
                  "usage": usage or None, "before_version": before["version"],
                  "after_version": after["version"],
                  "save_status": base.save_status(events, before, after),
                  "save_attempts": [e for e in events if e.get("type") == "item.completed" and
                                    e.get("item", {}).get("tool") == "milai_working_state_update"],
                  "semantic_evaluation": "PENDING_SEPARATE_REVIEW",
                  "later_model_inputs": "UNOBSERVED"}
        base.write_json(observation / "result.json", result)
        if (workspace / "answer.txt").exists():
            shutil.copyfile(workspace / "answer.txt", observation / "answer.txt")
        return result
    finally:
        auth.unlink(missing_ok=True)
