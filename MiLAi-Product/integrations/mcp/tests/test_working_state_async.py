from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from mcp import Client
from milai_client import AsyncMilaiClient, HttpxAsyncTransport

from milai_mcp.server import CodexFullRuntimeClients, build_server
from test_codex_full_profile import _as_client, _RoleClient

TOKEN = "async-state-test-token-at-least-32-characters"  # noqa: S105
CAPABILITIES = {
    "api_version": "1", "contract_version": "agent.v1", "runtime_version": "0.1.0",
    "profile": "submitter", "capabilities": ["working-state:read", "working-state:write"],
    "routes": ["L0", "L1"], "consistency_modes": ["CANONICAL_REQUIRED"],
    "agent_profiles": ["submitter"], "features": {}, "limits": {},
    "data_mode": "SYNTHETIC_ONLY", "schema_status": "0.1.x EXPERIMENTAL",
    "implementation_status": "CANDIDATE",
}


def make_server(factory, *, timing=False, catalog="legacy"):
    role = _as_client(_RoleClient("submitter"))
    return build_server(
        "codex-full", role, default_scope={"project_ids": ["project-one"]}, max_retries=0,
        codex_full_clients=CodexFullRuntimeClients(role, role, role, role),
        codex_working_state_scope_refs={"TASK": "task-one", "SESSION": "session-one"},
        working_state_client_factory=factory,
        request_timing_enabled=timing,
        catalog=catalog,
    )


def decoded(result) -> dict:
    assert not result.is_error
    return json.loads(result.content[0].text)


def test_embedded_sync_compatibility_call_without_serving_lifespan() -> None:
    server = make_server(None)
    result = asyncio.run(server.call_tool("milai_working_state_get", {"scope": "TASK"}))
    assert decoded(result)["status"] == "ABSENT"


@pytest.mark.parametrize("arguments,field", [
    ({"scope": "PRIVATE_SCOPE"}, "scope"),
    ({"expected_version": "PRIVATE_VERSION"}, "expected_version"),
    ({"payload": "PRIVATE_BODY"}, "payload"),
])
def test_ordinary_state_argument_types_are_sanitized_before_dispatch(arguments, field) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid arguments must not reach Runtime")

    def factory() -> AsyncMilaiClient:
        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle),
        ))

    async def run():
        async with Client(make_server(factory, catalog="ordinary-memory-v1"),
                          mode="2026-07-28") as client:
            return await client.call_tool("milai_working_state_update", {
                "operation_id": "invalid", "expected_version": 0, "payload": {}, **arguments,
            })

    result = asyncio.run(run())
    assert result.is_error
    error = json.loads(result.content[0].text)
    assert error["code"] == "INVALID_ARGUMENT" and error["retryable"] is False
    assert any(item["path"] == field for item in error["fields"])
    assert "PRIVATE" not in result.content[0].text
    if field == "payload":
        expected = next(item["expected"] for item in error["fields"] if item["path"] == field)
        assert "Working State" in expected
        assert "65536" in expected and "1024" in expected


