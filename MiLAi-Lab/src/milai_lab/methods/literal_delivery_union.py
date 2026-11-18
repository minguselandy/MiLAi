"""Normalize compatible opened literal ranges before projecting the Reader packet."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.methods.evidence_reading import project_pack

DELIVERY_PROTOCOL = "source_interval_union_v1"


@dataclass(frozen=True)
class LiteralDelivery:
    evidence: list[dict[str, Any]]
    source_aliases: dict[str, dict[str, Any]]
    unique_source_chars: int
    overlap_before_normalization: int


def literal_delivery(
    opened: dict[int, dict[str, Any]],
    read: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    position: Callable[[str], int],
) -> LiteralDelivery:
    """Normalize within authorized, literal Source scopes and keep capture order."""
    groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    order: list[tuple[int, dict[str, Any], list[tuple[int, dict[str, Any]]] | None]] = []
    for index, item in opened.items():
        if (item["kind"] != "original_source" or item.get("visibility") != "visible"
                or item.get("body_delivered") is not True or item.get("unavailable_source_ranges")):
            order.append((index, item, None))
            continue
        key = (item["session_id"],
               json.dumps(item.get("source_access_scope"), sort_keys=True, ensure_ascii=False),
               item.get("source_representation", "original_exchange"))
        group = groups.setdefault(key, [])
        if not group:
            order.append((index, item, group))
        group.append((index, item))

    evidence = []
    aliases: dict[str, dict[str, Any]] = {}
    unique_chars, overlap = 0, 0
    for index, original, group in order:
        if group is None:
            evidence.append(project_pack(original, index))
            continue
        before = [span for _, item in group for span in item["source_ranges"]]
        merged = merge_source_ranges(sorted(before, key=lambda span: position(span["source_ref"])))
        covered = sum(span["end"] - span["start"] for span in merged)
        unique_chars += covered
        overlap += sum(span["end"] - span["start"] for span in before) - covered
        items = [item for _, item in group]
        descriptor = {**original, "source_ranges": merged, "turn_range": [
            min(item["turn_range"][0] for item in items),
            max(item["turn_range"][1] for item in items),
        ]}
        actual = read([descriptor])[0]
        if actual["visibility"] != "visible":
            raise ValueError("Literal Source visibility changed during delivery planning")
        projected = project_pack({**descriptor, **actual}, index)
        if len(group) > 1:
            projected["also_selected_as"] = [f"e{i}" for i, _ in group[1:]]
        local: dict[tuple[str, int], str] = {}
        for span, piece in zip(actual["source_ranges"], projected["evidence"], strict=True):
            key_span = (span["source_ref"], span["source_revision"])
            alias = local.setdefault(key_span, f"e{index}:s{len(local)}")
            piece["source"] = alias
            aliases.setdefault(alias, {k: span[k] for k in ("source_ref", "source_revision")})
        evidence.append(projected)
    return LiteralDelivery(evidence, aliases, unique_chars, overlap)
