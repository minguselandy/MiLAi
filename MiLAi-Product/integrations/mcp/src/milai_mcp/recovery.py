"""Versioned, safe recovery diagnostics for the ordinary-memory catalog."""

from typing import Any

from milai_client import MilaiClientError, UnavailableError

from milai_mcp.input_contracts import safe_validation_fields

ERROR_CONTRACT = "ordinary-memory-errors-v1"
_PUBLIC_CODES = frozenset({
    "INVALID_REQUEST", "INVALID_ARGUMENT", "INVALID_TOOL_ARGUMENTS", "STALE_WORKING_STATE",
    "STALE_NOTE", "OPERATION_CONFLICT", "EVIDENCE_REFERENCE_INVALID", "NOTE_NOT_FOUND",
    "NOTE_SCOPE_DENIED", "NOTE_SOURCE_UNAVAILABLE", "HOST_WORKING_STATE_EXPIRED",
    "HOST_WORKING_STATE_NOT_FOUND", "HOST_WORKING_STATE_SCOPE_DENIED",
    "INVALID_HOST_WORKING_STATE", "TENANT_MISMATCH", "FORBIDDEN", "UNAUTHORIZED",
    "PERMISSION_DENIED", "NOT_FOUND", "INVALID_NOTE", "NOTE_DELETED", "NOTE_OPERATION_NOT_FOUND",
})


def recovery_error(
    exc: MilaiClientError, *, kind: str, write: bool, scope: str | None = None,
    expected_version: int | None = None, state_id: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Project only fixed codes, validation fields and an exact-object CAS observation."""
    unknown = isinstance(exc, UnavailableError) and write
    code = (f"{kind}_OUTCOME_UNKNOWN" if write else f"{kind}_UNAVAILABLE") if isinstance(
        exc, UnavailableError
    ) else exc.code if exc.code in _PUBLIC_CODES else "REQUEST_REJECTED"
    result: dict[str, Any] = {
        "error_contract": ERROR_CONTRACT, "code": code, "retryable": False,
        "message": "Request rejected; inspect the code and recovery action.",
        "recovery_action": "INSPECT_REQUEST", "fields": [],
    }
    if scope is not None:
        result["scope"] = scope
    if code in {"INVALID_REQUEST", "INVALID_ARGUMENT", "INVALID_TOOL_ARGUMENTS",
                "INVALID_HOST_WORKING_STATE", "INVALID_NOTE"}:
        fields = exc.details.get("fields", [])
        result.update({
            "recovery_action": "CORRECT_INPUT",
            "fields": safe_validation_fields([
                field for field in fields if isinstance(field, dict)
            ], working_state=kind == "WORKING_STATE") if isinstance(fields, list) else [],
        })
    elif code in {"STALE_WORKING_STATE", "STALE_NOTE"}:
        result.update({
            "recovery_action": "READ_AND_REBASE",
            "message": "Read the same scope and rebase on the current version; do not merely "
            "increase expected_version or overwrite concurrent changes.",
            "next_tool": "milai_working_state_get" if kind == "WORKING_STATE" else "milai_note_get",
            "current_version_requires_read": True,
        })
        if scope is not None:
            result["next_arguments"] = {"scope": scope}
        if expected_version is not None:
            result["expected_version"] = expected_version
        current = exc.details.get("current_version")
        # The Runtime supplies this only after binding checks. Require correlation as well;
        # never disclose a version returned for a different object or on an auth error.
        if (code == "STALE_WORKING_STATE" and state_id is not None
                and exc.details.get("state_id") == state_id
                and type(current) is int and current >= 1):
            result["current_version"] = current
            result["current_version_requires_read"] = False
    elif code == "OPERATION_CONFLICT":
        result.update({
            "recovery_action": "RECONCILE_ORIGINAL_OPERATION",
            "message": "This operation ID belongs to a different request. Check the original "
            "request; a changed payload requires a new operation_id after reconciliation. "
            "Do not automatically replace the ID and retry.",
        })
    elif unknown:
        result.update({
            "recovery_action": "RECONCILE_ORIGINAL_OPERATION",
            "operation_id": operation_id,
            "message": "The commit is unconfirmed. A current read or absent receipt cannot "
            "prove failure of an in-flight write. Reconcile the original request or use "
            "controlled replay with the identical operation_id and payload; never blind retry.",
        })
        if kind == "NOTE":
            result["next_tool"] = "milai_note_operation_get"
    elif isinstance(exc, UnavailableError):
        result.update({
            "recovery_action": "RESTORE_AVAILABILITY",
            "message": "Memory unavailable; this is not ABSENT, MISS or empty history.",
        })
    return result
