"""Request-local ODR validation and append-only analysis records."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import canonical_json
from milai_lab.methods.on_demand_reconstruction.evidence_view import EvidenceView
from milai_lab.methods.on_demand_reconstruction.freshness import freshness_block, inspect_freshness
from milai_lab.methods.on_demand_reconstruction.schema import (
    ReconstructionError,
    validate_reconstruction,
)

ODR_RECIPE_ID = "milai-odr-request-reconstruction-json-action-v1"
ODR_TRANSPORT_VARIANT = "json_action_reconstruction_v1"
ARMS = ("b1_control", "freshness_only", "odr")


class ODRController:
    recipe_id = ODR_RECIPE_ID
    def __init__(self, observer: ProvenanceObserver, arm: str, trace_path: Path) -> None:
        if arm not in ARMS or arm == "b1_control":
            raise ValueError("ODR_CONTROLLER_ARM_INVALID")
        self.observer = observer
        self.arm = arm
        self.trace_path = trace_path
        self.view = EvidenceView(observer.sidecar)
        self._thread_id: str | None = None
        self._public_index: int | None = None
        self._planned: dict[str, str] = {}
        self._freshness: dict[str, dict[str, Any]] = {}

    def begin_public_message(self, scope: Any, public_index: int) -> None:
        self._thread_id = scope.config()["configurable"]["thread_id"]
        self._public_index = public_index
        self._planned = {}
        self._freshness = {}

    def _scope(self) -> tuple[str, int]:
        if self._thread_id is None or self._public_index is None:
            raise ReconstructionError("ODR_PUBLIC_SCOPE_MISSING")
        return self._thread_id, self._public_index

    def request_id(self, request_index: int) -> str:
        thread, public_index = self._scope()
        identity = canonical_json([thread, public_index, request_index])
        return hashlib.sha256(identity.encode()).hexdigest()

    def project(self, messages: list[dict[str, Any]]) -> tuple[str, str]:
        thread, index = self._scope()
        handles = self.view.handles(messages, thread_id=thread, public_index=index)
        self._planned = {f"e{i}": ref for i, ref in enumerate(handles)}
        statuses = inspect_freshness(handles, self.observer.sidecar)
        self._freshness = statuses
        block = freshness_block(handles, statuses)
        if self.arm == "freshness_only":
            return block, ""
        labels = [f"{short}: {handles[ref]['label']}"
                  for short, ref in self._planned.items()]
        evidence = "Available evidence in this request:\n"
        evidence += "\n".join(labels) if labels else "none"
        return block, evidence

    def _append(self, row: dict[str, Any]) -> None:
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(canonical_json(row) + "\n")

    def reject(self, request_index: int, response_id: str, code: str,
               raw: Any = None) -> None:
        self._append({"event": "odr_reconstruction", "request_id": self.request_id(request_index),
                      "response_id": response_id, "status": "rejected", "code": code,
                      "raw_reconstruction": raw})

    def accept(self, request_index: int, response_id: str,
               reconstruction: Any, action: dict[str, Any],
               business_names: set[str]) -> dict[str, Any]:
        if self.arm != "odr":
            raise ReconstructionError("ODR_RECONSTRUCTION_IN_FRESHNESS_ONLY")
        validate_reconstruction(reconstruction)
        thread, index = self._scope()
        request_id = self.request_id(request_index)
        delivered = self.view.handles([], thread_id=thread, public_index=index,
                                      request_id=request_id)
        freshness = {ref: self._freshness[ref] for ref in delivered
                     if ref in self._freshness}
        bound = None
        if reconstruction is not None:
            normalized = []
            seen: set[tuple[str, str]] = set()
            for evidence in reconstruction["evidence_used"]:
                short = evidence["ref"]
                ref = self._planned.get(short, short)
                if ref not in delivered:
                    raise ReconstructionError("ODR_EVIDENCE_NOT_DELIVERED")
                if (evidence["support_role"] == "supports_value"
                        and delivered[ref]["kind"] == "memory_unknown"):
                    raise ReconstructionError("ODR_MEMORY_REVISION_UNKNOWN")
                if (evidence["support_role"] == "supports_value"
                        and freshness.get(ref, {}).get("status") in {"SUPERSEDED", "DELETED"}):
                    raise ReconstructionError("ODR_STALE_SUPPORTS_VALUE")
                key = ref, evidence["support_role"]
                if key not in seen:
                    normalized.append({"ref": ref, "support_role": evidence["support_role"]})
                    seen.add(key)
            bound = {**reconstruction, "evidence_used": normalized}
        business = any(call["name"] in business_names for call in action.get("calls", []))
        row = {"event": "odr_reconstruction", "request_id": request_id,
               "response_id": response_id, "status": "accepted", "reconstruction": bound,
               "calls": action.get("calls"), "answer": action.get("answer"),
               "freshness": freshness,
               "action_without_reconstruction": bool(business and bound is None)}
        if row["action_without_reconstruction"]:
            row["metric"] = "ACTION_WITHOUT_RECONSTRUCTION"
        self._append(row)
        return row
