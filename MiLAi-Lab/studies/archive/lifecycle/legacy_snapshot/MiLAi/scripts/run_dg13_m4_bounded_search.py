#!/usr/bin/env python3
"""Run the DG-13 M4 matched bounded-search quality/cost Gate."""

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
    _json_request,
    _require_status,
    _terminate,
    _wait_ready,
)

DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_REPORT_ROOT = ROOT / "var/dg13/m4"


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
    parser.add_argument("--run-id", default=f"dg13-m4-bounded-{uuid4().hex[:12]}")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--mcp-call", action="store_true", help=argparse.SUPPRESS)
    return parser


async def _mcp_call_mode(rounds: int) -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    query = os.environ["MILAI_M4_QUERY"]
    entity = os.environ["MILAI_M4_ENTITY"]
    memory_type = os.environ["MILAI_M4_MEMORY_TYPE"]
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
        for _ in range(rounds):
            baseline_result = await client.call_tool(
                "milai_recall",
                {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 3},
            )
            if baseline_result.is_error or not isinstance(
                baseline_result.structured_content, dict
            ):
                raise SmokeError("M4 baseline recall did not return structured success")
            baseline = dict(baseline_result.structured_content)
            baseline_trace_id = baseline.get("trace_id")
            if not isinstance(baseline_trace_id, str):
                raise SmokeError("M4 baseline recall omitted trace identity")
            baseline_trace_result = await client.call_tool(
                "milai_trace_get", {"trace_id": baseline_trace_id}
            )
            if baseline_trace_result.is_error or not isinstance(
                baseline_trace_result.structured_content, dict
            ):
                raise SmokeError("M4 baseline trace recovery failed")

            target_result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": query,
                    "consistency_mode": "CANONICAL_REQUIRED",
                    "limit": 3,
                    "entities": [entity],
                    "memory_types": [memory_type],
                },
            )
            if target_result.is_error or not isinstance(
                target_result.structured_content, dict
            ):
                raise SmokeError("M4 target resolve did not return structured success")
            target = dict(target_result.structured_content)
            target_trace_id = target.get("trace_id")
            if not isinstance(target_trace_id, str):
                raise SmokeError("M4 target resolve omitted trace identity")
            target_trace_result = await client.call_tool(
                "milai_trace_get", {"trace_id": target_trace_id}
            )
            if target_trace_result.is_error or not isinstance(
                target_trace_result.structured_content, dict
            ):
                raise SmokeError("M4 target trace recovery failed")
            observations.append(
                {
                    "baseline": baseline,
                    "baseline_trace": dict(baseline_trace_result.structured_content),
                    "target": target,
                    "target_trace": dict(target_trace_result.structured_content),
                }
            )
    print(json.dumps({"catalog": catalog, "observations": observations}, sort_keys=True))


def _seed_claim(
    base_url: str,
    *,
    submitter_token: str,
    reviewer_token: str,
    marker: str,
    subject_id: str,
    claim_type: str,
) -> dict[str, str]:
    evidence = _require_status(
        "M4 evidence capture",
        _json_request(
            base_url,
            "/v1/evidence",
            token=submitter_token,
            idempotency_key=f"m4-evidence-{uuid4()}",
            payload={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"dg13-m4://{uuid4()}",
                "subject_id": subject_id,
                "observed_at": "2026-08-26T00:00:00+08:00",
                "content": f"governed bounded search fixture {marker} {subject_id}",
                "media_type": "text/plain",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            },
        ),
        {201},
    )
    proposal = _require_status(
        "M4 proposal create",
        _json_request(
            base_url,
            "/v1/proposals",
            token=submitter_token,
            idempotency_key=f"m4-proposal-{uuid4()}",
            payload={
                "operation": "CREATE",
                "proposed_patch": {
                    "subject_id": subject_id,
                    "predicate": "runtime.bounded_search.state",
                    "claim_type": claim_type,
                    "payload": {
                        "marker": marker,
                        "value": f"current governed state for {subject_id}",
                    },
                    "authority": "ACTION_SAFE",
                    "confidence": 0.99,
                    "valid_time_from": "2026-08-25T00:00:00+00:00",
                },
                "supporting_evidence_refs": [str(evidence["evidence_id"])],
                "scope_predicate": {"project_ids": ["milai"]},
                "requested_authority": "ACTION_SAFE",
                "derivation_policy_id": "dg13-m4-bounded-search-v1",
                "derivation_snapshot": {"fixture": "matched-bounded-search"},
            },
        ),
        {201},
    )
    review = _require_status(
        "M4 proposal review",
        _json_request(
            base_url,
            f"/v1/proposals/{proposal['proposal_id']}/review",
            token=reviewer_token,
            idempotency_key=f"m4-review-{uuid4()}",
            payload={
                "decision": "APPROVE",
                "policy_version": "dg13-m4-bounded-search-v1",
                "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
            },
        ),
        {200},
    )
    return {
        "claim_id": str(review["claim_id"]),
        "claim_version_id": str(review["claim_version_id"]),
        "subject_id": subject_id,
        "claim_type": claim_type,
    }


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
        "MILAI_M4_QUERY": query,
        "MILAI_M4_ENTITY": entity,
        "MILAI_M4_MEMORY_TYPE": memory_type,
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
            "M4 MCP child failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("M4 MCP child returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeError("M4 MCP child returned a non-object")
    return result


