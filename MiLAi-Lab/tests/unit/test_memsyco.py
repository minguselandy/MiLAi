from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from milai_lab.datasets.memsyco import load_memsyco
from milai_lab.scorers.memsyco import (
    JUDGE_MAX_TOKENS,
    aggregate_track,
    judge_messages,
    judge_response_format,
    parse_judge,
)


def _row(track: str, case_id: str) -> dict[str, object]:
    rubrics = {
        "contextual_scope_control": {
            "expected_behavior": "boundary",
            "failure_behavior": "scope trap",
            "scope_conflict": "other audience",
            "scope_label": "audience",
            "acceptable_memory_use": ["private preference"],
            "scope_limits": ["respect others"],
            "overgeneralization_failure": "applies to others",
            "underuse_failure": "ignores private need",
        },
        "valid_memory_selection": {
            "expected_behavior": "use newer",
            "failure_behavior": "use older",
        },
        "personalized_memory_use": {
            "expected_behavior": "use preference",
            "correct_reason": "because preferred",
        },
    }
    items = {
        "contextual_scope_control": [
            {"content": "GOLD_MEMORY", "type": "preference", "status": "active"}
        ],
        "valid_memory_selection": [
            {"content": "GOLD_OLD", "type": "preference", "status": "outdated"},
            {"content": "GOLD_NEW", "type": "preference", "status": "current"},
        ],
        "personalized_memory_use": [
            {"content": "GOLD_MEMORY", "type": "preference", "status": "active"}
        ],
    }
    return {
        "id": case_id,
        "task": track,
        "dialogue": [
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "user", "content": "Earlier request"},
        ],
        "question": "Current question",
        "memory": {"policy": "GOLD_POLICY", "items": items[track]},
        "evaluation": {"reference_answer": "GOLD_ANSWER", "rubric": rubrics[track]},
        "metadata": {"subtype": "GOLD_SUBTYPE"},
    }


@pytest.mark.parametrize(
    "track",
    ["contextual_scope_control", "valid_memory_selection", "personalized_memory_use"],
)
def test_fixed_screen_input_excludes_gold_and_preserves_dialogue(
    tmp_path: Path, track: str
) -> None:
    source = tmp_path / "track.jsonl"
    source.write_text(
        json.dumps(_row(track, "screen-1"))
        + "\n"
        + json.dumps(_row(track, "confirmation-1"))
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "external_root": str(tmp_path),
        "source_commit": "test-commit",
        "source_files": [{"task": track, "relative_path": source.name}],
        "groups": {
            "screen": {"cases": [{"task": track, "case_id": "screen-1"}]},
            "confirmation": {"cases": [{"task": track, "case_id": "confirmation-1"}]},
        },
    }
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(manifest), encoding="utf-8")

    (case,) = load_memsyco(selection)
    assert case.case_id == "screen-1"
    assert [turn.role for turn in case.task.history] == ["assistant", "user"]
    assert [turn.content for turn in case.task.history] == ["Earlier answer", "Earlier request"]
    assert case.task.question == "Current question"
    assert "GOLD_" not in json.dumps(asdict(case.task))
    assert case.answer == "GOLD_ANSWER"
    assert case.metadata["memory"]["policy"] == "GOLD_POLICY"
    messages = judge_messages(case, "Candidate answer")
    payload = json.loads(messages[1]["content"])
    if track == "valid_memory_selection":
        assert payload["older_preference_memory"] == "GOLD_OLD"
        assert payload["newer_preference_memory"] == "GOLD_NEW"
    else:
        assert payload["preference_memory"][0]["content"] == "GOLD_MEMORY"
    assert payload["assistant_answer"] == "Candidate answer"


def test_native_judge_parse_and_aggregation() -> None:
    scope = parse_judge(
        "contextual_scope_control",
        '{"accuracy":1,"incorrectly_used_preference":1,"scope_pass":true,"brief_rationale":"scope"}',
    )
    assert scope["accuracy"] == 0
    assert scope["scope_pass"] is False
    assert scope["success"] is False
    assert scope["success_definition"] == "scope_pass"
    assert scope["format_error"] is False
    assert scope["judge_parse_ok"] is True
    assert scope["judge_warning"]

    valid = parse_judge(
        "valid_memory_selection",
        '```json\n{"uses_latest_preference":"yes","outdated_preference_contamination":"no","brief_rationale":"latest"}\n```',
    )
    assert valid["valid_selection_pass"] is True
    assert valid["judge_parse_ok"] is True
    inconsistent = parse_judge(
        "valid_memory_selection",
        '{"uses_latest_preference":0,"outdated_preference_contamination":1,"valid_selection_pass":true}',
    )
    assert inconsistent["valid_selection_pass"] is True  # upstream retains explicit flag

    personalized = parse_judge(
        "personalized_memory_use",
        '{"answer_accuracy":1,"preference_used":1,"memory_use_pass":true}',
    )
    assert personalized["memory_use_pass"] is True
    failed = parse_judge("personalized_memory_use", "truncated")
    assert failed["judge_parse_ok"] is False
    assert failed["success"] is None
    assert failed["format_error"] is True
    metrics = aggregate_track("personalized_memory_use", [personalized, failed, None])
    assert metrics["n_total"] == 3
    assert metrics["n_judged"] == 1
    assert metrics["n_unjudged"] == 2
    assert metrics["answer_accuracy_sum"] == 1
    assert metrics["correct_pref_use"] == 1.0
    assert JUDGE_MAX_TOKENS > 32
    schema = judge_response_format("personalized_memory_use")["json_schema"]["schema"]
    assert schema["required"] == [
        "answer_accuracy",
        "preference_used",
        "memory_use_pass",
        "brief_rationale",
    ]
