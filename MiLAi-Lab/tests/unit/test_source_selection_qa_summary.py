"""Natural source evidence changes do not follow native polarity automatically."""

from summarize_source_selection_qa import natural_pairs


def item(question, native, disposition, success, qualified=False):
    return {"dataset": "musique", "question_id": question, "native_positive": native,
            "disposition": disposition, "family": question,
            "source_contract_task_pass": success, "source_qualified": qualified}


def test_native_negative_can_still_have_a_valid_source_answer():
    rows = [item("a", True, "supported", True), item("a", False, "supported", True)]
    result = natural_pairs(rows)
    assert result["native_positive_negative_pairs"] == 1
    assert result["source_supported_insufficient_pairs"] == 0


def test_source_pair_requires_success_on_both_and_keeps_qualifications():
    rows = [item("a", True, "supported", True, True),
            item("a", False, "pool_insufficient", False),
            item("b", True, "masked", None), item("b", False, "pool_insufficient", True)]
    result = natural_pairs(rows)
    assert result["native_positive_negative_pairs"] == 2
    assert result["source_supported_insufficient_pairs"] == 1
    assert result["unqualified_source_pairs"] == result["both_source_task_pass"] == 0
