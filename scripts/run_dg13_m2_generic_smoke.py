#!/usr/bin/env python3
"""Run DG-13 M2 exact current/historical reads through real stdio MCP."""

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
    _json_request,
    _require_status,
    _seed_fixture,
    _terminate,
    _wait_ready,
)

DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_REPORT_ROOT = ROOT / "var/dg13/m2"
ZERO_EXACT_COST = {
    "auxiliary_llm_calls": 0,
    "embedding_calls": 0,
    "vector_search_calls": 0,
    "reranker_calls": 0,
    "broad_head_scan_calls": 0,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"dg13-m2-generic-{uuid4().hex[:12]}")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--mcp-call", action="store_true", help=argparse.SUPPRESS)
    return parser


def _supersede(
    base_url: str,
    *,
    submitter_token: str,
    reviewer_token: str,
    claim_id: str,
    claim_version_id: str,
) -> dict[str, str]:
    evidence = _require_status(
        "replacement evidence capture",
        _json_request(
            base_url,
            "/v1/evidence",
            token=submitter_token,
            idempotency_key=f"m2-evidence-{uuid4()}",
            payload={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"dg13-m2://{uuid4()}",
                "subject_id": "dg13-m2-generic-smoke",
                "observed_at": "2026-08-26T01:00:00+08:00",
                "content": "governed M2 replacement fixture",
                "media_type": "text/plain",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            },
        ),
        {201},
    )
    proposal = _require_status(
        "replacement proposal create",
        _json_request(
            base_url,
            "/v1/proposals",
            token=submitter_token,
            idempotency_key=f"m2-proposal-{uuid4()}",
            payload={
                "target_claim_id": claim_id,
                "operation": "SUPERSEDE",
                "expected_version_id": claim_version_id,
                "proposed_patch": {
                    "payload": {"value": "replacement"},
                    "authority": "ACTION_SAFE",
                    "confidence": 0.99,
                },
                "supporting_evidence_refs": [str(evidence["evidence_id"])],
                "scope_predicate": {"project_ids": ["milai"]},
                "requested_authority": "ACTION_SAFE",
                "derivation_policy_id": "dg13-m2-generic-smoke-v1",
                "derivation_snapshot": {"fixture": "governed-replacement"},
            },
        ),
        {201},
    )
    review = _require_status(
        "replacement proposal review",
        _json_request(
            base_url,
            f"/v1/proposals/{proposal['proposal_id']}/review",
            token=reviewer_token,
            idempotency_key=f"m2-review-{uuid4()}",
            payload={
                "decision": "APPROVE",
                "policy_version": "dg13-m2-generic-smoke-v1",
                "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
            },
        ),
        {200},
    )
    return {
        "claim_id": str(review["claim_id"]),
        "claim_version_id": str(review["claim_version_id"]),
    }


async def _mcp_call_mode() -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    operations = json.loads(os.environ["MILAI_M2_SMOKE_OPERATIONS"])
    if not isinstance(operations, list):
        raise SmokeError("M2 child operations must be a list")
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
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        catalog = sorted(tool.name for tool in (await client.list_tools()).tools)
        for operation in operations:
            if not isinstance(operation, dict):
                raise SmokeError("M2 child operation must be an object")
            arguments = dict(operation)
            tool = str(arguments.pop("_tool", "milai_memory_get"))
            if tool not in {"milai_memory_get", "milai_memory_resolve"}:
                raise SmokeError("M2 child operation selected an unexpected tool")
            result = await client.call_tool(tool, arguments)
            if result.is_error or not isinstance(result.structured_content, dict):
                raise SmokeError("milai_memory_get did not return structured success")
            observations.append(dict(result.structured_content))
    print(json.dumps({"catalog": catalog, "observations": observations}, sort_keys=True))


