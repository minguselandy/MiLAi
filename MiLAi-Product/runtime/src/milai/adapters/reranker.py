from __future__ import annotations

import hashlib
import importlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class RerankerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RerankerExecution:
    results: list[dict[str, Any]]
    metadata: dict[str, Any]


class CrossEncoderReranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        limit: int,
        pool_size: int,
    ) -> RerankerExecution: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _memory_text(candidate: dict[str, Any]) -> str:
    payload = candidate.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("memory_text"), str):
        return str(payload["memory_text"])
    value = candidate.get("memory_text")
    return str(value) if isinstance(value, str) else ""


class FrozenOnnxCrossEncoderReranker:
    """Lazy, bounded CPU-only cross-encoder over canonical-gated candidates."""

    def __init__(
        self,
        model_root: Path,
        *,
        model_id: str,
        revision: str,
        expected_model_sha256: str,
    ) -> None:
        self.model_root = model_root.expanduser().resolve()
        self.model_path = self.model_root / "onnx/model_qint8_avx512.onnx"
        self.tokenizer_path = self.model_root / "tokenizer.json"
        if not self.model_path.is_file() or not self.tokenizer_path.is_file():
            raise RerankerUnavailable("frozen cross-encoder files are unavailable")
        model_sha256 = _sha256(self.model_path)
        if model_sha256 != expected_model_sha256:
            raise RerankerUnavailable("frozen cross-encoder digest mismatch")
        self.identity = {
            "provider": "onnx_cross_encoder",
            "model_id": model_id,
            "revision": revision,
            "model_sha256": model_sha256,
            "tokenizer_sha256": _sha256(self.tokenizer_path),
            "runtime": "onnxruntime/CPUExecutionProvider",
            "max_length": 512,
        }
        self._numpy: Any | None = None
        self._tokenizer: Any | None = None
        self._session: Any | None = None

    def _load(self) -> None:
        if self._session is not None:
            return
        try:
            numpy = importlib.import_module("numpy")
            onnxruntime = importlib.import_module("onnxruntime")
            tokenizers = importlib.import_module("tokenizers")
            tokenizer = tokenizers.Tokenizer.from_file(str(self.tokenizer_path))
            tokenizer.enable_truncation(max_length=512, strategy="longest_first")
            tokenizer.enable_padding()
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            session = onnxruntime.InferenceSession(
                str(self.model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise RerankerUnavailable("frozen cross-encoder could not be loaded") from exc
        self._numpy = numpy
        self._tokenizer = tokenizer
        self._session = session

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        limit: int,
        pool_size: int,
    ) -> RerankerExecution:
        if limit <= 0 or pool_size < limit:
            raise ValueError("reranker pool must cover the positive result limit")
        pool = candidates[:pool_size]
        if not pool:
            return RerankerExecution([], {**self.identity, "pairs": 0, "duration_ms": 0.0})
        self._load()
        assert self._numpy is not None
        assert self._tokenizer is not None
        assert self._session is not None
        encodings = self._tokenizer.encode_batch(
            [(query, _memory_text(candidate)) for candidate in pool]
        )
        inputs = {
            "input_ids": self._numpy.asarray(
                [encoding.ids for encoding in encodings], dtype="int64"
            ),
            "attention_mask": self._numpy.asarray(
                [encoding.attention_mask for encoding in encodings], dtype="int64"
            ),
            "token_type_ids": self._numpy.asarray(
                [encoding.type_ids for encoding in encodings], dtype="int64"
            ),
        }
        started = time.perf_counter()
        try:
            scores = self._session.run(["logits"], inputs)[0].reshape(-1)
        except Exception as exc:
            raise RerankerUnavailable("frozen cross-encoder inference failed") from exc
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        ranked_indices = sorted(
            range(len(pool)),
            key=lambda index: (float(scores[index]), -index),
            reverse=True,
        )[:limit]
        metadata = {
            **self.identity,
            "pairs": len(pool),
            "duration_ms": duration_ms,
        }
        selected = []
        for index in ranked_indices:
            result = dict(pool[index])
            result["reranker"] = {
                **metadata,
                "score": round(float(scores[index]), 8),
                "source_rank": index + 1,
            }
            selected.append(result)
        return RerankerExecution(selected, metadata)
