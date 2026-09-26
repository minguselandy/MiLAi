"""Request-level lineage for ordinary assistant text, without word-level claims."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from milai_lab.baselines.langmem_revision_store import RevisionSidecar, content_identity

DERIVED_WITHHELD = (
    "[Historical assistant response withheld: its generating request contained "
    "memory evidence that is now superseded or deleted. Re-evaluate from current "
    "user and tool evidence.]"
)
REBASE_REASON = "GENERATING_REQUEST_EXACT_MEMORY_SUPERSEDED_OR_DELETED"


@dataclass(frozen=True)
class DerivedProjection:
    messages: list[dict[str, Any]]
    rebases: list[dict[str, Any]]
    unknown_bindings: list[dict[str, Any]]


def delivered_exact_snapshot(items: list[dict[str, Any]],
                             ) -> tuple[list[dict[str, Any]], int]:
    """Only current bodies actually planned into the bound outgoing request count."""
    exact: dict[tuple[tuple[str, ...], str, int], dict[str, Any]] = {}
    unknown_items = 0
    for item in items:
        if item["status"] == "CURRENT" and item["current_body_delivered"]:
            ref, body_ref = item["ref"], item["source_body_ref"]
        elif (item.get("delivery_source") == "public Store.get"
              and item["current_body_delivered"]):
            ref, body_ref = item["current_ref"], item["projected_body_ref"]
        else:
            if item["status"] == "UNKNOWN" or (
                item["status"] == "SUPERSEDED" and not item["current_body_delivered"]
            ):
                unknown_items += 1
            continue
        if not isinstance(ref, str):
            unknown_items += 1
            continue
        namespace = tuple(item["namespace"])
        revision = int(ref.rsplit("@", 1)[1])
        key = (namespace, item["memory_id"], revision)
        exact[key] = {
            "namespace": list(namespace), "memory_id": item["memory_id"],
            "revision": revision, "ref": ref, "body_ref": body_ref,
            "source_tool_call": item["source_tool_call"],
            "source_search_id": item["source_search_id"],
            "delivery_source": item.get("delivery_source", "search_memory"),
        }
    return list(exact.values()), unknown_items


def project_derived_assistants(
    graph_messages: list[BaseMessage], wire_messages: list[dict[str, Any]],
    sidecar: RevisionSidecar, thread_id: str,
) -> DerivedProjection:
    """Demote only a checkpoint message bound to its own stale request snapshot."""
    projected = list(wire_messages)
    rebases: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    if len(graph_messages) != len(wire_messages):
        return DerivedProjection(projected, rebases, [{"reason": "MESSAGE_COUNT_UNBOUND"}])
    for position, (graph, wire) in enumerate(zip(graph_messages, wire_messages, strict=True)):
        if (not isinstance(graph, AIMessage) or graph.tool_calls
                or not isinstance(graph.content, str) or not graph.content):
            continue
        response_id = graph.id
        if (not isinstance(response_id, str) or wire.get("role") != "assistant"
                or wire.get("content") != graph.content or wire.get("tool_calls")):
            unknown.append({"message_index": position, "response_id": response_id,
                            "reason": "MESSAGE_ID_OR_BODY_UNBOUND"})
            continue
        lineage = sidecar.get_assistant_lineage(thread_id, response_id)
        original_kind, original_sha, original_ref = content_identity(graph.content)
        if lineage is None or lineage["original_body_ref"] != original_ref:
            unknown.append({"message_index": position, "response_id": response_id,
                            "original_body_ref": original_ref,
                            "reason": "LINEAGE_UNAVAILABLE_OR_BODY_CHANGED"})
            continue
        stale_refs: list[dict[str, Any]] = []
        current_refs: list[dict[str, Any]] = []
        unknown_refs: list[dict[str, Any]] = []
        for evidence in json.loads(lineage["exact_snapshot_json"]):
            namespace = tuple(evidence["namespace"])
            latest = sidecar.latest_revision(namespace, evidence["memory_id"])
            if latest is None or int(latest["revision"]) < evidence["revision"]:
                unknown_refs.append(evidence)
                continue
            if latest["tombstone"] or int(latest["revision"]) > evidence["revision"]:
                stale_refs.append({**evidence, "status": (
                    "DELETED" if latest["tombstone"] else "SUPERSEDED")})
                current_refs.append({"namespace": list(namespace),
                                     "memory_id": evidence["memory_id"],
                                     "revision": None if latest["tombstone"] else
                                     int(latest["revision"]),
                                     "ref": None if latest["tombstone"] else
                                     f"memory:{evidence['memory_id']}@{latest['revision']}",
                                     "status": "DELETED" if latest["tombstone"] else
                                     "CURRENT"})
        if not stale_refs:
            if unknown_refs:
                unknown.append({"message_index": position, "response_id": response_id,
                                "reason": "SNAPSHOT_CURRENTNESS_UNKNOWN",
                                "unknown_refs": unknown_refs})
            continue
        projected[position] = {**wire, "content": DERIVED_WITHHELD}
        _, projected_sha, projected_ref = content_identity(DERIVED_WITHHELD)
        rebases.append({
            "message_index": position, "response_id": response_id,
            "generating_request_id": lineage["generating_request_id"],
            "original_body_kind": original_kind,
            "original_body_hash": original_sha,
            "original_body_ref": original_ref,
            "projected_body_hash": projected_sha,
            "projected_body_ref": projected_ref,
            "stale_refs": stale_refs, "current_refs": current_refs,
            "unknown_refs": unknown_refs,
            "reason": REBASE_REASON,
        })
    return DerivedProjection(projected, rebases, unknown)
