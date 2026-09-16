from __future__ import annotations

from milai_lab.context_preflight import (
    classify_terminal_failure,
    material_turn_ordinals,
    select_outcome_blind_context_cases,
    selection_digest,
    semantic_terminal,
    source_session_instance_keys,
)


def _record(stratum: str, gold_count: int, ordinal: int, events: int) -> dict[str, object]:
    return {
        "question_id": f"{stratum}-{gold_count}-{ordinal}",
        "question_type": stratum,
        "question": f"forbidden selector payload {ordinal}",
        "answer": f"forbidden answer payload {ordinal}",
        "answer_session_ids": [f"gold-{index}" for index in range(gold_count)],
        "haystack_sessions": [[{} for _ in range(events)]],
    }


def test_selector_covers_length_tails_without_reading_outcomes() -> None:
    records = [
        _record(question_type, gold_count, ordinal, events)
        for question_type, gold_count in (("single", 1), ("multi", 2), ("multi", 3))
        for ordinal, events in enumerate((2, 4, 6, 8, 10))
    ]
    selected = select_outcome_blind_context_cases(records, case_count=9)

    assert len(selected) == 9
    for stratum in {item.stratum for item in selected}:
        lengths = [item.history_event_count for item in selected if item.stratum == stratum]
        assert min(lengths) == 2
        assert max(lengths) == 10
    first_digest = selection_digest(selected)
    for record in records:
        record["question"] = "changed question text"
        record["answer"] = "changed answer text"
    assert selection_digest(
        select_outcome_blind_context_cases(records, case_count=9)
    ) == first_digest


def test_failure_classes_do_not_turn_infrastructure_into_semantic_abstention() -> None:
    assert classify_terminal_failure(TimeoutError("timeout")) == "INFRASTRUCTURE"
    assert classify_terminal_failure(ValueError("wire drift")) == "PROTOCOL_IMPLEMENTATION"
    assert semantic_terminal("ABSTAINED") is True
    assert semantic_terminal("UNAVAILABLE") is False


def test_duplicate_source_session_ids_keep_deterministic_instance_identity() -> None:
    keys = source_session_instance_keys(("session-a", "session-a", "session-b"))

    assert keys == (
        "session-a\x1fduplicate-occurrence:0",
        "session-a\x1fduplicate-occurrence:1",
        "session-b",
    )
    assert len(set(keys)) == 3


def test_empty_turn_is_omitted_without_renumbering_material_turns() -> None:
    assert material_turn_ordinals(
        [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "material"},
            {"role": "user", "content": "later"},
        ]
    ) == (1, 2)
