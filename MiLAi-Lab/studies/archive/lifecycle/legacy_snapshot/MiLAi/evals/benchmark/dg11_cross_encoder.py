from __future__ import annotations

import hashlib
import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class CrossEncoderUnavailable(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FrozenOnnxCrossEncoder:
    """Bounded CPU-only reranker used only by the DG11 retrieval experiment."""

    def __init__(
        self,
        model_root: Path,
        *,
        model_id: str,
        revision: str,
    ) -> None:
        self.model_root = model_root.expanduser().resolve()
        self.model_path = self.model_root / "onnx/model_qint8_avx512.onnx"
        self.tokenizer_path = self.model_root / "tokenizer.json"
        if not self.model_path.is_file() or not self.tokenizer_path.is_file():
            raise CrossEncoderUnavailable("frozen cross-encoder files are unavailable")
        self.identity = {
            "model_id": model_id,
            "revision": revision,
            "model_sha256": _sha256(self.model_path),
            "tokenizer_sha256": _sha256(self.tokenizer_path),
            "runtime": "onnxruntime/CPUExecutionProvider",
            "max_length": 512,
        }
        self.inference_batches = 0
        self.scored_pairs = 0
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
            raise CrossEncoderUnavailable("frozen cross-encoder could not be loaded") from exc
        self._numpy: Any = numpy
        self._tokenizer: Any = tokenizer
        self._session: Any = session

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        encodings = self._tokenizer.encode_batch([(query, text) for text in texts])
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
        try:
            logits = self._session.run(["logits"], inputs)[0].reshape(-1)
        except Exception as exc:
            raise CrossEncoderUnavailable("frozen cross-encoder inference failed") from exc
        self.inference_batches += 1
        self.scored_pairs += len(texts)
        return [float(value) for value in logits]


def blend_scores(
    cross_encoder_scores: Sequence[float],
    retrieval_scores: Sequence[float],
    *,
    cross_encoder_weight: float,
) -> list[float]:
    if len(cross_encoder_scores) != len(retrieval_scores):
        raise ValueError("score vectors must have equal length")
    if not 0.0 <= cross_encoder_weight <= 1.0:
        raise ValueError("cross_encoder_weight must be between zero and one")

    def normalize(values: Sequence[float]) -> list[float]:
        if not values:
            return []
        low, high = min(values), max(values)
        if high == low:
            return [0.5] * len(values)
        return [(value - low) / (high - low) for value in values]

    cross_normalized = normalize(cross_encoder_scores)
    retrieval_normalized = normalize(retrieval_scores)
    return [
        cross_encoder_weight * cross + (1.0 - cross_encoder_weight) * retrieval
        for cross, retrieval in zip(
            cross_normalized, retrieval_normalized, strict=True
        )
    ]
