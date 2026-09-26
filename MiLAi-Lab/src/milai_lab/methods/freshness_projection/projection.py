"""Withhold superseded search bodies only in the outgoing Provider request."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from milai_lab.baselines.langmem_revision_store import RevisionSidecar, content_identity

SOURCE_AUTHORITY = (
    "Previous assistant statements are not authoritative evidence about external or "
    "remembered state. Use current user and tool evidence for current action parameters."
)


@dataclass(frozen=True)
class ProjectedRequest:
    messages: list[dict[str, Any]]
    materials: dict[str, dict[str, str]]
    items: list[dict[str, Any]]


def _status(item: dict[str, Any], sidecar: RevisionSidecar) -> tuple[str, str | None]:
    if item["revision_status"] != "EXACT":
        return "UNKNOWN", None
    latest = sidecar.latest_revision(tuple(item["namespace"]), item["memory_id"])
    if latest is None:
        return "UNKNOWN", None
    if latest["tombstone"]:
        return "DELETED", None
    if latest["revision"] == item["revision"]:
        return "CURRENT", f"memory:{item['memory_id']}@{item['revision']}"
    if latest["revision"] > item["revision"]:
        return "SUPERSEDED", f"memory:{item['memory_id']}@{latest['revision']}"
    return "UNKNOWN", None


def project_current_evidence(
    messages: list[dict[str, Any]], sidecar: RevisionSidecar, thread_id: str,
) -> ProjectedRequest:
    """Bind each original search message before replacing individual stale values."""
    searches = {row["call_id"]: row for row in sidecar.rows("searches")
                if row["thread_id"] == thread_id and row["status"] == "returned"
                and row["tool_message_body_ref"] is not None}
    bound: dict[int, tuple[dict[str, Any], list[dict[str, Any]],
                           list[dict[str, Any]]]] = {}
    exact_refs: set[tuple[tuple[str, ...], str, int]] = set()
    for position, message in enumerate(messages):
        if message.get("role") != "tool" or message.get("tool_call_id") not in searches:
            continue
        search = searches[message["tool_call_id"]]
        original_ref = content_identity(message.get("content"))[2]
        if original_ref != search["tool_message_body_ref"]:
            raise ValueError("PROJECTION_SEARCH_BODY_UNBOUND")
        entries = json.loads(search["returned_json"] or "[]")
        body = json.loads(message["content"])
        if (not isinstance(body, list) or len(body) != len(entries)
                or any(raw != entry["store_item"] for raw, entry in zip(body, entries,
                                                                         strict=True))):
            raise ValueError("PROJECTION_SEARCH_ITEMS_UNBOUND")
        bound[position] = search, entries, body
        exact_refs.update((tuple(item["namespace"]), item["memory_id"], item["revision"])
                          for item in entries if item["revision_status"] == "EXACT")
    projected = list(messages)
    materials: dict[str, dict[str, str]] = {}
    events: list[dict[str, Any]] = []
    for position, (search, entries, body) in bound.items():
        changed = False
        rendered = list(body)
        for item_index, item in enumerate(entries):
            status, current_ref = _status(item, sidecar)
            ref = (f"memory:{item['memory_id']}@{item['revision']}"
                   if item["revision_status"] == "EXACT" else None)
            current_revision = int(current_ref.rsplit("@", 1)[1]) if current_ref else None
            delivered = ((tuple(item["namespace"]), item["memory_id"], current_revision)
                         in exact_refs if current_revision is not None else False)
            event = {"source_tool_call": search["call_id"],
                     "source_search_id": search["search_id"],
                     "item_index": item_index, "memory_id": item["memory_id"],
                     "namespace": item["namespace"], "ref": ref,
                     "status": status, "current_ref": current_ref,
                     "current_body_delivered": delivered,
                     "source_body_ref": item["body_ref"]}
            if status in {"SUPERSEDED", "DELETED"}:
                marker = f"Historical memory {ref}. Status: {status}."
                if current_ref:
                    marker += f" Current revision: {current_ref}."
                    if not delivered:
                        marker += " Current revision body is absent from this request."
                marker += " Historical body withheld from this request."
                rendered[item_index] = {**body[item_index], "value": {"content": marker}}
                event["projected_body_ref"] = content_identity(marker)[2]
                changed = True
            else:
                event["projected_body_ref"] = item["body_ref"]
            events.append(event)
        if changed:
            original_message = messages[position]
            projected_content = json.dumps(rendered, ensure_ascii=False,
                                           separators=(",", ":"))
            projected[position] = {**original_message, "content": projected_content}
            materials[search["call_id"]] = {
                "source_search_id": search["search_id"],
                "original_body_ref": search["tool_message_body_ref"],
                "projected_body_ref": content_identity(projected_content)[2],
            }
    return ProjectedRequest(projected, materials, events)
