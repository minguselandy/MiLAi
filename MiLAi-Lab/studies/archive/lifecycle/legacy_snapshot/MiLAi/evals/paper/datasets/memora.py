"""Label-free Memora inputs and deterministic post-freeze label loading."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file

TASKS = ("remembering", "reasoning", "recommending")
TASK_LABELS = {
    "remembering": "Remembering",
    "reasoning": "Reasoning",
    "recommending": "Recommending",
}
MINIMUM_SESSIONS_BY_PERIOD = {"weekly": 100, "monthly": 500, "quarterly": 1500}
FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "evaluation",
        "evaluation_answers",
        "evaluation_questions",
        "expected_answer",
        "forgetting_evidence",
        "memory_evidence",
        "operation",
        "operation_details",
        "share_memory",
        "session_type",
    }
)


class MemoraInputError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoraTurn:
    actor: str
    content: str


@dataclass(frozen=True)
class MemoraSession:
    observed_at: str
    session_id: str
    turns: tuple[MemoraTurn, ...]


@dataclass(frozen=True)
class MemoraCohort:
    cohort_id: str
    period: str
    persona: str
    sessions: tuple[MemoraSession, ...]


@dataclass(frozen=True)
class MemoraCase:
    case_id: str
    cohort_id: str
    question: str
    question_at: str
    source_question_id: str
    task: str


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoraInputError(f"invalid Memora JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MemoraInputError(f"expected Memora JSON object: {path}")
    return value


def _contains_forbidden(value: object) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_INPUT_KEYS.intersection(value)) or any(
            _contains_forbidden(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden(item) for item in value)
    return False


def pseudonym(namespace: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{namespace}\0{source_id}".encode()).hexdigest()
    return digest[:24]


def _turn(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MemoraInputError("Memora conversation turn is not an object")
    speaker = value.get("speaker")
    content = value.get("message")
    actor = {"ai_agent": "assistant", "user_agent": "user"}.get(str(speaker))
    if actor is None or not isinstance(content, str) or not content.strip():
        raise MemoraInputError("Memora conversation turn contract drifted")
    return {"actor": actor, "content": content}


def _session(path: Path, *, cohort_id: str) -> dict[str, Any]:
    value = _object(path)
    raw_id = value.get("session_id")
    date = value.get("date")
    conversation = value.get("conversation")
    if (
        not isinstance(raw_id, int)
        or isinstance(raw_id, bool)
        or not isinstance(date, str)
        or not isinstance(conversation, list)
        or not conversation
    ):
        raise MemoraInputError(f"Memora session contract drifted: {path}")
    return {
        "observed_at": date,
        "session_id": "session-" + pseudonym(cohort_id, str(raw_id)),
        "turns": [_turn(item) for item in conversation],
    }


def _question_rows(path: Path, *, period: str, persona: str) -> list[dict[str, str]]:
    value = _object(path)
    groups = value.get("questions")
    if value.get("persona") != persona or not isinstance(groups, dict):
        raise MemoraInputError("Memora evaluation-question root drifted")
    expected_per_task = 10 if period == "quarterly" else 5
    rows: list[dict[str, str]] = []
    for task in TASKS:
        questions = groups.get(task)
        if not isinstance(questions, list) or len(questions) != expected_per_task:
            raise MemoraInputError("Memora task denominator drifted")
        for row in questions:
            if not isinstance(row, dict):
                raise MemoraInputError("Memora question row is not an object")
            source_id = row.get("question_id")
            question = row.get("question")
            question_at = row.get("question_date")
            if (
                not isinstance(source_id, str)
                or not source_id.strip()
                or not isinstance(question, str)
                or not question.strip()
                or not isinstance(question_at, str)
                or not question_at.strip()
            ):
                raise MemoraInputError("Memora label-free question fields drifted")
            namespace = f"{period}:{persona}"
            rows.append(
                {
                    "case_id": "memora-" + pseudonym(namespace, source_id),
                    "cohort_id": namespace,
                    "question": question,
                    "question_at": question_at,
                    "source_question_id": source_id,
                    "task": TASK_LABELS[task],
                }
            )
    return rows


def build_label_free_inputs(
    *, data_root: Path, strata: tuple[tuple[str, str], ...]
) -> dict[str, Any]:
    if len(strata) != 3 or len(set(strata)) != 3:
        raise MemoraInputError("Memora paper strata must contain three unique cohorts")
    cohorts = []
    cases = []
    source_records = []
    for period, persona in strata:
        cohort_id = f"{period}:{persona}"
        cohort_root = data_root / period / persona
        conversation_paths = sorted((cohort_root / "conversations").glob("*.json"))
        expected_minimum = MINIMUM_SESSIONS_BY_PERIOD.get(period)
        if expected_minimum is None or len(conversation_paths) < expected_minimum:
            raise MemoraInputError("Memora conversation denominator drifted")
        question_paths = sorted(cohort_root.glob("evaluation_questions_*.json"))
        if len(question_paths) != 1:
            raise MemoraInputError("Memora evaluation-question file is ambiguous")
        sessions = [_session(path, cohort_id=cohort_id) for path in conversation_paths]
        cohorts.append(
            {
                "cohort_id": cohort_id,
                "period": period,
                "persona": persona,
                "sessions": sessions,
            }
        )
        cases.extend(_question_rows(question_paths[0], period=period, persona=persona))
        records = [
            {
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(data_root)),
                "sha256": sha256_file(path),
            }
            for path in [*conversation_paths, question_paths[0]]
        ]
        source_records.extend(records)
    canonical_records = b"".join(
        json.dumps(item, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for item in source_records
    )
    result: dict[str, Any] = {
        "case_count": len(cases),
        "cases": cases,
        "cohort_count": len(cohorts),
        "cohorts": cohorts,
        "forbidden_label_fields_present": False,
        "paper_labels_opened": False,
        "schema": "milai.dg11.paper-memora-inputs.v1",
        "scorer_label_values_accessed": False,
        "source_file_count": len(source_records),
        "source_inventory_sha256": hashlib.sha256(canonical_records).hexdigest(),
        "strata": [
            {"period": period, "persona": persona} for period, persona in strata
        ],
    }
    if len(cases) != 60 or len({row["case_id"] for row in cases}) != 60:
        raise MemoraInputError("Memora paper case denominator drifted")
    if _contains_forbidden(result):
        raise MemoraInputError("a scorer or simulator label leaked into Memora inputs")
    return result


def load_inputs(path: Path) -> tuple[tuple[MemoraCohort, ...], tuple[MemoraCase, ...]]:
    value = _object(path)
    test_data_only = value.get("test_data_only") is True
    expected_cases = value.get("case_count")
    expected_cohorts = value.get("cohort_count")
    if (
        value.get("schema") != "milai.dg11.paper-memora-inputs.v1"
        or value.get("paper_labels_opened") is not False
        or value.get("scorer_label_values_accessed") is not False
        or value.get("forbidden_label_fields_present") is not False
        or not isinstance(expected_cases, int)
        or isinstance(expected_cases, bool)
        or not isinstance(expected_cohorts, int)
        or isinstance(expected_cohorts, bool)
        or (not test_data_only and (expected_cases != 60 or expected_cohorts != 3))
        or (
            test_data_only and not (1 <= expected_cases <= 10 and expected_cohorts >= 1)
        )
        or not isinstance(value.get("cohorts"), list)
        or not isinstance(value.get("cases"), list)
        or _contains_forbidden(value)
    ):
        raise MemoraInputError("label-free Memora input artifact drifted")
    cohorts = []
    for raw in value["cohorts"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), list):
            raise MemoraInputError("Memora cohort contract drifted")
        sessions = []
        for session in raw["sessions"]:
            if not isinstance(session, dict) or not isinstance(
                session.get("turns"), list
            ):
                raise MemoraInputError("Memora session input drifted")
            sessions.append(
                MemoraSession(
                    observed_at=str(session["observed_at"]),
                    session_id=str(session["session_id"]),
                    turns=tuple(
                        MemoraTurn(
                            actor=str(turn["actor"]), content=str(turn["content"])
                        )
                        for turn in session["turns"]
                        if isinstance(turn, dict)
                    ),
                )
            )
        cohorts.append(
            MemoraCohort(
                cohort_id=str(raw["cohort_id"]),
                period=str(raw["period"]),
                persona=str(raw["persona"]),
                sessions=tuple(sessions),
            )
        )
    cases = tuple(
        MemoraCase(
            case_id=str(raw["case_id"]),
            cohort_id=str(raw["cohort_id"]),
            question=str(raw["question"]),
            question_at=str(raw["question_at"]),
            source_question_id=str(raw["source_question_id"]),
            task=str(raw["task"]),
        )
        for raw in value["cases"]
        if isinstance(raw, dict)
    )
    if (
        len(cases) != expected_cases
        or len(cohorts) != expected_cohorts
        or (
            not test_data_only
            and sum(len(cohort.sessions) for cohort in cohorts) < 2100
        )
    ):
        raise MemoraInputError("loaded Memora denominator drifted")
    return tuple(cohorts), cases
