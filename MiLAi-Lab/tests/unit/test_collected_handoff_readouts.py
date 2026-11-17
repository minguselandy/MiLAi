"""Preserve failed/partial first readouts instead of manufacturing valid answers."""

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize("status,eligible", [("UNKNOWN", True), ("RUNNING", False)])
def test_closed_unknown_is_not_retried_but_live_dispatch_is_not_reusable(status, eligible):
    case = {"family": "f", "event_id": "task/step-1", "response_event_id": "task"}
    action = {"id": "stop", "kind": "HANDOFF", "parameters": {}}
    wire = {"messages": [{"role": "user", "content": "entire original packet"}]}
    record = {**case, "status": status, "action": action, "answer": None,
              "reason": "producer_stopped_after_dispatch"}
    branch = {"action": action, "readout_request": wire}
    prior = [(Path("original/readout.json"), record, wire)]
    assert (reusable_readout(case, branch, prior) is not None) is eligible
    assert reusable_readout({**case, "response_event_id": "other"}, branch, prior) is None
    assert reusable_readout(case, {**branch, "readout_request": {"messages": []}}, prior) is None


def test_unknown_first_closes_all_identical_bindings_without_new_chat_or_false_quality(
    tmp_path, monkeypatch,
):
    import run_collected_handoff_readouts as runner
    from milai_lab.scorers.reviewed_task import reviewed_task_outcome

    def write(path, value):
        path.write_text(json.dumps(value))

    prepared, prior, output = (tmp_path / name for name in ["prepared", "prior", "output"])
    prepared.mkdir()
    prior.mkdir()
    config = tmp_path / "config.json"
    write(config, {"entrypoints": {"functional": {"host": {}, "capacity": {}}}})
    write(prepared / "run.json", {"status": "COMPLETED", "config": str(config)})
    wire = {"messages": [], "response_format": {},
            "chat_template_kwargs": {"enable_thinking": True}}
    action = {"id": "stop", "kind": "HANDOFF", "parameters": {}}
    write(prior / "request.json", wire)
    first = {"family": "f", "event_id": "task", "status": "UNKNOWN", "answer": None,
             "action": action, "request": str(prior / "request.json"),
             "reason": "producer_stopped_after_dispatch"}
    write(prior / "readout.json", first)
    write(prior / "run.json", {"status": "COMPLETED_WITH_FAILURES"})
    write(prior / "readout-paths.json", {"primary": {"task": str(prior / "readout.json")}})
    branches = [{"action": {**action, "id": name}, "policies": [name],
                 "readout_request": wire, "body_tokens": 10, "execution_result": {"ok": True}}
                for name in ["stop", "read"]]
    write(prepared / "cases.json", [{"family": "f", "event_id": "task/step-2",
        "response_event_id": "task", "request_id": "q", "choices": {"a": "stop", "b": "read"},
        "branches": branches}])
    generation = {"charged_tokens": 100, "known_tokens": 50, "unknown_usage": 1}
    budget = SimpleNamespace(state={"generation": dict(generation), "generation_requests": 1},
                             record_compute=lambda *_: None)
    monkeypatch.setattr(runner, "http_budget_scope", lambda _: nullcontext(budget))
    monkeypatch.setattr(runner, "HostCapacity", lambda _: None)
    monkeypatch.setattr(runner, "VLLMConfig", lambda **_: None)

    class Client:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def chat(self, *_, **__):
            pytest.fail("An unknown first must never trigger replacement generation")

    monkeypatch.setattr(runner, "VLLMClient", Client)
    monkeypatch.setattr("sys.argv", ["reader", str(prepared), str(output), "--compute-phase",
        "test", "--reuse-readouts", str(prior), "--share-identical-packets"])
    runner.main()
    result = json.loads((output / "run.json").read_text())
    assert result["closed_readouts"] == result["unknown_readouts"] == 2
    assert result["chat_invocations"] == result["failed_readouts"] == 0
    assert budget.state["generation"] == generation
    for i in range(2):
        record = json.loads((output / "case-000" / f"packet-{i}" / "readout.json").read_text())
        assert record["status"] == "UNKNOWN" and record["new_generation"] is False
        outcome = reviewed_task_outcome({"execution_status": record["status"],
                                         "primary_outcome": None}, None)
        assert outcome["primary_outcome"] is None and not outcome["quality_target_known"]
