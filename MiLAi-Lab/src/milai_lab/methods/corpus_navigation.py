"""Bounded query-hit navigation over the same original Source ranges as the index."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_protocols import DELTA_NAVIGATION_LIMIT
from milai_lab.datasets.memory_control_views import SourceObject, Span

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE = re.compile(r"[^.!?\u3002\uff01\uff1f\n]+[.!?\u3002\uff01\uff1f]*")


def query_terms(query: str) -> set[str]:
    return {match.group().casefold() for match in _WORD.finditer(query)}


def excerpt(
    terms: set[str],
    ranges: list[Span],
    objects: Mapping[int, SourceObject],
    encoder: Tokenizer,
    limit: int,
) -> tuple[int, dict[str, Any]] | None:
    location = locate_excerpt(terms, ranges, objects)
    return tokenize_excerpt(location, objects, encoder, limit) if location is not None else None


def locate_excerpt(
    terms: set[str], ranges: list[Span], objects: Mapping[int, SourceObject],
) -> tuple[int, int, int, int] | None:
    """Use the same query-hit ordering for both navigation protocols."""
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
                selected = (
                    oid,
                    sentence.start(),
                    sentence.end(),
                    sentence.start() + hits[0].start(),
                )
    return selected


def tokenize_excerpt(
    selected: tuple[int, int, int, int],
    objects: Mapping[int, SourceObject],
    encoder: Tokenizer,
    limit: int,
) -> tuple[int, dict[str, Any]] | None:
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
            return oid, {
                "text": text,
                "start": a,
                "end": b,
                "encoder_tokens": count,
                "role": objects[oid].role,
            }
        right -= 1
    return None


def delta_preview(
    terms: set[str],
    focus: list[Span],
    expansion: list[Span] | None,
    objects: Mapping[int, SourceObject],
    refs: Mapping[int, str],
    encoder: Tokenizer,
    *,
    source_revision: int,
) -> dict[str, Any]:
    ranges = {"focus": focus, "expansion_only": expansion}
    locations: dict[str, tuple[int, int, int, int]] = {}
    previews: dict[str, dict[str, Any]] = {}
    half = DELTA_NAVIGATION_LIMIT // 2

    def render(role: str, quota: int) -> None:
        tokens = tokenize_excerpt(locations[role], objects, encoder, quota)
        if tokens is None:
            previews[role] = {"status": "empty", "encoder_tokens": 0}
        else:
            oid, fragment = tokens
            previews[role] = {
                "status": "available", "source_ref": refs[oid],
                "source_revision": source_revision, **fragment,
            }

    for role, spans in ranges.items():
        if spans is None:
            previews[role] = {"status": "absent", "encoder_tokens": 0}
        elif any(oid not in objects for oid, _, _ in spans):
            previews[role] = {
                "status": "missing", "reason": "source_unavailable", "encoder_tokens": 0,
            }
        elif (location := locate_excerpt(terms, spans, objects)) is None:
            previews[role] = {"status": "empty", "encoder_tokens": 0}
        else:
            locations[role] = location
            render(role, half)
    # Only one side may take unused capacity. An unavailable source keeps its quota.
    if locations:
        recipient = max(locations, key=lambda role: previews[role]["encoder_tokens"])
        donor = "focus" if recipient == "expansion_only" else "expansion_only"
        if previews[donor]["status"] != "missing" and previews[donor]["encoder_tokens"] < half:
            render(recipient, DELTA_NAVIGATION_LIMIT - previews[donor]["encoder_tokens"])
    return {**previews, "encoder_tokens": sum(r["encoder_tokens"] for r in previews.values())}
