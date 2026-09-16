from __future__ import annotations

from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_prompt_single_turn_dev_calibration as calibration


def test_partial_calibration_case_set_is_exact_frozen_dev_subset() -> None:
    plan, case_ids = calibration._load_plan(bfcl_contract.DEFAULT_OUTPUT)

    assert len(case_ids) == 122
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids).issubset(plan["split"]["dev_case_ids"])
    assert all(
        not item.startswith(("bfcl_v4:simple_java_", "bfcl_v4:simple_javascript_"))
        for item in case_ids
    )
    assert all("multi_turn" not in item for item in case_ids)


def test_category_aggregates_keep_argument_and_no_call_denominators_separate() -> None:
    records = [
        {
            "category": "simple_python",
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "latency_ms": 5.0,
            "answer_record": {
                "official_checker_valid": True,
                "tool_selection_correct": True,
                "argument_correctness": True,
                "no_call_correct": None,
                "invalid_tool_call": False,
            },
        },
        {
            "category": "irrelevance",
            "usage": {"input_tokens": 8, "output_tokens": 1},
            "latency_ms": 3.0,
            "answer_record": {
                "official_checker_valid": True,
                "tool_selection_correct": True,
                "argument_correctness": None,
                "no_call_correct": True,
                "invalid_tool_call": False,
            },
        },
    ]

    result = calibration._category_aggregates(records)

    assert result["simple_python"]["argument_correctness_accuracy"] == 1.0
    assert result["simple_python"]["no_call_accuracy"] is None
    assert result["irrelevance"]["argument_correctness_accuracy"] is None
    assert result["irrelevance"]["no_call_accuracy"] == 1.0
