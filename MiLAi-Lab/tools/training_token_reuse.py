"""Reuse SDK tokenizer outputs for preparation and permutations, preserving its encoding rules."""

from __future__ import annotations

from collections import Counter
from typing import Any

from train_laya_matched import audit


class TrainingTokenizerCache:
    """SDK-only tokenizer proxy; long-state cache lasts exactly one preparation row.

    Question text/settings stay in an ordinary local dictionary for this job. SDK
    serializers, option rendering, truncation, marker assembly and target order
    remain authoritative. No content digests, global cache or model values are used.
    """

    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer
        self.question_tokens: dict[Any, tuple[int, ...]] = {}
        self.state_tokens: dict[Any, tuple[int, ...]] = {}
        self.state_text: str | None = None
        self.counters: Counter[str] = Counter()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tokenizer, name)

    def begin_state(self, state: Any) -> None:
        from laya.common import serialize_state

        self.state_text = serialize_state(state).replace(self.tokenizer.mask_token, " ")
        self.state_tokens.clear()

    def end_state(self) -> None:
        self.state_text = None
        self.state_tokens.clear()

    def __call__(self, text: str, **kwargs: Any) -> dict[str, list[int]]:
        # Only the SDK encode_text/build_head calls use this proxy. They consume
        # input_ids and pass scalar tokenizer settings, never return_tensors.
        key = (text, tuple(kwargs.items()))
        state = self.state_text is not None and text == self.state_text
        cache = self.state_tokens if state else self.question_tokens
        kind = "state" if state else "question"
        if key not in cache:
            cache[key] = tuple(self.tokenizer(text, **kwargs)["input_ids"])
            self.counters[kind + "_tokenizations"] += 1
            self.counters[kind + "_tokens"] += len(cache[key])
        else:
            self.counters[kind + "_cache_hits"] += 1
        return {"input_ids": list(cache[key])}


def prepare_training_rows(
    tokenizer: Any, rows: list[dict[str, Any]], max_len: int, head_max_len: int
) -> tuple[Any, ...]:
    """Run the original audit/item/sequence routines together, sharing only tokenizer results."""
    from laya.train import encode_item, items_from_rows

    cached = TrainingTokenizerCache(tokenizer)
    lengths, items, encoded = [], [], []
    skipped: Counter[str] = Counter()
    for row in rows:
        cached.begin_state(row["state"])
        try:
            lengths.extend(audit([row], cached, max_len, head_max_len))
            current, rejected = items_from_rows(cached, [row], max_len, head_max_len)
            skipped.update(rejected)
            items.extend(current)
            encoded.extend(encode_item(cached, item, max_len, head_max_len) for item in current)
        finally:
            cached.end_state()
    return lengths, items, dict(skipped), encoded, cached
