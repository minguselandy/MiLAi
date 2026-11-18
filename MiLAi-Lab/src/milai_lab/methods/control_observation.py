"""Model-independent legal observations and complete action bindings."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict
from typing import Any, cast

from milai_lab.memory.literal_projection import (
    compact_observation_state,
    expand_observation_state,
    observation_object,
    project_observation_state,
)
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

COMPACT_ACTION_PROJECTIONS = {"compact_actions", "compact_actions_request_text"}
VISIBLE_SOURCE_HANDLES_V2 = "control-observation-visible-source-handles-v2"
BOUND_VIEW_UNITS_V3 = "control-observation-bound-view-units-v3"
ACTION_BOUND_PROJECTIONS = {
    "shared_actions", "shared_actions_request_text", *COMPACT_ACTION_PROJECTIONS}
ACTION_BINDING_INSTRUCTIONS = (
    " action_bindings lists each offered action's exact target and complete parameters. "
    "Match the decision-head action ID to that table; the short head names its operation kind."
)


def payload_actions(payload: dict[str, Any]) -> list[MemoryAction]:
    """Recover exact recorded options from the binding table or legacy export metadata."""
    state = observation_object(payload["state"])
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
    state = observation_object(payload["state"])
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
        if projection.endswith("request_text"):
            shared = project_request_text(shared)
        if projection in COMPACT_ACTION_PROJECTIONS:
            shared = {**shared, "state": compact_observation_state(shared["state"])}
        return shared
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
                "source", "role", "origin", "range", "reported_at", "captured_at",
                "calendar_context"))
                for source in item.get("evidence", [])]}
            for item in state["visible_evidence"]],
        "pending_candidates": [fields(item, (
            "item_index", "kind", "navigation_only", "date", "visibility",
            "can_expand_context", "revision", "version_view", "control_pool_rank"))
            for item in state["pending_candidates"]],
        "views": [fields(item, (
            "id", "slot", "revision", "visibility", "pending_events", "source_bindings",
            "source_metadata"))
            for item in state["views"]],
        "new_events": [fields(item, (
            "source_ref", "role", "origin", "reported_at", "captured_at", "calendar_context"))
            for item in state["new_events"]],
        **({"observed_materials": state["observed_materials"],
            "observed_evidence": [fields(item, (
                "label", "kind", "revision", "visibility", "source_bindings"))
                for item in state["observed_evidence"]]}
           if "observed_materials" in state else {}),
        **({"retrieved_scopes": [fields(item, ("item_index", "source_ranges"))
                                  for item in state["retrieved_scopes"]]}
           if "retrieved_scopes" in state else {}),
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
            "retrieved_scope_indices selects original retrieved ranges (including their "
            "provided context), listed with exact bodies in retrieved_scopes. These may include "
            "another candidate covered by an acquired expanded context, without a separate READ. "
            "Full expanded observations remain available; scope selection performs no new READ. "
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


def control_input(state: MemoryControlState, actions: list[MemoryAction]) -> dict[str, Any]:
    """The online contract: actual observations and executable options, without labels."""
    return {"observation": state.project(), "actions": [asdict(a) for a in actions]}


def visible_source_handle_input(online: dict[str, Any]) -> dict[str, Any]:
    """Alias visible machine Source handles while retaining every literal body/query.

    Only handles anchored in the public observation are aliased. Handles that
    occur in literal content remain literal everywhere. Unobserved binding-only
    strings stay unchanged; no object lookup or hidden source access is involved.
    This is an encoder view: executable actions and their actual parameters remain
    with the caller, which continues to bind the returned original action ID.
    """
    data = {key: copy.deepcopy(online[key]) for key in ("observation", "actions")}
    literal_keys = {"content", "excerpt", "request", "query", "text"}
    literals: list[str] = []
    strings: list[str] = []

    def collect_literals(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    strings.append(key)
                if key in literal_keys and isinstance(item, str):
                    literals.append(item)
                collect_literals(item)
        elif isinstance(value, list):
            for item in value:
                collect_literals(item)
        elif isinstance(value, str):
            strings.append(value)

    collect_literals(data)
    refs: list[str] = []

    def collect_refs(value: Any) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                if key not in literal_keys:
                    candidates = ([value[key]] if key == "source_ref" else
                                  value[key] if key == "source_refs"
                                  and isinstance(value[key], list) else [])
                    for ref in candidates:
                        if (isinstance(ref, str) and ref and ref not in refs
                                and not ref.startswith("@source-handle:")):
                            refs.append(ref)
                    collect_refs(value[key])
        elif isinstance(value, list):
            for item in value:
                collect_refs(item)

    anchors = ("new_events", "visible_evidence", "observed_evidence", "observed_materials",
               "pending_candidates")
    observation = data["observation"]
    for key in anchors:
        collect_refs(observation.get(key))
    for key in sorted(observation):
        if key not in anchors:
            collect_refs(observation[key])
    aliases: dict[str, str] = {}
    number = 0
    for ref in refs:
        if any(ref in text for text in literals):
            continue
        alias = f"@source-handle:{number}"
        while any(alias in text for text in strings):
            number += 1
            alias = f"@source-handle:{number}"
        aliases[ref] = alias
        number += 1

    pattern = (re.compile(r"(?<!\w)(?:" + "|".join(
        re.escape(ref) for ref in sorted(aliases, key=len, reverse=True)) + r")(?!\w)")
        if aliases else None)

    def replace(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {aliases.get(name, name): replace(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [replace(item, key) for item in value]
        if isinstance(value, str):
            if key in {"source_ref", "source_refs"}:
                return aliases.get(value, value)
            if key in {"target", "id"} and pattern is not None:
                return pattern.sub(lambda match: aliases[match.group()], value)
        return value

    return cast(dict[str, Any], replace(data))


def legacy_control_input(row: dict[str, Any]) -> dict[str, Any]:
    """Recover saved legal input; leave all offline supervision outside the observation."""
    observation = copy.deepcopy(expand_observation_state(observation_object(row["state"])))
    observation.pop("action_bindings", None)
    return {"observation": observation, "actions": [asdict(a) for a in payload_actions(row)]}


def proposed_delivery_projection(observation: dict[str, Any],
                                 action: dict[str, Any]) -> dict[str, Any]:
    """Resolve a bound HANDOFF using only already visible material projections.

    This does not open a Source, reconstruct a hidden body or certify semantics.
    An unavailable projection stays explicitly unresolved instead of using a
    different item's body. Retrieved scopes take their exact offered range.
    """
    parameters = action["parameters"]
    if not parameters:
        return {"material_projection": copy.deepcopy(observation["visible_evidence"]),
                "unresolved_indices": [], "scope": "current_visible_projection"}
    scopes = {item["item_index"]: item["evidence"]
              for item in observation.get("retrieved_scopes", []) if "evidence" in item}
    acquired: dict[str, Any] = {}
    for layer in [observation["visible_evidence"], observation.get("observed_evidence", [])]:
        current_layer: dict[str, Any] = {}
        for item in layer:
            for label in [item["label"], *item.get("also_selected_as", [])]:
                if label in current_layer and current_layer[label] != item:
                    raise ValueError(
                        "Conflicting material projections within one observation layer")
                current_layer[label] = item
        # Explicit delivery indices address the acquired original. Its current
        # selection can be a narrower K projection of the same object index.
        acquired.update(current_layer)
    projections, unresolved = [], []
    for index in parameters["delivery_indices"]:
        item = (scopes.get(index) if index in parameters.get("retrieved_scope_indices", [])
                else acquired.get(f"e{index}"))
        if item is None:
            unresolved.append(index)
        elif item not in projections:
            projections.append(copy.deepcopy(item))
    return {"material_projection": projections, "unresolved_indices": unresolved,
            "source_alias_scope": "local_observation_not_rendered_reader_aliases",
            "scope": "bound_acquired_projection_only_not_semantic_proof"}


def proposed_view_unit_projection(observation: dict[str, Any],
                                  action: dict[str, Any]) -> dict[str, Any]:
    """Resolve selected View content from the supplied observation, without Store access."""
    parameters = action["parameters"]
    matches = [v for v in observation.get("views", [])
               if v.get("id") == action["target"]
               and v.get("slot", "current") == parameters.get("slot", "current")]
    if len(matches) > 1:
        raise ValueError("Conflicting public View targets in one observation")
    if not matches:
        return {"status": "unresolved_parent", "scope": "public_observation_only"}
    view = matches[0]
    if (view.get("visibility") != "visible" or view.get("body_delivered") is False
            or not isinstance(view.get("interpretation"), dict)):
        return {"status": "parent_unavailable", "scope": "public_observation_only"}
    bound_revision = parameters.get("view_revision", view["revision"])
    if type(bound_revision) is not int or bound_revision != view["revision"]:
        return {"status": "parent_revision_mismatch", "scope": "public_observation_only"}
    from milai_lab.methods.query_structure_projection import project_structure_units

    parent = {"kind": "query_structure", "visibility": "visible",
        "revision": view["revision"], "interpretation": copy.deepcopy(view["interpretation"]),
        "source_bindings": copy.deepcopy(view["source_bindings"]),
        "source_metadata": {"by_alias": copy.deepcopy(view.get("source_metadata", {}))},
        "semantics": view.get("interpretation_semantics"),
        "parent_query_time": view.get("query_time"),
        "requested_query_time": observation.get("task", {}).get("query_time")}
    requested = parameters.get("view_nodes", list(parent["interpretation"]["nodes"]))
    selected = project_structure_units(parent, requested)
    # JSON map-key sorting must not turn opaque node aliases into semantic
    # ordering. Rows retain recorded order and the complete literal node value.
    selected["interpretation"]["nodes"] = [
        {"node_id": node_id, "node": value}
        for node_id, value in selected["interpretation"]["nodes"].items()]
    selected["node_map_encoding"] = "ordered_node_rows_v1"
    return {"status": "bound_public_view_units", "parent_id": view["id"],
            **selected, "scope": "Observed interpretation only; no new Source or truth proof"}


def control_texts(online: dict[str, Any], *, delivery_context: bool = False,
                  view_unit_context: bool = False,
                  ) -> tuple[str, list[str]]:
    """Serialize only the online allowlist, with no action-ID or menu-position feature.

    Target descriptions include already visible matching material. This does not open
    sources or encode unread bodies. Full parameters remain in the action description.
    """
    observation = copy.deepcopy(online["observation"])
    observation.pop("action_bindings", None)
    last = observation.get("last_result")
    if last is not None and "action" in last:
        last["action"].pop("id", None)

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    descriptions = []
    for action in online["actions"]:
        parameters = action["parameters"]
        matching = []
        for item in observation.get("pending_candidates", []):
            if (parameters.get("index") is not None
                    and item.get("item_index") == parameters["index"]):
                matching.append(item)
        bound_source = parameters.get("observed_source", {}).get("source_ref")
        if bound_source is not None:
            matching.extend(item for item in observation.get("new_events", [])
                            if item.get("source_ref") == bound_source)
        description = {"kind": action["kind"], "target": action["target"],
                       "parameters": parameters, "visible_target": matching}
        if delivery_context and action["kind"] == "HANDOFF":
            description["proposed_delivery"] = proposed_delivery_projection(observation, action)
        if view_unit_context and action["kind"] == "USE_VIEW":
            description["proposed_view_units"] = proposed_view_unit_projection(observation, action)
        descriptions.append(dumps(description))
    return dumps(observation), descriptions


def joint_control_texts(online: dict[str, Any], *, wrapped_json: bool = False,
                       view_unit_context: bool = False,
                        ) -> tuple[str, list[str]]:
    """Lossless shared state and complete bindings, with request-local option aliases.

    All bindings precede all readout positions, so even the first causal readout
    can inspect the whole legal menu. Original IDs only map outputs to operations.
    """
    state = copy.deepcopy(online["observation"])
    state.pop("action_bindings", None)
    last = state.get("last_result")
    if last is not None and "action" in last:
        last["action"].pop("id", None)
    state["action_bindings"] = [{**copy.deepcopy(action), "id": f"a{index}"}
                                for index, action in enumerate(online["actions"])]
    if view_unit_context:
        for action in state["action_bindings"]:
            if action["kind"] == "USE_VIEW":
                action["proposed_view_units"] = proposed_view_unit_projection(state, action)
    compact = compact_observation_state(project_observation_state(state))
    # compact_observation_state already returns JSON text. Preserve the wrapped
    # v1 layout only for its explicitly versioned existing checkpoints.
    body = (json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            if wrapped_json else compact)
    prefix = (INSTRUCTIONS + "\nState and complete action bindings:\n"
              + body
              + "\nScore each offered binding:\n")
    return prefix, [f"\nOption a{index} ({action['kind']}) value:"
                    for index, action in enumerate(online["actions"])]
