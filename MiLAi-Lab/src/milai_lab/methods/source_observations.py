"""Budgeted, reversible navigation over literal source-arrival observations."""
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from milai_lab.memory.functional_state import canonical


@dataclass(frozen=True)
class SourceObservationBudget:
    max_tokens: int
    token_count: Callable[[str], int]


class SourceObservationPages:
    """Keep source order and character ranges; paging never changes the Store.

    The current page replaces the previous controller observation. Previous pages
    can be reopened. Full-bank search and Reader delivery have separate paths.
    """

    def __init__(self, events: list[dict[str, Any]], budget: SourceObservationBudget) -> None:
        self.events, self.budget = events, budget
        self.visible = {event["source_ref"] for event in events}
        self.starts: list[tuple[int, int]] = [(0, 0)]
        self.position = 0
        self.complete_prefix = 0
        self.current: dict[str, Any] = {}
        self.open((0, 0))

    def checkpoint(self) -> dict[str, Any]:
        """Literal navigation state for a captured decision, without serializing callbacks."""
        return copy.deepcopy({"events": self.events, "visible": sorted(self.visible),
            "starts": [list(cursor) for cursor in self.starts], "position": self.position,
            "complete_prefix": self.complete_prefix, "current": self.current})

    @classmethod
    def restore(cls, saved: dict[str, Any],
                budget: SourceObservationBudget) -> SourceObservationPages:
        result = cls.__new__(cls)
        result.budget = budget
        result.events = copy.deepcopy(saved["events"])
        result.visible = set(saved["visible"])
        result.starts = [(index, offset) for index, offset in saved["starts"]]
        result.position, result.complete_prefix = saved["position"], saved["complete_prefix"]
        result.current = copy.deepcopy(saved["current"])
        return result

    def restrict(self, visible: set[str]) -> None:
        self.visible.intersection_update(visible)
        self.current = self._page(self.starts[self.position])

    def navigation(self) -> dict[str, list[int]]:
        result = {}
        if self.position:
            result["previous"] = list(self.starts[self.position - 1])
        if self.current["next_cursor"] is not None:
            result["next"] = self.current["next_cursor"]
        return result

    def open(self, cursor: tuple[int, int]) -> dict[str, Any]:
        if cursor in self.starts:
            self.position = self.starts.index(cursor)
        else:
            self.starts = [*self.starts[:self.position + 1], cursor]
            self.position += 1
        self.current = self._page(cursor)
        end = self.current["next_cursor"]
        self.complete_prefix = max(self.complete_prefix, end[0] if end else len(self.events))
        return copy.deepcopy(self.current)

    def coverage(self) -> dict[str, Any]:
        completed = self.events[:self.complete_prefix]
        cursor = ([completed[-1]["captured_at"], completed[-1]["source_ref"]]
                  if completed else [])
        return {"cursor": cursor, "boundary_refs": [event["source_ref"] for event in completed
            if cursor and event["captured_at"] == cursor[0]
            and event["source_ref"] in self.visible]}

    def _page(self, cursor: tuple[int, int]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        index, offset = cursor

        def packet(next_index: int, next_offset: int) -> dict[str, Any]:
            while (next_index < len(self.events)
                   and self.events[next_index]["source_ref"] not in self.visible):
                next_index, next_offset = next_index + 1, 0
            return {"events": rows, "cursor": list(cursor),
                    "next_cursor": [next_index, next_offset]
                        if next_index < len(self.events) else None,
                    "total_sources": len(self.visible),
                    "remaining_sources": sum(event["source_ref"] in self.visible
                                             for event in self.events[next_index:]),
                    "scope": "Current source-observation page, not Reader evidence or "
                             "a relevance filter; full visible bank remains searchable. "
                             "Ranges are Unicode character offsets in the unchanged source."}

        def fits(value: dict[str, Any]) -> bool:
            return self.budget.token_count(canonical(value)) <= self.budget.max_tokens

        while index < len(self.events):
            event = self.events[index]
            if event["source_ref"] not in self.visible:
                index, offset = index + 1, 0
                continue
            body = event["content"]
            row = {**event, "content": body[offset:], "source_range": [offset, len(body)],
                   "source_characters": len(body)}
            rows.append(row)
            if fits(packet(index + 1, 0)):
                index, offset = index + 1, 0
                continue
            # Admit a literal prefix when a whole remaining source does not fit.
            # Every tested prefix includes its real continuation cursor/envelope.
            lower, upper, accepted = offset + 1, len(body) - 1, offset
            while lower <= upper:
                end = (lower + upper) // 2
                row.update(content=body[offset:end], source_range=[offset, end])
                if fits(packet(index, end)):
                    accepted, lower = end, end + 1
                else:
                    upper = end - 1
            if accepted > offset:
                row.update(content=body[offset:accepted], source_range=[offset, accepted])
                return packet(index, accepted)
            rows.pop()
            if rows:
                return packet(index, offset)
            raise ValueError("Source observation budget cannot fit the envelope and one character")
        result = packet(index, offset)
        if not fits(result):
            raise ValueError("Source observation budget cannot fit its empty envelope")
        return result
