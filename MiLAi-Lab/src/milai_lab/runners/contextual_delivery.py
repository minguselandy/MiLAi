"""Exact material spans resident in the current Host transcript, never a read history."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeliveredSpan:
    ref: str
    sha256: str
    start: int
    end: int


def _materials(value: Any) -> Iterator[tuple[str, str, dict[str, Any]]]:
    if isinstance(value, list):
        for item in value:
            yield from _materials(item)
    elif isinstance(value, dict):
        if value.get("kind") in {"source", "interpretation"} and "ref" in value:
            yield value["ref"], value["kind"], value
            for excerpt in value.get("excerpts", []):
                yield value["ref"], value["kind"], excerpt
        for key in ("materials", "expanded_materials", "sources", "associated_materials"):
            if key in value:
                yield from _materials(value[key])


def _body(ref: str, kind: str, item: dict[str, Any]) -> tuple[str, str, DeliveredSpan] | None:
    key = "content" if kind == "source" else "text"
    if key not in item:
        return None
    body: str = item[key]
    page = item.get("page")
    if page is None:
        span = DeliveredSpan(ref, hashlib.sha256(body.encode()).hexdigest(), 0, len(body))
    else:
        span = DeliveredSpan(ref, page["content_sha256"], page["start"], page["end"])
    # Only accurately described pages can authorize omission of later text.
    if len(body) != span.end - span.start:
        return None
    return key, body, span


def _uncovered(start: int, end: int, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    remaining = []
    cursor = start
    for lower, upper in sorted(covered):
        if upper <= cursor or lower >= end:
            continue
        if lower > cursor:
            remaining.append((cursor, lower))
        cursor = max(cursor, upper)
    if cursor < end:
        remaining.append((cursor, end))
    return remaining


@dataclass
class DeliveryLedger:
    """Local to one run; removed or edited messages cease authorizing deduplication."""

    generation: str
    entries: list[tuple[dict[str, Any], str, tuple[DeliveredSpan, ...]]] = field(
        default_factory=list
    )

    @staticmethod
    def resident(message: dict[str, Any], transcript: Sequence[dict[str, Any]]) -> bool:
        return any(candidate is message for candidate in transcript)

    def record(self, message: dict[str, Any], result: dict[str, Any]) -> None:
        spans = []
        for ref, kind, item in _materials(result):
            body = _body(ref, kind, item)
            if body:
                spans.append(body[2])
            elif "delivered_spans" in item:
                for part in item["delivered_spans"]:
                    spans.append(DeliveredSpan(
                        ref, item["delivery"]["content_sha256"],
                        part["start"], part["end"],
                    ))
        self.entries.append((message, message["content"], tuple(spans)))

    def deliver(
        self, result: dict[str, Any], transcript: Sequence[dict[str, Any]],
    ) -> tuple[dict[str, Any], int]:
        self.entries = [
            entry for entry in self.entries
            if self.resident(entry[0], transcript) and entry[0]["content"] == entry[1]
        ]
        covered: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for _, _, spans in self.entries:
            for span in spans:
                covered.setdefault((span.ref, span.sha256), []).append((span.start, span.end))
        rendered = copy.deepcopy(result)
        omitted_bytes = 0
        for ref, kind, item in _materials(rendered):
            body = _body(ref, kind, item)
            if body is None:
                continue
            key, text, span = body
            remaining = _uncovered(
                span.start, span.end, covered.get((span.ref, span.sha256), [])
            )
            if remaining == [(span.start, span.end)]:
                continue
            del item[key]
            parts: list[dict[str, Any]] = [
                {"start": lower, "end": upper, key: text[lower - span.start:upper - span.start]}
                for lower, upper in remaining
            ]
            item["delivered_spans"] = parts
            item["delivery"] = {
                "context_generation": self.generation,
                "content_sha256": span.sha256,
                "requested_range": [span.start, span.end],
                "notice": "Omitted body ranges are present in earlier receipts in this context. "
                "Current status, corrections and restrictions below still apply.",
            }
            omitted_bytes += len(text.encode()) - sum(len(part[key].encode()) for part in parts)
        return rendered, omitted_bytes
