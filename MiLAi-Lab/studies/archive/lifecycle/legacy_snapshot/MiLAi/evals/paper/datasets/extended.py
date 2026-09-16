"""Strict label-free loaders for BEAM, HorizonBench, and CUPID inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ExtendedDatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtendedTurn:
    role: str
    content: str


@dataclass(frozen=True)
class ExtendedSession:
    session_id: str
    observed_at: str
    turns: tuple[ExtendedTurn, ...]


@dataclass(frozen=True)
class ExtendedCase:
    case_id: str
    category: str
    question: str
    question_at: str
    sessions: tuple[ExtendedSession, ...]


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtendedDatasetError(f"invalid extended input archive: {path}") from exc
    if not isinstance(value, dict):
        raise ExtendedDatasetError("extended input archive is not an object")
    return value


def _envelope(value: dict[str, Any], schema: str) -> tuple[str, list[Any]]:
    cases = value.get("cases")
    if (
        value.get("schema") != schema
        or value.get("paper_labels_opened") is not False
        or value.get("answer_label_fields_read_by_preparer") is not False
        or value.get("forbidden_label_fields_present") is not False
        or not isinstance(value.get("partition"), str)
        or not isinstance(cases, list)
        or value.get("case_count") != len(cases)
    ):
        raise ExtendedDatasetError("extended input envelope drifted")
    return str(value["partition"]), cases


def _turns(raw: object) -> tuple[ExtendedTurn, ...]:
    if not isinstance(raw, list) or not raw:
        raise ExtendedDatasetError("extended session has no messages")
    turns = []
    for message in raw:
        if not isinstance(message, dict):
            raise ExtendedDatasetError("extended message is not an object")
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise ExtendedDatasetError("extended message role/content drifted")
        turns.append(ExtendedTurn(role, content))
    return tuple(turns)


def _timestamp(ordinal: int) -> str:
    value = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=ordinal)
    return value.isoformat().replace("+00:00", "Z")


def _after_sessions(sessions: tuple[ExtendedSession, ...]) -> str:
    """Place a synthetic question strictly after every source session."""

    observed: list[datetime] = []
    for session in sessions:
        normalized = session.observed_at.strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ExtendedDatasetError("extended session timestamp drifted") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        observed.append(value.astimezone(timezone.utc))
    return (max(observed) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")


def _sessions(raw: object, *, namespace: str) -> tuple[ExtendedSession, ...]:
    if not isinstance(raw, list) or not raw:
        raise ExtendedDatasetError("extended history has no sessions")
    sessions = []
    for ordinal, session in enumerate(raw):
        if not isinstance(session, dict):
            raise ExtendedDatasetError("extended session is not an object")
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = f"{namespace}-session-{ordinal:04d}"
        sessions.append(
            ExtendedSession(
                session_id=session_id,
                observed_at=_timestamp(ordinal),
                turns=_turns(session.get("messages")),
            )
        )
    return tuple(sessions)


def load_beam_inputs(path: Path) -> tuple[str, tuple[ExtendedCase, ...]]:
    value = _object(path)
    partition, raw_cases = _envelope(value, "milai.dg11.paper-beam-inputs.v1")
    histories = value.get("histories")
    if (
        value.get("published_scale_label") != "128K"
        or value.get("repository_directory_label") != "100K"
        or value.get("scale_label_difference_disclosed") is not True
        or not isinstance(histories, list)
        or value.get("history_count") != len(histories)
    ):
        raise ExtendedDatasetError("BEAM input identity drifted")
    by_id: dict[str, tuple[ExtendedSession, ...]] = {}
    for history in histories:
        if not isinstance(history, dict) or not isinstance(history.get("history_id"), str):
            raise ExtendedDatasetError("BEAM history contract drifted")
        history_id = history["history_id"]
        by_id[history_id] = _sessions(history.get("sessions"), namespace=history_id)
    cases = []
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "category",
            "history_id",
            "question",
        }:
            raise ExtendedDatasetError("BEAM case fields drifted")
        history_id = raw["history_id"]
        if history_id not in by_id:
            raise ExtendedDatasetError("BEAM case references an unknown history")
        sessions = by_id[history_id]
        cases.append(
            ExtendedCase(
                case_id=str(raw["case_id"]),
                category=str(raw["category"]),
                question=str(raw["question"]),
                question_at=_after_sessions(sessions),
                sessions=sessions,
            )
        )
    _unique(cases)
    return partition, tuple(cases)


def _parse_horizon_history(
    text: str, *, history_id: str
) -> tuple[ExtendedSession, ...]:
    sessions: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in text.splitlines():
        if line.startswith("Conversation History:"):
            continue
        if line.startswith("Date: "):
            candidate = line[6:].strip()
            try:
                datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            except ValueError:
                # A model response can itself contain a document line such as
                # ``Date: [auto-fill]``. It is content, not a session delimiter.
                pass
            else:
                if current is not None:
                    sessions.append(current)
                current = {"messages": [], "observed_at": candidate}
                continue
        if line.startswith("Scenario: "):
            continue
        if current is None:
            continue
        messages = current["messages"]
        assert isinstance(messages, list)
        if line.startswith("User: "):
            messages.append({"content": line[6:], "role": "user"})
        elif line.startswith("Assistant: "):
            messages.append({"content": line[11:], "role": "assistant"})
        elif messages:
            last = messages[-1]
            assert isinstance(last, dict) and isinstance(last.get("content"), str)
            last["content"] = str(last["content"]) + "\n" + line
    if current is not None:
        sessions.append(current)
    if not sessions:
        raise ExtendedDatasetError("HorizonBench history did not contain sessions")
    result = []
    for ordinal, session in enumerate(sessions):
        observed_at = session.get("observed_at")
        result.append(
            ExtendedSession(
                session_id=f"{history_id}-session-{ordinal:03d}",
                observed_at=(
                    observed_at if isinstance(observed_at, str) else _timestamp(ordinal)
                ),
                turns=_turns(session.get("messages")),
            )
        )
    return tuple(result)


def load_horizon_inputs(path: Path) -> tuple[str, tuple[ExtendedCase, ...]]:
    value = _object(path)
    partition, raw_cases = _envelope(value, "milai.dg11.paper-horizon-inputs.v1")
    histories = value.get("histories")
    if not isinstance(histories, list) or value.get("history_count") != len(histories):
        raise ExtendedDatasetError("HorizonBench history denominator drifted")
    by_id: dict[str, tuple[ExtendedSession, ...]] = {}
    for history in histories:
        if not isinstance(history, dict) or set(history) != {
            "conversation",
            "history_id",
        }:
            raise ExtendedDatasetError("HorizonBench history fields drifted")
        history_id = history["history_id"]
        conversation = history["conversation"]
        if not isinstance(history_id, str) or not isinstance(conversation, str):
            raise ExtendedDatasetError("HorizonBench history types drifted")
        by_id[history_id] = _parse_horizon_history(
            conversation, history_id=history_id
        )
    cases = []
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "history_id",
            "options",
            "question",
        }:
            raise ExtendedDatasetError("HorizonBench case fields drifted")
        options = raw["options"]
        history_id = raw["history_id"]
        if not isinstance(options, list) or history_id not in by_id:
            raise ExtendedDatasetError("HorizonBench case references drifted")
        rendered_options = []
        for option in options:
            if (
                not isinstance(option, dict)
                or set(option) != {"letter", "option"}
                or option.get("letter") not in {"A", "B", "C", "D", "E"}
                or not isinstance(option.get("option"), str)
            ):
                raise ExtendedDatasetError("HorizonBench option fields drifted")
            rendered_options.append(f"{option['letter']}: {option['option']}")
        sessions = by_id[history_id]
        question = (
            f"{raw['question']}\n"
            + "\n".join(rendered_options)
            + "\nRespond with only the letter A, B, C, D, or E."
        )
        cases.append(
            ExtendedCase(
                case_id=str(raw["case_id"]),
                category="preference",
                question=question,
                question_at=_after_sessions(sessions),
                sessions=sessions,
            )
        )
    _unique(cases)
    return partition, tuple(cases)


def load_cupid_inputs(path: Path) -> tuple[str, tuple[ExtendedCase, ...]]:
    value = _object(path)
    partition, raw_cases = _envelope(value, "milai.dg11.paper-cupid-inputs.v1")
    cases = []
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "current_request",
            "sessions",
        }:
            raise ExtendedDatasetError("CUPID case fields drifted")
        case_id = raw["case_id"]
        request = raw["current_request"]
        if not isinstance(case_id, str) or not isinstance(request, str):
            raise ExtendedDatasetError("CUPID case types drifted")
        sessions = _sessions(raw["sessions"], namespace=case_id)
        cases.append(
            ExtendedCase(
                case_id=case_id,
                category="preference",
                question=request,
                question_at=_timestamp(len(sessions) + 1),
                sessions=sessions,
            )
        )
    _unique(cases)
    return partition, tuple(cases)


def load_extended_inputs(path: Path) -> tuple[str, tuple[ExtendedCase, ...]]:
    value = _object(path)
    schema = value.get("schema")
    if schema == "milai.dg11.paper-beam-inputs.v1":
        return load_beam_inputs(path)
    if schema == "milai.dg11.paper-horizon-inputs.v1":
        return load_horizon_inputs(path)
    if schema == "milai.dg11.paper-cupid-inputs.v1":
        return load_cupid_inputs(path)
    raise ExtendedDatasetError("unknown extended benchmark input schema")


def _unique(cases: list[ExtendedCase]) -> None:
    if len({case.case_id for case in cases}) != len(cases):
        raise ExtendedDatasetError("extended case IDs are not unique")
