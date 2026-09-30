"""Plain local tokenizer admission for the existing metered embedding transport."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.memory.embeddings import normalized
from milai_lab.providers.contextual_vllm import VLLMClient


class EmbeddingCapacity:
    def __init__(self, config: dict[str, Any]) -> None:
        path = Path(config["tokenizer_path"])
        if not path.is_absolute() or not path.is_file():
            raise ValueError("EMBEDDING_TOKENIZER_LOCAL_FILE_REQUIRED")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != config["tokenizer_sha256"]:
            raise ValueError("EMBEDDING_TOKENIZER_IDENTITY_MISMATCH")
        limit = config["context_tokens"]
        if type(limit) is not int or limit < 1:
            raise ValueError("EMBEDDING_CONTEXT_LIMIT_INVALID")
        self.tokenizer = Tokenizer.from_file(str(path))
        self.limit = limit
        self.identity = {**config, "tokenizer_sha256": actual}

    def check(self, texts: Sequence[str]) -> list[int]:
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        counts = [len(self.tokenizer.encode(text, add_special_tokens=True).ids) for text in texts]
        if any(count > self.limit for count in counts):
            raise ValueError("EMBEDDING_CONTEXT_CAPACITY_EXCEEDED")
        return counts


class MeteredEmbeddings(Embeddings):
    """No retry/cache/window rewrite; admit each original input, then use VLLMClient."""

    def __init__(
        self,
        client: VLLMClient,
        model: str,
        config: dict[str, Any],
        *,
        dimension: int,
        batch_size: int,
    ) -> None:
        if (
            type(dimension) is not int
            or dimension < 1
            or type(batch_size) is not int
            or batch_size < 1
        ):
            raise ValueError("EMBEDDING_VECTOR_OR_BATCH_INVALID")
        self.client, self.model = client, model
        self.dimension, self.batch_size = dimension, batch_size
        self.capacity = EmbeddingCapacity(config)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        counts = self.capacity.check(texts)
        if self.client.emit is not None:
            self.client.emit(
                {
                    "event": "embedding_admission",
                    "input_tokens_with_specials": counts,
                    "identity": self.capacity.identity,
                    "request_sent": False,
                }
            )
        output: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors = self.client.embed(batch, self.model)
            if len(vectors) != len(batch):
                raise ValueError("EMBEDDING_VECTOR_COUNT_MISMATCH")
            output.extend(normalized(vector, self.dimension) for vector in vectors)
        return output

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
