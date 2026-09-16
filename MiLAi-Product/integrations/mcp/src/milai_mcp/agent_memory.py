"""Fixed product entrypoint for the authenticated agent-memory HTTP facade."""

from __future__ import annotations

import argparse

from milai_mcp.profiles import accepted_resolve_budget_profile_names
from milai_mcp.server import main as server_main

_DEFAULT_BUDGET_PROFILE = "MCP_INTERACTIVE_STANDARD_V01"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "MiLAi agent-memory MCP facade (authenticated Streamable HTTP, "
            "fixed agent-memory profile, zero automatic retries)"
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7337)
    parser.add_argument("--mcp-path", default="/mcp")
    parser.add_argument(
        "--resolve-budget-profile",
        choices=accepted_resolve_budget_profile_names(),
        default=_DEFAULT_BUDGET_PROFILE,
        help="host-owned fixed resolve budget profile",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the product facade without exposing transport/profile/retry choices."""

    args = _parser().parse_args(argv)
    server_main(
        [
            "--transport",
            "streamable-http",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--mcp-path",
            args.mcp_path,
            "--profile",
            "agent-memory",
            "--max-retries",
            "0",
            "--resolve-budget-profile",
            args.resolve_budget_profile,
        ]
    )
