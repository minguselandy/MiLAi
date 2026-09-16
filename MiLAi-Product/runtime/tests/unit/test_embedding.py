from __future__ import annotations

import hashlib
import math
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import UUID

import pytest

from milai.adapters import (
    BoundedEmbeddingProvider,
    DeterministicHashEmbedding,
    EmbeddingUnavailable,
    OnnxSentenceTransformerEmbedding,
    SentenceTransformerEmbedding,
)
from milai.adapters.embedding import ProjectionIdentity, _dense_projection
from milai.application.retrieval import RetrievalService
from milai.domain import RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import GatedBatch, ProjectionState


def test_deterministic_embedding_is_normalized_and_input_sensitive() -> None:
    adapter = DeterministicHashEmbedding()
    first = adapter.embed("Python runtime 3.12")
    replay = adapter.embed("Python runtime 3.12")
    different = adapter.embed("PostgreSQL canonical state")

    assert first == replay
    assert first != different
    assert len(first) == adapter.dimensions == 16
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)
    assert adapter.embed("") == [0.0] * 16


def test_deterministic_embedding_embed_many_preserves_order() -> None:
    adapter = DeterministicHashEmbedding()
    texts = ["Python runtime 3.12", "PostgreSQL canonical state"]

    assert adapter.embed_many(texts, batch_size=2) == [adapter.embed(text) for text in texts]


def test_projection_identity_is_stable_and_complete() -> None:
    provider = DeterministicHashEmbedding()
    assert len(provider.identity.key) == 64
    assert provider.identity.projection_dimensions == 16
    assert provider.identity.normalization == "l2"


def test_dense_projection_supports_128d_and_keeps_normalization() -> None:
    identity = ProjectionIdentity(
        provider="onnx_sentence_transformer",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        source_dimensions=384,
        projection_dimensions=128,
        normalization="mean-pool-l2+dense-projection-l2",
        code_version="projection-128/v1",
    )
    projected = _dense_projection([1.0, *([0.0] * 383)], identity, 128)

    assert len(projected) == 128
    assert math.isclose(math.sqrt(sum(value * value for value in projected)), 1.0)


def test_legacy_projection_code_version_is_read_as_semantic_identity() -> None:
    legacy = ProjectionIdentity(
        provider="onnx_sentence_transformer",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        source_dimensions=384,
        projection_dimensions=128,
        normalization="mean-pool-l2+dense-projection-l2",
        code_version="dg11-1",
    )
    semantic = ProjectionIdentity(
        provider="onnx_sentence_transformer",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        source_dimensions=384,
        projection_dimensions=128,
        normalization="mean-pool-l2+dense-projection-l2",
        code_version="projection-128/v1",
    )

    assert legacy.code_version == "projection-128/v1"
    assert legacy.key == semantic.key


def test_semantic_projection_rebuild_preserves_legacy_vector_bytes() -> None:
    identity = ProjectionIdentity(
        provider="onnx_sentence_transformer",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        source_dimensions=384,
        projection_dimensions=128,
        normalization="mean-pool-l2+dense-projection-l2",
        code_version="projection-128/v1",
    )
    source = [1.0, *([0.0] * 383)]
    legacy_seed = hashlib.sha256(
        b"onnx_sentence_transformer|sentence-transformers/all-MiniLM-L6-v2|"
        b"384|128|mean-pool-l2+dense-projection-l2|dg11-1"
    ).hexdigest()

    projected = _dense_projection(source, identity, 128)

    expected = [0.0] * 128
    base = legacy_seed.encode() + (0).to_bytes(4, "big")
    for block_start in range(0, 128, 32):
        digest = hashlib.sha256(
            base + (b"" if block_start == 0 else block_start.to_bytes(2, "big"))
        ).digest()
        for offset in range(32):
            expected[block_start + offset] = (digest[offset] - 127.5) / 127.5
    norm = math.sqrt(sum(value * value for value in expected))
    expected = [value / norm for value in expected]

    assert projected == expected


