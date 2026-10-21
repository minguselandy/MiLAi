"""Resume real Store and executor snapshots without replaying already executed operations."""
import json
import sys
from pathlib import Path

import httpx
import pytest
from test_given_retrieval import no_http, prepared_given, source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import message


def captured_after(directory, kind):
    return next(path for path in directory.glob("*/steps/*")
                if read_json(path / "call.json")["initial_observation"]["last_result"][
                    "action"]["kind"] == kind)


@pytest.mark.parametrize("after", ["SEARCH", "READ"])
@pytest.mark.parametrize("delivery_selection", [False, True])
def test_post_operation_store_materials_actions_and_allowance_resume_without_prefix_execution(
    tmp_path, monkeypatch, after, delivery_selection,
):
    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "max_control_steps": 6,
        "source_observation_tokens": 300, "delivery_selection": delivery_selection})
    snapshots = root / "frozen-retrieval-calls"
    monkeypatch.setattr(httpx.Client, "send", no_http)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code"}, retrieval_snapshots=snapshots,
        retrieval_step_snapshots=True)
    assert original["status"] == "COMPLETED", original.get("error")
    captured = captured_after(snapshots, after)
    call, checkpoint = read_json(captured / "call.json"), read_json(captured / "control.json")
    assert call["status"] == "ORIGINAL_COMPLETED" and call["control_step"] > 0
    assert call["read_allowance"]["reads_remaining"] < 8
    before = {p.relative_to(captured): p.read_bytes() for p in captured.rglob("*") if p.is_file()}
    handoff = next(a for a in call["initial_actions"] if a["kind"] == "HANDOFF"
                   and not a["parameters"])
    executed = []
    execute = EvidenceOperations.execute

    def record_execute(operations, action, state):
        executed.append(action)
        return execute(operations, action, state)

    monkeypatch.setattr(EvidenceOperations, "execute", record_execute)
    result = replay_call(captured, tmp_path / "branch", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": handoff,
                                                   "continuation_steps": 0})
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["frozen_request_and_allowance_equal"]
    assert result["frozen_initial_observation_and_actions_equal"]
    assert result["frozen_start_step"] == call["control_step"]
    assert executed == []
    accounting = read_json(tmp_path / "branch/replay.json")
    assert accounting["prefix_operations_reexecuted"] == 0
    assert accounting["restored_prefix_usage"]["operations"] == call["control_step"]
    assert result["retrieval_result"]["usage"]["control_steps"] == call["control_step"] + 1
    assert bool(result["retrieval_result"]["evidence"]) == bool(checkpoint["operations"]["opened"])
    assert result["budget_before"]["generation"] == result["budget_after"]["generation"]
    assert {p.relative_to(captured): p.read_bytes()
            for p in captured.rglob("*") if p.is_file()} == before

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import prepare_view_feedback_branches

    write_json(root / "driver.json", {"status": "COMPLETED", "source_version": "mechanical"})
    write_json(root / "fixture.json", {"histories": [{"id": "bank", "continuous": True,
        "source_group": "family", "split": "train", "requests": [{"id": "q"}]}]})
    proposal = tmp_path / "proposal"
    monkeypatch.setattr(sys, "argv", ["prepare", str(root), "--groups", "family",
        "--per-group", "100", "--include-control-steps", "--output", str(proposal)])
    prepare_view_feedback_branches.main()
    selected = read_json(proposal / "selection.json")["selected"]
    assert any(row["control_step"] > 0 for row in selected)
    assert len({row["capture"] for row in selected}) == len(selected)
    raw = read_jsonl(proposal / "raw-selected-states.jsonl")
    assert len(raw) == len(selected) and not any(row["gold"] for row in raw)
    assert any(row["metadata"]["control_step"] > 0 for row in raw)
    assert all("control_checkpoint" not in row["state"] for row in raw)


