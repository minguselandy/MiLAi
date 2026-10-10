"""Small reference-only working state over already delivered memory snapshots."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

EVIDENCE_TYPES = (
    "current_interpretation", "saved_history", "original_source", "live_business",
)


def empty_view() -> dict[str, Any]:
    return {"focus": None, "read_goal": None, "resident_refs": [], "pending_refs": []}


def plan_delivery(
    selected_refs: list[dict[str, Any]],
    fits: Callable[[list[dict[str, Any]]], bool],
) -> dict[str, Any]:
    """Plan whole semantic matters using the caller's complete request cost.

    The selected order and every reference remain explicit, including a matter
    that cannot fit alone. Pages are delivery choices, never summaries or proof
    that their bodies have already reached a model. Previously read references
    remain loadable through the same caller-owned snapshot.
    """
    selected = copy.deepcopy(selected_refs)
    if fits(selected):
        return {"selected_refs": selected, "pages": [selected] if selected else [],
                "unavailable_refs": [], "fits_together": True}
    pages: list[list[dict[str, Any]]] = []
    page: list[dict[str, Any]] = []
    unavailable = []
    for ref in selected:
        if fits([*page, ref]):
            page.append(ref)
            continue
        if page:
            pages.append(page)
            page = []
        if fits([ref]):
            page = [ref]
        else:
            unavailable.append(ref)
    if page:
        pages.append(page)
    return {"selected_refs": selected, "pages": pages,
            "unavailable_refs": unavailable, "fits_together": False}


def item_ref(item: dict[str, Any], snapshot_id: str, unit_index: int) -> dict[str, Any]:
    source = item["type"] == "fragment"
    return {
        "kind": "source" if source else "record",
        "id": item["source_ref"] if source else item["record_id"],
        "revision": item.get("source_revision", 1) if source else item["revision"],
        "view": "original_source" if source else item["version_view"],
        "range": [item["start"], item["end"]] if source else item["content_range"],
        **({"unit_id": item["edit_unit"]["unit_id"]} if "edit_unit" in item else {}),
        "snapshot_id": snapshot_id,
        "unit_index": unit_index,
    }


def material_ref(snapshot_id: str, item_index: int) -> dict[str, Any]:
    """Locate one actual retrieval entry; this reference grants no operation rights."""
    return {"snapshot_id": snapshot_id, "collection": "materials", "item_index": item_index}


def select_material_refs(
    state: dict[str, Any], available_refs: list[dict[str, Any]], item_indices: list[int], *,
    keep_resident: bool = False, read_goal: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select array positions from one fixed pool without inventing record identities."""
    selected = []
    for index in item_indices:
        if type(index) is not int or not 0 <= index < len(available_refs):
            raise ValueError("READ_MATERIAL_INDEX_UNAVAILABLE")
        selected.append(copy.deepcopy(available_refs[index]))
    merged = copy.deepcopy(state["resident_refs"]) if keep_resident else []
    if any(ref not in available_refs for ref in merged):
        raise ValueError("READ_MATERIAL_REFERENCE_UNAVAILABLE")
    merged.extend(ref for ref in selected if ref not in merged)
    return {
        **state, "resident_refs": merged,
        "read_goal": copy.deepcopy(read_goal if read_goal is not None else state.get("read_goal")),
    }


