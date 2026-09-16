from __future__ import annotations

from pathlib import Path

from evals.dg21.baseline_freeze import run_baseline_freeze

_ROOT = Path(__file__).resolve().parents[1]


def test_dg21_s0_recomputes_frozen_denominators() -> None:
    baseline = run_baseline_freeze(_ROOT)

    assert baseline["status"] == "PASS_BASELINE_CONTRACT_FREEZE"
    assert baseline["hard_gate"]["passed"]
    assert len(baseline["raw_comparison_table"]) == 10
    assert len(baseline["case_classification"]["zero_gain_failures"]) == 6
    assert baseline["first_loss_distribution"] == {
        "CHANNEL": 4,
        "INTERPRETATION": 3,
    }
    assert baseline["rejection_binding_denominator"] == {
        "case_ids": [
            "2a1811e2",
            "2e6d26dc",
            "88432d0a",
            "9a707b82",
            "a89d7624",
            "gpt4_8279ba03",
        ],
        "total": 2130,
        "by_reason": {
            "ENTITY_INCOMPATIBLE": 130,
            "TEMPORAL_INCOMPATIBLE": 3,
            "TYPE_INCOMPATIBLE": 1997,
        },
        "type_incompatible_share": 0.937558685446,
    }
    assert baseline["formal_holdout"] == {
        "consumed": False,
        "overlap_count": 0,
        "denominator": 0,
        "case_ids_loaded": [],
    }


def test_dg21_s0_safe_comparison_omits_question_answer_and_content() -> None:
    baseline = run_baseline_freeze(_ROOT)

    prohibited = {"question", "answer", "content", "context", "gold"}
    assert all(
        not prohibited.intersection(record)
        for record in baseline["raw_comparison_table"]
    )
    assert all(
        record["question_or_content_stored"] is False
        for record in baseline["raw_comparison_table"]
    )
