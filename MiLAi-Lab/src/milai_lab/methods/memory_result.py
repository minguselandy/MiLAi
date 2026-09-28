"""Pure, mechanical completion evidence for the opt-in v3 ordinary-memory recipe."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

RESPONSIBILITY_PROMPT = (
    "You are responsible for both the user's current task and any explicitly requested ongoing "
    "memory work. When the user asks you to keep information for later, use the memory tools to "
    "retain useful, accurate content unless an actual existing record already satisfies the "
    "request. Acknowledging a request or retaining conversation history alone is not a saved "
    "memory record.\n"
    "Distinguish ongoing instructions from requests limited to this reply, quoted speech, and "
    "suggestions the user has not adopted. Do not turn these into standing preferences. A "
    "read-only question or a turn with no new reusable information need not change memory.\n"
    "When an existing matter changes, use its actual record identity to update the affected "
    "content, preserve other still-supported details and unrelated matters, and avoid unnecessary "
    "duplicates. Handle authorized removal of a saved item within its stated scope; saving a "
    "reminder note does not schedule a notification.\n"
    "Use actual business results to distinguish an attempted action, a completed action, and a "
    "partial failure. If a result changes a current assertion in a saved record, maintain that "
    "assertion or report the unfinished memory work. Do not repeat a completed business action "
    "to repair memory.\n"
    "Before finishing, check your memory work against the actual records and tool results "
    "available to you. Report only what actually happened. If a correct record already exists, "
    "you may leave it unchanged. If work remains unresolved, say what remains instead of claiming "
    "that it was saved. The tools do not decide whether the content meets the user's intent; "
    "you remain responsible for that judgment.\n"
)

RESULT_PROTOCOL = (
    'For a final reply use {"answer":"...","memory_result":'
    '{"status":"committed|no_change|unresolved","receipt_refs":["..."],"note":"..."}}. '
    "The note is optional. Reference the exact receipt_ref labels in actual current-turn "
    "tool results. Committed requires a successful current-turn memory creation, update, "
    "or deletion; a read or an unchanged update is not a new commit. No_change reports "
    "no persistent change, without certifying that the user's intent is satisfied. "
    "Unresolved reports unfinished memory work. This field does not certify content "
    "correctness or completion of all requirements."
)
CORRECTION_PROTOCOL = (
    "One memory-only correction entry follows your prior final reply. Keep the actual "
    "user observations, records and tool results; use only the available memory/read "
    "tools. Do not repeat business actions. Produce another final reply with the actual "
    "memory result. There is no further automatic correction entry."
)
MEMORY_TOOLS = frozenset({"manage_memory", "search_memory", "read_memory"})
CORRECTION_TOOLS = MEMORY_TOOLS | {"read_history"}
MUTATIONS = frozenset({"created", "updated", "deleted"})


def result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["committed", "no_change", "unresolved"]},
            "receipt_refs": {"type": "array", "items": {"type": "string"}},
            "note": {"type": "string"},
        },
        "required": ["status", "receipt_refs"],
        "additionalProperties": False,
    }


def valid_result(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) <= {"status", "receipt_refs", "note"}
        and type(value.get("status")) is str
        and value["status"] in {"committed", "no_change", "unresolved"}
        and isinstance(value.get("receipt_refs"), list)
        and all(isinstance(ref, str) and bool(ref) for ref in value["receipt_refs"])
        and ("note" not in value or isinstance(value["note"], str))
    )


def turn_receipts(
    messages: Sequence[Mapping[str, Any]], scope: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Only paired actual checkpoint results with the current generated scope qualify."""
    start = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("type") == "human"),
        len(messages),
    )
    calls: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for message in messages[start:]:
        if message.get("type") == "ai":
            metadata = message.get("response_metadata", {})
            if not isinstance(metadata, dict) or metadata.get("memory_turn") != dict(scope):
                continue
            for call in message.get("tool_calls", []):
                if isinstance(call, dict) and isinstance(call.get("id"), str):
                    calls[call["id"]] = call
        elif message.get("type") == "tool":
            ref = message.get("tool_call_id")
            call = calls.pop(ref, None) if isinstance(ref, str) else None
            if call is None or message.get("name") != call.get("name"):
                continue
            content = message.get("content")
            parsed: Any = None
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except ValueError:
                    pass
            rows.append(
                {
                    **scope,
                    "ref": ref,
                    "name": call["name"],
                    "arguments": call.get("args", {}),
                    "transport_status": message.get("status", "success"),
                    "content": content,
                    "parsed": parsed,
                }
            )
    return rows


def verify_result(
    value: Any, receipts: Sequence[Mapping[str, Any]], scope: Mapping[str, str]
) -> dict[str, Any]:
    """Support reported operations, never semantic saved or all-requirements completion."""
    legal = {
        row["ref"]: row
        for row in receipts
        if all(row.get(key) == expected for key, expected in scope.items())
    }
    mutations: list[str] = []
    zero_write: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []
    for ref, row in legal.items():
        if row.get("name") != "manage_memory":
            continue
        parsed = row.get("parsed")
        if row.get("transport_status") == "error":
            failed.append(ref)
        elif isinstance(parsed, dict) and parsed.get("ok") is True:
            if parsed.get("status") in MUTATIONS:
                mutations.append(ref)
            elif parsed.get("status") == "no_change":
                zero_write.append(ref)
            else:
                unknown.append(ref)
        else:
            unknown.append(ref)
    reasons: list[str] = []
    if not valid_result(value):
        reasons.append("MEMORY_RESULT_SCHEMA_INVALID")
        refs: list[str] = []
        status: str | None = None
    else:
        refs, status = value["receipt_refs"], value["status"]
        for ref in refs:
            if ref not in legal:
                reasons.append("MEMORY_RESULT_RECEIPT_NOT_CURRENT")
            elif legal[ref].get("name") not in MEMORY_TOOLS:
                reasons.append("MEMORY_RESULT_RECEIPT_NOT_MEMORY")
            elif status != "unresolved" and legal[ref].get("transport_status") != "success":
                reasons.append("MEMORY_RESULT_FAILED_RECEIPT")
        if status == "committed" and not any(ref in mutations for ref in refs):
            reasons.append("MEMORY_RESULT_NO_REFERENCED_COMMIT")
        if status == "no_change" and mutations:
            reasons.append("MEMORY_RESULT_NO_CHANGE_CONTRADICTS_WRITE")
    return {
        "declaration_supported": not reasons,
        "reasons": sorted(set(reasons)),
        "reported_status": status,
        "successful_change_refs": mutations,
        "zero_write_refs": zero_write,
        "failed_operation_refs": failed,
        "unknown_operation_refs": unknown,
        "unreferenced_failed_operation_refs": [ref for ref in failed if ref not in refs],
        "partial_operations_observed": bool(mutations and (failed or unknown)),
        "needs_correction": bool(reasons) or status == "unresolved",
        "semantic_completion": None,
    }


def correction_marker(
    messages: Sequence[Mapping[str, Any]], message_key: str
) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("type") == "human":
            break
        metadata = message.get("response_metadata", {})
        if isinstance(metadata, dict):
            marker = metadata.get("memory_correction")
            if isinstance(marker, dict) and marker.get("message_key") == message_key:
                return marker
    return None
