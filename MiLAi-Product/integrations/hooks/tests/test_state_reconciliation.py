from __future__ import annotations

from copy import deepcopy

import pytest

from milai_hooks.state_reconciliation import (
    StateDeltaError,
    validate_and_merge_state_delta,
)


def _delta(*changes: dict[str, object], no_material_change: bool = False) -> dict[str, object]:
    return {
        "base_state_id": "state-one",
        "base_version": 3,
        "no_material_change": no_material_change,
        "changes": list(changes),
    }


def _change(
    field: str,
    *,
    op: str = "REPLACE",
    value: object = None,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "field": field,
        "op": op,
        "reason_event_ids": ["event-one"] if reasons is None else reasons,
    }
    if op == "REPLACE":
        result["value"] = value
    return result


def test_replace_clear_and_missing_keep_preserve_unowned_fields() -> None:
    previous = {
        "task": {"active_goal": "old"},
        "blockers": ["resolved"],
        "next_actions": ["keep this"],
        "host_extension": {"preserved": True},
    }
    original = deepcopy(previous)
    result = validate_and_merge_state_delta(
        previous,
        _delta(
            _change("task", value={"active_goal": "new"}),
            _change("blockers", op="CLEAR", reasons=["event-two"]),
        ),
        expected_state_id="state-one",
        expected_version=3,
        eligible_event_ids={"event-one", "event-two"},
    )

    assert result.payload == {
        "task": {"active_goal": "new"},
        "next_actions": ["keep this"],
        "host_extension": {"preserved": True},
    }
    assert result.base_state_id == "state-one"
    assert result.base_version == 3
    assert result.changed_fields == ("task", "blockers")
    assert result.referenced_event_ids == ("event-one", "event-two")
    assert previous == original


def test_no_material_change_returns_an_independent_unchanged_payload() -> None:
    previous = {"task": {"active_goal": "keep"}}
    result = validate_and_merge_state_delta(
        previous,
        _delta(no_material_change=True),
        expected_state_id="state-one",
        expected_version=3,
        eligible_event_ids={"event-one"},
    )

    assert result.payload == previous
    assert result.payload is not previous
    assert result.no_material_change is True
    assert result.changed_fields == ()
    assert result.referenced_event_ids == ()


@pytest.mark.parametrize(
    ("raw_delta", "code"),
    [
        (_delta(_change("authority", value="CANONICAL")), "FIELD_NOT_ALLOWED"),
        (
            _delta(
                _change("task", value={"active_goal": "one"}),
                _change("task", value={"active_goal": "two"}),
            ),
            "DUPLICATE_FIELD",
        ),
        (_delta(_change("task", op="KEEP")), "INVALID_OPERATION"),
        (_delta(_change("task", value={"goal": "x"}, reasons=[])), "INVALID_REASON_EVENT_IDS"),
        (
            _delta(_change("task", value={"goal": "x"}, reasons=["outside"])),
            "EVENT_REFERENCE_OUTSIDE_WINDOW",
        ),
        (_delta(_change("task", value=float("nan"))), "INVALID_REPLACEMENT_VALUE"),
        (_delta(no_material_change=False), "INVALID_DELTA"),
    ],
)
def test_invalid_delta_fails_with_actionable_code(
    raw_delta: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(StateDeltaError) as captured:
        validate_and_merge_state_delta(
            {},
            raw_delta,
            expected_state_id="state-one",
            expected_version=3,
            eligible_event_ids={"event-one"},
        )

    assert captured.value.code == code
    assert captured.value.problem
    assert captured.value.fix


@pytest.mark.parametrize(
    ("expected_state_id", "expected_version"),
    [("different-state", 3), ("state-one", 4)],
)
def test_delta_cannot_target_a_different_state_head(
    expected_state_id: str,
    expected_version: int,
) -> None:
    with pytest.raises(StateDeltaError) as captured:
        validate_and_merge_state_delta(
            {},
            _delta(_change("next_actions", value=["continue"])),
            expected_state_id=expected_state_id,
            expected_version=expected_version,
            eligible_event_ids={"event-one"},
        )

    assert captured.value.code == "BASE_MISMATCH"


def test_delta_envelope_is_complete_for_an_absent_base_state() -> None:
    incomplete = {
        "base_version": 0,
        "no_material_change": True,
        "changes": [],
    }
    with pytest.raises(StateDeltaError) as captured:
        validate_and_merge_state_delta(
            {},
            incomplete,
            expected_state_id=None,
            expected_version=0,
            eligible_event_ids=set(),
        )

    assert captured.value.code == "INVALID_DELTA"
    assert "base_state_id" in captured.value.problem


@pytest.mark.parametrize(
    ("state_id", "version"),
    [(None, 3), ("state-one", 0), ("state-one", True)],
)
def test_delta_rejects_invalid_working_state_base_shape(
    state_id: str | None,
    version: object,
) -> None:
    raw = _delta(_change("next_actions", value=["continue"]))
    raw["base_state_id"] = state_id
    raw["base_version"] = version
    with pytest.raises(StateDeltaError) as captured:
        validate_and_merge_state_delta(
            {},
            raw,
            expected_state_id=state_id,
            expected_version=version,  # type: ignore[arg-type]
            eligible_event_ids={"event-one"},
        )

    assert captured.value.code == "INVALID_DELTA"


@pytest.mark.parametrize(
    "change",
    [
        _change("blockers", op="CLEAR"),
        _change("task", value={"active_goal": "same"}),
    ],
)
def test_delta_rejects_operations_that_do_not_change_effective_payload(
    change: dict[str, object],
) -> None:
    with pytest.raises(StateDeltaError) as captured:
        validate_and_merge_state_delta(
            {"task": {"active_goal": "same"}},
            _delta(change),
            expected_state_id="state-one",
            expected_version=3,
            eligible_event_ids={"event-one"},
        )

    assert captured.value.code == "NO_EFFECTIVE_CHANGE"
    assert "no_material_change=true" in captured.value.fix
