from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from milai_lab.datasets.contextual import (
    load_longmemeval,
    load_personamem_v1,
    load_personamem_v2,
)
from milai_lab.scorers.contextual import longmemeval_judge_prompt, parse_judge, score_mcq


def _csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_v1_exclusive_prefix_and_shared_history_identity(tmp_path: Path) -> None:
    contexts = tmp_path / "contexts.jsonl"
    contexts.write_text(
        json.dumps(
            {
                "shared": [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "second"},
                    {"role": "user", "content": "future"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    questions = tmp_path / "questions.csv"
    base = {
        "persona_id": "p1",
        "question_type": "updated",
        "shared_context_id": "shared",
        "user_question_or_message": "Which?",
        "correct_answer": "(b)",
        "all_options": json.dumps(["(a) Alpha", "(b) Beta", "(c) Gamma", "(d) Delta"]),
    }
    _csv(
        questions,
        [
            {**base, "question_id": "q1", "end_index_in_shared_context": "2"},
            {**base, "question_id": "q2", "end_index_in_shared_context": "2"},
            {**base, "question_id": "q3", "end_index_in_shared_context": "3"},
        ],
    )
    first, second, later = load_personamem_v1(questions, contexts)
    assert [message.content for message in first.task.history] == ["first", "second"]
    assert first.task.options == ("(a) Alpha", "(b) Beta", "(c) Gamma", "(d) Delta")
    assert first.task.user_id == second.task.user_id == later.task.user_id
    assert first.task.history_id == second.task.history_id
    assert first.task.history_id != later.task.history_id
    assert first.task.history == second.task.history
    assert "correct_answer" not in asdict(first.task)
    assert score_mcq("<final_answer>(b)</final_answer>", first)["success"] is True
    assert score_mcq("(a) and (b)", first)["success"] is False


def test_v2_native_history_and_reproducible_options(tmp_path: Path) -> None:
    root = tmp_path / "v2"
    history_path = root / "data" / "chat_history_32k" / "p1.json"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        json.dumps(
            {
                "metadata": {"hidden": "scoring-only"},
                "chat_history": [
                    {"role": "user", "content": "old"},
                    {"role": "assistant", "content": "reply"},
                ],
            }
        ),
        encoding="utf-8",
    )
    row = {
        "persona_id": "p1",
        "chat_history_32k_link": "data/chat_history_32k/p1.json",
        "user_query": "{'role': 'user', 'content': 'Which preference?'}",
        "correct_answer": "Beta",
        "incorrect_answers": json.dumps(["Alpha", "Gamma", "Delta"]),
        "pref_type": "implicit",
        "who": "self",
        "updated": "False",
        "sensitive_info": "False",
    }
    rows = tmp_path / "rows.csv"
    _csv(rows, [row, {**row, "incorrect_answers": ""}])
    with rows.open("a", encoding="utf-8") as stream:
        stream.write("p1,data/chat_history_32k/p1.json\n")
    selected = {"val_text-000000", "val_text-000001"}
    first, second = load_personamem_v2(rows, root, "val_text", seed=17, case_ids=selected)
    repeated = load_personamem_v2(
        rows, root, "val_text", seed=17, case_ids={"val_text-000000"}
    )[0]
    other_split = load_personamem_v2(
        rows, root, "train_text", seed=17, case_ids={"train_text-000000"}
    )[0]
    assert first.task.history == second.task.history
    assert first.task.history is second.task.history
    assert first.task.history is not repeated.task.history
    assert first.task is not second.task
    assert first.task.history_id == second.task.history_id
    assert first.task.user_id == second.task.user_id
    assert first.task.history_id != other_split.task.history_id
    assert [message.role for message in first.task.history] == ["user", "assistant"]
    assert [message.content for message in first.task.history] == ["old", "reply"]
    assert first.task.question == "Which preference?"
    assert first.task.options == repeated.task.options
    assert set(first.task.options) == {"Alpha", "Beta", "Gamma", "Delta"}
    assert second.task.options == ("Beta",)
    assert "correct_answer" not in asdict(first.task)
    assert score_mcq(f"Final Answer: {first.answer}", first)["success"] is True
    assert score_mcq(str(first.answer), first)["format_error"] is True
    with pytest.raises(ValueError, match="row 2 is incomplete"):
        load_personamem_v2(rows, root, "val_text")
    with pytest.raises(ValueError, match="selected case IDs absent"):
        load_personamem_v2(rows, root, "val_text", case_ids={"val_text-000099"})


def test_longmemeval_keeps_dates_and_hides_oracle_labels(tmp_path: Path) -> None:
    path = tmp_path / "longmemeval_s_cleaned.json"
    path.write_text(
        json.dumps(
            [
                {
                    "question_id": "q_abs",
                    "question_type": "temporal-reasoning",
                    "question": "When?",
                    "question_date": "2025/01/03",
                    "answer": "The date is absent.",
                    "answer_session_ids": ["answer_session_1"],
                    "haystack_session_ids": ["answer_session_1", "other_session_2"],
                    "haystack_dates": ["2025/01/01", "2025/01/02"],
                    "haystack_sessions": [
                        [{"role": "user", "content": "first", "has_answer": True}],
                        [{"role": "assistant", "content": "second", "has_answer": False}],
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    case = load_longmemeval(path)[0]
    assert [message.date for message in case.task.history] == ["2025/01/01", "2025/01/02"]
    assert [message.role for message in case.task.history] == ["user", "assistant"]
    assert case.task.question_date == "2025/01/03"
    assert all("answer" not in message.session_id for message in case.task.history)
    assert all("_abs" not in message.event_id for message in case.task.history)
    assert "has_answer" not in asdict(case.task)
    assert "unanswerable question" in longmemeval_judge_prompt(case, "I cannot tell")
    assert parse_judge("yes") == {"success": True, "format_error": False, "judgment": True}
    assert parse_judge("maybe yes") == {"success": False, "format_error": True, "judgment": None}
