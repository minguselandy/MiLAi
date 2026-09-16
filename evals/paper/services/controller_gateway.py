"""Authenticated loopback gateway with exact usage receipts for paper controllers."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import signal
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

from evals.paper.identity import sha256_file
from evals.paper.provider import MODEL_ID

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_UPSTREAM = "http://127.0.0.1:7860"
DEFAULT_VLLM_IDENTITY = ROOT / "docs/reports/DG-10-vllm-local-identity-2026-08-20.json"
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_COMPLETION_TOKENS = 8192
_NATIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,255}")


class ControllerGatewayError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise ControllerGatewayError("controller gateway identity is write-once")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _api_key(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ControllerGatewayError("controller API key file is unavailable")
    if path.stat().st_mode & 0o077:
        raise ControllerGatewayError(
            "controller API key file permissions are too broad"
        )
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ControllerGatewayError("controller API key is too short")
    return value


def _strict_upstream(value: str) -> str:
    normalized = value.rstrip("/").removesuffix("/v1")
    if normalized != DEFAULT_UPSTREAM:
        raise ControllerGatewayError("controller upstream is not the frozen vLLM")
    return normalized


def _nonnegative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ControllerGatewayError(f"controller response has invalid {name}")
    return value


@dataclass(slots=True)
class ControllerUsage:
    request_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    upstream_latency_ms: float = 0.0
    receipts: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_success(
        self,
        *,
        request_raw: bytes,
        response_raw: bytes,
        response: dict[str, Any],
        latency_ms: float,
    ) -> None:
        usage = response.get("usage")
        choices = response.get("choices")
        native_id = response.get("id")
        if (
            not isinstance(usage, dict)
            or not isinstance(choices, list)
            or not choices
            or not isinstance(native_id, str)
            or _NATIVE_ID.fullmatch(native_id) is None
            or response.get("model") != MODEL_ID
        ):
            raise ControllerGatewayError("controller response envelope drifted")
        prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"), "prompt_tokens")
        completion_tokens = _nonnegative_int(
            usage.get("completion_tokens"), "completion_tokens"
        )
        total_tokens = _nonnegative_int(usage.get("total_tokens"), "total_tokens")
        if total_tokens != prompt_tokens + completion_tokens:
            raise ControllerGatewayError("controller usage total is inconsistent")
        finish_reasons = []
        for choice in choices:
            if not isinstance(choice, dict) or not isinstance(
                choice.get("finish_reason"), str
            ):
                raise ControllerGatewayError("controller finish reason is absent")
            finish_reasons.append(choice["finish_reason"])
        receipt = {
            "completion_tokens": completion_tokens,
            "finish_reasons": finish_reasons,
            "native_id": native_id,
            "prompt_tokens": prompt_tokens,
            "request_bytes": len(request_raw),
            "request_sha256": hashlib.sha256(request_raw).hexdigest(),
            "response_bytes": len(response_raw),
            "response_sha256": hashlib.sha256(response_raw).hexdigest(),
            "total_tokens": total_tokens,
            "upstream_latency_ms": round(latency_ms, 3),
        }
        with self._lock:
            self.request_count += 1
            self.successful_count += 1
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.total_tokens += total_tokens
            self.request_bytes += len(request_raw)
            self.response_bytes += len(response_raw)
            self.upstream_latency_ms += latency_ms
            self.receipts.append(receipt)

    def add_failure(self, *, request_raw: bytes, error: str, latency_ms: float) -> None:
        with self._lock:
            self.request_count += 1
            self.failed_count += 1
            self.request_bytes += len(request_raw)
            self.upstream_latency_ms += latency_ms
            self.receipts.append(
                {
                    "error": error,
                    "request_bytes": len(request_raw),
                    "request_sha256": hashlib.sha256(request_raw).hexdigest(),
                    "upstream_latency_ms": round(latency_ms, 3),
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "completion_tokens": self.completion_tokens,
                "failed_count": self.failed_count,
                "prompt_tokens": self.prompt_tokens,
                "request_bytes": self.request_bytes,
                "request_count": self.request_count,
                "response_bytes": self.response_bytes,
                "successful_count": self.successful_count,
                "total_tokens": self.total_tokens,
                "upstream_latency_ms": round(self.upstream_latency_ms, 3),
                "receipts": list(self.receipts),
            }


class ControllerGateway:
    def __init__(self, *, api_key: str, upstream: str) -> None:
        self.api_key = api_key
        self.upstream = _strict_upstream(upstream)
        self.usage = ControllerUsage()

    def authorized(self, header: str | None) -> bool:
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header.removeprefix("Bearer "), self.api_key)

    def _validate_request(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ControllerGatewayError("controller request must be an object")
        if payload.get("model") != MODEL_ID:
            raise ControllerGatewayError("controller request model identity drifted")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ControllerGatewayError("controller messages are absent")
        if payload.get("stream", False) is not False:
            raise ControllerGatewayError("streaming controller calls are unsupported")
        max_tokens = payload.get("max_tokens")
        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or not 1 <= max_tokens <= MAX_COMPLETION_TOKENS
        ):
            raise ControllerGatewayError(
                "controller max_tokens is outside the frozen cap"
            )
        return payload

    def complete(self, raw: bytes) -> bytes:
        payload = self._validate_request(json.loads(raw))
        started = time.perf_counter()
        request = urllib.request.Request(
            self.upstream + "/v1/chat/completions",
            data=_canonical(payload),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=1200) as response:
                response_raw = bytes(response.read(MAX_RESPONSE_BYTES + 1))
                status = int(response.status)
            if status != 200 or len(response_raw) > MAX_RESPONSE_BYTES:
                raise ControllerGatewayError(
                    "controller upstream returned non-200 or oversized response"
                )
            response_value = json.loads(response_raw)
            if not isinstance(response_value, dict):
                raise ControllerGatewayError("controller response must be an object")
            latency_ms = (time.perf_counter() - started) * 1000
            self.usage.add_success(
                request_raw=raw,
                response_raw=response_raw,
                response=response_value,
                latency_ms=latency_ms,
            )
            return response_raw
        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
            ControllerGatewayError,
        ) as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self.usage.add_failure(
                request_raw=raw,
                error=type(exc).__name__,
                latency_ms=latency_ms,
            )
            raise ControllerGatewayError("controller upstream request failed") from exc


class _Handler(BaseHTTPRequestHandler):
    gateway: ClassVar[ControllerGateway]
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _write_raw(self, status: HTTPStatus, raw: bytes) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def _write(self, status: HTTPStatus, value: object) -> None:
        self._write_raw(status, _canonical(value))

    def _error(self, status: HTTPStatus, message: str, code: str) -> None:
        self._write(
            status,
            {
                "error": {
                    "code": code,
                    "message": message,
                    "type": "invalid_request_error",
                }
            },
        )

    def _authorized(self) -> bool:
        if self.gateway.authorized(self.headers.get("Authorization")):
            return True
        self._error(HTTPStatus.UNAUTHORIZED, "authentication required", "UNAUTHORIZED")
        return False

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path == "/health":
            self._write(HTTPStatus.OK, {"status": "READY"})
        elif self.path == "/metrics":
            self._write(HTTPStatus.OK, self.gateway.usage.snapshot())
        elif self.path == "/v1/models":
            self._write(
                HTTPStatus.OK,
                {
                    "data": [
                        {
                            "created": 0,
                            "id": MODEL_ID,
                            "object": "model",
                            "owned_by": "frozen-local-vllm",
                        }
                    ],
                    "object": "list",
                },
            )
        else:
            self._error(HTTPStatus.NOT_FOUND, "route not found", "NOT_FOUND")

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if self.path != "/v1/chat/completions":
            self._error(HTTPStatus.NOT_FOUND, "route not found", "NOT_FOUND")
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "request size is invalid",
                "REQUEST_SIZE_INVALID",
            )
            return
        raw = self.rfile.read(length)
        try:
            response_raw = self.gateway.complete(raw)
        except (json.JSONDecodeError, ControllerGatewayError) as exc:
            self._error(
                HTTPStatus.BAD_GATEWAY,
                str(exc),
                "CONTROLLER_REQUEST_FAILED",
            )
            return
        self._write_raw(HTTPStatus.OK, response_raw)


def _identity(*, upstream: str, vllm_identity: Path) -> dict[str, Any]:
    return {
        "api": {
            "authentication": "BEARER_TOKEN_FROM_MODE_0600_FILE_NOT_ARCHIVED",
            "base_url": "LOOPBACK_PORT_FROM_CLI",
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "max_request_bytes": MAX_REQUEST_BYTES,
            "model_id": MODEL_ID,
            "streaming": False,
        },
        "created_at": time.time(),
        "gateway_source_sha256": sha256_file(Path(__file__)),
        "schema": "milai.dg11.paper-controller-gateway-identity.v1",
        "status": "READY",
        "upstream": _strict_upstream(upstream),
        "vllm_identity_path": str(vllm_identity.resolve()),
        "vllm_identity_sha256": sha256_file(vllm_identity),
    }


def run(
    *,
    host: str,
    port: int,
    api_key_file: Path,
    identity_output: Path,
    upstream: str,
    vllm_identity: Path,
) -> None:
    if host != "127.0.0.1" or not 1024 <= port <= 65535:
        raise ControllerGatewayError(
            "controller gateway must use an unprivileged loopback port"
        )
    if not vllm_identity.is_file():
        raise ControllerGatewayError("frozen vLLM identity is unavailable")
    gateway = ControllerGateway(api_key=_api_key(api_key_file), upstream=upstream)
    _Handler.gateway = gateway
    server = HTTPServer((host, port), _Handler)
    _atomic_json_once(
        identity_output,
        _identity(upstream=upstream, vllm_identity=vllm_identity),
    )

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--identity-output", type=Path, required=True)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    parser.add_argument("--vllm-identity", type=Path, default=DEFAULT_VLLM_IDENTITY)
    args = parser.parse_args()
    run(
        host=args.host,
        port=args.port,
        api_key_file=args.api_key_file.absolute(),
        identity_output=args.identity_output.resolve(),
        upstream=args.upstream,
        vllm_identity=args.vllm_identity.resolve(),
    )


if __name__ == "__main__":
    main()
