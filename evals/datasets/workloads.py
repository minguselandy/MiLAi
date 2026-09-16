from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evals.datasets.text import retrieval_query, runtime_safe_text
from evals.harness import HistoryItem, WorkloadHistory, WorkloadQuestion


@dataclass(frozen=True, slots=True)
class DatasetMapping:
    dataset_id: str
    workload_id_field: str
    history_field: str
    question_id_field: str
    question_field: str
    answer_field: str


@dataclass(frozen=True, slots=True)
class MappedWorkload:
    history: WorkloadHistory
    questions: tuple[WorkloadQuestion, ...]


LONGMEMEVAL = DatasetMapping(
    "LONGMEMEVAL",
    "question_id",
    "haystack_sessions",
    "question_id",
    "question",
    "answer",
)
MEMORA = DatasetMapping(
    "MEMORA", "persona_id", "history", "question_id", "question", "answer"
)
BEAM = DatasetMapping(
    "BEAM", "history_id", "history", "question_id", "question", "answer"
)
HORIZON = DatasetMapping(
    "HORIZON", "case_id", "history", "case_id", "question", "answer"
)
CUPID = DatasetMapping("CUPID", "case_id", "history", "case_id", "question", "answer")


def _turns(value: object) -> list[tuple[str, str | None, dict[str, Any]]]:
    sessions = value if isinstance(value, list) else []
    result: list[tuple[str, str | None, dict[str, Any]]] = []
    for session_index, session in enumerate(sessions):
        session_id = f"session-{session_index}"
        session_observed_at: str | None = None
        turns: object = session
        if isinstance(session, dict):
            session_id = str(session.get("session_id", session_id))
            raw_observed_at = session.get("observed_at", session.get("timestamp"))
            if raw_observed_at is not None:
                session_observed_at = str(raw_observed_at)
            turns = session.get("turns", session.get("messages", []))
        if not isinstance(turns, list):
            continue
        for turn in turns:
            if isinstance(turn, dict):
                result.append((session_id, session_observed_at, turn))
    return result


def map_record(record: dict[str, Any], mapping: DatasetMapping) -> MappedWorkload:
    workload_id = str(record[mapping.workload_id_field])
    items = tuple(
        HistoryItem(
            item_id=str(turn.get("id", f"{workload_id}:{index}")),
            session_id=session_id,
            role=str(turn.get("role", "user")),  # type: ignore[arg-type]
            content=runtime_safe_text(str(turn["content"])),
            occurred_at=(
                str(turn["timestamp"])
                if turn.get("timestamp") is not None
                else session_observed_at
            ),
            metadata={"source_index": index},
        )
        for index, (session_id, session_observed_at, turn) in enumerate(
            _turns(record[mapping.history_field])
        )
    )
    answer = record.get(mapping.answer_field)
    answers = (
        tuple(str(value) for value in answer)
        if isinstance(answer, list)
        else ((str(answer),) if answer is not None else ())
    )
    history = WorkloadHistory(
        workload_id=workload_id,
        dataset_id=mapping.dataset_id,
        items=items,
        metadata={"mapping": mapping.dataset_id},
    )
    question = WorkloadQuestion(
        question_id=str(record[mapping.question_id_field]),
        workload_id=workload_id,
        query=retrieval_query(str(record[mapping.question_field]), mapping.dataset_id),
        expected_answers=answers,
    )
    return MappedWorkload(history=history, questions=(question,))
