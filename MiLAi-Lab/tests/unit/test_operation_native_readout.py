"""Repeated operation states retain native references and literal first answers."""
import copy

from score_operation_readout_native import native_event_input


def test_repeated_states_share_source_but_not_scoring_position_and_never_extract_answer():
    case = {"event_id": "paper/q/step-0", "family": "paper", "native_control": {
        "native_question_id": "native-q", "annotations": [{"answer": {"yes_no": True}}]}}
    branch = {"readout_status": "COMPLETED", "answer": "Yes, only under these conditions. [e0]",
              "answer_fields": {"answer": "WRONG_ALTERNATIVE"}}
    gold, prediction = native_event_input(case, branch)
    assert prediction["predicted_answer"] == branch["answer"]
    second = copy.deepcopy(case)
    second["event_id"] = "paper/q/step-4"
    other_gold, other_prediction = native_event_input(second, branch)
    assert set(gold) == set(other_gold) == {"paper"}
    assert gold["paper"]["qas"][0]["answers"] == other_gold["paper"]["qas"][0]["answers"]
    assert prediction["question_id"] != other_prediction["question_id"]
    branch["readout_status"] = "FAILED"
    assert native_event_input(case, branch)[1] is None
