"""Pure semantic material shared by the Host and benchmark Readers.

Callers acquire visible versions, revision views and original evidence. This
projection neither reads the Store nor changes access, state or source delivery.
"""

from __future__ import annotations

import copy
from typing import Any

from milai_lab.memory.edit_units import read_applicability, render_state


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
    unit = {**copy.deepcopy(stored), **copy.deepcopy(projected)}
    if isinstance(stored.get("assertion"), dict) and isinstance(projected.get("assertion"), dict):
        assertion = {**copy.deepcopy(stored["assertion"]), **copy.deepcopy(projected["assertion"])}
        old_links = stored["assertion"].get("evidence_links", {})
        for stance, links in assertion.get("evidence_links", {}).items():
            # revision_view shortens these links to their actual range identities.
            # Keep explicit role/clock/support values next to the assertion too.
            assertion["evidence_links"][stance] = [
                {**copy.deepcopy(next(
                    (old for old in old_links.get(stance, []) if _contains(old, link)), {}
                )), **link}
                for link in links
            ]
        unit["assertion"] = assertion
    return unit


def project_record(
    record: dict[str, Any], *, edit_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one explicit unit view, retaining unproven rendered expressions.

    ``applicability`` accepts the existing EditMemory.revision_view result or a
    ``statements`` list from read_applicability. Its public metadata stays explicit;
    there are no inherited values or nested JSON references. Actual stored unit
    metadata supplies role, assertion and support when ``edit_state`` is provided.
    ``revision_evidence`` is copied unchanged, including every original body.

    ``content_projection`` reports ``exact_rendered_units`` only when the complete
    supplied content equals render_state(edit_state). Otherwise it reports
    ``retained_unproven`` and keeps content. A previously projected record can be
    passed again without its state; it retains its existing proof and unit view.
    """
    result = copy.deepcopy(record)
    view = result.get("applicability")
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
    return result
