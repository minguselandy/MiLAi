"""Lossless binding references for already selected ordinary evidence units."""

from __future__ import annotations

import json
from typing import Any


def compact_units(
    units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Share complete bindings; do not read the bank, select a revision or alter bodies."""
    values = json.loads(json.dumps(units, ensure_ascii=False, allow_nan=False))
    table: list[dict[str, Any]] = []
    keys: dict[str, int] = {}
    record_ids = list(
        dict.fromkeys(
            unit["record"]["id"]
            for unit in values
            if unit["type"] in {"record", "historical_record"}
        )
    )
    scopes: list[Any] = []
    scope_counts: dict[str, int] = {}
    scope_keys: dict[str, int] = {}
    for unit in values:
        scope = unit.get("record", {}).get("scope")
        if scope:
            key = json.dumps(scope, ensure_ascii=False, sort_keys=True, allow_nan=False)
            scope_counts[key] = scope_counts.get(key, 0) + 1

    def read_pointer(value: Any) -> None:
        if not isinstance(value, dict):
            return
        if value.get("tool") == "read_memory" and value.get("id") in record_ids:
            value["record_id_index"] = record_ids.index(value.pop("id"))
        if value.get("tool") in {"read_memory", "read_source"} and "source_ref" in value:
            indices = [
                index
                for index, binding in enumerate(table)
                if binding["source_ref"] == value["source_ref"]
            ]
            if len(indices) == 1:
                value["source_binding_index"] = indices[0]
                value.pop("source_ref")

    def register(binding: dict[str, Any]) -> int:
        key = json.dumps(binding, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if key not in keys:
            keys[key] = len(table)
            table.append(binding)
        return keys[key]

    def bindings(value: Any) -> bool:
        return isinstance(value, list) and all(
            isinstance(row, dict)
            and all(isinstance(row.get(key), str) for key in ("source_ref", "role"))
            for row in value
        )

    for unit in values:
        for value in (unit.get("source_bindings"), unit.get("record", {}).get("source_bindings")):
            if bindings(value):
                for binding in value:
                    register(binding)
        if unit["type"] == "source":
            register(
                {
                    "source_ref": unit["source_ref"],
                    "role": unit["role"],
                    "source_revision": unit["source_revision"],
                }
            )

    for unit in values:
        record = unit.get("record", {})
        expected_id = (
            "record:" + record["id"]
            if unit["type"] == "record"
            else "history:" + record["id"] + ":" + str(record["revision"])
            if unit["type"] == "historical_record"
            else None
        )
        if expected_id is not None and unit.get("unit_id") == expected_id:
            unit.pop("unit_id")
        if expected_id is not None:
            record["record_id_index"] = record_ids.index(record.pop("id"))
        scope = record.get("scope")
        if scope:
            key = json.dumps(scope, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if scope_counts[key] > 1:
                if key not in scope_keys:
                    scope_keys[key] = len(scopes)
                    scopes.append(scope)
                record["scope_index"] = scope_keys[key]
                record.pop("scope")
        for target in (unit, record):
            value = target.get("source_bindings")
            if not bindings(value):
                continue
            target["source_binding_indices"] = [register(binding) for binding in value]
            target.pop("source_bindings")
            if record.get("source_refs") == [binding["source_ref"] for binding in value]:
                record.pop("source_refs")
                record["source_refs_from_bindings"] = True
        if unit["type"] == "source":
            unit["source_binding_index"] = register(
                {
                    "source_ref": unit.pop("source_ref"),
                    "role": unit.pop("role"),
                    "source_revision": unit.pop("source_revision"),
                }
            )
        for match in record.get("source_matches", []):
            indices = [
                index
                for index, binding in enumerate(table)
                if binding["source_ref"] == match["source_ref"]
                and binding.get("source_revision", 1) == match["source_revision"]
            ]
            if len(indices) == 1:
                match["source_binding_index"] = indices[0]
                match.pop("source_ref")
                match.pop("source_revision")
            read_pointer(match.get("read_more"))
        for pointer in (
            unit.get("read_more"),
            record.get("read_more"),
            record.get("history_index", {}).get("read_more"),
            record.get("source_matches_read_more"),
        ):
            read_pointer(pointer)
    tables: dict[str, Any] = {"source_binding_table": table}
    if record_ids:
        tables["record_id_table"] = record_ids
    if scopes:
        tables["scope_table"] = scopes
    groups = {
        "record": [unit["record"] for unit in values if "record" in unit],
        "history_index": [
            unit["record"]["history_index"]
            for unit in values
            if "history_index" in unit.get("record", {})
        ],
        "source_match": [
            match for unit in values for match in unit.get("record", {}).get("source_matches", [])
        ],
    }
    defaults = {}
    for name, rows in groups.items():
        if len(rows) < 2:
            continue
        shared = {
            key: value
            for key, value in rows[0].items()
            if key
            not in {
                "content",
                "fields",
                "scope",
                "object_ref",
                "candidate_handle",
                "id",
                "record_id_index",
                "revision",
                "source_refs",
                "source_binding_indices",
                "read_more",
                "history_index",
                "source_matches",
            }
            and all(
                key in row
                and json.dumps(row[key], sort_keys=True, allow_nan=False)
                == json.dumps(value, sort_keys=True, allow_nan=False)
                for row in rows[1:]
            )
        }
        if shared:
            defaults[name] = shared
            for row in rows:
                for key in shared:
                    row.pop(key)
    if defaults:
        tables["shared_defaults"] = defaults
    return values, tables
