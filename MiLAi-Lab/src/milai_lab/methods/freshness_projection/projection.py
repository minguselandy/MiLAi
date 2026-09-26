"""Withhold superseded search bodies only in the outgoing Provider request."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.store.base import Item

from milai_lab.baselines.langmem_revision_store import (
    RevisionSidecar,
    canonical_json,
    content_identity,
)

SOURCE_AUTHORITY = (
    "Previous assistant statements are not authoritative evidence about external or "
    "remembered state. Use current user and tool evidence for current action parameters."
)


@dataclass(frozen=True)
class ProjectedRequest:
    messages: list[dict[str, Any]]
    materials: dict[str, dict[str, str]]
    items: list[dict[str, Any]]
    exact_reads: list[dict[str, Any]]
    derived_rebases: list[dict[str, Any]] = field(default_factory=list)
    unknown_bindings: list[dict[str, Any]] = field(default_factory=list)
    projection_cpu_ns: int = 0
    projection_wall_ns: int = 0


def _status(item: dict[str, Any], sidecar: RevisionSidecar,
            ) -> tuple[str, str | None, dict[str, Any] | None]:
    if item["revision_status"] != "EXACT":
        return "UNKNOWN", None, None
    latest = sidecar.latest_revision(tuple(item["namespace"]), item["memory_id"])
    if latest is None:
        return "UNKNOWN", None, None
    if latest["tombstone"]:
        return "DELETED", None, latest
    if latest["revision"] == item["revision"]:
        return "CURRENT", f"memory:{item['memory_id']}@{item['revision']}", latest
    if latest["revision"] > item["revision"]:
        return "SUPERSEDED", f"memory:{item['memory_id']}@{latest['revision']}", latest
    return "UNKNOWN", None, latest


def project_current_evidence(
    messages: list[dict[str, Any]], sidecar: RevisionSidecar, thread_id: str,
    get_current: Callable[[tuple[str, ...], str], Item | None] | None = None,
    record_exact_read: Callable[[dict[str, Any]], None] | None = None,
    *, refresh_until_current_candidate: bool = False,
    max_exact_refresh_per_search: int | None = None,
) -> ProjectedRequest:
    """Bind each original search message before replacing individual stale values."""
    if max_exact_refresh_per_search is not None and max_exact_refresh_per_search < 0:
        raise ValueError("PROJECTION_EXACT_REFRESH_LIMIT_INVALID")
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
    exact_reads: list[dict[str, Any]] = []
    refreshed: dict[tuple[tuple[str, ...], str, int], Item | None] = {}
    refreshed_in_request: set[tuple[tuple[str, ...], str, int]] = set()
    read_indexes: dict[tuple[tuple[str, ...], str, int], int] = {}
    for position, (search, entries, body) in bound.items():
        changed = False
        refreshed_in_message = False
        current_candidate = False
        new_reads_in_search = 0
        rendered = list(body)
        for item_index, item in enumerate(entries):
            status, current_ref, latest = _status(item, sidecar)
            ref = (f"memory:{item['memory_id']}@{item['revision']}"
                   if item["revision_status"] == "EXACT" else None)
            current_revision = int(current_ref.rsplit("@", 1)[1]) if current_ref else None
            current_key = ((tuple(item["namespace"]), item["memory_id"], current_revision)
                           if current_revision is not None else None)
            delivered = (current_key in exact_refs or
                         (refresh_until_current_candidate
                          and current_key in refreshed_in_request))
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
                if (status == "SUPERSEDED" and not delivered
                        and get_current is not None and latest is not None):
                    key = (tuple(item["namespace"]), item["memory_id"],
                           int(latest["revision"]))
                    if refresh_until_current_candidate and current_candidate:
                        event["refresh_skip_reason"] = "HIGHER_RANK_CURRENT_CANDIDATE"
                    elif (key not in refreshed and max_exact_refresh_per_search is not None
                          and new_reads_in_search >= max_exact_refresh_per_search):
                        event["refresh_skip_reason"] = "SEARCH_EXACT_READ_LIMIT"
                    else:
                        if key not in refreshed:
                            new_reads_in_search += 1
                            started = time.perf_counter_ns()
                            error_type = None
                            try:
                                current = get_current(key[0], key[1])
                            except Exception as error:
                                current = None
                                error_type = type(error).__name__
                            wall_ns = time.perf_counter_ns() - started
                            bound_current = (error_type is None and current is not None and
                                             canonical_json(current.dict())
                                             == latest["post_item_json"])
                            refreshed[key] = current if bound_current else None
                            read = {
                                "namespace": list(key[0]), "memory_id": key[1],
                                "expected_revision": key[2], "source": "public Store.get",
                                "refresh_ttl": False, "wall_ns": wall_ns,
                                "status": ("BOUND_CURRENT" if bound_current else
                                           "UNKNOWN_ERROR" if error_type else
                                           "UNKNOWN_NOT_FOUND" if current is None else
                                           "UNKNOWN_BINDING"),
                                "returned_body_ref": (content_identity(
                                    current.value.get("content"))[2]
                                    if current is not None else None),
                                "error_type": error_type,
                            }
                            read_indexes[key] = len(exact_reads)
                            exact_reads.append(read)
                            if record_exact_read is not None:
                                record_exact_read(read)
                        current = refreshed[key]
                        event["exact_read_index"] = read_indexes[key]
                        event["refresh_status"] = exact_reads[event["exact_read_index"]]["status"]
                        if current is not None:
                            rendered[item_index] = {
                                **current.dict(),
                                "_version_projection": {
                                    "status": "EXACT_CURRENT_REFRESH",
                                    "ref": current_ref, "supersedes_ref": ref,
                                    "source": "public Store.get",
                                },
                            }
                            event["projected_body_ref"] = content_identity(
                                current.value.get("content"))[2]
                            event["current_body_delivered"] = True
                            event["delivery_source"] = "public Store.get"
                            refreshed_in_message = True
                            if refresh_until_current_candidate:
                                current_candidate = True
                                refreshed_in_request.add(key)
                changed = True
            else:
                event["projected_body_ref"] = item["body_ref"]
                if status == "CURRENT":
                    current_candidate = True
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
                "coverage": ("PROJECTED_REFRESHED" if refreshed_in_message else
                             "PROJECTED_WITHHELD"),
            }
    return ProjectedRequest(projected, materials, events, exact_reads)
