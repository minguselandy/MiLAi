from __future__ import annotations

import copy
import dataclasses
import hashlib
import json

import pytest

from scripts import dg13u_u1_task_scenarios as tasks


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _event_evidence(session_ref: str, turn_id: str) -> dict[str, object]:
    return {
        "schema": tasks.EVENT_EVIDENCE_SCHEMA,
        "event_stream_sha256": _hash("events:" + turn_id),
        "event_count": 3,
        "typed_error_count": 0,
        "session_id_sha256": _hash("session:" + session_ref),
    }


def _measured_rows(case_id: str) -> list[dict[str, object]]:
    scenario = tasks.scenario_for_case(case_id)
    barrier = _hash("barrier:" + case_id)
    rows: list[dict[str, object]] = []
    for turn in scenario.turns:
        batch = next(
            batch for batch in scenario.batches if turn.turn_id in batch.turn_ids
        )
        rows.append(
            {
                "turn_id": turn.turn_id,
                "batch_index": batch.batch_index,
                "launch_mode": batch.launch_mode,
                "barrier_release_sha256": (
                    barrier if batch.launch_mode == "BARRIER_CONCURRENT" else None
                ),
                "session_id_sha256": _hash("session:" + turn.session_ref),
                "operation_id_sha256": _hash("operation:" + turn.turn_id),
                "task_id_sha256": _hash("task:" + turn.session_ref),
                "mcp_calls": 1,
                "provider_calls": 1,
                "automatic_retries": 0,
                "fresh_resolve": case_id == "U1-TASK-CONTINUE",
                "mcp_tool": (
                    "milai_memory_resolve"
                    if case_id == "U1-TASK-CONTINUE"
                    else None
                ),
                "event_evidence": _event_evidence(turn.session_ref, turn.turn_id),
            }
        )
    return rows


def test_exact_task_scenario_set_and_call_totals_are_frozen() -> None:
    expected = {
        "U1-TASK-CONTINUE": (2, 2),
        "U1-TASK-SWITCH": (2, 2),
        "U1-TASK-RETURN": (3, 3),
        "U1-TASK-CONCURRENT": (2, 2),
    }

    assert set(tasks.TASK_SCENARIOS) == set(expected)
    for case_id, (mcp_calls, provider_calls) in expected.items():
        scenario = tasks.scenario_for_case(case_id)
        assert scenario.expected_mcp_calls == mcp_calls
        assert scenario.expected_provider_calls == provider_calls
        assert scenario.automatic_retries == 0
        with pytest.raises(dataclasses.FrozenInstanceError):
            scenario.case_id = "U1-NONE-EN"  # type: ignore[misc]


def test_continue_switch_return_and_concurrent_session_orchestration_is_exact() -> None:
    assert [
        (turn.turn_id, turn.session_ref, turn.session_action)
        for turn in tasks.TASK_SCENARIOS["U1-TASK-CONTINUE"].turns
    ] == [("A-NEW", "A", "NEW"), ("A-CONTINUE", "A", "CONTINUE")]
    assert [
        (turn.turn_id, turn.session_ref, turn.session_action)
        for turn in tasks.TASK_SCENARIOS["U1-TASK-SWITCH"].turns
    ] == [("A-NEW", "A", "NEW"), ("B-NEW", "B", "NEW")]
    assert [
        (turn.turn_id, turn.session_ref, turn.session_action)
        for turn in tasks.TASK_SCENARIOS["U1-TASK-RETURN"].turns
    ] == [
        ("A-NEW", "A", "NEW"),
        ("B-NEW", "B", "NEW"),
        ("A-RETURN", "A", "CONTINUE"),
    ]
    concurrent = tasks.TASK_SCENARIOS["U1-TASK-CONCURRENT"]
    assert concurrent.batches == (
        tasks.BatchSpec(0, ("A-NEW", "B-NEW"), "BARRIER_CONCURRENT"),
    )
    assert all(turn.session_action == "NEW" for turn in concurrent.turns)


