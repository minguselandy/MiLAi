"""Preserve failed/partial first readouts instead of manufacturing valid answers."""

from pathlib import Path

import pytest

from run_collected_handoff_readouts import parse_readout, reusable_readout


@pytest.mark.parametrize(
    "finish,body,status",
    [
        ("stop", '{"answer":"answer with qualification"}', "COMPLETED"),
        ("length", '{"answer":"apparently valid but truncated"}', "FAILED"),
        ("stop", '{"answer":42}', "FAILED"),
        ("stop", "not JSON", "FAILED"),
    ],
)
def test_first_output_status_is_not_repaired(finish, body, status):
    response = {"choices": [{"finish_reason": finish, "message": {"content": body}}]}
    result = parse_readout(response)
    assert result["status"] == status
    assert (result["answer"] is None) == (status == "FAILED")
    assert response["choices"][0]["message"]["content"] == body


def test_reuse_keeps_failed_first_result_and_requires_same_full_wire_and_action():
    case = {"family": "f", "event_id": "f/q/1"}
    action = {"id": "read", "kind": "READ", "parameters": {"index": 3}}
    wire = {"messages": [{"role": "user", "content": "actual packet"}], "max_tokens": 100}
    record = {**case, "status": "FAILED", "action": action, "answer": None, "reason": "length"}
    path = Path("closed/readout.json")
    prior = [(path, record, wire)]
    branch = {"action": action, "readout_request": wire}
    assert reusable_readout(case, branch, prior) == (path, record)
    assert (
        reusable_readout(case, {**branch, "readout_request": {**wire, "max_tokens": 200}}, prior)
        is None
    )
    assert (
        reusable_readout(case, {**branch, "action": {**action, "parameters": {"index": 4}}}, prior)
        is None
    )
    assert reusable_readout({**case, "event_id": "f/q/2"}, branch, prior) is None


def test_branch_analysis_identity_can_share_the_same_declared_task_first_without_retry():
    action = {"id": "plain_stop", "kind": "HANDOFF", "parameters": {}}
    wire = {"messages": [{"role": "user", "content": "same actual task and packet"}]}
    record = {"family": "f", "event_id": "original-task", "status": "FAILED",
              "action": {**action, "id": "original-policy"}, "reason": "length"}
    path = Path("first/readout.json")
    prior = [(path, record, wire)]
    case = {"family": "f", "event_id": "original-task/step-3/h0",
            "response_event_id": "original-task"}
    branch = {"action": action, "readout_request": wire}
    assert reusable_readout(case, branch, prior, share_identical_packets=True) == (path, record)
    assert reusable_readout(case, branch, prior) is None
    assert reusable_readout({**case, "family": "other"}, branch, prior,
                            share_identical_packets=True) is None
    assert reusable_readout(case, {**branch, "readout_request": {"messages": []}}, prior,
                            share_identical_packets=True) is None
