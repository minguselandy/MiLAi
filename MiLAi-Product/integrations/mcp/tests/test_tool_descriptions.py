"""Host-first descriptions: useful without opening a schema, no behavior changes."""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import Client

from milai_mcp.auth_policy import ALL_SCOPES
from milai_mcp.server import SERVER_DESCRIPTION, CodexFullRuntimeClients, build_server
from test_aigcit_full import private_fixture
from test_aigcit_http import edge, rpc
from test_codex_full_profile import _as_client, _RoleClient


@asynccontextmanager
async def unused_state_client():
    yield None


@pytest.mark.parametrize("profile", [
    "agent-memory", "reader-lite", "reader-detail", "reader",
    "submitter", "reviewer", "operator", "codex-full",
])
def test_every_profile_exposes_readable_titles_and_concise_useful_descriptions(profile):
    async def run():
        role = _RoleClient("all")
        api = _as_client(role)
        server = build_server(
            profile, api, default_scope={"project_ids": ["project-one"]},
            codex_full_clients=CodexFullRuntimeClients(api, api, api, api),
        )
        assert server.name == "MiLAi" and server.title == "MiLAi"
        assert server.description == SERVER_DESCRIPTION
        assert "does not automatically ingest conversations" in server.description
        assert "Checkpoints can expire" in server.description
        async with Client(server, mode="2026-07-28") as client:
            tools = (await client.list_tools()).tools
        assert tools
        for tool in tools:
            assert tool.title and tool.title != tool.name
            description = tool.description or ""
            assert description.startswith("[")
            assert 80 <= len(description) <= 700, (tool.name, len(description))
            assert description == " ".join(description.split())
            assert len(description.split(". ", 1)[0]) <= 160, tool.name
            assert "persistent task memory" not in description
            assert SERVER_DESCRIPTION not in description
        assert not role.calls

    asyncio.run(run())


def test_oauth_initialize_and_all_ordinary_descriptions_are_host_ready(tmp_path):
    fixture = private_fixture(tmp_path / "policy.json")
    snapshot = Path(__file__).resolve().parents[3] / "contracts/mcp"
    old = json.loads((snapshot / "ordinary-memory-v1.repair-0.1.13.tools.json").read_text())
    old = {tool["name"]: tool for tool in old["tools"]}
    with edge(fixture, scopes=ALL_SCOPES, catalog="ordinary-memory-v1",
              working_state_client_factory=unused_state_client) as (http, _server, roles):
        token = fixture.token(sub="alice", scope=" ".join(sorted(ALL_SCOPES)))
        init = rpc(http, "initialize", token=token, params={
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "description-check", "version": "1"},
        }).json()["result"]
        assert init["serverInfo"]["title"] == "MiLAi"
        assert init["serverInfo"]["description"] == SERVER_DESCRIPTION
        assert "does not automatically ingest conversations" in init["instructions"]
        tools = rpc(http, "tools/list", token=token).json()["result"]["tools"]
        assert {tool["name"] for tool in tools} == set(old)
        for tool in tools:
            assert tool["title"] and tool["title"] != tool["name"]
            description = tool["description"]
            assert description.startswith("[") and len(description) <= 700
            assert description == " ".join(description.split())
            assert len(description.split(". ", 1)[0]) <= 160
            # Only display text changed; input schema and risk hints stay identical.
            assert tool["inputSchema"] == old[tool["name"]]["inputSchema"]
            for flag in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                assert tool["annotations"][flag] == old[tool["name"]]["annotations"][flag]
        by_name = {t["name"]: t for t in tools}
        assert "including across sessions" in by_name["milai_memory_search"]["description"]
        assert "lexical" in by_name["milai_note_search"]["description"]
        assert "physical_deletion_supported=false" in by_name["milai_note_delete"]["description"]
        assert "is not approval" in by_name["milai_proposal_create"]["description"]
        assert "expire" in by_name["milai_working_state_get"]["description"]
        assert not any(role.calls for role in roles)