def test_actual_opencode_command_contract_uses_new_then_explicit_session() -> None:
    scenario = tasks.scenario_for_case("U1-TASK-CONTINUE")
    prompt = "synthetic private prompt"
    new_command = tasks.build_opencode_command(
        scenario.turns[0],
        container_name="milai-worker-synthetic",
        prompt=prompt,
        known_sessions={},
        created_session_id="ses_synthetic_private_new",
    )
    session_id = "ses_synthetic_private_1"
    continued = tasks.build_opencode_command(
        scenario.turns[1],
        container_name="milai-worker-synthetic",
        prompt=prompt,
        known_sessions={"A": session_id},
    )

    common = (
        "docker",
        "exec",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        "milai-worker-synthetic",
        "opencode",
        "run",
        "--attach",
        "http://127.0.0.1:4096",
        "--password",
        "openworker-local",
        "--format",
        "json",
        "--model",
        "openworker/Qwen3.6-35B-A3B-FP8",
    )
    assert new_command == (
        *common,
        "--session",
        "ses_synthetic_private_new",
        "--dir",
        "/openworker/runtime",
        prompt,
    )
    assert continued == (
        *common,
        "--session",
        session_id,
        "--dir",
        "/openworker/runtime",
        prompt,
    )
    with pytest.raises(tasks.TaskScenarioError, match="NEW_SESSION_ALREADY_BOUND"):
        tasks.build_opencode_command(
            scenario.turns[0],
            container_name="milai-worker-synthetic",
            prompt=prompt,
            known_sessions={"A": session_id},
        )
    with pytest.raises(
        tasks.TaskScenarioError, match="CONTINUATION_SESSION_UNAVAILABLE"
    ):
        tasks.build_opencode_command(
            scenario.turns[1],
            container_name="milai-worker-synthetic",
            prompt=prompt,
            known_sessions={},
        )


def test_raw_sessions_are_bound_only_in_memory_and_continuation_must_match() -> None:
    scenario = tasks.scenario_for_case("U1-TASK-RETURN")
    bindings = tasks.bind_observed_session(
        scenario.turns[0],
        "ses_private_a",
        {},
        created_session_id="ses_private_a",
    )
    bindings = tasks.bind_observed_session(
        scenario.turns[1],
        "ses_private_b",
        bindings,
        created_session_id="ses_private_b",
    )
    verified = tasks.bind_observed_session(scenario.turns[2], "ses_private_a", bindings)

    assert verified == {"A": "ses_private_a", "B": "ses_private_b"}
    with pytest.raises(tasks.TaskScenarioError, match="CONTINUATION_SESSION_MISMATCH"):
        tasks.bind_observed_session(scenario.turns[2], "ses_private_b", bindings)
    concurrent = tasks.scenario_for_case("U1-TASK-CONCURRENT")
    with pytest.raises(tasks.TaskScenarioError, match="CROSS_SESSION_ID_REUSED"):
        tasks.bind_observed_session(
            concurrent.turns[1],
            "ses_private_a",
            {"A": "ses_private_a"},
            created_session_id="ses_private_a",
        )


def test_session_create_command_and_parser_are_shell_free_and_memory_only() -> None:
    command = tasks.build_opencode_session_create_command("milai-worker-synthetic")
    private_session = "ses_private_created_1"
    raw = json.dumps(
        {
            "id": private_session,
            "directory": "/openworker/runtime",
            "time": {"created": 1},
        }
    ).encode()

    assert command == (
        "docker",
        "exec",
        "milai-worker-synthetic",
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--user",
        "opencode:openworker-local",
        "--request",
        "POST",
        "--header",
        "Content-Type: application/json",
        "--data-binary",
        '{"title":"DG13U U1 bounded session"}',
        "http://127.0.0.1:4096/session?directory=%2Fopenworker%2Fruntime",
    )
    assert not any(value in command for value in ("sh", "bash", "-c"))
    assert tasks.parse_created_opencode_session(raw) == private_session


@pytest.mark.parametrize(
    ("raw", "reason"),
    (
        (b"", "SESSION_CREATE_RESPONSE_EMPTY"),
        (b"\xff", "SESSION_CREATE_RESPONSE_INVALID_UTF8"),
        (b"not-json", "SESSION_CREATE_RESPONSE_INVALID_JSON"),
        (b"[]", "SESSION_CREATE_RESPONSE_INVALID"),
        (b'{"id":"bad id"}', "SESSION_CREATE_ID_INVALID"),
        (
            b'{"id":"ses_a","nested":{"id":"ses_b"}}',
            "SESSION_CREATE_ID_INVALID",
        ),
    ),
)
def test_session_create_parser_fails_closed(raw: bytes, reason: str) -> None:
    with pytest.raises(tasks.TaskScenarioError, match=reason):
        tasks.parse_created_opencode_session(raw)


