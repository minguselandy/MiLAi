from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "tools/run_product03_openworker_lme.py"
    spec = importlib.util.spec_from_file_location("product03_openworker_lme", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_history_events_preserve_all_material_turns_without_gold_answer() -> None:
    module = _module()
    record = {
        "question_id": "opened-case",
        "question": "What is the remembered value?",
        "answer": "GOLD-MUST-NOT-BE-SEEDED",
        "haystack_session_ids": ["session-a"],
        "haystack_dates": ["2026/09/01 (Tue) 12:30"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I observed value BLUE."},
                {"role": "assistant", "content": "I will remember that."},
            ]
        ],
    }

    events = module._history_events(record)

    assert len(events) == 2
    assert [event["speaker"] for event in events] == ["user", "assistant"]
    assert all(event["data_classification"] == "DEIDENTIFIED" for event in events)
    assert all(
        event["permission_snapshot"]["project_ids"] == ["orchid-release"]
        for event in events
    )
    assert "GOLD-MUST-NOT-BE-SEEDED" not in "\n".join(
        str(event["content"]) for event in events
    )
    assert events[0]["source_context"]["next_turn_id"] == events[1]["source_context"][
        "turn_id"
    ]
    assert events[1]["source_context"]["previous_turn_id"] == events[0][
        "source_context"
    ]["turn_id"]


def test_answer_match_is_case_and_whitespace_tolerant() -> None:
    module = _module()

    assert module._answer_matches("The plan is 500   Mbps.", "500 Mbps")
    assert not module._answer_matches("The plan is 50 Mbps.", "500 Mbps")


def test_answer_match_rejects_typed_insufficient_numeric_false_positive() -> None:
    module = _module()
    answer = (
        '{"answer":"UNKNOWN","memory_outcome":"MEMORY_INSUFFICIENT",'
        '"memory_used":false,"status":"MEMORY_INSUFFICIENT",'
        '"trace_id":"62f25e77-75cd-4b41-9c3b-ba56c568b121"}'
    )

    assert not module._answer_matches(answer, 3)


def test_answer_match_requires_reference_token_boundaries() -> None:
    module = _module()

    assert module._answer_matches("There are 3 items.", 3)
    assert not module._answer_matches("There are 13 items.", 3)
