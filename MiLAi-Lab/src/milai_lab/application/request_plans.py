"""Compile current user intent parameters into the two existing request contracts.

Plans describe requested work, not permission or observed results. The caller
binds them to the actual user input and registers them before business dispatch.
No memory prose supplies object identities, versions or completion status.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]

from milai_lab.application.document_publication import document_schemas
from milai_lab.application.tools import BUSINESS_SCHEMAS


def _application_contract(workflow: str) -> tuple[list[dict[str, Any]], str, str]:
    workflow = {"reservation": "reservation_v1", "document": "document_publication_v1"}.get(
        workflow, workflow
    )
    if workflow == "reservation_v1":
        return BUSINESS_SCHEMAS, "get_reservation", "item_key"
    if workflow == "document_publication_v1":
        return document_schemas(), "get_document_status", "title"
    raise ValueError("APPLICATION_REQUEST_WORKFLOW_INVALID")


def application_operation_catalog(workflow: str) -> list[dict[str, str]]:
    """Project the public operation meanings without parameters or object state."""
    schemas, _, _ = _application_contract(workflow)
    return [{"name": schema["function"]["name"],
             "description": schema["function"]["description"]} for schema in schemas]


def application_requests_schema(workflow: str) -> dict[str, Any]:
    """The native declaration's array schema, derived from existing tool inputs.

    Target literals occur once. Arguments omit the target and fields that must
    come from a real lookup: reservation_id and document_version.
    """
    schemas, query, target_field = _application_contract(workflow)
    actions = []
    target = {}
    for schema in schemas:
        name = schema["function"]["name"]
        parameters = deepcopy(schema["function"]["parameters"])
        if name == query:
            target = parameters
            target["description"] = schema["function"]["description"]
            target["properties"][target_field]["minLength"] = 1
            continue
        for field in (target_field, "reservation_id", "document_version"):
            parameters["properties"].pop(field, None)
            if field in parameters["required"]:
                parameters["required"].remove(field)
        for definition in parameters["properties"].values():
            if definition.get("type") == "string":
                definition["minLength"] = 1
        actions.append({
            "type": "object", "additionalProperties": False,
            "description": schema["function"]["description"],
            "properties": {"operation": {"const": name}, "arguments": parameters},
            "required": ["operation", "arguments"],
        })
    return {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"target": target, "actions": {
            "type": "array", "minItems": 1, "items": {"oneOf": actions},
        }},
        "required": ["target", "actions"],
    }}


def compile_application_requests(
    workflow: str,
    application_requests: Sequence[Mapping[str, Any]],
    *,
    save_result: bool,
    feedback: bool = True,
) -> list[dict[str, Any]]:
    """Return one existing C requirements object for each declared target.

    The declaration schema is checked at this boundary. Completion fields and
    dependent arguments come from the workflow contract, not model output. This
    validates shape only; the semantic request interpretation stays unchecked.
    """
    validate(list(application_requests), application_requests_schema(workflow))
    reservation = workflow in {"reservation", "reservation_v1"}
    result = []
    for request in application_requests:
        target = deepcopy(dict(request["target"]))
        actions = {action["operation"]: action["arguments"] for action in request["actions"]}
        if len(actions) != len(request["actions"]):
            raise ValueError("APPLICATION_REQUEST_DUPLICATE_OPERATION")
        steps = []
        if reservation:
            if "reserve_and_label" in actions:
                arguments = {**target, **deepcopy(actions["reserve_and_label"])}
                steps.append({"id": "reservation", "operation": "reserve_and_label",
                              "arguments": arguments, "completed": deepcopy(arguments)})
            steps.append({
                "id": "label", "operation": "complete_label", "arguments": {},
                "arguments_from_state": {"reservation_id": "reservation_id"},
                "completed": {**target, "label_status": "created"},
            })
        else:
            for action in request["actions"]:
                operation, values = action["operation"], deepcopy(action["arguments"])
                if operation == "create_or_update_draft":
                    step_id = "draft"
                    arguments = {**target, **values, "document_version": 0}
                    completed = {**target, "content": values["content"]}
                elif operation == "approve_document_version":
                    step_id, arguments = "approve", dict(target)
                    completed = {**target, "approval_status": "approved"}
                else:
                    step_id, arguments = "publish", {**target, **values}
                    completed = {**target, "publication_status": "published",
                                 "audience": values["audience"]}
                steps.append({
                    "id": step_id, "operation": operation, "arguments": arguments,
                    "arguments_from_state": {"document_version": "document_version"},
                    "completed": completed,
                })
        result.append({"target": target, "steps": steps,
                       "save_result": save_result, "feedback": feedback})
    return result


def project_stage_receipt(
    step: Mapping[str, Any], result: Mapping[str, Any],
) -> dict[str, Any]:
    """Project an actual result onto an already registered stage, retaining it.

    The caller supplies the actual journal result including receipt, source and
    call identity. A combined partial receipt is not a partial label effect when
    the workflow explicitly reports that no label was created. Unknown dispatch
    effects remain unknown even if cached fields look like completed work.
    """
    projected = deepcopy(dict(result))
    receipt = result.get("receipt") or {}
    effect = result.get("business_effect", "unknown")
    satisfied = all(receipt.get(field) == value for field, value in step["completed"].items())
    stage_effect = effect
    if effect != "unknown":
        if satisfied and effect in {"confirmed", "partial"}:
            stage_effect = "confirmed"
        elif (
            step["operation"] == "complete_label"
            and receipt.get("label_status") == "not_created"
            and receipt.get("status") in {"reserved_label_failed", "label_service_unavailable"}
        ):
            stage_effect = "none"
    projected.update(original_business_effect=effect, business_effect=stage_effect,
                     stage_satisfied=effect != "unknown" and satisfied)
    return projected
