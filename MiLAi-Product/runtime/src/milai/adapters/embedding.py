from __future__ import annotations

import hashlib
import importlib
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, RLock
from time import perf_counter
from typing import Any, Protocol

_DIMENSIONS = 16
_TOKEN_PATTERN = re.compile(r"[\w.-]+", re.UNICODE)
PROJECTION_128_V1 = "projection-128/v1"
LEGACY_PROJECTION_CODE_VERSIONS = {"dg11-1": PROJECTION_128_V1}


def semantic_projection_code_version(value: str) -> str:
    return LEGACY_PROJECTION_CODE_VERSIONS.get(value, value)


class EmbeddingUnavailable(RuntimeError):
    """Raised when an explicitly configured real provider cannot produce a vector."""


@dataclass(frozen=True, slots=True)
class ProjectionIdentity:
    provider: str
    model_id: str
    source_dimensions: int
    projection_dimensions: int
    normalization: str
    code_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "code_version",
            semantic_projection_code_version(self.code_version),
        )

    @property
    def key(self) -> str:
        canonical = "|".join(
            (
                self.provider,
                self.model_id,
                str(self.source_dimensions),
                str(self.projection_dimensions),
                self.normalization,
                self.code_version,
            )
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class EmbeddingProvider(Protocol):
    dimensions: int
    identity: ProjectionIdentity

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingWarmupResult:
    state: str
    duration_ms: float
    provider: str
    model_id: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    logical_items: int
    inference_batches: int
    failed_batches: int
    duration_ms: float


class BoundedEmbeddingProvider:
    """Bound concurrent inference and expose payload-free warmup state."""

    def __init__(
        self, provider: EmbeddingProvider, *, max_concurrency: int,
        queue_timeout_seconds: float | None = None,
    ) -> None:
        if not 1 <= max_concurrency <= 64:
            raise ValueError("embedding max_concurrency must be between 1 and 64")
        self._provider = provider
        if queue_timeout_seconds is not None and not 0 < queue_timeout_seconds <= 60:
            raise ValueError("embedding queue timeout must be between 0 and 60 seconds")
        self._queue_timeout_seconds = queue_timeout_seconds
        self._semaphore = BoundedSemaphore(max_concurrency)
        self._state_lock = RLock()
        self._runtime_state = "COLD"
        self._last_error_code: str | None = None
        self._logical_items = 0
        self._inference_batches = 0
        self._failed_batches = 0
        self._duration_ms = 0.0
        self.dimensions = provider.dimensions
        self.identity = provider.identity

    @property
    def runtime_state(self) -> str:
        with self._state_lock:
            return self._runtime_state

    @property
    def last_error_code(self) -> str | None:
        with self._state_lock:
            return self._last_error_code

    @contextmanager
    def _slot(self) -> Iterator[None]:
        if not self._semaphore.acquire(timeout=self._queue_timeout_seconds):
            self._set_state("DEGRADED", "EMBEDDING_UNAVAILABLE")
            raise EmbeddingUnavailable("embedding concurrency limit reached")
        try:
            yield
        finally:
            self._semaphore.release()

    def embed(self, text: str) -> list[float]:
        started = perf_counter()
        with self._slot():
            self._record_attempt(1)
            try:
                result = self._provider.embed(text)
            except EmbeddingUnavailable:
                self._record_failure()
                self._set_state("DEGRADED", "EMBEDDING_UNAVAILABLE")
                raise
            finally:
                self._record_duration(started)
            self._set_state("READY", None)
            return result

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        size = _validated_batch_size(batch_size)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), size):
            batch = texts[start : start + size]
            started = perf_counter()
            with self._slot():
                self._record_attempt(len(batch))
                try:
                    method = getattr(self._provider, "embed_many", None)
                    if method is None:
                        result = [self._provider.embed(text) for text in batch]
                    else:
                        result = method(batch, len(batch))
                except EmbeddingUnavailable:
                    self._record_failure()
                    self._set_state("DEGRADED", "EMBEDDING_UNAVAILABLE")
                    raise
                finally:
                    self._record_duration(started)
            if len(result) != len(batch):
                self._record_failure()
                self._set_state("DEGRADED", "EMBEDDING_BATCH_MISMATCH")
                raise EmbeddingUnavailable("embedding batch result count changed")
            vectors.extend(result)
        if texts:
            self._set_state("READY", None)
        return vectors

    def usage(self) -> EmbeddingUsage:
        with self._state_lock:
            return EmbeddingUsage(
                logical_items=self._logical_items,
                inference_batches=self._inference_batches,
                failed_batches=self._failed_batches,
                duration_ms=round(self._duration_ms, 3),
            )

    def warmup(self, text: str = "milai synthetic embedding warmup") -> EmbeddingWarmupResult:
        started = perf_counter()
        try:
            self.embed(text)
        except EmbeddingUnavailable:
            state = "DEGRADED"
        else:
            state = "READY"
        return EmbeddingWarmupResult(
            state=state,
            duration_ms=round((perf_counter() - started) * 1_000, 3),
            provider=self.identity.provider,
            model_id=self.identity.model_id,
            error_code=self.last_error_code,
        )

    def _set_state(self, state: str, error_code: str | None) -> None:
        with self._state_lock:
            self._runtime_state = state
            self._last_error_code = error_code

    def _record_attempt(self, logical_items: int) -> None:
        with self._state_lock:
            self._logical_items += logical_items
            self._inference_batches += 1

    def _record_failure(self) -> None:
        with self._state_lock:
            self._failed_batches += 1

    def _record_duration(self, started: float) -> None:
        with self._state_lock:
            self._duration_ms += (perf_counter() - started) * 1_000