def admit_refs(
    state: dict[str, Any], refs: list[dict[str, Any]], *, keep_resident: bool = False,
    read_goal: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Continue one matter's pages; switch matters unless explicitly retained.

    Sources opened beside a matter are its selected original evidence. Opening
    another matter replaces that whole selection; neither path changes archives.
    """
    current = copy.deepcopy(state)
    if read_goal is not None:
        current["read_goal"] = copy.deepcopy(read_goal)
    if not refs:
        return current
    previous = state["resident_refs"]
    records = {ref["id"] for ref in refs if ref["kind"] == "record"}
    same_matter = bool(records) and records == {
        ref["id"] for ref in previous if ref["kind"] == "record"
    }
    same_source = not records and {ref["id"] for ref in refs} == {
        ref["id"] for ref in previous if ref["kind"] == "source"
    }
    supporting_source = not records and any(ref["kind"] == "record" for ref in previous)
    merged = copy.deepcopy(previous) if (
        keep_resident or same_matter or same_source or supporting_source
    ) else []
    current_revisions = {
        ref["id"]: ref["revision"] for ref in refs
        if ref["kind"] == "record" and ref["view"] == "current_at_snapshot"
    }
    merged = [
        ref for ref in merged if ref["kind"] != "record"
        or ref["view"] != "current_at_snapshot" or ref["id"] not in current_revisions
        or ref["revision"] == current_revisions[ref["id"]]
    ]
    for ref in refs:
        identity = [ref.get(key) for key in (
            "kind", "id", "revision", "view", "range", "unit_id"
        )]
        merged = [
            old for old in merged
            if [old.get(key) for key in (
                "kind", "id", "revision", "view", "range", "unit_id"
            )] != identity
        ]
        merged.append(copy.deepcopy(ref))
    return {
        **current,
        "focus": list(records) if records else state.get("focus") or refs[0]["id"],
        "resident_refs": merged,
    }


def select_view_refs(
    state: dict[str, Any], available_refs: list[dict[str, Any]],
    selections: list[dict[str, Any]], *, keep_resident: bool = False,
    read_goal: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Open selected identities from one actual pool, without bodies or another controller.

    Callers resolve these references through their existing reader. Omitting a
    range selects every available page/unit of that actual object and revision.
    A missing identity cannot discover material outside the supplied candidate pool.
    """
    selected: list[dict[str, Any]] = []
    for selection in selections:
        kind = selection.get("kind", "record")
        view = selection.get("view", "original_source" if kind == "source"
                             else "current_at_snapshot")
        view = {"current": "current_at_snapshot", "saved_history": "historical_exact_revision"}.get(
            view, view)
        selected.extend(
            ref for ref in available_refs
            if ref["kind"] == kind and ref["id"] == selection["id"] and ref["view"] == view
            and all(ref.get(key) == selection[key]
                    for key in ("revision", "range", "unit_id") if key in selection)
        )
    return admit_refs(state, selected, keep_resident=keep_resident, read_goal=read_goal)


def catalog_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project actual candidate order without opening all candidate bodies to a model."""
    seen: set[tuple[str, str, int]] = set()
    candidates = []
    for item in items:
        source = item["type"] == "fragment"
        if not source and item["type"] not in {"record", "withdrawal"}:
            continue
        identity = (
            "source" if source else "record",
            item["source_ref"] if source else item["record_id"],
            item.get("source_revision", 1) if source else item["revision"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        if source:
            candidates.append({
                "type": "source_candidate", "source_ref": identity[1],
                "source_revision": identity[2], "role": item["role"],
                "version_view": "original_source",
                "observed_at": item["observed_at"],
                "description": item["content"],
                "body_codepoints": item["source_total_codepoints"],
                "read": {"tool": "read_source", "arguments": {"source_ref": identity[1]}},
            })
        else:
            body_sizes = {
                part.get("edit_unit", {}).get("unit_id"): part.get("content_total_codepoints", 0)
                for part in items if part.get("record_id") == identity[1]
                and part.get("revision") == identity[2]
            }
            candidates.append(record_candidate(
                identity[1], identity[2],
                item.get("edit_matter_description", item["content"]),
                sum(body_sizes.values()), view=item.get("version_view", "current_at_snapshot"),
                navigation=item.get("retrieval_navigation"),
            ))
    return candidates


def record_candidate(
    record_id: str, revision: int, description: Any, body_codepoints: int = 0, *,
    view: str = "current_at_snapshot",
    navigation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One actual candidate for Host and controlled pools; a description is navigation."""
    if navigation is not None:
        key_description = (
            "whole-record search key" if navigation.get("key_kind") == "whole" else "stored unit"
        )
        description = (
            f"{description}\nCosine-winning {key_description} excerpt (navigation only; "
            "open the complete record for evidence): "
            + navigation["excerpt"] + ("…" if navigation["truncated"] else "")
        )
    return {
        "type": "record_candidate", "record_id": record_id, "revision": revision,
        "version_view": view, "description": description, "body_codepoints": body_codepoints,
        "read": {"tool": "read_memory", "arguments": {
            "record_id": record_id,
            **({"revision": revision} if view == "historical_exact_revision" else {}),
        }},
    }


def read_evidence_basis(items: list[dict[str, Any]]) -> dict[str, str]:
    """Describe only material actually opened, independently of the request's purpose."""
    meanings = {
        "current_at_snapshot": (
            "Current stored interpretation; use its scope and applicability for the queried time."
        ),
        "original_source": (
            "Original wording with speaker and source time; not a saved semantic revision."
        ),
        "historical_exact_revision": (
            "Actual saved revision; committed_at is storage time, not when a fact was valid."
        ),
    }
    views = dict.fromkeys(
        "original_source" if item["type"] == "fragment" else item.get("version_view")
        for item in items if item["type"] in {"record", "fragment"}
    )
    return {view: meanings[view] for view in views if view in meanings}


def read_requirement_status(
    state: dict[str, Any],
    actual_items: list[dict[str, Any]],
    *,
    continuations: list[dict[str, Any]] | None = None,
    fresh_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare explicit evidence needs with actual delivery, never infer sufficiency.

    A legacy prose goal is retained without guessing evidence types from words.
    ``fresh_observations`` must come from the application's actual current-turn
    query receipt check; original tool Sources and old receipt bodies are not new
    observations. The caller also supplies its real, still-unread continuations.
    Seeing a view type says nothing about whether the requested revision, range,
    conditions or all pages needed to answer the question have been delivered.
    """
    goal = state.get("read_goal")
    explicit = isinstance(goal, dict)
    structured = goal if isinstance(goal, dict) else {}
    declared = structured.get("evidence", [])
    required = list(dict.fromkeys(
        kind for kind in declared if kind in EVIDENCE_TYPES
    )) if isinstance(declared, list) else []
    view_types = {
        "current_at_snapshot": "current_interpretation",
        "historical_exact_revision": "saved_history",
        "original_source": "original_source",
    }
    delivered = set(view_types[view] for view in read_evidence_basis(actual_items))
    observations = copy.deepcopy(fresh_observations or [])
    if observations:
        delivered.add("live_business")
    unread = copy.deepcopy(continuations or [])
    pending = [kind for kind in required if kind not in delivered]
    return {
        "purpose": structured.get("purpose") if explicit else goal,
        "required_evidence": required,
        "delivered_evidence": [kind for kind in EVIDENCE_TYPES if kind in delivered],
        "pending_evidence": pending,
        "continuations": unread,
        "pending_refs": copy.deepcopy(state.get("pending_refs", [])),
        "fresh_observations": observations,
        "status": "purpose_untyped" if not explicit else "needs_evidence" if pending
        else "has_delivery_gaps" if unread else "evidence_types_delivered",
        "coverage": "delivery_only",
        "answer_sufficiency": "unchecked",
        "instruction": (
            "Use pending_evidence and actual continuations to choose the next read. "
            "A delivered evidence type does not prove that the required revision, "
            "all pages or every condition has been obtained. Original Sources and "
            "past application receipts cannot satisfy a need for live_business; "
            "obtain a new actual query observation in this public request."
        ),
    }
