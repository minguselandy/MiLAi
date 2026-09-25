from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer, models, pre_tokenizers, processors

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
embed_texts_windowed = importlib.import_module("contextual_embeddings").embed_texts_windowed


def _tokenizer() -> Tokenizer:
    vocabulary = {
        "[UNK]": 0,
        "<s>": 1,
        "</s>": 2,
        "[PAD]": 3,
        **{
            word: index
            for index, word in enumerate(
                ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "theta"], start=4
            )
        },
    }
    tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", special_tokens=[("<s>", 1), ("</s>", 2)]
    )
    tokenizer.enable_truncation(4)
    tokenizer.enable_padding(length=4, pad_id=3, pad_token="[PAD]")
    return tokenizer


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[list[str] | list[list[int]]] = []

    def embed(self, texts: Any, model: str) -> list[list[float]]:
        assert model == "test-model"
        self.requests.append(list(texts))
        if isinstance(texts[0], str):
            return [[0.3, 0.4] for _ in texts]
        return [[1.0, 0.0] if ids[1] == 4 else [0.0, 1.0] for ids in texts]


def test_long_text_preserves_order_and_pools_by_original_token_count() -> None:
    tokenizer = _tokenizer()
    client = FakeClient()
    source = "alpha beta gamma delta epsilon zeta theta"

    result = embed_texts_windowed(
        client, [source], "test-model", tokenizer=tokenizer, max_tokens=5, batch_size=2
    )

    assert tokenizer.truncation is None
    assert tokenizer.padding is None
    assert [len(request) for request in client.requests] == [2, 1]
    windows = [ids for request in client.requests for ids in request]
    assert windows == [[1, 4, 5, 6, 2], [1, 7, 8, 9, 2], [1, 10, 2]]
    assert [token for window in windows for token in window[1:-1]] == list(range(4, 11))
    assert all(
        math.isclose(actual, expected)
        for actual, expected in zip(result[0], [0.6, 0.8], strict=True)
    )
    assert math.isclose(math.dist(result[0], [0.0, 0.0]), 1.0)


def test_short_text_uses_original_string_embedding_unchanged() -> None:
    client = FakeClient()
    result = embed_texts_windowed(
        client, ["alpha beta"], "test-model", tokenizer=_tokenizer(), max_tokens=5, batch_size=2
    )

    assert client.requests == [["alpha beta"]]
    assert result == [[0.3, 0.4]]
