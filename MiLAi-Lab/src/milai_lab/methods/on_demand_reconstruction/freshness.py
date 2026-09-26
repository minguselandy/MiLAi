"""Mechanical currentness, recomputed for evidence in each provider request."""

from __future__ import annotations

from typing import Any

from milai_lab.baselines.langmem_revision_store import RevisionSidecar


def inspect_freshness(handles: dict[str, dict[str, Any]],
                      sidecar: RevisionSidecar) -> dict[str, dict[str, Any]]:
    current_refs = set(handles)
    result = {}
    for ref, item in handles.items():
        if item["kind"] == "memory_unknown":
            result[ref] = {"status": "UNKNOWN", "current_ref": None,
                           "current_body_delivered": False}
            continue
        if item["kind"] != "memory":
            continue
        latest = sidecar.latest_revision(item["namespace"], item["memory_id"])
        if latest is None:
            status, current_ref = "UNKNOWN", None
        elif latest["tombstone"]:
            status, current_ref = "DELETED", None
        elif latest["revision"] == item["revision"]:
            status, current_ref = "CURRENT", ref
        elif latest["revision"] > item["revision"]:
            status = "SUPERSEDED"
            current_ref = f"memory:{item['memory_id']}@{latest['revision']}"
        else:
            status, current_ref = "UNKNOWN", None
        delivered = current_ref in current_refs if current_ref else False
        result[ref] = {"status": status, "current_ref": current_ref,
                       "current_body_delivered": delivered}
    return result


def freshness_block(handles: dict[str, dict[str, Any]],
                    currentness: dict[str, dict[str, Any]]) -> str:
    lines = []
    for ref in handles:
        item = currentness.get(ref)
        if item is None or item["status"] not in {"SUPERSEDED", "DELETED"}:
            continue
        if item["status"] == "DELETED":
            lines.append(f"- {ref} was deleted.")
        else:
            line = f"- {ref} is superseded by {item['current_ref']}."
            if not item["current_body_delivered"]:
                line += " The current revision body is absent from this request."
            lines.append(line)
    return "Evidence freshness:\n" + "\n".join(lines) if lines else ""
