"""Generate contract metadata from actual signed MCP requests; never call a business tool."""

import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from milai_mcp.auth_policy import ALL_SCOPES, TOOL_SCOPE_ALTERNATIVES
from test_aigcit_full import private_fixture
from test_aigcit_http import edge, rpc


def encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


@asynccontextmanager
async def unused_state_client():
    yield None


def export():
    report = {"schema_version": "compact-catalog-release-v1", "catalogs": {},
              "serialization": "JSON ensure_ascii=false sort_keys=true separators=(',', ':')",
              "tokenizer": None, "model_requests": 0}
    with tempfile.TemporaryDirectory(prefix="milai-compact-catalog-") as temporary:
        fixture = private_fixture(Path(temporary) / "policy.json")
        for catalog in ("legacy", "ordinary-memory-v1", "compact-memory-v1"):
            with edge(fixture, scopes=ALL_SCOPES, catalog=catalog,
                      working_state_client_factory=unused_state_client) as (http, _server, roles):
                token = fixture.token(sub="alice", scope=" ".join(sorted(ALL_SCOPES)))
                initialized = rpc(http, "initialize", token=token, params={
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "compact-release-metadata", "version": "1"},
                }).json()["result"]
                listed = rpc(http, "tools/list", token=token).json()["result"]
                counts = {}
                for scope in sorted(ALL_SCOPES):
                    scoped = fixture.token(sub="alice", scope=scope)
                    tools = rpc(http, "tools/list", token=scoped).json()["result"]["tools"]
                    counts[scope] = [t["name"] for t in tools]
                report["catalogs"][catalog] = {
                    "serverInfo": initialized["serverInfo"],
                    "instructions": initialized["instructions"], "tools": listed["tools"],
                    "tool_count": len(listed["tools"]), "single_scope_tools": counts,
                    "tools_list_utf8_bytes": encoded_bytes(listed),
                    "instructions_utf8_bytes": len(initialized["instructions"].encode("utf-8")),
                    "initialize_result_utf8_bytes": encoded_bytes(initialized),
                }
                assert not any(role.calls for role in roles)
    report["entry_scope_alternatives"] = {k: sorted(v) for k, v in TOOL_SCOPE_ALTERNATIVES.items()}
    return report


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    print(json.dumps(export(), ensure_ascii=False, indent=2))
