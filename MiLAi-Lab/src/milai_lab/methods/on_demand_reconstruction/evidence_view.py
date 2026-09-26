"""Exact request evidence from B1 observations, deliveries and receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from milai_lab.baselines.langmem_revision_store import (
    RevisionSidecar,
    canonical_json,
    content_identity,
)
from milai_lab.methods.on_demand_reconstruction.schema import ReconstructionError


class EvidenceView:
    def __init__(self, sidecar: RevisionSidecar) -> None:
        self.sidecar = sidecar

    def request_messages(self, request_id: str) -> list[dict[str, Any]]:
        row = next((row for row in self.sidecar.rows("requests")
                    if row["request_id"] == request_id), None)
        if row is None or row["status"] != "completed":
            raise ReconstructionError("ODR_REQUEST_NOT_COMPLETED")
        if row["request_json"] is not None:
            request = json.loads(row["request_json"])
        else:
            with open(row["trace_path"], "rb") as stream:
                stream.seek(row["trace_byte_offset"])
                raw = stream.readline()
            if hashlib.sha256(raw).hexdigest() != row["trace_record_sha256"]:
                raise ReconstructionError("ODR_REQUEST_TRACE_CHANGED")
            request = json.loads(raw)["request"]
        request_sha = hashlib.sha256(canonical_json(request).encode()).hexdigest()
        if request_sha != row["request_object_sha256"]:
            raise ReconstructionError("ODR_REQUEST_OBJECT_CHANGED")
        return cast(list[dict[str, Any]], request["messages"])

    def handles(self, messages: list[dict[str, Any]], *, thread_id: str,
                public_index: int, request_id: str | None = None) -> dict[str, dict[str, Any]]:
        if request_id is not None:
            messages = self.request_messages(request_id)
            material = {row["tool_call_id"]: row for row in self.sidecar.rows("request_material")
                        if row["request_id"] == request_id and row["coverage"] == "FULL"}
        else:
            material = None
        handles: dict[str, dict[str, Any]] = {}
        observations = self.sidecar.rows("observations")
        user_rows = {row["public_message_index"]: row for row in observations
                     if row["thread_id"] == thread_id and row["role"] == "user"}
        users = [(i, message) for i, message in enumerate(messages)
                 if message.get("role") == "user"]
        for user_index, (position, message) in enumerate(users):
            row = user_rows.get(user_index)
            if (row is not None and content_identity(message.get("content"))[1]
                    == row["content_sha256"]):
                ref = "observation:" + row["observation_id"]
                handles[ref] = {"ref": ref, "kind": "observation", "label":
                                f"user message at position {position}",
                                "new_in_public_message": user_index == public_index}
        searches = {row["call_id"]: row for row in self.sidecar.rows("searches")
                    if row["thread_id"] == thread_id and row["status"] == "returned"
                    and row["tool_message_body_ref"] is not None}
        calls = {row["call_id"]: row for row in self.sidecar.rows("tool_calls")
                 if row["thread_id"] == thread_id and row["result_body_ref"] is not None}
        business = {row["observation_id"]: row for row in observations
                    if row["thread_id"] == thread_id and row["role"] == "business_tool"}
        for position, message in enumerate(messages):
            if message.get("role") != "tool" or not isinstance(message.get("tool_call_id"), str):
                continue
            call_id = message["tool_call_id"]
            body_ref = content_identity(message.get("content"))[2]
            if material is not None and (call_id not in material
                                         or material[call_id]["body_ref"] != body_ref):
                continue
            search = searches.get(call_id)
            if search is not None and search["tool_message_body_ref"] == body_ref:
                for item_index, item in enumerate(json.loads(search["returned_json"] or "[]")):
                    if item["revision_status"] != "EXACT":
                        ref = f"memory_unknown:{search['search_id']}:{item_index}"
                        handles.setdefault(ref, {
                            "ref": ref, "kind": "memory_unknown",
                            "memory_id": item["memory_id"],
                            "namespace": tuple(item["namespace"]),
                            "label": f"search result {item_index} at message {position}: "
                                     f"{item['memory_id']} (revision unknown)",
                        })
                        continue
                    ref = f"memory:{item['memory_id']}@{item['revision']}"
                    handles.setdefault(ref, {
                        "ref": ref, "kind": "memory", "memory_id": item["memory_id"],
                        "revision": item["revision"],
                        "namespace": tuple(item["namespace"]),
                        "label": f"search result {item_index} at message {position}: {ref}",
                    })
                continue
            call = calls.get(call_id)
            if call is None or call["result_body_ref"] != body_ref:
                continue
            identity = canonical_json([call["call_key"], "business_result"])
            event_id = hashlib.sha256(identity.encode()).hexdigest()
            row = business.get(event_id)
            if row is not None and row["body_ref"] == body_ref:
                ref = "observation:" + event_id
                handles.setdefault(ref, {"ref": ref, "kind": "receipt", "label":
                                         f"{call['tool_name']} result at message {position}"})
        return handles