class DeterministicHashEmbedding:
    """Offline deterministic adapter for tests and local no-network fallback."""

    model_id = "deterministic-hash-v1"
    dimensions = _DIMENSIONS
    identity = ProjectionIdentity(
        provider="deterministic_hash",
        model_id=model_id,
        source_dimensions=_DIMENSIONS,
        projection_dimensions=_DIMENSIONS,
        normalization="l2",
        code_version="1",
    )

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN_PATTERN.findall(text.casefold())
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            for offset in range(self.dimensions):
                magnitude = (digest[offset] + 1) / 256.0
                vector[offset] += magnitude if digest[offset + self.dimensions] & 1 else -magnitude
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        _validated_batch_size(batch_size)
        return [self.embed(text) for text in texts]


class SentenceTransformerEmbedding:
    """Lazy local model with a stable signed projection to a configured space."""

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str,
        source_dimensions: int,
        projection_dimensions: int = _DIMENSIONS,
        allow_network: bool = False,
    ) -> None:
        if projection_dimensions not in {_DIMENSIONS, 128}:
            raise ValueError("projection_dimensions must be 16 or 128")
        self._model_path = model_path.expanduser().resolve(strict=False)
        self._allow_network = allow_network
        self.dimensions = projection_dimensions
        if not allow_network and not self._model_path.is_dir():
            raise EmbeddingUnavailable("local embedding model path is unavailable")
        self._model: Any | None = None
        self.identity = ProjectionIdentity(
            provider="sentence_transformers",
            model_id=model_id,
            source_dimensions=source_dimensions,
            projection_dimensions=projection_dimensions,
            normalization="source-l2+signed-projection-l2",
            code_version="2" if projection_dimensions == _DIMENSIONS else PROJECTION_128_V1,
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text], 1)[0]

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        size = _validated_batch_size(batch_size)
        if not texts:
            return []
        if self._model is None:
            try:
                module = importlib.import_module("sentence_transformers")
                model_class = module.SentenceTransformer
                self._model = model_class(
                    str(self._model_path),
                    local_files_only=not self._allow_network,
                    device="cpu",
                )
            except Exception as exc:
                raise EmbeddingUnavailable(
                    "local sentence-transformer could not be loaded"
                ) from exc
        projected: list[list[float]] = []
        for start in range(0, len(texts), size):
            try:
                raw_batch = self._model.encode(
                    texts[start : start + size], normalize_embeddings=True
                )
                sources = [[float(value) for value in raw] for raw in raw_batch]
            except Exception as exc:
                raise EmbeddingUnavailable("local sentence-transformer inference failed") from exc
            if any(len(source) != self.identity.source_dimensions for source in sources):
                raise EmbeddingUnavailable("embedding source dimension changed")
            projected.extend(
                _dense_projection(source, self.identity, self.dimensions) for source in sources
            )
        return projected


