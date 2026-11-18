"""Bounded query-hit navigation over the same original Source ranges as the index."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_views import SourceObject, Span

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE = re.compile(r"[^.!?。！？\n]+[.!?。！？]*")


def query_terms(query: str) -> set[str]:
    return {match.group().casefold() for match in _WORD.finditer(query)}


def excerpt(
    terms: set[str], ranges: list[Span], objects: Mapping[int, SourceObject],
    encoder: Tokenizer, limit: int,
) -> tuple[int, dict[str, Any]] | None:
    selected: tuple[int, int, int, int] | None = None
    best = 0
    for oid, start, end in ranges:
        body = objects[oid].body
        if end > start and selected is None:
            selected = (oid, start, end, start)
        for sentence in _SENTENCE.finditer(body, start, end):
            hits = [m for m in _WORD.finditer(sentence.group()) if m.group().casefold() in terms]
            score = len({match.group().casefold() for match in hits})
            if score > best:
                best = score
                selected = (oid, sentence.start(), sentence.end(),
                            sentence.start() + hits[0].start())
    if selected is None:
        return None
    oid, start, end, hit = selected
    body = objects[oid].body
    offsets = encoder.encode(body[start:end], add_special_tokens=False).offsets
    if not offsets:
        return None
    center = next((i for i, (_, b) in enumerate(offsets) if b > hit - start), 0)
    left = max(0, min(center - limit // 3, len(offsets) - limit))
    right = min(len(offsets), left + limit)
    # The extracted original substring can tokenize differently at its edges.
    while right > left:
        a, b = start + offsets[left][0], start + offsets[right - 1][1]
        text = body[a:b]
        count = len(encoder.encode(text, add_special_tokens=False).ids)
        if count <= limit:
            return oid, {"text": text, "start": a, "end": b,
                         "encoder_tokens": count, "role": objects[oid].role}
        right -= 1
    return None
