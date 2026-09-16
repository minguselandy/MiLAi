from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from milai_hooks.agent_event import validate_host_event_binding
from milai_hooks.state_reconciliation import validate_and_merge_state_delta

_WORKING_STATE_WIRE_SCHEMA = "host-cognitive-state-v1"
_WORKING_STATE_SCHEMA = "codex-cognitive-state-v1"
_WORKING_STATE_AUTHORITY = "HOST_WORKING"
_EVENT_WIRE_SCHEMA = "host-execution-event-v1"
_MAX_EVENT_WINDOW = 200


class WorkingStateReconciliationClient(Protocol):
    def get_working_state(self, binding: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_host_execution_event_window(
        self,
        binding: Mapping[str, Any],
    ) -> dict[str, Any]: ...

    def update_working_state(
        self,
        payload: Mapping[str, Any],
        *,
        operation_id: str,
    ) -> dict[str, Any]: ...


class ReconciliationOrchestrationError(ValueError):
    """A correctable Host-side orchestration contract violation."""

    def __init__(self, code: str, problem: str, fix: str) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.fix = fix


def reconcile_working_state_explicit(
    client: WorkingStateReconciliationClient,
    *,
    principal_binding_digest: str,
    project_id: str,
    task_ref: str,
    raw_delta: Mapping[str, Any],
    operation_id: str,
    expected_event_high_watermark: int,
    after_position: int = 0,
    event_limit: int = 100,
) -> dict[str, Any]:
    """Apply one Host-triggered, Codex-authored Delta through exact Working State CAS.

    This function does not decide when reconciliation is needed and does not invoke a model.
    The Host supplies the Delta and stable operation identity explicitly.
    """

    binding = validate_host_event_binding(
        principal_binding_digest=principal_binding_digest,
        project_id=project_id,
        task_ref=task_ref,
    )
    _validate_cursor(after_position, expected_event_high_watermark, event_limit)
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
        raise _error(
            "INVALID_OPERATION_ID",
            "Reconciliation operation_id must contain between 1 and 128 characters.",
            "Supply one stable Host operation identity and reuse it only for an identical retry.",
        )
    if not isinstance(raw_delta, Mapping):
        raise _error(
            "INVALID_DELTA",
            "Reconciliation delta must be a JSON object.",
            "Supply the complete StateDelta envelope produced from the current State and "
            "Event window.",
        )

    state_binding = {
        "principal_binding_digest": binding["principal_binding_digest"],
        "project_id": binding["project_id"],
        "scope_type": "TASK",
        "scope_ref": binding["task_ref"],
    }
    state = _working_state_head(client.get_working_state(state_binding))
    event_window = _event_window(
        client.get_host_execution_event_window(
            {
                **binding,
                "after_position": after_position,
                "limit": event_limit,
            }
        ),
        after_position=after_position,
        event_limit=event_limit,
    )
    if event_window["visible_high_watermark"] != expected_event_high_watermark:
        raise _error(
            "EVENT_WINDOW_CHANGED",
            "The Event window advanced after the StateDelta input was prepared.",
            "Read the new frozen Event window and regenerate the Delta before retrying.",
        )
    if event_window["has_more"]:
        raise _error(
            "EVENT_WINDOW_INCOMPLETE",
            "The bounded Event window has more eligible rows and cannot be reconciled atomically.",
            "Retry with a larger event_limit up to 200, or reconcile an explicitly bounded "
            "batch in a later workflow.",
        )

    runtime_operation_id = reconciliation_runtime_operation_id(
        principal_binding_digest=binding["principal_binding_digest"],
        project_id=binding["project_id"],
        task_ref=binding["task_ref"],
        public_operation_id=operation_id,
    )
    eligible_event_ids = {
        event["event_id"] for event in event_window["events"] if not event["warnings"]
    }
    ineligible_event_ids = sorted(
        event["event_id"] for event in event_window["events"] if event["warnings"]
    )
    cited_ineligible = sorted(set(ineligible_event_ids) & _raw_reason_event_ids(raw_delta))
    if cited_ineligible:
        raise _error(
            "EVENT_REFERENCE_NOT_ELIGIBLE",
            "StateDelta cites Event identities whose Evidence is stale or unreadable: "
            + ", ".join(cited_ineligible),
            "Reload the Event Evidence, remove invalid references, and regenerate the Delta.",
        )
    merged = validate_and_merge_state_delta(
        state["payload"],
        raw_delta,
        expected_state_id=state["state_id"],
        expected_version=state["version"],
        eligible_event_ids=eligible_event_ids,
    )
    window_receipt = {
        "after_position": event_window["after_position"],
        "through_position": event_window["next_position"],
        "visible_high_watermark": event_window["visible_high_watermark"],
        "event_count": len(event_window["events"]),
        "eligible_event_count": len(eligible_event_ids),
        "ineligible_event_ids": ineligible_event_ids,
        "has_more": False,
    }
    delta_receipt = {
        "base_state_id": merged.base_state_id,
        "base_version": merged.base_version,
        "changed_fields": list(merged.changed_fields),
        "referenced_event_ids": list(merged.referenced_event_ids),
    }
    if merged.no_material_change:
        return {
            "status": "NO_MATERIAL_CHANGE",
            "state": state,
            "event_window": window_receipt,
            "delta": delta_receipt,
            "basis_candidate": {
                "event_position": event_window["next_position"],
                "persisted": False,
            },
            "working_state_mutation": False,
            "canonical_mutation": False,
            "operation_id": operation_id,
        }

    updated = _updated_working_state(
        client.update_working_state(
            {
                **state_binding,
                "state_id": merged.base_state_id,
                "expected_version": merged.base_version,
                "payload": merged.payload,
            },
            operation_id=runtime_operation_id,
        ),
        base_state_id=merged.base_state_id,
        base_version=merged.base_version,
        expected_payload=merged.payload,
    )
    return {
        "status": "UPDATED",
        "state": updated,
        "event_window": window_receipt,
        "delta": delta_receipt,
        "basis_candidate": {
            "event_position": event_window["next_position"],
            "persisted": False,
        },
        "working_state_mutation": True,
        "canonical_mutation": False,
        "operation_id": operation_id,
    }


def reconciliation_runtime_operation_id(
    *,
    principal_binding_digest: str,
    project_id: str,
    task_ref: str,
    public_operation_id: str,
) -> str:
    """Namespace one Host retry identity before it reaches Runtime idempotency storage."""

    material = {
        "contract": "explicit-working-state-reconciliation-v1",
        "principal_binding_digest": principal_binding_digest,
        "project_id": project_id,
        "task_ref": task_ref,
        "public_operation_id": public_operation_id,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "host-state-reconcile-v1:" + hashlib.sha256(encoded).hexdigest()


def _working_state_head(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_runtime("Working State response is not an object.")
    if value.get("schema_version") != _WORKING_STATE_WIRE_SCHEMA:
        raise _invalid_runtime("Working State schema_version is unsupported.")
    if value.get("schema_name") != _WORKING_STATE_SCHEMA:
        raise _invalid_runtime("Working State schema_name is unsupported.")
    if value.get("authority") != _WORKING_STATE_AUTHORITY or value.get("scope") != "TASK":
        raise _invalid_runtime("Working State authority or scope is not the requested TASK State.")
    status = value.get("status")
    if status not in {"ABSENT", "ACTIVE"}:
        raise _error(
            "WORKING_STATE_NOT_USABLE",
            f"Working State status {status!r} cannot be reconciled.",
            "Continue with explicitly stale context if appropriate, or create/reload a usable "
            "TASK State before retrying.",
        )
    state_id = value.get("state_id")
    version = value.get("version")
    payload = value.get("payload")
    if status == "ABSENT":
        if state_id is not None or version != 0 or payload != {}:
            raise _invalid_runtime("ABSENT Working State violates the empty-head invariant.")
    elif (
        not isinstance(state_id, str)
        or not state_id
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(payload, dict)
    ):
        raise _invalid_runtime("ACTIVE Working State has an invalid identity, version, or payload.")
    return dict(value)


def _event_window(
    value: object,
    *,
    after_position: int,
    event_limit: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_runtime("Host Event window response is not an object.")
    if value.get("schema_version") != _EVENT_WIRE_SCHEMA or value.get("status") != "WINDOW":
        raise _invalid_runtime("Host Event window schema or status is unsupported.")
    if value.get("after_position") != after_position:
        raise _invalid_runtime("Host Event window does not match the requested cursor.")
    next_position = _position(value.get("next_position"), field="next_position")
    high_watermark = _position(
        value.get("visible_high_watermark"),
        field="visible_high_watermark",
    )
    has_more = value.get("has_more")
    events = value.get("events")
    if not isinstance(has_more, bool) or not isinstance(events, list) or len(events) > event_limit:
        raise _invalid_runtime("Host Event window paging fields are invalid.")
    if next_position < after_position or next_position > high_watermark:
        raise _invalid_runtime(
            "Host Event window violates after_position <= next_position <= high watermark."
        )

    normalized: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    prior_position = after_position
    for event in events:
        if not isinstance(event, dict):
            raise _invalid_runtime("Host Event window contains a non-object Event.")
        event_id = event.get("event_id")
        position = _position(event.get("position"), field="event.position")
        warnings = event.get("warnings")
        if not isinstance(event_id, str) or not event_id or event_id in event_ids:
            raise _invalid_runtime(
                "Host Event window contains an invalid or duplicate Event identity."
            )
        if position <= prior_position or position > high_watermark:
            raise _invalid_runtime(
                "Host Event positions are not strictly ordered inside the frozen window."
            )
        if not isinstance(warnings, list) or any(not isinstance(item, dict) for item in warnings):
            raise _invalid_runtime("Host Event warnings are malformed.")
        event_ids.add(event_id)
        prior_position = position
        normalized.append({**event, "warnings": list(warnings)})
    expected_next = prior_position if normalized else after_position
    if next_position != expected_next:
        raise _invalid_runtime("Host Event next_position does not match the returned rows.")
    if has_more and (not normalized or next_position >= high_watermark):
        raise _invalid_runtime("Host Event has_more contradicts the returned window.")
    if not has_more and high_watermark > after_position and next_position != high_watermark:
        raise _invalid_runtime(
            "Complete Host Event window does not reach its visible high watermark."
        )
    return {
        **value,
        "events": normalized,
        "next_position": next_position,
        "visible_high_watermark": high_watermark,
        "has_more": has_more,
    }


def _raw_reason_event_ids(raw_delta: Mapping[str, Any]) -> set[str]:
    raw_changes = raw_delta.get("changes")
    if not isinstance(raw_changes, list):
        return set()
    found: set[str] = set()
    for change in raw_changes:
        if not isinstance(change, dict):
            continue
        reasons = change.get("reason_event_ids")
        if isinstance(reasons, list):
            found.update(item for item in reasons if isinstance(item, str))
    return found


def _updated_working_state(
    value: object,
    *,
    base_state_id: str | None,
    base_version: int,
    expected_payload: Mapping[str, Any],
) -> dict[str, Any]:
    state = _working_state_head(value)
    if state["status"] != "ACTIVE":
        raise _invalid_runtime("Working State update did not return an ACTIVE version.")
    if state["version"] != base_version + 1:
        raise _invalid_runtime("Working State update returned an unexpected version.")
    if base_state_id is not None and state["state_id"] != base_state_id:
        raise _invalid_runtime("Working State update changed the State chain identity.")
    if state["payload"] != dict(expected_payload):
        raise _invalid_runtime("Working State update did not return the merged payload.")
    return state


def _validate_cursor(
    after_position: object,
    expected_event_high_watermark: object,
    event_limit: object,
) -> None:
    if (
        isinstance(after_position, bool)
        or not isinstance(after_position, int)
        or after_position < 0
    ):
        raise _error(
            "INVALID_EVENT_CURSOR",
            "after_position must be a non-negative integer.",
            "Use 0 for the first reconciliation or the last Host-committed Event basis cursor.",
        )
    if (
        isinstance(expected_event_high_watermark, bool)
        or not isinstance(expected_event_high_watermark, int)
        or expected_event_high_watermark < 0
    ):
        raise _error(
            "INVALID_EVENT_WATERMARK",
            "expected_event_high_watermark must be a non-negative integer.",
            "Use the exact visible_high_watermark from the Event window used to produce the Delta.",
        )
    if (
        isinstance(event_limit, bool)
        or not isinstance(event_limit, int)
        or not 1 <= event_limit <= _MAX_EVENT_WINDOW
    ):
        raise _error(
            "INVALID_EVENT_LIMIT",
            "event_limit must be an integer between 1 and 200.",
            "Use the default 100 or increase it only enough to include the bounded Event window.",
        )


def _position(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_runtime(f"Host Event {field} is invalid.")
    return value


def _invalid_runtime(problem: str) -> ReconciliationOrchestrationError:
    return _error(
        "INVALID_RUNTIME_RESPONSE",
        problem,
        "Retry with the same inputs; if it repeats, verify Runtime compatibility before "
        "reconciling State.",
    )


def _error(code: str, problem: str, fix: str) -> ReconciliationOrchestrationError:
    return ReconciliationOrchestrationError(code, problem, fix)
