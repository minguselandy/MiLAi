"""Reopen original ranges from a caller's current Source snapshot."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Sequence
from typing import Any

from milai_lab.memory.functional_state import FunctionalRejection, body_text
from milai_lab.memory.reader_projection import merge_source_ranges


def read_original_materials(
    materials: Sequence[dict[str, Any]],
    source: Callable[[str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Share the actual Source read contract across live and immutable storage."""
    result = []
    for material in materials:
        if material.get("kind") != "original_source":
            result.append(copy.deepcopy(material))
            continue
        spans = merge_source_ranges(
            [
                *material["source_ranges"],
                *material.get("unavailable_source_ranges", []),
            ]
        )
        turns, actual_ranges, unavailable = [], [], []
        partial = False
        for span in spans:
            event = source(span["source_ref"])
            if event is None or event.get("source_revision", 1) != span["source_revision"]:
                unavailable.append(dict(span))
                continue
            body = body_text(event)
            start, end = span["start"], span["end"]
            if not 0 <= start <= end <= len(body):
                raise FunctionalRejection("SOURCE_MATERIAL_RANGE_UNAVAILABLE")
            partial = partial or start != 0 or end != len(body)
            turn = {
                "source_ref": event["event_id"],
                "source_revision": span["source_revision"],
                "session_id": event["session"],
                "role": event["role"],
                "origin": event["origin"],
                "content": body[start:end],
                "timestamp": event.get("occurred_at", event["observed_at"]),
                "observed_at": event["observed_at"],
                "occurred_at": event.get("occurred_at"),
                "range": [start, end],
                "source_total_codepoints": len(body),
            }
            if "calendar_context" in event:
                turn["calendar_context"] = event["calendar_context"]
            if "capture_context" in event:
                turn["capture_context"] = event["capture_context"]
            turns.append(turn)
            actual_ranges.append(dict(span))
        result.append(
            {
                "kind": "original_source",
                "provenance": "original_exchange",
                "id": material["id"],
                "session_id": material["session_id"],
                "date": turns[0]["timestamp"] if turns else material.get("date"),
                "turn_range": material["turn_range"],
                "text": json.dumps(turns, ensure_ascii=False),
                "source_ranges": actual_ranges,
                "unavailable_source_ranges": unavailable,
                "score": material.get("score"),
                "truncated": partial or bool(unavailable),
                "coverage": "selected_visible_source_ranges",
                "body_delivered": bool(turns),
                "visibility": "partial"
                if turns and unavailable
                else "visible"
                if turns
                else "unavailable",
            }
        )
    return result
