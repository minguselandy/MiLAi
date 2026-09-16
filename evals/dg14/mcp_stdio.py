"""Persistent current-protocol stdio MCP transport for DG-14.

The benchmark/provisioner interpreter intentionally does not depend on the MCP
SDK. A tiny JSON-lines dispatcher therefore runs under the Python interpreter
next to the configured ``milai-mcp`` executable. It owns all four MCP client
contexts in one asyncio Task for their complete lifetime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import select
import subprocess
import sys
from collections.abc import Mapping
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, cast

from evals.dg14.contracts import (
    MCP_PROTOCOL_MODE,
    DG14AdapterConfig,
    DG14ContractError,
    DG14LifecycleError,
    DG14TransportError,
    McpProfile,
)

_PROFILES: tuple[McpProfile, ...] = (
    "submitter",
    "reviewer",
    "reader-detail",
    "operator",
)
_REQUIRED_TOOLS: dict[McpProfile, frozenset[str]] = {
    "submitter": frozenset({"milai_evidence_capture", "milai_proposal_create"}),
    "reviewer": frozenset({"milai_proposal_get", "milai_memory_review"}),
    "reader-detail": frozenset({"milai_memory_resolve", "milai_trace_get"}),
    "operator": frozenset({"milai_evidence_revoke"}),
}
# The MCP Runtime client allows 35 seconds so a bounded 30-second projection
# readiness slice can return a typed 408. The outer stdio envelope must remain
# strictly wider or it converts that typed response into a transport timeout.
_BRIDGE_TIMEOUT_SECONDS = 40.0


class StdioMcpTransport:
    """Keep one authenticated MCP subprocess/session open for each named profile."""

    def __init__(self, config: DG14AdapterConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._request_sequence = 0
        # Explicit inert fields retain compatibility with old diagnostic probes.
        self._loop: None = None
        self._clients: dict[McpProfile, object] = {}

    @property
    def process_id(self) -> int:
        """Return the live dispatcher PID used as the MCP process witness."""

        process = self._process
        if process is None or process.poll() is not None:
            raise DG14LifecycleError("stdio MCP transport has no live dispatcher")
        return process.pid

    def open_case(self, scope: Mapping[str, object]) -> None:
        if self._process is not None:
            raise DG14LifecycleError("stdio MCP transport already has an open case")
        normalized_scope = dict(scope)
        if not normalized_scope.get("project_ids"):
            raise DG14ContractError("stdio MCP scope must contain the exact case project_id")
        executable = Path(self._config.executable).resolve()
        if not executable.is_file():
            raise DG14TransportError(f"milai-mcp executable does not exist: {executable}")
        client_python = executable.with_name("python")
        if not client_python.is_file():
            raise DG14TransportError(
                f"MCP client interpreter does not exist next to milai-mcp: {client_python}"
            )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MILAI_")
        }
        project_root = Path(__file__).resolve().parents[2]
        process = subprocess.Popen(
            [
                str(client_python),
                "-c",
                "from evals.dg14.mcp_stdio import _main; _main()",
                "--bridge",
            ],
            cwd=project_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        self._process = process
        self._request_sequence = 0
        try:
            response = self._exchange(
                {
                    "kind": "initialize",
                    "base_url": self._config.base_url,
                    "executable": str(executable),
                    "profile_tokens": dict(self._config.profile_tokens),
                    "scope": normalized_scope,
                    "max_limit": self._config.max_limit,
                }
            )
        except (DG14TransportError, OSError, subprocess.SubprocessError):
            self._terminate_bridge()
            raise
        if response.get("kind") != "ready" or response.get("protocol_mode") != (
            MCP_PROTOCOL_MODE
        ):
            self._terminate_bridge()
            raise DG14TransportError("MCP dispatcher returned an invalid readiness receipt")

    def _environment(
        self, profile: McpProfile, scope: Mapping[str, object]
    ) -> dict[str, str]:
        return _profile_environment(
            base_url=self._config.base_url,
            token=self._config.profile_tokens[profile],
            scope=scope,
            max_limit=self._config.max_limit,
        )

    def call(
        self,
        profile: McpProfile,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> dict[str, object]:
        if getattr(self, "_process", None) is None:
            raise DG14LifecycleError("stdio MCP transport has no open case")
        if tool_name not in _REQUIRED_TOOLS[profile]:
            raise DG14TransportError(
                f"DG14 does not permit {profile} to call unregistered tool {tool_name}"
            )
        response = self._exchange(
            {
                "kind": "call",
                "profile": profile,
                "tool_name": tool_name,
                "arguments": dict(arguments),
            }
        )
        structured = response.get("structured")
        if not isinstance(structured, dict):
            raise DG14TransportError(
                f"MCP tool returned no structured object: {profile}/{tool_name}"
            )
        return cast(dict[str, object], structured)

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            response = self._exchange({"kind": "close"})
        except (DG14TransportError, OSError, subprocess.SubprocessError):
            self._terminate_bridge()
            raise
        if response.get("kind") != "closed":
            self._terminate_bridge()
            raise DG14TransportError("MCP dispatcher returned an invalid close receipt")
        try:
            return_code = process.wait(timeout=_BRIDGE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            self._terminate_bridge()
            raise DG14TransportError("MCP dispatcher did not exit after close") from exc
        self._process = None
        if return_code != 0:
            raise DG14TransportError("MCP dispatcher exited unsuccessfully")

    def _exchange(self, payload: Mapping[str, object]) -> dict[str, object]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise DG14LifecycleError("stdio MCP transport has no open dispatcher")
        self._request_sequence += 1
        request_id = self._request_sequence
        envelope = {"request_id": request_id, **dict(payload)}
        encoded = (
            json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        try:
            process.stdin.write(encoded)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise DG14TransportError("MCP dispatcher input pipe failed") from exc
        readable, _writable, _exceptional = select.select(
            [process.stdout], [], [], _BRIDGE_TIMEOUT_SECONDS
        )
        if not readable:
            # A timed-out request may still emit a late reply.  The stream is no
            # longer safe for another request (including ``close``), because
            # that late reply would be mistaken for the next envelope.
            self._terminate_bridge()
            raise DG14TransportError("MCP dispatcher response timed out")
        raw = process.stdout.readline()
        if not raw:
            raise DG14TransportError(
                f"MCP dispatcher exited before responding (code={process.poll()})"
            )
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._terminate_bridge()
            raise DG14TransportError("MCP dispatcher returned invalid JSON") from exc
        if not isinstance(response, dict) or response.get("request_id") != request_id:
            self._terminate_bridge()
            raise DG14TransportError("MCP dispatcher response identity drifted")
        if response.get("ok") is not True:
            code = response.get("error_code")
            raise DG14TransportError(f"MCP dispatcher rejected request: {code}")
        return cast(dict[str, object], response)

    def _terminate_bridge(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _profile_environment(
    *,
    base_url: str,
    token: str,
    scope: Mapping[str, object],
    max_limit: int,
) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL")
        if key in os.environ
    }
    environment.update(
        {
            "MILAI_BASE_URL": base_url,
            "MILAI_AGENT_TOKEN": token,
            "MILAI_AGENT_SCOPE_JSON": json.dumps(
                scope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_AGENT_MAX_LIMIT": str(max_limit),
            "MILAI_AGENT_MAX_RETRIES": "0",
        }
    )
    return environment


async def _bridge() -> None:
    try:
        from mcp import (  # type: ignore[import-not-found]
            Client,
            MCPError,
            StdioServerParameters,
            stdio_client,
        )
    except ImportError as exc:
        raise DG14TransportError("the configured MCP client environment lacks mcp") from exc

    raw_initialize = await asyncio.to_thread(sys.stdin.buffer.readline)
    initialize = _bridge_request(raw_initialize, "initialize")
    request_id = _bridge_request_id(initialize)
    base_url = _bridge_text(initialize, "base_url")
    executable = _bridge_text(initialize, "executable")
    scope = initialize.get("scope")
    profile_tokens = initialize.get("profile_tokens")
    max_limit = initialize.get("max_limit")
    if not isinstance(scope, dict) or not scope.get("project_ids"):
        raise DG14TransportError("bridge initialize scope is invalid")
    if not isinstance(profile_tokens, dict) or set(profile_tokens) != set(_PROFILES):
        raise DG14TransportError("bridge initialize profile tokens are invalid")
    if not isinstance(max_limit, int) or isinstance(max_limit, bool):
        raise DG14TransportError("bridge initialize max_limit is invalid")

    closing_request_id: int | None = None
    async with AsyncExitStack() as stack:
        clients: dict[McpProfile, Any] = {}
        for profile in _PROFILES:
            token = profile_tokens.get(profile)
            if not isinstance(token, str) or not token:
                raise DG14TransportError(f"bridge token is invalid for {profile}")
            parameters = StdioServerParameters(
                command=executable,
                args=["--profile", profile, "--max-retries", "0"],
                env=_profile_environment(
                    base_url=base_url,
                    token=token,
                    scope=scope,
                    max_limit=max_limit,
                ),
            )
            try:
                client = await stack.enter_async_context(
                    Client(stdio_client(parameters), mode=MCP_PROTOCOL_MODE)
                )
                catalog = await client.list_tools()
            except (MCPError, OSError, RuntimeError, TimeoutError) as exc:
                raise DG14TransportError(
                    f"could not open current MCP profile {profile}"
                ) from exc
            names = {item.name for item in catalog.tools}
            missing = sorted(_REQUIRED_TOOLS[profile] - names)
            if missing:
                raise DG14TransportError(
                    f"profile {profile} is missing current DG13 MCP tools: {missing}"
                )
            if client.protocol_version != MCP_PROTOCOL_MODE:
                raise DG14TransportError(
                    f"profile {profile} negotiated unexpected MCP protocol"
                )
            clients[profile] = client
        _bridge_reply(
            request_id,
            {
                "kind": "ready",
                "protocol_mode": MCP_PROTOCOL_MODE,
                "profiles": list(_PROFILES),
            },
        )

        while True:
            raw_request = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not raw_request:
                return
            request = _bridge_request(raw_request)
            request_id = _bridge_request_id(request)
            kind = request.get("kind")
            if kind == "close":
                closing_request_id = request_id
                break
            if kind != "call":
                _bridge_error(request_id, "UNKNOWN_REQUEST_KIND")
                continue
            raw_profile = request.get("profile")
            tool_name = request.get("tool_name")
            arguments = request.get("arguments")
            if (
                raw_profile not in _PROFILES
                or not isinstance(tool_name, str)
                or not isinstance(arguments, dict)
            ):
                _bridge_error(request_id, "INVALID_CALL_ENVELOPE")
                continue
            profile = raw_profile
            if tool_name not in _REQUIRED_TOOLS[profile]:
                _bridge_error(request_id, "TOOL_NOT_PERMITTED")
                continue
            try:
                result = await clients[profile].call_tool(tool_name, arguments)
            except (MCPError, OSError, RuntimeError, TimeoutError):
                _bridge_error(request_id, "MCP_CALL_FAILED")
                continue
            if result.is_error is True or not isinstance(result.structured_content, dict):
                _bridge_error(request_id, "MCP_TOOL_ERROR")
                continue
            _bridge_reply(request_id, {"structured": result.structured_content})

    if closing_request_id is not None:
        _bridge_reply(closing_request_id, {"kind": "closed"})


def _bridge_request(raw: bytes, expected_kind: str | None = None) -> dict[str, object]:
    if not raw:
        raise DG14TransportError("MCP dispatcher input closed")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DG14TransportError("MCP dispatcher input is invalid JSON") from exc
    if not isinstance(value, dict):
        raise DG14TransportError("MCP dispatcher input must be an object")
    if expected_kind is not None and value.get("kind") != expected_kind:
        raise DG14TransportError(f"MCP dispatcher expected {expected_kind}")
    return cast(dict[str, object], value)


def _bridge_request_id(request: Mapping[str, object]) -> int:
    value = request.get("request_id")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DG14TransportError("MCP dispatcher request_id is invalid")
    return value


def _bridge_text(request: Mapping[str, object], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise DG14TransportError(f"MCP dispatcher field {field} is invalid")
    return value


def _bridge_reply(request_id: int, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(
        {"request_id": request_id, "ok": True, **dict(payload)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _bridge_error(request_id: int, error_code: str) -> None:
    encoded = json.dumps(
        {"request_id": request_id, "ok": False, "error_code": error_code},
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bridge", action="store_true")
    args = parser.parse_args()
    if not args.bridge:
        raise SystemExit("mcp_stdio is an internal DG14 dispatcher")
    asyncio.run(_bridge())


if __name__ == "__main__":
    _main()
