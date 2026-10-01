"""Reversible display indices into one actual record's complete leaf binding table."""
from __future__ import annotations

import json
from typing import Any


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _index(value: Any, size: int) -> int:
    if type(value) is not int or not 0 <= value < size:
        raise ValueError("V13_SUPPORT_DISPLAY_INDEX_INVALID")
    return value


def encode_field_support(
    fields: dict[str, Any], bindings: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Only literal tuple equality shares an index; the Stored map is untouched."""
    result: dict[str, Any] = {}
    parents: list[dict[str, Any]] = []
    binding_literals = [_literal(row) for row in bindings]
    parent_literals: list[str] = []
    for field, entry in fields.items():
        refs, leaves = entry["source_refs"], entry["source_bindings"]
        if refs != [row["source_ref"] for row in leaves]:
            raise ValueError("V13_SUPPORT_DISPLAY_BINDING_MISMATCH")
        indices = []
        for leaf in leaves:
            literal = _literal(leaf)
            if literal not in binding_literals:
                raise ValueError("V13_SUPPORT_DISPLAY_BINDING_MISMATCH")
            indices.append(binding_literals.index(literal))
        value = {k: _copy(v) for k, v in entry.items()
                 if k not in {"source_refs", "source_bindings", "reused_from"}}
        value["record_source_indices"] = indices
        if "reused_from" in entry:
            parent = entry["reused_from"]
            literal = _literal(parent)
            if literal not in parent_literals:
                parents.append(_copy(parent))
                parent_literals.append(literal)
            value["reused_from_index"] = parent_literals.index(literal)
        result[field] = value
    return result, parents


def expand_field_support(
    fields: dict[str, Any], bindings: list[dict[str, Any]], parents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Decode explicit indices after ordinary compact record bindings are expanded.

    This provides no tool argument coercion, candidate/source selection or semantic check.
    """
    result = {}
    for field, entry in fields.items():
        leaves = [_copy(bindings[_index(i, len(bindings))])
                  for i in entry["record_source_indices"]]
        value = {k: _copy(v) for k, v in entry.items()
                 if k not in {"record_source_indices", "reused_from_index"}}
        value.update(source_refs=[row["source_ref"] for row in leaves], source_bindings=leaves)
        if "reused_from_index" in entry:
            value["reused_from"] = _copy(parents[_index(entry["reused_from_index"], len(parents))])
        result[field] = value
    return result
