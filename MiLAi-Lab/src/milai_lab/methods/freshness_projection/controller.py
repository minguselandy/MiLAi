"""Join a request-copy projection to the actual B1 Provider receipt."""

from __future__ import annotations

import hashlib
from typing import Any

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import canonical_json
from milai_lab.methods.freshness_projection.projection import (
    ProjectedRequest,
    project_current_evidence,
)

RECIPE_ID = "milai-freshness-projection-json-action-v1"
TRANSPORT_VARIANT = "json_action_freshness_projection_v1"
ARMS = ("b1_control", "a1_notice", "a2_quarantine")


class ProjectionController:
    recipe_id = RECIPE_ID

    def __init__(self, observer: ProvenanceObserver, emit: Any = None) -> None:
        self.observer = observer
        self.emit = emit

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
                message_key: str | None) -> ProjectedRequest:
        thread_id, _, _ = self._identity(message_key, 0)
        return project_current_evidence(messages, self.observer.sidecar, thread_id)

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
            if (row is None or row["coverage"] != "PROJECTED_WITHHELD"
                    or row["body_ref"] != plan["projected_body_ref"]
                    or row["source_id"] != plan["source_search_id"]):
                raise ValueError("PROJECTION_ACTUAL_MATERIAL_MISMATCH")
        if self.emit is not None:
            self.emit({"event": "freshness_projection", "status": "delivered",
                       "request_id": request_id, "public_message_index": public_index,
                       "request_object_sha256": request["request_object_sha256"],
                       "projected_material": projected.materials,
                       "items": projected.items,
                       "exact_store_reads": 0})
