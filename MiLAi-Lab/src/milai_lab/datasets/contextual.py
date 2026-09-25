from __future__ import annotations

import ast
import csv
import hashlib
import json
import random
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    event_id: str
    role: str
    content: str
    session_id: str = ""
    date: str = ""


@dataclass(frozen=True, slots=True)
class TaskInput:
    user_id: str
    history_id: str
    history: tuple[HistoryMessage, ...]
    question: str
    question_date: str = ""
    options: tuple[str, ...] = ()
    task_conditions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    dataset: str
    split: str
    task: TaskInput
    answer: Any
    groups: dict[str, str]
    metadata: dict[str, Any]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _json_or_literal(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return ast.literal_eval(value)


def _role_content(message: dict[str, Any]) -> tuple[str, str]:
    role = message["role"]
    content = message["content"]
    if not isinstance(role, str) or not isinstance(content, str):
        raise ValueError("history message role/content must be strings")
    return role, content


def _messages(
    raw_messages: list[dict[str, Any]], *, prefix: str, session_id: str = ""
) -> tuple[HistoryMessage, ...]:
    messages: list[HistoryMessage] = []
    for index, raw in enumerate(raw_messages):
        role, content = _role_content(raw)
        messages.append(
            HistoryMessage(
                event_id=f"{prefix}-event-{index:06d}",
                role=role,
                content=content,
                session_id=session_id,
            )
        )
    return tuple(messages)


def _v1_contexts(path: Path) -> dict[str, list[dict[str, Any]]]:
    contexts: dict[str, list[dict[str, Any]]] = {}
    for record in _read_jsonl(path):
        if len(record) != 1:
            raise ValueError("PersonaMem-v1 shared context rows must have one key")
        key, value = next(iter(record.items()))
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("PersonaMem-v1 shared context must be a message list")
        contexts[str(key)] = value
    return contexts


def _v1_options(value: str) -> tuple[str, ...]:
    parsed = _json_or_literal(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("PersonaMem-v1 options must be a string list")
    return tuple(parsed)


def load_personamem_v1(questions_path: Path, contexts_path: Path) -> list[EvaluationCase]:
    contexts = _v1_contexts(contexts_path)
    source_id = hashlib.sha256(contexts_path.read_bytes()).hexdigest()[:20]
    cases: list[EvaluationCase] = []
    with questions_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            context_key = row["shared_context_id"]
            context = contexts[context_key]
            end = int(row["end_index_in_shared_context"])
            if end < 0 or end > len(context):
                raise ValueError("PersonaMem-v1 history boundary is outside shared context")
            context_id = hashlib.sha256(context_key.encode()).hexdigest()[:20]
            history_id = f"v1-{source_id}-{context_id}-{end:06d}"
            history = _messages(context[:end], prefix=history_id)
            options = _v1_options(row["all_options"])
            question = row["user_question_or_message"]
            case_id = row["question_id"]
            cases.append(
                EvaluationCase(
                    case_id=case_id,
                    dataset="personamem-v1",
                    split="benchmark",
                    task=TaskInput(
                        user_id=f"v1-user-{row['persona_id']}",
                        history_id=history_id,
                        history=history,
                        question=question,
                        options=options,
                    ),
                    answer=row["correct_answer"],
                    groups={"question_type": row.get("question_type", "")},
                    metadata={
                        "persona_id": row.get("persona_id", ""),
                        "shared_context_id": context_key,
                        "end_index_in_shared_context": end,
                        "groundtruth_info": row.get("groundtruth_info", ""),
                    },
                )
            )
    return cases


def _seed_for_v2(persona_id: object, question: str) -> int:
    # Upstream uses hash(f"{persona_id}_{question}") % 2**32; SHA-256 replaces
    # Python's process-randomized hash while retaining the same seed input.
    payload = f"{persona_id}_{question}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def _read_v2_history(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("chat_history")
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError("PersonaMem-v2 history must be a JSON message list")
    return raw


def load_personamem_v2(
    rows_path: Path,
    history_root: Path,
    split: str,
    seed: int = 20260923,
    case_ids: Collection[str] | None = None,
) -> list[EvaluationCase]:
    """Load native v2 rows and create reproducible, label-free MCQ choices."""
    if split not in {"train_text", "val_text", "benchmark_text"}:
        raise ValueError("split must be train_text, val_text, or benchmark_text")
    selected = set(case_ids) if case_ids is not None else None
    found: set[str] = set()
    cases: list[EvaluationCase] = []
    history_cache: dict[str, tuple[HistoryMessage, ...]] = {}
    with rows_path.open(newline="", encoding="utf-8") as stream:
        for row_ordinal, row in enumerate(csv.DictReader(stream)):
            case_id = f"{split}-{row_ordinal:06d}"
            if selected is not None and case_id not in selected:
                continue
            found.add(case_id)
            required = (
                "persona_id",
                "chat_history_32k_link",
                "user_query",
                "correct_answer",
                "incorrect_answers",
            )
            if any(not isinstance(row.get(field), str) for field in required):
                raise ValueError(f"PersonaMem-v2 {split} row {row_ordinal} is incomplete")
            query = _json_or_literal(row["user_query"])
            if not isinstance(query, dict) or not isinstance(query.get("content"), str):
                raise ValueError("PersonaMem-v2 user_query must contain string content")
            question = query["content"]
            path_value = row["chat_history_32k_link"]
            history_path = Path(path_value)
            if not history_path.is_absolute():
                history_path = history_root / history_path
            history_key = hashlib.sha256(path_value.encode()).hexdigest()[:20]
            history_id = f"v2-{split}-{history_key}"
            history = history_cache.get(history_id)
            if history is None:
                history = _messages(_read_v2_history(history_path), prefix=history_id)
                history_cache[history_id] = history
            # Upstream treats an empty distractor cell as no distractors.
            incorrect = (
                _json_or_literal(row["incorrect_answers"]) if row["incorrect_answers"] else []
            )
            if not isinstance(incorrect, list) or not all(
                isinstance(item, str) for item in incorrect
            ):
                raise ValueError("PersonaMem-v2 incorrect_answers must be a string list")
            options = [row["correct_answer"], *incorrect]
            stable_seed = seed ^ _seed_for_v2(row["persona_id"], question)
            random.Random(stable_seed).shuffle(options)  # noqa: S311 - reproducible option order
            correct_letters = [
                chr(65 + index)
                for index, value in enumerate(options)
                if value == row["correct_answer"]
            ]
            if not correct_letters:
                raise ValueError("PersonaMem-v2 correct answer was lost during option assembly")
            cases.append(
                EvaluationCase(
                    case_id=case_id,
                    dataset="personamem-v2",
                    split=split,
                    task=TaskInput(
                        user_id=f"v2-{split}-user-{row['persona_id']}",
                        history_id=history_id,
                        history=history,
                        question=question,
                        options=tuple(options),
                    ),
                    answer=correct_letters[0],
                    groups={
                        "pref_type": row.get("pref_type", ""),
                        "who": row.get("who", ""),
                        "updated": str(row.get("updated", "")),
                        "sensitive_info": str(row.get("sensitive_info", "")),
                    },
                    metadata={
                        "persona_id": row.get("persona_id", ""),
                        "correct_answer": row["correct_answer"],
                        "option_mapping": {chr(65 + i): value for i, value in enumerate(options)},
                        "source_row_ordinal": row_ordinal,
                    },
                )
            )
    if selected is not None and selected != found:
        missing = selected - found
        raise ValueError(f"PersonaMem-v2 selected case IDs absent from {split}: {missing}")
    return cases


def load_longmemeval(path: Path) -> list[EvaluationCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("LongMemEval input must be a JSON list")
    cases: list[EvaluationCase] = []
    for row_ordinal, row in enumerate(raw):
        sessions = row["haystack_sessions"]
        session_dates = row["haystack_dates"]
        if len(sessions) != len(session_dates) or len(sessions) != len(row["haystack_session_ids"]):
            raise ValueError("LongMemEval session/date/id lengths differ")
        history_messages: list[HistoryMessage] = []
        for session_ordinal, session in enumerate(sessions):
            date = str(session_dates[session_ordinal])
            for message_ordinal, message in enumerate(session):
                role, content = _role_content(message)
                history_messages.append(
                    HistoryMessage(
                        event_id=f"lme-event-{row_ordinal:06d}-{session_ordinal:04d}-{message_ordinal:04d}",
                        role=role,
                        content=content,
                        session_id=f"lme-session-{session_ordinal:04d}",
                        date=date,
                    )
                )
        question_id = row["question_id"]
        cases.append(
            EvaluationCase(
                case_id=question_id,
                dataset="longmemeval-s-cleaned",
                split="benchmark",
                task=TaskInput(
                    user_id=f"lme-user-{row_ordinal:06d}",
                    history_id=f"lme-history-{row_ordinal:06d}",
                    history=tuple(history_messages),
                    question=row["question"],
                    question_date=str(row["question_date"]),
                ),
                answer={
                    "answer": row["answer"],
                    "question_type": row["question_type"],
                    "question_id": question_id,
                },
                groups={"question_type": row["question_type"]},
                metadata={
                    "answer_session_ids": row.get("answer_session_ids", []),
                    "haystack_session_ids": row["haystack_session_ids"],
                    "source_row_ordinal": row_ordinal,
                    "abstention": "_abs" in question_id,
                },
            )
        )
    return cases
