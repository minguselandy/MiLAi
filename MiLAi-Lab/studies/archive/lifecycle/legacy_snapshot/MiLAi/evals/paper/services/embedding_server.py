"""OpenAI-compatible loopback server for the frozen DG11 ONNX embedder."""

from __future__ import annotations

import argparse
import array
import base64
import hmac
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar, cast

import milai
from milai.config import load_settings
from milai.operations.cli import _load_environment_file
from milai.workers.main import _embedding_provider
from tokenizers import Tokenizer

from evals.paper.identity import sha256_file, source_inventory

ROOT = Path(__file__).resolve().parents[3]
MODEL_ALIAS = str(ROOT / "runtime/var/models/all-MiniLM-L6-v2")
DEFAULT_ENV = ROOT / "runtime/.env"
DEFAULT_RUNTIME_WHEEL = (
    ROOT / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl"
)
EXPECTED_RUNTIME_WHEEL_SHA256 = (
    "7fc0b1ab3babed5d99daca1ef92a7160ba0de729a34ccc1b1a10c5c82641e25a"
)
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_BATCH_ITEMS = 4096
MAX_INPUT_CHARS = 2_000_000


class EmbeddingServerError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise EmbeddingServerError("embedding server identity is write-once")
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
        raise EmbeddingServerError("embedding API key file is unavailable")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise EmbeddingServerError("embedding API key file permissions are too broad")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise EmbeddingServerError("embedding API key is too short")
    return value


def _runtime_origin() -> str:
    origin = Path(str(milai.__file__)).resolve()
    if not origin.is_relative_to(Path(sys.prefix).resolve()):
        raise EmbeddingServerError("embedding server imported outside frozen wheel env")
    return str(origin)


@dataclass(slots=True)
class Usage:
    request_count: int = 0
    item_count: int = 0
    input_chars: int = 0
    prompt_tokens: int = 0
    inference_ms: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(
        self,
        *,
        items: int,
        input_chars: int,
        prompt_tokens: int,
        inference_ms: float,
    ) -> None:
        with self._lock:
            self.request_count += 1
            self.item_count += items
            self.input_chars += input_chars
            self.prompt_tokens += prompt_tokens
            self.inference_ms += inference_ms

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "inference_ms": round(self.inference_ms, 3),
                "input_chars": self.input_chars,
                "item_count": self.item_count,
                "prompt_tokens": self.prompt_tokens,
                "request_count": self.request_count,
            }


class EmbeddingService:
    def __init__(self, *, provider: Any, tokenizer: Tokenizer, api_key: str) -> None:
        self.provider = provider
        self.tokenizer = tokenizer
        self.api_key = api_key
        self.usage = Usage()

    def authorized(self, header: str | None) -> bool:
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header.removeprefix("Bearer "), self.api_key)

    def embed(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("model") != MODEL_ALIAS:
            raise EmbeddingServerError("embedding request model identity drifted")
        raw_input = payload.get("input")
        if isinstance(raw_input, str):
            inputs = [raw_input]
        elif isinstance(raw_input, list) and all(
            isinstance(item, str) for item in raw_input
        ):
            inputs = cast(list[str], raw_input)
        else:
            raise EmbeddingServerError(
                "embedding input must be a string or string list"
            )
        if not inputs or len(inputs) > MAX_BATCH_ITEMS:
            raise EmbeddingServerError("embedding batch size is invalid")
        if any(not item.strip() or len(item) > MAX_INPUT_CHARS for item in inputs):
            raise EmbeddingServerError("embedding input text is invalid")
        encoding_format = payload.get("encoding_format", "float")
        if encoding_format not in {None, "float", "base64"}:
            raise EmbeddingServerError("embedding encoding format is unsupported")
        started = time.perf_counter()
        vectors = [self.provider.embed(text) for text in inputs]
        inference_ms = (time.perf_counter() - started) * 1000
        if any(len(vector) != self.provider.dimensions for vector in vectors):
            raise EmbeddingServerError("embedding dimension drifted")
        prompt_tokens = sum(
            min(len(self.tokenizer.encode(text).ids), 256) for text in inputs
        )
        self.usage.add(
            items=len(inputs),
            input_chars=sum(len(item) for item in inputs),
            prompt_tokens=prompt_tokens,
            inference_ms=inference_ms,
        )
        encoded_vectors: list[list[float] | str]
        if encoding_format == "base64":
            encoded_vectors = [
                base64.b64encode(array.array("f", vector).tobytes()).decode("ascii")
                for vector in vectors
            ]
        else:
            encoded_vectors = vectors
        return {
            "data": [
                {"embedding": vector, "index": index, "object": "embedding"}
                for index, vector in enumerate(encoded_vectors)
            ],
            "model": MODEL_ALIAS,
            "object": "list",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "total_tokens": prompt_tokens,
            },
        }


