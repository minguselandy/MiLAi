from __future__ import annotations

from collections import Counter

import pytest

from evals.benchmark import dg11_holdout
from evals.benchmark.dg11_holdout_context_worker import (
    CHECKPOINT_SCHEMA,
    _resume_records,
)


def _row(source_id: str, category: str) -> dict[str, object]:
    return {
        "question_id": source_id,
        "question_type": category,
        "question": f"question {source_id}",
        "question_date": "2025/01/01 (Wed) 12:00",
        "haystack_session_ids": [f"session-{source_id}"],
        "haystack_dates": ["2024/12/31 (Tue) 12:00"],
        "haystack_sessions": [[{"role": "user", "content": "memory"}]],
        "answer": "must not enter label-free inputs",
        "answer_session_ids": [f"session-{source_id}"],
    }


def test_stratified_selection_is_deterministic_and_proportional() -> None:
    rows = [
        _row(f"unused-{index:03d}", "a" if index < 60 else "b")
        for index in range(120)
    ]
    first_ids, first_allocation = dg11_holdout.stratified_source_ids(rows)
    second_ids, second_allocation = dg11_holdout.stratified_source_ids(rows)
    assert first_ids == second_ids
    assert first_allocation == second_allocation == {"a": 50, "b": 50}
    assert len(first_ids) == len(set(first_ids)) == 100
    assert not set(first_ids).intersection(dg11_holdout.consumed_source_ids())


def test_label_free_inputs_excludes_all_gold_fields() -> None:
    rows = [_row(f"unused-{index:03d}", "a") for index in range(100)]
    source_ids = tuple(str(row["question_id"]) for row in rows)
    payload = dg11_holdout.label_free_inputs(rows, source_ids)
    encoded = dg11_holdout.canonical(payload)
    assert payload["label_fields_present"] is False
    assert b'"answer"' not in encoded
    assert b'"answer_session_ids"' not in encoded
    assert b'"gold_answers"' not in encoded


def test_four_arm_schedule_is_a_balanced_cyclic_latin_square() -> None:
    schedules = [dg11_holdout.schedule(index) for index in range(100)]
    assert all(set(schedule) == set(dg11_holdout.ARMS) for schedule in schedules)
    for position in range(4):
        assert Counter(schedule[position] for schedule in schedules) == {
            arm: 25 for arm in dg11_holdout.ARMS
        }


def test_generation_seed_is_independent_of_run_id() -> None:
    assert dg11_holdout.generation_id(7, "MILAI_DG11_CURRENT") == (
        "dg11-sealed-holdout-v1-008-milai_dg11_current"
    )


def test_scoring_requires_and_aggregates_exact_four_hundred_records() -> None:
    categories = (
        "single-session-assistant",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
    )
    records = []
    labels = {}
    for case_index in range(100):
        source_id = f"case-{case_index:03d}"
        labels[source_id] = ["correct"]
        for arm in dg11_holdout.ARMS:
            records.append(
                {
                    "source_id": source_id,
                    "case_id": f"longmemeval:{source_id}",
                    "category": categories[case_index % len(categories)],
                    "arm": arm,
                    "answer": (
                        "correct"
                        if arm == "MILAI_DG11_CURRENT"
                        or (arm == "MILAI_DG10_FROZEN" and case_index % 2 == 0)
                        else "wrong"
                    ),
                    "prompt_tokens": 100,
                }
            )
    scored = dg11_holdout.score_records(records, labels)
    assert scored["arms"]["MILAI_DG11_CURRENT"]["scorer_v1"] == {
        "case_count": 100,
        "exact_match_mean": 1,
        "normalized_f1_mean": 1.0,
        "prompt_tokens_mean": 100,
    }
    paired = scored["paired"]["scorer_v1"]
    assert paired["dg11_minus_dg10_f1_mean"] == 0.5
    assert paired["bootstrap"]["lower95"] > 0


def test_context_checkpoint_resumes_only_matching_unique_source_ids() -> None:
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "identity": "current",
        "input_sha256": "a" * 64,
        "records": [{"source_id": "a", "context": {}, "trace": {}}],
    }

    records = _resume_records(
        payload,
        identity="current",
        input_sha256="a" * 64,
        expected_source_ids={"a", "b"},
    )

    assert set(records) == {"a"}


def test_context_checkpoint_rejects_identity_or_source_drift() -> None:
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "identity": "current",
        "input_sha256": "a" * 64,
        "records": [{"source_id": "unexpected"}],
    }

    with pytest.raises(dg11_holdout.HoldoutError, match="source IDs drifted"):
        _resume_records(
            payload,
            identity="current",
            input_sha256="a" * 64,
            expected_source_ids={"a"},
        )
