"""Literal prose expansion of request information for the retrained E3 contrast."""
from __future__ import annotations

import json
from typing import Any

REQUEST_FIELDS = {
    "request": "The search query",
    "query_time": "The query time",
    "read_goal": "The normalized reading goal",
    "retrieval_request": "The complete Host request",
}


def describe_value(subject: str, value: Any, depth: int = 0) -> str:
    """Render arbitrary JSON details without interpreting their task semantics.

    Quoted text retains literal whitespace and punctuation. Named details and
    ordered items retain nesting, empty containers, nulls and scalar types.
    Extensions use the same grammar as the declared request fields.
    """
    prefix = "  " * depth + subject
    if isinstance(value, dict):
        return "\n".join([
            f"{prefix} has {len(value)} named details:",
            *(describe_value(f"For {json.dumps(key, ensure_ascii=False)}, the value", item,
                             depth + 1) for key, item in value.items()),
        ])
    if isinstance(value, list):
        return "\n".join([
            f"{prefix} has {len(value)} ordered items:",
            *(describe_value(f"Item {i}", item, depth + 1)
              for i, item in enumerate(value, 1)),
        ])
    if value is None:
        return f"{prefix} is explicitly null."
    kind = "text" if isinstance(value, str) else "boolean" if isinstance(value, bool) else "number"
    return f"{prefix} is the {kind} {json.dumps(value, ensure_ascii=False, allow_nan=False)}."


def project_request_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace request fields and their aliases; leave observations and labels intact.

    The operational request still lives in the tool's runtime state. This
    projection changes only model input, so reference resolution, search,
    permissions, limits and result delivery use the original request.
    """
    state = payload["state"]
    task = state["task"]
    fields = [key for key in task if key in REQUEST_FIELDS]
    if not fields:
        return payload
    text = "\n".join(describe_value(REQUEST_FIELDS[key], task[key]) for key in fields)
    return {**payload, "state": {**state, "task": {
        **{key: value for key, value in task.items() if key not in REQUEST_FIELDS},
        "request_text": text,
    }}}