def test_new_command_and_binding_require_the_created_session_identity() -> None:
    turn = tasks.scenario_for_case("U1-TASK-CONTINUE").turns[0]
    with pytest.raises(tasks.TaskScenarioError, match="CREATED_SESSION_UNAVAILABLE"):
        tasks.build_opencode_command(
            turn,
            container_name="milai-worker-synthetic",
            prompt="synthetic prompt",
            known_sessions={},
        )
    with pytest.raises(tasks.TaskScenarioError, match="CREATED_SESSION_MISMATCH"):
        tasks.bind_observed_session(
            turn,
            "ses_observed",
            {},
            created_session_id="ses_created",
        )


def test_json_event_parser_returns_raw_session_only_in_memory_and_hash_only_evidence() -> (
    None
):
    session_id = "ses_private_synthetic_1"
    raw = b"\n".join(
        [
            json.dumps(
                {
                    "type": "step_start",
                    "sessionID": session_id,
                    "part": {"type": "step-start"},
                }
            ).encode(),
            json.dumps(
                {
                    "type": "text",
                    "sessionID": session_id,
                    "part": {"type": "text", "text": "private synthetic answer"},
                }
            ).encode(),
        ]
    )

    parsed_session, evidence = tasks.parse_opencode_session_events(raw)

    encoded = json.dumps(evidence, sort_keys=True)
    assert parsed_session == session_id
    assert evidence == {
        "schema": tasks.EVENT_EVIDENCE_SCHEMA,
        "event_stream_sha256": hashlib.sha256(raw).hexdigest(),
        "event_count": 2,
        "typed_error_count": 0,
        "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
    }
    assert session_id not in encoded
    assert "private synthetic answer" not in encoded
    assert "text" not in evidence
    assert "content" not in evidence


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"", "OPENCODE_EVENTS_EMPTY"),
        (b"not-json", "OPENCODE_EVENT_INVALID_JSON"),
        (b"[]", "OPENCODE_EVENT_INVALID"),
        (b'{"type":"text"}', "OPENCODE_SESSION_NOT_UNIQUE"),
        (
            b'{"type":"text","sessionID":"ses_a"}\n{"type":"text","sessionID":"ses_b"}',
            "OPENCODE_SESSION_NOT_UNIQUE",
        ),
        (b'{"type":"error","sessionID":"ses_a"}', "OPENCODE_TYPED_ERROR"),
    ],
)
def test_json_event_parser_fails_closed(raw: bytes, reason: str) -> None:
    with pytest.raises(tasks.TaskScenarioError, match=reason):
        tasks.parse_opencode_session_events(raw)


