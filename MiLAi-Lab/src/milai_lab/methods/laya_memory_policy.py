"""One operation projection for native Laya, generation and training exports."""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from milai_lab.memory.literal_projection import expand_observation_state, project_observation_state
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

ACTION_BOUND_PROJECTIONS = {"shared_actions", "shared_actions_request_text"}
ACTION_BINDING_INSTRUCTIONS = (
    " action_bindings lists each offered action's exact target and complete parameters. "
    "Match the decision-head action ID to that table; the short head names its operation kind."
)


def payload_actions(payload: dict[str, Any]) -> list[MemoryAction]:
    """Recover exact recorded options from the binding table or legacy export metadata."""
    state = payload["state"]
    criteria = payload["questions"]["next"]["criteria"]
    metadata = payload.get("metadata", {})
    if "action_bindings" in state:
        actions = [MemoryAction(**item)
                   for item in expand_observation_state(state)["action_bindings"]]
    else:
        actions = []
        for key, text in criteria.items():
            kind, parameters = metadata["action_kinds"][key], metadata["action_parameters"][key]
            prefix = kind + " "
            suffix = " " + json.dumps(parameters, ensure_ascii=False, separators=(",", ":"))
            if not text.startswith(prefix) or not text.endswith(suffix):
                raise ValueError("Recorded action text does not match its kind and parameters")
            actions.append(MemoryAction(key, kind, text[len(prefix):-len(suffix)],
                                        copy.deepcopy(parameters)))
    if [action.id for action in actions] != list(criteria):
        raise ValueError("Recorded action bindings differ from the actual option order")
    if "action_parameters" in metadata:
        if any(action.kind != metadata["action_kinds"][action.id]
               or action.parameters != metadata["action_parameters"][action.id]
               for action in actions):
            raise ValueError("Recorded action bindings differ from export metadata")
    return actions


def complete_action_payload(payload: dict[str, Any], actions: list[MemoryAction] | None = None,
                            ) -> dict[str, Any]:
    """Explicit input condition: full arguments in state, short unique IDs in the head.

    This does not invent observed/delivered materials or change executable options.
    Existing shared/legacy checkpoints keep their original representation.
    """
    actions = payload_actions(payload) if actions is None else actions
    state = payload["state"]
    if "action_bindings" not in state:
        state = {**expand_observation_state(state),
                 "action_bindings": [asdict(action) for action in actions]}
    question = payload["questions"]["next"]
    instructions = question["instructions"]
    if not instructions.endswith(ACTION_BINDING_INSTRUCTIONS):
        instructions += ACTION_BINDING_INSTRUCTIONS
    return {**payload, "state": state, "questions": {**payload["questions"], "next": {
        **question, "instructions": instructions, "criteria": {
            action.id: action.kind for action in actions}}}}


def project_operation_payload(payload: dict[str, Any], projection: str) -> dict[str, Any]:
    """Project matched training/live inputs; task and actual operation options stay fixed."""
    if projection == "full":
        return payload
    if projection in ACTION_BOUND_PROJECTIONS:
        payload = complete_action_payload(payload)
    if projection in {"shared", "shared_request_text", *ACTION_BOUND_PROJECTIONS}:
        shared = {**payload, "state": project_observation_state(payload["state"])}
        return project_request_text(shared) if projection.endswith("request_text") else shared
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
        **({"action_bindings": state["action_bindings"]} if "action_bindings" in state else {}),
    }}


def operation_payload(
    state: MemoryControlState, actions: list[MemoryAction], projection: str = "full",
) -> dict[str, Any]:
    instructions = (RETRIEVAL_INSTRUCTIONS
                    if "retrieval_request" in state.task else INSTRUCTIONS)
    projected_state = state.project()
    criteria = {action.id: f"{action.kind} {action.target} "
                + json.dumps(action.parameters, ensure_ascii=False, separators=(",", ":"))
                for action in actions}
    if state.observed_materials is not None:
        instructions += (
            " observed_materials lists actual acquired items and whether each is selected. "
            "observed_evidence contains controller-only bodies not in the current delivery; "
            "its source aliases are local to each item. visible_evidence is the selected packet. "
            "READ observe_only acquires material without adding it to delivery. USE_VIEW "
            "replace_delivery selects only that View. HANDOFF delivery_indices explicitly "
            "chooses an offered acquired packet; plain HANDOFF retains current delivery. "
            "Only selected material goes to the Host; observations and generation still cost work."
            " action_bindings gives each option's complete target and parameters."
            " SEARCH query_from refers to the request, a required point, or the actual search "
            "text of an observed/known material at the supplied index."
        )
        # Native Laya caps individual option text. Keep complete bound arguments in
        # the shared state, with the same identifiers in the short decision head.
        projected_state["action_bindings"] = [asdict(a) for a in actions]
        criteria = {a.id: a.kind for a in actions}
    payload = {"state": projected_state, "questions": {"next": {
        "type": "choice", "instructions": instructions,
        "criteria": criteria,
    }}}
    if projection in ACTION_BOUND_PROJECTIONS:
        payload = complete_action_payload(payload, actions)
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
