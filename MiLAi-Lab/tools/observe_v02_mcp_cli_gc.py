"""Observe standard Python GC around the published CLI, without private Product hooks."""

from __future__ import annotations

import argparse
import runpy
import signal
import sys
from pathlib import Path

from v02_client_gc import observe


def run(entrypoint: Path, arguments: list[str], output: Path) -> None:
    argv, original_term = sys.argv, signal.getsignal(signal.SIGTERM)

    def terminate(signum, _frame):
        # Uvicorn restores and re-raises SIGTERM after its own graceful cleanup.
        # Retain normal termination while allowing the probe's finally to write.
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    sys.argv = [str(entrypoint), *arguments]
    try:
        with observe(
            output, enabled=True, output_name="mcp-gc.json",
            scope="MCP_SERVER_STANDARD_GC_AROUND_PUBLISHED_CLI",
        ):
            runpy.run_path(str(entrypoint), run_name="__main__")
    finally:
        sys.argv = argv
        signal.signal(signal.SIGTERM, original_term)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("entrypoint", type=Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    run(args.entrypoint, args.arguments, args.output)
