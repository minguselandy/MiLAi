"""Pure semantic material shared by the Host and benchmark Readers.

Callers acquire visible versions, revision views and original evidence. This
projection neither reads the Store nor changes access, state or source delivery.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any, cast

from milai_lab.memory.edit_units import read_applicability, render_state

PROJECTION_INSTRUCTIONS = (
    "A field containing only meta gives the exact complete JSON value in "
    "the delivered metadata_table. Each table entry is literal and needs one lookup; "
    "entries contain no further references or inherited defaults. Explicit nulls "
    "remain unknown. Named metadata/context groups contain explicit disjoint fields. "
    "report_source occurred_at/observed_at give report/capture clocks, never event/onset. "
    "source_table rows give their original source identity in source_key. Original "
    "evidence content and its range remain literal."
)

_METADATA_OBJECTS = {
    "comparison_basis", "time_values", "from_time", "until_time",
    "source_metadata", "query_context", "applicability_metadata",
    "report_source", "interpretation_context",
}
_SOURCE_FIELDS = {"source_revision", "role", "occurred_at", "observed_at", "calendar_context"}
_QUERY_FIELDS = {"version_time", "query_time", "query_calendar_context"}
_APPLICABILITY_FIELDS = {
    "event_at", "effective_from", "effective_until", "bound_effective_limits",
    "combined_effective_from", "combined_effective_until", "time_values", "status",
    "interval_convention", "comparison_basis", "retrospective", "reported_after_query",
}
_CONTEXT_FIELDS = {
    "calendar_context_semantics", "selection_policy", "completion_status", "semantic_support",
}
_METADATA_STRINGS = {
    "source_ref", "evidence_id", "fragment_handle", "occurred_at", "observed_at",
    "reported_at", "captured_at", "query_time", "version_time",
    "source_unit", "target_unit", "unit_id", "current_unit_id", "relation_id",
    "source_key",
}


def _reader_diagnostics(view: dict[str, Any]) -> None:
    """Keep the old Reader's semantic clock information and explicit unknowns.

    Parsed report/capture/query diagnostics are redundant with delivered raw
    clocks. A differing per-unit parse value, including null, remains explicit.
    """
    view_clocks = view.pop("time_values", {})
    source_clocks = {
        ref: source.pop("time_values", {}) for ref, source in view.get("source_table", {}).items()
    }
    for unit in view.get("units", []):
        assertion = unit.get("assertion") or {}
        temporal = unit.get("temporal") or {}
        clocks = temporal.get("time_values", {})
        for field in ("reported_at", "captured_at", "query_time", "version_time"):
            origin = (view_clocks if field in {"query_time", "version_time"}
                      else source_clocks.get(assertion.get("source_ref"), {}))
            if clocks.get(field) is not None and field in origin and clocks[field] == origin[field]:
                clocks.pop(field)
        for field in (
            "event_at", "effective_from", "effective_until", "bound_effective_limits",
            "combined_effective_from", "combined_effective_until", "time_values",
        ):
            if field in temporal and temporal[field] in (None, [], {}):
                temporal.pop(field)
        # These are derived absence descriptors, not source metadata overrides.
        for field in ("declared_scope", "applies_under", "general_rules", "exceptions"):
            if field in unit and unit[field] in (None, [], {}):
                unit.pop(field)


def _share_metadata(record: dict[str, Any]) -> None:
    """Share exact repeated values in one flat table, never inside table entries."""
    counts: Counter[str] = Counter()

    def encoded(value: Any, field: str) -> str | None:
        eligible = (
            (field in _METADATA_OBJECTS and isinstance(value, (dict, list)))
            or (field in _METADATA_STRINGS and isinstance(value, str))
        )
        if not eligible:
            return None
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def count(value: Any, field: str = "") -> None:
        if field == "scope" and isinstance(value, dict):
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
        if field == "scope" and isinstance(value, dict):
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
            return {name: share(item, "source_description" if field == "source_table" else name)
                    for name, item in value.items()}
        if isinstance(value, list):
            return [share(item, "source_description" if field == "source_table" else "")
                    for item in value]
        return value

    shared = share(record)

    def restore_single(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            if field == "scope":
                return value
            if (set(value) == {"meta"} and field in (
                _METADATA_OBJECTS | _METADATA_STRINGS | {"source_description"}
            ) and uses[value["meta"]] < 2):
                return table[str(value["meta"])]
            return {key: restore_single(item,
                                        "source_description" if field == "source_table" else key)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [restore_single(item, "source_description" if field == "source_table" else "")
                    for item in value]
        return value

    shared = restore_single(shared)
    repeated = {key: value for key, value in table.items() if uses[int(key)] >= 2}
    if repeated:
        record.clear()
        record.update(shared)
        record["metadata_table"] = repeated


def _group_metadata(view: dict[str, Any]) -> None:
    """Make repeated source/query/limit descriptions explicit single-value blocks."""
    if isinstance(view.get("source_table"), dict):
        # A dictionary key cannot carry an exact short reference. Explicit rows
        # let repeated source identities share the same one-step value table.
        view["source_table"] = [
            {"source_key": ref, "source_metadata": source}
            for ref, source in view["source_table"].items()
        ]
    for name, fields in (("query_context", _QUERY_FIELDS),
                         ("interpretation_context", _CONTEXT_FIELDS)):
        values = {field: view.pop(field) for field in list(view) if field in fields}
        if values:
            view[name] = values
    for unit in view.get("units", []):
        assertion = unit.get("assertion") or {}
        source = {field: assertion.pop(field)
                  for field in list(assertion) if field in _SOURCE_FIELDS}
        if source:
            assertion["source_metadata"] = source
        temporal = unit.get("temporal") or {}
        if ("reported_at" in temporal and "captured_at" in temporal
                and "occurred_at" in source and "observed_at" in source
                and temporal["reported_at"] == source["occurred_at"]
                and temporal["captured_at"] == source["observed_at"]):
            temporal.pop("reported_at")
            temporal.pop("captured_at")
            temporal["report_source"] = copy.deepcopy(source)
        for name, fields in (
            ("query_context", _QUERY_FIELDS), ("applicability_metadata", _APPLICABILITY_FIELDS),
        ):
            values = {field: temporal.pop(field) for field in list(temporal) if field in fields}
            if values:
                temporal[name] = values


def expand_record(record: dict[str, Any]) -> dict[str, Any]:
    """Expand direct metadata for adapters needing literal tool IDs or paging."""
    result = copy.deepcopy(record)
    table = result.pop("metadata_table", {})

    def expand(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            if field == "scope":
                return value
            if set(value) == {"meta"} and field in (
                _METADATA_OBJECTS | _METADATA_STRINGS | {"source_description"}
            ):
                return copy.deepcopy(table[str(value["meta"])])
            return {key: expand(item, "source_description" if field == "source_table" else key)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item, "source_description" if field == "source_table" else "")
                    for item in value]
        return value

    result = cast(dict[str, Any], expand(result))
    view = result.get("applicability")
    if isinstance(view, dict):
        for name in ("query_context", "interpretation_context"):
            if name in view:
                view.update(view.pop(name))
    if isinstance(view, dict) and isinstance(view.get("source_table"), list):
        view["source_table"] = {
            source["source_key"]: source["source_metadata"]
            for source in view["source_table"]
        }
    for unit in view.get("units", []) if isinstance(view, dict) else []:
        for field, groups in (
            ("assertion", ("source_metadata",)),
            ("temporal", ("query_context", "applicability_metadata")),
        ):
            values = unit.get(field) or {}
            for name in groups:
                if name in values:
                    values.update(values.pop(name))
            if field == "temporal" and "report_source" in values:
                source = values.pop("report_source")
                values.update(reported_at=source["occurred_at"], captured_at=source["observed_at"])
    return result


def project_material(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Use one flat exact-value table for all already acquired Reader records.

    To restore a member's literal tool IDs and fields, pass its dictionary plus
    this result's ``metadata_table`` to ``expand_record``.
    """
    memories = [expand_record(project_record(record)) for record in records]
    for memory in memories:
        memory.pop("retrieval_navigation", None)
        view = memory.get("applicability")
        if isinstance(view, dict):
            _group_metadata(view)
    result = {"memories": memories}
    _share_metadata(result)
    return result


