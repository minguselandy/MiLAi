"""Lossless token-window embeddings for sources longer than the model context."""

from __future__ import annotations

from collections.abc import Sequence

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.methods.reasoning_bank import normalized
from milai_lab.providers.contextual_vllm import VLLMClient


def embed_texts_windowed(
    client: VLLMClient,
    texts: Sequence[str],
    model: str,
    *,
    tokenizer: Tokenizer,
    max_tokens: int,
    batch_size: int,
) -> list[list[float]]:
    """Embed full texts, pooling long texts across ordered token windows.

    Short texts use the existing string request path unchanged. Long texts are
    tokenized once without specials, split without overlap, post-processed with
    the model's own special tokens, and pooled by original window token count.
    """
    if not texts:
        return []
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    tokenizer.no_truncation()
    tokenizer.no_padding()
    processor = tokenizer.post_processor
    specials = processor.num_special_tokens_to_add(False) if processor is not None else 0
    payload_limit = max_tokens - specials
    if payload_limit < 1:
        raise ValueError("max_tokens must leave room for source tokens and specials")

    output: dict[int, list[float]] = {}
    short: list[tuple[int, str]] = []
    windows: list[tuple[int, int, list[int]]] = []
    for index, source in enumerate(texts):
        encoding = tokenizer.encode(source, add_special_tokens=False)
        if len(encoding.ids) <= payload_limit:
            short.append((index, source))
            continue
        encoding.truncate(payload_limit, stride=0)
        pieces = [encoding, *encoding.overflowing]
        for piece in pieces:
            with_specials = tokenizer.post_process(piece, add_special_tokens=True)
            windows.append((index, len(piece.ids), with_specials.ids))

    for offset in range(0, len(short), batch_size):
        short_batch = short[offset : offset + batch_size]
        vectors = client.embed([source for _, source in short_batch], model)
        for (index, _), vector in zip(short_batch, vectors, strict=True):
            output[index] = vector

    weighted: dict[int, list[float]] = {}
    for offset in range(0, len(windows), batch_size):
        window_batch = windows[offset : offset + batch_size]
        token_inputs = [ids for _, _, ids in window_batch]
        vectors = client.embed(token_inputs, model)
        for (index, weight, _), vector in zip(window_batch, vectors, strict=True):
            previous = weighted.get(index, [0.0] * len(vector))
            weighted[index] = [
                left + weight * right for left, right in zip(previous, vector, strict=True)
            ]

    for index, total in weighted.items():
        # Normalizing the weighted sum is equivalent to normalizing its weighted mean.
        output[index] = normalized(total, len(total))
    return [output[index] for index in range(len(texts))]
