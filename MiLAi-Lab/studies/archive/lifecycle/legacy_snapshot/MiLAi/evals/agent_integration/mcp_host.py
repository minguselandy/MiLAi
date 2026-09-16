from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters, stdio_client


async def _run(
    profile: str,
    mode: str,
    tool: str | None,
    arguments: dict[str, Any],
    *,
    include_catalog: bool = False,
) -> dict[str, Any]:
    executable = Path(sys.executable).with_name("milai-mcp")
    if not executable.is_file():
        raise RuntimeError("milai-mcp entrypoint is not installed")
    server_environment = {
        "MILAI_BASE_URL": os.environ["MILAI_BASE_URL"],
        "MILAI_AGENT_TOKEN": os.environ["MILAI_AGENT_TOKEN"],
    }
    for name in (
        "MILAI_AGENT_SCOPE_JSON",
        "MILAI_AGENT_REQUIRED_AUTHORITY",
        "MILAI_AGENT_CONSISTENCY_FLOOR",
        "MILAI_AGENT_MAX_LIMIT",
        "MILAI_AGENT_AS_OF",
    ):
        if name in os.environ:
            server_environment[name] = os.environ[name]
    parameters = StdioServerParameters(
        command=str(executable),
        args=["--profile", profile],
        env=server_environment,
    )
    transport = stdio_client(parameters)
    async with Client(transport, mode=mode) as session:
        catalog = await session.list_tools()
        names = [item.name for item in catalog.tools]
        catalog_payload = (
            [item.model_dump(mode="json", by_alias=True) for item in catalog.tools]
            if include_catalog
            else None
        )
        if tool is None:
            result: dict[str, Any] = {
                "protocol_version": session.protocol_version,
                "tools": names,
            }
            if catalog_payload is not None:
                result["catalog"] = catalog_payload
                result["server_executable"] = str(executable.resolve())
            return result
        tool_result = await session.call_tool(tool, arguments)
        response = {
            "protocol_version": session.protocol_version,
            "tools": names,
            "is_error": tool_result.is_error,
            "structured": tool_result.structured_content,
            "content": [
                item.model_dump(mode="json") for item in tool_result.content
            ],
        }
        if catalog_payload is not None:
            response["catalog"] = catalog_payload
            response["server_executable"] = str(executable.resolve())
        return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("reader-lite", "reader-detail", "reader", "submitter", "operator"),
        required=True,
    )
    parser.add_argument(
        "--mode", choices=("2026-07-28", "legacy"), default="2026-07-28"
    )
    parser.add_argument("--tool")
    parser.add_argument(
        "--include-catalog",
        action="store_true",
        help="Include the full list_tools schema payload for functional package checks.",
    )
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise TypeError("MCP arguments must be an object")
    result = asyncio.run(
        _run(
            args.profile,
            args.mode,
            args.tool,
            payload,
            include_catalog=args.include_catalog,
        )
    )
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
