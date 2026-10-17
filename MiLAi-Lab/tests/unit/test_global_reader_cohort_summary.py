"""Family weighting and qualified source judgments cannot become misleading totals."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from summarize_global_reader_cohorts import summarize


def row(family, task, disposition="supported"):
    return {
        "family": family,
        "source_contract_task_pass": task,
        "disposition": disposition,
        "native_positive": False,
        "native_f1": 0,
        "reader_response_pass": bool(task),
        "contract_failure": False,
        "schema_or_generation_failure": False,
        "annotation": {
            "answer_target": "correct",
            "source_grounding": "supported_by_delivered_material",
            "citation_grounding": "adequate",
            "output_contract": "valid",
        },
    }


def test_more_rows_do_not_give_one_family_more_weight():
    result = summarize([row("large", True)] * 3 + [row("small", False)])
    assert result["source_eligible_cases"] == 4
    assert result["source_eligible_families"] == 2
    assert result["source_strata"]["supported"]["task_pass"] == 3
    assert result["source_family_macro_task_pass"] == 0.5
    assert result["native_positive_f1_with_missing_zero"] is None


def test_grounded_nonunique_answer_is_visible_without_becoming_a_scored_failure():
    item = row("ambiguous", None, "masked")
    item["annotation"]["answer_target"] = "ambiguous_or_qualified"
    result = summarize([item])
    assert result["grounded_cited_valid_qualified_responses"] == 1
    assert result["remaining_qualified_responses"] == 0
    assert result["source_strata"]["masked"]["task_pass"] is None
    assert result["source_eligible_cases"] == 0
    assert result["source_family_macro_task_pass"] is None
    assert result["unqualified_response_pass"] == 0
    assert result["contract_failures"] == 0
    assert summarize([])["native_positive_f1_with_missing_zero"] is None