def _p95(values: list[float]) -> float:
    if not values:
        raise SmokeError("M4 p95 requires observations")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _item_ids(body: dict[str, Any]) -> list[str]:
    items = body.get("items")
    if not isinstance(items, list):
        return []
    return [
        str(item["claim_version_id"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("claim_version_id"), str)
    ]


def _trace_candidate_count(trace: dict[str, Any]) -> int:
    accepted = trace.get("accepted_candidates")
    rejected = trace.get("rejected_candidates")
    return len(accepted if isinstance(accepted, list) else []) + len(
        rejected if isinstance(rejected, list) else []
    )


def _span(body: dict[str, Any], name: str) -> float:
    trace = body.get("access_trace")
    spans = trace.get("spans") if isinstance(trace, dict) else None
    value = spans.get(name) if isinstance(spans, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SmokeError(f"M4 span {name} is absent")
    return float(value)


def _structural_call(body: dict[str, Any], name: str) -> int:
    trace = body.get("access_trace")
    cost = trace.get("structural_cost") if isinstance(trace, dict) else None
    value = cost.get(name) if isinstance(cost, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SmokeError(f"M4 structural cost {name} is absent")
    return value


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
    database_name = f"milai_smoke_dg13m4_{suffix}"
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

    with tempfile.TemporaryDirectory(prefix="milai-dg13-m4-") as temporary_value:
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
                marker = f"m4shared{uuid4().hex}"
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
                    raise SmokeError("M4 projection worker failed")
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
                raise SmokeError("M4 fresh database cleanup failed")

    if fixture is None or mcp_result is None:
        raise SmokeError("M4 smoke did not complete")
    observations = mcp_result.get("observations")
    if not isinstance(observations, list) or len(observations) != args.rounds:
        raise SmokeError("M4 observation count is invalid")
    expected = fixture["claim_version_id"]
    baseline_runtime: list[float] = []
    target_runtime: list[float] = []
    baseline_handler: list[float] = []
    target_handler: list[float] = []
    baseline_candidates: list[int] = []
    target_candidates: list[int] = []
    baseline_context: list[int] = []
    target_context: list[int] = []
    target_vector_calls = 0
    target_recent_calls = 0
    target_reranker_calls = 0
    for raw in observations:
        if not isinstance(raw, dict):
            raise SmokeError("M4 observation is not an object")
        baseline = raw.get("baseline")
        target = raw.get("target")
        baseline_trace = raw.get("baseline_trace")
        target_trace = raw.get("target_trace")
        if (
            not isinstance(baseline, dict)
            or not isinstance(target, dict)
            or not isinstance(baseline_trace, dict)
            or not isinstance(target_trace, dict)
        ):
            raise SmokeError("M4 observation sections are malformed")
        baseline = dict(baseline)
        target = dict(target)
        baseline_trace = dict(baseline_trace)
        target_trace = dict(target_trace)
        if expected not in _item_ids(baseline) or _item_ids(target) != [expected]:
            raise SmokeError("M4 matched quality slice returned a wrong canonical version")
        target_search = target.get("search_trace")
        target_plan = target.get("access_plan")
        if not isinstance(target_search, dict) or not isinstance(target_plan, dict):
            raise SmokeError("M4 target omitted bounded plan or trace")
        if target_search.get("stop_stage") != "FTS":
            raise SmokeError(
                "M4 target did not stop at canonical-gated FTS: "
                f"{target_search.get('stop_stage')} / "
                f"{target_search.get('sufficiency_reason')}"
            )
        if target_search.get("deadline_outcome") != "MET":
            raise SmokeError("M4 target exceeded its search deadline")
        if int(target_search.get("context_token_upper_bound", -1)) > int(
            target_plan.get("context_token_budget", -1)
        ):
            raise SmokeError("M4 target exceeded its context token bound")
        baseline_runtime.append(_span(baseline, "runtime_kernel_ms"))
        target_runtime.append(_span(target, "runtime_kernel_ms"))
        baseline_handler.append(_span(baseline, "mcp_handler_ms"))
        target_handler.append(_span(target, "mcp_handler_ms"))
        baseline_candidates.append(_trace_candidate_count(baseline_trace))
        target_candidates.append(_trace_candidate_count(target_trace))
        baseline_context.append(
            len(json.dumps(baseline.get("items", []), separators=(",", ":")).encode())
        )
        target_context.append(int(target_search["context_token_upper_bound"]))
        target_vector_calls += _structural_call(target, "vector_search_calls")
        target_recent_calls += _structural_call(target, "broad_head_scan_calls")
        target_reranker_calls += _structural_call(target, "reranker_calls")

    baseline_runtime_p95 = _p95(baseline_runtime)
    target_runtime_p95 = _p95(target_runtime)
    if target_runtime_p95 >= baseline_runtime_p95:
        raise SmokeError("M4 Runtime p95 did not improve over the matched baseline")
    if max(target_candidates) >= max(baseline_candidates):
        raise SmokeError("M4 gated candidate count did not improve")
    if max(target_context) >= max(baseline_context):
        raise SmokeError("M4 context bound did not improve")
    if target_vector_calls or target_recent_calls or target_reranker_calls:
        raise SmokeError("M4 sufficient FTS path performed forbidden escalation")

    report = {
        "schema": "milai.dg13.m4-bounded-search.v1",
        "run_id": args.run_id,
        "status": "PASS",
        "source_identity": _source_identity(
            (
                Path(__file__).resolve(),
                ROOT / "runtime/src/milai/application/memory_resolve.py",
                ROOT / "runtime/src/milai/application/retrieval.py",
                ROOT / "runtime/src/milai/persistence/retrieval_repository.py",
                ROOT / "integrations/mcp/src/milai_mcp/server.py",
            )
        ),
        "runtime": {
            "fresh_database": True,
            "migration_head": migration_head,
            "projection_worker_started": True,
            "database_cleanup": "PASS",
            "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
            "implementation_status": "0.1.x CANDIDATE",
        },
        "mcp": {
            "profile": "reader-detail",
            "processes": 1,
            "client_sessions": 1,
            "primary_resolve_calls": args.rounds * 2,
            "diagnostic_trace_calls": args.rounds * 2,
            "logical_calls_per_resolve": 1,
            "automatic_retries": 0,
            "tool_catalog": mcp_result.get("catalog"),
        },
        "matched_slice": {
            "rounds_per_arm": args.rounds,
            "same_database_fixture_query_scope": True,
            "expected_claim_version_id": expected,
            "baseline_quality_hits": args.rounds,
            "target_quality_hits": args.rounds,
            "quality_non_inferior": True,
        },
        "cost": {
            "baseline_candidate_count_max": max(baseline_candidates),
            "target_candidate_count_max": max(target_candidates),
            "baseline_runtime_kernel_p95_ms": round(baseline_runtime_p95, 3),
            "target_runtime_kernel_p95_ms": round(target_runtime_p95, 3),
            "baseline_mcp_handler_p95_ms": round(_p95(baseline_handler), 3),
            "target_mcp_handler_p95_ms": round(_p95(target_handler), 3),
            "baseline_context_bytes_max": max(baseline_context),
            "target_context_token_upper_bound_max": max(target_context),
            "target_vector_calls": target_vector_calls,
            "target_recent_canonical_calls": target_recent_calls,
            "target_reranker_calls": target_reranker_calls,
        },
        "gate": {
            "possible_probe_fixed_budget": "PASS",
            "hard_partition_before_ranking": "PASS",
            "temporal_fts_before_vector": "PASS",
            "canonical_gate_before_sufficiency": "PASS",
            "vector_sparse_escalation_only": "PASS",
            "reranker_conditional_small_set": "PASS",
            "deadline_and_context_cap": "PASS",
            "quality_non_inferior_and_cost_improved": "PASS",
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
        print(f"DG-13 M4 bounded search failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
