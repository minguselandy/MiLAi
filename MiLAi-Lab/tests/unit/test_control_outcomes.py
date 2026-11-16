"""Support, coverage, input availability and execution are distinct causal observations."""
import copy
import json

import pytest
from jsonschema import ValidationError

from milai_lab.methods.control_calibration import four_axis_cases
from milai_lab.methods.control_outcomes import (
    case_from_readout,
    parse_outcome,
    primary_outcome,
    review_input,
    review_schema,
    unavailable_outcome,
)


def case():
    return {"question": "What limit and date?", "execution_status": "COMPLETED",
        "review_input_status": "complete", "answer": "1500 credits; July 1",
        "delivered_evidence": [{"label": "e0", "evidence": [
            {"role": "user", "content": "Limit 1500 credits, effective July 1."}]}]}


def review(**updates):
    result = {"material_sufficiency": "sufficient", "answer_support": "supported",
        "answer_completeness": "complete", "material_evidence_quotes": ["Limit 1500 credits"],
        "support_evidence_quotes": ["effective July 1"], "rationale": "Both requested fields."}
    result.update(updates)
    return json.dumps(result)


def test_complete_wrong_value_is_not_incomplete_and_material_can_still_be_sufficient():
    record = case()
    record["answer"] = "1900 credits; July 1"
    outcome = parse_outcome(review(answer_support="unsupported"), record)
    assert outcome["material_sufficiency"] == "sufficient"
    assert outcome["answer_completeness"] == "complete"
    assert outcome["primary_outcome"] is False


def test_quote_failure_masks_only_its_axis_and_known_incompleteness_stays_negative():
    outcome = parse_outcome(review(support_evidence_quotes=["Made-up quote"],
                                   answer_completeness="incomplete"), case())
    assert outcome["answer_support"] == "unknown"
    assert outcome["material_sufficiency"] == "sufficient"
    assert outcome["answer_completeness"] == "incomplete"
    assert outcome["primary_outcome"] is False
    outcome = parse_outcome(review(support_evidence_quotes=["Made-up quote"]), case())
    assert outcome["primary_outcome"] is None


def test_missing_capture_is_unknown_but_actual_empty_delivery_is_not():
    missing = {**case(), "review_input_status": "missing_delivery_capture",
               "delivered_evidence": None}
    assert unavailable_outcome(missing, "input_unavailable")["primary_outcome"] is None
    empty = {**case(), "delivered_evidence": []}
    outcome = parse_outcome(review(material_sufficiency="insufficient",
        answer_support="unsupported", material_evidence_quotes=[],
        support_evidence_quotes=[]), empty)
    assert outcome["primary_outcome"] is False
    assert unavailable_outcome(case(), "judge_failed")["primary_outcome"] is None


def test_failed_execution_is_observed_and_cannot_be_relabelled_by_the_judge():
    failed = {**case(), "execution_status": "FAILED", "answer": None}
    outcome = parse_outcome(review(), failed)
    assert outcome["material_sufficiency"] == "sufficient"
    assert outcome["answer_support"] == outcome["answer_completeness"] == "unknown"
    assert outcome["primary_outcome"] is False
    with pytest.raises(ValidationError, match="Additional properties"):
        parse_outcome(review(execution_status="COMPLETED"), failed)


def test_expected_labels_never_enter_single_candidate_review_input():
    original = {**case(), "expected": {"primary_outcome": True}, "group_id": "SECRET",
                "policy": "SECRET", "future_reference": "SECRET"}
    before = copy.deepcopy(original)
    assert "SECRET" not in json.dumps(review_input(original))
    assert "expected" not in review_input(original)
    assert original == before


def test_trailing_citation_and_paired_delimiters_require_the_actual_item():
    outcome = parse_outcome(review(support_evidence_quotes=['"effective July 1" [e0]']), case())
    assert outcome["primary_outcome"] is True
    assert parse_outcome(review(support_evidence_quotes=['"effective July 1" [e1]']), case())[
        "answer_support"] == "unknown"


def test_fixed_calibration_has_true_unavailable_cases_and_covers_all_four_axes():
    cases = four_axis_cases()
    assert len(cases) == len({c["sample_id"] for c in cases}) == 200
    unavailable = [c for c in cases if c["review_input_status"] != "complete"]
    assert len(unavailable) == 20
    for row in cases:
        expected = {**row["expected"], "review_input_status": row["review_input_status"]}
        assert primary_outcome(expected) is row["expected"]["primary_outcome"]
    assert sum(c["delivered_evidence"] == [] for c in cases) == 20


def test_response_format_is_not_execution_and_the_whole_first_text_is_retained():
    text = '1500 credits; July 1. Additional unsupported explanation.'
    wire = {"messages": [{"role": "system", "content": "Answer"}, {"role": "user",
        "content": json.dumps({"request": "What limit and date?", "memory": {"evidence": []}})}],
        "response_format": {"json_schema": {"schema": {"type": "object"}}}}
    response = {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
    result = case_from_readout("one", wire, response)
    assert result["execution_status"] == "COMPLETED" and result["answer"] == text
    assert result["output_format_status"] == "invalid"
    incomplete = copy.deepcopy(response)
    incomplete["choices"][0]["finish_reason"] = "length"
    assert case_from_readout("two", wire, incomplete)["execution_status"] == "FAILED"
    assert case_from_readout("three", None, response)["review_input_status"] != "complete"


def test_previous_review_contract_is_explicit_and_not_silently_reinterpreted():
    current = json.loads(review())
    previous = {({"material_evidence_quotes": "material_quotes",
                  "support_evidence_quotes": "answer_quotes"}).get(key, key): value
                for key, value in current.items()}
    assert parse_outcome(json.dumps(previous), case(), protocol="four_axes_v3")[
        "primary_outcome"] is True
    with pytest.raises(ValidationError):
        parse_outcome(json.dumps(previous), case(), protocol="four_axes_v4")


def test_bound_references_resolve_real_records_but_do_not_claim_entailment():
    record = case()
    payload = review_input(record, protocol="four_axes_v5")
    source = payload["delivered_evidence"][0]["evidence"][0]
    assert source["review_unit_id"] == "u0"
    assert source["source_record"] == record["delivered_evidence"][0]["evidence"][0]
    raw = {"material_sufficiency": "sufficient", "answer_support": "supported",
        "answer_completeness": "complete", "material_evidence_ids": ["u0"],
        "support_evidence_ids": ["u0"], "rationale": "One source establishes both fields."}
    outcome = parse_outcome(json.dumps(raw), record, protocol="four_axes_v5")
    assert outcome["primary_outcome"] is True
    assert outcome["evidence_validation"] == "program_bound_location_only_not_entailment"
    assert outcome["answer_support_source_records"][0]["content"] == source["source_record"][
        "content"]
    raw["support_evidence_ids"] = ["u99"]
    invalid = parse_outcome(json.dumps(raw), record, protocol="four_axes_v5")
    assert invalid["answer_support"] == "unknown"
    assert invalid["material_sufficiency"] == "sufficient"
    assert invalid["answer_completeness"] == "complete"
    assert "enum" in review_schema(record, "four_axes_v5")["properties"][
        "support_evidence_ids"]["items"]
    empty = {**record, "delivered_evidence": []}
    assert review_schema(empty, "four_axes_v5")["properties"]["support_evidence_ids"][
        "maxItems"] == 0
