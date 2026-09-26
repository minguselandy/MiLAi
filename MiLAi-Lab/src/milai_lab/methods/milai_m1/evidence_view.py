"""Bind small model-visible handles to actual B1 request delivery."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from milai_lab.baselines.langmem_revision_store import (
    RevisionSidecar,
    canonical_json,
    content_identity,
)
from milai_lab.methods.milai_m1.decision_basis import DecisionDeltaError


class EvidenceView:
    def __init__(self, sidecar: RevisionSidecar) -> None:
        self.sidecar = sidecar

    def _request(self, request_id: str) -> dict[str, Any]:
        row = next((item for item in self.sidecar.rows("requests")
                    if item["request_id"] == request_id), None)
        if row is None or row["status"] != "completed":
            raise DecisionDeltaError("DECISION_REQUEST_NOT_COMPLETED")
        if row["request_json"] is not None:
            request = json.loads(row["request_json"])
        elif row["trace_path"] is not None:
            with open(row["trace_path"], "rb") as stream:
                stream.seek(row["trace_byte_offset"])
                raw = stream.readline()
            if hashlib.sha256(raw).hexdigest() != row["trace_record_sha256"]:
                raise DecisionDeltaError("DECISION_REQUEST_TRACE_CHANGED")
            request = json.loads(raw)["request"]
        else:
            raise DecisionDeltaError("DECISION_REQUEST_BODY_MISSING")
        sha = hashlib.sha256(canonical_json(request).encode()).hexdigest()
        if sha != row["request_object_sha256"]:
            raise DecisionDeltaError("DECISION_REQUEST_OBJECT_CHANGED")
        return cast(dict[str, Any], request)

    def request_messages(self, request_id: str) -> list[dict[str, Any]]:
        messages = self._request(request_id).get("messages")
        if not isinstance(messages, list):
            raise DecisionDeltaError("DECISION_REQUEST_MESSAGES_MISSING")
        return messages

    def handles(
        self, messages: list[dict[str, Any]], *, thread_id: str,
        public_index: int, request_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Before send: candidate projection. After send: exact delivery validation."""
        if request_id is not None:
            messages = self.request_messages(request_id)
            material = {row["tool_call_id"]: row for row in
                        self.sidecar.rows("request_material")
                        if row["request_id"] == request_id and row["coverage"] == "FULL"}
        else:
            material = None
        handles: dict[str, dict[str, Any]] = {}
        observations = self.sidecar.rows("observations")
        current_user = next((row for row in observations
                             if row["thread_id"] == thread_id
                             and row["public_message_index"] == public_index
                             and row["role"] == "user"), None)
        users = [(position, message) for position, message in enumerate(messages)
                 if message.get("role") == "user"]
        if current_user is not None and users:
            position, user_message = users[-1]
            content = user_message.get("content")
            if content_identity(content)[1] == current_user["content_sha256"]:
                ref = "observation:" + current_user["observation_id"]
                handles[ref] = {
                    "ref": ref, "kind": "observation",
                    "content_sha256": current_user["content_sha256"],
                    "request_id": request_id, "delivery": "current_user",
                    "label": f"current user message at position {position}",
                    "new_in_public_message": True,
                }
        searches = {row["call_id"]: row for row in self.sidecar.rows("searches")
                    if row["thread_id"] == thread_id and row["status"] == "returned"
                    and row["tool_message_body_ref"] is not None}
        calls = {row["call_id"]: row for row in self.sidecar.rows("tool_calls")
                 if row["thread_id"] == thread_id and row["result_body_ref"] is not None}
        business = {row["observation_id"]: row for row in observations
                    if row["thread_id"] == thread_id and row["role"] == "business_tool"}
        for position, message in enumerate(messages):
            if message.get("role") != "tool":
                continue
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str):
                continue
            body_ref = content_identity(message.get("content"))[2]
            binding = material.get(call_id) if material is not None else None
            if material is not None and (binding is None or binding["body_ref"] != body_ref):
                continue
            search = searches.get(call_id)
            if search is not None and search["tool_message_body_ref"] == body_ref:
                for item_index, item in enumerate(json.loads(search["returned_json"] or "[]")):
                    if item["revision_status"] != "EXACT":
                        continue
                    ref = f"memory:{item['memory_id']}@{item['revision']}"
                    handles[ref] = {
                        "ref": ref, "kind": "memory",
                        "content_sha256": item["content_sha256"],
                        "request_id": request_id, "delivery": "search_tool_message",
                        "search_id": search["search_id"],
                        "label": (f"search_memory result {item_index} in tool message "
                                  f"at position {position}: "
                                  f"{item['memory_id']}@{item['revision']}"),
                        "new_in_public_message": False,
                    }
                continue
            call = calls.get(call_id)
            if call is None or call["result_body_ref"] != body_ref:
                continue
            event_id = hashlib.sha256(
                canonical_json([call["call_key"], "business_result"]).encode()
            ).hexdigest()
            row = business.get(event_id)
            if row is not None and row["body_ref"] == body_ref:
                ref = "observation:" + event_id
                handles[ref] = {
                    "ref": ref, "kind": "observation",
                    "content_sha256": row["content_sha256"],
                    "request_id": request_id, "delivery": "business_tool_message",
                    "label": (f"{call['tool_name']} result in tool message "
                              f"at position {position}"),
                    "new_in_public_message": row["public_message_index"] == public_index,
                }
        return handles

    @staticmethod
    def bind(
        refs: list[str], delivered: dict[str, dict[str, Any]],
        current: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        continued = ({item["ref"]: item for item in current["adopted_bindings"]}
                     if current is not None else {})
        bound = []
        for ref in refs:
            if ref in delivered:
                bound.append(delivered[ref])
            elif ref in continued:
                bound.append({**continued[ref], "delivery": "continued_exact",
                              "continued_from_request_id": continued[ref]["request_id"]})
            else:
                raise DecisionDeltaError("DECISION_EVIDENCE_NOT_DELIVERED")
        return bound