def test_mixed_projection_identity_uses_a_distinct_projection_key() -> None:
    current = ProjectionIdentity(
        provider="onnx_sentence_transformer",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        source_dimensions=384,
        projection_dimensions=128,
        normalization="mean-pool-l2+dense-projection-l2",
        code_version="projection-128/v1",
    )
    next_version = ProjectionIdentity(
        provider=current.provider,
        model_id=current.model_id,
        source_dimensions=current.source_dimensions,
        projection_dimensions=current.projection_dimensions,
        normalization=current.normalization,
        code_version="projection-128/v2",
    )

    assert next_version.key != current.key


def test_bounded_provider_warmup_reports_ready_without_payload() -> None:
    provider = BoundedEmbeddingProvider(DeterministicHashEmbedding(), max_concurrency=2)
    result = provider.warmup()
    assert result.state == "READY"
    assert result.error_code is None
    assert result.duration_ms >= 0
    assert provider.runtime_state == "READY"


def test_bounded_provider_chunks_native_batches_and_counts_payload_free_usage() -> None:
    class NativeBatchProvider:
        identity = DeterministicHashEmbedding.identity
        dimensions = 16

        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def embed(self, text: str) -> list[float]:
            raise AssertionError("scalar fallback must not run")

        def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
            assert batch_size == len(texts)
            self.calls.append(tuple(texts))
            return [[float(index)] * 16 for index, _text in enumerate(texts)]

    source = NativeBatchProvider()
    provider = BoundedEmbeddingProvider(source, max_concurrency=1)

    vectors = provider.embed_many(["a", "b", "c"], batch_size=2)

    assert source.calls == [("a", "b"), ("c",)]
    assert len(vectors) == 3
    assert provider.usage().logical_items == 3
    assert provider.usage().inference_batches == 2
    assert provider.usage().failed_batches == 0


def test_onnx_embedding_embed_many_uses_one_tensor_batch(tmp_path: Path) -> None:
    numpy = pytest.importorskip("numpy")
    model_path = tmp_path / "model"
    (model_path / "onnx").mkdir(parents=True)
    (model_path / "onnx" / "model.onnx").touch()
    (model_path / "tokenizer.json").write_text("{}")
    provider = OnnxSentenceTransformerEmbedding(
        model_path,
        model_id="synthetic-onnx",
        source_dimensions=2,
    )

    class Encoding:
        def __init__(self, ids: list[int]) -> None:
            self.ids = ids
            self.attention_mask = [1] * len(ids)
            self.type_ids = [0] * len(ids)

    class Tokenizer:
        def encode_batch(self, texts: list[str]) -> list[Encoding]:
            assert texts == ["short", "long"]
            return [Encoding([1]), Encoding([2, 3])]

        def token_to_id(self, token: str) -> int:
            assert token == "[PAD]"
            return 0

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, outputs: list[str], inputs: dict[str, object]):
            self.calls += 1
            assert outputs == ["last_hidden_state"]
            assert inputs["input_ids"].shape == (2, 2)  # type: ignore[union-attr]
            return [
                numpy.asarray(
                    [
                        [[1.0, 0.0], [0.0, 0.0]],
                        [[0.0, 1.0], [0.0, 1.0]],
                    ],
                    dtype="float32",
                )
            ]

    session = Session()
    provider._tokenizer = Tokenizer()  # type: ignore[assignment]
    provider._session = session
    provider._numpy = numpy

    vectors = provider.embed_many(["short", "long"], batch_size=2)

    assert session.calls == 1
    assert len(vectors) == 2
    assert all(len(vector) == 16 for vector in vectors)


def test_bounded_provider_warmup_failure_is_degraded_and_retry_can_recover() -> None:
    class FlakyProvider:
        identity = DeterministicHashEmbedding.identity
        dimensions = 16

        def __init__(self) -> None:
            self.fail = True

        def embed(self, text: str) -> list[float]:
            if self.fail:
                raise EmbeddingUnavailable("synthetic outage")
            return [0.0] * 16

    source = FlakyProvider()
    provider = BoundedEmbeddingProvider(source, max_concurrency=1)
    result = provider.warmup()
    assert result.state == "DEGRADED"
    assert result.error_code == "EMBEDDING_UNAVAILABLE"
    source.fail = False
    assert provider.embed("retry") == [0.0] * 16
    assert provider.runtime_state == "READY"


