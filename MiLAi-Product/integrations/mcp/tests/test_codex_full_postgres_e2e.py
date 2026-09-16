from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from milai_mcp.remote_registration import RemoteUserRegistry

_RUN_REAL_POSTGRES = os.environ.get("MILAI_MCP_BASELINE_E2E") == "1"
_DATABASE_PREFIX = "milai_mcpbase_"
_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME_ROOT = _ROOT / "runtime"

pytestmark = pytest.mark.skipif(
    not _RUN_REAL_POSTGRES,
    reason="set MILAI_MCP_BASELINE_E2E=1 for the disposable PostgreSQL MCP lifecycle",
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _database_url(source: str, database: str) -> str:
    parsed = urlsplit(source)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.username is None:
        raise AssertionError("unsafe PostgreSQL URL for disposable MCP test")
    if not re.fullmatch(r"milai_mcpbase_[0-9a-f]{20}", database):
        raise AssertionError("unsafe disposable MCP database name")
    return urlunsplit(parsed._replace(path=f"/{database}"))


def _postgres_environment(source: str, *, database: str | None = None) -> dict[str, str]:
    parsed = urlsplit(source)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.username is None:
        raise AssertionError("invalid PostgreSQL connection source")
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PG") and not key.startswith("MILAI_")
    }
    result.update(
        {
            "PGHOST": parsed.hostname or "",
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": unquote(parsed.username),
            "PGDATABASE": database or parsed.path.lstrip("/"),
        }
    )
    if parsed.password is not None:
        result["PGPASSWORD"] = unquote(parsed.password)
    query = parse_qs(parsed.query)
    if query.get("sslmode"):
        result["PGSSLMODE"] = query["sslmode"][0]
    return result


def _run_checked(
    arguments: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: int = 90,
) -> None:
    completed = subprocess.run(  # noqa: S603 - exact local product/tool executables
        arguments,
        cwd=cwd,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"local lifecycle command failed: {Path(arguments[0]).name} "
            f"exit={completed.returncode}"
        )


def _create_and_migrate_database(
    owner_source: str,
    database: str,
) -> dict[str, str]:
    owner_environment = _postgres_environment(owner_source)
    _run_checked(
        ["/usr/bin/createdb", "--owner=milai_owner", database],
        cwd=_ROOT,
        environment=owner_environment,
    )
    database_environment = _postgres_environment(owner_source, database=database)
    _run_checked(
        [
            "/usr/bin/psql",
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--command",
            (
                f'REVOKE ALL ON DATABASE "{database}" FROM PUBLIC; '
                f'GRANT CONNECT ON DATABASE "{database}" TO '
                "milai_api, milai_steward, milai_worker, milai_audit;"
            ),
        ],
        cwd=_ROOT,
        environment=database_environment,
    )
    urls = {
        "owner": _database_url(owner_source, database),
        "api": _database_url(_required_environment("MILAI_DATABASE_URL"), database),
        "steward": _database_url(
            _required_environment("MILAI_STEWARD_DATABASE_URL"), database
        ),
        "worker": _database_url(
            _required_environment("MILAI_WORKER_DATABASE_URL"), database
        ),
    }
    migration_environment = {
        **{key: value for key, value in os.environ.items() if not key.startswith("MILAI_")},
        "MILAI_MIGRATION_DATABASE_URL": urls["owner"],
    }
    _run_checked(
        [str(_RUNTIME_ROOT / ".venv/bin/alembic"), "-c", "alembic.ini", "upgrade", "head"],
        cwd=_RUNTIME_ROOT,
        environment=migration_environment,
        timeout=180,
    )
    return urls


