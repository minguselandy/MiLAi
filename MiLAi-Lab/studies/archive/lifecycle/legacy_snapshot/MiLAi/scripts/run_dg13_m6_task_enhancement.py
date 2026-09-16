#!/usr/bin/env python3
"""Run the DG-13 M6 optional TaskContext matched-ablation Gate."""

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
from pathlib import Path
from typing import Any
from uuid import uuid4

from run_dg13_m1_generic_smoke import (
    ROOT,
    SmokeError,
    _terminate,
    _wait_ready,
)
from run_dg13_m4_bounded_search import (
    _item_ids,
    _seed_claim,
    _span,
    _trace_candidate_count,
)

DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_REPORT_ROOT = ROOT / "var/dg13/m6"


def _source_identity(paths: tuple[Path, ...]) -> dict[str, Any]:
    aggregate = hashlib.sha256()
    files: list[dict[str, str]] = []
    for path in sorted(paths):
        relative = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        aggregate.update(relative.encode("utf-8") + b"\0" + bytes.fromhex(digest))
        files.append({"path": relative, "sha256": digest})
    return {
        "algorithm": "sha256",
        "aggregate_sha256": aggregate.hexdigest(),
        "files": files,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"dg13-m6-task-{uuid4().hex[:12]}")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--mcp-call", action="store_true", help=argparse.SUPPRESS)
    return parser


async def _mcp_call_mode(rounds: int) -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    query = os.environ["MILAI_M6_QUERY"]
    entity = os.environ["MILAI_M6_ENTITY"]
    memory_type = os.environ["MILAI_M6_MEMORY_TYPE"]
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
        tools = (await client.list_tools()).tools
        catalog = sorted(tool.name for tool in tools)
        resolve_tool = next(tool for tool in tools if tool.name == "milai_memory_resolve")
        task_context_schema_present = "task_context" in resolve_tool.input_schema.get(
            "properties", {}
        )
        for _ in range(rounds):
            task_off_result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": query,
                    "consistency_mode": "CANONICAL_REQUIRED",
                    "limit": 3,
                },
            )
            if task_off_result.is_error or not isinstance(
                task_off_result.structured_content, dict
            ):
                raise SmokeError("M6 task-off resolve did not return structured success")
            task_off = dict(task_off_result.structured_content)
            task_off_trace = await _trace(client, task_off, "task-off")

            task_on_result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": query,
                    "consistency_mode": "CANONICAL_REQUIRED",
                    "limit": 3,
                    "task_context": {
                        "project_ids": ["milai"],
                        "entities": [entity],
                        "memory_types": [memory_type],
                        "action_risk": "HIGH",
                    },
                },
            )
            if task_on_result.is_error or not isinstance(
                task_on_result.structured_content, dict
            ):
                raise SmokeError("M6 task-on resolve did not return structured success")
            task_on = dict(task_on_result.structured_content)
            task_on_trace = await _trace(client, task_on, "task-on")
            observations.append(
                {
                    "task_off": task_off,
                    "task_off_trace": task_off_trace,
                    "task_on": task_on,
                    "task_on_trace": task_on_trace,
                }
            )

        last_task_on = observations[-1]["task_on"]
        receipt = last_task_on.get("context_receipt")
        capsule_id = receipt.get("context_capsule_id") if isinstance(receipt, dict) else None
        if not isinstance(capsule_id, str):
            raise SmokeError("M6 task-on response omitted reusable ContextReceipt")
        task_free_reuse_result = await client.call_tool(
            "milai_memory_resolve",
            {
                "query": query,
                "consistency_mode": "CANONICAL_REQUIRED",
                "limit": 3,
                "entities": [entity],
                "memory_types": [memory_type],
                "previous_context_id": capsule_id,
            },
        )
        if task_free_reuse_result.is_error or not isinstance(
            task_free_reuse_result.structured_content, dict
        ):
            raise SmokeError("M6 task-off reuse of task-on receipt failed")
        task_free_reuse = dict(task_free_reuse_result.structured_content)

        widening = await client.call_tool(
            "milai_memory_resolve",
            {
                "query": query,
                "task_context": {"project_ids": ["attacker-project"]},
            },
        )
        widening_rejected = widening.is_error
    print(
        json.dumps(
            {
                "catalog": catalog,
                "observations": observations,
                "task_context_schema_present": task_context_schema_present,
                "task_free_reuse": task_free_reuse,
                "widening_rejected": widening_rejected,
            },
            sort_keys=True,
        )
    )


async def _trace(client: Any, body: dict[str, Any], arm: str) -> dict[str, Any]:
    trace_id = body.get("trace_id")
    if not isinstance(trace_id, str):
        raise SmokeError(f"M6 {arm} resolve omitted trace identity")
    result = await client.call_tool("milai_trace_get", {"trace_id": trace_id})
    if result.is_error or not isinstance(result.structured_content, dict):
        raise SmokeError(f"M6 {arm} trace recovery failed")
    return dict(result.structured_content)