@pytest.mark.parametrize("delivery_selection", [False, True])
def test_generated_view_and_consumed_generation_allowance_are_restored_not_regenerated(
    tmp_path, monkeypatch, delivery_selection,
):
    root = prepared_given(tmp_path, policy={"policy": "rules", "reads": 0,
        "max_control_steps": 6, "source_observation_tokens": 300,
        "delivery_selection": delivery_selection})

    def reply(wire, _number):
        payload = json.loads(wire["messages"][-1]["content"])
        return {"role": "assistant", "content": json.dumps({"scope": "Recorded interpretation",
            "nodes": [{"id": "n0", "text": "The code is 9999.", "kind": "reported",
                       "evidence": [payload["sources"][0]["id"]]}],
            "rules": [], "remove": [], "remove_rules": [], "unresolved": []})}

    wires = scripted(monkeypatch, reply, native=True)
    snapshots = root / "frozen-retrieval-calls"
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code"}, retrieval_snapshots=snapshots,
        retrieval_step_snapshots=True)
    assert original["status"] == "COMPLETED", original.get("error")
    assert len(wires) == 1
    captured = captured_after(snapshots, "REFRESH_VIEW")
    call = read_json(captured / "call.json")
    assert call["generation_calls_before"] == 1
    assert "9999" in json.dumps(call["initial_observation"])
    monkeypatch.setattr(httpx.Client, "send", no_http)
    handoff = next(a for a in call["initial_actions"] if a["kind"] == "HANDOFF"
                   and not a["parameters"])
    result = replay_call(captured, tmp_path / "branch", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": handoff,
                                                   "continuation_steps": 0})
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["frozen_initial_observation_and_actions_equal"]
    assert result["retrieval_result"]["evidence"] == original["retrieval_result"]["evidence"]
    assert "9999" in json.dumps(result["retrieval_result"])
    assert result["budget_before"]["generation_requests"] == result["budget_after"][
        "generation_requests"] == 1

    read = next(a for a in call["initial_actions"] if a["kind"] == "READ"
                and "observed_source" in a["parameters"]
                and not a["parameters"].get("observe_only"))
    opened = replay_call(captured, tmp_path / "read-original", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": read,
                                                   "continuation_steps": 0})
    assert opened["status"] == "COMPLETED", opened.get("error")
    assert opened["frozen_initial_observation_and_actions_equal"]
    # The inaccurate recorded View remains; the new branch adds an actual original body.
    assert "9999" in json.dumps(opened["retrieval_result"])
    assert "4312" in json.dumps(opened["retrieval_result"])
    assert opened["budget_before"]["generation_requests"] == opened["budget_after"][
        "generation_requests"] == 1


@pytest.mark.parametrize("continuation", [0, 1])
def test_post_search_read_branch_uses_absolute_budget_and_relative_intervention_window(
    tmp_path, monkeypatch, continuation,
):
    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "max_control_steps": 6,
        "source_observation_tokens": 300, "delivery_selection": True})
    snapshots = root / "frozen-retrieval-calls"
    monkeypatch.setattr(httpx.Client, "send", no_http)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code"}, retrieval_snapshots=snapshots,
        retrieval_step_snapshots=True)
    assert original["status"] == "COMPLETED", original.get("error")
    captured = captured_after(snapshots, "SEARCH")
    call = read_json(captured / "call.json")
    read = next(a for a in call["initial_actions"] if a["kind"] == "READ"
                and a["parameters"] == {"index": 0})
    executed = []
    execute = EvidenceOperations.execute

    def record_execute(operations, action, state):
        executed.append(action)
        return execute(operations, action, state)

    monkeypatch.setattr(EvidenceOperations, "execute", record_execute)
    result = replay_call(captured, tmp_path / "branch", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": read,
                                                   "continuation_steps": continuation})
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["frozen_initial_observation_and_actions_equal"]
    assert [action.kind for action in executed] == (
        ["READ", "SEARCH"] if continuation else ["READ"])
    assert "4312" in json.dumps(result["retrieval_result"])
    assert result["retrieval_result"]["usage"]["control_steps"] == (
        call["control_step"] + 2 + continuation)
    if continuation:
        assert executed[1].parameters["limit"] == 16  # The prior limit8 attempt is retained.


def test_known_evidence_is_restored_without_reopening_or_recharging_it(tmp_path, monkeypatch):
    from milai_lab.methods.intent_retrieval import IntentRetrievalMemory

    root = prepared_given(tmp_path)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    first = message(root, bank="bank", owner="alice", session="host", message_id="first",
        content="Find Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code"})
    snapshots = root / "frozen-retrieval-calls"
    request = {"query": "Verify Cedar code", "task_context": {"known_evidence_refs": [
        first["retrieval_result"]["evidence"][0]["ref"]]}}
    second = message(root, bank="bank", owner="alice", session="host", message_id="second",
        content="Verify Cedar code", given_retrieval_request=request,
        retrieval_snapshots=snapshots, retrieval_step_snapshots=True)
    assert second["status"] == "COMPLETED", second.get("error")
    captured = captured_after(snapshots, "SEARCH")
    call = read_json(captured / "call.json")
    assert call["initial_observation"]["task"]["known_evidence"]
    monkeypatch.setattr(IntentRetrievalMemory, "_known_materials", no_http)
    handoff = next(a for a in call["initial_actions"] if a["kind"] == "HANDOFF"
                   and not a["parameters"])
    result = replay_call(captured, tmp_path / "branch", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": handoff,
                                                   "continuation_steps": 0})
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["frozen_request_and_allowance_equal"]
    assert result["frozen_initial_observation_and_actions_equal"]
    assert result["retrieval_result"]["usage"]["known_reference_reads"] == 1


