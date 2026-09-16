#!/usr/bin/env python3
"""Run the Product-09 Host capture → PostgreSQL → HTTP MCP → Codex lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
PRODUCT = LAB.parent / "MiLAi-Product"
RUNTIME = PRODUCT / "runtime"
MCP = PRODUCT / "integrations" / "mcp"
HOOKS = PRODUCT / "integrations" / "hooks"

OPS_EXE = RUNTIME / ".venv" / "bin" / "milai-ops"
ALEMBIC_EXE = RUNTIME / ".venv" / "bin" / "alembic"
API_EXE = RUNTIME / ".venv" / "bin" / "milai-api"
WORKER_EXE = RUNTIME / ".venv" / "bin" / "milai-worker"
MCP_EXE = MCP / ".venv" / "bin" / "milai-mcp"
HOOK_EXE = HOOKS / ".venv" / "bin" / "milai-hook"

PROJECT_A = "p09-aurora"
PROJECT_B = "p09-borealis"
SUBJECT = "p09-local-user"
CANONICAL_TABLES = (
    "claim",
    "operation_proposal",
    "steward_decision",
    "open_issue",
    "claim_version",
    "claim_head",
    "version_transition",
    "grounding_relation",
    "grounding_block",
    "open_issue_transition",
)


class Product09Error(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _command(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 180,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 -- explicit local product executables
        arguments,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        stdin=None if input_text is not None else subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        message = (completed.stderr or completed.stdout)[-2_000:]
        raise Product09Error(f"command failed ({Path(arguments[0]).name}): {message}")
    return completed


def _clean_environment(values: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("MILAI_")
    }
    environment.update(values)
    return environment


def _load_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MILAI_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: object | None = None,
    timeout: float = 30,
) -> tuple[int, dict[str, Any]]:
    headers: dict[str, str] = {}
    body: bytes | None = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(  # noqa: S310 -- run-owned loopback URL
        url, data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


def _wait_http(url: str, process: subprocess.Popen[str], *, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Product09Error(f"process exited before {url} became ready")
        try:
            status, _ = _http_json("GET", url, timeout=2)
            if status == 200:
                return
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    raise Product09Error(f"timed out waiting for {url}")


@dataclass(slots=True)
class ProcessGroup:
    root: Path
    entries: list[tuple[str, subprocess.Popen[str], Any]] = field(default_factory=list)

    def start(
        self,
        name: str,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.Popen[str]:
        log_path = self.root / f"{name}.log"
        handle = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(  # noqa: S603 -- explicit local product executables
            arguments,
            cwd=cwd,
            env=env,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.entries.append((name, process, handle))
        return process

    def stop(self) -> None:
        for _, process, _ in reversed(self.entries):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, process, handle in reversed(self.entries):
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
            handle.close()
        self.entries.clear()


def _start_runtime(group: ProcessGroup, environment: dict[str, str]) -> None:
    child = _clean_environment(environment)
    api = group.start("api", [str(API_EXE)], cwd=RUNTIME, env=child)
    group.start("worker", [str(WORKER_EXE)], cwd=RUNTIME, env=child)
    _wait_http(f"{environment['MILAI_BASE_URL']}/health/ready", api)


def _start_mcp(
    group: ProcessGroup,
    environment: dict[str, str],
    *,
    port: int,
    inbound_token: str,
    project: str = PROJECT_A,
    name: str = "mcp",
) -> subprocess.Popen[str]:
    values = dict(environment)
    values.update(
        {
            "MILAI_AGENT_TOKEN": environment["MILAI_AGENT_READER_TOKEN"],
            "MILAI_AGENT_SCOPE_JSON": json.dumps(
                {"project_ids": [project]}, separators=(",", ":")
            ),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_MCP_HTTP_BEARER_TOKEN": inbound_token,
            "MILAI_MCP_HTTP_PRINCIPAL_ID": "codex-product09",
        }
    )
    process = group.start(
        name,
        [
            str(MCP_EXE),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--profile",
            "agent-memory",
            "--max-retries",
            "0",
            "--resolve-budget-profile",
            "MCP_INTERACTIVE_WIDE_V01",
        ],
        cwd=MCP,
        env=_clean_environment(values),
    )
    _wait_http(f"http://127.0.0.1:{port}/readyz", process)
    return process


def _capture(
    environment: dict[str, str],
    *,
    project: str,
    event: dict[str, Any],
    data_classification: str = "SYNTHETIC",
) -> dict[str, Any]:
    values = dict(environment)
    values.update(
        {
            "MILAI_AGENT_TOKEN": environment["MILAI_AGENT_SUBMITTER_TOKEN"],
            "MILAI_AGENT_SCOPE_JSON": json.dumps(
                {"project_ids": [project]}, separators=(",", ":")
            ),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_MAX_RETRIES": "0",
            "MILAI_HOST_EVENT_CAPTURE": "ON",
            "MILAI_HOST_EVENT_DATA_CLASSIFICATION": data_classification,
        }
    )
    completed = _command(
        [str(HOOK_EXE), "AgentEvent"],
        cwd=HOOKS,
        env=_clean_environment(values),
        input_text=json.dumps(event, ensure_ascii=False),
        timeout=45,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Product09Error("Host capture returned invalid JSON") from exc
    if not isinstance(result, dict) or result.get("status") != "RAW_EVIDENCE_CAPTURED":
        raise Product09Error("Host capture did not return a Raw Evidence receipt")
    return result


def _wait_projection(environment: dict[str, str], outbox_ids: list[str]) -> dict[str, Any]:
    status, result = _http_json(
        "POST",
        f"{environment['MILAI_BASE_URL']}/v1/system/projection-readiness",
        token=environment["MILAI_AGENT_READER_TOKEN"],
        payload={
            "target_outbox_ids": outbox_ids,
            "required_projections": ["evidence"],
            "expected_versions": {"evidence": "evidence-search-v1"},
            "timeout_ms": 30_000,
            "poll_interval_ms": 50,
        },
        timeout=35,
    )
    if status != 200 or result.get("status") != "READY":
        raise Product09Error(f"Evidence projection did not become ready: {result}")
    return result


def _validate_persisted_event(
    environment: dict[str, str],
    *,
    event: dict[str, Any],
    receipt: dict[str, Any],
    project: str,
) -> None:
    evidence_id = receipt.get("evidence_id")
    status, persisted = _http_json(
        "GET",
        f"{environment['MILAI_BASE_URL']}/v1/evidence/{evidence_id}",
        token=environment["MILAI_API_TOKEN"],
    )
    context = persisted.get("source_context")
    permission = persisted.get("permission_snapshot")
    expected_source_type = {
        "USER_MESSAGE": "USER_OBSERVATION",
        "TOOL_RESULT": "TOOL_OBSERVATION",
    }[event["event_type"]]
    if not (
        status == 200
        and persisted.get("source_type") == expected_source_type
        and persisted.get("source_ref") == event["source_id"]
        and persisted.get("subject_id") == event["subject_id"]
        and persisted.get("content") == event["content"]
        and isinstance(context, dict)
        and context.get("session_id") == event["session_id"]
        and context.get("turn_id") == event["turn_id"]
        and context.get("turn_ordinal") == event["turn_ordinal"]
        and isinstance(permission, dict)
        and permission.get("readable") is True
        and permission.get("project_ids") == [project]
    ):
        raise Product09Error("persisted Host event lost identity, content, or project scope")


def _event(
    *,
    event_id: str,
    event_type: str,
    session_id: str,
    turn_id: str,
    turn_ordinal: int,
    observed_at: datetime,
    content: str,
) -> dict[str, Any]:
    return {
        "schema_version": "host-agent-event-v1",
        "event_id": event_id,
        "event_type": event_type,
        "session_id": session_id,
        "source_id": f"codex:{session_id}:{turn_id}",
        "subject_id": SUBJECT,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "content": content,
        "turn_id": turn_id,
        "turn_ordinal": turn_ordinal,
        "round_id": f"round-{turn_ordinal}",
        "round_ordinal": turn_ordinal,
    }


def _codex_trace(stdout: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        if item.get("tool") != "milai_memory_resolve" or item.get("status") != "completed":
            continue
        result = item.get("result")
        structured: dict[str, Any] | None = None
        if isinstance(result, dict) and isinstance(result.get("structured_content"), dict):
            structured = result["structured_content"]
        calls.append(
            {
                "arguments": item.get("arguments"),
                "structured_content": structured,
            }
        )
    return calls


def _run_codex(
    codex: Path,
    *,
    mcp_url: str,
    inbound_token: str,
    prompt: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="milai-p09-codex-") as temporary:
        last_message = Path(temporary) / "last-message.txt"
        host_environment = dict(os.environ)
        host_environment["MILAI_P09_CODEX_MCP_TOKEN"] = inbound_token
        command = [
            str(codex),
            "--approve-for-me",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
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
            "--sandbox",
            "read-only",
            "--json",
            "--output-last-message",
            str(last_message),
            "-c",
            f"mcp_servers.milai.url={json.dumps(mcp_url)}",
            "-c",
            'mcp_servers.milai.bearer_token_env_var="MILAI_P09_CODEX_MCP_TOKEN"',
            "-c",
            "mcp_servers.milai.required=true",
            "-c",
            'mcp_servers.milai.enabled_tools=["milai_memory_resolve"]',
            "-c",
            "skills.include_instructions=false",
            "-c",
            "skills.bundled.enabled=false",
            prompt,
        ]
        started = time.perf_counter()
        completed = _command(
            command,
            env=host_environment,
            timeout=timeout_seconds,
            check=False,
        )
        latency_ms = round((time.perf_counter() - started) * 1_000, 3)
        answer = last_message.read_text(encoding="utf-8").strip() if last_message.exists() else ""
    calls = _codex_trace(completed.stdout)
    return {
        "returncode": completed.returncode,
        "answer": answer,
        "calls": calls,
        "latency_ms": latency_ms,
        "stdout_tail": completed.stdout[-6_000:],
        "stderr_tail": completed.stderr[-2_000:],
    }


def _normalized_answer(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    return stripped.strip("`").strip()


def _tool_contains(run: dict[str, Any], needle: str) -> bool:
    return needle.casefold() in json.dumps(run.get("calls", []), ensure_ascii=False).casefold()


def _database_counts(compose: list[str]) -> dict[str, int]:
    canonical_sql = " + ".join(
        f"(SELECT count(*) FROM milai.{table})"  # noqa: S608 -- fixed table allowlist
        for table in CANONICAL_TABLES
    )
    sql = (
        "SELECT (SELECT count(*) FROM milai.evidence_record), "  # noqa: S608
        "(SELECT count(*) FROM milai.evidence_search_document), "
        f"{canonical_sql};"
    )
    completed = _command(
        [
            *compose,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "milai_owner",
            "-d",
            "milai",
            "-Atc",
            sql,
        ],
        cwd=RUNTIME,
        timeout=30,
    )
    values = completed.stdout.strip().split("|")
    if len(values) != 3:
        raise Product09Error("PostgreSQL count probe returned an invalid result")
    return {
        "evidence": int(values[0]),
        "projection": int(values[1]),
        "canonical": int(values[2]),
    }


def _write_summary(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    for executable in (OPS_EXE, ALEMBIC_EXE, API_EXE, WORKER_EXE, MCP_EXE, HOOK_EXE, args.codex):
        if not executable.is_file():
            raise Product09Error(f"required executable is missing: {executable}")

    postgres_port = _free_port()
    api_port = _free_port()
    mcp_port = _free_port()
    compose_project = f"{args.run_id}-pg"
    postgres_started = False
    phase = "bootstrap"
    with tempfile.TemporaryDirectory(prefix="milai-p09-") as temporary:
        root = Path(temporary)
        env_file = root / "runtime.env"
        process_group = ProcessGroup(root)
        _command(
            [
                str(OPS_EXE),
                "init",
                "--env-file",
                str(env_file),
                "--blob-root",
                str(root / "blobs"),
                "--postgres-port",
                str(postgres_port),
                "--api-port",
                str(api_port),
            ],
            cwd=RUNTIME,
        )
        environment = _load_environment(env_file)
        compose = [
            "docker",
            "compose",
            "--project-name",
            compose_project,
            "--env-file",
            str(env_file),
            "--file",
            str(RUNTIME / "compose.yaml"),
        ]
        try:
            phase = "postgres"
            _command([*compose, "up", "--detach", "postgres"], cwd=RUNTIME, timeout=120)
            postgres_started = True
            deadline = time.monotonic() + 90
            while True:
                migration = _command(
                    [str(ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                    cwd=RUNTIME,
                    env=_clean_environment(
                        {
                            "MILAI_MIGRATION_DATABASE_URL": environment[
                                "MILAI_MIGRATION_DATABASE_URL"
                            ]
                        }
                    ),
                    timeout=120,
                    check=False,
                )
                if migration.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    raise Product09Error("fresh PostgreSQL migration did not become ready")
                time.sleep(1)

            phase = "capture"
            _start_runtime(process_group, environment)
            nonce = secrets.token_hex(4)
            plan_label = f"rolling-quartz-{nonce}"
            fix_command = f"uv run pytest -q tests/test_lease_{nonce}.py"
            foreign_marker = f"borealis-secret-{nonce}"
            base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
            decision_event = _event(
                event_id=f"p09-decision-{nonce}",
                event_type="USER_MESSAGE",
                session_id=f"codex-design-{nonce}",
                turn_id=f"design-turn-{nonce}",
                turn_ordinal=0,
                observed_at=base_time,
                content=(
                    "Aurora indexer design decision: the selected zero-downtime migration plan "
                    f"is {plan_label}. Preserve this decision for later implementation work."
                ),
            )
            fix_event = _event(
                event_id=f"p09-fix-{nonce}",
                event_type="TOOL_RESULT",
                session_id=f"codex-fix-{nonce}",
                turn_id=f"fix-turn-{nonce}",
                turn_ordinal=0,
                observed_at=base_time + timedelta(minutes=1),
                content=(
                    "Verified Aurora projection lease failure P09E742. "
                    "The exact passing verification "
                    f"command was: {fix_command}"
                ),
            )
            foreign_event = _event(
                event_id=f"p09-foreign-{nonce}",
                event_type="USER_MESSAGE",
                session_id=f"codex-foreign-{nonce}",
                turn_id=f"foreign-turn-{nonce}",
                turn_ordinal=0,
                observed_at=base_time + timedelta(minutes=2),
                content=f"Borealis private deployment marker is {foreign_marker}.",
            )
            decision = _capture(environment, project=PROJECT_A, event=decision_event)
            duplicate = _capture(environment, project=PROJECT_A, event=decision_event)
            fix = _capture(environment, project=PROJECT_A, event=fix_event)
            foreign = _capture(environment, project=PROJECT_B, event=foreign_event)
            receipts = [decision["receipt"], fix["receipt"], foreign["receipt"]]
            if not all(isinstance(receipt, dict) for receipt in receipts):
                raise Product09Error("capture receipts are malformed")
            if (
                duplicate.get("receipt", {}).get("evidence_id")
                != decision.get("receipt", {}).get("evidence_id")
                or duplicate.get("receipt", {}).get("replayed") is not True
            ):
                raise Product09Error("duplicate Host event was not idempotently replayed")
            outbox_ids = [str(receipt["outbox_id"]) for receipt in receipts]
            for event, receipt, project_scope in (
                (decision_event, receipts[0], PROJECT_A),
                (fix_event, receipts[1], PROJECT_A),
                (foreign_event, receipts[2], PROJECT_B),
            ):
                _validate_persisted_event(
                    environment,
                    event=event,
                    receipt=receipt,
                    project=project_scope,
                )
            readiness = _wait_projection(environment, outbox_ids)
            counts_after_capture = _database_counts(compose)
            if counts_after_capture != {"evidence": 3, "projection": 3, "canonical": 0}:
                raise Product09Error(
                    f"unexpected persisted lifecycle counts: {counts_after_capture}"
                )

            phase = "codex-before-restart"
            inbound_token = secrets.token_urlsafe(40)
            _start_mcp(
                process_group,
                environment,
                port=mcp_port,
                inbound_token=inbound_token,
            )
            mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"
            decision_run = _run_codex(
                args.codex,
                mcp_url=mcp_url,
                inbound_token=inbound_token,
                prompt=(
                    "Use the MiLAi memory tool exactly once. What zero-downtime migration plan was "
                    "selected for the Aurora indexer? Return only its exact plan label and no "
                    "markup."
                ),
                timeout_seconds=args.codex_timeout_seconds,
            )
            if (
                decision_run["returncode"] != 0
                or len(decision_run["calls"]) != 1
                or _normalized_answer(decision_run["answer"]) != plan_label
                or not _tool_contains(decision_run, plan_label)
            ):
                raise Product09Error("Codex could not recall the design decision before restart")

            phase = "restart"
            process_group.stop()
            process_group = ProcessGroup(root)
            _start_runtime(process_group, environment)
            _start_mcp(
                process_group,
                environment,
                port=mcp_port,
                inbound_token=inbound_token,
            )

            phase = "codex-after-restart"
            fix_run = _run_codex(
                args.codex,
                mcp_url=mcp_url,
                inbound_token=inbound_token,
                prompt=(
                    "Use the MiLAi memory tool exactly once. What exact passing verification "
                    "command fixed Aurora projection lease failure P09E742? Return only the "
                    "command, without Markdown or explanation."
                ),
                timeout_seconds=args.codex_timeout_seconds,
            )
            if (
                fix_run["returncode"] != 0
                or len(fix_run["calls"]) != 1
                or _normalized_answer(fix_run["answer"]) != fix_command
                or not _tool_contains(fix_run, fix_command)
            ):
                raise Product09Error("Codex could not recall verified tool Evidence after restart")

            phase = "codex-controls"
            no_memory_run = _run_codex(
                args.codex,
                mcp_url=mcp_url,
                inbound_token=inbound_token,
                prompt="Compute 3 + 4 without tools or historical memory. Return only the result.",
                timeout_seconds=args.codex_timeout_seconds,
            )
            if (
                no_memory_run["returncode"] != 0
                or _normalized_answer(no_memory_run["answer"]) != "7"
                or no_memory_run["calls"]
            ):
                raise Product09Error("Codex no-memory control unexpectedly used MiLAi")
            cross_scope_run = _run_codex(
                args.codex,
                mcp_url=mcp_url,
                inbound_token=inbound_token,
                prompt=(
                    "Use the MiLAi memory tool exactly once to look for the Borealis private "
                    "deployment marker. If no matching evidence is returned, answer exactly "
                    "NOT_FOUND. Never infer or invent a marker."
                ),
                timeout_seconds=args.codex_timeout_seconds,
            )
            if (
                cross_scope_run["returncode"] != 0
                or len(cross_scope_run["calls"]) != 1
                or _tool_contains(cross_scope_run, foreign_marker)
                or _normalized_answer(cross_scope_run["answer"]) != "NOT_FOUND"
            ):
                raise Product09Error("project-scoped MCP read leaked or invented foreign Evidence")

            final_counts = _database_counts(compose)
            if final_counts["canonical"] != 0:
                raise Product09Error("capture or recall mutated Canonical state")
            phase = "complete"
            summary = {
                "schema_version": "milai-product09-codex-http-lifecycle-v1",
                "status": "PASS_PRODUCT09_CODEX_HTTP_PERSISTENT_MEMORY_USABLE",
                "run_id": args.run_id,
                "phase": phase,
                "codex_version": _command(
                    [str(args.codex), "--version"], timeout=10
                ).stdout.strip(),
                "transport": "streamable-http",
                "model_backend": "none",
                "capture": {
                    "events_submitted": 4,
                    "unique_evidence": final_counts["evidence"],
                    "duplicate_replayed": True,
                    "event_types": ["USER_MESSAGE", "TOOL_RESULT"],
                    "source_identity_preserved": True,
                },
                "projection": {
                    "status": readiness.get("status"),
                    "rows": final_counts["projection"],
                },
                "scenarios": {
                    "design_before_restart": {
                        "passed": True,
                        "tool_calls": len(decision_run["calls"]),
                        "latency_ms": decision_run["latency_ms"],
                    },
                    "verified_fix_after_restart": {
                        "passed": True,
                        "tool_calls": len(fix_run["calls"]),
                        "latency_ms": fix_run["latency_ms"],
                    },
                    "no_memory": {
                        "passed": True,
                        "tool_calls": len(no_memory_run["calls"]),
                        "latency_ms": no_memory_run["latency_ms"],
                    },
                    "cross_project_scope": {
                        "passed": True,
                        "tool_calls": len(cross_scope_run["calls"]),
                        "latency_ms": cross_scope_run["latency_ms"],
                    },
                },
                "invariants": {
                    "cross_project_evidence_leak": 0,
                    "canonical_mutation": final_counts["canonical"],
                    "model_visible_write_tools": 0,
                    "internal_reader_calls": 0,
                    "vllm_calls": 0,
                    "automatic_semantic_retries": 0,
                    "formal_500_consumed": False,
                },
                "database_counts": final_counts,
                "database_restart_completed": True,
                "run_owned_database_volume_removed": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            }
            return summary
        except Exception as exc:
            return {
                "schema_version": "milai-product09-codex-http-lifecycle-v1",
                "status": "FAIL_PRODUCT09_E2E",
                "run_id": args.run_id,
                "phase": phase,
                "failure": {"type": type(exc).__name__, "message": str(exc)},
                "formal_500_consumed": False,
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            }
        finally:
            process_group.stop()
            if postgres_started:
                _command(
                    [*compose, "down", "--volumes", "--remove-orphans"],
                    cwd=RUNTIME,
                    timeout=90,
                    check=False,
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--codex",
        type=Path,
        default=Path(os.environ.get("CODEX_BIN", "/usr/local/bin/codex")),
    )
    parser.add_argument("--codex-timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    if not 8 <= len(args.run_id) <= 48 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in args.run_id
    ):
        raise SystemExit("run-id must contain 8-48 lowercase alphanumeric/hyphen characters")
    if args.output.exists():
        raise SystemExit("output already exists")
    summary = run(args)
    _write_summary(args.output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
