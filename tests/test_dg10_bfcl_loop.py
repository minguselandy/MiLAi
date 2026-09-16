from __future__ import annotations

import pytest

from scripts import dg10_bfcl_loop as loop


def _controller(**updates: object) -> loop.ToolLoopController:
    values = {
        "required_outcomes": frozenset({"ticket_created"}),
        "allowed_result_fields": frozenset({"status", "ticket_id", "items"}),
    }
    values.update(updates)
    return loop.ToolLoopController(**values)


def test_required_optional_no_call_triage() -> None:
    controller = _controller()
    assert controller.triage(["create_ticket"]) == "REQUIRED"
    controller.resolved_outcomes.add("ticket_created")
    assert controller.triage(["lookup_ticket"]) == "OPTIONAL"
    assert controller.triage([]) == "NO_CALL"


def test_missing_function_and_parameter_recovery_is_single_use() -> None:
    controller = _controller()
    assert controller.recover_missing_function("create_ticket")["action"] == (
        "REQUEST_FUNCTION_EXPOSURE"
    )
    with pytest.raises(loop.ToolLoopError, match="MISSING_FUNCTION_UNRECOVERABLE"):
        controller.recover_missing_function("create_ticket")
    controller = _controller()
    assert controller.recover_missing_parameter("create_ticket", "title")["action"] == (
        "REQUEST_PARAMETER"
    )
    with pytest.raises(loop.ToolLoopError, match="MISSING_PARAMETER_UNRECOVERABLE"):
        controller.recover_missing_parameter("create_ticket", "title")


def test_identical_call_without_progress_fails_before_twenty_steps() -> None:
    controller = _controller()
    call = [{"name": "lookup", "arguments": {"id": 1}}]
    result = [{"status": "same"}]
    controller.process_step(calls=call, tool_results=result, state_patch={})
    controller.process_step(calls=call, tool_results=result, state_patch={})
    with pytest.raises(loop.ToolLoopError, match="NO_PROGRESS_BOUNDED_FAIL"):
        controller.process_step(calls=call, tool_results=result, state_patch={})
    assert controller.step_count == 3


def test_two_state_cycle_fails_bounded() -> None:
    controller = _controller(no_progress_limit=10)
    calls = (
        [{"name": "next", "arguments": {"state": "a"}}],
        [{"name": "next", "arguments": {"state": "b"}}],
    )
    controller.process_step(
        calls=calls[0],
        tool_results=[{"status": "a"}],
        state_patch={"position": "a"},
    )
    controller.process_step(
        calls=calls[1],
        tool_results=[{"status": "b"}],
        state_patch={"position": "b"},
    )
    controller.process_step(
        calls=calls[0],
        tool_results=[{"status": "a"}],
        state_patch={"position": "a"},
    )
    with pytest.raises(loop.ToolLoopError, match="STATE_CYCLE_BOUNDED_FAIL"):
        controller.process_step(
            calls=calls[1],
            tool_results=[{"status": "b"}],
            state_patch={"position": "b"},
        )


def test_three_state_cycle_fails_bounded() -> None:
    controller = _controller(no_progress_limit=10)
    for index in range(5):
        state = index % 3
        controller.process_step(
            calls=[{"name": "next", "arguments": {"state": state}}],
            tool_results=[{"status": state}],
            state_patch={"position": state},
        )
    with pytest.raises(loop.ToolLoopError, match="STATE_CYCLE_BOUNDED_FAIL"):
        controller.process_step(
            calls=[{"name": "next", "arguments": {"state": 2}}],
            tool_results=[{"status": 2}],
            state_patch={"position": 2},
        )


def test_tool_result_allowlist_compacts_and_enforces_byte_limit() -> None:
    compacted = loop.compact_tool_result(
        {"status": "ok", "secret": "must-not-appear", "items": list(range(100))},
        allowed_fields=["status", "items"],
    )
    assert "secret" not in compacted["result"]
    assert compacted["result"]["items"]["count"] == 100
    assert compacted["result"]["items"]["omitted_count"] == 68
    with pytest.raises(loop.ToolLoopError, match="TOOL_RESULT_BYTE_LIMIT"):
        loop.compact_tool_result(
            {"status": "x" * 2000},
            allowed_fields=["status"],
            max_bytes=100,
        )


def test_step_19_can_succeed_but_step_20_with_pending_state_fails() -> None:
    controller = _controller(no_progress_limit=30)
    for index in range(18):
        controller.process_step(
            calls=[{"name": "advance", "arguments": {"index": index}}],
            tool_results=[{"status": "ok", "ticket_id": index}],
            state_patch={"index": index},
        )
    result = controller.process_step(
        calls=[{"name": "create_ticket", "arguments": {"index": 18}}],
        tool_results=[{"status": "ok", "ticket_id": 18}],
        state_patch={"index": 18},
        resolved_outcomes=["ticket_created"],
    )
    assert result["step_count"] == 19
    done = controller.process_step(calls=[], tool_results=[], state_patch={})
    assert done["status"] == "SUCCESS_EXPLICIT_NO_CALL"

    controller = _controller(no_progress_limit=30)
    for index in range(19):
        controller.process_step(
            calls=[{"name": "advance", "arguments": {"index": index}}],
            tool_results=[{"status": "ok", "ticket_id": index}],
            state_patch={"index": index},
        )
    with pytest.raises(loop.ToolLoopError, match="STEP_LIMIT_BOUNDARY_FORCE_QUIT"):
        controller.process_step(
            calls=[{"name": "advance", "arguments": {"index": 19}}],
            tool_results=[{"status": "ok", "ticket_id": 19}],
            state_patch={"index": 19},
        )


def test_increasing_max_steps_is_rejected() -> None:
    with pytest.raises(loop.ToolLoopError, match="STEP_LIMIT_DRIFT"):
        _controller(max_steps=21)
