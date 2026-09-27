"""Pure LSA request contracts, with no Store, model, or LangGraph imports.

Prompt text and wire shapes are intentionally stable. Keep semantic policy changes
separate from orchestration refactors so historical experiment identities remain useful.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast


class ControlResponseError(ValueError):
    """A control response is incomplete or violates its declared wire contract."""


LOCAL_INTRO = (
    'Maintain short local States for continuing matters from source-identified events. '
)

GLOBAL_INTRO = (
    'Maintain one global working note covering continuing matters from source-identified '
    'events. '
)

EVIDENCE_RULES = (
    'A user request describes intent or pending work; it does not prove an operation was '
    "attempted, completed, or failed. A user's statement about a past event may be kept as "
    'their report, without treating it as a tool-confirmed outcome. A tool event with a '
    'tool_call_id is an observed receipt from an attempted action; read its actual fields, '
    'including any partial effect when ok=false. Distinguish work requested before a receipt '
    'from outcomes observed in an existing receipt. Preserve exact entity names, '
    'identifiers, values, and conditions from sources; do not infer a different entity or '
    'outcome. A later instruction may advance or revise the same matter, even when its verb '
    'changes; use its concrete references and conditions when deciding whether to update an '
    'existing State. '
)

LOCAL_UPDATE = (
    'Independently update States affected by new observations and select focus for the '
    'current question or action. A State may need an update even when it is not in focus; '
    'focus need not include every updated State. '
)

GLOBAL_UPDATE = (
    'Update the note when new observations affect it, whether or not it is in focus. Select '
    'focus separately for the current question or action. '
)

SELECTIVE_UPDATE = (
    'Update only selected existing candidate States affected by new observations; '
    'independently decide whether new observations warrant a new State. '
)

NO_INVENT = (
    'Do not invent a business action, source, or State id. '
)

CREATE_RULE = (
    'A new edit requires id:null, a short nonempty title naming the continuing matter and '
    'content; cite source evidence when available. '
)

UPDATE_RULE = (
    'An update requires an exact existing State id and content; omitted title or needs '
    'preserves its previous value. No change needs no edit. '
)

LOCAL_FOCUS = (
    'Focus is an array of identifiers only: exact ids from states, or new:0, new:1 for a '
    'newly created edit at that zero-based edits index. Never put a title, factual summary, '
    'or answer in focus. Empty focus is valid. Choose focus for the current_task, which is a '
    'query rather than an answer. '
)

GLOBAL_FOCUS = (
    'Focus is an array of identifiers only: the exact existing note id, or new:0 when '
    'creating the first note. Never put a title, factual summary, or answer in focus. Empty '
    'focus is valid. Choose focus for the current_task, which is a query rather than an '
    'answer. '
)

EVIDENCE_END = (
    'Evidence may cite only listed source ids. Keep unresolved needs concise.'
)

GLOBAL_TAIL = (
    ' Keep all continuing matters in this one note. Create it only when none exists; '
    'otherwise update its exact id or make no edit.'
)

LOCAL_TAIL = (
    ' Keep separate local States for matters that can be updated and resumed independently; '
    'a shared topic alone does not make them one matter.'
)


def control_prompt(
    representation: str, local_granularity: bool = False, *,
    maintenance: bool = False, candidate_only: bool = False,
) -> str:
    """Compose the existing policy without editing another prompt by substring."""
    global_note = representation == "global_note"
    if maintenance:
        update = ("Update the note when new observations affect it. " if global_note else
                  SELECTIVE_UPDATE if candidate_only else
                  "Update States affected by new observations independently. ")
    else:
        update = GLOBAL_UPDATE if global_note else LOCAL_UPDATE
    create = ("A new edit requires id:null, a short nonempty title naming the working "
              "note and content; cite source evidence when available. "
              if global_note else CREATE_RULE)
    return "".join((
        GLOBAL_INTRO if global_note else LOCAL_INTRO,
        EVIDENCE_RULES, update, NO_INVENT,
        "Return JSON with edits only. " if maintenance else
        "Return JSON with edits and focus only. ",
        create, UPDATE_RULE,
        "" if maintenance else GLOBAL_FOCUS if global_note else LOCAL_FOCUS,
        EVIDENCE_END,
        GLOBAL_TAIL if global_note else LOCAL_TAIL if local_granularity else "",
    ))


def control_schema(state_ids: list[str], max_states: int,
                   single_note: bool = False) -> dict[str, Any]:
    """Constrain new-State titles and focus to actual or request-local identifiers."""
    fields: dict[str, Any] = {
        "title": {"type": "string", "minLength": 1},
        "content": {"type": "string", "minLength": 1},
        "needs": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    }
    new_edit = {"type": "object", "properties": {"id": {"type": "null"}, **fields},
                "required": ["id", "title", "content"], "additionalProperties": False}
    existing_edit = {
        "type": "object", "properties": {"id": {"enum": state_ids}, **fields},
        "required": ["id", "content"], "additionalProperties": False,
    }
    edits = ([existing_edit] if single_note and state_ids else
             [new_edit, existing_edit] if state_ids else [new_edit])
    focus_ids = ([*state_ids, *([] if state_ids else ["new:0"])] if single_note else
                 [*state_ids, *(f"new:{index}" for index in range(max_states))])
    return {
        "type": "object", "properties": {
            "edits": {"type": "array", "items": (
                {"oneOf": edits} if len(edits) > 1 else edits[0]),
                "maxItems": max_states},
            "focus": {"type": "array", "items": {"enum": focus_ids}},
        },
        "required": ["edits", "focus"], "additionalProperties": False,
    }


def selection_schema(field: Literal["read_ids", "update_ids"],
                     state_ids: set[str]) -> dict[str, Any]:
    """Keep candidate order out of the enum while preserving the response wire shape."""
    items: dict[str, Any] = {"type": "string"}
    if state_ids:
        items["enum"] = sorted(state_ids)
    return {"type": "object", "properties": {
        field: {"type": "array", "items": items, "maxItems": len(state_ids)}},
        "required": [field], "additionalProperties": False}


def selected_ids(plan: dict[str, Any], field: str,
                 allowed: set[str]) -> list[str] | None:
    """Validate once; preserve model order and reject, rather than repair, bad IDs."""
    values = plan.get(field)
    if (set(plan) != {field} or not isinstance(values, list)
            or any(not isinstance(key, str) for key in values)):
        return None
    unique = set(values)
    return cast(list[str], values) if len(unique) == len(values) and unique <= allowed else None


def state_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in (
        "id", "title", "content", "needs", "evidence_refs", "revision")}


def state_directory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in ("id", "title", "needs", "revision")}
            for row in rows]


READ_SELECTOR_PROMPT = (
    "From the updated State directory and current task, select the State "
    "ids needed for the current answer or action. Empty and multiple "
    "selections are valid. Return read_ids only."
)


def read_selector_payload(query: str, observations: list[dict[str, Any]],
                          rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One directory A contract for live LR/LRU and frozen read diagnostics."""
    return {"current_task": query, "new_observations": observations,
            "directory": state_directory(rows)}


def event_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "kind", "actor", "tool_call_id", "content")
            if key in row}


def parse_json_response(receipt: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = receipt["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ControlResponseError("LSA_CONTROL_INCOMPLETE")
        value = json.loads(choice["message"]["content"])
        if not isinstance(value, dict):
            raise ControlResponseError("LSA_CONTROL_INVALID_SHAPE")
        return cast(dict[str, Any], value)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ControlResponseError("LSA_CONTROL_INVALID_RESPONSE") from error


def parse_control_response(receipt: dict[str, Any]) -> dict[str, Any]:
    value = parse_json_response(receipt)
    if (set(value) != {"edits", "focus"} or not isinstance(value["edits"], list)
            or not isinstance(value["focus"], list)
            or any(not isinstance(key, str) for key in value["focus"])):
        raise ControlResponseError("LSA_CONTROL_INVALID_SHAPE")
    return value
