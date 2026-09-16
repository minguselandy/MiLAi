from __future__ import annotations

import copy

import pytest

from scripts import dg10_bfcl_multiturn_safety as safety


def _identity_decoder(raw: str) -> list[str]:
    if raw == "[]":
        return []
    return [raw.strip()[1:-1]]


def test_dual_gate_preserves_typed_nested_literals() -> None:
    raw = (
        "[tool(profile={'name':'P','active':True}, values=[1, -2, 3.5], "
        "point=(4, 5), empty=None)]"
    )

    result = safety.attest_dual_gate(raw, {"tool"}, _identity_decoder)

    assert result.execution_calls == (raw[1:-1],)
    keywords = dict(result.canonical_calls[0]["keywords"])
    assert keywords["values"]["type"] == "list"
    assert keywords["values"]["items"][0] == {"type": "int", "value": 1}
    assert keywords["values"]["items"][2] == {
        "type": "float",
        "value": 3.5,
    }
    assert keywords["point"]["type"] == "tuple"
    assert keywords["empty"] == {"type": "none", "value": None}


def test_raw_gate_failure_never_invokes_official_decoder() -> None:
    calls = 0

    def decoder(_raw: str) -> list[str]:
        nonlocal calls
        calls += 1
        return []

    with pytest.raises(safety.SafetyGateError) as caught:
        safety.attest_dual_gate("tool(value=1)", {"tool"}, decoder)

    assert caught.value.code == "RAW_EXPLICIT_LIST_REQUIRED"
    assert calls == 0


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        ("[tool(1)]", "POSITIONAL_ARGUMENT_FORBIDDEN"),
        ("[obj.tool(value=1)]", "BARE_FUNCTION_NAME_REQUIRED"),
        ("[tool(value=other)]", "NON_LITERAL_ARGUMENT"),
        ("[tool(value=nested(x=1))]", "NON_LITERAL_ARGUMENT"),
        ("[tool(value={'x':1, 'x':2})]", "DUPLICATE_DICT_KEY"),
        ("[tool(**{'value':1})]", "KEYWORD_UNPACK_FORBIDDEN"),
        ("[tool(value=b'x')]", "UNSUPPORTED_CONSTANT"),
    ],
)
def test_raw_gate_rejects_unsafe_shapes(raw: str, expected_code: str) -> None:
    with pytest.raises(safety.SafetyGateError) as caught:
        safety.attest_dual_gate(raw, {"tool", "nested"}, _identity_decoder)

    assert caught.value.code == expected_code


def test_post_decoder_gate_rejects_type_change() -> None:
    with pytest.raises(safety.SafetyGateError) as caught:
        safety.attest_dual_gate(
            "[tool(value=1)]", {"tool"}, lambda _raw: ["tool(value=1.0)"]
        )

    assert caught.value.code == "RAW_DECODED_CANONICAL_MISMATCH"


def test_state_machine_latches_failure_without_executor_or_tool_result() -> None:
    executions: list[tuple[str, ...]] = []

    def executor(calls: tuple[str, ...]) -> list[str]:
        executions.append(calls)
        return ["unexpected"]

    machine = safety.SafeTurnStateMachine(
        frozenset({"tool"}), _identity_decoder, executor
    )
    result = machine.process_native_step(
        "READY", {"native_request_id": "native-fixture"}
    )

    assert result["status"] == "SAFETY_GATE_FAILURE"
    assert result["tool_results_emitted"] is False
    assert machine.failure_code == "RAW_EXPLICIT_LIST_REQUIRED"
    assert executions == []
    assert machine.records[0]["native_receipt"]["native_request_id"] == (
        "native-fixture"
    )


def test_state_machine_preserves_n_plus_one_without_executing() -> None:
    executions: list[tuple[str, ...]] = []

    def executor(calls: tuple[str, ...]) -> list[str]:
        executions.append(calls)
        return ["ok"]

    machine = safety.SafeTurnStateMachine(
        frozenset({"tool"}), _identity_decoder, executor, max_execution_steps=1
    )
    machine.process_native_step("[tool(value=1)]", {"native_request_id": "n1"})
    boundary = machine.process_native_step(
        "[tool(value=2)]", {"native_request_id": "n2"}
    )

    assert boundary["status"] == "STEP_LIMIT_BOUNDARY_FORCE_QUIT"
    assert boundary["execution_permitted"] is False
    assert boundary["tool_results_emitted"] is False
    assert executions == [("tool(value=1)",)]
    assert len(machine.records) == 2


def test_missed_function_schedule_is_exact_cumulative_and_non_mutating() -> None:
    case = {
        "function": [{"name": "initial_tool"}],
        "missed_function": {"1": [{"name": "revealed_tool"}]},
        "question": [[{"role": "user", "content": "first"}], []],
    }
    original = copy.deepcopy(case)

    schedule = safety.build_case_turn_schedule(case, "{functions}\nMORE")

    assert case == original
    assert schedule["turns"][0]["exposed_function_names"] == ["initial_tool"]
    assert schedule["turns"][1]["exposed_function_names"] == [
        "initial_tool",
        "revealed_tool",
    ]
    assert schedule["turns"][1]["effective_messages"] == [
        {"role": "user", "content": "[{'name': 'revealed_tool'}]\nMORE"}
    ]


def test_missed_function_schedule_rejects_nonempty_reveal_turn() -> None:
    case = {
        "function": [{"name": "initial_tool"}],
        "missed_function": {"0": [{"name": "revealed_tool"}]},
        "question": [[{"role": "user", "content": "must be empty"}]],
    }

    with pytest.raises(safety.SafetyGateError) as caught:
        safety.build_case_turn_schedule(case, "{functions}")

    assert caught.value.code == "HOLDOUT_TURN_NOT_EMPTY"
