"""Small, source-bound AND/OR support sets inside existing record revisions."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from milai_lab.memory.functional_state import FunctionalRejection


def retain_support_groups(state: dict[str, Any], previous: dict[str, Any] | None = None) -> None:
    """A removed premise removes its whole AND route, never just that conjunct.

    An empty alternatives list remains explicit: no stored route survives. This
    does not retract or negate the target claim. An editor must reconsider it.
    """
    if "support_groups" not in state:
        return
    ids = {unit["unit_id"] for unit in state["units"]}
    state["support_groups"] = [
        {**group, "alternatives": [route for route in group["alternatives"] if set(route) <= ids]}
        for group in state["support_groups"] if group["target_unit"] in ids
    ]
    if previous is not None:
        old = {unit["unit_id"]: unit for unit in previous["units"]}
        changed = {unit["unit_id"] for unit in state["units"] if unit["unit_id"] in old and any(
            unit.get(field) != old[unit["unit_id"]].get(field)
            for field in ("text", "role", "assertion"))}
        for group in state["support_groups"]:
            if group["target_unit"] in changed:
                group["changed_target"] = True
            premises = {uid for route in group["alternatives"] for uid in route}
            pending = (set(group.get("changed_premises", [])) | changed) & premises
            if pending:
                group["changed_premises"] = sorted(pending)
            else:
                group.pop("changed_premises", None)


def apply_support_groups(
    state: dict[str, Any], changes: list[dict[str, Any]], *, old: dict[str, Any] | None = None,
) -> None:
    """Bind local generation references after the existing unit edits, before commit."""
    retain_support_groups(state)
    old_ids = {unit["unit_id"] for unit in old["units"]} if old else set()
    generated = [unit["unit_id"] for unit in state["units"] if unit["unit_id"] not in old_ids]
    ids = {unit["unit_id"] for unit in state["units"]}
    groups = {group["target_unit"]: copy.deepcopy(group)
              for group in state.get("support_groups", [])}

    def resolve(reference: dict[str, Any], *, removing: bool = False) -> str:
        if "generated" in reference:
            index = reference["generated"]
            if not 0 <= index < len(generated):
                raise FunctionalRejection("EDIT_SUPPORT_GENERATED_UNIT_UNAVAILABLE")
            return str(generated[index])
        unit_id = reference["existing"]
        if unit_id not in ids and not (removing and unit_id in old_ids):
            raise FunctionalRejection("EDIT_SUPPORT_UNIT_UNAVAILABLE")
        return str(unit_id)

    changed = set()
    for change in changes:
        # Unit retraction already removes its support group. Explicitly
        # removing that same base target's group is harmless cleanup, not a
        # dangling new relationship. Setting groups still requires a live target.
        target = resolve(change["target"], removing=change["operation"] == "remove")
        if target in changed:
            raise FunctionalRejection("EDIT_SUPPORT_TARGET_REPEATED")
        changed.add(target)
        if change["operation"] == "remove":
            groups.pop(target, None)
            continue
        alternatives = [list(dict.fromkeys(resolve(ref) for ref in route))
                        for route in change["alternatives"]]
        groups[target] = {
            "group_id": (groups[target]["group_id"] if target in groups
                         else "support-" + str(uuid.uuid4())),
            "target_unit": target, "alternatives": alternatives,
            "evidence_refs": copy.deepcopy(change["evidence_refs"]),
        }
    if changes or "support_groups" in state:
        state["support_groups"] = list(groups.values())


def support_status(group: dict[str, Any], applicability: dict[str, bool | None]) -> str:
    """Three-valued OR-of-AND evaluation; absent applicability stays unknown."""
    if group.get("changed_target"):
        return "unknown"
    unknown = False
    for route in group["alternatives"]:
        values = [None if uid in group.get("changed_premises", []) else applicability.get(uid)
                  for uid in route]
        if any(value is False for value in values):
            continue
        if all(value is True for value in values):
            return "supported"
        unknown = True
    return "unknown" if unknown else "unsupported"


def select_support_routes(
    state: dict[str, Any], selected: set[str], *,
    choices: dict[str, list[int]] | None = None,
) -> tuple[set[str], list[dict[str, Any]]]:
    """Expand selected alternatives as whole groups; never split an AND route.

    ``choices`` is query-local model output keyed by the actual target unit.
    Without a choice all routes remain candidates, rather than guessing which
    free-text premise applies. Scope/time judgments remain explicit inputs.
    """
    chosen = []
    expanded = set(selected)
    for group in state.get("support_groups", []):
        target = group["target_unit"]
        if target not in selected:
            continue
        indexes = (choices or {}).get(target, list(range(len(group["alternatives"]))))
        routes = [group["alternatives"][index] for index in dict.fromkeys(indexes)]
        expanded.update(uid for route in routes for uid in route)
        chosen.append({**copy.deepcopy(group), "alternatives": copy.deepcopy(routes),
                       "selected_route_indices": list(dict.fromkeys(indexes)),
                       "total_routes": len(group["alternatives"])})
    return expanded, chosen
