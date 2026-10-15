"""Visible, version-bound premise references across existing memory records."""

from __future__ import annotations

import copy
from typing import Any

from milai_lab.memory.functional_state import FunctionalRejection


def reference_key(record_id: str, unit_id: str) -> str:
    return "external:" + record_id + ":" + unit_id


def bind_external_unit(
    service: Any, reference: dict[str, Any], receipts: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Bind a delivered premise, or its confirmed update in this same batch.

    A different concurrent revision is not silently substituted for what the
    model read. Explicit preceding receipts can advance a seen revision by one;
    all other changes remain observable as stale support at the next read.
    """
    record_id, unit_id, revision = (reference[k] for k in ("record_id", "unit_id", "revision"))
    seen = service.read(record_id, revision)
    if not seen.get("ok") or not any(
        u["unit_id"] == unit_id for u in seen["value"].get("edit_state", {}).get("units", [])
    ):
        raise FunctionalRejection("EDIT_EXTERNAL_PREMISE_UNAVAILABLE")
    current = service.read(record_id)
    accepted = next((r for r in receipts if r.get("ok") and r.get("id") == record_id
                     and r.get("revision") == revision + 1), None)
    bound = current if (accepted is not None and current.get("ok")
                        and current["value"]["revision"] == accepted["revision"]) else seen
    unit = next((u for u in bound["value"].get("edit_state", {}).get("units", [])
                 if u["unit_id"] == unit_id), None)
    if unit is None:
        raise FunctionalRejection("EDIT_EXTERNAL_PREMISE_RETRACTED")
    identity = {"record_id": record_id, "unit_id": unit_id,
                "revision": bound["value"]["revision"]}
    return reference_key(record_id, unit_id), identity, copy.deepcopy(unit["evidence_refs"])


def inspect_external_unit(
    service: Any, reference: dict[str, Any], *, historical: bool = False,
) -> dict[str, Any]:
    """Resolve actual bodies under current visibility; no state or truth is changed."""
    record_id, unit_id, revision = (reference[k] for k in ("record_id", "unit_id", "revision"))
    bound = service.read(record_id, revision)
    current = bound if historical else service.read(record_id)
    if not bound.get("ok") or not current.get("ok"):
        return {**reference, "status": "unavailable"}
    old = next((u for u in bound["value"].get("edit_state", {}).get("units", [])
                if u["unit_id"] == unit_id), None)
    new = next((u for u in current["value"].get("edit_state", {}).get("units", [])
                if u["unit_id"] == unit_id), None)
    if old is None:
        return {**reference, "status": "unavailable"}
    if new is None:
        return {**reference, "status": "retracted", "bound_record": bound,
                "current_record": current}
    changed = any(old.get(k) != new.get(k) for k in ("text", "role", "assertion"))
    return {**reference, "status": "historical" if historical else "changed" if changed else
            "unchanged", "bound_record": bound, "current_record": current}


def dependent_record_candidates(
    service: Any, records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand actual declared record links; traversal/enumeration costs are real work.

    This small slice scans visible records rather than claiming a new O(k) index.
    Unit-level impact and preservation decisions happen after this candidate step.
    """
    available = {row["id"]: row for row in service.records()}
    selected = {row["id"]: row for row in records if row.get("ok")}
    while True:
        before = set(selected)
        for record_id, row in available.items():
            dependencies = {ref["record_id"] for group in row["value"].get(
                "edit_state", {}).get("support_groups", [])
                for ref in group.get("external_units", {}).values()}
            if record_id in selected:
                selected.update({key: available[key] for key in dependencies if key in available})
            elif dependencies & set(selected):
                selected[record_id] = row
        if set(selected) == before:
            return list(selected.values())


def order_dependent_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put explicitly referenced record updates before their dependent proposals.

    Cycles keep their remaining source order and may leave stale support; they
    do not acquire an imaginary multi-record transaction or a synthesized value.
    """
    pending = list(proposals)
    result: list[dict[str, Any]] = []
    while pending:
        targets = {p["target"] for p in pending if p.get("target")}
        ready = [p for p in pending if not ({ref["record"] for group in p.get("support_groups", [])
            for route in group.get("alternatives", []) for ref in route if isinstance(ref, dict)}
            & targets)]
        if not ready:
            return [*result, *pending]
        result.extend(ready)
        pending = [p for p in pending if p not in ready]
    return result
