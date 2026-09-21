from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import httpx2 as httpx
import pytest
import uvicorn
from starlette.testclient import TestClient

from milai_mcp.auth_policy import READ_SCOPES, TOOL_SCOPES, authentication_mode
from milai_mcp.http_transport import HttpResourceBinding
from milai_mcp.server import (
    CodexFullRuntimeClients,
    _request_access_token,
    _RequestAccessTokenMiddleware,
    build_server,
)
from support.auth import ISSUER, RESOURCE, Fixture
from support.postgres import _free_port
from support.profile import _RoleClient


@contextmanager
def edge(
    fixture: Fixture, *, stateless: bool = True, scopes: frozenset[str] = READ_SCOPES,
    working_state_client_factory: Any = None,
    role_clients: list[Any] | None = None,
    data_classification: Any = "SYNTHETIC",
    catalog: Any = "legacy",
    network: bool = False,
) -> Iterator[tuple[Any, ...]]:
    roles = role_clients or [
        _RoleClient(role) for role in ["reader", "submitter", "reviewer", "operator"]
    ]
    binding = HttpResourceBinding.create(
        issuer_url=ISSUER,
        resource_url=RESOURCE,
        scope={"project_ids": ["project-one"]},
        scopes=tuple(sorted(scopes)),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fixture.response))
    verifier = fixture.verifier(client)
    verifier.policy.enabled_scopes = scopes
    verifier.scope_digest = binding.scope_digest
    server = build_server(
        "codex-full",
        cast(Any, roles[0]),
        default_scope={"project_ids": ["project-one"]},
        http_principal_binding=binding,
        http_token_verifier=verifier,
        codex_full_clients=CodexFullRuntimeClients(*cast(Any, roles)),
        codex_full_data_classification=data_classification,
        codex_working_state_scope_refs={"TASK": "auth-test-task"},
        max_retries=0,
        working_state_client_factory=working_state_client_factory,
        catalog=catalog,
    )
    try:
        app = server.streamable_http_app(json_response=True, stateless_http=stateless)
        if network:
            port = _free_port()
            runner = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="error", access_log=False,
            ))
            thread = threading.Thread(target=runner.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not runner.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert runner.started, "local MCP HTTP server failed to start"
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}",
                    headers={"Host": httpx.URL(RESOURCE).netloc.decode()}, timeout=15,
                ) as http:
                    yield http, server, roles
            finally:
                runner.should_exit = True
                thread.join(timeout=10)
                assert not thread.is_alive(), "local MCP HTTP server did not stop"
        else:
            with TestClient(app, base_url=RESOURCE.removesuffix("/mcp")) as http:
                yield http, server, roles
    finally:
        asyncio.run(client.aclose())


def rpc(
    http: TestClient,
    method: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    params = dict(params or {})
    if (headers or {}).get("MCP-Protocol-Version") == "2026-07-28":
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    return http.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
            "MCP-Method": method,
            **({"Authorization": f"Bearer {token}"} if token else {}),
            **(headers or {}),
        },
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )


def test_public_metadata_no_local_as_and_unauthenticated_challenge(tmp_path: Any) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    with edge(fixture) as (http, _server, roles):
        metadata = http.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        body = metadata.json()
        assert body["resource"] == RESOURCE
        assert body["authorization_servers"] == [ISSUER]
        assert set(body["scopes_supported"]) == READ_SCOPES
        for path in [
            "/.well-known/oauth-authorization-server",
            "/register",
            "/authorize",
            "/token",
            "/revoke",
            "/oauth/consent",
        ]:
            assert http.get(path).status_code == 404
        for headers in [{}, {"Cookie": "owner=true"}, {"x-agent-id": "owner"}]:
            response = rpc(http, "tools/list", headers=headers)
            assert response.status_code == 401
            assert (
                RESOURCE.removesuffix("/mcp") + "/.well-known/oauth-protected-resource/mcp"
                in response.headers["www-authenticate"]
            )
        assert not fixture.requests
        assert not any(role.calls for role in roles)



def test_tool_directory_and_direct_denial_precede_runtime(tmp_path: Any) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    with edge(fixture) as (http, _server, roles):
        token = fixture.token(scope="milai.state.read")
        response = rpc(http, "tools/list", token=token)
        assert response.status_code == 200, response.text
        assert [t["name"] for t in response.json()["result"]["tools"]] == [
            "milai_working_state_get"
        ]
        read = rpc(
            http,
            "tools/call",
            token=token,
            params={
                "name": "milai_working_state_get",
                "arguments": {"scope": "TASK"},
            },
        )
        assert read.status_code == 200, read.text
        assert not read.json()["result"].get("isError"), read.text
        assert len(roles[1].calls) == 1
        before = [len(role.calls) for role in roles]
        for name in TOOL_SCOPES:
            if name == "milai_working_state_get":
                continue
            denied = rpc(
                http,
                "tools/call",
                token=token,
                params={
                    "name": name,
                    "arguments": {},
                },
            )
            assert denied.status_code == 200
            assert "error" in denied.json() or denied.json()["result"]["isError"]
        assert [len(role.calls) for role in roles] == before
        # The SDK's HTTP success status does not imply handler execution.
        valid_write = rpc(
            http,
            "tools/call",
            token=token,
            params={
                "name": "milai_working_state_update",
                "arguments": {
                    "scope": "TASK",
                    "operation_id": "must-not-write",
                    "expected_version": 0,
                    "payload": {"value": 1},
                },
            },
        )
        assert valid_write.json()["result"]["isError"]
        assert [len(role.calls) for role in roles] == before


