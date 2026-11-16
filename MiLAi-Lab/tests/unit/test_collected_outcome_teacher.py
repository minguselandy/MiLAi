"""Teacher evidence belongs to each delivered candidate; failed outcomes stay unknown."""

import copy
import json

import pytest

from review_collected_operation_outcomes import RUBRIC, parse_review, teacher_input, teacher_rubric


def fixture():
    payload = {"question": "What code?", "offline_reference_annotations": [
        {"free_form_answer": "Cedar", "evidence": ["Cedar is the code."]}], "candidates": [
            {"candidate": "candidate-0", "answer_status": "COMPLETED", "answer": "Cedar",
             "delivered_evidence": [{"evidence": [{"content": "Cedar is the code."}]}]},
            {"candidate": "candidate-1", "answer_status": "FAILED", "answer": None,
             "delivered_evidence": []},
        ]}
    reviews = {"reviews": [
        {"candidate": "candidate-0", "material_status": "sufficient", "answer_status": "complete",
         "answer_support": "supported", "evidence_quotes": ["Cedar is the code."],
         "rationale": "Actual delivered code statement."},
        {"candidate": "candidate-1", "material_status": "insufficient",
         "answer_status": "incorrect", "answer_support": "unsupported", "evidence_quotes": [],
         "rationale": "Empty packet and no completed first answer."},
    ]}
    return payload, reviews


def test_failed_first_answer_is_unknown_while_material_judgment_is_retained():
    payload, reviews = fixture()
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][0]["answer_status"] == "complete"
    assert parsed["reviews"][1]["answer_status"] == "unknown"
    assert parsed["reviews"][1]["material_status"] == "insufficient"


def test_offline_reference_or_other_candidate_cannot_supply_a_delivered_quote():
    payload, reviews = fixture()
    reviews["reviews"][1].update(material_status="sufficient",
                                 evidence_quotes=["Cedar is the code."])
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][1]["material_status"] == "unknown"
    assert parsed["reviews"][0]["answer_status"] == "complete"
    assert parsed["masked_candidates"] == 1
    reviews["reviews"][1]["evidence_quotes"] = []
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][1]["material_status"] == "unknown"
    assert parsed["reviews"][0]["material_status"] == "sufficient"


def test_duplicate_missing_candidate_or_unsupported_completion_is_unresolved():
    payload, reviews = fixture()
    missing = copy.deepcopy(reviews)
    missing["reviews"][1] = missing["reviews"][0]
    with pytest.raises(ValueError, match="exactly once"):
        parse_review(json.dumps(missing), payload)
    reviews["reviews"][0]["answer_support"] = "qualified"
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][0]["answer_status"] == "unknown"
    assert parsed["reviews"][0]["material_status"] == "sufficient"


def test_teacher_sees_rotated_material_and_answers_without_actions_or_policy_names():
    payload, _ = fixture()
    branches = [{"action": {"id": f"read-{i}"}, "policies": [f"policy-{i}"],
        "answer": c["answer"], "readout_status": c["answer_status"],
        "readout_request": {"messages": [{"role": "system", "content": "Host system"},
            {"role": "user", "content": json.dumps({"memory": {
                "evidence": c["delivered_evidence"]}})}]}}
        for i, c in enumerate(payload["candidates"])]
    case = {"question": payload["question"], "branches": branches,
        "native_control": {"annotations": [{"answer": {"free_form_answer": "Cedar"}}]}}
    actual, bindings = teacher_input(case, 1)
    assert actual["candidates"][0]["answer"] is None
    assert bindings["candidate-0"] is branches[1]
    assert "policies" not in json.dumps(actual) and "action" not in json.dumps(actual)
    assert actual["offline_reference_annotations"] == [{"free_form_answer": "Cedar"}]


def test_actual_item_citation_suffix_is_not_treated_as_invented_source_prose():
    payload, reviews = fixture()
    payload["candidates"][0]["delivered_evidence"][0]["label"] = "e0"
    reviews["reviews"][0]["evidence_quotes"] = ["Cedar is the code. [e0]"]
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][0]["answer_status"] == "complete"
    assert parsed["reviews"][0]["evidence_quotes"] == ["Cedar is the code. [e0]"]
    reviews["reviews"][0]["evidence_quotes"] = ["Cedar is the code. [e1]"]
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][0]["material_status"] == "unknown"


def test_explicit_prior_item_can_support_an_empty_new_packet_but_not_another_candidate():
    payload, reviews = fixture()
    original = payload["candidates"][0].pop("delivered_evidence")
    payload["candidates"][0].update(known_evidence=original, delivered_evidence=[])
    reviews["reviews"][1].update(material_status="sufficient",
                                 evidence_quotes=["Cedar is the code."])
    parsed = parse_review(json.dumps(reviews), payload)
    assert parsed["reviews"][0]["answer_status"] == "complete"
    assert parsed["reviews"][0]["material_status"] == "sufficient"
    assert parsed["reviews"][1]["material_status"] == "unknown"
    assert parsed["reviews"][1]["answer_status"] == "unknown"


def test_only_explicit_known_items_change_teacher_context_and_cold_rubric_is_unchanged():
    known = [{"label": "e0", "evidence": [{"role": "user", "content": "Cedar is the code."}]}]
    wire = {"memory": {"evidence": []}, "known_evidence": known}
    branch = {"readout_request": {"messages": [{}, {"content": json.dumps(wire)}]},
              "readout_status": "COMPLETED", "answer": "Cedar"}
    case = {"question": "What code?", "branches": [branch],
            "native_control": {"annotations": [{"answer": {"free_form_answer": "Cedar"}}]}}
    payload, _ = teacher_input(case, 0)
    assert payload["candidates"][0]["known_evidence"] == known
    assert payload["candidates"][0]["delivered_evidence"] == []
    assert teacher_rubric(payload) != RUBRIC
    wire["known_evidence"] = []
    branch["readout_request"]["messages"][1]["content"] = json.dumps(wire)
    cold, _ = teacher_input(case, 0)
    assert "known_evidence" not in cold["candidates"][0]
    assert teacher_rubric(cold) == RUBRIC
