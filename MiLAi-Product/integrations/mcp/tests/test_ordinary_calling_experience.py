"""Signed synthetic HTTP checks; no public services or real mutations."""
import json
from contextlib import asynccontextmanager

from milai_mcp.auth_policy import ALL_SCOPES, ORDINARY_CATALOG_TOOL_SCOPES
from milai_mcp.input_contracts import CAPTURE_EXAMPLE
from support.http import edge, rpc
from support.private_catalog import private_fixture


@asynccontextmanager
async def unused_state_client():
    yield None


def test_ordinary_catalog_excludes_cleanup_dispatch_even_with_admin_grant(tmp_path):
    fixture = private_fixture(tmp_path / "policy.json")
    with edge(fixture, scopes=ALL_SCOPES, catalog="ordinary-memory-v1",
              working_state_client_factory=unused_state_client) as (http, server, roles):
        token = fixture.token(sub="alice", scope=" ".join(sorted(ALL_SCOPES)))
        tools = rpc(http, "tools/list", token=token).json()["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == set(ORDINARY_CATALOG_TOOL_SCOPES)
        assert len(names) == 22
        assert "milai_namespace_cleanup_status" in names
        assert "milai_namespace_cleanup_submit" not in names
        assert "milai_namespace_cleanup_submit" not in {
            t.name for t in server._tool_manager.list_tools()
        }
        before = [len(role.calls) for role in roles]
        for arguments in [{}, {"operation_id": "blocked", "confirmation": "CLEANUP_NAMESPACE"}]:
            result = rpc(http, "tools/call", token=token, params={
                "name": "milai_namespace_cleanup_submit", "arguments": arguments,
            }).json()
            assert "error" in result or result["result"].get("isError")
        assert [len(role.calls) for role in roles] == before


def test_ordinary_advice_and_schema_are_explicit_without_repeated_server_prose(tmp_path):
    fixture = private_fixture(tmp_path / "policy.json")
    with edge(fixture, scopes=ALL_SCOPES, catalog="ordinary-memory-v1",
              working_state_client_factory=unused_state_client) as (http, _server, _roles):
        token = fixture.token(sub="alice", scope=" ".join(sorted(ALL_SCOPES)))
        init = rpc(http, "initialize", token=token, params={
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "calling-experience", "version": "1"},
        }).json()["result"]
        instructions = init["instructions"]
        assert "suggested_next_step" in instructions
        assert "administrator-only" in instructions
        assert "MiLAi provides persistent task memory" not in instructions
        tools = rpc(http, "tools/list", token=token).json()["result"]["tools"]
        for tool in tools:
            assert instructions not in tool.get("description", "")
            assert "MiLAi provides persistent task memory" not in tool.get("description", "")
        proposal = next(t for t in tools if t["name"] == "milai_proposal_create")
        assert proposal["inputSchema"]["properties"]["proposal"]["type"] == "object"
        assert "$ref" not in json.dumps(proposal["inputSchema"])
        assert ("CREATE patch requires subject_id, predicate, claim_type, payload"
                in proposal["description"])
        assert len(proposal["description"]) < 1000
        response = rpc(http, "tools/call", token=token, params={
            "name": "milai_evidence_capture", "arguments": CAPTURE_EXAMPLE,
        }).json()["result"]
        assert not response.get("isError"), response
        body = response["structuredContent"]
        assert "mcp_guidance" not in body
        advice = body["suggested_next_step"]
        assert advice["next_tool"] == "milai_proposal_create"
        assert advice["optional"] is True
        assert advice["requires_user_authorization"] is True
        assert advice["authorization_granted"] is False
