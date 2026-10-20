"""One operation projection for native Laya, generation and training exports."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from milai_lab.memory.literal_projection import project_observation_state
from milai_lab.memory.request_text import project_request_text
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState

INSTRUCTIONS = (
    "Choose the next memory operation for the original task using actual observations. "
    "Candidate excerpts are navigation, not delivered evidence. USE_VIEW opens an existing "
    "source-bound interpretation without generation; REFRESH_VIEW generates an interpretation "
    "from the specified actual sources. Consider subject, report/effective time, scope and "
    "new exceptions. HANDOFF sends only opened material to the Reader; it cannot fill missing "
    "facts. Read necessary available evidence before handoff, and avoid repeating work when "
    "the delivered material already supports the task. A tool receipt is not semantic proof."
)

RETRIEVAL_INSTRUCTIONS = (
    "Control this MiLAi evidence retrieval, not the Host's entire task. "
    "Follow the Host request, purpose, required points, target scope, as_of time and limits. "
    "Use actual observations and operation results to choose the next available operation "
    "with its bound parameters. Candidate excerpts are navigation, not returned evidence. "
    "Known evidence was previously delivered; its current visibility and applicability "
    "must be considered separately. USE_VIEW opens a source-bound interpretation, not a "
    "certified answer. REFRESH_VIEW generates an interpretation from actual sources. "
    "Read or refresh when relevant changes or missing evidence require it; avoid repeating "
    "work when the evidence already supports this request. HANDOFF returns only opened "
    "material, never invented facts or the Host's final answer."
)


def project_operation_payload(payload: dict[str, Any], projection: str) -> dict[str, Any]:
    """Project matched training/live inputs; task and actual operation options stay fixed."""
    if projection == "full":
        return payload
    if projection in {"shared", "shared_request_text"}:
        shared = {**payload, "state": project_observation_state(payload["state"])}
        return project_request_text(shared) if projection == "shared_request_text" else shared
    if projection != "mechanical":
        raise ValueError(f"Unknown operation state projection: {projection}")

    def fields(item: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
        return {key: item[key] for key in names if key in item}

    state = payload["state"]
    result = state["last_result"]
    last = None if result is None else fields(result, (
        "ok", "status", "index", "view_id", "revision", "candidates", "visibility",
        "body_delivered", "effect", "error_type", "revisions", "next_cursor"))
    if last is not None and "action" in result:
        last["action"] = fields(result["action"], ("id", "kind", "parameters"))
    return {**payload, "state": {
        "task": state["task"], "budget": state["budget"], "last_result": last,
        "visible_evidence": [{**fields(item, (
            "label", "kind", "revision", "version_view", "visibility", "dependency_status",
            "source_bindings", "reused_sources")), "evidence": [fields(source, (
                "source", "role", "origin", "range", "reported_at", "captured_at"))
                for source in item.get("evidence", [])]}
            for item in state["visible_evidence"]],
        "pending_candidates": [fields(item, (
            "item_index", "kind", "navigation_only", "date", "visibility",
            "can_expand_context", "revision", "version_view", "control_pool_rank"))
            for item in state["pending_candidates"]],
        "views": [fields(item, (
            "id", "slot", "revision", "visibility", "pending_events", "source_bindings"))
            for item in state["views"]],
        "new_events": [fields(item, (
            "source_ref", "role", "origin", "reported_at", "captured_at"))
            for item in state["new_events"]],
        **({"observed_materials": state["observed_materials"],
            "observed_evidence": [fields(item, (
                "label", "kind", "revision", "visibility", "source_bindings"))
                for item in state["observed_evidence"]]}
           if "observed_materials" in state else {}),
    }}


def operation_payload(
    state: MemoryControlState, actions: list[MemoryAction], projection: str = "full",
) -> dict[str, Any]:
    instructions = (RETRIEVAL_INSTRUCTIONS
                    if "retrieval_request" in state.task else INSTRUCTIONS)
    if state.observed_materials is not None:
        instructions += (
            " observed_materials lists actual acquired items and whether each is selected. "
            "observed_evidence contains controller-only bodies not in the current delivery; "
            "its source aliases are local to each item. visible_evidence is the selected packet. "
            "READ observe_only acquires material without adding it to delivery. USE_VIEW "
            "replace_delivery selects only that View. HANDOFF delivery_indices explicitly "
            "chooses an offered acquired packet; plain HANDOFF retains current delivery. "
            "Only selected material goes to the Host; observations and generation still cost work."
        )
    payload = {"state": state.project(), "questions": {"next": {
        "type": "choice", "instructions": instructions,
        "criteria": {action.id: f"{action.kind} {action.target} "
                     + json.dumps(action.parameters, ensure_ascii=False, separators=(",", ":"))
                     for action in actions},
    }}}
    return project_operation_payload(payload, projection)


@dataclass
class LayaMemoryPolicy:
    predict: Callable[[dict[str, Any]], dict[str, Any]]
    projection: str = "full"

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        result = self.predict(operation_payload(state, actions, self.projection))
        return str(result["choice"])


@dataclass
class GenerativeMemoryPolicy:
    call: Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
    projection: str = "full"

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        payload = operation_payload(state, actions, self.projection)
        schema = {"type": "object", "properties": {"choice": {
            "type": "string", "enum": [a.id for a in actions]}},
            "required": ["choice"], "additionalProperties": False}
        result = self.call("memory_control", [{"role": "system",
            "content": payload["questions"]["next"]["instructions"]},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], schema)
        return str(result["choice"])
