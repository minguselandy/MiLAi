"""Pure literal sharing for Reader packets and complete controller observations."""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any, cast

_METADATA_OBJECTS = {
    "comparison_basis",
    "time_values",
    "from_time",
    "until_time",
    "source_metadata",
    "query_context",
    "applicability_metadata",
    "report_source",
    "interpretation_context",
}

_METADATA_STRINGS = {
    "source_ref",
    "evidence_id",
    "fragment_handle",
    "occurred_at",
    "observed_at",
    "reported_at",
    "captured_at",
    "query_time",
    "version_time",
    "source_unit",
    "target_unit",
    "unit_id",
    "current_unit_id",
    "relation_id",
    "source_key",
}

_OBSERVATION_STRINGS = _METADATA_STRINGS | {
    "content",
    "text",
    "excerpt",
    "delivery",
    "origin",
    "id",
    "kind",
    "label",
    "mode",
    "status",
    "target",
    "visibility",
    "source_discovery",
    "built_for",
    "semantics",
    "date",
    "source",
    "role",
    "request",
}

_OBSERVATION_LITERALS = {"task", "metadata_table"}

_OBSERVATION_INSTRUCTIONS = (
    "meta fields refer to metadata_table's complete literal JSON values, with no nested "
    "references. table denotes an object list: merge shared fields with each row's column "
    "values. literal holds original object fields as key/value pairs. Source identities, "
    "roles, clocks, unknowns and order are unchanged; text sharing never merges sources."
)


def project_observation_state(state: dict[str, Any]) -> dict[str, Any]:
    """Share literal values and repeated field names without dropping observations.

    The caller supplies a MemoryControlState projection. Its task stays literal;
    source bodies are never interpreted. This is an input representation, not
    a relevance filter, source merge, Store mutation or reusable encoder state.
    """
    if "observation_encoding" in state:
        return copy.deepcopy(state)
    result = copy.deepcopy(state)
    _share_metadata(
        result, string_fields=_OBSERVATION_STRINGS, literal_fields=_OBSERVATION_LITERALS
    )
    tables_written = 0

    def compact(value: Any) -> Any:
        nonlocal tables_written
        if isinstance(value, dict):
            fields = {
                key: item if key in _OBSERVATION_LITERALS | {"scope"} else compact(item)
                for key, item in value.items()
            }
            # Escape producer objects that have the representation's reserved shape.
            return (
                {"literal": list(fields.items())}
                if set(fields) in ({"table"}, {"literal"})
                else fields
            )
        if not isinstance(value, list):
            return value
        items = [compact(item) for item in value]
        if len(items) < 2 or not all(
            isinstance(item, dict) and set(item) == set(items[0]) for item in items
        ):
            return items
        keys = list(items[0])
        values = {key: [json.dumps(item[key], sort_keys=True) for item in items] for key in keys}
        shared = {key: items[0][key] for key in keys if len(set(values[key])) == 1}
        columns = [key for key in keys if key not in shared]
        table = {
            "table": {
                "columns": columns,
                "shared": shared,
                "rows": [[item[key] for key in columns] for item in items],
            }
        }
        if len(json.dumps(table)) < len(json.dumps(items)):
            tables_written += 1
            return table
        return items

    result = cast(dict[str, Any], compact(result))
    if "metadata_table" not in result and not tables_written:
        return copy.deepcopy(state)
    result["observation_encoding"] = {
        "format": "literal_tables_v1",
        "instructions": _OBSERVATION_INSTRUCTIONS,
    }
    return result


