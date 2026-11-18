"""Public benchmark task schema and deterministic MCQ option ordering."""

from __future__ import annotations

import random
from dataclasses import dataclass
from string import ascii_uppercase
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA

LONGMEMEVAL_S = "longmemeval_s_cleaned"
MEMORYAGENTBENCH_EVENTQA = "memoryagentbench_eventqa_full"


@dataclass(frozen=True)
class ReaderTask:
    source: str
    query: str
    options: tuple[str, ...] = ()
    invalid_reason: str | None = None

    def schema(self) -> dict[str, Any]:
        if self.source == PERSONA:
            fields: dict[str, Any] = {
                "selected_option": {"enum": list(ascii_uppercase[: len(self.options)])}
            }
        else:
            fields = {
                "answer": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            }
            if self.source == MUSIQUE:
                fields["answerable"] = {"type": "boolean"}
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }


def reader_task(
    source: str,
    query: str,
    task_id: int,
    annotation: dict[str, Any],
    option_seed: int,
) -> tuple[ReaderTask, frozenset[str]]:
    if source != PERSONA:
        return ReaderTask(source, query), frozenset()
    wrong, correct = annotation["incorrect_answers"], annotation.get("correct_answer")
    choices = [correct, *wrong] if isinstance(wrong, list) else []
    if not 2 <= len(choices) <= len(ascii_uppercase) or any(
        not isinstance(text, str) or not text.strip() for text in choices
    ):
        return ReaderTask(source, query, invalid_reason="invalid_options"), frozenset()
    rng = random.Random(option_seed + task_id)  # noqa: S311 -- fixed public option order
    rng.shuffle(choices)
    # Match the original evaluator even if an identical option text occurs twice.
    correct_letters = frozenset(
        letter
        for letter, text in zip(ascii_uppercase[: len(choices)], choices, strict=True)
        if text == correct
    )
    return ReaderTask(source, query, tuple(choices)), correct_letters
