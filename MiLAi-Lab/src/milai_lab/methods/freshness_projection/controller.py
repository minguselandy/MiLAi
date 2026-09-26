"""Join a request-copy projection to the actual B1 Provider receipt."""

from __future__ import annotations

import hashlib
from typing import Any

from langgraph.store.base import BaseStore

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import canonical_json
from milai_lab.methods.freshness_projection.projection import (
    ProjectedRequest,
    project_current_evidence,
)

RECIPE_ID = "milai-freshness-projection-json-action-v1"
TRANSPORT_VARIANT = "json_action_freshness_projection_v1"
ARMS = ("b1_control", "a1_notice", "a2_quarantine", "a3_exact_refresh")


class ProjectionController:
    recipe_id = RECIPE_ID

    def __init__(self, observer: ProvenanceObserver, emit: Any = None,
                 *, arm: str = "a2_quarantine", store: BaseStore | None = None) -> None:
        if arm not in {"a2_quarantine", "a3_exact_refresh"}:
            raise ValueError("PROJECTION_ARM_INVALID")
        if arm == "a3_exact_refresh" and store is None:
            raise ValueError("PROJECTION_EXACT_STORE_MISSING")
        self.observer = observer
        self.emit = emit
        self.arm = arm
        self.store = store

    @staticmethod
    def _identity(message_key: str | None, request_index: int) -> tuple[str, int, str]:
        if message_key is None:
            raise ValueError("PROJECTION_PUBLIC_MESSAGE_KEY_MISSING")
        thread_id, public_text = message_key.rsplit(":", 1)
        public_index = int(public_text)
        request_id = hashlib.sha256(
            canonical_json([thread_id, public_index, request_index]).encode()
        ).hexdigest()
        return thread_id, public_index, request_id

    def project(self, messages: list[dict[str, Any]],
                message_key: str | None, request_index: int) -> ProjectedRequest:
        thread_id, public_index, request_id = self._identity(message_key, request_index)
        store = self.store

        def record_read(read: dict[str, Any]) -> None:
            if self.emit is not None:
                self.emit({"event": "freshness_exact_read", "arm": self.arm,
                           "request_id": request_id,
                           "public_message_index": public_index,
                           "provider_delivery": False, **read})

        return project_current_evidence(
            messages, self.observer.sidecar, thread_id,
            get_current=(lambda namespace, memory_id: store.get(
                namespace, memory_id, refresh_ttl=False))
            if store is not None and self.arm == "a3_exact_refresh" else None,
            record_exact_read=record_read,
        )

    def record_delivery(self, message_key: str | None, request_index: int,
                        projected: ProjectedRequest) -> None:
        _, public_index, request_id = self._identity(message_key, request_index)
        request = next((row for row in self.observer.sidecar.rows("requests")
                        if row["request_id"] == request_id), None)
        if request is None or request["status"] != "completed":
            raise ValueError("PROJECTION_REQUEST_NOT_COMPLETED")
        material = {row["tool_call_id"]: row for row in
                    self.observer.sidecar.rows("request_material")
                    if row["request_id"] == request_id}
        for call_id, plan in projected.materials.items():
            row = material.get(call_id)
            if (row is None or row["coverage"] != plan["coverage"]
                    or row["body_ref"] != plan["projected_body_ref"]
                    or row["source_id"] != plan["source_search_id"]):
                raise ValueError("PROJECTION_ACTUAL_MATERIAL_MISMATCH")
        if self.emit is not None:
            self.emit({"event": "freshness_projection", "status": "delivered",
                       "arm": self.arm,
                       "request_id": request_id, "public_message_index": public_index,
                       "request_object_sha256": request["request_object_sha256"],
                       "projected_material": projected.materials,
                       "actual_material": {
                           call_id: {"body_ref": row["body_ref"],
                                     "coverage": row["coverage"],
                                     "source_id": row["source_id"]}
                           for call_id, row in material.items()},
                       "items": [{**item,
                                  "actual_tool_body_ref": material.get(
                                      item["source_tool_call"], {}).get("body_ref")}
                                 for item in projected.items],
                       "exact_reads": projected.exact_reads,
                       "exact_store_reads": len(projected.exact_reads)})
