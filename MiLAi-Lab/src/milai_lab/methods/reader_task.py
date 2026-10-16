"""Question-only task classification, separate from evidence nomination."""

from __future__ import annotations

import json
from typing import Any


def task_request(question: str, date: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    schema = {
        "title": "reader_task_v1",
        "type": "object",
        "additionalProperties": False,
        "properties": {"task": {"enum": ["lookup", "range"]}},
        "required": ["task"],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Classify the evidence task asked by the original question; do not answer it. "
                "lookup obtains or compares specified facts, including a reported quantity or "
                "the time between two named events. range enumerates, filters, counts or sums "
                "members/events over a requested set of records, where omitted members can change "
                "the result. Classify the requested operation, independent of whether currently "
                "retrieved evidence would fit or already contain an answer. Return the schema."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "date": date, "response_schema": schema},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]
    return messages, schema
