"""Fresh compact protocol consumer. Discovery input contains no old ID or answer."""

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
            async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                response = await client.call_tool(name, arguments)
                assert not response.is_error, response.content
                assert isinstance(response.structured_content, dict)
                return response.structured_content

            if "save" in config:
                saved = await call("milai_memory_save", config["save"])
                return {"pid": os.getpid(), "saved": saved}
            # This branch receives only the new question/literal hint and connection identity.
            assert set(config) <= {"url", "host", "token", "query", "note_query"}
            discovery = await call("milai_memory_search", {
                "query": config["query"], "note_query": config.get("note_query"),
            })
            reads = []
            for item in (discovery["sources"]["notes"]["result"] or {}).get("items", []):
                assert item["read_tool"] == "milai_memory_read"
                arguments = item["read_arguments"]
                pages = []
                while True:
                    page = await call(item["read_tool"], arguments)
                    pages.append(page)
                    if page.get("next_offset") is None:
                        break
                    arguments = {"target": {**page["read_arguments"]["target"],
                                            "offset": page["next_offset"]}}
                reads.append({"pages": pages, "content": "".join(p["content"] for p in pages)})
            return {"pid": os.getpid(), "discovery": discovery, "reads": reads}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(json.load(sys.stdin))), ensure_ascii=False))
