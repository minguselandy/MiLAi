from __future__ import annotations

import json
from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Any, Literal

StateDeltaOperation = Literal["REPLACE", "CLEAR"]

STATE_DELTA_FIELDS = frozenset(
    {
        "task",
        "requirements",
        "established",
        "hypotheses",
        "decisions",
        "failed_approaches",
        "blockers",
        "open_questions",
        "next_actions",
        "completion_conditions",
    }
)


class StateDeltaError(ValueError):
    """A correctable Host-side StateDelta contract violation."""

    def __init__(self, code: str, problem: str, fix: str) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.fix = fix


@dataclass(frozen=True, slots=True)
class StateDeltaChange:
    field: str
    operation: StateDeltaOperation
    value: Any
    reason_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedStateDelta:
    base_state_id: str | None
    base_version: int
    no_material_change: bool
    changes: tuple[StateDeltaChange, ...]


@dataclass(frozen=True, slots=True)
class StateDeltaMergeResult:
    base_state_id: str | None
    base_version: int
    payload: dict[str, Any]
    changed_fields: tuple[str, ...]
    referenced_event_ids: tuple[str, ...]
    no_material_change: bool


def validate_state_delta(
    value: Mapping[str, Any],
    *,
    expected_state_id: str | None,
    expected_version: int,
    eligible_event_ids: Set[str],
) -> ValidatedStateDelta:
    """Validate mechanical Delta boundaries without claiming semantic grounding."""

    allowed_top_level = {"base_state_id", "base_version", "no_material_change", "changes"}
    unexpected = sorted(set(value) - allowed_top_level)
    if unexpected:
        raise _error(
            "INVALID_DELTA",
            "StateDelta contains unsupported top-level fields: " + ", ".join(unexpected),
            "Return only base_state_id, base_version, no_material_change, and changes.",
        )
    missing = sorted(allowed_top_level - set(value))
    if missing:
        raise _error(
            "INVALID_DELTA",
            "StateDelta is missing required fields: " + ", ".join(missing),
            "Return the complete StateDelta envelope even when there is no material change.",
        )
    state_id = value.get("base_state_id")
    version = value.get("base_version")
    _validate_base_shape(state_id, version, owner="StateDelta")
    _validate_base_shape(expected_state_id, expected_version, owner="Host expected base")
    if state_id != expected_state_id or version != expected_version:
        raise _error(
            "BASE_MISMATCH",
            "StateDelta does not target the supplied base State head.",
            "Regenerate the Delta from the current State identity and version.",
        )
    no_material_change = value.get("no_material_change")
    if not isinstance(no_material_change, bool):
        raise _error(
            "INVALID_DELTA",
            "no_material_change must be boolean.",
            "Use true only when no semantic field needs REPLACE or CLEAR.",
        )
    raw_changes = value.get("changes")
    if not isinstance(raw_changes, list):
        raise _error(
            "INVALID_DELTA",
            "changes must be an array.",
            "Return an empty array for no change, or one bounded entry per changed field.",
        )
    if no_material_change != (len(raw_changes) == 0):
        raise _error(
            "INVALID_DELTA",
            "no_material_change and changes contradict each other.",
            "Use true with an empty changes array, or false with at least one change.",
        )
    if len(raw_changes) > len(STATE_DELTA_FIELDS):
        raise _error(
            "INVALID_DELTA",
            "changes exceeds the allowed semantic field count.",
            "Return at most one change for each supported field.",
        )

    changes: list[StateDeltaChange] = []
    seen_fields: set[str] = set()
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise _error(
                "INVALID_DELTA",
                "Each StateDelta change must be an object.",
                "Use field, op, value when replacing, and reason_event_ids.",
            )
        changes.append(
            _validate_change(
                raw_change,
                seen_fields=seen_fields,
                eligible_event_ids=eligible_event_ids,
            )
        )
    return ValidatedStateDelta(
        base_state_id=state_id,
        base_version=version,
        no_material_change=no_material_change,
        changes=tuple(changes),
    )


def merge_state_delta(
    previous_payload: Mapping[str, Any],
    delta: ValidatedStateDelta,
) -> StateDeltaMergeResult:
    """Apply validated field replacement/clear operations without mutating the input."""

    previous = _clone_json_object(previous_payload, field="previous_payload")
    payload = _clone_json_object(previous, field="previous_payload")
    referenced: set[str] = set()
    changed_fields: list[str] = []
    for change in delta.changes:
        changed_fields.append(change.field)
        referenced.update(change.reason_event_ids)
        if change.operation == "CLEAR":
            payload.pop(change.field, None)
        else:
            payload[change.field] = _clone_json(change.value, field=change.field)
    if delta.changes and payload == previous:
        raise _error(
            "NO_EFFECTIVE_CHANGE",
            "StateDelta operations do not change the effective Working State payload.",
            "Return no_material_change=true with no changes, or emit a material replacement.",
        )
    return StateDeltaMergeResult(
        base_state_id=delta.base_state_id,
        base_version=delta.base_version,
        payload=payload,
        changed_fields=tuple(changed_fields),
        referenced_event_ids=tuple(sorted(referenced)),
        no_material_change=delta.no_material_change,
    )