def _contains(actual: Any, selected: Any) -> bool:
    """An inline relation may become an ID only when its values remain available."""
    if isinstance(selected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value) for key, value in selected.items()
        )
    if isinstance(selected, list):
        return isinstance(actual, list) and len(actual) == len(selected) and all(
            _contains(old, current) for old, current in zip(actual, selected, strict=True)
        )
    return bool(actual == selected)


def _unit_metadata(stored: dict[str, Any], projected: dict[str, Any]) -> dict[str, Any]:
    unit = copy.deepcopy(projected)
    # The revision view already contains the delivered assertion/support fields.
    # Issued writer handles and undelivered link metadata are not Reader facts.
    for field in ("role", "local_exception"):
        if field in stored:
            unit.setdefault(field, copy.deepcopy(stored[field]))
    return unit


def project_record(
    record: dict[str, Any], *, edit_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one explicit unit view, retaining unproven rendered expressions.

    ``applicability`` accepts the existing EditMemory.revision_view result or a
    ``statements`` list from read_applicability. Repeated complete metadata values
    use direct IDs in one flat table, with no inherited or nested references. Stored unit
    metadata supplies structural role when ``edit_state`` is provided; it does not
    expand support beyond the supplied revision view.
    Original ``revision_evidence`` bodies and ranges remain literal; its repeated
    metadata may use direct IDs and is unchanged after ``expand_record``.

    ``content_projection`` reports ``exact_rendered_units`` only when the complete
    supplied content equals render_state(edit_state). Otherwise it reports
    ``retained_unproven`` and keeps content. A previously projected record can be
    passed again without its state; it retains its existing proof and unit view.
    """
    result = copy.deepcopy(record)
    if "metadata_table" in result:
        return result
    view = result.get("applicability")
    if isinstance(view, dict) and (
        isinstance(view.get("source_table"), list)
        or "query_context" in view or "interpretation_context" in view
    ):
        # A small projection may have no repeated metadata to put in a table.
        return result
    if not isinstance(view, dict) and edit_state is not None:
        view = {
            "representation": edit_state["representation"],
            "matter": edit_state.get("matter_description"),
            "units": list(read_applicability(edit_state).values()),
            "relations": copy.deepcopy(edit_state["relations"]),
        }
    if not isinstance(view, dict):
        return result
    units = view.get("units", view.get("statements"))
    if not isinstance(units, list):
        return result

    proved_state = False
    if edit_state is not None:
        stored = edit_state["units"]
        proved_state = (
            view.get("representation", edit_state["representation"])
            == edit_state["representation"]
            and [(unit.get("unit_id"), unit.get("text")) for unit in units]
            == [(unit["unit_id"], unit["text"]) for unit in stored]
            and all(
                _contains(old[field], current[field])
                for old, current in zip(stored, units, strict=True)
                for field in old if field in current
            )
            and (
                "relations" not in view
                or (
                    len(view["relations"]) == len(edit_state["relations"])
                    and all(_contains(current, old) for old, current in zip(
                        edit_state["relations"], view["relations"], strict=True,
                    ))
                )
            )
        )
        if proved_state:
            units = [_unit_metadata(old, current)
                     for old, current in zip(stored, units, strict=True)]
            view["representation"] = edit_state["representation"]
            view.setdefault("relations", copy.deepcopy(edit_state["relations"]))
            if "matter_description" in edit_state:
                view.setdefault("matter", edit_state["matter_description"])

    # read_revision_view already uses unit IDs. The older applicability list
    # contains literal related statements; replace only exact available copies.
    by_id = {unit["unit_id"]: copy.deepcopy(unit) for unit in units}
    for unit in units:
        for field in ("applies_under", "general_rules", "exceptions"):
            if field in unit:
                unit[field] = [
                    related["unit_id"]
                    if isinstance(related, dict) and related.get("unit_id") in by_id
                    and _contains(by_id[related["unit_id"]], related)
                    else related
                    for related in unit[field]
                ]
    view.pop("statements", None)
    view["units"] = units
    result["applicability"] = view
    if "content" in result:
        if (proved_state and edit_state is not None
                and result["content"] == render_state(edit_state)):
            result.pop("content")
            result["content_projection"] = "exact_rendered_units"
        else:
            result["content_projection"] = "retained_unproven"
    _reader_diagnostics(view)
    _group_metadata(view)
    _share_metadata(result)
    return result
