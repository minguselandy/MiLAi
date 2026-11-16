"""Opt-in literal range candidates inside an actually retrieved Source pool."""
from __future__ import annotations

import json
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRangeBudget:
    tokens: int
    count: Callable[[str], int]
    offsets: Callable[[str], Sequence[tuple[int, int]]]

    def __post_init__(self) -> None:
        if type(self.tokens) is not int or self.tokens < 1:
            raise ValueError("Source range tokens must be a positive integer")

    def ranges(self, text: str) -> list[tuple[int, int]]:
        """Cover every codepoint once; native token offsets propose each boundary.

        Retokenization of a fragment can change boundary tokens. Count that exact
        fragment before accepting it. Never decode token slices or discard gaps.
        """
        ends = [end for _, end in self.offsets(text)]
        result, start = [], 0
        while start < len(text):
            stop = min(len(ends), bisect_right(ends, start) + self.tokens)
            end = ends[stop - 1] if stop < len(ends) else len(text)
            if self.count(text[start:end]) > self.tokens:
                lower, upper, accepted = start + 1, end - 1, start
                while lower <= upper:
                    middle = (lower + upper) // 2
                    if self.count(text[start:middle]) <= self.tokens:
                        accepted, lower = middle, middle + 1
                    else:
                        upper = middle - 1
                if accepted == start:
                    raise ValueError("Source range budget cannot fit one Unicode character")
                end = accepted
            result.append((start, end))
            start = end
        return result or [(0, 0)]


def source_range_packs(material: dict[str, Any], budget: SourceRangeBudget,
                       *, scope_only: bool = False) -> list[dict[str, Any]]:
    """Keep Source identity/version; expansion opens adjacent ranges of that Source.

    These are candidates, not delivered bodies. Ordinary READ reopens the exact
    ranges through MemoryService, including visibility and revision checks.
    """
    packs = []
    for ordinal, turn in enumerate(json.loads(material["text"])):
        text = turn["content"]
        base = turn["range"][0]
        ranges = budget.ranges(text)
        for index, (left, right) in enumerate(ranges):
            span = {"source_ref": turn["source_ref"], "source_revision": turn["source_revision"],
                    "start": base + left, "end": base + right}
            context = {**span, "start": base + ranges[max(0, index - 1)][0],
                       "end": base + ranges[min(len(ranges) - 1, index + 1)][1]}
            focused = {**turn, "content": text[left:right],
                       "range": [span["start"], span["end"]]}
            turn_range = [material["turn_range"][0] + ordinal,
                          material["turn_range"][0] + ordinal + 1]
            packs.append({**material,
                "id": f"{material['id']}:range:{ordinal}:{span['start']}:{span['end']}",
                "source_ranges": [span], "focus_source_ranges": [span],
                "context_source_ranges": [context], "turn_range": turn_range,
                "context_turn_range": turn_range, "text": json.dumps([focused], ensure_ascii=False),
                "index_text": focused["content"], "pack_kind": "literal_source_range",
                "source_range_read": True, "scope_only": scope_only})
    return packs