def validate_and_merge_state_delta(
    previous_payload: Mapping[str, Any],
    raw_delta: Mapping[str, Any],
    *,
    expected_state_id: str | None,
    expected_version: int,
    eligible_event_ids: Set[str],
) -> StateDeltaMergeResult:
    delta = validate_state_delta(
        raw_delta,
        expected_state_id=expected_state_id,
        expected_version=expected_version,
        eligible_event_ids=eligible_event_ids,
    )
    return merge_state_delta(previous_payload, delta)


def _validate_change(
    value: dict[str, Any],
    *,
    seen_fields: set[str],
    eligible_event_ids: Set[str],
) -> StateDeltaChange:
    allowed = {"field", "op", "value", "reason_event_ids"}
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise _error(
            "INVALID_DELTA",
            "StateDelta change contains unsupported fields: " + ", ".join(unexpected),
            "Return only field, op, optional value, and reason_event_ids.",
        )
    field = value.get("field")
    if not isinstance(field, str) or field not in STATE_DELTA_FIELDS:
        raise _error(
            "FIELD_NOT_ALLOWED",
            "StateDelta attempted to modify an unsupported or authority-owned field.",
            "Choose one of the documented Host semantic fields; never modify binding or version.",
        )
    if field in seen_fields:
        raise _error(
            "DUPLICATE_FIELD",
            f"StateDelta modifies {field} more than once.",
            "Return one full-field REPLACE or CLEAR operation for that field.",
        )
    seen_fields.add(field)
    operation = value.get("op")
    if operation not in {"REPLACE", "CLEAR"}:
        raise _error(
            "INVALID_OPERATION",
            "StateDelta operation must be REPLACE or CLEAR.",
            "Missing fields already mean KEEP; do not emit a KEEP operation.",
        )
    raw_reasons = value.get("reason_event_ids")
    if (
        not isinstance(raw_reasons, list)
        or not raw_reasons
        or any(not isinstance(item, str) or not item for item in raw_reasons)
        or len(set(raw_reasons)) != len(raw_reasons)
    ):
        raise _error(
            "INVALID_REASON_EVENT_IDS",
            "Each changed field requires unique, non-empty reason Event identities.",
            "Cite one or more exact Event IDs from the frozen reconciliation window.",
        )
    outside = sorted(set(raw_reasons) - set(eligible_event_ids))
    if outside:
        raise _error(
            "EVENT_REFERENCE_OUTSIDE_WINDOW",
            "StateDelta cites Event identities outside the frozen window: " + ", ".join(outside),
            "Use only exact Event IDs supplied in this reconciliation request.",
        )

    replacement: Any = None
    if operation == "REPLACE":
        if "value" not in value or value["value"] is None:
            raise _error(
                "INVALID_REPLACEMENT_VALUE",
                "REPLACE requires a non-null full-field value.",
                "Return the complete replacement value, preserving every still-valid old item.",
            )
        replacement = _clone_json(value["value"], field=field)
    elif value.get("value") is not None:
        raise _error(
            "INVALID_REPLACEMENT_VALUE",
            "CLEAR cannot carry a replacement value.",
            "Omit value or set it to null when clearing a field.",
        )
    return StateDeltaChange(
        field=field,
        operation=operation,
        value=replacement,
        reason_event_ids=tuple(raw_reasons),
    )


def _validate_base_shape(state_id: object, version: object, *, owner: str) -> None:
    if state_id is not None and (not isinstance(state_id, str) or not state_id):
        raise _error(
            "INVALID_DELTA",
            f"{owner} state identity must be a non-empty string or null.",
            "Use null only with version 0; otherwise use the exact existing State identity.",
        )
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise _error(
            "INVALID_DELTA",
            f"{owner} version must be a non-negative integer.",
            "Use version 0 only when no base State identity exists.",
        )
    if (state_id is None) != (version == 0):
        raise _error(
            "INVALID_DELTA",
            f"{owner} violates the Working State create/update base invariant.",
            "Use base_state_id=null with version=0, or an exact State identity with version>0.",
        )


def _clone_json_object(value: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    cloned = _clone_json(dict(value), field=field)
    if not isinstance(cloned, dict):
        raise AssertionError("JSON object clone changed type")
    return cloned


def _clone_json(value: Any, *, field: str) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "INVALID_REPLACEMENT_VALUE",
            f"{field} is not valid JSON data.",
            "Return only JSON-compatible objects, arrays, strings, numbers, booleans, or null.",
        ) from exc


def _error(code: str, problem: str, fix: str) -> StateDeltaError:
    return StateDeltaError(code, problem, fix)
