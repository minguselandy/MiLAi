"""Three independent, default-off read and receipt communication contracts.

Snapshots use public Store get/put under the existing cooperating service lock;
neither this contract nor that lock supplies backend CAS or HTTP serialization.
"""

from __future__ import annotations

import json
from typing import Any, NoReturn, cast

PROFILES = {
    "memory_read_protocol": "selected_snapshot_v1",
    "tool_read_feedback": "typed_read_v1",
    "tool_save_communication": "completed_receipt_v1",
}
SAVE_GUIDANCE = (
    "Report the actual effect acknowledged by each completed tool receipt. "
    "Raw event or observation capture does not confirm semantic memory storage. "
    "Say an item was saved or updated only after its completed mutation receipt confirms it. "
    "No-change or replay acknowledges only the identified existing result. "
    "Maintenance after the Host final reply may decline, remain pending or be partial; "
    "it cannot retroactively confirm a save claim in that reply. "
    "No receipt guarantees whole-turn or future coverage. A tool call is not mandatory."
)
READ_CODES = frozenset(
    {
        "V13_SELECTED_PAGE_NOT_READY",
        "V13_SELECTED_CURSOR_CHANGED_OR_INVALID",
        "V13_HISTORY_READ_REQUIRES_EXACT_ID",
        "V13_HISTORY_ARGUMENTS_REQUIRE_HISTORY_VIEW",
        "V13_HISTORY_CURSOR_CHANGED_OR_INVALID",
        "V13_SOURCE_INDEX_CURSOR_CHANGED_OR_INVALID",
        "V13_SELECTED_SNAPSHOT_MISSING",
        "V13_SELECTED_SNAPSHOT_REVOKED",
    }
)


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def profile(name: str, value: Any = "legacy") -> str:
    if name not in PROFILES or type(value) is not str or value not in {"legacy", PROFILES[name]}:
        raise ValueError("V13_READ_PROTOCOL_PROFILE_INVALID:" + name)
    return value


def profiles(settings: dict[str, Any]) -> dict[str, str]:
    return {name: profile(name, settings.get(name, "legacy")) for name in PROFILES}


def nonlegacy(settings: dict[str, Any]) -> dict[str, str]:
    return {name: value for name, value in profiles(settings).items() if value != "legacy"}


def validate_settings(settings: dict[str, Any]) -> dict[str, str]:
    values = profiles(settings)
    if values["memory_read_protocol"] != "legacy" and (
        settings.get("memory_reader_policy") != "bounded_evidence_v1"
        or settings.get("memory_mutation_contract", "legacy") != "event_bound_v1"
        or settings.get("memory_candidate_contract") != "read_handle_v1"
    ):
        raise ValueError("V13_SELECTED_SNAPSHOT_REQUIRES_BOUND_READ_HANDLE")
    return values


def freeze_fields(settings: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    active = nonlegacy(settings)
    if not active:
        return {}
    return {
        **active,
        "read_protocol_presentation": {
            "profiles": profiles(settings),
            "catalog_version": settings.get("config_version", "public_memory_v2"),
            "save_guidance_version": "completed_receipt_v1"
            if active.get("tool_save_communication")
            else None,
            "feedback_max_utf8_bytes": 1024,
            "snapshot_store": "issued snapshot_id; public Store get/put under service lock",
        },
    }


def check_frozen(frozen: dict[str, Any]) -> None:
    """Parse declared profiles; the run owns its ordinary immutable config version."""
    validate_settings(frozen["config"])


def save_guidance(value: Any = "legacy") -> str:
    return "\n" + SAVE_GUIDANCE if profile("tool_save_communication", value) != "legacy" else ""


def present_catalog(catalog: list[dict[str, Any]], value: Any = "legacy") -> list[dict[str, Any]]:
    if profile("tool_save_communication", value) == "legacy":
        return catalog
    # All arms receive the same capability-neutral explanation, without M-only fields.
    result = json.loads(canonical(catalog))
    for item in result:
        function = item.get("function", item)
        function["description"] = function.get("description", "") + " " + SAVE_GUIDANCE
    return cast(list[dict[str, Any]], result)


class ReadProtocolRejected(ValueError):
    """An explicitly typed, finite rejection at an existing read protocol guard."""

    def __init__(self, code: str, origin: str) -> None:
        if code not in READ_CODES or origin not in {
            "memory_service",
            "memory_tools",
            "grounded_reader",
        }:
            raise ValueError("V13_READ_REJECTION_CONTRACT_INVALID")
        self.code, self.origin = code, origin
        super().__init__(code)

    def receipt(self) -> dict[str, Any]:
        result = {
            "ok": False,
            "status": "read_rejected",
            "code": self.code,
            "origin": self.origin,
            "semantic_effect": "none",
        }
        if len(canonical(result).encode()) > 1024:
            raise ValueError("V13_READ_FEEDBACK_SIZE_INVALID")
        return result


def reject(code: str, origin: str, value: Any = "legacy") -> NoReturn:
    if profile("tool_read_feedback", value) == "legacy":
        raise ValueError(code)
    raise ReadProtocolRejected(code, origin)


def snapshot_key(snapshot_id: str) -> str:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("V13_SELECTED_SNAPSHOT_KEY_INVALID")
    return "selected_snapshot:" + snapshot_id