@pytest.mark.parametrize("status", ["ABSENT", "ACTIVE"])
@pytest.mark.parametrize("catalog", ["legacy", "ordinary-memory-v1"])
def test_scope_guidance_matches_concurrent_requests_and_preserves_binding(status, catalog) -> None:
    requests = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=CAPABILITIES)
        body = json.loads(request.content)
        requests.append(body)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"status": status, "payload": {}})

    def factory() -> AsyncMilaiClient:
        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle)
        ))

    async def run() -> None:
        async with Client(make_server(factory, catalog=catalog), mode="2026-07-28") as client:
            scopes = ["SESSION", "PROJECT", "TASK"]
            reads = await asyncio.gather(*[
                client.call_tool("milai_working_state_get", {"scope": scope})
                for scope in scopes
            ])
            for scope, result in zip(scopes, reads, strict=True):
                value = decoded(result)
                assert value["mcp_usage_contract"]["resume"]["arguments"] == {"scope": scope}
                key = "suggested_next_step" if catalog == "ordinary-memory-v1" else "mcp_guidance"
                assert value[key]["next_arguments"] == {"scope": scope}
                if catalog == "ordinary-memory-v1":
                    assert value[key]["requires_user_authorization"] is True
                    assert (value["mcp_usage_contract"]["authority"]
                            == "ADVISORY_ONLY_NOT_AUTHORIZATION")
                if status == "ABSENT":
                    assert f"No {scope} checkpoint" in value[key]["message"]
            writes = await asyncio.gather(*[
                client.call_tool("milai_working_state_update", {
                    "scope": scope, "operation_id": "scope-" + scope,
                    "expected_version": 0, "payload": {},
                }) for scope in scopes
            ])
            for scope, result in zip(scopes, writes, strict=True):
                guidance = decoded(result)[key]
                if catalog == "ordinary-memory-v1":
                    assert guidance["optional"] is True
                    assert guidance["authorization_granted"] is False
                    assert guidance["requires_user_authorization"] is False
                assert guidance["next_arguments"] == {"scope": scope}
                assert f"saved in {scope} scope" in guidance["message"]
            default = decoded(await client.call_tool("milai_working_state_get", {}))
            assert default["mcp_usage_contract"]["resume"]["arguments"] == {"scope": "TASK"}

    asyncio.run(run())
    refs = {"SESSION": "session-one", "PROJECT": "project-one", "TASK": "task-one"}
    assert len(requests) == 7
    assert all(body["scope_ref"] == refs[body["scope_type"]] for body in requests)
    assert all(body["project_id"] == "project-one" for body in requests)
    assert len({body["principal_binding_digest"] for body in requests}) == 1


@pytest.mark.parametrize("scope", ["SESSION", "TASK", "PROJECT"])
@pytest.mark.parametrize("code,status,details,action", [
    ("STALE_WORKING_STATE", 409, {"state_id": "same-state", "current_version": 2},
     "READ_AND_REBASE"),
    ("STALE_WORKING_STATE", 409, {"state_id": "foreign-state", "current_version": 9},
     "READ_AND_REBASE"),
    ("INVALID_REQUEST", 400, {"fields": [{"path": "expected_version", "type": "value_error",
                                        "input": "PRIVATE"}]}, "CORRECT_INPUT"),
    ("OPERATION_CONFLICT", 409, {}, "RECONCILE_ORIGINAL_OPERATION"),
    ("UNAVAILABLE", 503, {}, "RECONCILE_ORIGINAL_OPERATION"),
    ("HOST_WORKING_STATE_SCOPE_DENIED", 403, {"state_id": "same-state", "current_version": 9},
     "INSPECT_REQUEST"),
])
def test_ordinary_state_structured_recovery_is_scoped_and_safe(
    scope, code, status, details, action,
):
    attempts = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=CAPABILITIES)
        attempts.append(request)
        return httpx.Response(status, json={"error": {
            "code": code, "message": "PRIVATE", "retryable": True,
            "details": {**details, "token": "PRIVATE", "payload": "PRIVATE"},
        }})

    def factory() -> AsyncMilaiClient:
        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle)
        ))

    async def run() -> None:
        async with Client(make_server(factory, catalog="ordinary-memory-v1"),
                          mode="2026-07-28") as client:
            result = await client.call_tool("milai_working_state_update", {
                "operation_id": "original-request", "expected_version": 1,
                "state_id": "same-state", "payload": {}, "scope": scope,
            })
        assert result.is_error
        # MCP SDK wraps ToolError text; old text consumers keep the stable JSON code inside it.
        text = result.content[0].text
        error = json.loads(text[text.index("{"):])
        assert error["error_contract"] == "ordinary-memory-errors-v1"
        assert error["scope"] == scope and error["retryable"] is False
        assert error["recovery_action"] == action
        assert "PRIVATE" not in text and "foreign-state" not in text
        if code == "STALE_WORKING_STATE":
            assert error["next_arguments"] == {"scope": scope}
            if details["state_id"] == "same-state":
                assert error["current_version"] == 2
            else:
                assert "current_version" not in error
        else:
            assert "current_version" not in error
        if code == "UNAVAILABLE":
            assert error["code"] == "WORKING_STATE_OUTCOME_UNKNOWN"
            assert "next_tool" not in error

    asyncio.run(run())
    assert len(attempts) == 1


