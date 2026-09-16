"""Invoke only the published Product Host bootstrap API with an ordinary credential."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def main():
    from milai_mcp import prepare_http_working_context

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepared = asyncio.run(prepare_http_working_context(
        args.url, os.environ["MILAI_MCP_BEARER_TOKEN"], timeout_seconds=20))
    args.output.write_text(json.dumps(prepared, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