def _run_mcp_child(
    *,
    base_url: str,
    reader_token: str,
    query: str,
    entity: str,
    memory_type: str,
    rounds: int,
) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "MILAI_BASE_URL": base_url,
        "MILAI_AGENT_TOKEN": reader_token,
        "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["milai"]}',
        "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
        "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
        "MILAI_AGENT_MAX_LIMIT": "3",
        "MILAI_M6_QUERY": query,
        "MILAI_M6_ENTITY": entity,
        "MILAI_M6_MEMORY_TYPE": memory_type,
    }
    completed = subprocess.run(
        [
            str(ROOT / "integrations/mcp/.venv/bin/python"),
            str(Path(__file__).resolve()),
            "--mcp-call",
            "--rounds",
            str(rounds),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise SmokeError(
            "M6 MCP child failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("M6 MCP child returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeError("M6 MCP child returned a non-object")
    return result


def _p95(values: list[float]) -> float:
    if not values:
        raise SmokeError("M6 p95 requires observations")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _context_tokens(body: dict[str, Any]) -> int:
    trace = body.get("search_trace")
    value = trace.get("context_token_upper_bound") if isinstance(trace, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SmokeError("M6 resolve omitted context token upper bound")
    return value


def _query_authority(trace: dict[str, Any]) -> str | None:
    plan = trace.get("query_plan")
    value = plan.get("required_authority") if isinstance(plan, dict) else None
    return value if isinstance(value, str) else None


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

    if not 4 <= args.rounds <= 30:
        raise SmokeError("--rounds must be between 4 and 30")
    load_runtime_environment(args.env_file.resolve())
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise SmokeError("fresh Runtime database-role URLs are absent")
    suffix = hashlib.sha256(args.run_id.encode()).hexdigest()[:20]
    database_name = f"milai_smoke_dg13m6_{suffix}"
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
    migration_head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    database_created = False
    api_process: subprocess.Popen[bytes] | None = None
    fixture: dict[str, str] | None = None
    mcp_result: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="milai-dg13-m6-") as temporary_value:
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
                marker = f"m6shared{uuid4().hex}"
                fixture = _seed_claim(
                    base_url,
                    submitter_token=tokens["submitter"],
                    reviewer_token=tokens["reviewer"],
                    marker=marker,
                    subject_id=f"release-alpha-{suffix}",
                    claim_type="PROJECT_STATE",
                )
                for label in ("beta", "gamma", "delta", "epsilon", "zeta"):
                    _seed_claim(
                        base_url,
                        submitter_token=tokens["submitter"],
                        reviewer_token=tokens["reviewer"],
                        marker=marker,
                        subject_id=f"release-{label}-{suffix}",
                        claim_type="PROJECT_STATE",
                    )
                worker_environment = dict(environment)
                worker_environment["MILAI_WORKER_DATABASE_URL"] = database_urls["worker"]
                worker = subprocess.run(
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
                    raise SmokeError("M6 projection worker failed")
                query = f"Recall {fixture['subject_id']} {marker} governed status"
                mcp_result = _run_mcp_child(
                    base_url=base_url,
                    reader_token=tokens["reader"],
                    query=query,
                    entity=fixture["subject_id"],
                    memory_type=fixture["claim_type"],
                    rounds=args.rounds,
                )
            finally:
                _terminate(api_process)
                runtime_log.close()
        finally:
            cleanup = (
                _drop_database(owner_source, database_name)
                if database_created
                else {"status": "NOT_CREATED"}
            )
            if database_created and cleanup.get("status") != "PASS":
                raise SmokeError("M6 fresh database cleanup failed")

    if fixture is None or mcp_result is None:
        raise SmokeError("M6 smoke did not complete")
    observations = mcp_result.get("observations")
    if not isinstance(observations, list) or len(observations) != args.rounds:
        raise SmokeError("M6 observation count is invalid")
    expected = fixture["claim_version_id"]
    off_runtime: list[float] = []
    on_runtime: list[float] = []
    off_handler: list[float] = []
    on_handler: list[float] = []
    off_candidates: list[int] = []
    on_candidates: list[int] = []
    off_context: list[int] = []
    on_context: list[int] = []
    for raw in observations:
        if not isinstance(raw, dict):
            raise SmokeError("M6 observation is not an object")
        off = raw.get("task_off")
        on = raw.get("task_on")
        off_trace = raw.get("task_off_trace")
        on_trace = raw.get("task_on_trace")
        if not isinstance(off, dict):
            raise SmokeError("M6 task-off observation is malformed")
        if not isinstance(on, dict):
            raise SmokeError("M6 task-on observation is malformed")
        if not isinstance(off_trace, dict):
            raise SmokeError("M6 task-off trace is malformed")
        if not isinstance(on_trace, dict):
            raise SmokeError("M6 observation sections are malformed")
        off = dict(off)
        on = dict(on)
        off_trace = dict(off_trace)
        on_trace = dict(on_trace)
        if expected not in _item_ids(off) or _item_ids(on) != [expected]:
            raise SmokeError("M6 task-on/off quality slice returned a wrong version")
        on_enhancement = on.get("task_enhancement")
        if "task_enhancement" in off:
            raise SmokeError("M6 task-off response leaked a Task-shaped field")
        if (
            not isinstance(on_enhancement, dict)
            or on_enhancement.get("applied") is not True
            or on_enhancement.get("authority_unchanged") is not True
            or on_enhancement.get("action_risk_non_authoritative") is not True
        ):
            raise SmokeError("M6 task-on governance trace is incomplete")
        if _query_authority(off_trace) != _query_authority(on_trace):
            raise SmokeError("M6 TaskContext changed required authority")
        off_runtime.append(_span(off, "runtime_kernel_ms"))
        on_runtime.append(_span(on, "runtime_kernel_ms"))
        off_handler.append(_span(off, "mcp_handler_ms"))
        on_handler.append(_span(on, "mcp_handler_ms"))
        off_candidates.append(_trace_candidate_count(off_trace))
        on_candidates.append(_trace_candidate_count(on_trace))
        off_context.append(_context_tokens(off))
        on_context.append(_context_tokens(on))

    candidate_improved = max(on_candidates) < max(off_candidates)
    context_improved = max(on_context) < max(off_context)
    if not candidate_improved and not context_improved:
        raise SmokeError("M6 TaskContext did not improve candidate or context cost")
    if mcp_result.get("task_context_schema_present") is not True:
        raise SmokeError("M6 detail profile did not advertise TaskContext")
    if mcp_result.get("widening_rejected") is not True:
        raise SmokeError("M6 project-scope widening was not rejected")
    task_free_reuse = mcp_result.get("task_free_reuse")
    last_task_on = observations[-1]["task_on"]
    if (
        not isinstance(task_free_reuse, dict)
        or task_free_reuse.get("receipt_reused") is not True
        or task_free_reuse.get("trace_id") != last_task_on.get("trace_id")
        or "task_enhancement" in task_free_reuse
        or any(str(key).lower().startswith("task") for key in task_free_reuse)
    ):
        raise SmokeError("M6 task-off receipt reuse was not task-free compatible")

    report = {
        "schema": "milai.dg13.m6-task-enhancement.v1",
        "run_id": args.run_id,
        "status": "PASS",
        "source_identity": _source_identity(
            (
                Path(__file__).resolve(),
                ROOT / "runtime/src/milai/application/context_receipt.py",
                ROOT / "runtime/src/milai/application/memory_resolve.py",
                ROOT / "runtime/src/milai/domain/memory_resolve.py",
                ROOT / "integrations/mcp/src/milai_mcp/server.py",
            )
        ),
        "runtime": {
            "fresh_database": True,
            "migration_head": migration_head,
            "database_cleanup": "PASS",
            "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
            "implementation_status": "0.1.x CANDIDATE",
        },
        "mcp": {
            "profile": "reader-detail",
            "processes": 1,
            "client_sessions": 1,
            "resolve_calls": args.rounds * 2 + 2,
            "diagnostic_trace_calls": args.rounds * 2,
            "logical_calls_per_resolve": 1,
            "automatic_retries": 0,
            "tool_catalog": mcp_result.get("catalog"),
        },
        "matched_ablation": {
            "rounds_per_arm": args.rounds,
            "same_database_fixture_query_scope": True,
            "expected_claim_version_id": expected,
            "task_off_quality_hits": args.rounds,
            "task_on_quality_hits": args.rounds,
            "task_free_correctness_non_inferior": True,
            "task_on_receipt_reused_task_off_without_task_fields": True,
        },
        "cost": {
            "task_off_candidate_count_max": max(off_candidates),
            "task_on_candidate_count_max": max(on_candidates),
            "task_off_context_token_upper_bound_max": max(off_context),
            "task_on_context_token_upper_bound_max": max(on_context),
            "task_off_runtime_kernel_p95_ms": round(_p95(off_runtime), 3),
            "task_on_runtime_kernel_p95_ms": round(_p95(on_runtime), 3),
            "task_off_mcp_handler_p95_ms": round(_p95(off_handler), 3),
            "task_on_mcp_handler_p95_ms": round(_p95(on_handler), 3),
            "candidate_cost_improved": candidate_improved,
            "context_cost_improved": context_improved,
        },
        "gate": {
            "task_optional_and_task_free_non_inferior": "PASS",
            "task_context_only_narrows": "PASS",
            "task_context_does_not_grant_authority": "PASS",
            "task_on_receipt_reuse_remains_task_free": "PASS",
            "project_scope_widening_rejected": "PASS",
            "matched_candidate_or_context_cost_improved": "PASS",
            "same_runtime_planner_and_canonical_gate": "PASS",
        },
    }
    target_dir = args.report_root / args.run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    (target_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return report


def main() -> int:
    args = _parser().parse_args()
    if args.mcp_call:
        asyncio.run(_mcp_call_mode(args.rounds))
        return 0
    try:
        report = _run(args)
    except (OSError, SmokeError, subprocess.SubprocessError) as exc:
        print(f"DG-13 M6 task enhancement failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