def test_timing_log_links_runtime_without_putting_metrics_or_payload_in_the_other_channel(caplog):
    import hashlib
    import logging

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=CAPABILITIES)
        return httpx.Response(200, json={
            "status": "ACTIVE", "payload": {"note": "PRIVATE_PAYLOAD_CANARY"},
            "request_id": "runtime-correlation-id",
        })

    def factory() -> AsyncMilaiClient:
        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle)
        ))

    async def run():
        async with Client(make_server(factory, timing=True), mode="2026-07-28") as client:
            value = decoded(await client.call_tool("milai_working_state_get", {}))
            assert value["payload"] == {"note": "PRIVATE_PAYLOAD_CANARY"}
            assert "runtime_client_ms" not in value and "handler_ms" not in value
            assert "handler_start_monotonic_s" not in value
            assert "handler_end_monotonic_s" not in value

    caplog.set_level(logging.INFO)
    asyncio.run(run())
    records = [r.getMessage() for r in caplog.records
               if r.getMessage().startswith("MILAI_WORKING_STATE_TIMING ")]
    assert len(records) == 1 and "PRIVATE_PAYLOAD_CANARY" not in records[0]
    assert TOKEN not in records[0] and "runtime-correlation-id" not in records[0]
    value = json.loads(records[0].split(" ", 1)[1])
    assert value["runtime_request_id_fingerprint"] == hashlib.sha256(
        b"runtime-correlation-id"
    ).hexdigest()[:16]
    assert value["handler_ms"] >= value["runtime_client_ms"] >= 0
    assert value["handler_ms"] == pytest.approx(1000 * (
        value["handler_end_monotonic_s"] - value["handler_start_monotonic_s"]
    ), abs=0.001)


def test_async_state_read_write_overlap_schema_and_lifetime() -> None:
    created, closed, requests = [], [], []

    def factory() -> AsyncMilaiClient:
        entered, release = asyncio.Event(), asyncio.Event()
        active = 0
        loop = asyncio.get_running_loop()
        created.append(loop)

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal active
            assert asyncio.get_running_loop() is loop
            assert request.headers["Authorization"] == "Bearer " + TOKEN
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json=CAPABILITIES)
            body = json.loads(request.content)
            requests.append({"body": body, "path": request.url.path})
            active += 1
            if active == 2:
                entered.set()
                release.set()
            try:
                await asyncio.wait_for(release.wait(), 1)
                return httpx.Response(200, json={
                    "status": "ACTIVE", "version": 1,
                    "payload": {"scope_ref": body["scope_ref"]},
                })
            finally:
                active -= 1

        class Transport(HttpxAsyncTransport):
            async def close(self) -> None:
                assert asyncio.get_running_loop() is loop and active == 0
                assert entered.is_set()
                await super().close()
                closed.append(loop)

        return AsyncMilaiClient(
            token=TOKEN, max_retries=0,
            transport=Transport("http://127.0.0.1", 2, transport=httpx.MockTransport(handle)),
        )

    server = make_server(factory)

    async def run() -> None:
        async with Client(server, mode="2026-07-28") as client:
            catalog = await client.list_tools()
            schemas = {tool.name: tool.input_schema for tool in catalog.tools}
            assert set(schemas["milai_working_state_get"]["properties"]) == {"scope"}
            assert "ctx" not in schemas["milai_working_state_update"]["properties"]
            results = await asyncio.wait_for(asyncio.gather(
                client.call_tool("milai_working_state_get", {"scope": "TASK"}),
                client.call_tool("milai_working_state_update", {
                    "scope": "SESSION", "operation_id": "same-op", "expected_version": 0,
                    "payload": {"note": "opaque"},
                }),
            ), 3)
            assert [decoded(r)["payload"]["scope_ref"] for r in results] == [
                "task-one", "session-one",
            ]
            assert (await client.call_tool(
                "milai_working_state_get", {"scope": "TASK", "ctx": "injected"}
            )).is_error

    asyncio.run(run())
    asyncio.run(run())
    assert len(created) == len(closed) == 2 and created == closed and created[0] is not created[1]
    assert len(requests) == 4
    assert all(r["body"]["project_id"] == "project-one" for r in requests)
    assert len({r["body"]["principal_binding_digest"] for r in requests}) == 1


