"""Fixed full-lifecycle Codex HTTP MCP entrypoint."""

from __future__ import annotations

import argparse

from milai_mcp.profiles import accepted_resolve_budget_profile_names
from milai_mcp.server import main as server_main

_DEFAULT_BUDGET_PROFILE = "MCP_INTERACTIVE_STANDARD_V01"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "MiLAi Codex full-control MCP facade (authenticated Streamable HTTP, "
            "fixed codex-full profile, zero automatic retries)"
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7337)
    parser.add_argument("--mcp-path", default="/mcp")
    parser.add_argument("--catalog", choices=(
        "legacy", "ordinary-memory-v1", "compact-memory-v1",
    ), default="legacy", help="Select advanced or compact memory tools; grants stay unchanged")
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help=(
            "explicitly allow a non-loopback listener; requires a public base URL "
            "and does not provide TLS"
        ),
    )
    parser.add_argument(
        "--resolve-budget-profile",
        choices=accepted_resolve_budget_profile_names(),
        default=_DEFAULT_BUDGET_PROFILE,
        help="Host-owned fixed resolve budget profile",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run full lifecycle without exposing transport/profile/retry choices."""

    args = _parser().parse_args(argv)
    server_arguments = [
            "--transport",
            "streamable-http",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--mcp-path",
            args.mcp_path,
            "--profile",
            "codex-full",
            "--max-retries",
            "0",
            "--resolve-budget-profile",
            args.resolve_budget_profile,
        ]
    if args.allow_non_loopback:
        server_arguments.append("--allow-non-loopback")
    if args.catalog != "legacy":
        server_arguments.extend(["--catalog", args.catalog])
    server_main(server_arguments)
