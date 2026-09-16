from __future__ import annotations

import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from milai.adapters import BoundedEmbeddingProvider, EmbeddingUnavailable
from milai.adapters import http_models as models
from milai.adapters.http_models import HTTPEmbedding, HTTPReranker, ModelHTTPError
from milai.adapters.reranker import RerankerUnavailable
from milai.api.app import _embedding_provider, _reranker_provider
from milai.config.settings import SettingsError, load_settings, load_worker_settings
from milai.workers.main import _embedding_provider as worker_embedding


def embedding(revision: str = "r1") -> HTTPEmbedding:
    return HTTPEmbedding("http://127.0.0.1:7861/v1/embeddings", model_id="bge-m3",
                         revision=revision, source_dimensions=3, projection_dimensions=128)


def response() -> dict[str, Any]:
    return {"model": "bge-m3", "data": [
        {"index": 1, "embedding": [0, 1, 0]}, {"index": 0, "embedding": [1, 0, 0]},
    ]}


def test_embedding_batch_order_projection_and_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def post(endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        calls.append(payload)
        return response()

    monkeypatch.setattr(models, "_post_json", post)
    vectors = embedding().embed_many(["你好", "世界", "你好", "世界"], 2)
    assert len(calls) == 2
    assert calls[0] == {"model": "bge-m3", "input": ["你好", "世界"], "encoding_format": "float"}
    assert vectors[0] == vectors[2] and vectors[0] != vectors[1]
    assert all(len(v) == 128 and math.isclose(math.hypot(*v), 1) for v in vectors)
    assert embedding().identity.key != embedding("r2").identity.key
    assert embedding().embed_many([], 2) == []


@pytest.mark.parametrize("bad", [
    {"model": "wrong", "data": []},
    {"model": "bge-m3", "data": [{"index": 0, "embedding": [1, 0, 0]}]},
    {"model": "bge-m3", "data": [{"index": 0, "embedding": [1, 0, 0]}] * 2},
    {"model": "bge-m3", "data": [None, None]},
    *[{"model": "bge-m3", "data": [
        {"index": 0, "embedding": value}, {"index": 1, "embedding": [1, 0, 0]},
    ]} for value in ([1, 2], [0, 0, 0], [True, 0, 0], [float("nan"), 0, 0],
                    [float("inf"), 0, 0], ["1", 0, 0])],
    *[{"model": "bge-m3", "data": [
        {"index": index, "embedding": [1, 0, 0]}, {"index": 1, "embedding": [1, 0, 0]},
    ]} for index in (-1, 2, True, "0")],
])
def test_embedding_rejects_untrusted_results(monkeypatch: pytest.MonkeyPatch, bad: object) -> None:
    monkeypatch.setattr(models, "_post_json", lambda *args: bad)
    with pytest.raises(EmbeddingUnavailable, match="validation or transport"):
        embedding().embed_many(["a", "b"], 2)


def reranker() -> HTTPReranker:
    return HTTPReranker("http://127.0.0.1:7961/v1/rerank", model_id="bge-reranker", revision="r1")


def test_reranker_maps_only_original_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [{"claim_id": str(i), "payload": {"memory_text": str(i)}} for i in range(4)]

    def post(endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        assert payload["documents"] == ["0", "1", "2", "3"]
        return {"model": "bge-reranker", "results": [
            {"index": i, "relevance_score": score, "document": {"claim_id": "forged"}}
            for i, score in [(3, .1), (2, .9), (1, .9), (0, .1)]
        ]}

    monkeypatch.setattr(models, "_post_json", post)
    result = reranker().rerank("q", candidates, limit=3, pool_size=4)
    assert [item["claim_id"] for item in result.results] == ["1", "2", "0"]
    assert result.results[0]["payload"] == candidates[1]["payload"]
    assert result.results[0]["reranker"]["source_rank"] == 2
    assert all("reranker" not in item for item in candidates)


@pytest.mark.parametrize("rows", [
    [], [{"index": 1, "relevance_score": .2}],
    [{"index": True, "relevance_score": .2}],
    *[[{"index": 0, "relevance_score": score}] for score in [None, True, "0.1", float("inf")]],
])
def test_reranker_rejects_invalid_scores(monkeypatch: pytest.MonkeyPatch, rows: object) -> None:
    monkeypatch.setattr(
        models, "_post_json", lambda *args: {"model": "bge-reranker", "results": rows},
    )
    with pytest.raises(RerankerUnavailable):
        reranker().rerank("q", [{"memory_text": "a"}], limit=1, pool_size=1)


def test_transport_failure_has_no_retry_or_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def post(*args: object) -> dict[str, Any]:
        calls.append(1)
        raise ModelHTTPError("private model response")

    monkeypatch.setattr(models, "_post_json", post)
    with pytest.raises(EmbeddingUnavailable) as error:
        embedding().embed("private content")
    assert "private" not in str(error.value)
    with pytest.raises(RerankerUnavailable):
        reranker().rerank("q", [{"memory_text": "a"}], limit=1, pool_size=1)
    assert len(calls) == 2


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:secret@host/v1",
                                 "http://host/v1?key=secret", "http://host/v1#frag", "http://host"])
