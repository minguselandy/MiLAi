"""Strictly reversible JSON layout/string dictionaries for material display only.

No Source/tool argument conversion, Store read, selection, ranking or schema repair.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from milai_lab.contracts.public_memory_contracts import DECODE_GUIDANCE


def _scalar(value: Any) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float and math.isfinite(value):
        return
    raise ValueError("COMPACT_EXACT_NON_JSON_VALUE")


def encode(value: Any) -> dict[str, Any]:
    counts: Counter[str] = Counter()

    def scan(v: Any) -> None:
        if type(v) is dict:
            if any(type(k) is not str for k in v):
                raise ValueError("COMPACT_EXACT_KEY_INVALID")
            for x in v.values():
                scan(x)
        elif type(v) is list:
            for x in v:
                scan(x)
        else:
            _scalar(v)
            if type(v) is str and len(v.encode()) >= 8:
                counts[v] += 1

    scan(value)
    strings = [s for s, count in counts.items() if count > 1]
    string_ids = {s: i for i, s in enumerate(strings)}
    layouts: list[list[str]] = []
    layout_ids: dict[tuple[str, ...], int] = {}

    def node(v: Any) -> Any:
        if type(v) is dict:
            keys = tuple(v)
            if keys not in layout_ids:
                layout_ids[keys] = len(layouts)
                layouts.append(list(keys))
            return {"o": [layout_ids[keys], [node(x) for x in v.values()]]}
        if type(v) is list:
            return [node(x) for x in v]
        if type(v) is str and v in string_ids:
            return {"s": string_ids[v]}
        return v

    root = node(value)
    return {
        "format": "json_dictionary_v1",
        "decode": DECODE_GUIDANCE,
        "key_layouts": layouts,
        "strings": strings,
        "root": root,
    }


def decode(frame: dict[str, Any]) -> Any:
    if (
        type(frame) is not dict
        or set(frame)
        != {
            "format",
            "decode",
            "key_layouts",
            "strings",
            "root",
        }
        or frame["format"] != "json_dictionary_v1"
        or frame["decode"] != DECODE_GUIDANCE
    ):
        raise ValueError("COMPACT_EXACT_FRAME_INVALID")
    layouts, strings = frame["key_layouts"], frame["strings"]
    if (
        type(layouts) is not list
        or type(strings) is not list
        or any(type(s) is not str for s in strings)
        or len(set(strings)) != len(strings)
    ):
        raise ValueError("COMPACT_EXACT_TABLE_INVALID")
    for layout in layouts:
        if (
            type(layout) is not list
            or any(type(k) is not str for k in layout)
            or len(set(layout)) != len(layout)
        ):
            raise ValueError("COMPACT_EXACT_LAYOUT_INVALID")
    if len({tuple(x) for x in layouts}) != len(layouts):
        raise ValueError("COMPACT_EXACT_LAYOUT_DUPLICATED")

    def index(v: Any, table: list[Any]) -> int:
        if type(v) is not int or not 0 <= v < len(table):
            raise ValueError("COMPACT_EXACT_INDEX_INVALID")
        return v

    def node(v: Any) -> Any:
        if type(v) is list:
            return [node(x) for x in v]
        if type(v) is dict:
            if set(v) == {"s"}:
                return strings[index(v["s"], strings)]
            if set(v) != {"o"} or type(v["o"]) is not list or len(v["o"]) != 2:
                raise ValueError("COMPACT_EXACT_NODE_INVALID")
            layout_index, values = v["o"]
            keys = layouts[index(layout_index, layouts)]
            if type(values) is not list or len(values) != len(keys):
                raise ValueError("COMPACT_EXACT_VALUES_INVALID")
            return {k: node(x) for k, x in zip(keys, values, strict=True)}
        _scalar(v)
        return v

    return node(frame["root"])
