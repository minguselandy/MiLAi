#!/usr/bin/env python3
"""Bounded real-Host memory experiment using pinned public Product entrypoints."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock
from run_product09_codex_lifecycle import (
    ALEMBIC_EXE,
    API_EXE,
    HOOKS,
    LAB,
    MCP,
    PRODUCT,
    RUNTIME,
    WORKER_EXE,
    ProcessGroup,
    _capture,
    _clean_environment,
    _command,
    _free_port,
    _load_environment,
    _wait_http,
    _wait_projection,
)
from v02_task_artifacts import carry_task_artifacts

CONFIG = LAB / "configs/v02-memory-flow.json"
FIXTURES = LAB / "data/fixtures/v02-memory-flow"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pin(config_path: Path = CONFIG) -> dict[str, Any]:
    config = read_json(config_path)
    lock = load_product_lock(LAB / config["product_lock"])
    result = verify_product_lock(lock, PRODUCT).to_dict()
    if not result["valid"]:
        raise RuntimeError("Product pin failed; no effect run allowed")
    return result


def installed_identity() -> dict[str, Any]:
    result = {}
    for package, module in ((RUNTIME, "milai"), (MCP, "milai_mcp"), (HOOKS, "milai_hooks")):
        code = (
            "import importlib.util,json; "
            f"print(json.dumps(importlib.util.find_spec('{module}').origin))"
        )
        origin = Path(json.loads(_command(
            [str(package / ".venv/bin/python"), "-c", code], cwd=package
        ).stdout)).resolve()
        expected = package / "src" / module / "__init__.py"
        if origin != expected:
            raise RuntimeError(f"Installed {module} does not resolve to the pinned source")
        result[module] = {"module_origin": str(origin), "interpreter": str(
            package / ".venv/bin/python"
        )}
    return result


def prepare(root: Path, *, config_path: Path = CONFIG,
            runtime_overrides: dict[str, str] | None = None,
            compose_override: Path | None = None) -> None:
    verification = pin(config_path)
    identity = installed_identity()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_json(root / "product-pin.json", verification)
    write_json(root / "installed-artifact.json", identity)
    shutil.copyfile(config_path, root / "config.json")
    env_file = root / "runtime.env"
    _command([
        str(RUNTIME / ".venv/bin/milai-ops"), "init", "--env-file", str(env_file),
        "--blob-root", str(root / "blobs"), "--postgres-port", str(_free_port()),
        "--api-port", str(_free_port()),
    ], cwd=RUNTIME)
    if runtime_overrides:
        with env_file.open("a") as output:
            for key, value in runtime_overrides.items():
                output.write(f"\n{key}={value}\n")
    env = _load_environment(env_file)
    compose = ["docker", "compose", "--project-name", root.name + "-pg", "--env-file",
               str(env_file), "--file", str(RUNTIME / "compose.yaml")]
    if compose_override is not None:
        compose.extend(["--file", str(compose_override)])
    write_json(root / "compose-command.json", compose)
    _command([*compose, "up", "--detach", "--wait", "postgres"], cwd=RUNTIME, timeout=120)
    migrated = _command([str(ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                        cwd=RUNTIME, env=_clean_environment(env), timeout=180)
    (root / "migration.log").write_text(migrated.stdout + migrated.stderr)
    processes = ProcessGroup(root)
    api = processes.start("api", [str(API_EXE)], cwd=RUNTIME, env=_clean_environment(env))
    worker = processes.start("worker", [str(WORKER_EXE)], cwd=RUNTIME,
                             env=_clean_environment(env))
    write_json(root / "services.json", {"api": api.pid, "worker": worker.pid})
    _wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
    write_json(root / "prepared.json", {"status": "READY", "base_url": env["MILAI_BASE_URL"],
                                        "created_at": time.time()})
    print(json.dumps({"root": str(root), "status": "READY"}), flush=True)


def assert_services(root: Path) -> None:
    for name, pid in read_json(root / "services.json").items():
        proc = Path(f"/proc/{pid}")
        if not proc.exists():
            raise RuntimeError(f"Run-owned {name} process is absent; inspect before restarting")
        cmdline = (proc / "cmdline").read_bytes()
        if str(root).encode() not in (proc / "environ").read_bytes() or (
            f"milai-{name}".encode() not in cmdline
        ):
            raise RuntimeError(f"Run-owned {name} process identity does not match")


async def mcp_call(url: str, token: str, tool: str | None,
                   arguments: dict[str, Any]) -> dict[str, Any]:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
            if tool is None:
                catalog = await client.list_tools()
                return {"server_info": client.server_info.model_dump(mode="json"),
                        "instructions": client.instructions,
                        "tools": catalog.model_dump(mode="json", by_alias=True)}
            response = await client.call_tool(tool, arguments)
            return response.model_dump(mode="json", by_alias=True)


def structured(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("isError"):
        return {"mcp_error": True, "content": response.get("content", [])}
    result = response.get("structuredContent")
    if isinstance(result, dict):
        return result
    for block in response.get("content", []):
        if block.get("type") == "text":
            parsed = json.loads(block["text"])
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError("MCP returned no structured object")


def remap_snapshot(payload: dict[str, Any], old_sources: list[dict[str, Any]],
                   new_sources: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    old_by_name = {item["filename"]: item["receipt"]["evidence_id"] for item in old_sources}
    new_by_name = {item["filename"]: item["receipt"]["evidence_id"] for item in new_sources}
    if old_by_name.keys() != new_by_name.keys():
        raise ValueError("Snapshot branches must have identical source filenames")
    mapping = {old_id: new_by_name[name] for name, old_id in old_by_name.items()}

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, str):
            for old, new in mapping.items():
                value = value.replace(old, new)
        return value

    return visit(payload), mapping


def save_status(events: list[dict[str, Any]], before: dict[str, Any],
                after: dict[str, Any]) -> str:
    attempts = [e["item"] for e in events if
                e.get("item", {}).get("tool") == "milai_working_state_update"]
    if after["version"] != before["version"]:
        return "COMMITTED_OBSERVED_HEAD"
    if not attempts:
        return "NOT_ATTEMPTED"
    completed = [item for item in attempts if item.get("status") in ("completed", "failed")]
    if not completed:
        return "OUTCOME_UNKNOWN"
    encoded = json.dumps(completed)
    if "WORKING_STATE_OUTCOME_UNKNOWN" in encoded:
        return "OUTCOME_UNKNOWN"
    if "CONFLICT" in encoded.upper() or "STALE_WORKING_STATE" in encoded:
        return "CONFLICT"
    if any(item.get("error") or item.get("status") == "failed" or
           item.get("result", {}).get("isError") or
           item.get("result", {}).get("is_error") for item in completed):
        return "FAILED"
    return "NO_PERSISTENT_CHANGE_OBSERVED"


def codex_config(config: dict[str, Any], host_opportunity: str | None = None) -> str:
    return (
        f"model = {json.dumps(config['model'])}\n"
        f"model_reasoning_effort = {json.dumps(config['reasoning_effort'])}\n"
        f"service_tier = {json.dumps(config['service_tier'])}\n"
        + (f"developer_instructions = {json.dumps(host_opportunity, ensure_ascii=False)}\n"
           if host_opportunity else "")
        +
        'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
        'web_search = "disabled"\nhide_agent_reasoning = true\n'
        "skills.include_instructions = false\nskills.bundled.enabled = false\n"
        "[features]\nskill_search = false\nrecommended_plugins = false\n"
        "enable_mcp_apps = false\nmulti_agent = false\nmemories = false\n"
        "[features.rollout_budget]\nenabled = true\n"
        f"limit_tokens = {config['rollout_token_budget']}\n"
        f"reminder_at_remaining_tokens = {json.dumps(config['rollout_reminders_remaining'])}\n"
    )


def run_case(root: Path, case_path: Path, arm: str, session_id: str,
             snapshot: Path | None, followup: bool, task_ref: str | None,
             batch_id: str) -> None:
    verification = pin()
    assert_services(root)
    batch = root / "batches" / batch_id
    batch.mkdir(parents=True, exist_ok=True)
    if not (batch / "config.json").exists():
        shutil.copyfile(CONFIG, batch / "config.json")
    config = read_json(batch / "config.json")
    if read_json(CONFIG) != config:
        raise RuntimeError("Study config changed; use a new batch identity")
    runs = root / "sessions"
    runs.mkdir(exist_ok=True)
    previous = [p for p in runs.iterdir() if
                read_json(p / "allocation.json").get("batch_id", "initial") == batch_id]
    if len(previous) >= config["batch_session_limit"]:
        raise RuntimeError("Preregister a new batch before allocating more sessions")
    if previous:
        first = min(read_json(p / "allocation.json")["started_at"] for p in previous)
        if time.time() - first > config["batch_wall_seconds"]:
            raise RuntimeError("Batch wall budget exhausted; preregister the next batch")
    observation = runs / session_id
    observation.mkdir(mode=0o700)
    case = read_json(case_path)
    task = task_ref or secrets.token_hex(12)
    project = "v02-" + task
    write_json(observation / "allocation.json", {
        "started_at": time.time(), "case_id": case["case_id"], "arm": arm,
        "batch_id": batch_id,
        "followup": followup, "task_ref": task, "project": project,
        "fixture_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "source_snapshot": str(snapshot) if snapshot else None,
        "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "wrapper_sha256": hashlib.sha256((LAB / "tools/v02_codex_container.py").read_bytes()
                                         ).hexdigest(),
        "product_pin": verification,
    })
    env = _load_environment(root / "runtime.env")
    env.update({"MILAI_CODEX_PRINCIPAL_ID": "v02-host", "MILAI_CODEX_TASK_REF": task,
                "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]})})
    group = ProcessGroup(observation)
    token = secrets.token_urlsafe(32)
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    env.update({"MILAI_CODEX_TOKEN": token,
                "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}"})
    try:
        mcp = group.start("observer-mcp", [str(MCP / ".venv/bin/milai-codex-full-mcp"),
                                          "--port", str(port)], cwd=MCP,
                          env=_clean_environment(env))
        _wait_http(f"http://127.0.0.1:{port}/readyz", mcp)
        def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return structured(asyncio.run(mcp_call(url, token, tool, arguments)))
        write_json(observation / "tool-catalog.json", asyncio.run(mcp_call(url, token, None, {})))
        state = call("milai_working_state_get", {"scope": "TASK"})
        if state["status"] == "ABSENT":
            capture_start = time.perf_counter()
            receipts = []
            for ordinal, (filename, content) in enumerate(case["sources"].items()):
                event = {
                    "schema_version": "host-agent-event-v1", "event_id": f"{task}-{ordinal}",
                    "event_type": "USER_MESSAGE", "session_id": f"sources-{task}",
                    "source_id": f"sources/{filename}", "subject_id": "v02-synthetic-user",
                    "observed_at": "2026-09-05T00:00:00Z", "content": content,
                    "turn_id": f"source-{ordinal}", "turn_ordinal": ordinal,
                    "round_id": f"source-{ordinal}", "round_ordinal": ordinal,
                }
                receipt = _capture(env, project=project, event=event)
                receipts.append({"filename": filename, **receipt})
            ready = _wait_projection(env, [r["receipt"]["outbox_id"] for r in receipts])
            write_json(observation / "source-receipts.json", receipts)
            write_json(observation / "source-preparation.json", {
                "elapsed_seconds": time.perf_counter() - capture_start, "readiness": ready,
            })
            payload = read_json(snapshot)["payload"] if snapshot else case["initial_payload"]
            # Branch-specific Evidence IDs are mapped by source filename, not copied across scopes.
            if snapshot:
                old_sources = read_json(snapshot.parent / "source-receipts.json")
                payload, mapping = remap_snapshot(payload, old_sources, receipts)
                write_json(observation / "branch-evidence-map.json", mapping)
            seed = call("milai_working_state_update", {
                "operation_id": "initialize-" + task, "expected_version": 0, "payload": payload,
            })
            write_json(observation / "initialization-receipt.json", seed)
            state = call("milai_working_state_get", {"scope": "TASK"})
        elif not followup or snapshot:
            raise RuntimeError("An initial arm requires an absent isolated State")
        if state["status"] != "ACTIVE":
            raise RuntimeError("Initial State is not ACTIVE")
        write_json(observation / "before.json", state)
        host_session = root / "host-sessions" / secrets.token_hex(12)
        workspace = host_session / "workspace"
        source_dir = workspace / "sources"
        source_dir.mkdir(parents=True)
        for filename, content in case["sources"].items():
            (source_dir / filename).write_text(content, encoding="utf-8")
        prior_session = snapshot.parent if snapshot else None
        if followup and prior_session is None:
            same_task = [p for p in runs.iterdir() if (p / "result.json").exists() and
                         read_json(p / "allocation.json")["task_ref"] == task]
            if same_task:
                prior_session = max(same_task, key=lambda p: read_json(
                    p / "allocation.json"
                )["started_at"])
        if prior_session is not None:
            paths = read_json(prior_session / "host-paths.json")
            manifest = carry_task_artifacts(Path(paths["workspace"]), workspace)
            write_json(observation / "task-artifacts.json", {
                "source_session": str(prior_session), "files": manifest,
                "excluded": "CLI answer.txt transcript, original sources, tool caches",
            })
        home = host_session / "home"
        home.mkdir(mode=0o700)
        auth = Path.home() / ".codex/auth.json"
        shutil.copyfile(auth, home / "auth.json")
        (home / "auth.json").chmod(0o600)
        cache = Path.home() / ".codex/models_cache.json"
        shutil.copyfile(cache, home / "models_cache.json")
        write_json(observation / "model-catalog-identity.json", {
            "sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
            "selected_model": config["model"],
            "selected_metadata": [m for m in read_json(cache)["models"]
                                  if m.get("slug") == config["model"]],
        })
        write_json(observation / "host-paths.json", {"home": str(home),
                                                    "workspace": str(workspace)})
        (home / "config.toml").write_text(codex_config(
            config, config["host_opportunity"] if arm == "H1" else None
        ))
        shutil.copyfile(home / "config.toml", observation / "host-config.toml")
        prompt = case["followup"] if followup else case["task"]
        if arm == "A1":
            prompt += "\n" + config["a1"]
        (observation / "user-prompt.txt").write_text(prompt, encoding="utf-8")
        container = "v02-host-" + secrets.token_hex(8)
        env.update({"CODEX_HOME": str(home), "V02_WORKSPACE": str(workspace),
                    "V02_OBSERVER": str(observation), "V02_CONTAINER_NAME": container,
                    "V02_CODEX_BINARY": str(Path(shutil.which("codex") or "").resolve()),
                    "V02_RG_BINARY": str(Path(shutil.which("rg") or "").resolve())})
        wrapper = LAB / "tools/v02_codex_container.py"
        args = [str(MCP / ".venv/bin/milai"), "codex", "--cwd", str(workspace),
                "--project-id", project, "--principal-id", "v02-host", "--task-ref", task,
                "--codex-bin", str(wrapper), "--mcp-server-bin",
                str(MCP / ".venv/bin/milai-codex-full-mcp"), "--", "exec", "--ephemeral",
                "--skip-git-repo-check", "--json", "--output-last-message",
                str(workspace / "answer.txt"), prompt]
        started = time.perf_counter()
        with (observation / "events.jsonl").open("w") as output, (
            observation / "host.stderr"
        ).open("w") as errors:
            process = subprocess.Popen(  # noqa: S603 -- pinned public launcher
                args, env=_clean_environment(env), stdout=output, stderr=errors,
                text=True, start_new_session=True,
            )
            write_json(observation / "process.json", {"pid": process.pid, "container": container})
            stop_reason = None
            while process.poll() is None:
                elapsed = time.perf_counter() - started
                events = parse_events(observation / "events.jsonl")
                count = tool_action_count(events)
                if elapsed > config["session_timeout_seconds"]:
                    stop_reason = "SESSION_TIMEOUT"
                elif count >= config["tool_call_watchdog"]:
                    stop_reason = "TOOL_WATCHDOG"
                if stop_reason:
                    _command(["docker", "stop", "--time", "1", container], check=False)
                    os.killpg(process.pid, signal.SIGTERM)
                    break
                time.sleep(0.2)
            process.wait(timeout=15)
        after = call("milai_working_state_get", {"scope": "TASK"})
        write_json(observation / "after.json", after)
        events = parse_events(observation / "events.jsonl")
        # Codex exec may emit reasoning summaries even with hide_agent_reasoning=true.
        # Retain external actions and answers only, never reasoning items.
        events = [e for e in events if e.get("item", {}).get("type") != "reasoning"]
        (observation / "events.jsonl").write_text("".join(
            json.dumps(e, ensure_ascii=False) + "\n" for e in events
        ), encoding="utf-8")
        updates = [e for e in events if e.get("type") == "item.completed" and
                   e.get("item", {}).get("tool") == "milai_working_state_update"]
        usage = [e.get("usage") for e in events if e.get("type") == "turn.completed"]
        result = {"returncode": process.returncode, "stop_reason": stop_reason,
                  "elapsed_seconds": time.perf_counter() - started, "usage": usage or None,
                  "before_version": state["version"], "after_version": after["version"],
                  "save_attempts": updates, "state_changed": after["version"] != state["version"],
                  "save_status": save_status(events, state, after),
                  "semantic_evaluation": "PENDING", "later_model_inputs": "UNOBSERVED"}
        write_json(observation / "result.json", result)
        if (workspace / "answer.txt").exists():
            shutil.copyfile(workspace / "answer.txt", observation / "answer.txt")
        (home / "auth.json").unlink(missing_ok=True)
        print(json.dumps({"session": session_id, "returncode": process.returncode,
                          "before_version": state["version"], "after_version": after["version"],
                          "elapsed_seconds": result["elapsed_seconds"], "usage": usage or None,
                          "stop_reason": stop_reason}, ensure_ascii=False), flush=True)
    finally:
        group.stop()
        if (observation / "host-paths.json").exists():
            Path(read_json(observation / "host-paths.json")["home"]).joinpath("auth.json").unlink(
                missing_ok=True
            )


def parse_events(path: Path) -> list[dict[str, Any]]:
    result = []
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # A running writer may not have finished the last line yet.
        if isinstance(event, dict):
            result.append(event)
    return result


def tool_action_count(events: list[dict[str, Any]]) -> int:
    return len({e["item"]["id"] for e in events if
                e.get("item", {}).get("type") in
                ("mcp_tool_call", "command_execution", "file_change")})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "status"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--arm", choices=("A0", "A1", "H1"), default="A0")
    parser.add_argument("--session-id")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--followup", action="store_true")
    parser.add_argument("--task-ref")
    parser.add_argument("--batch-id", default="initial")
    args = parser.parse_args()
    for value in (args.run_id, args.session_id, args.task_ref, args.batch_id):
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", value):
            parser.error("Run/session/task IDs require lowercase letters, digits and hyphens")
    root = LAB / "artifacts/v02-memory-flow" / args.run_id
    if args.action == "prepare":
        prepare(root)
    elif args.action == "status":
        assert_services(root)
        print(json.dumps({"status": "LIVE_PROCESSES", "product": pin()}))
    else:
        if args.case is None or args.session_id is None:
            parser.error("run requires --case and --session-id")
        run_case(root, args.case, args.arm, args.session_id, args.snapshot,
                 args.followup, args.task_ref, args.batch_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