@pytest.mark.parametrize("case_id", tuple(tasks.TASK_SCENARIOS))
def test_measured_reducer_validates_counts_bindings_and_emits_no_raw_values(
    case_id: str,
) -> None:
    rows = _measured_rows(case_id)

    evidence = tasks.reduce_measured_task_case(case_id, rows)

    scenario = tasks.scenario_for_case(case_id)
    encoded = json.dumps(evidence, sort_keys=True)
    assert evidence["schema"] == tasks.CASE_EVIDENCE_SCHEMA
    assert evidence["status"] == "PASS"
    assert evidence["turn_count"] == len(scenario.turns)
    assert evidence["observed_mcp_calls"] == scenario.expected_mcp_calls
    assert evidence["observed_provider_calls"] == scenario.expected_provider_calls
    assert evidence["automatic_retries"] == 0
    assert evidence["all_turns_fresh_resolve"] is (
        case_id == "U1-TASK-CONTINUE"
    )
    assert evidence["mcp_tool"] == (
        "milai_memory_resolve" if case_id == "U1-TASK-CONTINUE" else None
    )
    assert evidence["operation_ids_unique"] is True
    assert evidence["session_task_bindings_distinct"] is True
    for forbidden in (
        "ses_private",
        "synthetic private prompt",
        "private synthetic answer",
        '"session_id"',
        '"operation_id"',
        '"task_id"',
        '"prompt"',
        '"output"',
        '"content"',
        '"text"',
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    ("case_id", "mutation", "reason"),
    [
        (
            "U1-TASK-CONTINUE",
            lambda rows: rows[1].__setitem__("session_id_sha256", _hash("other")),
            "SESSION_CONTINUITY_INVALID",
        ),
        (
            "U1-TASK-CONTINUE",
            lambda rows: rows[1].__setitem__("task_id_sha256", _hash("other")),
            "TASK_CONTINUITY_INVALID",
        ),
        (
            "U1-TASK-SWITCH",
            lambda rows: rows[1].__setitem__(
                "session_id_sha256", rows[0]["session_id_sha256"]
            ),
            "CROSS_SESSION_ID_REUSED",
        ),
        (
            "U1-TASK-SWITCH",
            lambda rows: rows[1].__setitem__(
                "task_id_sha256", rows[0]["task_id_sha256"]
            ),
            "CROSS_SESSION_TASK_REUSED",
        ),
        (
            "U1-TASK-RETURN",
            lambda rows: rows[2].__setitem__(
                "operation_id_sha256", rows[0]["operation_id_sha256"]
            ),
            "OPERATION_ID_REUSED",
        ),
        (
            "U1-TASK-CONCURRENT",
            lambda rows: rows[1].__setitem__("barrier_release_sha256", _hash("other")),
            "CONCURRENT_BARRIER_MISMATCH",
        ),
        (
            "U1-TASK-CONTINUE",
            lambda rows: rows[0].__setitem__("automatic_retries", 1),
            "MEASURED_CALL_ACCOUNTING_INVALID",
        ),
        (
            "U1-TASK-CONTINUE",
            lambda rows: rows[0].__setitem__("provider_calls", 2),
            "MEASURED_CALL_ACCOUNTING_INVALID",
        ),
        (
            "U1-TASK-CONTINUE",
            lambda rows: rows[1].__setitem__("fresh_resolve", False),
            "MEASURED_QUERY_FIRST_INVALID",
        ),
        (
            "U1-TASK-SWITCH",
            lambda rows: rows[0].__setitem__(
                "mcp_tool", "milai_memory_resolve"
            ),
            "MEASURED_QUERY_FIRST_UNEXPECTED",
        ),
    ],
)
def test_measured_reducer_rejects_reuse_drift_mixing_and_retry(
    case_id: str,
    mutation,
    reason: str,  # type: ignore[no-untyped-def]
) -> None:
    rows = _measured_rows(case_id)
    mutation(rows)
    for row in rows:
        event = row["event_evidence"]
        assert isinstance(event, dict)
        event["session_id_sha256"] = row["session_id_sha256"]

    with pytest.raises(tasks.TaskScenarioError, match=reason):
        tasks.reduce_measured_task_case(case_id, rows)


def test_measured_reducer_rejects_event_binding_drift_and_raw_field() -> None:
    drifted = _measured_rows("U1-TASK-CONTINUE")
    drifted[0]["event_evidence"]["session_id_sha256"] = _hash("other")
    with pytest.raises(tasks.TaskScenarioError, match="EVENT_EVIDENCE_INVALID"):
        tasks.reduce_measured_task_case("U1-TASK-CONTINUE", drifted)

    raw = _measured_rows("U1-TASK-CONTINUE")
    raw[0]["prompt"] = "must never be accepted"
    with pytest.raises(tasks.TaskScenarioError, match="MEASURED_ROW_FIELDS_INVALID"):
        tasks.reduce_measured_task_case("U1-TASK-CONTINUE", raw)


def test_wrong_order_and_unsupported_selectors_fail_closed() -> None:
    rows = _measured_rows("U1-TASK-SWITCH")
    rows.reverse()
    with pytest.raises(tasks.TaskScenarioError, match="MEASURED_TURN_ORDER_INVALID"):
        tasks.reduce_measured_task_case("U1-TASK-SWITCH", rows)
    with pytest.raises(tasks.TaskScenarioError, match="UNSUPPORTED_CASE"):
        tasks.scenario_for_case("U1-NONE-EN")
    with pytest.raises(tasks.TaskScenarioError, match="TURN_ID_INVALID"):
        tasks.turn_for_id("U1-TASK-SWITCH", "C-NEW")


def test_reducer_does_not_mutate_measured_rows() -> None:
    rows = _measured_rows("U1-TASK-RETURN")
    before = copy.deepcopy(rows)

    tasks.reduce_measured_task_case("U1-TASK-RETURN", rows)

    assert rows == before