def _drop_database(owner_source: str, database: str) -> None:
    if not database.startswith(_DATABASE_PREFIX) or len(database) > 63:
        raise AssertionError("refusing to drop a non-test database")
    environment = _postgres_environment(owner_source)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        completed = subprocess.run(  # noqa: S603 - fixed local dropdb executable
            ["/usr/bin/dropdb", "--if-exists", database],
            cwd=_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode == 0:
            return
        time.sleep(0.2)
    raise AssertionError("disposable MCP database still had live connections")


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise AssertionError(f"{name} is required for real PostgreSQL MCP E2E")
    return value


def _runtime_environment(
    urls: Mapping[str, str],
    tokens: Mapping[str, str],
    *,
    tenant_id: str,
    actor_id: str,
    blob_root: Path,
    port: int,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("MILAI_")
    }
    environment.update(
        {
            "MILAI_ENVIRONMENT": "test",
            "MILAI_DATABASE_URL": urls["api"],
            "MILAI_STEWARD_DATABASE_URL": urls["steward"],
            "MILAI_BLOB_ROOT": str(blob_root),
            "MILAI_TENANT_ID": tenant_id,
            "MILAI_LOCAL_ACTOR_ID": actor_id,
            "MILAI_API_TOKEN": tokens["legacy"],
            "MILAI_CAUSAL_TOKEN_SECRET": tokens["causal"],
            "MILAI_AGENT_READER_TOKEN": tokens["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": tokens["submitter"],
            "MILAI_AGENT_REVIEWER_TOKEN": tokens["reviewer"],
            "MILAI_AGENT_OPERATOR_TOKEN": tokens["operator"],
            "MILAI_DATA_MODE": "SYNTHETIC_ONLY",
            "MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED": "true",
            "MILAI_BLOB_ENCRYPTION": "PLAINTEXT",
            "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
            "MILAI_EMBEDDING_MODEL_ID": "deterministic-hash-v1",
            "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "16",
            "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "16",
            "MILAI_EMBEDDING_PREWARM": "false",
            "MILAI_DATABASE_POOL_MIN_SIZE": "1",
            "MILAI_DATABASE_POOL_MAX_SIZE": "2",
            "MILAI_BIND_HOST": "127.0.0.1",
            "MILAI_BIND_PORT": str(port),
            "MILAI_LOG_LEVEL": "ERROR",
            "MILAI_LOG_FORMAT": "json",
        }
    )
    return environment


def _worker_environment(
    urls: Mapping[str, str],
    *,
    tenant_id: str,
    actor_id: str,
    blob_root: Path,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("MILAI_")
    }
    environment.update(
        {
            "MILAI_ENVIRONMENT": "test",
            "MILAI_WORKER_DATABASE_URL": urls["worker"],
            "MILAI_BLOB_ROOT": str(blob_root),
            "MILAI_TENANT_ID": tenant_id,
            "MILAI_LOCAL_ACTOR_ID": actor_id,
            "MILAI_DATA_MODE": "SYNTHETIC_ONLY",
            "MILAI_BLOB_ENCRYPTION": "PLAINTEXT",
            "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
            "MILAI_EMBEDDING_MODEL_ID": "deterministic-hash-v1",
            "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "16",
            "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "16",
            "MILAI_EMBEDDING_PREWARM": "false",
            "MILAI_DATABASE_POOL_MIN_SIZE": "1",
            "MILAI_DATABASE_POOL_MAX_SIZE": "2",
            "MILAI_WORKER_POLL_INTERVAL_SECONDS": "0.1",
            "MILAI_WORKER_RETRY_DELAY_SECONDS": "0",
            "MILAI_LOG_LEVEL": "ERROR",
            "MILAI_LOG_FORMAT": "json",
        }
    )
    return environment


def _mcp_environment(
    tokens: Mapping[str, str],
    *,
    runtime_port: int,
    registry_path: Path,
    project_id: str = "mcp-baseline",
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("MILAI_")
    }
    environment.update(
        {
            "MILAI_BASE_URL": f"http://127.0.0.1:{runtime_port}",
            "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project_id]}),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_CODEX_TOKEN": tokens["mcp_master"],
            "MILAI_CODEX_PRINCIPAL_ID": "mcp-baseline-host",
            "MILAI_CODEX_TASK_REF": "mcp-baseline-task",
            "MILAI_CODEX_SESSION_REF": "mcp-baseline-session",
            "MILAI_CODEX_USER_REGISTRY": str(registry_path),
            "MILAI_AGENT_READER_TOKEN": tokens["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": tokens["submitter"],
            "MILAI_AGENT_REVIEWER_TOKEN": tokens["reviewer"],
            "MILAI_AGENT_OPERATOR_TOKEN": tokens["operator"],
            "MILAI_CODEX_DATA_CLASSIFICATION": "SYNTHETIC",
            "MILAI_LOG_LEVEL": "ERROR",
        }
    )
    return environment


def _start_process(
    executable: Path,
    *,
    arguments: list[str],
    cwd: Path,
    environment: Mapping[str, str],
    output_fd: int = subprocess.DEVNULL,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - exact installed product executable
        [str(executable), *arguments],
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=output_fd,
        stderr=output_fd,
    )


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_ready(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"{Path(process.args[0]).name} exited before readiness")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                payload = json.load(response)
            if response.status == 200 and payload.get("status") in {"ready", "ok"}:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"service did not become ready: {urlsplit(url).path}")


async def _client(url: str, token: str) -> Any:
    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    return Client(
        streamable_http_client(url, http_client=http_client),
        mode="2026-07-28",
    ), http_client


def _tool_payload(result: Any) -> dict[str, Any]:
    assert result.is_error is False, result.content[0].text
    assert isinstance(result.structured_content, dict)
    return result.structured_content


async def _phase_one(url: str, token_a: str, token_b: str, marker: str) -> dict[str, str]:
    client_context, http_client = await _client(url, token_a)
    async with http_client, client_context as client:
        catalog = await client.list_tools()
        assert len(catalog.tools) == 13
        assert _tool_payload(await client.call_tool("milai_working_state_get", {}))[
            "status"
        ] == "ABSENT"
        state_v1 = _tool_payload(
            await client.call_tool(
                "milai_working_state_update",
                {
                    "operation_id": "state-v1",
                    "expected_version": 0,
                    "payload": {"active_goal": "prove the real MCP baseline"},
                },
            )
        )
        state_v2 = _tool_payload(
            await client.call_tool(
                "milai_working_state_update",
                {
                    "operation_id": "state-v2",
                    "state_id": state_v1["state_id"],
                    "expected_version": state_v1["version"],
                    "payload": {
                        "active_goal": "prove the real MCP baseline",
                        "next_actions": ["restart and resolve Evidence"],
                    },
                },
            )
        )
        assert state_v2["version"] == 2
        stale = await client.call_tool(
            "milai_working_state_update",
            {
                "operation_id": "state-stale",
                "state_id": state_v1["state_id"],
                "expected_version": 1,
                "payload": {"active_goal": "must not overwrite v2"},
            },
        )
        assert stale.is_error is True
        capture_arguments = {
            "operation_id": "shared-capture-operation",
            "source_type": "AGENT_TURN",
            "source_ref": f"mcp-baseline/{marker}/turn-1",
            "subject_id": f"mcp-baseline-{marker}",
            "observed_at": datetime.now(UTC).isoformat(),
            "content": f"MCP baseline {marker} uses port 6432.",
            "confirmation": "CAPTURE",
        }
        evidence = _tool_payload(
            await client.call_tool("milai_evidence_capture", capture_arguments)
        )
        replay = _tool_payload(
            await client.call_tool("milai_evidence_capture", capture_arguments)
        )
        assert replay["evidence_id"] == evidence["evidence_id"]
        assert replay["replayed"] is True
        conflict = await client.call_tool(
            "milai_evidence_capture",
            {**capture_arguments, "content": "conflicting retry payload"},
        )
        assert conflict.is_error is True

    other_context, other_http = await _client(url, token_b)
    async with other_http, other_context as other:
        assert _tool_payload(await other.call_tool("milai_working_state_get", {}))[
            "status"
        ] == "ABSENT"
        independent = _tool_payload(
            await other.call_tool(
                "milai_evidence_capture",
                {
                    **capture_arguments,
                    "source_ref": f"mcp-baseline/{marker}/other-user",
                    "content": f"Independent collaborating principal {marker}.",
                },
            )
        )
        assert independent["evidence_id"] != evidence["evidence_id"]

    return {
        "state_id": str(state_v2["state_id"]),
        "evidence_id": str(evidence["evidence_id"]),
    }


async def _resolve_until(
    client: Any,
    query: str,
    *,
    evidence_id: str | None,
    expected: bool,
) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _tool_payload(await client.call_tool("milai_memory_resolve", {"query": query}))
        ids = {
            item_id
            for item in last.get("evidence", [])
            for item_id in item.get("evidence_ids", [])
        }
        visible = bool(last.get("evidence")) if evidence_id is None else evidence_id in ids
        if visible is expected:
            return last
        await asyncio.sleep(0.2)
    raise AssertionError(
        f"resolve visibility did not become {expected}; status={last.get('retrieval_status')}"
    )


async def _cross_project_proposal_is_rejected(
    primary_url: str,
    other_project_url: str,
    token: str,
    marker: str,
) -> None:
    other_context, other_http = await _client(other_project_url, token)
    async with other_http, other_context as other:
        evidence = _tool_payload(
            await other.call_tool(
                "milai_evidence_capture",
                {
                    "operation_id": "capture-cross-project-evidence",
                    "source_type": "AGENT_TURN",
                    "source_ref": f"mcp-other/{marker}/turn-1",
                    "subject_id": f"mcp-other-{marker}",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "content": f"Cross-project evidence {marker} must not ground another project.",
                    "confirmation": "CAPTURE",
                },
            )
        )

    primary_context, primary_http = await _client(primary_url, token)
    async with primary_http, primary_context as primary:
        rejected = await primary.call_tool(
            "milai_proposal_create",
            {
                "operation_id": "reject-cross-project-grounding",
                "proposal": {
                    "operation": "CREATE",
                    "supporting_evidence_refs": [evidence["evidence_id"]],
                    "proposed_patch": {
                        "subject_id": f"mcp-baseline-{marker}",
                        "predicate": "cross_project.must_be_rejected",
                        "claim_type": "FACT",
                        "payload": {"value": True},
                        "confidence": 0.99,
                    },
                },
                "confirmation": "SUBMIT",
            },
        )
        assert rejected.is_error is True
        proposals = _tool_payload(await primary.call_tool("milai_proposals_list", {}))
        assert proposals["proposals"] == []


async def _exercise_streamable_http_continuation(
    client: Any,
    other_principal: Any,
    marker: str,
) -> None:
    query_marker = f"continuation-{marker}"
    for ordinal in range(55):
        _tool_payload(
            await client.call_tool(
                "milai_evidence_capture",
                {
                    "operation_id": f"continuation-capture-{ordinal}",
                    "source_type": "AGENT_TURN",
                    "source_ref": f"mcp-continuation/{marker}/turn-{ordinal}",
                    "subject_id": f"mcp-continuation-{marker}",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "content": (
                        f"MCP {query_marker} avalanche collection item {ordinal}; "
                        "preserve each independent Evidence identity."
                    ),
                    "confirmation": "CAPTURE",
                },
            )
        )

    first: dict[str, Any] = {}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        first = _tool_payload(
            await client.call_tool(
                "milai_memory_resolve",
                {"query": f"Recall {query_marker} avalanche collection"},
            )
        )
        continuation = first.get("continuation")
        if isinstance(continuation, dict) and continuation.get("available") is True:
            break
        await asyncio.sleep(0.2)
    else:
        raise AssertionError("MCP continuation frontier did not become available")

    first_ids = {
        evidence_id
        for item in first["evidence"]
        for evidence_id in item.get("evidence_ids", [])
    }
    assert first_ids
    assert isinstance(first.get("context_id"), str)
    denied = await other_principal.call_tool(
        "milai_memory_resolve",
        {
            "query": f"Recall {query_marker} avalanche collection",
            "previous_context_id": first["context_id"],
        },
    )
    assert denied.is_error is True
    denied_problem = json.loads(denied.content[0].text.split(": ", 1)[1])
    assert denied_problem["reason"] == "RETRIEVAL_CONTINUATION_UNAVAILABLE"

    second = _tool_payload(
        await client.call_tool(
            "milai_memory_resolve",
            {
                "query": f"Recall {query_marker} avalanche collection",
                "previous_context_id": first["context_id"],
            },
        )
    )
    second_ids = {
        evidence_id
        for item in second["evidence"]
        for evidence_id in item.get("evidence_ids", [])
    }
    assert second_ids
    assert first_ids.isdisjoint(second_ids)


async def _concurrent_working_state(client: Any, other: Any, marker: str) -> None:
    receipts = await asyncio.gather(*[
        current.call_tool("milai_working_state_update", {
            "scope": "SESSION", "operation_id": "parallel-identical-public-id",
            "expected_version": 0, "payload": {"principal_canary": name},
        }) for current, name in ((client, "a"), (other, "b"))
    ])
    states = [_tool_payload(value) for value in receipts]
    assert states[0]["state_id"] != states[1]["state_id"]
    reads = await asyncio.gather(*[
        current.call_tool("milai_working_state_get", {"scope": "SESSION"})
        for current in (client, other)
    ])
    assert [_tool_payload(value)["payload"]["principal_canary"] for value in reads] == ["a", "b"]

    requests = [
        {"scope": "SESSION", "state_id": states[0]["state_id"], "expected_version": 1,
         "operation_id": f"parallel-cas-{i}", "payload": {"winner": i}}
        for i in range(2)
    ]
    gate = asyncio.Event()

    async def compete(request: dict[str, Any]) -> Any:
        await gate.wait()
        return await client.call_tool("milai_working_state_update", request)

    tasks = [asyncio.create_task(compete(request)) for request in requests]
    gate.set()
    results = await asyncio.gather(*tasks)
    assert sum(not result.is_error for result in results) == 1
    winner_index = next(i for i, result in enumerate(results) if not result.is_error)
    winner = _tool_payload(results[winner_index])
    assert winner["version"] == 2
    assert "STALE_WORKING_STATE" in results[1 - winner_index].content[0].text
    replay = _tool_payload(await client.call_tool(
        "milai_working_state_update", requests[winner_index]
    ))
    assert replay["replayed"] and replay["state_version_id"] == winner["state_version_id"]

    evidence = _tool_payload(await client.call_tool("milai_evidence_capture", {
        "operation_id": "state-disclosure-source", "source_type": "AGENT_TURN",
        "source_ref": f"mcp-state/{marker}", "subject_id": "state-concurrency",
        "observed_at": datetime.now(UTC).isoformat(), "content": "working state disclosure canary",
        "confirmation": "CAPTURE",
    }))
    invalid = await client.call_tool("milai_working_state_update", {
        "scope": "SESSION", "state_id": winner["state_id"], "expected_version": 2,
        "operation_id": "state-invalid-source-session",
        "payload": {"evidence_refs": [evidence["evidence_id"]]},
    })
    assert invalid.is_error and "EVIDENCE_REFERENCE_INVALID" in invalid.content[0].text
    evidence = _tool_payload(await client.call_tool("milai_evidence_capture", {
        "operation_id": "state-disclosure-qualified-source", "source_type": "AGENT_TURN",
        "source_ref": f"mcp-state/{marker}/qualified", "subject_id": "state-concurrency",
        "observed_at": datetime.now(UTC).isoformat(), "content": "working state disclosure canary",
        "source_context": {
            "session_id": "mcp-baseline-session", "turn_id": "state-source", "turn_ordinal": 0,
            "round_id": "state-round", "round_ordinal": 0,
        },
        "confirmation": "CAPTURE",
    }))
    referenced_request = {
        "scope": "SESSION", "state_id": winner["state_id"], "expected_version": 2,
        "operation_id": "state-reference", "payload": {
            "note": "derived disclosure canary", "evidence_refs": [evidence["evidence_id"]],
        },
    }
    referenced = _tool_payload(await client.call_tool(
        "milai_working_state_update", referenced_request
    ))
    _tool_payload(await client.call_tool("milai_evidence_revoke", {
        "operation_id": "state-reference-revoke", "evidence_id": evidence["evidence_id"],
        "reason_code": "USER_REQUEST", "confirmation": "REVOKE",
    }))
    revoked, replayed, independent = await asyncio.gather(
        client.call_tool("milai_working_state_get", {"scope": "SESSION"}),
        client.call_tool("milai_working_state_update", referenced_request),
        other.call_tool("milai_working_state_get", {"scope": "SESSION"}),
    )
    for result in (revoked, replayed):
        value = _tool_payload(result)
        assert value["payload"] == {} and value["payload_withheld"]
        assert value["state_version_id"] == referenced["state_version_id"]
    assert _tool_payload(independent)["payload"] == {"principal_canary": "b"}


async def _phase_two(
    url: str,
    token: str,
    other_token: str,
    marker: str,
    phase_one: Mapping[str, str],
) -> None:
    client_context, http_client = await _client(url, token)
    other_context, other_http = await _client(url, other_token)
    async with http_client, client_context as client, other_http, other_context as other:
        resumed = _tool_payload(await client.call_tool("milai_working_state_get", {}))
        assert resumed["status"] == "ACTIVE"
        assert resumed["version"] == 2
        assert resumed["state_id"] == phase_one["state_id"]

        await _concurrent_working_state(client, other, marker)

        await _exercise_streamable_http_continuation(client, other, marker)

        await _resolve_until(
            client,
            marker,
            evidence_id=phase_one["evidence_id"],
            expected=True,
        )
        create = _tool_payload(
            await client.call_tool(
                "milai_proposal_create",
                {
                    "operation_id": "proposal-create-v1",
                    "proposal": {
                        "operation": "CREATE",
                        "supporting_evidence_refs": [phase_one["evidence_id"]],
                        "proposed_patch": {
                            "subject_id": f"mcp-baseline-{marker}",
                            "predicate": "runtime.port",
                            "claim_type": "FACT",
                            "payload": {"port": 6432, "marker": marker},
                            "confidence": 0.99,
                        },
                    },
                    "confirmation": "SUBMIT",
                },
            )
        )
        proposal = _tool_payload(
            await client.call_tool(
                "milai_proposal_get", {"proposal_id": create["proposal_id"]}
            )
        )
        assert proposal["status"] in {"PENDING", "PENDING_REVIEW"}
        reviewed_v1 = _tool_payload(
            await client.call_tool(
                "milai_memory_review",
                {
                    "proposal_id": create["proposal_id"],
                    "operation_id": "review-create-v1",
                    "decision": "APPROVE",
                    "policy_version": "mcp-baseline-v1",
                    "reason_code": "SYNTHETIC_BASELINE_VERIFIED",
                    "confirmation": "APPROVE",
                },
            )
        )
        claim_v1 = _tool_payload(
            await client.call_tool(
                "milai_memory_get", {"claim_id": reviewed_v1["claim_id"]}
            )
        )
        assert claim_v1["items"][0]["payload"]["port"] == 6432

        evidence_v2 = _tool_payload(
            await client.call_tool(
                "milai_evidence_capture",
                {
                    "operation_id": "capture-v2",
                    "source_type": "AGENT_TURN",
                    "source_ref": f"mcp-baseline/{marker}/turn-2",
                    "subject_id": f"mcp-baseline-{marker}",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "content": f"MCP baseline {marker} now uses port 6433.",
                    "confirmation": "CAPTURE",
                },
            )
        )
        supersede = _tool_payload(
            await client.call_tool(
                "milai_proposal_create",
                {
                    "operation_id": "proposal-supersede-v2",
                    "proposal": {
                        "operation": "SUPERSEDE",
                        "target_claim_id": reviewed_v1["claim_id"],
                        "expected_version_id": reviewed_v1["claim_version_id"],
                        "supporting_evidence_refs": [evidence_v2["evidence_id"]],
                        "proposed_patch": {
                            "payload": {"port": 6433, "marker": marker},
                            "confidence": 0.99,
                        },
                    },
                    "confirmation": "SUBMIT",
                },
            )
        )
        reviewed_v2 = _tool_payload(
            await client.call_tool(
                "milai_memory_review",
                {
                    "proposal_id": supersede["proposal_id"],
                    "operation_id": "review-supersede-v2",
                    "decision": "APPROVE",
                    "policy_version": "mcp-baseline-v1",
                    "reason_code": "SYNTHETIC_BASELINE_VERIFIED",
                    "confirmation": "APPROVE",
                },
            )
        )
        assert reviewed_v2["claim_version_id"] != reviewed_v1["claim_version_id"]
        claim_v2 = _tool_payload(
            await client.call_tool(
                "milai_memory_get", {"claim_id": reviewed_v1["claim_id"]}
            )
        )
        assert claim_v2["items"][0]["payload"]["port"] == 6433

        await _resolve_until(
            client,
            f"{marker} 6433",
            evidence_id=str(evidence_v2["evidence_id"]),
            expected=True,
        )
        revoked = _tool_payload(
            await client.call_tool(
                "milai_evidence_revoke",
                {
                    "evidence_id": evidence_v2["evidence_id"],
                    "operation_id": "revoke-v2",
                    "reason_code": "USER_REQUEST",
                    "confirmation": "REVOKE",
                },
            )
        )
        assert revoked["logical_revocation_status"] == "APPLIED"
        await _resolve_until(
            client,
            f"{marker} 6433",
            evidence_id=str(evidence_v2["evidence_id"]),
            expected=False,
        )
        deletion = _tool_payload(
            await client.call_tool(
                "milai_deletion_status_get",
                {"evidence_id": evidence_v2["evidence_id"]},
            )
        )
        assert deletion["logical_revocation_status"] == "APPLIED"


def test_codex_full_real_postgres_mcp_lifecycle(tmp_path: Path) -> None:
    owner_source = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    database = _DATABASE_PREFIX + secrets.token_hex(10)
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in (
            "legacy",
            "causal",
            "reader",
            "submitter",
            "reviewer",
            "operator",
            "mcp_master",
        )
    }
    registry = RemoteUserRegistry(tmp_path / "remote-users.json")
    token_a = registry.issue("mcp-baseline-user-a")
    token_b = registry.issue("mcp-baseline-user-b")
    tenant_id = secrets.token_hex(16)
    actor_id = secrets.token_hex(16)
    marker = secrets.token_hex(8)
    runtime_port = _free_port()
    mcp_port = _free_port()
    other_mcp_port = _free_port()
    urls: dict[str, str] | None = None
    api_process: subprocess.Popen[bytes] | None = None
    worker_process: subprocess.Popen[bytes] | None = None
    mcp_process: subprocess.Popen[bytes] | None = None
    other_mcp_process: subprocess.Popen[bytes] | None = None
    try:
        urls = _create_and_migrate_database(owner_source, database)
        api_environment = _runtime_environment(
            urls,
            tokens,
            tenant_id=tenant_id,
            actor_id=actor_id,
            blob_root=tmp_path / "blobs",
            port=runtime_port,
        )
        worker_environment = _worker_environment(
            urls,
            tenant_id=tenant_id,
            actor_id=actor_id,
            blob_root=tmp_path / "blobs",
        )
        api_process = _start_process(
            _RUNTIME_ROOT / ".venv/bin/milai-api",
            arguments=[],
            cwd=_RUNTIME_ROOT,
            environment=api_environment,
        )
        _wait_ready(f"http://127.0.0.1:{runtime_port}/health/ready", api_process)
        worker_process = _start_process(
            _RUNTIME_ROOT / ".venv/bin/milai-worker",
            arguments=[],
            cwd=_RUNTIME_ROOT,
            environment=worker_environment,
        )
        mcp_environment = _mcp_environment(
            tokens,
            runtime_port=runtime_port,
            registry_path=registry.path,
        )
        other_mcp_environment = _mcp_environment(
            tokens,
            runtime_port=runtime_port,
            registry_path=registry.path,
            project_id="mcp-other",
        )

        def start_mcp(
            port: int, environment: Mapping[str, str]
        ) -> subprocess.Popen[bytes]:
            process = _start_process(
                Path(__file__).resolve().parents[1] / ".venv/bin/milai-codex-full-mcp",
                arguments=["--host", "127.0.0.1", "--port", str(port)],
                cwd=Path(__file__).resolve().parents[1],
                environment=environment,
            )
            _wait_ready(f"http://127.0.0.1:{port}/readyz", process)
            return process

        mcp_process = start_mcp(mcp_port, mcp_environment)
        other_mcp_process = start_mcp(other_mcp_port, other_mcp_environment)
        phase_one = asyncio.run(
            _phase_one(
                f"http://127.0.0.1:{mcp_port}/mcp",
                token_a,
                token_b,
                marker,
            )
        )
        asyncio.run(
            _cross_project_proposal_is_rejected(
                f"http://127.0.0.1:{mcp_port}/mcp",
                f"http://127.0.0.1:{other_mcp_port}/mcp",
                token_a,
                marker,
            )
        )
        _stop_process(other_mcp_process)
        other_mcp_process = None
        _stop_process(mcp_process)
        mcp_process = start_mcp(mcp_port, mcp_environment)
        asyncio.run(
            _phase_two(
                f"http://127.0.0.1:{mcp_port}/mcp",
                token_a,
                token_b,
                marker,
                phase_one,
            )
        )
    finally:
        _stop_process(other_mcp_process)
        _stop_process(mcp_process)
        _stop_process(worker_process)
        _stop_process(api_process)
        if urls is not None:
            _drop_database(owner_source, database)
