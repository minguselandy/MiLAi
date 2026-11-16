"""Natural source evidence changes do not follow native polarity automatically."""

from copy import deepcopy

from join_global_reader_review import verdict
from summarize_source_selection_qa import citation_sensitivity, natural_pairs


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


def test_citation_supplement_preserves_primary_and_applies_to_each_shared_position():
    annotation = {"answer_target": "correct", "source_grounding": "supported_by_delivered_material",
                  "citation_grounding": "uncertain", "output_contract": "valid",
                  "exploratory_citation_grounding": "adequate",
                  "exploratory_supplement": "pre-mapping-route"}
    row = {**item("a", True, "supported", False), "case": "a", "response_id": "r1",
           "annotation": annotation, "native_f1": 1.0, **verdict(annotation, "supported")}
    original = deepcopy(row)
    for _ in range(2):  # Two methods sharing the same first response receive the same sensitivity.
        result = citation_sensitivity([row])
        assert result["all"]["source_strata"]["supported"]["task_pass"] == 1
        assert result["affected_positions"][0]["primary_task_pass"] is False
        assert result["affected_positions"][0]["alternative_task_pass"] is True
        assert row == original


def test_citation_supplement_cannot_override_mask_failure_or_unsupported_claim():
    for disposition, contract, grounding, expected in [
        ("masked", "valid", "supported_by_delivered_material", None),
        ("supported", "schema_or_generation_failure", "supported_by_delivered_material", False),
        ("supported", "valid", "unsupported_claim", False),
    ]:
        annotation = {"answer_target": "correct", "source_grounding": grounding,
                      "citation_grounding": "uncertain", "output_contract": contract,
                      "exploratory_citation_grounding": "adequate",
                      "exploratory_supplement": "pre-mapping-route"}
        row = {**item("a", True, disposition, expected), "case": "a", "response_id": "r1",
               "annotation": annotation, "native_f1": 1.0, **verdict(annotation, disposition)}
        result = citation_sensitivity([row])
        assert result["affected_positions"][0]["alternative_task_pass"] is expected