@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
def test_existing_session_cannot_outlive_admission(tmp_path: Any, protocol: str) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    with edge(fixture, stateless=False) as (http, _server, roles):
        token = fixture.token()
        response = rpc(
            http,
            "initialize" if protocol == "2025-11-25" else "tools/list",
            token=token,
            headers={"MCP-Protocol-Version": protocol},
            params={
                "protocolVersion": protocol,
                "capabilities": {},
                "clientInfo": {"name": "aigcit-test", "version": "1"},
            },
        )
        assert response.status_code == 200, response.text
        headers = {"MCP-Protocol-Version": protocol}
        if response.headers.get("mcp-session-id"):
            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        listed = rpc(http, "tools/list", token=token, headers=headers)
        assert listed.status_code == 200, listed.text
        fixture.doc["owners"][0]["enabled"] = False
        fixture.write()
        denied = rpc(http, "tools/list", token=token, headers=headers)
        assert denied.status_code == 403, denied.text
        assert rpc(http, "tools/list", headers=headers).status_code == 401
        fixture.path.write_text("invalid")
        assert rpc(http, "tools/list", token=token, headers=headers).status_code == 503
        assert not any(role.calls for role in roles)


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Host": "attacker.test", "X-Forwarded-Host": "memory.example.test:7960"}, 421),
        ({"Host": "memory.example.test:7968"}, 421),
        ({"Origin": "https://memory.example.test"}, 403),
        ({"Origin": "https://memory.example.test:7960"}, 200),
    ],
)
def test_external_mode_preserves_exact_host_origin(
    tmp_path: Any, headers: Any, expected: int
) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    with edge(fixture) as (http, _server, _roles):
        response = rpc(http, "tools/list", token=fixture.token(), headers=headers)
        assert response.status_code == expected, response.text


def test_missing_handler_identity_and_unmapped_catalog_fail_closed(tmp_path: Any) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    with edge(fixture) as (_http, server, roles):
        result = asyncio.run(server.call_tool("milai_working_state_get", {"scope": "TASK"}))
        assert result.is_error
        assert _request_access_token.get() is None
        assert not any(role.calls for role in roles)
        with pytest.raises(ValueError, match="mapping"):
            fixture.policy().validate_tools(set(TOOL_SCOPES) | {"new_tool"})


