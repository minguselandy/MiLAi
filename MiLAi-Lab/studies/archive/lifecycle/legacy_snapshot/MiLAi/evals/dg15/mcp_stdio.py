"""Persistent DG-15 MCP transport with one bounded multiplexed call primitive."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from evals.dg14.contracts import (
    MCP_PROTOCOL_MODE,
    DG14AdapterConfig,
    DG14ContractError,
    DG14LifecycleError,
    DG14TransportError,
    McpProfile,
)
from evals.dg14.mcp_stdio import (
    StdioMcpTransport,
    _bridge_error,
    _bridge_reply,
    _bridge_request,
    _bridge_request_id,
    _bridge_text,
    _profile_environment,
)

_PROFILES: tuple[McpProfile, ...] = (
    "submitter",
    "reviewer",
    "reader-detail",
    "operator",
)
_REQUIRED_TOOLS: dict[McpProfile, frozenset[str]] = {
    "submitter": frozenset({"milai_evidence_capture"}),
    "reviewer": frozenset({"milai_proposal_get", "milai_memory_review"}),
    "reader-detail": frozenset(
        {
            "milai_memory_resolve",
            "milai_trace_get",
            "milai_projection_readiness_wait",
        }
    ),
    "operator": frozenset(
        {
            "milai_evidence_revoke",
            "milai_namespace_cleanup_submit",
            "milai_namespace_cleanup_status",
        }
    ),
}
_ALLOWED_CONCURRENCY = frozenset({1, 2, 4, 8})
_MAX_BATCH_ITEMS = 512


@dataclass(frozen=True, slots=True)
class McpBatchCall:
    profile: McpProfile
    tool_name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class McpBatchOutcome:
    ordinal: int
    status: Literal["SUCCEEDED", "FAILED"]
    structured: Mapping[str, object] | None
    error_code: str | None


class MultiplexedStdioMcpTransport(StdioMcpTransport):
    """Reuse four authenticated MCP sessions and batch only physical scheduling."""

    def __init__(
        self,
        config: DG14AdapterConfig,
        *,
        stderr: Any = None,
    ) -> None:
        super().__init__(config)
        self._process: subprocess.Popen[bytes] | None
        self._config = config
        self._stderr = stderr

    def open_case(self, scope: Mapping[str, object]) -> None:
        if self._process is not None:
            raise DG14LifecycleError("stdio MCP transport already has an open case")
        normalized_scope = dict(scope)
        if not normalized_scope.get("project_ids"):
            raise DG14ContractError(
                "stdio MCP scope must contain the exact case project_id"
            )
        executable = Path(self._config.executable).resolve()
        if not executable.is_file():
            raise DG14TransportError(
                f"milai-mcp executable does not exist: {executable}"
            )
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
                "from evals.dg15.mcp_stdio import _main; _main()",
                "--bridge",
            ],
            cwd=project_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
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
            raise DG14TransportError(
                "MCP dispatcher returned an invalid readiness receipt"
            )

    def call(
        self,
        profile: McpProfile,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> dict[str, object]:
        outcome = self.call_many(
            [McpBatchCall(profile, tool_name, arguments)], max_concurrency=1
        )[0]
        if outcome.status != "SUCCEEDED" or outcome.structured is None:
            raise DG14TransportError(
                f"MCP tool failed: {profile}/{tool_name}/{outcome.error_code}"
            )
        return dict(outcome.structured)

    def call_many(
        self,
        calls: Sequence[McpBatchCall],
        *,
        max_concurrency: int,
    ) -> tuple[McpBatchOutcome, ...]:
        if self._process is None:
            raise DG14LifecycleError("stdio MCP transport has no open case")
        if max_concurrency not in _ALLOWED_CONCURRENCY:
            raise DG14ContractError("MCP concurrency must be one of 1, 2, 4, or 8")
        if not 1 <= len(calls) <= _MAX_BATCH_ITEMS:
            raise DG14ContractError("MCP batch must contain between 1 and 512 calls")
        if len(calls) > max_concurrency:
            raise DG14ContractError(
                "MCP batch must fit in one bounded concurrency wave"
            )
        payload_calls: list[dict[str, object]] = []
        for ordinal, call in enumerate(calls):
            if call.tool_name not in _REQUIRED_TOOLS[call.profile]:
                raise DG14TransportError(
                    f"DG15 does not permit {call.profile} to call {call.tool_name}"
                )
            payload_calls.append(
                {
                    "ordinal": ordinal,
                    "profile": call.profile,
                    "tool_name": call.tool_name,
                    "arguments": dict(call.arguments),
                }
            )
        response = self._exchange(
            {
                "kind": "call_many",
                "max_concurrency": max_concurrency,
                "calls": payload_calls,
            }
        )
        raw_outcomes = response.get("outcomes")
        if not isinstance(raw_outcomes, list) or len(raw_outcomes) != len(calls):
            raise DG14TransportError("MCP batch returned an invalid outcome list")
        outcomes: list[McpBatchOutcome] = []
        for expected_ordinal, raw in enumerate(raw_outcomes):
            if not isinstance(raw, dict) or raw.get("ordinal") != expected_ordinal:
                raise DG14TransportError("MCP batch outcome identity drifted")
            succeeded = raw.get("ok") is True
            structured = raw.get("structured")
            if succeeded and not isinstance(structured, dict):
                raise DG14TransportError("MCP batch success lacks structured content")
            error_code = raw.get("error_code")
            if not succeeded and not isinstance(error_code, str):
                raise DG14TransportError("MCP batch failure lacks an error code")
            outcomes.append(
                McpBatchOutcome(
                    ordinal=expected_ordinal,
                    status="SUCCEEDED" if succeeded else "FAILED",
                    structured=(
                        cast(dict[str, object], structured) if succeeded else None
                    ),
                    error_code=None if succeeded else cast(str, error_code),
                )
            )
        return tuple(outcomes)


async def _execute_many(
    clients: Mapping[McpProfile, Any],
    calls: Sequence[Mapping[str, object]],
    max_concurrency: int,
) -> list[dict[str, object]]:
    semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(raw: Mapping[str, object]) -> dict[str, object]:
        ordinal = raw.get("ordinal")
        profile = raw.get("profile")
        tool_name = raw.get("tool_name")
        arguments = raw.get("arguments")
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or profile not in _PROFILES
            or not isinstance(tool_name, str)
            or not isinstance(arguments, dict)
            or tool_name not in _REQUIRED_TOOLS[profile]
        ):
            return {
                "ordinal": int(ordinal) if isinstance(ordinal, int) else -1,
                "ok": False,
                "error_code": "INVALID_CALL_ENVELOPE",
            }
        try:
            async with semaphore:
                result = await clients[profile].call_tool(tool_name, arguments)
        except (OSError, RuntimeError, TimeoutError):
            return {"ordinal": ordinal, "ok": False, "error_code": "MCP_CALL_FAILED"}
        if result.is_error is True or not isinstance(result.structured_content, dict):
            return {"ordinal": ordinal, "ok": False, "error_code": "MCP_TOOL_ERROR"}
        return {"ordinal": ordinal, "ok": True, "structured": result.structured_content}

    return list(await asyncio.gather(*(execute(call) for call in calls)))


async def _bridge() -> None:
    try:
        from mcp import (  # type: ignore[import-not-found]
            Client,
            MCPError,
            StdioServerParameters,
            stdio_client,
        )
    except ImportError as exc:
        raise DG14TransportError(
            "the configured MCP client environment lacks mcp"
        ) from exc

    initialize = _bridge_request(
        await asyncio.to_thread(sys.stdin.buffer.readline), "initialize"
    )
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
            missing = sorted(
                _REQUIRED_TOOLS[profile] - {item.name for item in catalog.tools}
            )
            if missing:
                raise DG14TransportError(
                    f"profile {profile} is missing DG15 MCP tools: {missing}"
                )
            if client.protocol_version != MCP_PROTOCOL_MODE:
                raise DG14TransportError(
                    f"profile {profile} negotiated unexpected protocol"
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
            raw = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not raw:
                return
            request = _bridge_request(raw)
            request_id = _bridge_request_id(request)
            kind = request.get("kind")
            if kind == "close":
                closing_request_id = request_id
                break
            if kind != "call_many":
                _bridge_error(request_id, "UNKNOWN_REQUEST_KIND")
                continue
            calls = request.get("calls")
            concurrency = request.get("max_concurrency")
            if (
                not isinstance(calls, list)
                or not 1 <= len(calls) <= _MAX_BATCH_ITEMS
                or concurrency not in _ALLOWED_CONCURRENCY
                or any(not isinstance(call, dict) for call in calls)
            ):
                _bridge_error(request_id, "INVALID_BATCH_ENVELOPE")
                continue
            outcomes = await _execute_many(
                clients,
                cast(list[Mapping[str, object]], calls),
                concurrency,
            )
            if [outcome["ordinal"] for outcome in outcomes] != list(range(len(calls))):
                _bridge_error(request_id, "BATCH_IDENTITY_DRIFT")
                continue
            _bridge_reply(request_id, {"outcomes": outcomes})

    if closing_request_id is not None:
        _bridge_reply(closing_request_id, {"kind": "closed"})


def _main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bridge", action="store_true")
    args = parser.parse_args()
    if not args.bridge:
        raise SystemExit("mcp_stdio is an internal DG15 dispatcher")
    asyncio.run(_bridge())


if __name__ == "__main__":
    _main()