@pytest.mark.parametrize(("status", "code", "message"), [
    (409, "STALE_WORKING_STATE", "rebase on the current version"),
    (409, "OPERATION_CONFLICT", "different request"),
    (503, "UNAVAILABLE", "WORKING_STATE_OUTCOME_UNKNOWN"),
    (503, "DATABASE_CAPACITY_EXCEEDED", "WORKING_STATE_OUTCOME_UNKNOWN"),
])
def test_async_state_errors_keep_recovery_and_single_attempt(status, code, message) -> None:
    attempts: list[Any] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=CAPABILITIES)
        attempts.append(request)
        return httpx.Response(status, json={"error": {
            "code": code, "message": "PRIVATE_DETAIL", "retryable": True,
        }})

    def factory() -> AsyncMilaiClient:
        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle)
        ))

    async def run() -> None:
        async with Client(make_server(factory), mode="2026-07-28") as client:
            result = await client.call_tool("milai_working_state_update", {
                "operation_id": "one-attempt", "expected_version": 0, "payload": {},
            })
            assert result.is_error
            text = json.dumps(result.model_dump(mode="json"))
            assert message in text and "PRIVATE_DETAIL" not in text

    asyncio.run(run())
    assert len(attempts) == 1


def test_cancelled_write_is_unknown_and_does_not_cancel_independent_read(caplog) -> None:
    async def run() -> None:
        both_entered, release_read, write_cancelled = (
            asyncio.Event(), asyncio.Event(), asyncio.Event()
        )
        active = 0

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal active
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json=CAPABILITIES)
            active += 1
            if active == 2:
                both_entered.set()
            try:
                if request.url.path.endswith("update"):
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        write_cancelled.set()
                        raise
                else:
                    await release_read.wait()
                return httpx.Response(200, json={"status": "ABSENT", "payload": {}})
            finally:
                active -= 1

        def factory() -> AsyncMilaiClient:
            return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
                "http://127.0.0.1", 2, transport=httpx.MockTransport(handle)
            ))

        async with Client(make_server(factory), mode="2026-07-28") as client:
            write = asyncio.create_task(client.call_tool("milai_working_state_update", {
                "operation_id": "cancelled-write", "expected_version": 0, "payload": {},
            }))
            read = asyncio.create_task(client.call_tool("milai_working_state_get", {}))
            try:
                await asyncio.wait_for(both_entered.wait(), 2)
                write.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await write
                await asyncio.wait_for(write_cancelled.wait(), 2)
                assert active == 1 and not read.done()
                release_read.set()
                assert decoded(await read)["status"] == "ABSENT"
            finally:
                release_read.set()
                write.cancel()
                read.cancel()
                await asyncio.gather(write, read, return_exceptions=True)
        assert active == 0

    asyncio.run(run())
    assert '"outcome": "UNKNOWN"' in caplog.text
    assert '"error_type": "CancelledError"' in caplog.text
