from __future__ import annotations

import json
import socket
import stat
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_PROTOCOL_VERSION = "2025-11-25"
_SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"2024-11-05", "2025-03-26", "2025-06-18", _PROTOCOL_VERSION}
)
_DEFAULT_MAX_FRAME_BYTES = 65_536


class McpUnixClientError(RuntimeError):
    """A bounded MCP-over-UDS transport or protocol failure."""

    def __init__(self, code: str) -> None:
        if not code or any(character.isspace() for character in code):
            raise ValueError("MCP error code must be a non-empty token")
        super().__init__(code)
        self.code = code


class McpUnixClient:
    """Persistent synchronous MCP client for a trusted profile-scoped UDS.

    The broker owns Runtime credentials and launches the installed MCP server. This
    client only holds the profile-scoped Unix socket capability and speaks the
    newline-delimited MCP JSON-RPC transport used by stdio servers.
    """

    def __init__(
        self,
        socket_path: Path,
        *,
        connect_timeout_seconds: float = 2.0,
        request_timeout_seconds: float = 10.0,
        max_frame_bytes: int = _DEFAULT_MAX_FRAME_BYTES,
    ) -> None:
        if not socket_path.is_absolute():
            raise ValueError("MCP socket path must be absolute")
        if connect_timeout_seconds <= 0 or request_timeout_seconds <= 0:
            raise ValueError("MCP timeouts must be positive")
        if not 1_024 <= max_frame_bytes <= 2 * 1024 * 1024:
            raise ValueError("MCP frame boundary is invalid")
        self.socket_path = socket_path
        self.connect_timeout_seconds = connect_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.max_frame_bytes = max_frame_bytes
        self._socket: socket.socket | None = None
        self._buffer = bytearray()
        self._sequence = 0
        self._lock = threading.Lock()
        self._active_deadline: float | None = None

    def _bounded_timeout(self, ceiling: float) -> float:
        if self._active_deadline is None:
            return ceiling
        remaining = self._active_deadline - time.monotonic()
        if remaining <= 0:
            self._close_locked()
            raise McpUnixClientError("MCP_DEADLINE_EXCEEDED")
        return min(ceiling, remaining)

    def _deadline_error(self, fallback: str) -> McpUnixClientError:
        if self._active_deadline is not None and time.monotonic() >= self._active_deadline:
            return McpUnixClientError("MCP_DEADLINE_EXCEEDED")
        return McpUnixClientError(fallback)

    def _close_locked(self) -> None:
        connection = self._socket
        self._socket = None
        self._buffer.clear()
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _validate_socket(self) -> None:
        try:
            current = self.socket_path.lstat()
        except OSError as exc:
            raise McpUnixClientError("MCP_SOCKET_UNAVAILABLE") from exc
        if (
            not stat.S_ISSOCK(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or stat.S_IMODE(current.st_mode) != 0o600
        ):
            raise McpUnixClientError("MCP_SOCKET_IDENTITY_REJECTED")

    @staticmethod
    def _encode(message: Mapping[str, Any]) -> bytes:
        return (
            json.dumps(
                dict(message),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )

    def _send_locked(self, message: Mapping[str, Any]) -> None:
        if self._socket is None:  # pragma: no cover - internal invariant
            raise McpUnixClientError("MCP_SESSION_UNAVAILABLE")
        encoded = self._encode(message)
        if len(encoded) > self.max_frame_bytes:
            raise McpUnixClientError("MCP_REQUEST_FRAME_TOO_LARGE")
        try:
            self._socket.settimeout(self._bounded_timeout(self.request_timeout_seconds))
            self._socket.sendall(encoded)
        except (OSError, TimeoutError) as exc:
            self._close_locked()
            raise self._deadline_error("MCP_SEND_FAILED") from exc

    def _receive_locked(self) -> dict[str, Any]:
        if self._socket is None:  # pragma: no cover - internal invariant
            raise McpUnixClientError("MCP_SESSION_UNAVAILABLE")
        while b"\n" not in self._buffer:
            try:
                self._socket.settimeout(self._bounded_timeout(self.request_timeout_seconds))
                block = self._socket.recv(min(65_536, self.max_frame_bytes + 1))
            except (OSError, TimeoutError) as exc:
                self._close_locked()
                raise self._deadline_error("MCP_RECEIVE_FAILED") from exc
            if not block:
                self._close_locked()
                raise McpUnixClientError("MCP_SESSION_CLOSED")
            self._buffer.extend(block)
            if len(self._buffer) > self.max_frame_bytes:
                self._close_locked()
                raise McpUnixClientError("MCP_RESPONSE_FRAME_TOO_LARGE")
        raw, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._close_locked()
            raise McpUnixClientError("MCP_RESPONSE_JSON_REJECTED") from exc
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            self._close_locked()
            raise McpUnixClientError("MCP_RESPONSE_CONTRACT_REJECTED")
        return value

    def _request_locked(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        request_id = self._sequence
        self._send_locked(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        for _ in range(32):
            response = self._receive_locked()
            if response.get("id") != request_id:
                if "method" in response and "id" not in response:
                    continue
                self._close_locked()
                raise McpUnixClientError("MCP_RESPONSE_ID_MISMATCH")
            if "error" in response:
                self._close_locked()
                raise McpUnixClientError("MCP_REMOTE_ERROR")
            result = response.get("result")
            if not isinstance(result, dict):
                self._close_locked()
                raise McpUnixClientError("MCP_RESULT_CONTRACT_REJECTED")
            return result
        self._close_locked()
        raise McpUnixClientError("MCP_NOTIFICATION_LIMIT_EXCEEDED")

    def _connect_locked(self) -> None:
        if self._socket is not None:
            return
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self._bounded_timeout(self.connect_timeout_seconds))
        try:
            connection.connect(str(self.socket_path))
        except (OSError, TimeoutError) as exc:
            connection.close()
            raise self._deadline_error("MCP_CONNECT_FAILED") from exc
        connection.settimeout(self._bounded_timeout(self.request_timeout_seconds))
        self._socket = connection
        try:
            initialized = self._request_locked(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "milai-host-prefetch",
                        "version": "0.1.0",
                    },
                },
            )
            if initialized.get("protocolVersion") not in _SUPPORTED_PROTOCOL_VERSIONS:
                raise McpUnixClientError("MCP_PROTOCOL_VERSION_REJECTED")
            self._send_locked({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            self._close_locked()
            raise

    def _call_tool_locked(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        result = self._request_locked(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )
        if result.get("isError") is True:
            raise McpUnixClientError("MCP_TOOL_ERROR")
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise McpUnixClientError("MCP_STRUCTURED_RESULT_ABSENT")
        return dict(structured)

    def recall(self, query: str) -> dict[str, Any]:
        if not query.strip() or len(query) > 2_000:
            raise ValueError("MCP recall query must contain 1-2000 characters")
        with self._lock:
            self._connect_locked()
            structured = self._call_tool_locked("milai_recall", {"query": query})
            if (
                not isinstance(structured.get("status"), str)
                or not isinstance(structured.get("items"), list)
                or not isinstance(structured.get("open_issue_ids"), list)
            ):
                raise McpUnixClientError("MCP_RECALL_CONTRACT_REJECTED")
            return structured

    def resolve_memory(
        self, query: str, *, previous_context_id: str | None = None
    ) -> dict[str, Any]:
        """Invoke the task-free contract with an optional explicit reuse locator."""
        if not query.strip() or len(query) > 2_000:
            raise ValueError("MCP memory resolve query must contain 1-2000 characters")
        arguments = {"query": query}
        if previous_context_id is not None:
            arguments["previous_context_id"] = previous_context_id
        started = time.perf_counter()
        with self._lock:
            self._connect_locked()
            structured = self._call_tool_locked("milai_memory_resolve", arguments)
            if (
                structured.get("schema_version") != "access-outcome-v0.1"
                or structured.get("status")
                not in {
                    "HIT",
                    "PARTIAL",
                    "CONTESTED",
                    "ABSENT",
                    "ABSTAINED",
                    "DENIED",
                    "UNAVAILABLE",
                }
                or not isinstance(structured.get("items"), list)
                or not isinstance(structured.get("open_issue_ids"), list)
                or structured.get("availability")
                not in {"AVAILABLE", "DEGRADED", "UNAVAILABLE"}
            ):
                raise McpUnixClientError("MCP_MEMORY_RESOLVE_CONTRACT_REJECTED")
            structured["host_transport"] = {
                "uds_roundtrip_ms": round((time.perf_counter() - started) * 1_000, 3)
            }
            return structured

    def list_tools(self) -> tuple[str, ...]:
        """Return the exact profile-scoped catalog over the initialized session."""
        with self._lock:
            self._connect_locked()
            result = self._request_locked("tools/list", {})
            tools = result.get("tools")
            if not isinstance(tools, list):
                raise McpUnixClientError("MCP_TOOL_CATALOG_REJECTED")
            names: list[str] = []
            for tool in tools:
                name = tool.get("name") if isinstance(tool, Mapping) else None
                if not isinstance(name, str) or not name or name in names:
                    raise McpUnixClientError("MCP_TOOL_CATALOG_REJECTED")
                names.append(name)
            return tuple(names)

    def prepare_memory_context(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke the host-only composite boundary over the same persistent UDS session."""
        if not isinstance(payload.get("query"), str):
            raise ValueError("MCP prepare_context query must be a string")
        budget = payload.get("budget")
        deadline_ms = budget.get("memory_deadline_ms") if isinstance(budget, Mapping) else None
        if (
            isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or not 25 <= deadline_ms <= 10_000
        ):
            raise ValueError("MCP prepare_context requires a valid memory deadline")
        started = time.perf_counter()
        with self._lock:
            self._active_deadline = time.monotonic() + deadline_ms / 1_000
            try:
                self._connect_locked()
                structured = self._call_tool_locked("milai_prepare_context", payload)
                if time.monotonic() >= self._active_deadline:
                    self._close_locked()
                    raise McpUnixClientError("MCP_DEADLINE_EXCEEDED")
                capsule = structured.get("context_capsule")
                token = structured.get("validation_token")
                if (
                    structured.get("status")
                    not in {
                        "READY",
                        "UNCHANGED",
                        "NEEDS_RECOVERY",
                        "DEGRADED",
                        "ABSTAIN",
                        "BUDGET_EXHAUSTED",
                    }
                    or not isinstance(structured.get("route"), str)
                    or not isinstance(structured.get("context_delta"), dict)
                    or not isinstance(structured.get("relevant_open_issue_closure"), list)
                    or (capsule is not None and not isinstance(capsule, dict))
                    or (token is not None and not isinstance(token, str))
                ):
                    raise McpUnixClientError("MCP_PREPARE_CONTEXT_CONTRACT_REJECTED")
                timing = structured.get("timing")
                structured["timing"] = {
                    **(dict(timing) if isinstance(timing, Mapping) else {}),
                    "uds_roundtrip_ms": round((time.perf_counter() - started) * 1_000, 3),
                }
                return structured
            finally:
                self._active_deadline = None
                if self._socket is not None:
                    self._socket.settimeout(self.request_timeout_seconds)

    def prepare_context(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Backward-compatible alias for the server-side memory context operation."""
        return self.prepare_memory_context(payload)

    def capture_evidence(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Use a submitter-scoped socket to capture Evidence, never canonical state."""
        required = {
            "operation_id",
            "source_type",
            "source_ref",
            "subject_id",
            "observed_at",
            "content",
            "permission_snapshot",
            "confirmation",
            "retention_state",
            "data_classification",
        }
        if set(payload) != required or payload.get("confirmation") != "CAPTURE":
            raise ValueError("submitter Evidence payload contract failed")
        with self._lock:
            self._connect_locked()
            return self._call_tool_locked("milai_evidence_capture", payload)

    def create_proposal(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Use a submitter-scoped socket to create a reviewable Proposal only."""
        if set(payload) != {"operation_id", "proposal", "confirmation"}:
            raise ValueError("submitter Proposal payload contract failed")
        if payload.get("confirmation") != "SUBMIT" or not isinstance(
            payload.get("proposal"), Mapping
        ):
            raise ValueError("submitter Proposal confirmation or body failed")
        with self._lock:
            self._connect_locked()
            return self._call_tool_locked("milai_proposal_create", payload)

    def __enter__(self) -> McpUnixClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
