"""Explicitly configured HTTP models; responses can rank data, never supply authority."""

from __future__ import annotations

import http.client
import json
import math
import socket
from threading import BoundedSemaphore, Timer
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from milai.adapters.embedding import (
    EmbeddingUnavailable,
    ProjectionIdentity,
    project_embedding_vector,
)
from milai.adapters.reranker import RerankerExecution, RerankerUnavailable, _memory_text


def validate_model_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or any(char.isspace() for char in value)
    ):
        raise ValueError("model URL must be an explicit HTTP(S) endpoint without credentials")
    _ = parsed.port
    return value


class ModelHTTPError(RuntimeError):
    pass


def _interrupt_socket(connection: socket.socket) -> None:
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # The request may already have closed its dedicated socket.


def _post_json(endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """No redirects, proxy environment, retries, or response bodies in errors."""
    parsed = urlsplit(validate_model_url(endpoint))
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > 4 * 1024 * 1024:
        raise ModelHTTPError("model request exceeds byte limit")
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(str(parsed.hostname), parsed.port, timeout=timeout)
    deadline = perf_counter() + timeout
    timer: Timer | None = None
    try:
        connection.connect()
        assert connection.sock is not None
        remaining = deadline - perf_counter()
        if remaining <= 0:
            raise ModelHTTPError("model request deadline exceeded")
        # Socket inactivity alone cannot bound trickled headers or response bytes.
        timer = Timer(remaining, _interrupt_socket, args=(connection.sock,))
        timer.daemon = True
        timer.start()
        connection.request("POST", parsed.path, body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ModelHTTPError("model HTTP request failed")
        raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ModelHTTPError("model response exceeds byte limit")
        result = json.loads(raw)
        if perf_counter() >= deadline:
            raise ModelHTTPError("model request deadline exceeded")
        if not isinstance(result, dict) or result.get("error"):
            raise ModelHTTPError("model response is invalid")
        return result
    except (OSError, http.client.HTTPException, ValueError, RecursionError) as exc:
        raise ModelHTTPError("model transport or JSON response failed") from exc
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def _number(value: object) -> float:
    if type(value) not in {int, float}:
        raise ValueError("model score must be numeric")
    result = float(value)  # type: ignore[arg-type]
    if not math.isfinite(result):
        raise ValueError("model score must be finite")
    return result


def _indexed_rows(value: object, count: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("model result cardinality mismatch")
    indexed: dict[int, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("model result is not an object")
        index = row.get("index")
        if type(index) is not int or not 0 <= index < count or index in indexed:
            raise ValueError("model result index is invalid")
        indexed[index] = row
    return [indexed[index] for index in range(count)]


class HTTPEmbedding:
    """OpenAI-shaped dense embeddings, projected to the existing 16/128d index."""

    def __init__(
        self, endpoint: str, *, model_id: str, revision: str,
        source_dimensions: int, projection_dimensions: int, timeout: float = 10.0,
    ) -> None:
        self.endpoint = validate_model_url(endpoint)
        if not revision or not 1 <= source_dimensions <= 8192:
            raise ValueError("HTTP embedding requires a revision and source dimensions")
        if projection_dimensions not in {16, 128} or not 0 < timeout <= 60:
            raise ValueError("invalid HTTP embedding bounds")
        self.timeout = timeout
        self.dimensions = projection_dimensions
        self.identity = ProjectionIdentity(
            provider="http_embeddings", model_id=model_id,
            source_dimensions=source_dimensions, projection_dimensions=projection_dimensions,
            normalization="source-l2+dense-projection-l2",
            code_version=f"http-projection/v1:{revision}",
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text], 1)[0]

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        if not 1 <= batch_size <= 1024:
            raise ValueError("embedding batch size must be between 1 and 1024")
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), batch_size):
                batch = texts[start:start + batch_size]
                result = _post_json(self.endpoint, {
                    "model": self.identity.model_id, "input": batch, "encoding_format": "float",
                }, self.timeout)
                if result.get("model") != self.identity.model_id:
                    raise ValueError("embedding model mismatch")
                for row in _indexed_rows(result.get("data"), len(batch)):
                    raw = row.get("embedding")
                    if not isinstance(raw, list) or len(raw) != self.identity.source_dimensions:
                        raise ValueError("embedding dimensions mismatch")
                    source = [_number(value) for value in raw]
                    norm = math.hypot(*source)
                    if not math.isfinite(norm) or norm == 0:
                        raise ValueError("embedding norm is invalid")
                    projected = project_embedding_vector(
                        [value / norm for value in source], self.identity,
                    )
                    if not math.isclose(math.hypot(*projected), 1.0):
                        raise ValueError("projected embedding norm is invalid")
                    vectors.append(projected)
        except (ModelHTTPError, ValueError, OverflowError) as exc:
            raise EmbeddingUnavailable("HTTP embedding failed validation or transport") from exc
        return vectors


class HTTPReranker:
    """Score only existing canonical-gated candidates; ignore echoed remote documents."""

    def __init__(
        self, endpoint: str, *, model_id: str, revision: str,
        timeout: float = 10.0, max_concurrency: int = 4,
    ) -> None:
        self.endpoint = validate_model_url(endpoint)
        if not 0 < timeout <= 60 or not 1 <= max_concurrency <= 64 or not revision:
            raise ValueError("invalid HTTP reranker bounds")
        self.timeout = timeout
        self._semaphore = BoundedSemaphore(max_concurrency)
        self.identity = {"provider": "http_reranker", "model_id": model_id, "revision": revision}

    def rerank(
        self, query: str, candidates: list[dict[str, Any]], *, limit: int, pool_size: int,
    ) -> RerankerExecution:
        if not 0 < limit <= pool_size <= 20:
            raise ValueError("reranker pool must cover the positive limit and not exceed 20")
        pool = candidates[:pool_size]
        if not pool:
            return RerankerExecution([], {**self.identity, "pairs": 0, "duration_ms": 0.0})
        started = perf_counter()
        if not self._semaphore.acquire(timeout=self.timeout):
            raise RerankerUnavailable("HTTP reranker concurrency limit reached")
        try:
            remaining = self.timeout - (perf_counter() - started)
            if remaining <= 0:
                raise ModelHTTPError("model queue deadline exceeded")
            result = _post_json(self.endpoint, {
                "model": self.identity["model_id"], "query": query,
                "documents": [_memory_text(candidate) for candidate in pool],
            }, remaining)
            if result.get("model") != self.identity["model_id"]:
                raise ValueError("reranker model mismatch")
            scores = [_number(row.get("relevance_score"))
                      for row in _indexed_rows(result.get("results"), len(pool))]
        except (ModelHTTPError, ValueError, OverflowError) as exc:
            raise RerankerUnavailable("HTTP reranker failed validation or transport") from exc
        finally:
            self._semaphore.release()
        metadata = {
            **self.identity, "pairs": len(pool),
            "duration_ms": round((perf_counter() - started) * 1000, 3),
        }
        indices = sorted(range(len(pool)), key=lambda index: (-scores[index], index))[:limit]
        selected = [{**pool[index], "reranker": {
            **metadata, "score": round(scores[index], 8), "source_rank": index + 1,
        }} for index in indices]
        return RerankerExecution(selected, metadata)
