"""Fixed answer fields, actual-wire sharing, and outcome-free annotation sampling."""
import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from milai_lab.runners.given_host_readout import SEPARATE_ANSWER_SCHEMA, separate_answer_fields
from prepare_utility_semantic_sample import select_semantic_states
from review_collected_operation_outcomes import teacher_input
from run_collected_handoff_readouts import parse_readout, reusable_readout


def test_fixed_fields_keep_actual_task_packet_known_evidence_and_original_wire():
    wire = {"model": "actual", "max_tokens": 100, "temperature": 1,
        "messages": [{"role": "system", "content": "Answer with evidence"},
                     {"role": "user", "content": json.dumps({"request": "question",
                         "memory": {"evidence": ["B"]}, "known_evidence": ["A"]})}],
        "response_format": {"type": "json_schema", "json_schema": {"schema": {}}}}
    before = copy.deepcopy(wire)
    formatted = separate_answer_fields(wire)
    assert wire == before and formatted["messages"][1] == wire["messages"][1]
    assert all(formatted[key] == wire[key] for key in ("model", "max_tokens", "temperature"))
    answer = {"answer": "Yes", "explanation": "Full qualification", "evidence": ["B"]}
    response = {"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(answer)}}]}
    result = parse_readout(response, SEPARATE_ANSWER_SCHEMA)
    assert result["answer"] == "Yes" and result["answer_fields"] == answer
    assert parse_readout(response)["status"] == "FAILED"  # Legacy schema remains strict.


def test_semantic_teacher_sees_full_returned_explanation_not_only_short_answer():
    fields = {"answer": "Yes", "explanation": "UNSUPPORTED_CLAIM", "evidence": []}
    case = {"question": "question", "native_control": {"annotations": []}, "branches": [{
        "readout_request": {"messages": [{}, {"content": json.dumps({
            "memory": {"evidence": []}, "known_evidence": []})}]},
        "readout_status": "COMPLETED", "answer": "Yes", "answer_fields": fields}]}
    payload, _ = teacher_input(case, 0)
    assert payload["candidates"][0]["answer"] == fields


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED"])
def test_identical_wire_sharing_is_opt_in_and_preserves_first_failure(status):
    case = {"family": "source", "event_id": "source/q/0"}
    wire = {"messages": [{"content": "same r K and actual packet"}]}
    record = {**case, "status": status, "action": {"id": "a"}}
    prior = [(Path("first.json"), record, wire)]
    branch = {"action": {"id": "b"}, "readout_request": wire}
    assert reusable_readout(case, branch, prior) is None
    assert reusable_readout(case, branch, prior, share_identical_packets=True) == prior[0][:2]
    assert reusable_readout({**case, "event_id": "another"}, branch, prior,
                             share_identical_packets=True) is None
    assert reusable_readout(case, {**branch, "readout_request": {"messages": []}}, prior,
                             share_identical_packets=True) is None


def fixture(count=40):
    cases, scores = [], []
    for i in range(count):
        actions = [{"id": "read", "kind": "READ", "parameters": {"index": 0}},
                   {"id": "stop", "kind": "HANDOFF", "parameters": {}}]
        event = f"source-{i // 4}/q/{i}"
        cases.append({"family": f"source-{i // 4}", "event_id": event,
                      "choices": {"learner": "read"},
                      "branches": [{"action": a} for a in actions]})
        scores.extend({"event_id": event, "action": a, "score_known": True,
                       "mean_logprob": -2. if a["id"] == "read" else -1.} for a in actions)
    return cases, scores


def test_sampling_uses_distinct_actual_states_and_declared_quotas_without_changing_cases():
    cases, scores = fixture()
    before = copy.deepcopy(cases)
    selected = select_semantic_states(cases, scores, 20, 3)
    assert selected == select_semantic_states(cases, scores, 20, 3)
    assert cases == before
    assert len({c["event_id"] for c, _ in selected}) == 20
    random_families = {c["family"] for c, reason in selected
                       if reason == "source_stratified_random"}
    assert len(random_families) == 10
    assert Counter(reason for _, reason in selected) == {
        "source_stratified_random": 10, "teacher_learner_disagreement": 5,
        "undercovered_binding_stratum_or_quota_shortfall": 5}


def test_unknown_teacher_scores_do_not_create_disagreement_or_block_random_annotations():
    cases, scores = fixture()
    for score in scores:
        score["score_known"] = False
    selected = select_semantic_states(cases, scores, 20, 3)
    assert len(selected) == 20
    assert "teacher_learner_disagreement" not in {reason for _, reason in selected}