def _run_mcp_child(
    *, base_url: str, reader_token: str, operations: list[dict[str, Any]]
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
        "MILAI_M2_SMOKE_OPERATIONS": json.dumps(operations, separators=(",", ":")),
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
            "generic M2 MCP child failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("generic M2 MCP child returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeError("generic M2 MCP child returned a non-object")
    return result


def _validate_exact(
    body: dict[str, Any], *, expected_version: str, expected_mode: str
) -> float:
    items = body.get("items")
    first = items[0] if isinstance(items, list) and items else None
    trace = body.get("access_trace")
    resolution = body.get("resolution")
    if body.get("status") != "HIT" or not isinstance(first, dict):
        raise SmokeError("exact read did not return one HIT")
    if first.get("claim_version_id") != expected_version:
        raise SmokeError("exact read returned the wrong canonical version")
    if not isinstance(resolution, dict) or resolution.get("mode") != expected_mode:
        raise SmokeError("exact read returned the wrong temporal resolution mode")
    if any(resolution.get(key) is not True for key in (
        "addressable", "reachable", "correctly_resolved"
    )):
        raise SmokeError("exact resolution dimensions are incomplete")
    if not isinstance(trace, dict):
        raise SmokeError("exact AccessTrace is absent")
    if trace.get("planned_stage") != "EXACT" or trace.get("terminal_stage") != "EXACT":
        raise SmokeError("exact read escaped the exact stage")
    if trace.get("structural_cost") != ZERO_EXACT_COST:
        raise SmokeError("exact structural cost contract failed")
    if trace.get("logical_mcp_calls") != 1 or trace.get("automatic_retry_count") != 0:
        raise SmokeError("exact logical call/retry contract failed")
    spans = trace.get("spans")
    if not isinstance(spans, dict) or not isinstance(spans.get("mcp_handler_ms"), int | float):
        raise SmokeError("exact MCP handler latency is absent")
    state_address_ms = spans.get("state_address_ms")
    repository_sql_ms = spans.get("repository_sql_ms")
    if not isinstance(state_address_ms, int | float) or not isinstance(
        repository_sql_ms, int | float
    ):
        raise SmokeError("exact StateAddress/SQL latency is absent")
    if repository_sql_ms < state_address_ms:
        raise SmokeError("repository SQL latency excludes StateAddress resolution")
    return float(spans["mcp_handler_ms"])


def _validate_resolve_exact(body: dict[str, Any], *, expected_version: str) -> float:
    items = body.get("items")
    first = items[0] if isinstance(items, list) and items else None
    trace = body.get("access_trace")
    if body.get("status") != "HIT" or body.get("requirement") != "EXACT":
        raise SmokeError("addressed resolve did not take the exact contract")
    if not isinstance(first, dict) or first.get("claim_version_id") != expected_version:
        raise SmokeError("addressed resolve returned the wrong canonical version")
    if not isinstance(trace, dict) or trace.get("structural_cost") != ZERO_EXACT_COST:
        raise SmokeError("addressed resolve escaped the exact cost contract")
    if trace.get("logical_mcp_calls") != 1 or trace.get("automatic_retry_count") != 0:
        raise SmokeError("addressed resolve logical call/retry contract failed")
    spans = trace.get("spans")
    if not isinstance(spans, dict) or not isinstance(spans.get("mcp_handler_ms"), int | float):
        raise SmokeError("addressed resolve MCP handler latency is absent")
    return float(spans["mcp_handler_ms"])


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
    database_name = f"milai_smoke_dg13m2_{suffix}"
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
    migration_head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    fixture: dict[str, str] | None = None
    replacement: dict[str, str] | None = None
    first: dict[str, Any] | None = None
    second: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="milai-dg13-m2-") as temporary_value:
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
                    fixture_token=f"m2state{uuid4().hex}",
                )
                canonical = _require_status(
                    "canonical state read",
                    _json_request(
                        base_url,
                        f"/v1/claims/{fixture['claim_id']}",
                        token=tokens["reader"],
                    ),
                    {200},
                )
                state_key = {
                    "subject": canonical["subject_id"],
                    "predicate": canonical["predicate"],
                    "claim_type": canonical["claim_type"],
                }
                original_system_time = str(canonical["system_time"])
                first = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    operations=[
                        {"state_key": state_key},
                        {"claim_id": fixture["claim_id"]},
                        {
                            "_tool": "milai_memory_resolve",
                            "query": "Read the exact current state",
                            "state_key": state_key,
                        },
                    ],
                )
                replacement = _supersede(
                    base_url,
                    submitter_token=tokens["submitter"],
                    reviewer_token=tokens["reviewer"],
                    claim_id=fixture["claim_id"],
                    claim_version_id=fixture["claim_version_id"],
                )
                second = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    operations=[
                        {"claim_id": fixture["claim_id"]},
                        {
                            "claim_id": fixture["claim_id"],
                            "valid_at": "2026-08-25T12:00:00+00:00",
                            "known_at": original_system_time,
                        },
                    ],
                )
            finally:
                _terminate(api_process)
                runtime_log.close()
        finally:
            if database_created:
                cleanup = _drop_database(owner_source, database_name)
                if cleanup.get("status") != "PASS":
                    raise SmokeError("fresh Runtime database cleanup failed")

    if fixture is None or replacement is None or first is None or second is None:
        raise SmokeError("M2 smoke did not complete")
    if "milai_memory_get" not in first.get("catalog", []):
        raise SmokeError("milai_memory_get is absent from reader-detail")
    first_rows = first.get("observations")
    second_rows = second.get("observations")
    if not isinstance(first_rows, list) or len(first_rows) != 3:
        raise SmokeError("first MCP session observations are malformed")
    if not isinstance(second_rows, list) or len(second_rows) != 2:
        raise SmokeError("second MCP session observations are malformed")
    latencies = [
        _validate_exact(first_rows[0], expected_version=fixture["claim_version_id"], expected_mode="CURRENT"),
        _validate_exact(first_rows[1], expected_version=fixture["claim_version_id"], expected_mode="CURRENT"),
        _validate_resolve_exact(first_rows[2], expected_version=fixture["claim_version_id"]),
        _validate_exact(second_rows[0], expected_version=replacement["claim_version_id"], expected_mode="CURRENT"),
        _validate_exact(second_rows[1], expected_version=fixture["claim_version_id"], expected_mode="HISTORICAL"),
    ]
    report = {
        "schema": "milai.dg13.m2-generic-smoke.v1",
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
        "canonical": {
            "governed_capture_proposal_review": True,
            "supersede_exact_head_cas": True,
            "original_claim_version_id": fixture["claim_version_id"],
            "replacement_claim_version_id": replacement["claim_version_id"],
        },
        "mcp": {
            "profile": "reader-detail",
            "processes": 2,
            "client_sessions": 2,
            "calls": 5,
            "logical_calls_per_read": 1,
            "automatic_retries": 0,
            "tool_catalog": first["catalog"],
        },
        "gate": {
            "state_key_current": "PASS",
            "claim_id_current": "PASS",
            "addressed_resolve_exact": "PASS",
            "current_after_supersede": "PASS",
            "historical_valid_at_known_at": "PASS",
            "projection_independence": "PASS",
            "resolution_dimensions_separate": "PASS",
            "state_address_sql_span_complete": "PASS",
            "exact_structural_cost": ZERO_EXACT_COST,
        },
        "latency_ms": {
            "metric": "access_trace.spans.mcp_handler_ms",
            "observations": len(latencies),
            "maximum": round(max(latencies), 3),
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
        print(f"DG-13 M2 generic smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
