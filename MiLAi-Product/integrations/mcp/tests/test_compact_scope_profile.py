"""Deployment examples must request exactly the scopes of every compact branch."""
import re
import tomllib
from pathlib import Path

from milai_mcp.auth_policy import (
    ALL_TOOL_SCOPES,
    COMPACT_CATALOG_TOOL_SCOPES,
    FULL_SCOPES,
    TOOL_SCOPE_ALTERNATIVES,
)
from milai_mcp.compact_memory import COMPACT_BACKENDS
from test_aigcit_http import rpc
from test_compact_memory import NOTE_REF, compact_edge, tool_call

REQUIRED = frozenset().union(
    *(TOOL_SCOPE_ALTERNATIVES.get(tool, {scope})
      for tool, scope in COMPACT_CATALOG_TOOL_SCOPES.items()),
    {ALL_TOOL_SCOPES[tool] for tool in COMPACT_BACKENDS},
)


def test_compact_deployment_profiles_match_real_tool_branch_union():
    root = Path(__file__).resolve().parents[3]
    examples = root / "examples/codex-mcp"
    assert len(REQUIRED) == 9
    assert not REQUIRED & {
        "milai.proposal.create", "milai.proposal.review", "milai.operations.admin",
    }
    for name in ("milai-aigcit-client.toml.example", "milai-private-workflow.toml.example"):
        client = tomllib.loads((examples / name).read_text())
        assert set(client["mcp_servers"]["milai"]["scopes"]) == REQUIRED
        assert "oauth_resource" not in client["mcp_servers"]["milai"]
    env = (examples / "milai-aigcit.env.example").read_text()
    scopes = re.search(r'^MILAI_AIGCIT_ENABLED_SCOPES="([^"]+)"$', env, re.M)
    assert scopes and set(scopes[1].split()) == REQUIRED
    script = (examples / "milai-reauthorize.ps1").read_text()
    assert set(re.findall(r'"(milai\.[a-z.]+)"', script)) == REQUIRED
    assert "8 tools" in script and "9 scopes" in script
    unit = (examples / "milai-aigcit.service.example").read_text()
    assert "--catalog compact-memory-v1" in unit
    assert "--port 7969" in unit
    proxy = (examples / "milai-aigcit-7960.nginx.conf.example").read_text()
    assert proxy.count("proxy_pass http://127.0.0.1:7969;") == 2
    assert "127.0.0.1:7968" not in proxy


def test_compact_nine_scopes_allow_notes_but_old_grant_stays_restricted(tmp_path):
    with compact_edge(tmp_path, scopes=REQUIRED) as (fixture, http, _, _, spy):
        fresh = fixture.token(sub="alice", scope=" ".join(REQUIRED))
        tools = rpc(http, "tools/list", token=fresh).json()["result"]["tools"]
        assert {t["name"] for t in tools} == set(COMPACT_CATALOG_TOOL_SCOPES)
        assert tool_call(http, fresh, "milai_memory_read", NOTE_REF)["content"] == "会议记录"
        assert tool_call(http, fresh, "milai_memory_list", {})["items"]
        found = tool_call(http, fresh, "milai_memory_search", {"query": "会议"})
        assert found["sources"]["notes"]["status"] == "OK"
        old = fixture.token(sub="alice", scope=" ".join(FULL_SCOPES))
        tools = rpc(http, "tools/list", token=old).json()["result"]["tools"]
        assert {t["name"] for t in tools} == (
            set(COMPACT_CATALOG_TOOL_SCOPES) - {"milai_memory_list"}
        )
        before = len(spy.calls)
        denied = rpc(http, "tools/call", token=old, params={
            "name": "milai_memory_read", "arguments": NOTE_REF,
        }).json()["result"]
        assert denied["isError"] and len(spy.calls) == before
        result = tool_call(http, old, "milai_memory_search", {"query": "会议"})
        assert result["sources"]["notes"]["status"] == "NOT_AUTHORIZED"
        assert len(spy.calls) == before
