from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from mcp import Client
from milai_mcp.server import build_server


class _Api:
    def capabilities(self) -> Any:
        return SimpleNamespace(
            raw={"contract_version": "agent.v1", "data_mode": "SYNTHETIC_ONLY"}
        )


async def run() -> None:
    server = build_server("reader", _Api())  # type: ignore[arg-type]
    async with Client(server, mode="2026-07-28") as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        assert names == sorted(names)
        assert "milai_proposal_review" not in names
        status = await client.call_tool("milai_status", {})
        assert status.structured_content["data_mode"] == "SYNTHETIC_ONLY"
    print("mcp-client smoke: PASS")


if __name__ == "__main__":
    asyncio.run(run())
