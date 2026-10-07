"""Evaluator-only native selection before method-outcome inspection."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from milai_lab.datasets.edit_benchmarks import halumem_time, halumem_users
from milai_lab.harness.artifact_io import read_json, write_json

CATEGORIES = (
    "ordinary_value",
    "condition_preservation",
    "scoped_override",
    "cancellation",
    "historical_correction",
    "uncertainty",
)


def tags(memory: dict[str, Any]) -> list[str]:
    """Lexical screening; final semantic labels require evaluator source review."""
    new = memory["memory_content"].lower()
    old = "\n".join(memory.get("original_memories", [])).lower()
    classified = ["ordinary_value"]
    condition = r"\b(if|unless|except|only when|provided that|on weekends|on weekdays)\b"
    if re.search(condition, new) and re.search(condition, old):
        classified.append("condition_preservation")
    if re.search(r"\b(only for|only during|for this|on weekends|on weekdays)\b", new):
        classified.append("scoped_override")
    if re.search(r"\b(no longer|cancel(?:led|ed)?|withdraw|retract|abandon|stopped)\b", new):
        classified.append("cancellation")
    if re.search(r"\b(previously|originally|in fact|actually|mistaken|incorrect)\b", new):
        classified.append("historical_correction")
    if re.search(r"\b(uncertain|unsure|might|possibly|tentative|not decided|not yet)\b", new):
        classified.append("uncertainty")
    return classified


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    settings = read_json(args.config)
    users = halumem_users(Path(settings["halumem"]["path"]), settings["halumem"]["users"])
    selected, available = [], []
    for user in users:
        opportunities = []
        ordered = sorted(
            enumerate(user["sessions"]),
            key=lambda item: (halumem_time(item[1]["start_time"]), item[0]),
        )
        for session_ordinal, session in ordered:
            if session.get("is_generated_qa_session", False):
                continue
            for memory_ordinal, memory in enumerate(session["memory_points"]):
                if memory["is_update"] != "True" or not memory.get("original_memories"):
                    continue
                opportunities.append(
                    {
                        "uuid": user["uuid"],
                        "session": session_ordinal,
                        "memory_ordinal": memory_ordinal,
                        "screening_categories": tags(memory),
                        "reference_update": memory,
                        "observed_dialogue": session["dialogue"],
                        "date": session["start_time"],
                        "semantic_classification": "PENDING_SOURCE_REVIEW",
                    }
                )
        chosen = []
        for category in CATEGORIES:
            item = next(
                (
                    row
                    for row in opportunities
                    if category in row["screening_categories"] and row not in chosen
                ),
                None,
            )
            if item is not None:
                chosen.append(item)
        chosen.extend(row for row in opportunities if row not in chosen)
        selected.extend(chosen[:8])
        available.append(
            {
                "uuid": user["uuid"],
                "native_updates": len(opportunities),
                "screening_available": {
                    category: sum(category in row["screening_categories"] for row in opportunities)
                    for category in CATEGORIES
                },
            }
        )
    write_json(
        args.output,
        {
            "version": "milai-edit-native-selection-v1",
            "per_user_limit": 8,
            "selection_basis": "prewritten lexical screening and chronology; "
            "before mechanism scores",
            "semantic_labels": "screening only until actual source review",
            "users": available,
            "selected": selected,
            "gold_initialization": False,
            "runtime_delivery": False,
        },
    )
    print(json.dumps({"selected": len(selected), "users": available}, ensure_ascii=False))


if __name__ == "__main__":
    main()