class OnnxSentenceTransformerEmbedding:
    """CPU-only local ONNX sentence embedding without Torch or import-time model loading."""

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str,
        source_dimensions: int,
        projection_dimensions: int = _DIMENSIONS,
    ) -> None:
        if projection_dimensions not in {_DIMENSIONS, 128}:
            raise ValueError("projection_dimensions must be 16 or 128")
        self._model_path = model_path.expanduser().resolve(strict=False)
        if not (self._model_path / "onnx" / "model.onnx").is_file():
            raise EmbeddingUnavailable("local ONNX embedding model is unavailable")
        if not (self._model_path / "tokenizer.json").is_file():
            raise EmbeddingUnavailable("local embedding tokenizer is unavailable")
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._numpy: Any | None = None
        self.dimensions = projection_dimensions
        self.identity = ProjectionIdentity(
            provider="onnx_sentence_transformer",
            model_id=model_id,
            source_dimensions=source_dimensions,
            projection_dimensions=projection_dimensions,
            normalization="mean-pool-l2+dense-projection-l2",
            code_version="1" if projection_dimensions == _DIMENSIONS else PROJECTION_128_V1,
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text], 1)[0]

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        size = _validated_batch_size(batch_size)
        if not texts:
            return []
        if self._session is None:
            self._load()
        assert self._session is not None
        assert self._tokenizer is not None
        assert self._numpy is not None
        projected: list[list[float]] = []
        for start in range(0, len(texts), size):
            batch = texts[start : start + size]
            try:
                encodings = self._tokenizer.encode_batch(batch)
                max_tokens = max(len(encoding.ids) for encoding in encodings)
                pad_id = self._tokenizer.token_to_id("[PAD]") or 0
                input_ids = [
                    [*encoding.ids, *([pad_id] * (max_tokens - len(encoding.ids)))]
                    for encoding in encodings
                ]
                attention_masks = [
                    [
                        *encoding.attention_mask,
                        *([0] * (max_tokens - len(encoding.attention_mask))),
                    ]
                    for encoding in encodings
                ]
                type_ids = [
                    [*encoding.type_ids, *([0] * (max_tokens - len(encoding.type_ids)))]
                    for encoding in encodings
                ]
                mask = self._numpy.asarray(attention_masks, dtype="float32")
                inputs = {
                    "input_ids": self._numpy.asarray(input_ids, dtype="int64"),
                    "attention_mask": self._numpy.asarray(attention_masks, dtype="int64"),
                    "token_type_ids": self._numpy.asarray(type_ids, dtype="int64"),
                }
                hidden = self._session.run(["last_hidden_state"], inputs)[0]
                source_arrays = (hidden * mask[:, :, None]).sum(axis=1) / self._numpy.maximum(
                    mask.sum(axis=1)[:, None], 1.0
                )
                norms = self._numpy.linalg.norm(source_arrays, axis=1)
                source_arrays = source_arrays / self._numpy.maximum(norms[:, None], 1e-12)
                sources = [
                    [float(value) for value in source_array] for source_array in source_arrays
                ]
            except Exception as exc:
                raise EmbeddingUnavailable("local ONNX embedding inference failed") from exc
            if any(len(source) != self.identity.source_dimensions for source in sources):
                raise EmbeddingUnavailable("embedding source dimension changed")
            projected.extend(
                _dense_projection(source, self.identity, self.dimensions) for source in sources
            )
        return projected

    def _load(self) -> None:
        try:
            onnxruntime = importlib.import_module("onnxruntime")
            tokenizers = importlib.import_module("tokenizers")
            self._numpy = importlib.import_module("numpy")
            self._tokenizer = tokenizers.Tokenizer.from_file(
                str(self._model_path / "tokenizer.json")
            )
            self._tokenizer.enable_truncation(max_length=256)
            self._session = onnxruntime.InferenceSession(
                str(self._model_path / "onnx" / "model.onnx"),
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise EmbeddingUnavailable("local ONNX embedding provider could not be loaded") from exc


def _dense_projection(
    source: list[float], identity: ProjectionIdentity, dimensions: int
) -> list[float]:
    projected = [0.0] * dimensions
    seed_code_version = (
        "dg11-1" if identity.code_version == PROJECTION_128_V1 else identity.code_version
    )
    seed = hashlib.sha256(
        "|".join(
            (
                identity.provider,
                identity.model_id,
                str(identity.source_dimensions),
                str(identity.projection_dimensions),
                identity.normalization,
                seed_code_version,
            )
        ).encode()
    ).hexdigest().encode()
    for index, value in enumerate(source):
        base = seed + index.to_bytes(4, "big")
        for block_start in range(0, dimensions, 32):
            digest = hashlib.sha256(
                base + (b"" if block_start == 0 else block_start.to_bytes(2, "big"))
            ).digest()
            for offset in range(min(32, dimensions - block_start)):
                output_index = block_start + offset
                weight = (digest[offset] - 127.5) / 127.5
                projected[output_index] += value * weight
    norm = math.sqrt(sum(value * value for value in projected))
    if norm == 0:
        return projected
    return [value / norm for value in projected]


def project_embedding_vector(
    source: list[float], identity: ProjectionIdentity
) -> list[float]:
    """Apply the public, identity-bound projection used by persisted vectors."""

    if len(source) != identity.source_dimensions:
        raise ValueError("embedding source dimension changed")
    if identity.projection_dimensions not in {_DIMENSIONS, 128}:
        raise ValueError("unsupported embedding projection dimension")
    return _dense_projection(source, identity, identity.projection_dimensions)


def _validated_batch_size(batch_size: int) -> int:
    if not 1 <= batch_size <= 1024:
        raise ValueError("embedding batch_size must be between 1 and 1024")
    return batch_size
