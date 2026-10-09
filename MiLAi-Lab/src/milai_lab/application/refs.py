"""Bind public ApplicationWorld receipts to a real object visible to this owner."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import (
    RECEIPT_PROFILES,
    ObservationField,
    ObservationProfile,
    VerifiedObjectRef,
)


def visible_verified_ref(service: Any, ref: VerifiedObjectRef) -> VerifiedObjectRef | None:
    """Resolve the actual issued identity; state and permission stay separate.

    The Host cannot issue a reference by assembling its public fields. Only an
    existing visible trusted source can supply one, including its historical
    observed fields. No content fingerprint or current-state assertion is used.
    """
    source = service.source(ref.source_ref)
    issued = source.get("object_ref") if source else None
    if issued is None or any(
        issued[field] != getattr(ref, field)
        for field in ("id", "owner", "source_ref", "external_id", "application")
    ):
        return None
    return VerifiedObjectRef(**issued)


def observation_profile(workflow: str, *, maintenance: bool = False) -> ObservationProfile:
    """Only public receipt structure; no correctness plans or hidden task metadata.

    document_version orders the document's content, not approval/publication
    effects. Those fields therefore have no declared ordered version domain.
    Reservation receipts expose no comparable business version at all.
    """
    if workflow == "reservation_v1":
        return ObservationProfile(
            profile_id=workflow,
            adapter_version="2" if maintenance else "1",
            application="ApplicationWorld.reservation",
            origins=("reserve_and_label", "get_reservation", "complete_label"),
            object_id_path=("reservation_id",),
            fields=(
                ObservationField("status", ("status",), "string"),
                ObservationField("label_status", ("label_status",), "string"),
                *((ObservationField("item_key", ("item_key",), "string"),
                   ObservationField("quantity", ("quantity",), "integer"),
                   ObservationField("destination", ("destination",), "string"),
                   ObservationField("packing", ("packing",), "string"),
                   ObservationField("operation_history", ("operation_history",), "json"))
                  if maintenance else ()),
            ),
        )
    if workflow == "document_publication_v1":
        from milai_lab.application.document_publication import DOCUMENT_NAMES

        return ObservationProfile(
            profile_id=workflow,
            adapter_version="2" if maintenance else "1",
            application="ApplicationWorld.document",
            origins=tuple(DOCUMENT_NAMES),
            object_id_path=("document_id",),
            resource_version_path=("document_version",),
            resource_version_type="integer",
            fields=tuple(
                ObservationField(
                    name,
                    (name,),
                    "integer" if dtype == "integer" else "string",
                    version_domain=("document_content" if name == "document_version" else None),
                )
                for name, dtype in RECEIPT_PROFILES[workflow]["fields"].items()
            ) + ((ObservationField("title", ("title",), "string"),
                  ObservationField("operation_history", ("operation_history",), "json"))
                 if maintenance else ()),
            unstructured_paths=(("content",),) if maintenance else (),
        )
    raise ValueError("V13_OBSERVATION_WORKFLOW_INVALID")


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
