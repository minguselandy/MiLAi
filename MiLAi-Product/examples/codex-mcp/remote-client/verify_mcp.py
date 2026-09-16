from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = {"2025-11-25", PROTOCOL_VERSION}
EXPECTED_TOOLS = {
    "milai_deletion_status_get",
    "milai_evidence_capture",
    "milai_evidence_revoke",
    "milai_memory_get",
    "milai_memory_resolve",
    "milai_memory_review",
    "milai_namespace_cleanup_status",
    "milai_namespace_cleanup_submit",
    "milai_proposal_create",
    "milai_proposal_get",
    "milai_proposals_list",
    "milai_working_state_get",
    "milai_working_state_update",
}
CLIENT_VERSION = (
    Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()
    if Path(__file__).with_name("VERSION").is_file()
    else "development"
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@dataclass(frozen=True)
class Response:
    status: int
    headers: Any
    payload: dict[str, Any] | None


def parse_body(body: bytes, content_type: str) -> dict[str, Any] | None:
    if not body:
        return None
    text = body.decode("utf-8")
    if content_type.split(";", 1)[0].strip() == "text/event-stream":
        messages = [
            json.loads(line[5:].strip())
            for line in text.splitlines()
            if line.startswith("data:") and line[5:].strip()
        ]
        if not messages:
            raise RuntimeError("MCP response contained no SSE data frame")
        return messages[-1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise TypeError("MCP response must be a JSON object")
    return value


def post(
    opener: Any,
    *,
    url: str,
    token: str,
    payload: dict[str, Any],
    session_id: str | None = None,
) -> Response:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = Request(  # noqa: S310 - caller validates absolute HTTP(S) /mcp URL
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with opener.open(request, timeout=15) as response:
        body = response.read()
        return Response(
            status=response.status,
            headers=response.headers,
            payload=parse_body(body, response.headers.get("Content-Type", "")),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a MiLAi codex-full MCP endpoint")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path != "/mcp":
        parser.error("--url must be an absolute HTTP(S) URL whose path is /mcp")
    token = os.environ.get("MILAI_CODEX_TOKEN", "")
    if len(token) < 32:
        parser.error("MILAI_CODEX_TOKEN must contain at least 32 characters")
    opener = build_opener(NoRedirect)
    try:
        initialized = post(
            opener,
            url=args.url,
            token=token,
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "milai-remote-verifier",
                        "version": CLIENT_VERSION,
                    },
                },
            },
        )
        session_id = initialized.headers.get("Mcp-Session-Id")
        if initialized.status != 200 or initialized.payload is None or not session_id:
            raise RuntimeError("MCP initialize did not return a session")
        if "error" in initialized.payload:
            raise RuntimeError(f"MCP initialize failed: {initialized.payload['error']}")
        negotiated = initialized.payload.get("result", {}).get("protocolVersion")
        if negotiated not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(f"unexpected protocol version: {negotiated!r}")

        post(
            opener,
            url=args.url,
            token=token,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        listed = post(
            opener,
            url=args.url,
            token=token,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        if listed.payload is None or "error" in listed.payload:
            raise RuntimeError(f"tools/list failed: {listed.payload}")
        tools = listed.payload.get("result", {}).get("tools", [])
        names = {item.get("name") for item in tools if isinstance(item, dict)}
        if names != EXPECTED_TOOLS:
            missing = sorted(EXPECTED_TOOLS - names)
            extra = sorted(names - EXPECTED_TOOLS)
            raise RuntimeError(f"unexpected tool catalog; missing={missing}, extra={extra}")
    except HTTPError as exc:
        print(f"verification failed: HTTP {exc.code}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1

    print("authenticated=true")
    print(f"tool_count={len(EXPECTED_TOOLS)}")
    print("catalog=codex-full-v1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
