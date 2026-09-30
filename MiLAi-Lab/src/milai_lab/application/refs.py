"""Bind public ApplicationWorld receipts to a real object visible to this owner."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import VerifiedObjectRef


def verified_reservation_ref(
    world: ApplicationWorld,
    owner: str,
    source_ref: str,
    tool_name: str,
    receipt: str,
    *,
    observer: Callable[[dict[str, Any]], None] | None = None,
) -> VerifiedObjectRef | None:
    """Trusted execution adapter only; never accept a Host-authored receipt here.

    Lookup checks identity/owner. Projected fields come from the original observed
    receipt, so an old receipt is not silently replaced with current world state.
    """
    if tool_name not in {"reserve_and_label", "get_reservation", "complete_label"}:
        return None
    body: Any = json.loads(receipt)
    if not isinstance(body, dict) or not body.get("reservation_id") or not body.get("item_key"):
        return None
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    with world.tool_lock:
        actual = json.loads(world.get_reservation(owner, body["item_key"]))
    if observer is not None:
        observer(
            {
                "event": "v13_ref_discovery",
                "owner": owner,
                "source_ref": source_ref,
                "tool": "get_reservation",
                "arguments": {"item_key": body["item_key"]},
                "original_lookup_result": actual,
                "lookup_calls": 1,
                "wall_ns": time.perf_counter_ns() - wall,
                "cpu_ns": time.process_time_ns() - cpu,
                "generation_tokens": 0,
            }
        )
    if actual.get("status") != "found" or actual.get("reservation_id") != body["reservation_id"]:
        return None
    fields = {
        key: body[key] for key in ("status", "label_status") if isinstance(body.get(key), str)
    }
    return VerifiedObjectRef(
        id=source_ref + ":" + body["reservation_id"],
        owner=owner,
        source_ref=source_ref,
        external_id=body["reservation_id"],
        application="ApplicationWorld.reservation",
        fields=fields,
    )


def verified_document_ref(
    world: Any,
    owner: str,
    source_ref: str,
    tool_name: str,
    receipt: str,
    *,
    observer: Callable[[dict[str, Any]], None] | None = None,
) -> VerifiedObjectRef | None:
    from milai_lab.application.document_publication import DOCUMENT_FIELDS, DOCUMENT_NAMES

    if tool_name not in DOCUMENT_NAMES:
        return None
    body = json.loads(receipt)
    if (
        not isinstance(body, dict)
        or not body.get("document_id")
        or not body.get("title")
        or type(body.get("document_version")) is not int
        or body["document_version"] < 1
        or not isinstance(body.get("content_digest"), str)
    ):
        return None
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    actual = json.loads(world.get_document_status(owner, body["title"]))
    if observer is not None:
        observer(
            {
                "event": "v13_ref_discovery",
                "owner": owner,
                "source_ref": source_ref,
                "tool": "get_document_status",
                "arguments": {"title": body["title"]},
                "original_lookup_result": actual,
                "lookup_calls": 1,
                "wall_ns": time.perf_counter_ns() - wall,
                "cpu_ns": time.process_time_ns() - cpu,
                "generation_tokens": 0,
            }
        )
    if (
        actual.get("status") != "found"
        or actual.get("document_id") != body["document_id"]
        or not any(
            value["document_version"] == body.get("document_version")
            and value["content_digest"] == body.get("content_digest")
            for value in actual.get("versions", [])
        )
    ):
        return None
    fields = {
        key: body[key]
        for key, dtype in DOCUMENT_FIELDS.items()
        if type(body.get(key)) is (int if dtype == "integer" else str)
    }
    return VerifiedObjectRef(
        source_ref + ":" + body["document_id"],
        owner,
        source_ref,
        body["document_id"],
        "ApplicationWorld.document",
        fields,
    )
