"""Fresh native MCP protocol client for the local cold-recovery check; no model."""

import asyncio
import json
import os
import sys
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def run(config: dict[str, Any]) -> dict[str, Any]:
    async with httpx2.AsyncClient(headers={
        "Authorization": "Bearer " + config["token"], "Host": config["host"],
    }, timeout=15) as http:
        async with Client(
            streamable_http_client(config["url"], http_client=http), mode="2026-07-28",
        ) as client:
            results = []
            for action in config["actions"]:
                result = await client.call_tool(action["tool"], action["arguments"])
                results.append({
                    "is_error": bool(result.is_error), "body": result.structured_content,
                })
            return {"pid": os.getpid(), "results": results}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(json.load(sys.stdin))), ensure_ascii=False))
