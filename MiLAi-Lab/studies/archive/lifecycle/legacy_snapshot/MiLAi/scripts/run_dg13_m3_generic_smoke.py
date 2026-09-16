#!/usr/bin/env python3
"""Run DG-13 M3 receipt reuse, same-call fallback, and typed failure smoke."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from run_dg13_m1_generic_smoke import (
    ROOT,
    SmokeError,
    _seed_fixture,
    _terminate,
    _wait_ready,
)
from run_dg13_m2_generic_smoke import ZERO_EXACT_COST, _supersede

DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_REPORT_ROOT = ROOT / "var/dg13/m3"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"dg13-m3-generic-{uuid4().hex[:12]}")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--mcp-call", action="store_true", help=argparse.SUPPRESS)
    return parser


async def _mcp_call_mode() -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    operations = json.loads(os.environ["MILAI_M3_SMOKE_OPERATIONS"])
    if not isinstance(operations, list):
        raise SmokeError("M3 child operations must be a list")
    parameters = StdioServerParameters(
        command=str(ROOT / "integrations/mcp/.venv/bin/milai-mcp"),
        args=["--profile", "reader-detail", "--max-retries", "0"],
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
    previous_context_id: str | None = None
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        catalog = sorted(tool.name for tool in (await client.list_tools()).tools)
        for raw_operation in operations:
            if not isinstance(raw_operation, dict):
                raise SmokeError("M3 child operation must be an object")
            operation = dict(raw_operation)
            reuse_previous = operation.pop("_reuse_previous", False)
            if reuse_previous is True:
                if previous_context_id is None:
                    raise SmokeError("M3 child has no previous receipt locator")
                operation["previous_context_id"] = previous_context_id
            result = await client.call_tool("milai_memory_resolve", operation)
            if result.is_error or not isinstance(result.structured_content, dict):
                raise SmokeError("milai_memory_resolve did not return structured success")
            observation = dict(result.structured_content)
            receipt = observation.get("context_receipt")
            if isinstance(receipt, dict) and isinstance(
                receipt.get("context_capsule_id"), str
            ):
                previous_context_id = str(receipt["context_capsule_id"])
            observations.append(observation)
    print(json.dumps({"catalog": catalog, "observations": observations}, sort_keys=True))


def _run_mcp_child(
    *,
    base_url: str,
    reader_token: str,
    operations: list[dict[str, Any]],
    scope: dict[str, object] | None = None,
) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "MILAI_BASE_URL": base_url,
        "MILAI_AGENT_TOKEN": reader_token,
        "MILAI_AGENT_SCOPE_JSON": json.dumps(
            scope or {"project_ids": ["milai"]}, separators=(",", ":")
        ),
        "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
        "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
        "MILAI_AGENT_MAX_LIMIT": "3",
        "MILAI_M3_SMOKE_OPERATIONS": json.dumps(operations, separators=(",", ":")),
    }
    completed = subprocess.run(
        [
            str(ROOT / "integrations/mcp/.venv/bin/python"),
            str(Path(__file__).resolve()),
            "--mcp-call",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if completed.returncode != 0:
        raise SmokeError(
            "generic M3 MCP child failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("generic M3 MCP child returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeError("generic M3 MCP child returned a non-object")
    return result


def _rows(value: dict[str, Any], count: int) -> list[dict[str, Any]]:
    observations = value.get("observations")
    if not isinstance(observations, list) or len(observations) != count or any(
        not isinstance(row, dict) for row in observations
    ):
        raise SmokeError("M3 MCP observations are malformed")
    return observations


def _assert_primary_exact(body: dict[str, Any], expected_version: str) -> None:
    items = body.get("items")
    first = items[0] if isinstance(items, list) and items else None
    trace = body.get("access_trace")
    if body.get("status") != "HIT" or not isinstance(first, dict):
        raise SmokeError("M3 exact primary call did not HIT")
    if first.get("claim_version_id") != expected_version:
        raise SmokeError("M3 exact primary call returned the wrong version")
    if not isinstance(trace, dict) or trace.get("structural_cost") != ZERO_EXACT_COST:
        raise SmokeError("M3 exact primary call violated the exact cost bound")
    if trace.get("logical_mcp_calls") != 1 or trace.get("automatic_retry_count") != 0:
        raise SmokeError("M3 exact primary call violated call/retry bounds")


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

    load_runtime_environment(args.env_file.resolve())
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise SmokeError("fresh Runtime database-role URLs are absent")
    suffix = hashlib.sha256(args.run_id.encode()).hexdigest()[:20]
    database_name = f"milai_smoke_dg13m3_{suffix}"
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
    database_created = False
    api_process: subprocess.Popen[bytes] | None = None
    migration_head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    fixture: dict[str, str] | None = None
    replacement: dict[str, str] | None = None
    initial: dict[str, Any] | None = None
    changed: dict[str, Any] | None = None
    scoped: dict[str, Any] | None = None
    unavailable: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="milai-dg13-m3-") as temporary_value:
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
                api_process = subprocess.Popen(
                    [str(ROOT / "runtime/.venv/bin/milai-api")],
                    cwd=ROOT / "runtime",
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=runtime_log,
                    stderr=subprocess.STDOUT,
                )
                base_url = f"http://{settings.bind_host}:{settings.bind_port}"
                _wait_ready(base_url, api_process)
                fixture = _seed_fixture(
                    base_url,
                    submitter_token=tokens["submitter"],
                    reviewer_token=tokens["reviewer"],
                    fixture_token=f"m3state{uuid4().hex}",
                )
                query = "Read the exact current governed receipt state"
                initial = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    operations=[
                        {"query": query, "claim_id": fixture["claim_id"]},
                        {
                            "query": query,
                            "claim_id": fixture["claim_id"],
                            "_reuse_previous": True,
                        },
                        {
                            "query": query,
                            "claim_id": fixture["claim_id"],
                            "previous_context_id": str(uuid4()),
                        },
                    ],
                )
                initial_rows = _rows(initial, 3)
                receipt = initial_rows[0].get("context_receipt")
                if not isinstance(receipt, dict) or not isinstance(
                    receipt.get("context_capsule_id"), str
                ):
                    raise SmokeError("M3 initial call did not issue a ContextReceipt")
                previous_context_id = str(receipt["context_capsule_id"])
                replacement = _supersede(
                    base_url,
                    submitter_token=tokens["submitter"],
                    reviewer_token=tokens["reviewer"],
                    claim_id=fixture["claim_id"],
                    claim_version_id=fixture["claim_version_id"],
                )
                changed = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    operations=[
                        {
                            "query": query,
                            "claim_id": fixture["claim_id"],
                            "previous_context_id": previous_context_id,
                        }
                    ],
                )
                scoped = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    scope={"project_ids": ["other"]},
                    operations=[
                        {
                            "query": query,
                            "claim_id": fixture["claim_id"],
                            "previous_context_id": previous_context_id,
                        }
                    ],
                )
            finally:
                _terminate(api_process)
                runtime_log.close()
            unavailable = _run_mcp_child(
                base_url=base_url,
                reader_token=tokens["reader"],
                operations=[
                    {
                        "query": "Recall the exact current unavailable state",
                        "claim_id": fixture["claim_id"],
                    }
                ],
            )
        finally:
            if database_created:
                cleanup = _drop_database(owner_source, database_name)
                if cleanup.get("status") != "PASS":
                    raise SmokeError("fresh Runtime database cleanup failed")

    if any(
        value is None
        for value in (fixture, replacement, initial, changed, scoped, unavailable)
    ):
        raise SmokeError("M3 smoke did not complete")
    assert fixture is not None
    assert replacement is not None
    assert initial is not None
    assert changed is not None
    assert scoped is not None
    assert unavailable is not None
    initial_rows = _rows(initial, 3)
    changed_row = _rows(changed, 1)[0]
    scoped_row = _rows(scoped, 1)[0]
    unavailable_row = _rows(unavailable, 1)[0]
    _assert_primary_exact(initial_rows[0], fixture["claim_version_id"])
    reused = initial_rows[1]
    if reused.get("receipt_reused") is not True:
        raise SmokeError("M3 valid receipt was not reused")
    reuse_trace = reused.get("access_trace")
    if not isinstance(reuse_trace, dict) or reuse_trace.get("terminal_stage") != "REUSE":
        raise SmokeError("M3 valid receipt lacks a REUSE AccessTrace")
    if reuse_trace.get("structural_cost") != ZERO_EXACT_COST:
        raise SmokeError("M3 receipt reuse violated structural cost bounds")
    missing = initial_rows[2]
    _assert_primary_exact(missing, fixture["claim_version_id"])
    if missing.get("receipt_fallback_reason") != "RECEIPT_NOT_FOUND_OR_NOT_OWNED":
        raise SmokeError("M3 unknown locator did not take same-call fallback")
    _assert_primary_exact(changed_row, replacement["claim_version_id"])
    if changed_row.get("receipt_fallback_reason") != (
        "RECEIPT_CANONICAL_POSITION_CHANGED"
    ):
        raise SmokeError("M3 head change did not invalidate the receipt")
    if scoped_row.get("receipt_fallback_reason") != "RECEIPT_COVERAGE_MISS":
        raise SmokeError("M3 scope change did not invalidate receipt coverage")
    if scoped_row.get("receipt_reused") is not False:
        raise SmokeError("M3 scope-changed receipt was reused")
    if (
        unavailable_row.get("status") != "UNAVAILABLE"
        or unavailable_row.get("memory_intent") != "REQUIRED"
        or unavailable_row.get("requirement") != "EXACT"
        or unavailable_row.get("availability") != "UNAVAILABLE"
    ):
        raise SmokeError("M3 Runtime outage lost the required typed outcome")

    report = {
        "schema": "milai.dg13.m3-generic-smoke.v1",
        "run_id": args.run_id,
        "status": "PASS",
        "runtime": {
            "fresh_database": True,
            "migration_head": migration_head,
            "projection_worker_started": False,
            "database_cleanup": "PASS",
            "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
            "implementation_status": "0.1.x CANDIDATE",
        },
        "mcp": {
            "profile": "reader-detail",
            "processes": 4,
            "client_sessions": 4,
            "calls": 6,
            "logical_calls_per_operation": 1,
            "automatic_retries": 0,
            "tool_catalog": initial["catalog"],
        },
        "gate": {
            "valid_receipt_reuse": "PASS",
            "unknown_locator_same_call_exact": "PASS",
            "head_change_same_call_exact": "PASS",
            "scope_change_invalidates_coverage": "PASS",
            "runtime_unavailable_remains_required": "PASS",
            "context_receipt_is_wire_view_over_context_capsule": "PASS",
            "host_second_canonical_truth": False,
            "exact_structural_cost": ZERO_EXACT_COST,
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
        asyncio.run(_mcp_call_mode())
        return 0
    try:
        report = _run(args)
    except (OSError, SmokeError, subprocess.SubprocessError) as exc:
        print(f"DG-13 M3 generic smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
