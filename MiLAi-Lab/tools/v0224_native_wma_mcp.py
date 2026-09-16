"""One principal's public persistent MCP session for harness ordinary Notes."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from pathlib import Path

import httpx

URL = "http://127.0.0.1:27338/mcp"
PROTOCOL = "2025-03-26"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
FIELDS = {
    "milai_note_add": (
        {"content", "operation_id"},
        {"content", "format", "tags", "operation_id", "source_refs", "observed_at"},
    ),
    "milai_note_get": (
        {"memory_id"},
        {"memory_id", "version", "offset", "length", "source_offset", "source_limit"},
    ),
    "milai_note_operation_get": ({"operation_id"}, {"operation_id"}),
}


def require(ok, why):
    if not ok:
        raise ValueError(why)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    value = json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")),
    )
    encoded(value)  # Also refuse finite-looking exponent overflow (1e999).
    return value


def rpc_message(raw, content_type, expected_id):
    if "text/event-stream" in content_type:
        messages, data = [], []
        for line in [*raw.decode("utf-8").replace("\r\n", "\n").split("\n"), ""]:
            if not line:
                if data:
                    messages.append(strict_json("\n".join(data)))
                    data = []
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        matches = [m for m in messages if isinstance(m, dict) and m.get("id") == expected_id]
        require(len(matches) == 1, "ONE_MATCHING_SSE_JSONRPC_REPLY_REQUIRED")
        result = matches[0]
    else:
        require("application/json" in content_type, "PUBLIC_MCP_JSON_OR_SSE_REQUIRED")
        result = strict_json(raw)
    require(
        type(result) is dict
        and result.get("jsonrpc") == "2.0"
        and type(result.get("id")) is int
        and result["id"] == expected_id,
        "EXACT_JSONRPC_REPLY_ID_REQUIRED",
    )
    require("error" not in result and "result" in result, "PUBLIC_MCP_RPC_ERROR")
    return result["result"]


class NoteMCP:
    def __init__(self, credentials_path, directory, max_http):
        require(type(max_http) is int and max_http >= 4, "HTTP_CAP_INCLUDES_HANDSHAKE_AND_DELETE")
        path = Path(credentials_path)
        require(path.is_absolute() and path.resolve() == path, "CANONICAL_CREDENTIAL_FILE_REQUIRED")
        info = path.stat()
        require(
            stat.S_ISREG(info.st_mode) and info.st_mode & 0o077 == 0,
            "PRIVATE_CREDENTIAL_FILE_REQUIRED",
        )
        require(info.st_size <= 65536, "BOUNDED_CREDENTIAL_FILE_REQUIRED")
        value = strict_json(path.read_bytes())
        require(
            set(value) == {"mcpServers"}
            and type(value["mcpServers"]) is dict
            and len(value["mcpServers"]) == 1,
            "ONE_PUBLIC_ISSUED_PRINCIPAL_CONFIG_REQUIRED",
        )
        server = next(iter(value["mcpServers"].values()))
        require(
            type(server) is dict
            and set(server) == {"type", "url", "headers"}
            and server["type"] == "http"
            and server["url"] == URL
            and type(server["headers"]) is dict
            and set(server["headers"]) == {"Authorization"},
            "FIXED_PUBLIC_NOTE_ENDPOINT_AND_CREDENTIAL_REQUIRED",
        )
        authorization = server["headers"]["Authorization"]
        require(
            type(authorization) is str
            and authorization.startswith("Bearer ")
            and len(authorization) > 7
            and not any(c.isspace() for c in authorization[7:]),
            "ONE_PUBLIC_BEARER_CREDENTIAL_REQUIRED",
        )
        self._token = authorization[7:]
        self._headers = {
            "Authorization": authorization,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        self._owner = (os.getpid(), threading.get_ident())
        self._session = None
        self._initialized = self._closed = self._init_attempted = False
        self._next_id = 1
        self.http_requests, self.max_http = 0, max_http
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        require(directory.resolve() == directory, "CANONICAL_RAW_DIRECTORY_REQUIRED")
        self._log = (directory / "mcp-http.jsonl").open("x", encoding="utf-8")
        self._client = httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(60, connect=10, pool=10),
            transport=httpx.HTTPTransport(retries=0, trust_env=False),
        )

    def _record(self, row):
        # No headers are logged. Defensive replacement prevents a server echo from
        # placing credential material in the ordinary response/error record.
        text = encoded(row).decode().replace(self._token, "[REDACTED_BEARER]")
        self._log.write(text + "\n")
        self._log.flush()

    def _active(self):
        require(
            not self._closed and self._owner == (os.getpid(), threading.get_ident()),
            "SAME_ACTIVE_PRINCIPAL_HOST_REQUIRED",
        )

    def _request(self, method, body=None, *, cleanup=False):
        self._active()
        require(
            self.http_requests < self.max_http - (0 if cleanup else 1), "REAL_HTTP_CAP_EXCEEDED"
        )
        request = None if body is None else encoded(body)
        ordinal = self.http_requests + 1
        self._record(
            {"event": "HTTP_INTENT", "ordinal": ordinal, "method": method, "url": URL, "body": body}
        )
        self.http_requests = ordinal
        started = time.monotonic_ns()
        row = {"event": "HTTP_OBSERVED", "ordinal": ordinal, "method": method}
        primary = None
        try:
            with self._client.stream(
                method, URL, content=request, headers=self._headers
            ) as response:
                chunks, length = [], 0
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    require(length <= MAX_RESPONSE_BYTES, "BOUNDED_PUBLIC_MCP_RESPONSE_REQUIRED")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                row.update(
                    status=response.status_code,
                    body=raw.decode("utf-8"),
                    response_sha256=hashlib.sha256(raw).hexdigest(),
                )
                require(200 <= response.status_code < 300, "PUBLIC_MCP_HTTP_STATUS_ERROR")
                return response.status_code, response.headers, raw
        except BaseException as exc:
            primary = exc
            row["exception_type"] = type(exc).__name__
            raise
        finally:
            row["elapsed_ns"] = time.monotonic_ns() - started
            try:
                self._record(row)
            except BaseException as secondary:
                if primary is None:
                    raise
                primary.add_note("SECONDARY_MCP_HTTP_RECORD_FAILURE: " + type(secondary).__name__)

    def _initialize(self):
        if self._initialized:
            return
        require(not self._init_attempted, "FAILED_INITIALIZATION_CANNOT_RETRY")
        self._init_attempted = True
        ident = self._next_id
        self._next_id += 1
        _, headers, raw = self._request(
            "POST",
            {
                "jsonrpc": "2.0",
                "id": ident,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "native-wma-note-host", "version": "1"},
                },
            },
        )
        self._session = headers.get("mcp-session-id")
        if self._session:
            self._headers.update(
                {"Mcp-Session-Id": self._session, "MCP-Protocol-Version": PROTOCOL}
            )
        result = rpc_message(raw, headers.get("content-type", ""), ident)
        require(result.get("protocolVersion") == PROTOCOL, "EXACT_PUBLIC_MCP_PROTOCOL_REQUIRED")
        require(
            type(self._session) is str and bool(self._session), "PERSISTENT_MCP_SESSION_REQUIRED"
        )
        self._headers.update({"Mcp-Session-Id": self._session, "MCP-Protocol-Version": PROTOCOL})
        self._request("POST", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    def call(self, name, args):
        self._active()
        require(name in FIELDS and type(args) is dict, "ONLY_PUBLIC_NOTE_TOOLS_REQUIRED")
        required, allowed = FIELDS[name]
        require(required <= set(args) <= allowed, "NO_SCOPE_OR_IDENTITY_PARAMETERS_ALLOWED")
        body = strict_json(encoded(args))
        self._initialize()
        ident = self._next_id
        self._next_id += 1
        _, headers, raw = self._request(
            "POST",
            {
                "jsonrpc": "2.0",
                "id": ident,
                "method": "tools/call",
                "params": {"name": name, "arguments": body},
            },
        )
        result = rpc_message(raw, headers.get("content-type", ""), ident)
        require(type(result) is dict and not result.get("isError"), "PUBLIC_NOTE_TOOL_ERROR")
        if "structuredContent" in result:
            value = result["structuredContent"]
        else:
            texts = [row["text"] for row in result.get("content", []) if row.get("type") == "text"]
            require(len(texts) == 1, "ONE_PUBLIC_NOTE_RESULT_REQUIRED")
            value = strict_json(texts[0])
        require(type(value) is dict, "PUBLIC_NOTE_RESULT_DICT_REQUIRED")
        self._record(
            {"event": "NOTE_TOOL_RESULT", "name": name, "arguments": body, "result": value}
        )
        return strict_json(encoded(value))

    def close(self):
        if self._closed:
            return
        self._active()
        primary = None
        try:
            if self._session is not None:
                self._request("DELETE", cleanup=True)
        except BaseException as exc:
            primary = exc
            raise
        finally:
            self._closed = True
            try:
                self._client.close()
            except BaseException as exc:
                if primary is None:
                    primary = exc
                    raise
                primary.add_note("SECONDARY_MCP_CLIENT_CLOSE_FAILURE: " + type(exc).__name__)
            finally:
                self._headers.clear()
                self._token = ""
                try:
                    self._log.close()
                except BaseException as exc:
                    if primary is None:
                        raise
                    primary.add_note("SECONDARY_MCP_LOG_CLOSE_FAILURE: " + type(exc).__name__)
