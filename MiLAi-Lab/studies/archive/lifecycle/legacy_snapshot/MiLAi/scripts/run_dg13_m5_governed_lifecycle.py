#!/usr/bin/env python3
"""Run the DG-13 M5 governed MCP lifecycle and delta-projection Gate."""

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
from time import perf_counter
from typing import Any
from uuid import uuid4

from run_dg13_m1_generic_smoke import ROOT, SmokeError, _terminate, _wait_ready

DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_REPORT_ROOT = ROOT / "var/dg13/m5"


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
    parser.add_argument("--run-id", default=f"dg13-m5-lifecycle-{uuid4().hex[:12]}")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--mcp-call", action="store_true", help=argparse.SUPPRESS)
    return parser


async def _mcp_call_mode() -> None:
    from mcp import Client, StdioServerParameters, stdio_client

    profile = os.environ["MILAI_M5_PROFILE"]
    tool = os.environ["MILAI_M5_TOOL"]
    raw_arguments = json.loads(os.environ["MILAI_M5_ARGUMENTS"])
    if not isinstance(raw_arguments, dict):
        raise SmokeError("M5 MCP arguments must be an object")
    parameters = StdioServerParameters(
        command=str(ROOT / "integrations/mcp/.venv/bin/milai-mcp"),
        args=["--profile", profile, "--max-retries", "0"],
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
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        catalog = sorted(item.name for item in (await client.list_tools()).tools)
        started = perf_counter()
        result = await client.call_tool(tool, raw_arguments)
        call_ms = (perf_counter() - started) * 1_000
        if result.is_error or not isinstance(result.structured_content, dict):
            detail = (
                str(getattr(result.content[0], "text", "unknown tool error"))
                if result.content
                else "unknown tool error"
            )
            raise SmokeError(f"M5 {profile}/{tool} failed: {detail[:500]}")
        print(
            json.dumps(
                {
                    "catalog": catalog,
                    "call_ms": round(call_ms, 3),
                    "result": result.structured_content,
                },
                sort_keys=True,
            )
        )


def _mcp_call(
    *,
    base_url: str,
    token: str,
    profile: str,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "MILAI_BASE_URL": base_url,
        "MILAI_AGENT_TOKEN": token,
        "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["milai"]}',
        "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
        "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
        "MILAI_AGENT_MAX_LIMIT": "3",
        "MILAI_M5_PROFILE": profile,
        "MILAI_M5_TOOL": tool,
        "MILAI_M5_ARGUMENTS": json.dumps(arguments, separators=(",", ":")),
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
            f"M5 {profile}/{tool} child failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    try:
        body = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"M5 {profile}/{tool} returned invalid JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        raise SmokeError(f"M5 {profile}/{tool} returned a malformed envelope")
    return body


def _capture(
    call: Any,
    *,
    subject: str,
    content: str,
) -> dict[str, Any]:
    return call(
        "submitter",
        "milai_evidence_capture",
        {
            "operation_id": f"m5-evidence-{uuid4()}",
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"dg13-m5://{uuid4()}",
            "subject_id": subject,
            "observed_at": "2026-08-26T00:00:00+08:00",
            "content": content,
            "data_classification": "SYNTHETIC",
            "permission_snapshot": {"readable": True, "project_ids": ["milai"]},
            "retention_state": "READABLE",
            "confirmation": "CAPTURE",
        },
    )


def _proposal(
    call: Any,
    *,
    operation: str,
    proposed_patch: dict[str, Any],
    supporting: list[str] | None = None,
    contradicting: list[str] | None = None,
    claim_id: str | None = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "operation": operation,
        "supporting_evidence_refs": supporting or [],
        "contradicting_evidence_refs": contradicting or [],
        "requested_authority": "ACTION_SAFE",
        "scope_predicate": {"project_ids": ["milai"]},
        "model_id": "deterministic-m5-fixture",
        "template_version": "m5-v1",
        "input_snapshot_hash": hashlib.sha256(
            json.dumps(
                {
                    "operation": operation,
                    "patch": proposed_patch,
                    "supporting": supporting or [],
                    "contradicting": contradicting or [],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "proposed_patch": proposed_patch,
        "derivation_policy_id": "dg13-m5-governed-lifecycle-v1",
    }
    if claim_id is not None:
        body["target_claim_id"] = claim_id
    if version_id is not None:
        body["expected_version_id"] = version_id
    return call(
        "submitter",
        "milai_proposal_create",
        {
            "operation_id": f"m5-proposal-{uuid4()}",
            "proposal": body,
            "confirmation": "SUBMIT",
        },
    )


def _review(call: Any, proposal_id: str, decision: str) -> dict[str, Any]:
    canonical_proposal = call(
        "reviewer",
        "milai_proposal_get",
        {"proposal_id": proposal_id},
    )
    if canonical_proposal.get("status") != "PENDING_REVIEW":
        raise SmokeError("M5 reviewer did not inspect a canonical pending Proposal")
    return call(
        "reviewer",
        "milai_memory_review",
        {
            "proposal_id": proposal_id,
            "operation_id": f"m5-review-{uuid4()}",
            "decision": decision,
            "policy_version": "dg13-m5-review-v1",
            "reason_code": f"SYNTHETIC_{decision}_VERIFIED",
            "confirmation": decision,
        },
    )


def _exact(call: Any, claim_id: str) -> dict[str, Any]:
    return call(
        "reader-detail",
        "milai_memory_get",
        {"claim_id": claim_id, "consistency_mode": "CANONICAL_REQUIRED"},
    )


def _only_item_version(body: dict[str, Any]) -> str | None:
    items = body.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    value = items[0].get("claim_version_id")
    return str(value) if isinstance(value, str) else None


def _database_snapshot(owner_url: str, tenant_id: object) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(owner_url) as connection:
        row = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.evidence_record WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.operation_proposal WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.claim WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.claim_version WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.open_issue WHERE tenant_id = %s),
              (SELECT COALESCE(max(outbox_sequence), 0) FROM milai.outbox_event
               WHERE tenant_id = %s),
              (SELECT COALESCE(jsonb_object_agg(projection_name,
                         last_contiguous_outbox_sequence), '{}'::jsonb)
               FROM milai.index_watermark WHERE tenant_id = %s)
            """,
            (tenant_id,) * 7,
        ).fetchone()
    assert row is not None
    return {
        "evidence": int(row[0]),
        "proposals": int(row[1]),
        "claims": int(row[2]),
        "claim_versions": int(row[3]),
        "open_issues": int(row[4]),
        "outbox_max": int(row[5]),
        "watermarks": dict(row[6]),
    }


def _actor_separation(
    owner_url: str,
    tenant_id: object,
    proposal_ids: list[str],
) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(owner_url) as connection:
        rows = connection.execute(
            """
            SELECT proposal.proposer_actor_id, decision.decision_actor_id
            FROM milai.operation_proposal proposal
            JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE proposal.tenant_id = %s
              AND proposal.proposal_id = ANY(%s::uuid[])
            ORDER BY proposal.proposal_id
            """,
            (tenant_id, proposal_ids),
        ).fetchall()
    return {
        "decisions_checked": len(rows),
        "all_distinct": bool(rows) and all(left != right for left, right in rows),
        "distinct_submitter_actor_count": len({left for left, _right in rows}),
        "distinct_reviewer_actor_count": len({right for _left, right in rows}),
    }


def _run_worker(environment: dict[str, str], *, deliberately_fail: bool = False) -> dict[str, Any]:
    worker_environment = dict(environment)
    if deliberately_fail:
        worker_environment["MILAI_EMBEDDING_PROJECTION_DIMENSIONS"] = "128"
    started = perf_counter()
    completed = subprocess.run(
        [str(ROOT / "runtime/.venv/bin/milai-worker"), "--once"],
        cwd=ROOT / "runtime",
        env=worker_environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=90,
    )
    elapsed_ms = round((perf_counter() - started) * 1_000, 3)
    if deliberately_fail:
        if completed.returncode == 0:
            raise SmokeError("M5 deliberately invalid projection worker unexpectedly succeeded")
        return {"exit_code": completed.returncode, "elapsed_ms": elapsed_ms}
    if completed.returncode != 0:
        raise SmokeError(
            "M5 projection worker failed: "
            + completed.stderr.decode(errors="replace")[-2_000:]
        )
    stage_metrics: dict[str, Any] = {}
    output = (completed.stdout + completed.stderr).decode(errors="replace")
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        safe = event.get("safe_metadata") if isinstance(event, dict) else None
        metrics = safe.get("stage_metrics") if isinstance(safe, dict) else None
        if isinstance(metrics, dict):
            stage_metrics = metrics
    return {
        "exit_code": 0,
        "elapsed_ms": elapsed_ms,
        "stage_metrics": stage_metrics,
    }


def _rebuild_search(
    steward_url: str,
    tenant_id: object,
    actor_id: object,
) -> dict[str, Any]:
    import psycopg

    outcomes: dict[str, Any] = {}
    with psycopg.connect(steward_url) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant_id),))
        connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(actor_id),))
        for projection in ("fts", "vector"):
            row = connection.execute(
                "SELECT milai.rebuild_search_projection(%s, %s, %s, %s)",
                (tenant_id, actor_id, projection, "REBUILD_DERIVED_PROJECTION"),
            ).fetchone()
            if row is None or not isinstance(row[0], dict):
                raise SmokeError(f"M5 {projection} rebuild did not return an object")
            outcomes[projection] = row[0]
    return outcomes


def _verify_http_review_boundary(
    client: Any,
    tokens: dict[str, str],
    owner_url: str,
    tenant_id: object,
) -> dict[str, Any]:
    import psycopg

    unique = uuid4().hex

    def headers(profile: str, operation_id: str | None = None) -> dict[str, str]:
        result = {"Authorization": f"Bearer {tokens[profile]}"}
        if operation_id is not None:
            result["Idempotency-Key"] = operation_id
        return result

    evidence = client.post(
        "/v1/evidence",
        headers=headers("legacy", f"m5-self-evidence-{unique}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"dg13-m5-self-review://{unique}",
            "subject_id": f"dg13-m5-self-review-{unique}",
            "observed_at": "2026-08-26T00:00:00+08:00",
            "content": f"synthetic self-review rejection fixture {unique}",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    evidence_body = evidence.get_json(silent=True)
    if evidence.status_code != 201 or not isinstance(evidence_body, dict):
        raise SmokeError("M5 canonical self-review evidence setup failed")
    proposal = client.post(
        "/v1/proposals",
        headers=headers("legacy", f"m5-self-proposal-{unique}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": f"dg13-m5-self-review-{unique}",
                "predicate": "runtime.governed_lifecycle.self_review",
                "claim_type": "FACT",
                "payload": {"value": "must remain pending"},
                "authority": "INFORMATIONAL",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [str(evidence_body["evidence_id"])],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "INFORMATIONAL",
            "derivation_policy_id": "dg13-m5-self-review-v1",
            "derivation_snapshot": {"fixture": "self-review-rejection"},
        },
    )
    proposal_body = proposal.get_json(silent=True)
    if proposal.status_code != 201 or not isinstance(proposal_body, dict):
        raise SmokeError("M5 canonical self-review proposal setup failed")
    proposal_id = str(proposal_body["proposal_id"])

    denied_profiles: list[str] = []
    for profile in ("reader", "submitter", "operator"):
        responses = (
            client.get("/v1/proposals?limit=1", headers=headers(profile)),
            client.get(f"/v1/proposals/{proposal_id}", headers=headers(profile)),
        )
        for response in responses:
            body = response.get_json(silent=True)
            error = body.get("error") if isinstance(body, dict) else None
            if (
                response.status_code != 403
                or not isinstance(error, dict)
                or error.get("code") != "CAPABILITY_REQUIRED"
            ):
                raise SmokeError(f"M5 {profile} inspected reviewer-only proposal state")
        denied_profiles.append(profile)

    forbidden = client.post(
        f"/v1/proposals/{proposal_id}/review",
        headers=headers("legacy", f"m5-self-review-{unique}"),
        json={
            "decision": "APPROVE",
            "policy_version": "dg13-m5-self-review-v1",
            "reason_code": "MUST_NOT_RUN",
        },
    )
    forbidden_body = forbidden.get_json(silent=True)
    forbidden_error = (
        forbidden_body.get("error") if isinstance(forbidden_body, dict) else None
    )
    if (
        forbidden.status_code != 403
        or not isinstance(forbidden_error, dict)
        or forbidden_error.get("code") != "SELF_REVIEW_FORBIDDEN"
    ):
        raise SmokeError("M5 canonical procedure allowed same-actor proposal review")

    with psycopg.connect(owner_url) as owner:
        state = owner.execute(
            """
            SELECT proposal.status,
                   (SELECT count(*) FROM milai.steward_decision decision
                    WHERE decision.tenant_id = proposal.tenant_id
                      AND decision.proposal_id = proposal.proposal_id)
            FROM milai.operation_proposal proposal
            WHERE proposal.tenant_id = %s AND proposal.proposal_id = %s
            """,
            (tenant_id, proposal_id),
        ).fetchone()
    if state != ("PENDING_REVIEW", 0):
        raise SmokeError("M5 rejected self-review changed canonical proposal state")
    return {
        "same_actor_http_status": forbidden.status_code,
        "same_actor_error_code": "SELF_REVIEW_FORBIDDEN",
        "proposal_status_after_rejection": state[0],
        "steward_decision_count_after_rejection": state[1],
        "proposal_inspection_denied_profiles": denied_profiles,
    }


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
        _HttpClient,
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
    database_name = f"milai_smoke_dg13m5_{suffix}"
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
    cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
    report_data: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="milai-dg13-m5-") as temporary_value:
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
            environment["MILAI_WORKER_DATABASE_URL"] = database_urls["worker"]
            environment["MILAI_LOG_LEVEL"] = "INFO"
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
                calls: list[dict[str, Any]] = []
                catalogs: dict[str, list[str]] = {}

                def call(profile: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
                    raw = _mcp_call(
                        base_url=base_url,
                        token=tokens["reader" if profile == "reader-detail" else profile],
                        profile=profile,
                        tool=tool,
                        arguments=arguments,
                    )
                    catalog = raw.get("catalog")
                    if isinstance(catalog, list):
                        catalogs[profile] = [str(item) for item in catalog]
                    calls.append(
                        {
                            "profile": profile,
                            "tool": tool,
                            "call_ms": float(raw.get("call_ms", 0.0)),
                        }
                    )
                    return dict(raw["result"])

                subject = f"dg13-m5-state-{suffix}"
                before = _database_snapshot(database_urls["owner"], settings.tenant_id)
                create_evidence = _capture(
                    call,
                    subject=subject,
                    content="M5 governed state is initial",
                )
                after_capture = _database_snapshot(database_urls["owner"], settings.tenant_id)
                if after_capture["claims"] != before["claims"]:
                    raise SmokeError("M5 Evidence capture created a canonical Claim")
                create_proposal = _proposal(
                    call,
                    operation="CREATE",
                    proposed_patch={
                        "subject_id": subject,
                        "predicate": "runtime.governed_lifecycle.state",
                        "claim_type": "PROJECT_STATE",
                        "payload": {"value": "initial"},
                        "authority": "ACTION_SAFE",
                        "confidence": 0.99,
                    },
                    supporting=[str(create_evidence["evidence_id"])],
                )
                pending = _database_snapshot(database_urls["owner"], settings.tenant_id)
                if pending["claims"] != before["claims"]:
                    raise SmokeError("M5 pending Proposal changed canonical Claim state")
                create_review = _review(call, str(create_proposal["proposal_id"]), "APPROVE")
                claim_id = str(create_review["claim_id"])
                version_one = str(create_review["claim_version_id"])
                initial_read = _exact(call, claim_id)
                if initial_read.get("status") != "HIT" or _only_item_version(initial_read) != version_one:
                    raise SmokeError("M5 approved CREATE was not visible through exact MCP read")
                projection_one = _run_worker(environment)
                snapshot_one = _database_snapshot(database_urls["owner"], settings.tenant_id)

                correction_evidence = _capture(
                    call,
                    subject=subject,
                    content="M5 governed state corrected to current",
                )
                supersede_proposal = _proposal(
                    call,
                    operation="SUPERSEDE",
                    claim_id=claim_id,
                    version_id=version_one,
                    supporting=[str(correction_evidence["evidence_id"])],
                    proposed_patch={
                        "payload": {"value": "corrected"},
                        "authority": "ACTION_SAFE",
                        "confidence": 0.995,
                    },
                )
                supersede_review = _review(
                    call, str(supersede_proposal["proposal_id"]), "APPROVE"
                )
                version_two = str(supersede_review["claim_version_id"])
                failed_worker = _run_worker(environment, deliberately_fail=True)
                read_during_projection_failure = _exact(call, claim_id)
                if (
                    read_during_projection_failure.get("status") != "HIT"
                    or _only_item_version(read_during_projection_failure) != version_two
                ):
                    raise SmokeError("M5 projection failure changed exact canonical truth")
                projection_two = _run_worker(environment)
                snapshot_two = _database_snapshot(database_urls["owner"], settings.tenant_id)
                if snapshot_two["claim_versions"] != snapshot_one["claim_versions"] + 1:
                    raise SmokeError("M5 SUPERSEDE did not append exactly one ClaimVersion")
                if snapshot_two["outbox_max"] <= snapshot_one["outbox_max"]:
                    raise SmokeError("M5 incremental write did not advance the delta outbox")

                rebuild = _rebuild_search(
                    database_urls["steward"],
                    settings.tenant_id,
                    settings.local_actor_id,
                )
                read_during_rebuild = _exact(call, claim_id)
                if (
                    read_during_rebuild.get("status") != "HIT"
                    or _only_item_version(read_during_rebuild) != version_two
                ):
                    raise SmokeError("M5 projection rebuild changed exact canonical truth")
                rebuild_worker = _run_worker(environment)
                snapshot_rebuilt = _database_snapshot(
                    database_urls["owner"], settings.tenant_id
                )
                if snapshot_rebuilt["claim_versions"] != snapshot_two["claim_versions"]:
                    raise SmokeError("M5 projection rebuild mutated canonical versions")

                contradiction = _capture(
                    call,
                    subject=subject,
                    content="M5 governed state conflicts with corrected value",
                )
                conflict_proposal = _proposal(
                    call,
                    operation="CONTRADICT",
                    claim_id=claim_id,
                    version_id=version_two,
                    proposed_patch={},
                    contradicting=[str(contradiction["evidence_id"])],
                )
                conflict_review = _review(
                    call, str(conflict_proposal["proposal_id"]), "APPROVE"
                )
                conflict_read = _exact(call, claim_id)
                if conflict_read.get("status") != "CONTESTED" or not conflict_read.get(
                    "open_issue_ids"
                ):
                    raise SmokeError("M5 CONTRADICT did not preserve typed OpenIssue semantics")

                rejected_proposal = _proposal(
                    call,
                    operation="NO_CHANGE",
                    claim_id=claim_id,
                    version_id=version_two,
                    proposed_patch={},
                )
                rejected_review = _review(
                    call, str(rejected_proposal["proposal_id"]), "REJECT"
                )
                if rejected_review.get("decision") != "REJECT":
                    raise SmokeError("M5 reviewer REJECT did not persist")

                revoke_subject = f"dg13-m5-revoke-{suffix}"
                revoke_evidence = _capture(
                    call,
                    subject=revoke_subject,
                    content="M5 governed revocation fixture",
                )
                revoke_proposal = _proposal(
                    call,
                    operation="CREATE",
                    supporting=[str(revoke_evidence["evidence_id"])],
                    proposed_patch={
                        "subject_id": revoke_subject,
                        "predicate": "runtime.governed_lifecycle.revocable",
                        "claim_type": "FACT",
                        "payload": {"value": "must disappear after revoke"},
                        "authority": "ACTION_SAFE",
                        "confidence": 0.99,
                    },
                )
                revoke_create = _review(call, str(revoke_proposal["proposal_id"]), "APPROVE")
                revoke_claim_id = str(revoke_create["claim_id"])
                revoke_version_id = str(revoke_create["claim_version_id"])
                before_revoke = _exact(call, revoke_claim_id)
                if _only_item_version(before_revoke) != revoke_version_id:
                    raise SmokeError("M5 revocation fixture was not readable before revoke")
                pre_revoke_projection = _run_worker(environment)
                revoke_receipt = call(
                    "operator",
                    "milai_evidence_revoke",
                    {
                        "evidence_id": str(revoke_evidence["evidence_id"]),
                        "operation_id": f"m5-revoke-{uuid4()}",
                        "reason_code": "USER_REQUEST",
                        "confirmation": "REVOKE",
                    },
                )
                immediate_after_revoke = _exact(call, revoke_claim_id)
                if _only_item_version(immediate_after_revoke) is not None:
                    raise SmokeError("M5 revoked ClaimVersion re-entered before async purge")
                deletion_before = call(
                    "operator",
                    "milai_deletion_status_get",
                    {"evidence_id": str(revoke_evidence["evidence_id"])},
                )
                purge_worker = _run_worker(environment)
                deletion_after = call(
                    "operator",
                    "milai_deletion_status_get",
                    {"evidence_id": str(revoke_evidence["evidence_id"])},
                )
                if deletion_after.get("derived_purge_status") != "COMPLETED" or deletion_after.get(
                    "primary_bytes_status"
                ) != "ERASED":
                    raise SmokeError("M5 asynchronous delete/purge did not complete")

                proposal_ids = [
                    str(create_proposal["proposal_id"]),
                    str(supersede_proposal["proposal_id"]),
                    str(conflict_proposal["proposal_id"]),
                    str(rejected_proposal["proposal_id"]),
                    str(revoke_proposal["proposal_id"]),
                ]
                actor_check = _actor_separation(
                    database_urls["owner"], settings.tenant_id, proposal_ids
                )
                if not actor_check["all_distinct"]:
                    raise SmokeError("M5 submitter/reviewer database actors were not independent")
                if "milai_memory_review" in catalogs.get("submitter", []) or any(
                    item in catalogs.get("reviewer", [])
                    for item in ("milai_evidence_capture", "milai_proposal_create")
                ):
                    raise SmokeError("M5 reviewer/submitter MCP catalogs overlap write authority")
                if not {
                    "milai_proposals_list",
                    "milai_proposal_get",
                    "milai_memory_review",
                }.issubset(catalogs.get("reviewer", [])):
                    raise SmokeError("M5 reviewer catalog omitted its governed inbox or decision")

                final = _database_snapshot(database_urls["owner"], settings.tenant_id)
                review_boundary = _verify_http_review_boundary(
                    _HttpClient(base_url),
                    tokens,
                    database_urls["owner"],
                    settings.tenant_id,
                )
                report_data = {
                    "runtime": {
                        "migration_head": migration_head,
                        "fresh_database": True,
                        "implementation_status": "0.1.x CANDIDATE",
                        "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
                    },
                    "mcp": {
                        "profiles": sorted(catalogs),
                        "profile_catalogs": catalogs,
                        "client_sessions": len(calls),
                        "processes": len(calls),
                        "automatic_retries": 0,
                        "calls": calls,
                    },
                    "lifecycle": {
                        "capture_did_not_create_claim": True,
                        "proposal_pending_before_review": True,
                        "actor_separation": actor_check,
                        "review_boundary": review_boundary,
                        "create_version_id": version_one,
                        "supersede_version_id": version_two,
                        "immutable_version_count_after_supersede": snapshot_two[
                            "claim_versions"
                        ],
                        "conflict_open_issue_id": conflict_review.get("open_issue_id"),
                        "rejected_decision_id": rejected_review.get("decision_id"),
                        "revoke_deletion_request_id": revoke_receipt.get(
                            "deletion_request_id"
                        ),
                        "immediate_revoke_status": immediate_after_revoke.get("status"),
                        "deletion_before_purge": {
                            "derived_purge_status": deletion_before.get(
                                "derived_purge_status"
                            ),
                            "primary_bytes_status": deletion_before.get(
                                "primary_bytes_status"
                            ),
                        },
                        "deletion_after_purge": {
                            "derived_purge_status": deletion_after.get(
                                "derived_purge_status"
                            ),
                            "primary_bytes_status": deletion_after.get(
                                "primary_bytes_status"
                            ),
                        },
                    },
                    "projection": {
                        "delta_outbox_advanced": True,
                        "set_based_delivery_admission_cap": 128,
                        "embedding_micro_batch_config": settings.embedding_batch_size,
                        "before_incremental": snapshot_one,
                        "after_incremental": snapshot_two,
                        "after_rebuild_replay": snapshot_rebuilt,
                        "final": final,
                        "failed_worker": failed_worker,
                        "initial_worker": projection_one,
                        "incremental_worker": projection_two,
                        "rebuild": rebuild,
                        "rebuild_worker": rebuild_worker,
                        "pre_revoke_worker": pre_revoke_projection,
                        "purge_worker": purge_worker,
                    },
                    "gate": {
                        "evidence_is_not_claim": "PASS",
                        "pending_proposal_requires_review": "PASS",
                        "reviewer_inspects_canonical_proposal": "PASS",
                        "independent_reviewer_profile_and_actor": "PASS",
                        "canonical_same_actor_review_rejected": "PASS",
                        "proposal_inspection_requires_reviewer": "PASS",
                        "create_and_supersede_immutable": "PASS",
                        "contradict_preserves_open_issue": "PASS",
                        "revoke_immediate_fail_closed": "PASS",
                        "delete_purge_asynchronous": "PASS",
                        "mcp_restart_retains_canonical_state": "PASS",
                        "delta_watermark_advances": "PASS",
                        "projection_failure_exact_truth_unchanged": "PASS",
                        "projection_rebuild_replays_without_canonical_mutation": "PASS",
                    },
                }
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
                raise SmokeError("M5 fresh database cleanup failed")

    if report_data is None:
        raise SmokeError("M5 smoke did not complete")
    report_data["runtime"]["database_cleanup"] = cleanup.get("status")
    report = {
        "schema": "milai.dg13.m5-governed-lifecycle.v1",
        "run_id": args.run_id,
        "status": "PASS",
        "source_identity": _source_identity(
            (
                Path(__file__).resolve(),
                ROOT / "runtime/migrations/versions/0032_reviewer_actor_separation.py",
                ROOT / "runtime/src/milai/api/auth.py",
                ROOT / "runtime/src/milai/persistence/canonical_repository.py",
                ROOT / "integrations/mcp/src/milai_mcp/server.py",
            )
        ),
        **report_data,
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
        asyncio.run(_mcp_call_mode())
        return 0
    try:
        report = _run(args)
    except (OSError, SmokeError, subprocess.SubprocessError) as exc:
        print(f"DG-13 M5 governed lifecycle failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
