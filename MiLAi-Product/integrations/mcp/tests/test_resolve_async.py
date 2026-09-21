from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from milai_client import AsyncMilaiClient, HttpxAsyncTransport

from milai_mcp.http_transport import HttpPrincipalBinding
from milai_mcp.server import CodexFullRuntimeClients, build_server
from support.profile import _as_client, _RoleClient
from support.working_state import CAPABILITIES

TOKEN = "async-resolve-reader-token-at-least-32-characters"  # noqa: S105


def make_server(factory, **options):
    role = _as_client(_RoleClient("reader"))
    return build_server(
        "codex-full", role, default_scope={"project_ids": ["project-one"]}, max_retries=0,
        codex_full_clients=CodexFullRuntimeClients(role, role, role, role),
        resolve_client_factory=factory, **options,
    )


def raw(query):
    value = _RoleClient("reader").resolve_memory(query).raw
    value.update(memory_intent="REQUIRED", requirement="SEARCH")
    value["memory_context"]["windows"][0]["text"] = query
    return value


def test_http_resolves_overlap_with_two_verified_principals_and_unchanged_schema():
    async def run():
        binding = HttpPrincipalBinding.create(
            bearer_token="a" * 32, principal_id="default", issuer_url="http://127.0.0.1:8000",
            resource_url="http://127.0.0.1:8000/mcp", scope={"project_ids": ["project-one"]},
            access_profile="codex-full",
        )
        entered, requests, closed = asyncio.Event(), [], []
        active = 0

        class Verifier:
            async def verify_token(self, token):
                if token in {"a" * 32, "b" * 32}:
                    return binding.access_token(token, principal_id="principal-" + token[0])
                return None

        async def handle(request):
            nonlocal active
            assert request.headers["Authorization"] == "Bearer " + TOKEN
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json={**CAPABILITIES, "profile": "reader",
                                                "capabilities": ["memory:read"]})
            body = json.loads(request.content)
            requests.append((body, request.headers["X-MiLA-Host-Principal-Binding-Digest"]))
            active += 1
            if active == 2:
                entered.set()
            try:
                await asyncio.wait_for(entered.wait(), 2)
                return httpx.Response(200, json=raw(body["query"]))
            finally:
                active -= 1

        class Transport(HttpxAsyncTransport):
            async def close(self):
                assert active == 0
                closed.append(True)
                await super().close()

        def factory():
            return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=Transport(
                "http://127.0.0.1", 3, transport=httpx.MockTransport(handle),
            ))

        server = make_server(factory, http_principal_binding=binding,
                             http_token_verifier=Verifier())
        app = server.streamable_http_app()
        async with app.router.lifespan_context(app):
            async def caller(subject):
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app),
                    headers={"Authorization": "Bearer " + subject * 32},
                ) as http:
                    async with Client(streamable_http_client(
                        "http://127.0.0.1:8000/mcp", http_client=http,
                    ), mode="2026-07-28") as client:
                        catalog = await client.list_tools()
                        schema = next(t.input_schema for t in catalog.tools
                                      if t.name == "milai_memory_resolve")
                        assert set(schema["properties"]) == {"query", "previous_context_id"}
                        rejected = await client.call_tool("milai_memory_resolve", {
                            "query": subject, "ctx": "injected", "requested_scope": {},
                        })
                        assert rejected.is_error
                        result = await client.call_tool("milai_memory_resolve", {
                            "query": subject, "previous_context_id": "context-" + subject,
                        })
                        assert not result.is_error
                        assert result.structured_content["evidence"][0]["text"] == subject

            await asyncio.wait_for(asyncio.gather(caller("a"), caller("b")), 5)
        assert closed == [True] and len(requests) == 2
        for body, digest in requests:
            assert body["requested_scope"] == {"project_ids": ["project-one"]}
            assert body["previous_context_id"] == "context-" + body["query"]
            expected = hashlib.sha256(json.dumps({
                "host_principal_id": "principal-" + body["query"],
                "scope_sha256": binding.scope_digest,
                "governance_mode": "SINGLE_HOST_FULL_CONTROL",
            }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            assert digest == expected
        assert requests[0][1] != requests[1][1]

    asyncio.run(run())


@pytest.mark.parametrize("status,code,expected", [
    (403, "CAPABILITY_REQUIRED", "ERROR"),
    (503, "CANONICAL_UNAVAILABLE", "ERROR"),
    (409, "RETRIEVAL_CONTINUATION_UNAVAILABLE", "tool_error"),
])
def test_async_resolve_errors_keep_the_existing_public_outcome(status, code, expected):
    attempts = []

    async def handle(request):
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={**CAPABILITIES, "profile": "reader",
                                            "capabilities": ["memory:read"]})
        attempts.append(request.url.path)
        if status == 503:
            return httpx.Response(status, json={**raw("test"), "status": "UNAVAILABLE",
                                               "availability": "UNAVAILABLE", "items": [],
                                               "memory_context": None})
        return httpx.Response(status, json={"error": {"code": code, "message": "test"}})

    def factory():
        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle),
        ))

    async def run():
        async with Client(make_server(factory), mode="2026-07-28") as client:
            result = await client.call_tool("milai_memory_resolve", {"query": "test"})
            if expected == "tool_error":
                assert result.is_error and code in result.content[0].text
            else:
                assert not result.is_error
                assert result.structured_content["retrieval_status"] == expected

    asyncio.run(run())
    assert attempts == ["/v1/memory/resolve"]


def test_cancelled_resolve_releases_transport_without_cancelling_peer_or_reusing_closed_client():
    created, closed, attempts = [], [], []
    signals = {}

    def factory():
        loop = asyncio.get_running_loop()
        created.append(loop)
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        signals.update(entered=entered, cancelled=cancelled, release=release)
        active = 0

        async def handle(request):
            nonlocal active
            assert asyncio.get_running_loop() is loop
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json={**CAPABILITIES, "profile": "reader",
                                                "capabilities": ["memory:read"]})
            query = json.loads(request.content)["query"]
            attempts.append(query)
            active += 1
            if active == 2:
                entered.set()
            try:
                if query == "cancel":
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                else:
                    await release.wait()
                return httpx.Response(200, json=raw(query))
            finally:
                active -= 1

        class Transport(HttpxAsyncTransport):
            async def close(self):
                assert active == 0 and asyncio.get_running_loop() is loop
                closed.append(loop)
                await super().close()

        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=Transport(
            "http://127.0.0.1", 2, transport=httpx.MockTransport(handle),
        ))

    server = make_server(factory)

    async def run():
        async with Client(server, mode="2026-07-28") as client:
            cancelled = asyncio.create_task(client.call_tool(
                "milai_memory_resolve", {"query": "cancel"},
            ))
            peer = asyncio.create_task(client.call_tool("milai_memory_resolve", {"query": "peer"}))
            try:
                await asyncio.wait_for(signals["entered"].wait(), 2)
                cancelled.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await cancelled
                await asyncio.wait_for(signals["cancelled"].wait(), 2)
                assert not peer.done()
                signals["release"].set()
                result = await asyncio.wait_for(peer, 2)
                assert not result.is_error
                assert result.structured_content["evidence"][0]["text"] == "peer"
            finally:
                signals["release"].set()
                cancelled.cancel()
                peer.cancel()
                await asyncio.gather(cancelled, peer, return_exceptions=True)

    asyncio.run(run())
    asyncio.run(run())
    assert len(created) == len(closed) == 2 and created == closed and created[0] is not created[1]
    assert attempts.count("cancel") == attempts.count("peer") == 2