def expand_observation_state(state: dict[str, Any]) -> dict[str, Any]:
    """Restore the exact JSON state, including table-shaped literal source metadata."""
    result = copy.deepcopy(state)
    encoding = result.pop("observation_encoding", None)
    if encoding is None:
        return result

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"table"}:
                table = value["table"]
                return [
                    expand({**table["shared"], **dict(zip(table["columns"], row, strict=True))})
                    for row in table["rows"]
                ]
            if set(value) == {"literal"}:
                return {key: expand(item) for key, item in value["literal"]}
            return {
                key: item if key in _OBSERVATION_LITERALS | {"scope"} else expand(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return _expand_metadata(
        cast(dict[str, Any], expand(result)),
        string_fields=_OBSERVATION_STRINGS,
        literal_fields=_OBSERVATION_LITERALS,
    )


def _share_metadata(
    record: dict[str, Any],
    *,
    extra_objects: set[str] | None = None,
    string_fields: set[str] | None = None,
    literal_fields: set[str] | None = None,
) -> None:
    """Share exact repeated values in one flat table, never inside table entries."""
    counts: Counter[str] = Counter()
    object_fields = _METADATA_OBJECTS | (extra_objects or set())
    strings = _METADATA_STRINGS if string_fields is None else string_fields
    literal = {"scope"} | (literal_fields or set())

    def encoded(value: Any, field: str) -> str | None:
        eligible = (field in object_fields and isinstance(value, (dict, list))) or (
            field in strings and isinstance(value, str)
        )
        if not eligible:
            return None
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def count(value: Any, field: str = "") -> None:
        if field in literal:
            return
        key = encoded(value, field)
        if key is not None:
            counts[key] += 1
        if isinstance(value, dict):
            for name, item in value.items():
                count(item, "source_description" if field == "source_table" else name)
        elif isinstance(value, list):
            for item in value:
                count(item, "source_description" if field == "source_table" else "")

    count(record)
    identifiers: dict[str, int] = {}
    table: dict[str, Any] = {}
    uses: Counter[int] = Counter()

    def share(value: Any, field: str = "") -> Any:
        if field in literal:
            return value
        key = encoded(value, field)
        if key is not None and counts[key] > 1 and len(key) >= 20:
            if key not in identifiers:
                identifier = len(table)
                identifiers[key] = identifier
                table[str(identifier)] = copy.deepcopy(value)
            identifier = identifiers[key]
            uses[identifier] += 1
            return {"meta": identifier}
        if isinstance(value, dict):
            return {
                name: share(item, "source_description" if field == "source_table" else name)
                for name, item in value.items()
            }
        if isinstance(value, list):
            return [
                share(item, "source_description" if field == "source_table" else "")
                for item in value
            ]
        return value

    shared = share(record)

    def restore_single(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            if field in literal:
                return value
            if (
                set(value) == {"meta"}
                and field in (object_fields | strings | {"source_description"})
                and uses[value["meta"]] < 2
            ):
                return table[str(value["meta"])]
            return {
                key: restore_single(item, "source_description" if field == "source_table" else key)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                restore_single(item, "source_description" if field == "source_table" else "")
                for item in value
            ]
        return value

    shared = restore_single(shared)
    repeated = {key: value for key, value in table.items() if uses[int(key)] >= 2}
    if repeated:
        record.clear()
        record.update(shared)
        record["metadata_table"] = repeated


def _expand_metadata(
    record: dict[str, Any],
    *,
    extra_objects: set[str] | None = None,
    string_fields: set[str] | None = None,
    literal_fields: set[str] | None = None,
) -> dict[str, Any]:
    result = copy.deepcopy(record)
    table = result.pop("metadata_table", {})
    object_fields = _METADATA_OBJECTS | (extra_objects or set())
    strings = _METADATA_STRINGS if string_fields is None else string_fields
    literal = {"scope"} | (literal_fields or set())

    def expand(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            if field in literal:
                return value
            if set(value) == {"meta"} and field in (
                object_fields | strings | {"source_description"}
            ):
                return copy.deepcopy(table[str(value["meta"])])
            return {
                key: expand(item, "source_description" if field == "source_table" else key)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                expand(item, "source_description" if field == "source_table" else "")
                for item in value
            ]
        return value

    return cast(dict[str, Any], expand(result))
