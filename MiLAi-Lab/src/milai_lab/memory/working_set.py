"""Small reference-only working state over already delivered memory snapshots."""

from __future__ import annotations

import copy
from typing import Any


def empty_view() -> dict[str, Any]:
    return {"focus": None, "read_goal": None, "resident_refs": [], "pending_refs": []}


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


def admit_refs(
    state: dict[str, Any], refs: list[dict[str, Any]], *, keep_resident: bool = False
) -> dict[str, Any]:
    """Continue one matter's pages; switch matters unless explicitly retained.

    Sources opened beside a matter are its selected original evidence. Opening
    another matter replaces that whole selection; neither path changes archives.
    """
    if not refs:
        return copy.deepcopy(state)
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
        **copy.deepcopy(state),
        "focus": list(records) if records else state.get("focus") or refs[0]["id"],
        "read_goal": "current_and_saved_history" if any(
            ref["view"] == "historical_exact_revision" for ref in merged
        ) else (
            state.get("read_goal") if supporting_source else
            ("current" if records else "original_source")
        ),
        "resident_refs": merged,
    }


def select_view_refs(
    state: dict[str, Any], available_refs: list[dict[str, Any]],
    selections: list[dict[str, Any]], *, keep_resident: bool = False,
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
    return admit_refs(state, selected, keep_resident=keep_resident)


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
            ))
    return candidates


def record_candidate(
    record_id: str, revision: int, description: Any, body_codepoints: int = 0, *,
    view: str = "current_at_snapshot",
) -> dict[str, Any]:
    """One actual candidate for Host and controlled pools; a description is navigation."""
    return {
        "type": "record_candidate", "record_id": record_id, "revision": revision,
        "version_view": view, "description": description, "body_codepoints": body_codepoints,
        "read": {"tool": "read_memory", "arguments": {"record_id": record_id}},
    }
