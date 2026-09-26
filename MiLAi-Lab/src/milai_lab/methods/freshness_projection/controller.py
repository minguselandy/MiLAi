"""Join a request-copy projection to the actual B1 Provider receipt."""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.store.base import BaseStore

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import canonical_json
from milai_lab.methods.freshness_projection.lineage import (
    delivered_exact_snapshot,
    project_derived_assistants,
)
from milai_lab.methods.freshness_projection.projection import (
    ProjectedRequest,
    project_current_evidence,
)

RECIPE_ID = "milai-freshness-projection-json-action-v1"
TRANSPORT_VARIANT = "json_action_freshness_projection_v1"
SER_RECIPE_ID = "milai-ser-v20-json-action-v1"
SER_TRANSPORT_VARIANT = "json_action_ser_v20_v1"
SER_V21_RECIPE_ID = "milai-ser-v21-json-action-v1"
SER_V21_TRANSPORT_VARIANT = "json_action_ser_v21_v1"
ARMS = ("b1_control", "a1_notice", "a2_quarantine", "a3_exact_refresh",
        "a4_selective_rebase", "a5_rank_bounded_rebase")


class ProjectionController:
    recipe_id = RECIPE_ID

    def __init__(self, observer: ProvenanceObserver, emit: Any = None,
                 *, arm: str = "a2_quarantine", store: BaseStore | None = None,
                 stage: str = "v19", refresh_until_current_candidate: bool = False,
                 max_exact_refresh_per_search: int | None = None) -> None:
        if arm not in {"a2_quarantine", "a3_exact_refresh", "a4_selective_rebase",
                       "a5_rank_bounded_rebase"}:
            raise ValueError("PROJECTION_ARM_INVALID")
        if arm in {"a3_exact_refresh", "a4_selective_rebase",
                   "a5_rank_bounded_rebase"} and store is None:
            raise ValueError("PROJECTION_EXACT_STORE_MISSING")
        if stage not in {"v19", "v20", "v21"} or (
            arm == "a4_selective_rebase" and stage not in {"v20", "v21"}
        ) or (arm == "a5_rank_bounded_rebase" and stage != "v21"):
            raise ValueError("PROJECTION_STAGE_INVALID")
        self.observer = observer
        self.emit = emit
        self.arm = arm
        self.store = store
        self.stage = stage
        self.recipe_id = (SER_V21_RECIPE_ID if stage == "v21" else
                          SER_RECIPE_ID if stage == "v20" else RECIPE_ID)
        self.refresh_until_current_candidate = (
            refresh_until_current_candidate if arm == "a5_rank_bounded_rebase" else False)
        self.max_exact_refresh_per_search = (
            max_exact_refresh_per_search if arm == "a5_rank_bounded_rebase" else None)

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
                message_key: str | None, request_index: int,
                graph_messages: list[BaseMessage] | None = None) -> ProjectedRequest:
        wall_started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
        thread_id, public_index, request_id = self._identity(message_key, request_index)
        store = self.store

        def record_read(read: dict[str, Any]) -> None:
            if self.emit is not None:
                self.emit({"event": "freshness_exact_read", "arm": self.arm,
                           "request_id": request_id,
                           "public_message_index": public_index,
                           "provider_delivery": False, **read})

        factual = project_current_evidence(
            messages, self.observer.sidecar, thread_id,
            get_current=(lambda namespace, memory_id: store.get(
                namespace, memory_id, refresh_ttl=False))
            if store is not None and self.arm in {"a3_exact_refresh", "a4_selective_rebase",
                                                   "a5_rank_bounded_rebase"}
            else None,
            record_exact_read=record_read,
            refresh_until_current_candidate=self.refresh_until_current_candidate,
            max_exact_refresh_per_search=self.max_exact_refresh_per_search,
        )
        if self.arm not in {"a4_selective_rebase", "a5_rank_bounded_rebase"}:
            result = factual
        else:
            if graph_messages is None:
                raise ValueError("REBASE_GRAPH_MESSAGES_MISSING")
            derived = project_derived_assistants(
                graph_messages, factual.messages, self.observer.sidecar, thread_id)
            result = replace(factual, messages=derived.messages,
                             derived_rebases=derived.rebases,
                             unknown_bindings=derived.unknown_bindings)
        return replace(result, projection_cpu_ns=time.process_time_ns() - cpu_started,
                       projection_wall_ns=time.perf_counter_ns() - wall_started)

    def record_delivery(self, message_key: str | None, request_index: int,
                        projected: ProjectedRequest,
                        action_messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        _, public_index, request_id = self._identity(message_key, request_index)
        request = next((row for row in self.observer.sidecar.rows("requests")
                        if row["request_id"] == request_id), None)
        if request is None or request["status"] != "completed":
            raise ValueError("PROJECTION_REQUEST_NOT_COMPLETED")
        actual_request = self.observer.current_provider_request()
        if (actual_request is None or actual_request.get("messages") != action_messages
                or hashlib.sha256(canonical_json(actual_request).encode()).hexdigest()
                != request["request_object_sha256"]):
            raise ValueError("PROJECTION_ACTUAL_REQUEST_MISMATCH")
        material = {row["tool_call_id"]: row for row in
                    self.observer.sidecar.rows("request_material")
                    if row["request_id"] == request_id}
        for call_id, plan in projected.materials.items():
            row = material.get(call_id)
            if (row is None or row["coverage"] != plan["coverage"]
                    or row["body_ref"] != plan["projected_body_ref"]
                    or row["source_id"] != plan["source_search_id"]):
                raise ValueError("PROJECTION_ACTUAL_MATERIAL_MISMATCH")
        exact_snapshot, unknown_items = delivered_exact_snapshot(projected.items)
        system_offset = len(action_messages) - len(projected.messages)
        for rebase in projected.derived_rebases:
            actual_index = rebase["message_index"] + system_offset
            actual = action_messages[actual_index]
            if (actual.get("role") != "assistant" or
                    actual.get("content") != projected.messages[rebase["message_index"]][
                        "content"]):
                raise ValueError("REBASE_ACTUAL_ASSISTANT_MISMATCH")
            if self.emit is not None:
                self.emit({"event": "derived_output_rebase", "status": "delivered",
                           "request_id": request_id,
                           "request_object_sha256": request["request_object_sha256"],
                           "public_message_index": public_index,
                           "provider_message_index": actual_index, **rebase})
        if self.emit is not None and projected.unknown_bindings:
            self.emit({"event": "derived_output_lineage_unknown",
                       "request_id": request_id,
                       "request_object_sha256": request["request_object_sha256"],
                       "unknown_bindings": projected.unknown_bindings})
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
                       "exact_store_reads": len(projected.exact_reads),
                       "refresh_policy": {
                           "refresh_until_current_candidate": self.refresh_until_current_candidate,
                           "max_exact_refresh_per_search": self.max_exact_refresh_per_search,
                       },
                       "projection_cpu_ns": projected.projection_cpu_ns,
                       "projection_wall_ns": projected.projection_wall_ns,
                       "projection_timing_scope": "inclusive_of_exact_store_get",
                       "exact_snapshot": exact_snapshot,
                       "unknown_snapshot_items": unknown_items})
        return exact_snapshot, unknown_items

    def record_output(self, message_key: str | None, request_index: int,
                      response_id: str, content: str,
                      exact_snapshot: list[dict[str, Any]],
                      unknown_items: int) -> None:
        if self.stage not in {"v20", "v21"}:
            return
        thread_id, public_index, request_id = self._identity(message_key, request_index)
        bound = self.observer.sidecar.record_assistant_lineage(
            thread_id, response_id, request_id, content, exact_snapshot, unknown_items)
        if self.emit is not None:
            self.emit({"event": "assistant_output_lineage",
                       "status": "RECORDED" if bound else "UNKNOWN_BINDING",
                       "request_id": request_id,
                       "public_message_index": public_index,
                       "response_id": response_id,
                       "exact_snapshot": exact_snapshot if bound else [],
                       "unknown_snapshot_items": unknown_items})