def test_post_step_branch_retains_original_complete_host_frame_for_readout(tmp_path, monkeypatch):
    from test_frozen_retrieval import native_request

    from milai_lab.runners.frozen_host_readout import (
        prepare_readout,
        run_readout,
        substitute_receipt,
    )

    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "max_control_steps": 6,
        "source_observation_tokens": 300, "delivery_selection": True})
    snapshots = root / "frozen-retrieval-calls"
    wires = scripted(monkeypatch, lambda wire, n:
        native_request({"query": "Cedar code"}) if n == 1 else
        {"role": "assistant", "content": "original answer" if n == 2 else "branch answer"},
        native=True)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        retrieval_snapshots=snapshots, retrieval_step_snapshots=True)
    assert original["status"] == "COMPLETED", original.get("error")
    captured = captured_after(snapshots, "SEARCH")
    call = read_json(captured / "call.json")
    frame = prepare_readout(captured)
    assert frame["status"] == "READY" and not frame["original_answer_loaded_as_input"]
    assert "original answer" not in json.dumps(frame["request"])
    read = next(a for a in call["initial_actions"] if a["kind"] == "READ"
                and a["parameters"] == {"index": 0})
    branch = tmp_path / "branch"
    result = replay_call(captured, branch, {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": read,
                                                   "continuation_steps": 0})
    assert result["status"] == "COMPLETED", result.get("error")
    expected = substitute_receipt(frame, result["messages"][0])
    readout = run_readout(captured, branch, branch / "host-readout", frame,
                          source_version="mechanical")
    assert readout["status"] == "COMPLETED" and readout["answer"] == "branch answer"
    assert len(wires) == 3 and wires[-1] == expected


@pytest.mark.parametrize("failure_kind", ["read", "policy"])
def test_closed_failed_original_keeps_its_pre_failure_decision_without_retrying_the_failure(
    tmp_path, monkeypatch, failure_kind,
):
    from milai_lab.methods.memory_control import FixedContextMemoryPolicy

    root = prepared_given(tmp_path)
    snapshots = root / "frozen-retrieval-calls"
    monkeypatch.setattr(httpx.Client, "send", no_http)
    execute = EvidenceOperations.execute
    choose = FixedContextMemoryPolicy.choose

    def fail_read(operations, action, state):
        if failure_kind == "read" and action.kind == "READ":
            raise RuntimeError("Original read failed")
        return execute(operations, action, state)

    def fail_policy(policy, state, actions):
        selected = choose(policy, state, actions)
        if failure_kind == "policy" and next(a for a in actions if a.id == selected).kind == "READ":
            raise RuntimeError("Original policy failed before READ")
        return selected

    monkeypatch.setattr(EvidenceOperations, "execute", fail_read)
    monkeypatch.setattr(FixedContextMemoryPolicy, "choose", fail_policy)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code"}, retrieval_snapshots=snapshots,
        retrieval_step_snapshots=True)
    assert original["status"] == "FAILED"
    captured = captured_after(snapshots, "SEARCH")
    call = read_json(captured / "call.json")
    # A closed error packet and an uncaught policy exception retain distinct statuses.
    assert call["status"] == ("ORIGINAL_COMPLETED" if failure_kind == "read" else "ORIGINAL_FAILED")
    if failure_kind == "read":
        assert not call["original_result"]["ok"]
    handoff = next(a for a in call["initial_actions"] if a["kind"] == "HANDOFF"
                   and not a["parameters"])
    branch = replay_call(captured, tmp_path / "branch", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": handoff,
                                                   "continuation_steps": 0})
    assert branch["status"] == "COMPLETED", branch.get("error")
    assert branch["frozen_initial_observation_and_actions_equal"]
    assert read_json(captured / "call.json") == call
