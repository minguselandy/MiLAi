from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from milai_lab.datasets.stale import PROBE_KEYS, load_stale
from milai_lab.scorers.stale import (
    JUDGE_MAX_TOKENS,
    aggregate_native,
    judge_messages,
    judge_response_format,
    parse_judge,
    probe_judgments,
)


def test_fixed_scenario_preserves_full_shared_history_and_isolates_gold(tmp_path: Path) -> None:
    uid = "fixed-scenario"
    row = {
        "uid": uid,
        "type": "T1",
        "M_old": "GOLD_OLD",
        "M_new": "GOLD_NEW",
        "explanation": "GOLD_LOGIC",
        "relevant_session_index": [0, 1],
        "timestamps": ["2025-01-01", "2025-02-02"],
        "haystack_session": [
            [{"role": "assistant", "content": "First"}],
            [
                {"role": "user", "content": "Second"},
                {"role": "assistant", "content": "Third"},
            ],
        ],
        "probing_queries": {key: f"Question {index}" for index, key in enumerate(PROBE_KEYS, 1)},
    }
    data = tmp_path / "stale.json"
    data.write_text(json.dumps([row, {"uid": "other"}], indent=2), encoding="utf-8")
    manifest = {
        "external_root": str(tmp_path),
        "source_revision": "test-revision",
        "scenarios": [{"scenario_id": uid, "type": "T1", "probe_keys": list(PROBE_KEYS)}],
    }
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(manifest), encoding="utf-8")

    cases = load_stale(selection, data_path=data)
    assert len(cases) == 3
    assert len({case.task.history_id for case in cases}) == 1
    assert cases[0].task.history is cases[1].task.history is cases[2].task.history
    assert [turn.content for turn in cases[0].task.history] == ["First", "Second", "Third"]
    assert [turn.role for turn in cases[0].task.history] == ["assistant", "user", "assistant"]
    assert [turn.date for turn in cases[0].task.history] == [
        "2025-01-01",
        "2025-02-02",
        "2025-02-02",
    ]
    assert [case.task.question for case in cases] == ["Question 1", "Question 2", "Question 3"]
    assert all("GOLD_" not in json.dumps(asdict(case.task)) for case in cases)
    assert all(case.answer is None for case in cases)

    frozen = {case.case_id: f"Answer {index}" for index, case in enumerate(cases, 1)}
    messages = judge_messages(cases, frozen)
    assert messages[0]["role"] == "system"
    assert "GOLD_NEW" in messages[1]["content"]
    assert "Target Model Response 3: Answer 3" in messages[1]["content"]


def test_native_three_dimension_parse_and_denominators() -> None:
    raw = json.dumps(
        {
            "dim1_eval": {"reasoning": "old may be stale", "pass": True},
            "dim2_eval": {"reasoning": "accepted premise", "pass": False},
            "dim3_eval": {"reasoning": "new state used", "pass": True},
        }
    )
    parsed = parse_judge(f"```json\n{raw}\n```")
    assert parsed["judge_parse_ok"] is True
    scores = probe_judgments(parsed)
    assert [scores[key]["success"] for key in PROBE_KEYS] == [True, False, True]
    assert all(scores[key]["format_error"] is False for key in PROBE_KEYS)
    incomplete = parse_judge('{"dim1_eval":{"pass":true}}')
    assert incomplete["format_error"] is True
    assert probe_judgments(incomplete)["dim2_query"]["success"] is None
    summary = aggregate_native([parsed, incomplete, None])
    assert summary["dim1"] == {
        "correct": 2,
        "total": 3,
        "accuracy": 2 / 3,
        "judged": 2,
        "unjudged": 1,
    }
    assert summary["overall"]["total"] == 9
    assert summary["overall"]["unjudged"] == 5
    schema = judge_response_format()["json_schema"]["schema"]
    assert set(schema["required"]) == {"dim1_eval", "dim2_eval", "dim3_eval"}
    assert JUDGE_MAX_TOKENS > 32
