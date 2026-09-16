"""Administrative enrollment CLI for the MiLAi MCP OAuth provider."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from milai_mcp.oauth_provider import OAuthStore
from milai_mcp.remote_registration import validate_agent_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Issue, list or revoke MiLAi OAuth user enrollments"
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(
            os.environ.get("MILAI_OAUTH_DB", "/var/lib/milai-mcp/oauth.sqlite3")
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue = subparsers.add_parser("issue")
    issue.add_argument("--agent-id", required=True)
    issue.add_argument("--replace", action="store_true")
    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--agent-id", required=True)
    subparsers.add_parser("list")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the owner-only OAuth enrollment operation."""

    args = _parser().parse_args(argv)
    store = OAuthStore(args.database)
    result: dict[str, Any]
    if args.command == "issue":
        enrollment_code = store.issue_enrollment(
            args.agent_id, replace=args.replace
        )
        result = {
            "agent_id": validate_agent_id(args.agent_id),
            "enrollment_code": enrollment_code,
            "status": "PENDING",
            "usage": "Enter this one-time code in the browser OAuth consent page.",
        }
    elif args.command == "revoke":
        store.revoke_user(args.agent_id)
        result = {"agent_id": validate_agent_id(args.agent_id), "status": "REVOKED"}
    else:
        result = {"users": store.list_users()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
