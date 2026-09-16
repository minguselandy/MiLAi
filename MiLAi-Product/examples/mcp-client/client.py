from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client


async def run(query: str) -> None:
    executable = Path(sys.executable).with_name("milai-mcp")
    parameters = StdioServerParameters(
        command=str(executable),
        args=["--profile", "reader"],
        env={
            "MILAI_BASE_URL": os.environ["MILAI_BASE_URL"],
            "MILAI_AGENT_TOKEN": os.environ["MILAI_AGENT_TOKEN"],
            "MILAI_AGENT_SCOPE_JSON": os.environ["MILAI_AGENT_SCOPE_JSON"],
            "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
        },
    )
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        result = await client.call_tool(
            "milai_recall",
            {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": 5},
        )
        print(result.structured_content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.query))