class _Handler(BaseHTTPRequestHandler):
    service: ClassVar[EmbeddingService]
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _write(self, status: HTTPStatus, value: object) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

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
        if self.service.authorized(self.headers.get("Authorization")):
            return True
        self._error(HTTPStatus.UNAUTHORIZED, "authentication required", "UNAUTHORIZED")
        return False

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path == "/health":
            self._write(HTTPStatus.OK, {"status": "READY"})
        elif self.path == "/v1/models":
            self._write(
                HTTPStatus.OK,
                {
                    "data": [
                        {
                            "created": 0,
                            "id": MODEL_ALIAS,
                            "object": "model",
                            "owned_by": "milai-dg11-paper",
                        }
                    ],
                    "object": "list",
                },
            )
        elif self.path == "/metrics":
            self._write(HTTPStatus.OK, self.service.usage.snapshot())
        else:
            self._error(HTTPStatus.NOT_FOUND, "route not found", "NOT_FOUND")

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if self.path != "/v1/embeddings":
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
            payload = json.loads(raw)
            result = self.service.embed(payload)
        except (json.JSONDecodeError, EmbeddingServerError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), "INVALID_EMBEDDING_REQUEST")
            return
        self._write(HTTPStatus.OK, result)


def _identity(
    *,
    env_file: Path,
    runtime_wheel: Path,
    provider: Any,
    warmup: Any,
) -> dict[str, Any]:
    model_path = Path(str(load_settings().embedding_model_path)).resolve()
    identity = provider.identity
    return {
        "api": {
            "authentication": "BEARER_TOKEN_FROM_MODE_0600_FILE_NOT_ARCHIVED",
            "base_url": "LOOPBACK_PORT_FROM_CLI",
            "max_batch_items": MAX_BATCH_ITEMS,
            "max_request_bytes": MAX_REQUEST_BYTES,
            "model_alias": MODEL_ALIAS,
            "response_encodings": ["float", "base64-float32-native-endian"],
        },
        "created_at": time.time(),
        "env_sha256": sha256_file(env_file),
        "model_inventory": source_inventory(model_path),
        "provider": {
            "code_version": identity.code_version,
            "dimensions": provider.dimensions,
            "identity_key": identity.key,
            "model_id": identity.model_id,
            "normalization": identity.normalization,
            "projection_dimensions": identity.projection_dimensions,
            "provider": identity.provider,
            "source_dimensions": identity.source_dimensions,
        },
        "python_prefix": str(Path(sys.prefix).resolve()),
        "runtime_origin": _runtime_origin(),
        "runtime_wheel_sha256": sha256_file(runtime_wheel),
        "schema": "milai.dg11.paper-embedding-service-identity.v1",
        "server_source_sha256": sha256_file(Path(__file__)),
        "status": "READY",
        "warmup": {
            "duration_ms": warmup.duration_ms,
            "error_code": warmup.error_code,
            "state": warmup.state,
        },
    }


def run(
    *,
    host: str,
    port: int,
    env_file: Path,
    runtime_wheel: Path,
    api_key_file: Path,
    identity_output: Path,
) -> None:
    if host != "127.0.0.1" or not 1024 <= port <= 65535:
        raise EmbeddingServerError(
            "embedding server must use an unprivileged loopback port"
        )
    if (
        not runtime_wheel.is_file()
        or sha256_file(runtime_wheel) != EXPECTED_RUNTIME_WHEEL_SHA256
    ):
        raise EmbeddingServerError("frozen Runtime wheel identity drifted")
    _load_environment_file(env_file.resolve())
    settings = load_settings()
    if (
        settings.embedding_provider != "onnx_sentence_transformer"
        or settings.embedding_model_id != "sentence-transformers/all-MiniLM-L6-v2"
        or settings.embedding_source_dimensions != 384
        or settings.embedding_projection_dimensions != 128
        or settings.embedding_model_path is None
    ):
        raise EmbeddingServerError("frozen DG11 embedding configuration drifted")
    provider = _embedding_provider(settings)
    warmup = provider.warmup()
    if warmup.state != "READY" or provider.dimensions != 128:
        raise EmbeddingServerError("frozen DG11 embedding provider did not warm up")
    tokenizer = Tokenizer.from_file(
        str(settings.embedding_model_path / "tokenizer.json")
    )
    service = EmbeddingService(
        provider=provider,
        tokenizer=tokenizer,
        api_key=_api_key(api_key_file),
    )
    _Handler.service = service
    server = HTTPServer((host, port), _Handler)
    _atomic_json_once(
        identity_output,
        _identity(
            env_file=env_file,
            runtime_wheel=runtime_wheel,
            provider=provider,
            warmup=warmup,
        ),
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
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--runtime-wheel", type=Path, default=DEFAULT_RUNTIME_WHEEL)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--identity-output", type=Path, required=True)
    args = parser.parse_args()
    run(
        host=args.host,
        port=args.port,
        env_file=args.env_file.resolve(),
        runtime_wheel=args.runtime_wheel.resolve(),
        api_key_file=args.api_key_file.absolute(),
        identity_output=args.identity_output.resolve(),
    )


if __name__ == "__main__":
    main()
