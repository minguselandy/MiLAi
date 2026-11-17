"""Semantic review identity and unknown masks cannot inherit native span negatives."""
import copy

import pytest

from milai_lab.scorers.reviewed_task import (
    TaskReviewIndex,
    first_review_observation,
    reviewed_task_outcome,
)


def review(resolution=True, material="SUFFICIENT", grounding=True):
    return {"task_resolution": resolution, "material_status": material,
            "answer_grounding": grounding, "grade": "B_assistant_provisional",
            "review_note": "Delivered paragraph explicitly gives the unique named poem's author."}


def test_supported_direct_answer_can_differ_from_extra_native_witness_conjunction():
    native = {"execution_status": "COMPLETED", "primary_outcome": False,
              "native_answer_em": True, "reference_support": {"complete": False}}
    original = copy.deepcopy(native)
    outcome = reviewed_task_outcome(native, review())
    assert outcome["primary_outcome"] is True
    assert outcome["native_primary_outcome"] is False
    assert outcome["reference_support"]["complete"] is False
    assert outcome["task_review"]["grade"] == "B_assistant_provisional"
    assert native == original
    assert reviewed_task_outcome(native, None)["primary_outcome"] is None


def test_unknown_transport_and_ambiguous_review_never_become_known_quality():
    for status in ["UNKNOWN", "NOT_RUN"]:
        out = reviewed_task_outcome({"execution_status": status, "primary_outcome": False},
                                    review())
        assert out["primary_outcome"] is None and not out["quality_target_known"]
    out = reviewed_task_outcome({"execution_status": "COMPLETED", "primary_outcome": False},
                                review(None, "UNKNOWN", None))
    assert out["primary_outcome"] is None
    assert out["semantic_material_sufficiency"] is None
    failed = {"execution_status": "FAILED", "primary_outcome": False}
    assert reviewed_task_outcome(failed, None)["primary_outcome"] is False
    with pytest.raises(ValueError, match="execution failure"):
        reviewed_task_outcome(failed, review())
    with pytest.raises(ValueError, match="sufficient, supported"):
        reviewed_task_outcome({"execution_status": "COMPLETED", "primary_outcome": False},
                              review(True, "INSUFFICIENT", False))


def test_same_task_and_entire_wire_and_observed_first_are_required_without_hashing():
    case = {"family": "source", "event_id": "task/step-2", "response_event_id": "task"}
    wire = {"messages": [{"role": "user", "content": "entire packet"}], "max_tokens": 32}
    record = {"status": "COMPLETED", "answer": "Author", "answer_fields": {
        "answer": "Author", "explanation": "Provided text", "evidence": ["literal"]}}
    entry = {"family": "source", "response_event_id": "task", "wire": wire,
             "first_observation": first_review_observation(record), "review": review()}
    index = TaskReviewIndex({"schema": "reviewed_task_outcomes_v1", "entries": [entry]})
    assert index.find(case, wire, record) == review()
    assert index.find({**case, "event_id": "task/step-5"}, wire, record) == review()
    assert index.find({**case, "family": "another"}, wire, record) is None
    assert index.find({**case, "response_event_id": "another"}, wire, record) is None
    assert index.find(case, {**wire, "max_tokens": 33}, record) is None
    with pytest.raises(ValueError, match="different observed first"):
        index.find(case, wire, {**record, "answer": "a later response"})
    duplicate = copy.deepcopy(entry)
    duplicate["review"] = review(None, "UNKNOWN", None)
    conflict = TaskReviewIndex({"schema": "reviewed_task_outcomes_v1",
                               "entries": [entry, duplicate]})
    with pytest.raises(ValueError, match="explicit adjudication"):
        conflict.find(case, wire, record)
