#!/usr/bin/env python3
"""Run the DG-13 M1 generic MCP client against a fresh governed Runtime.

The default mode runs under ``runtime/.venv`` and owns a temporary database,
Runtime process, fixture and cleanup.  ``--mcp-call`` is an internal child mode
run under ``integrations/mcp/.venv`` so the smoke exercises the real stdio SDK,
installed ``milai-mcp`` entrypoint and HTTP boundary without merging venvs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_REPORT_ROOT = ROOT / "var/dg13/m1"
M0_TRACE = (
    ROOT
    / "var/dg13/runs/dg13-m0-openworker-replay-20260826a/host-access-trace.jsonl"
)


class SmokeError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"dg13-m1-generic-{uuid4().hex[:12]}")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--calls", type=int, default=20)
    parser.add_argument("--mcp-call", action="store_true", help=argparse.SUPPRESS)
    return parser


def _json_request(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(  # noqa: S310 - base URL is generated loopback HTTP
        base_url + path,
        data=(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            if payload is not None
            else None
        ),
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            body = json.loads(response.read())
            if not isinstance(body, dict):
                raise SmokeError(f"non-object response from {path}")
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except json.JSONDecodeError:
            body = {}
        return int(exc.code), body if isinstance(body, dict) else {}


def _wait_ready(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeError("fresh Runtime exited before readiness")
        try:
            status, body = _json_request(base_url, "/health/ready", timeout=1.0)
            if status == 200 and body.get("status") == "ready":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise SmokeError("fresh Runtime readiness timeout")


def _require_status(
    operation: str, response: tuple[int, dict[str, Any]], expected: set[int]
) -> dict[str, Any]:
    status, body = response
    if status not in expected:
        code = body.get("error", {}).get("code") if isinstance(body.get("error"), dict) else None
        raise SmokeError(f"{operation} returned HTTP {status} ({code or 'UNKNOWN'})")
    return body


def _seed_fixture(
    base_url: str,
    *,
    submitter_token: str,
    reviewer_token: str,
    fixture_token: str,
) -> dict[str, str]:
    evidence = _require_status(
        "evidence capture",
        _json_request(
            base_url,
            "/v1/evidence",
            token=submitter_token,
            idempotency_key=f"m1-evidence-{uuid4()}",
            payload={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"dg13-m1://{uuid4()}",
                "subject_id": "dg13-m1-generic-smoke",
                "observed_at": "2026-08-26T00:00:00+08:00",
                "content": f"governed fixture {fixture_token}",
                "media_type": "text/plain",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            },
        ),
        {201},
    )
    evidence_id = str(evidence["evidence_id"])
    proposal = _require_status(
        "proposal create",
        _json_request(
            base_url,
            "/v1/proposals",
            token=submitter_token,
            idempotency_key=f"m1-proposal-{uuid4()}",
            payload={
                "operation": "CREATE",
                "proposed_patch": {
                    "subject_id": f"dg13-m1-subject-{uuid4()}",
                    "predicate": "runtime.generic_smoke.status",
                    "claim_type": "FACT",
                    "payload": {"token": fixture_token, "value": "persisted"},
                    "authority": "ACTION_SAFE",
                    "confidence": 0.99,
                    "valid_time_from": "2026-08-25T00:00:00+00:00",
                },
                "supporting_evidence_refs": [evidence_id],
                "scope_predicate": {"project_ids": ["milai"]},
                "requested_authority": "ACTION_SAFE",
                "derivation_policy_id": "dg13-m1-generic-smoke-v1",
                "derivation_snapshot": {"fixture": "governed"},
            },
        ),
        {201},
    )
    review = _require_status(
        "proposal review",
        _json_request(
            base_url,
            f"/v1/proposals/{proposal['proposal_id']}/review",
            token=reviewer_token,
            idempotency_key=f"m1-review-{uuid4()}",
            payload={
                "decision": "APPROVE",
                "policy_version": "dg13-m1-generic-smoke-v1",
                "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
            },
        ),
        {200},
    )
    return {
        "evidence_id": evidence_id,
        "claim_id": str(review["claim_id"]),
        "claim_version_id": str(review["claim_version_id"]),
    }


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _m0_handler_baseline() -> float:
    for line in M0_TRACE.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == "HOST_MCP_PREPARE_CONTEXT":
            return float(event["access_trace_link"]["spans"]["mcp_handler_ms"])
    raise SmokeError("declared M0 MCP handler baseline is absent")


def _p95(values: list[float]) -> float:
    if not values:
        raise SmokeError("cannot calculate p95 from no observations")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _run_mcp_child(
    *, base_url: str, reader_token: str, query: str, calls: int
) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "MILAI_BASE_URL": base_url,
        "MILAI_AGENT_TOKEN": reader_token,
        "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["milai"]}',
        "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
        "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
        "MILAI_AGENT_MAX_LIMIT": "3",
        "MILAI_M1_SMOKE_QUERY": query,
    }
    completed = subprocess.run(  # noqa: S603 - argv uses repository-owned executable
        [
            str(ROOT / "integrations/mcp/.venv/bin/python"),
            str(Path(__file__).resolve()),
            "--mcp-call",
            "--calls",
            str(calls),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if completed.returncode != 0:
        raise SmokeError(
            "generic MCP child failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    try:
        body = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("generic MCP child returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise SmokeError("generic MCP child returned a non-object")
    return body


async def _mcp_call_mode(calls: int) -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    query = os.environ["MILAI_M1_SMOKE_QUERY"]
    executable = ROOT / "integrations/mcp/.venv/bin/milai-mcp"
    parameters = StdioServerParameters(
        command=str(executable),
        args=["--profile", "reader-lite", "--max-retries", "0"],
        env={
            key: os.environ[key]
            for key in (
                "PATH",
                "LANG",
                "MILAI_BASE_URL",
                "MILAI_AGENT_TOKEN",
                "MILAI_AGENT_SCOPE_JSON",
                "MILAI_AGENT_REQUIRED_AUTHORITY",
                "MILAI_AGENT_CONSISTENCY_FLOOR",
                "MILAI_AGENT_MAX_LIMIT",
            )
        },
    )
    observations: list[dict[str, Any]] = []
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        catalog = await client.list_tools()
        names = sorted(tool.name for tool in catalog.tools)
        for _ in range(calls):
            result = await client.call_tool("milai_memory_resolve", {"query": query})
            if result.is_error or not isinstance(result.structured_content, dict):
                raise SmokeError("milai_memory_resolve did not return structured success")
            body = result.structured_content
            items = body.get("items")
            first = items[0] if isinstance(items, list) and items else {}
            trace = body.get("access_trace")
            observations.append(
                {
                    "status": body.get("status"),
                    "claim_id": first.get("claim_id") if isinstance(first, dict) else None,
                    "claim_version_id": (
                        first.get("claim_version_id") if isinstance(first, dict) else None
                    ),
                    "canonical_position": body.get("canonical_position"),
                    "trace_id": body.get("trace_id"),
                    "access_trace": trace,
                }
            )
    print(json.dumps({"catalog": names, "observations": observations}, sort_keys=True))


def _validate_observations(
    observations: list[dict[str, Any]], fixture: dict[str, str]
) -> list[float]:
    handler_latencies: list[float] = []
    for item in observations:
        if item.get("status") != "HIT":
            raise SmokeError(f"unexpected resolve status: {item.get('status')}")
        if item.get("claim_id") != fixture["claim_id"]:
            raise SmokeError("MCP result did not retain the canonical claim")
        if item.get("claim_version_id") != fixture["claim_version_id"]:
            raise SmokeError("MCP result did not retain the canonical claim version")
        trace = item.get("access_trace")
        if not isinstance(trace, dict):
            raise SmokeError("AccessTrace is absent")
        if trace.get("logical_mcp_calls") != 1 or trace.get("automatic_retry_count") != 0:
            raise SmokeError("logical call or automatic retry invariant failed")
        if not trace.get("planned_stage") or not trace.get("attempted_stages"):
            raise SmokeError("AccessTrace planning or attempts are incomplete")
        if not trace.get("terminal_stage") or trace.get("route_trace_complete") is not True:
            raise SmokeError("AccessTrace terminal route is incomplete")
        spans = trace.get("spans")
        if not isinstance(spans, dict) or not isinstance(spans.get("mcp_handler_ms"), int | float):
            raise SmokeError("MCP handler latency is absent")
        handler_latencies.append(float(spans["mcp_handler_ms"]))
    return handler_latencies


def _run(args: argparse.Namespace) -> dict[str, Any]:
    from alembic import command
    from alembic.script import ScriptDirectory
    from milai.config import load_settings
    from milai.config.settings import prepare_runtime_directories
    from milai.operations import load_runtime_environment
    from milai.operations.smoke import (
        _alembic_config,
        _api_environment,
        _create_database,
        _database_url,
        _drop_database,
        _free_loopback_port,
        _migration_url,
        _smoke_settings,
    )

    if args.calls < 2:
        raise SmokeError("--calls must be at least 2")
    load_runtime_environment(args.env_file.resolve())
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise SmokeError("fresh Runtime database-role URLs are absent")

    suffix = hashlib.sha256(args.run_id.encode()).hexdigest()[:20]
    database_name = f"milai_smoke_dg13m1_{suffix}"
    database_urls = {
        "owner": _database_url(owner_source, database_name),
        "api": _database_url(source.database_dsn, database_name),
        "steward": _database_url(source.steward_database_dsn, database_name),
        "worker": _database_url(worker_source, database_name),
        "audit": _database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    api_process: subprocess.Popen[bytes] | None = None
    database_created = False
    fixture: dict[str, str] | None = None
    first: dict[str, Any] | None = None
    second: dict[str, Any] | None = None
    migration_head = ScriptDirectory.from_config(_alembic_config()).get_current_head()

    with tempfile.TemporaryDirectory(prefix="milai-dg13-m1-") as temporary_value:
        temporary = Path(temporary_value)
        try:
            _create_database(owner_source, database_name)
            database_created = True
            with _migration_url(database_urls["owner"]):
                command.upgrade(_alembic_config(), "head")
            settings = _smoke_settings(
                source,
                database_urls,
                temporary / "blobs",
                uuid4(),
                uuid4(),
                tokens,
                _free_loopback_port(),
            )
            prepare_runtime_directories(settings)
            environment = _api_environment(settings, database_urls, tokens)
            runtime_log = (temporary / "runtime.log").open("wb")
            try:
                api_process = subprocess.Popen(  # noqa: S603 - fixed local entrypoint
                    [str(ROOT / "runtime/.venv/bin/milai-api")],
                    cwd=ROOT / "runtime",
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=runtime_log,
                    stderr=subprocess.STDOUT,
                )
                base_url = f"http://{settings.bind_host}:{settings.bind_port}"
                _wait_ready(base_url, api_process)
                fixture_token = f"genericpersisted{uuid4().hex}"
                fixture = _seed_fixture(
                    base_url,
                    submitter_token=tokens["submitter"],
                    reviewer_token=tokens["reviewer"],
                    fixture_token=fixture_token,
                )
                worker_environment = dict(environment)
                worker_environment["MILAI_WORKER_DATABASE_URL"] = database_urls["worker"]
                worker = subprocess.run(  # noqa: S603 - fixed local entrypoint
                    [str(ROOT / "runtime/.venv/bin/milai-worker"), "--once"],
                    cwd=ROOT / "runtime",
                    env=worker_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=runtime_log,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=30,
                )
                if worker.returncode != 0:
                    raise SmokeError("fresh Runtime projection worker failed")
                query = f"What is the current {fixture_token} status?"
                first = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    query=query,
                    calls=args.calls,
                )
                second = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    query=query,
                    calls=1,
                )
                query_fingerprint = hashlib.sha256(query.encode()).hexdigest()
            finally:
                _terminate(api_process)
                runtime_log.close()
        finally:
            if database_created:
                cleanup = _drop_database(owner_source, database_name)
                if cleanup.get("status") != "PASS":
                    raise SmokeError("fresh Runtime database cleanup failed")

    if fixture is None or first is None or second is None:
        raise SmokeError("generic smoke did not reach both MCP sessions")
    if "milai_memory_resolve" not in first.get("catalog", []):
        raise SmokeError("target tool is absent from the reader-lite catalog")
    first_observations = first.get("observations")
    second_observations = second.get("observations")
    if not isinstance(first_observations, list) or not isinstance(second_observations, list):
        raise SmokeError("generic MCP observations are malformed")
    latencies = _validate_observations(first_observations, fixture)
    latencies.extend(_validate_observations(second_observations, fixture))
    first_position = first_observations[-1]["canonical_position"]
    second_position = second_observations[0]["canonical_position"]
    if first_position != second_position:
        raise SmokeError("canonical position changed across an idle MCP restart")
    target_p95 = _p95(latencies)
    baseline = _m0_handler_baseline()
    if target_p95 > baseline:
        raise SmokeError(
            f"M1 handler p95 {target_p95:.3f}ms regressed past M0 {baseline:.3f}ms"
        )
    report = {
        "schema": "milai.dg13.m1-generic-smoke.v1",
        "run_id": args.run_id,
        "status": "PASS",
        "fixture": {
            "governed_capture_proposal_review": True,
            "claim_id": fixture["claim_id"],
            "claim_version_id": fixture["claim_version_id"],
            "query_fingerprint": query_fingerprint,
            "query_plaintext_persisted": False,
        },
        "runtime": {
            "fresh_database": True,
            "migration_head": migration_head,
            "database_cleanup": "PASS",
            "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
            "implementation_status": "0.1.x CANDIDATE",
        },
        "mcp": {
            "profile": "reader-lite",
            "processes": 2,
            "client_sessions": 2,
            "calls": len(latencies),
            "task_metadata_supplied": False,
            "logical_calls_per_resolve": 1,
            "automatic_retries": 0,
            "canonical_state_retained_after_restart": True,
            "tool_catalog": first["catalog"],
        },
        "trace": {
            "complete": True,
            "requested_planned_attempted_terminal_present": True,
        },
        "latency_ms": {
            "metric": "access_trace.spans.mcp_handler_ms",
            "observations": len(latencies),
            "m1_p95": round(target_p95, 3),
            "m0_declared_baseline": round(baseline, 3),
            "non_regression": True,
            "m0_source": str(M0_TRACE.relative_to(ROOT)),
        },
    }
    target_dir = args.report_root / args.run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    target = target_dir / "report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    args = _parser().parse_args()
    if args.mcp_call:
        asyncio.run(_mcp_call_mode(args.calls))
        return 0
    try:
        report = _run(args)
    except (OSError, SmokeError, subprocess.SubprocessError) as exc:
        print(f"DG-13 M1 generic smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