def test_bounded_provider_enforces_configured_inference_concurrency() -> None:
    class BlockingProvider:
        identity = DeterministicHashEmbedding.identity
        dimensions = 16

        def __init__(self) -> None:
            self.entered = 0
            self.maximum = 0
            self.guard = Lock()
            self.started = Event()
            self.release = Event()

        def embed(self, text: str) -> list[float]:
            with self.guard:
                self.entered += 1
                self.maximum = max(self.maximum, self.entered)
                if self.entered == 2:
                    self.started.set()
            self.release.wait(timeout=2)
            with self.guard:
                self.entered -= 1
            return [0.0] * 16

    source = BlockingProvider()
    provider = BoundedEmbeddingProvider(source, max_concurrency=2)
    threads = [Thread(target=provider.embed, args=(str(index),)) for index in range(4)]
    for thread in threads:
        thread.start()
    assert source.started.wait(timeout=2)
    assert source.maximum == 2
    source.release.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert source.maximum == 2


def test_sentence_transformer_requires_explicit_local_model(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingUnavailable, match="model path"):
        SentenceTransformerEmbedding(
            tmp_path / "missing",
            model_id="example-model",
            source_dimensions=384,
        )


class _UnavailableProvider:
    identity = DeterministicHashEmbedding.identity
    dimensions = 16

    def embed(self, text: str) -> list[float]:
        raise EmbeddingUnavailable("injected provider outage")


class _Repository:
    def __init__(self) -> None:
        self.fts_attempted = False
        self.vector_attempted = False
        self.exact_attempted = False
        self.recent_attempted = False

    def projection_state(self, context: SessionContext) -> ProjectionState:
        return ProjectionState(0, 0, 0, False, False)

    def search_fts(self, *args: Any, **kwargs: Any) -> list[Any]:
        self.fts_attempted = True
        return []

    def exact_candidates(self, *args: Any, **kwargs: Any) -> list[Any]:
        self.exact_attempted = True
        return []

    def search_vector(self, *args: Any, **kwargs: Any) -> list[Any]:
        self.vector_attempted = True
        return []

    def recent_canonical_candidates(self, *args: Any, **kwargs: Any) -> list[Any]:
        self.recent_attempted = True
        return []

    def gate_and_hydrate(self, *args: Any, **kwargs: Any) -> GatedBatch:
        return GatedBatch(ProjectionState(0, 0, 0, False, False), [], [])

    def record_trace(self, *args: Any, **kwargs: Any) -> UUID:
        return UUID("11111111-1111-4111-8111-111111111111")


def test_real_provider_outage_only_degrades_vector_recall() -> None:
    repository = _Repository()
    service = RetrievalService(repository, embedding=_UnavailableProvider())  # type: ignore[arg-type]
    result = service.retrieve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ),
        RetrievalRequest(route="L1", query="synthetic", consistency="EVENTUAL"),
        "request-embedding-outage",
    )
    assert result.status_code == 200
    assert repository.fts_attempted is True
    assert repository.vector_attempted is False
    assert repository.exact_attempted is True
    assert repository.recent_attempted is False
    assert result.body["degraded_components"] == ["vector"]
    assert result.body["abstained"] is True
    assert result.body["fallback_used"] is False
    stage_metrics = result.body["stage_metrics"]
    assert stage_metrics["durations_ms"]["query_total_ms"] >= 0
    assert stage_metrics["counts"]["query_embedding_ms"] == 1
    assert "synthetic" not in str(stage_metrics)


def test_canonical_required_still_generates_all_hybrid_candidate_lanes() -> None:
    repository = _Repository()
    service = RetrievalService(repository)  # type: ignore[arg-type]
    result = service.retrieve(
        SessionContext(
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ),
        RetrievalRequest(
            route="L1",
            query="synthetic",
            consistency="CANONICAL_REQUIRED",
        ),
        "request-canonical-hybrid",
    )
    assert result.status_code == 200
    assert repository.exact_attempted is True
    assert repository.fts_attempted is True
    assert repository.vector_attempted is True
    assert repository.recent_attempted is False
    assert result.body["fallback_used"] is False
