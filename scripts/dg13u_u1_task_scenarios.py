"""Frozen OpenCode orchestration and hash-only reducers for DG-13U U1 task cases.

The helpers in this module never start a process.  Raw prompts and OpenCode
session identifiers are accepted only to construct an in-memory command or to
derive a digest; neither is returned in durable evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

SessionAction = Literal["NEW", "CONTINUE"]
LaunchMode = Literal["SERIAL", "BARRIER_CONCURRENT"]

EVENT_EVIDENCE_SCHEMA = "milai.dg13u.u1-task-opencode-events.v1"
CASE_EVIDENCE_SCHEMA = "milai.dg13u.u1-task-case-evidence.v1"
_MODEL = "openworker/Qwen3.6-35B-A3B-FP8"
_OPENWORKER_ORIGIN = "http://127.0.0.1:4096"
_OPENWORKER_DIRECTORY = "/openworker/runtime"
_OPENWORKER_DIRECTORY_QUERY = "%2Fopenworker%2Fruntime"
_OPENWORKER_BASIC_AUTH = "opencode:openworker-local"
_OPENWORKER_PASSWORD = "openworker-local"
_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


class TaskScenarioError(ValueError):
    """A task plan, command input, or measured row violated the contract."""


@dataclass(frozen=True, slots=True)
class TurnSpec:
    turn_id: str
    session_ref: str
    session_action: SessionAction


@dataclass(frozen=True, slots=True)
class BatchSpec:
    batch_index: int
    turn_ids: tuple[str, ...]
    launch_mode: LaunchMode


@dataclass(frozen=True, slots=True)
class TaskScenario:
    case_id: str
    turns: tuple[TurnSpec, ...]
    batches: tuple[BatchSpec, ...]
    expected_mcp_calls: int
    expected_provider_calls: int
    automatic_retries: Literal[0]


def _scenario(
    case_id: str,
    turns: tuple[TurnSpec, ...],
    batches: tuple[BatchSpec, ...],
) -> TaskScenario:
    count = len(turns)
    flattened = tuple(turn_id for batch in batches for turn_id in batch.turn_ids)
    if flattened != tuple(turn.turn_id for turn in turns):
        raise AssertionError("task scenario batches do not preserve turn order")
    return TaskScenario(
        case_id=case_id,
        turns=turns,
        batches=batches,
        expected_mcp_calls=count,
        expected_provider_calls=count,
        automatic_retries=0,
    )


TASK_SCENARIOS: Mapping[str, TaskScenario] = MappingProxyType(
    {
        "U1-TASK-CONTINUE": _scenario(
            "U1-TASK-CONTINUE",
            (
                TurnSpec("A-NEW", "A", "NEW"),
                TurnSpec("A-CONTINUE", "A", "CONTINUE"),
            ),
            (
                BatchSpec(0, ("A-NEW",), "SERIAL"),
                BatchSpec(1, ("A-CONTINUE",), "SERIAL"),
            ),
        ),
        "U1-TASK-SWITCH": _scenario(
            "U1-TASK-SWITCH",
            (
                TurnSpec("A-NEW", "A", "NEW"),
                TurnSpec("B-NEW", "B", "NEW"),
            ),
            (
                BatchSpec(0, ("A-NEW",), "SERIAL"),
                BatchSpec(1, ("B-NEW",), "SERIAL"),
            ),
        ),
        "U1-TASK-RETURN": _scenario(
            "U1-TASK-RETURN",
            (
                TurnSpec("A-NEW", "A", "NEW"),
                TurnSpec("B-NEW", "B", "NEW"),
                TurnSpec("A-RETURN", "A", "CONTINUE"),
            ),
            (
                BatchSpec(0, ("A-NEW",), "SERIAL"),
                BatchSpec(1, ("B-NEW",), "SERIAL"),
                BatchSpec(2, ("A-RETURN",), "SERIAL"),
            ),
        ),
        "U1-TASK-CONCURRENT": _scenario(
            "U1-TASK-CONCURRENT",
            (
                TurnSpec("A-NEW", "A", "NEW"),
                TurnSpec("B-NEW", "B", "NEW"),
            ),
            (BatchSpec(0, ("A-NEW", "B-NEW"), "BARRIER_CONCURRENT"),),
        ),
    }
)


def scenario_for_case(case_id: str) -> TaskScenario:
    if not isinstance(case_id, str) or case_id not in TASK_SCENARIOS:
        raise TaskScenarioError("UNSUPPORTED_CASE")
    return TASK_SCENARIOS[case_id]


def turn_for_id(case_id: str, turn_id: str) -> TurnSpec:
    scenario = scenario_for_case(case_id)
    matches = [turn for turn in scenario.turns if turn.turn_id == turn_id]
    if len(matches) != 1:
        raise TaskScenarioError("TURN_ID_INVALID")
    return matches[0]


def build_opencode_session_create_command(container_name: str) -> tuple[str, ...]:
    """Build the shell-free local control-plane request for one fresh session."""

    if (
        not isinstance(container_name, str)
        or _IDENTIFIER.fullmatch(container_name) is None
    ):
        raise TaskScenarioError("CONTAINER_NAME_INVALID")
    return (
        "docker",
        "exec",
        container_name,
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--user",
        _OPENWORKER_BASIC_AUTH,
        "--request",
        "POST",
        "--header",
        "Content-Type: application/json",
        "--data-binary",
        '{"title":"DG13U U1 bounded session"}',
        f"{_OPENWORKER_ORIGIN}/session?directory={_OPENWORKER_DIRECTORY_QUERY}",
    )


def parse_created_opencode_session(raw: bytes) -> str:
    """Validate one session-create response and return its raw ID only in memory."""

    if not isinstance(raw, bytes) or not raw.strip():
        raise TaskScenarioError("SESSION_CREATE_RESPONSE_EMPTY")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise TaskScenarioError("SESSION_CREATE_RESPONSE_INVALID_UTF8") from exc
    except json.JSONDecodeError as exc:
        raise TaskScenarioError("SESSION_CREATE_RESPONSE_INVALID_JSON") from exc
    if not isinstance(value, Mapping):
        raise TaskScenarioError("SESSION_CREATE_RESPONSE_INVALID")
    observed_ids = [
        candidate
        for mapping in _nested_mappings(value)
        if "id" in mapping
        for candidate in (mapping.get("id"),)
    ]
    session_id = value.get("id")
    if (
        len(observed_ids) != 1
        or observed_ids[0] != session_id
        or not isinstance(session_id, str)
        or _IDENTIFIER.fullmatch(session_id) is None
    ):
        raise TaskScenarioError("SESSION_CREATE_ID_INVALID")
    return session_id


def _nested_mappings(value: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    observed: list[Mapping[str, object]] = []

    def visit(candidate: object) -> None:
        if isinstance(candidate, Mapping):
            observed.append(cast(Mapping[str, object], candidate))
            for nested in candidate.values():
                visit(nested)
        elif isinstance(candidate, Sequence) and not isinstance(
            candidate, (str, bytes)
        ):
            for nested in candidate:
                visit(nested)

    visit(value)
    return tuple(observed)


def build_opencode_command(
    turn: TurnSpec,
    *,
    container_name: str,
    prompt: str,
    known_sessions: Mapping[str, str],
    created_session_id: str | None = None,
    model: str = _MODEL,
) -> tuple[str, ...]:
    """Build the actual shell-free OpenCode CLI contract for one turn."""

    if (
        not isinstance(container_name, str)
        or _IDENTIFIER.fullmatch(container_name) is None
    ):
        raise TaskScenarioError("CONTAINER_NAME_INVALID")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4_096:
        raise TaskScenarioError("PROMPT_INVALID")
    if model != _MODEL:
        raise TaskScenarioError("MODEL_INVALID")
    if not isinstance(known_sessions, Mapping):
        raise TaskScenarioError("SESSION_BINDINGS_INVALID")
    command = [
        "docker",
        "exec",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        container_name,
        "opencode",
        "run",
        "--attach",
        _OPENWORKER_ORIGIN,
        "--password",
        _OPENWORKER_PASSWORD,
        "--format",
        "json",
        "--model",
        model,
    ]
    if turn.session_action == "NEW":
        if turn.session_ref in known_sessions:
            raise TaskScenarioError("NEW_SESSION_ALREADY_BOUND")
        if (
            not isinstance(created_session_id, str)
            or _IDENTIFIER.fullmatch(created_session_id) is None
            or created_session_id in known_sessions.values()
        ):
            raise TaskScenarioError("CREATED_SESSION_UNAVAILABLE")
        session_id = created_session_id
    else:
        if created_session_id is not None:
            raise TaskScenarioError("CONTINUATION_CREATED_SESSION_FORBIDDEN")
        session_id = known_sessions.get(turn.session_ref)
        if not isinstance(session_id, str) or _IDENTIFIER.fullmatch(session_id) is None:
            raise TaskScenarioError("CONTINUATION_SESSION_UNAVAILABLE")
    command.extend(("--session", session_id, "--dir", _OPENWORKER_DIRECTORY))
    command.append(prompt)
    return tuple(command)


def bind_observed_session(
    turn: TurnSpec,
    observed_session_id: str,
    known_sessions: Mapping[str, str],
    *,
    created_session_id: str | None = None,
) -> dict[str, str]:
    """Bind or verify one raw OpenCode session strictly in runner memory."""

    if (
        not isinstance(observed_session_id, str)
        or _IDENTIFIER.fullmatch(observed_session_id) is None
        or not isinstance(known_sessions, Mapping)
        or any(
            not isinstance(ref, str)
            or not isinstance(session_id, str)
            or _IDENTIFIER.fullmatch(session_id) is None
            for ref, session_id in known_sessions.items()
        )
    ):
        raise TaskScenarioError("SESSION_BINDINGS_INVALID")
    updated = dict(known_sessions)
    if turn.session_action == "NEW":
        if (
            not isinstance(created_session_id, str)
            or _IDENTIFIER.fullmatch(created_session_id) is None
            or not _constant_time_equal(created_session_id, observed_session_id)
        ):
            raise TaskScenarioError("CREATED_SESSION_MISMATCH")
        if turn.session_ref in updated:
            raise TaskScenarioError("NEW_SESSION_ALREADY_BOUND")
        if observed_session_id in updated.values():
            raise TaskScenarioError("CROSS_SESSION_ID_REUSED")
        updated[turn.session_ref] = observed_session_id
        return updated
    if created_session_id is not None:
        raise TaskScenarioError("CONTINUATION_CREATED_SESSION_FORBIDDEN")
    expected = updated.get(turn.session_ref)
    if expected is None:
        raise TaskScenarioError("CONTINUATION_SESSION_UNAVAILABLE")
    if not _constant_time_equal(expected, observed_session_id):
        raise TaskScenarioError("CONTINUATION_SESSION_MISMATCH")
    return updated


def parse_opencode_session_events(raw: bytes) -> tuple[str, dict[str, object]]:
    """Return the raw session only in memory plus content-free event evidence."""

    if not isinstance(raw, bytes) or not raw.strip():
        raise TaskScenarioError("OPENCODE_EVENTS_EMPTY")
    events: list[Mapping[str, object]] = []
    session_ids: set[str] = set()
    typed_error_count = 0
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise TaskScenarioError("OPENCODE_EVENTS_INVALID_UTF8") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TaskScenarioError("OPENCODE_EVENT_INVALID_JSON") from exc
        if not isinstance(event, Mapping):
            raise TaskScenarioError("OPENCODE_EVENT_INVALID")
        events.append(cast(Mapping[str, object], event))
        if event.get("type") == "error":
            typed_error_count += 1
        session_id = event.get("sessionID")
        if isinstance(session_id, str):
            if _IDENTIFIER.fullmatch(session_id) is None:
                raise TaskScenarioError("OPENCODE_SESSION_INVALID")
            session_ids.add(session_id)
    if typed_error_count:
        raise TaskScenarioError("OPENCODE_TYPED_ERROR")
    if len(events) == 0:
        raise TaskScenarioError("OPENCODE_EVENTS_EMPTY")
    if len(session_ids) != 1:
        raise TaskScenarioError("OPENCODE_SESSION_NOT_UNIQUE")
    session_id = next(iter(session_ids))
    evidence: dict[str, object] = {
        "schema": EVENT_EVIDENCE_SCHEMA,
        "event_stream_sha256": hashlib.sha256(raw).hexdigest(),
        "event_count": len(events),
        "typed_error_count": 0,
        "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
    }
    return session_id, evidence


_ROW_FIELDS = frozenset(
    {
        "turn_id",
        "batch_index",
        "launch_mode",
        "barrier_release_sha256",
        "session_id_sha256",
        "operation_id_sha256",
        "task_id_sha256",
        "mcp_calls",
        "provider_calls",
        "automatic_retries",
        "fresh_resolve",
        "mcp_tool",
        "event_evidence",
    }
)
_EVENT_FIELDS = frozenset(
    {
        "schema",
        "event_stream_sha256",
        "event_count",
        "typed_error_count",
        "session_id_sha256",
    }
)


def reduce_measured_task_case(
    case_id: str, measured_rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Validate measured rows and emit only hashes, structure, and call counts."""

    scenario = scenario_for_case(case_id)
    if (
        not isinstance(measured_rows, Sequence)
        or isinstance(measured_rows, (str, bytes))
        or len(measured_rows) != len(scenario.turns)
    ):
        raise TaskScenarioError("MEASURED_ROW_COUNT_INVALID")
    expected_turn_ids = tuple(turn.turn_id for turn in scenario.turns)
    rows = list(measured_rows)
    if (
        tuple(row.get("turn_id") for row in rows if isinstance(row, Mapping))
        != expected_turn_ids
    ):
        raise TaskScenarioError("MEASURED_TURN_ORDER_INVALID")

    safe_rows: list[dict[str, object]] = []
    for turn, row in zip(scenario.turns, rows, strict=True):
        if not isinstance(row, Mapping) or set(row) != _ROW_FIELDS:
            raise TaskScenarioError("MEASURED_ROW_FIELDS_INVALID")
        batch = next(
            batch for batch in scenario.batches if turn.turn_id in batch.turn_ids
        )
        if (
            row.get("batch_index") != batch.batch_index
            or row.get("launch_mode") != batch.launch_mode
        ):
            raise TaskScenarioError("MEASURED_BATCH_BINDING_INVALID")
        for name in ("session_id_sha256", "operation_id_sha256", "task_id_sha256"):
            if not _is_sha256(row.get(name)):
                raise TaskScenarioError("MEASURED_ID_HASH_INVALID")
        if (
            row.get("mcp_calls") != 1
            or row.get("provider_calls") != 1
            or row.get("automatic_retries") != 0
        ):
            raise TaskScenarioError("MEASURED_CALL_ACCOUNTING_INVALID")
        if case_id == "U1-TASK-CONTINUE":
            if (
                row.get("fresh_resolve") is not True
                or row.get("mcp_tool") != "milai_memory_resolve"
            ):
                raise TaskScenarioError("MEASURED_QUERY_FIRST_INVALID")
        elif row.get("fresh_resolve") is not False or row.get("mcp_tool") is not None:
            raise TaskScenarioError("MEASURED_QUERY_FIRST_UNEXPECTED")
        event = row.get("event_evidence")
        if not isinstance(event, Mapping) or set(event) != _EVENT_FIELDS:
            raise TaskScenarioError("EVENT_EVIDENCE_FIELDS_INVALID")
        if (
            event.get("schema") != EVENT_EVIDENCE_SCHEMA
            or not _is_sha256(event.get("event_stream_sha256"))
            or not isinstance(event.get("event_count"), int)
            or isinstance(event.get("event_count"), bool)
            or cast(int, event.get("event_count")) < 1
            or event.get("typed_error_count") != 0
            or event.get("session_id_sha256") != row.get("session_id_sha256")
        ):
            raise TaskScenarioError("EVENT_EVIDENCE_INVALID")
        barrier = row.get("barrier_release_sha256")
        if batch.launch_mode == "SERIAL":
            if barrier is not None:
                raise TaskScenarioError("SERIAL_BARRIER_INVALID")
        elif not _is_sha256(barrier):
            raise TaskScenarioError("CONCURRENT_BARRIER_INVALID")
        safe_rows.append(
            {
                name: (dict(event) if name == "event_evidence" else row[name])
                for name in sorted(_ROW_FIELDS)
            }
        )

    operation_hashes = [cast(str, row["operation_id_sha256"]) for row in rows]
    if len(operation_hashes) != len(set(operation_hashes)):
        raise TaskScenarioError("OPERATION_ID_REUSED")
    session_refs = tuple(dict.fromkeys(turn.session_ref for turn in scenario.turns))
    session_hash_by_ref: dict[str, str] = {}
    task_hash_by_ref: dict[str, str] = {}
    for session_ref in session_refs:
        indices = [
            index
            for index, turn in enumerate(scenario.turns)
            if turn.session_ref == session_ref
        ]
        session_hashes = {
            cast(str, rows[index]["session_id_sha256"]) for index in indices
        }
        task_hashes = {cast(str, rows[index]["task_id_sha256"]) for index in indices}
        if len(session_hashes) != 1:
            raise TaskScenarioError("SESSION_CONTINUITY_INVALID")
        if len(task_hashes) != 1:
            raise TaskScenarioError("TASK_CONTINUITY_INVALID")
        session_hash_by_ref[session_ref] = next(iter(session_hashes))
        task_hash_by_ref[session_ref] = next(iter(task_hashes))
    if len(set(session_hash_by_ref.values())) != len(session_refs):
        raise TaskScenarioError("CROSS_SESSION_ID_REUSED")
    if len(set(task_hash_by_ref.values())) != len(session_refs):
        raise TaskScenarioError("CROSS_SESSION_TASK_REUSED")
    for batch in scenario.batches:
        if batch.launch_mode != "BARRIER_CONCURRENT":
            continue
        barrier_hashes = {
            cast(str, rows[index]["barrier_release_sha256"])
            for index, turn in enumerate(scenario.turns)
            if turn.turn_id in batch.turn_ids
        }
        if len(barrier_hashes) != 1:
            raise TaskScenarioError("CONCURRENT_BARRIER_MISMATCH")

    return {
        "schema": CASE_EVIDENCE_SCHEMA,
        "case_id": scenario.case_id,
        "status": "PASS",
        "turn_count": len(rows),
        "session_count": len(session_refs),
        "observed_mcp_calls": sum(cast(int, row["mcp_calls"]) for row in rows),
        "observed_provider_calls": sum(
            cast(int, row["provider_calls"]) for row in rows
        ),
        "automatic_retries": 0,
        "all_turns_fresh_resolve": case_id == "U1-TASK-CONTINUE",
        "mcp_tool": (
            "milai_memory_resolve" if case_id == "U1-TASK-CONTINUE" else None
        ),
        "operation_ids_unique": True,
        "session_task_bindings_distinct": True,
        "rows": safe_rows,
    }


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
