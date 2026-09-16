"""Label-free LongMemEval input contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LongMemEvalInputError(RuntimeError):
    pass


def pseudonymize_session_id(
    source_id: str, raw_session_id: str, occurrence: int = 0
) -> str:
    """Remove benchmark answer markers while preserving scorer-reproducible identity."""

    if not source_id or not raw_session_id or occurrence < 0:
        raise LongMemEvalInputError("LongMemEval session identity is empty")
    digest = hashlib.sha256(
        b"milai-dg11-paper-session-v1\0"
        + source_id.encode()
        + b"\0"
        + raw_session_id.encode()
        + b"\0"
        + str(occurrence).encode()
    ).hexdigest()
    return f"session-{digest[:24]}"


@dataclass(frozen=True)
class LongMemEvalTurn:
    role: str
    content: str


@dataclass(frozen=True)
class LongMemEvalSession:
    session_id: str
    observed_at: str
    turns: tuple[LongMemEvalTurn, ...]


@dataclass(frozen=True)
class LongMemEvalCase:
    source_id: str
    category: str
    question: str
    question_at: str
    sessions: tuple[LongMemEvalSession, ...]


def load_inputs(path: Path) -> tuple[str, tuple[LongMemEvalCase, ...]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LongMemEvalInputError(
            f"invalid LongMemEval paper inputs: {path}"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != "milai.dg11.paper-longmemeval-inputs.v1"
        or value.get("forbidden_label_fields_present") is not False
        or value.get("label_fields_accessed") is not False
        or value.get("paper_labels_opened") is not False
        or not isinstance(value.get("partition"), str)
        or not isinstance(value.get("cases"), list)
        or value.get("case_count") != len(value["cases"])
    ):
        raise LongMemEvalInputError("LongMemEval paper input envelope drifted")
    cases: list[LongMemEvalCase] = []
    for raw_case in value["cases"]:
        if not isinstance(raw_case, dict) or set(raw_case) != {
            "category",
            "question",
            "question_date",
            "sessions",
            "source_id",
        }:
            raise LongMemEvalInputError("LongMemEval case fields drifted")
        raw_sessions = raw_case["sessions"]
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raise LongMemEvalInputError("LongMemEval case has no sessions")
        sessions: list[LongMemEvalSession] = []
        for raw_session in raw_sessions:
            if not isinstance(raw_session, dict) or set(raw_session) != {
                "observed_at",
                "session_id",
                "turns",
            }:
                raise LongMemEvalInputError("LongMemEval session fields drifted")
            raw_turns = raw_session["turns"]
            if not isinstance(raw_turns, list) or not raw_turns:
                raise LongMemEvalInputError("LongMemEval session has no turns")
            turns: list[LongMemEvalTurn] = []
            for raw_turn in raw_turns:
                if (
                    not isinstance(raw_turn, dict)
                    or set(raw_turn) != {"content", "role"}
                    or raw_turn.get("role") not in {"user", "assistant"}
                    or not isinstance(raw_turn.get("content"), str)
                ):
                    raise LongMemEvalInputError("LongMemEval turn fields drifted")
                turns.append(
                    LongMemEvalTurn(str(raw_turn["role"]), raw_turn["content"])
                )
            sessions.append(
                LongMemEvalSession(
                    session_id=str(raw_session["session_id"]),
                    observed_at=str(raw_session["observed_at"]),
                    turns=tuple(turns),
                )
            )
        cases.append(
            LongMemEvalCase(
                source_id=str(raw_case["source_id"]),
                category=str(raw_case["category"]),
                question=str(raw_case["question"]),
                question_at=str(raw_case["question_date"]),
                sessions=tuple(sessions),
            )
        )
    if len({case.source_id for case in cases}) != len(cases):
        raise LongMemEvalInputError("LongMemEval input case IDs are not unique")
    source_ids = value.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or [case.source_id for case in cases] != source_ids
    ):
        raise LongMemEvalInputError("LongMemEval input order differs from its manifest")
    return str(value["partition"]), tuple(cases)


def labels_from_dataset(
    dataset: Path, source_ids: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Open the minimum scoring fields only; caller must pass the paper freeze gate."""

    try:
        rows = json.loads(dataset.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LongMemEvalInputError("LongMemEval label source is invalid") from exc
    if not isinstance(rows, list):
        raise LongMemEvalInputError("LongMemEval label source is not an array")
    selected = set(source_ids)
    labels: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("question_id") not in selected:
            continue
        source_id = str(row["question_id"])
        raw_answer = row.get("answer")
        if isinstance(raw_answer, str) and raw_answer.strip():
            answers = [raw_answer]
        elif isinstance(raw_answer, int) and not isinstance(raw_answer, bool):
            answers = [str(raw_answer)]
        elif (
            isinstance(raw_answer, list)
            and raw_answer
            and all(isinstance(item, str) and item.strip() for item in raw_answer)
        ):
            answers = list(raw_answer)
        else:
            raise LongMemEvalInputError("LongMemEval answer contract drifted")
        raw_answer_sessions = row.get("answer_session_ids")
        if not isinstance(raw_answer_sessions, list) or not all(
            isinstance(item, str) for item in raw_answer_sessions
        ):
            raise LongMemEvalInputError("LongMemEval evidence-label contract drifted")
        raw_history_sessions = row.get("haystack_session_ids")
        if not isinstance(raw_history_sessions, list) or not all(
            isinstance(item, str) for item in raw_history_sessions
        ):
            raise LongMemEvalInputError("LongMemEval history identity contract drifted")
        pseudonymized_answer_sessions = [
            pseudonymize_session_id(source_id, history_session, occurrence)
            for occurrence, history_session in enumerate(raw_history_sessions)
            if history_session in raw_answer_sessions
        ]
        if not pseudonymized_answer_sessions:
            raise LongMemEvalInputError(
                "LongMemEval evidence labels do not identify a history session"
            )
        labels[source_id] = {
            "answer_session_ids": pseudonymized_answer_sessions,
            "answers": answers,
        }
    if set(labels) != selected:
        raise LongMemEvalInputError("LongMemEval scoring labels are incomplete")
    return labels