@pytest.mark.parametrize(
    "environment",
    [
        {"MILAI_MCP_AUTH_MODE": "typo"},
        {"MILAI_AIGCIT_ISSUER": ISSUER},
        {"MILAI_MCP_AUTH_MODE": "legacy", "MILAI_OAUTH_DB": "old.sqlite"},
        {"MILAI_MCP_AUTH_MODE": "local-oauth"},
        *[
            {"MILAI_MCP_AUTH_MODE": "aigcit", key: "configured"}
            for key in [
                "MILAI_OAUTH_DB",
                "MILAI_CODEX_TOKEN",
                "MILAI_CODEX_USER_REGISTRY",
                "MILAI_MCP_HTTP_BEARER_TOKEN",
                "MILAI_CODEX_PRINCIPAL_ID",
            ]
        ],
    ],
)
def test_mode_conflicts(environment: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        authentication_mode(environment)


def test_implicit_legacy_modes_remain_compatible() -> None:
    assert authentication_mode({}) == "legacy"
    assert authentication_mode({"MILAI_OAUTH_DB": "old.sqlite"}) == "local-oauth"
    assert authentication_mode({"MILAI_MCP_AUTH_MODE": "aigcit"}) == "aigcit"


def test_request_identity_reset_across_threads_failure_and_cancel() -> None:
    from types import SimpleNamespace

    from mcp.server.auth.provider import AccessToken

    async def run() -> None:
        middleware = _RequestAccessTokenMiddleware()
        entered = asyncio.Event()

        async def one(subject: str, fail: bool = False, wait: bool = False) -> None:
            token = AccessToken(  # synthetic context, never an accepted wire credential
                token=subject,
                client_id="fixture",
                subject=subject,
                scopes=[],
            )
            context = SimpleNamespace(
                request=SimpleNamespace(
                    scope={
                        "user": SimpleNamespace(access_token=token),
                    }
                )
            )

            async def handler(_ctx: Any) -> Any:
                observed = await asyncio.to_thread(_request_access_token.get)
                assert observed and observed.subject == subject
                if wait:
                    entered.set()
                    await asyncio.Event().wait()
                await asyncio.sleep(0)
                assert _request_access_token.get() is token
                if fail:
                    raise ValueError("fixture error")
                return None

            try:
                await middleware(cast(Any, context), handler)
            finally:
                assert _request_access_token.get() is None

        outcomes = await asyncio.gather(one("one"), one("two", fail=True), return_exceptions=True)
        assert outcomes[0] is None and isinstance(outcomes[1], ValueError)
        cancelled = asyncio.create_task(one("cancelled", wait=True))
        await entered.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        await one("after-cancellation")
        assert _request_access_token.get() is None

    asyncio.run(run())


def test_aigcit_cli_assembles_external_mode_without_static_credential(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    from types import SimpleNamespace

    from milai_mcp import server as module
    from milai_mcp.aigcit_auth import AigcitTokenVerifier

    fixture = Fixture(tmp_path / "bindings.json")
    for key in list(os.environ):
        if key.startswith("MILAI_"):
            monkeypatch.delenv(key)
    for key, value in {
        "MILAI_MCP_AUTH_MODE": "aigcit",
        "MILAI_AIGCIT_ISSUER": ISSUER,
        "MILAI_MCP_HTTP_PUBLIC_BASE_URL": RESOURCE.removesuffix("/mcp"),
        "MILAI_AIGCIT_BINDINGS_FILE": str(fixture.path),
        "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["project-one"]}',
    }.items():
        monkeypatch.setenv(key, value)
    for role in ["READER", "SUBMITTER", "REVIEWER", "OPERATOR"]:
        monkeypatch.setenv(f"MILAI_AGENT_{role}_TOKEN", "runtime-test-credential-" + role * 10)
    # Bind the policy-file owner to the test process while also fixing the historical
    # ``milai_mcp.server.AdmissionPolicy`` monkeypatch observation point.
    original = module.AdmissionPolicy
    monkeypatch.setattr(
        module,
        "AdmissionPolicy",
        lambda *a, **kw: original(
            *a,
            **kw,
            trusted_owner_uid=os.getuid(),
        ),
    )
    captured: dict[str, Any] = {}
    role = object()
    monkeypatch.setattr(
        module, "_codex_full_clients_from_environment", lambda **kw: SimpleNamespace(reader=role)
    )

    def build(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(run=lambda **kw: captured.update(run=kw))

    monkeypatch.setattr(module, "build_server", build)
    module.main(["--transport", "streamable-http", "--profile", "codex-full"])
    assert isinstance(captured["http_principal_binding"], HttpResourceBinding)
    assert isinstance(captured["http_token_verifier"], AigcitTokenVerifier)
    assert captured["http_oauth_provider"] is None
    assert set(captured["http_principal_binding"].scopes) == READ_SCOPES
    assert captured["run"]["transport"] == "streamable-http"


def test_authorization_audit_omits_token_and_memory(tmp_path: Any, caplog: Any) -> None:
    import json
    import logging

    fixture = Fixture(tmp_path / "bindings.json")
    with edge(fixture) as (http, _server, roles):
        token = fixture.token()
        with caplog.at_level(logging.INFO, logger="milai_mcp.auth"):
            response = rpc(
                http,
                "tools/call",
                token=token,
                params={
                    "name": "milai_working_state_update",
                    "arguments": {
                        "operation_id": "raw-operation-canary",
                        "expected_version": 0,
                        "payload": {"private": "private-memory-canary"},
                    },
                },
            )
        assert response.json()["result"]["isError"]
        records = [r.getMessage() for r in caplog.records if r.name == "milai_mcp.auth"]
        assert len(records) == 1
        record = json.loads(records[0])
        assert record["reason"] == "insufficient_scope" and record["policy_version"] == 1
        assert len(record["runtime_operation_id"]) == 64 and record["request_id"]
        assert token not in records[0]
        assert (
            "private-memory-canary" not in records[0] and "raw-operation-canary" not in records[0]
        )
        assert not any(role.calls for role in roles)

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="milai_mcp.auth"):
            listing = rpc(http, "tools/list", token=token)
        records = [r.getMessage() for r in caplog.records if r.name == "milai_mcp.auth"]
        assert len(records) == 1
        directory = json.loads(records[0])
        assert directory["event"] == "tool_directory_authorization"
        assert directory["granted_scopes"] == sorted(READ_SCOPES)
        assert directory["effective_scopes"] == sorted(READ_SCOPES)
        assert directory["visible_tools"] == sorted(
            tool["name"] for tool in listing.json()["result"]["tools"]
        )
        assert "milai_working_state_update" in directory["filtered_tools"]
        assert token not in records[0] and "private-memory-canary" not in records[0]
        assert "principal" not in directory and "client_id" not in directory