def test_reject_unsafe_endpoint(url: str) -> None:
    with pytest.raises(ValueError):
        models.validate_model_url(url)


@pytest.mark.parametrize("status,raw", [(302, b'{}'), (500, b'secret'), (200, b'not JSON'),
                                        (200, b'[]'), (200, b'{"error":"secret"}'),
                                        (200, b'x' * (16 * 1024 * 1024 + 1))])
def test_http_boundary_no_redirect_and_bounded_body(
    monkeypatch: pytest.MonkeyPatch, status: int, raw: bytes,
) -> None:
    closed = []

    class Response:
        def read(self, size: int) -> bytes:
            assert size == 16 * 1024 * 1024 + 1
            return raw

    class Connection:
        sock = object()

        def __init__(self, *args: object, **kwargs: object) -> None:
            assert kwargs["timeout"] == 2

        def connect(self) -> None:
            pass

        def request(self, *args: object) -> None:
            assert args[0] == "POST"
            assert json.loads(args[2]) == {"input": "你好"}

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(Response, "status", status, raising=False)
    monkeypatch.setattr(models.http.client, "HTTPConnection", Connection)
    with pytest.raises(ModelHTTPError) as error:
        models._post_json("http://127.0.0.1/v1", {"input": "你好"}, 2)
    assert "secret" not in str(error.value) and closed == [True]


def environment(tmp_path: Path) -> dict[str, str]:
    return {
        "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
        "MILAI_STEWARD_DATABASE_URL": "postgresql://milai_steward:secret@127.0.0.1:15432/milai",
        "MILAI_WORKER_DATABASE_URL": "postgresql://milai_worker:secret@127.0.0.1:15432/milai",
        "MILAI_BLOB_ROOT": str(tmp_path),
        "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "MILAI_API_TOKEN": "test-token-with-at-least-32-characters",
        "MILAI_CAUSAL_TOKEN_SECRET": "test-causal-secret-with-at-least-32-characters",
        "MILAI_EMBEDDING_PROVIDER": "http_embeddings",
        "MILAI_EMBEDDING_ENDPOINT": "http://127.0.0.1:7861/v1/embeddings",
        "MILAI_EMBEDDING_MODEL_ID": "bge-m3",
        "MILAI_EMBEDDING_MODEL_REVISION": "r1",
        "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "1024",
        "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "128",
        "MILAI_RETRIEVAL_RERANKER_PROVIDER": "http_reranker",
        "MILAI_RETRIEVAL_RERANKER_ENDPOINT": "http://127.0.0.1:7961/v1/rerank",
        "MILAI_RETRIEVAL_RERANKER_MODEL_ID": "bge-reranker",
        "MILAI_RETRIEVAL_RERANKER_REVISION": "r1",
    }


def test_api_worker_use_same_remote_identity(tmp_path: Path) -> None:
    env = environment(tmp_path)
    settings = load_settings(env)
    assert (_embedding_provider(settings).identity
            == worker_embedding(load_worker_settings(env)).identity)
    assert isinstance(_reranker_provider(settings), HTTPReranker)


@pytest.mark.parametrize("missing", ["MILAI_EMBEDDING_ENDPOINT", "MILAI_EMBEDDING_MODEL_REVISION"])
def test_remote_config_requires_identity(tmp_path: Path, missing: str) -> None:
    env = environment(tmp_path)
    env.pop(missing)
    for loader in (load_settings, load_worker_settings):
        with pytest.raises(SettingsError):
            loader(env)


@pytest.mark.parametrize("headers_first", [True, False])
def test_slow_http_response_is_interrupted_by_total_deadline(headers_first: bool) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            try:
                if headers_first:
                    self.send_response(200)
                    self.end_headers()
                    for byte in b'{"padding":"' + b'x' * 100 + b'"}':
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(.01)
                else:
                    for byte in b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}':
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(.01)
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        with pytest.raises(ModelHTTPError):
            models._post_json(f"http://127.0.0.1:{server.server_port}/v1", {}, .1)
        assert time.perf_counter() - started < .8
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_embedding_queue_is_bounded_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = Event(), Event()

    def post(*args: object) -> dict[str, Any]:
        entered.set()
        assert release.wait(2)
        return {"model": "bge-m3", "data": [{"index": 0, "embedding": [1, 0, 0]}]}

    monkeypatch.setattr(models, "_post_json", post)
    provider = BoundedEmbeddingProvider(embedding(), max_concurrency=1, queue_timeout_seconds=.05)
    results = []
    thread = Thread(target=lambda: results.append(provider.embed("a")))
    thread.start()
    try:
        assert entered.wait(1)
        with pytest.raises(EmbeddingUnavailable, match="concurrency"):
            provider.embed("b")
    finally:
        release.set()
        thread.join(2)
    assert len(results) == 1
    assert len(provider.embed("c")) == 128
