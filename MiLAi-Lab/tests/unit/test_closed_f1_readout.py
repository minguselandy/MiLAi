"""Actual local replay/capture paths with scripted HTTP; no live model or shared ledger."""

import copy
import json
from pathlib import Path

import pytest
from test_frozen_host_message import VERSION
from test_frozen_retrieval import native_request
from test_given_retrieval import prepared_given
from test_v13_5_functional_integration import scripted

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.runners.frozen_host_message import memory_store_values
from milai_lab.runners.frozen_host_readout import prepare_readout, run_readout
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import message
from milai_lab.runners.handoff_comparison import prepare_handoff_call
from prepare_closed_f1_readout import BOUNDARY, prepare_closed_f1_readout
from prepare_known_budget_readout import append_fresh_request, public_messages
from run_frozen_retrieval_calls import declared_readout_frame
from run_known_budget_request import run_condition


def closed_f1_fixture(tmp_path, monkeypatch, *, native=True):
    root = prepared_given(tmp_path, native=native, host_source_arrivals=True,
        policy={"policy": "fixed_context", "reads": 2, "max_control_steps": 8,
                "delivery_selection": True})
    request = {"query": "Cedar code", "read_goal": {"purpose": "find both reported parts"}}
    wires = scripted(monkeypatch, lambda _wire, n: (
        (native_request(request) if n == 1 else {"role": "assistant", "content": "4312"})
        if native else ({"calls": [{"name": "milai_retrieve", "arguments": request}]}
                        if n == 1 else {"answer": "4312"})), native=native)
    result = message(root, bank="bank", owner="alice", session="host", message_id="original",
        content="What is the reported code?", incoming_sources=[{
            "session_id": f"reference-{i}", "event_key": f"part-{i}", "role": "tool",
            "origin": "reference_document", "content": f"Cedar code part {i} is {part}."}
            for i, part in enumerate(["43", "12"])],
        retrieval_snapshots=tmp_path / "calls", retrieval_step_snapshots=True)
    assert result["status"] == "COMPLETED"
    captured, = (tmp_path / "calls").iterdir()
    call = read_json(captured / "call.json")
    replay = tmp_path / "original-f1"
    result = replay_call(captured, replay, {"policy": "fixed", "reads": 2}, source_version=VERSION)
    assert result["status"] == "COMPLETED"
    readout_dir = replay / "host-readout"
    readout = run_readout(captured, replay, readout_dir, prepare_readout(captured),
                          source_version=VERSION)
    assert readout["status"] == "COMPLETED"
    runtime = replay / "runtime"
    relative = Path(call["source_bank_root"]).relative_to(call["source_root"])
    bank = runtime / relative
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(call["binding"]["bank"]), call["binding"]["owner"],
                                bank / "memory.lock", functional_contract="functional_v1")
        inventory = memory_store_values(service)
    refs = [item["ref"] for item in result["retrieval_result"]["evidence"]]
    assert refs
    request = copy.deepcopy(call["request"])
    request.setdefault("task_context", {})["known_evidence_refs"] = refs
    audit = {"actual_provider_request": str(readout_dir / "request.json"),
        "source_readout": str(readout_dir / "readout.json"), "source_call": str(captured),
        "actual_known_raw_refs": refs, "generated_answer_read_for_input_or_written_to_Store": False}
    audit_path = tmp_path / "anchor-audit.json"
    write_json(audit_path, audit)
    freeze = read_json(runtime / "input-freeze.json")
    plan = {"status": "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED",
        "family": "scripted", "anchor_audit": str(audit_path), "source_call": str(captured),
        "source_f1_readout": audit["source_readout"],
        "source_provider_request": audit["actual_provider_request"],
        "source_provider_output_message_id": read_json(readout_dir / "response.json")["id"],
        "source_snapshot": str(runtime), "source_snapshot_boundary": BOUNDARY,
        "source_bank_relative": str(relative), "source_store_values": inventory,
        "source_public_source_ref": call["binding"]["source_ref"],
        "source_version": freeze["source_version"],
        "original_ledger": freeze["config"]["budget_path"],
        "public_message": {**call["public_message"], "bank": call["bank"],
                           "message_id": "fresh-r1", "incoming_sources": []},
        "conditions": [{"arm": "baseline", "request": request}]}
    execution = tmp_path / "fresh"
    run = run_condition(plan, execution, "baseline")
    assert run["status"] == "COMPLETED"
    return plan, execution, Path(run["call_captures"][0]), wires


@pytest.mark.parametrize("native", [True, False])
def test_actual_f1_boundary_keeps_public_history_and_substitutes_only_new_receipt(
    tmp_path, monkeypatch, native,
):
    plan, execution, captured, wires = closed_f1_fixture(tmp_path, monkeypatch, native=native)
    before = copy.deepcopy(wires[-1])
    count = len(wires)
    ledger_before = read_json(Path(plan["original_ledger"]))
    frame = prepare_closed_f1_readout(plan, execution, captured)
    assert len(wires) == count and read_json(Path(plan["original_ledger"])) == ledger_before
    assert frame["request"]["messages"][:-2] == public_messages(before["messages"])
    assert frame["request"]["messages"][-1]["content"] == ""
    assert frame["starting_bank_boundary"] == BOUNDARY and frame["resolved_raw_known_equal"]
    assert not frame["original_answer_loaded_as_input"] and not frame["host_request_generated"]
    assert "closed_capture" not in frame
    frame_file = tmp_path / "frame.json"
    write_json(frame_file, frame)
    assert declared_readout_frame(captured, [{"capture": captured.name,
        "host_readout_frame": str(frame_file)}]) == frame
    branch = tmp_path / "fresh-branch"
    result = replay_call(captured, branch, {"policy": "fixed", "reads": 0}, source_version=VERSION)
    readout = run_readout(captured, branch, branch / "host-readout", frame, source_version=VERSION)
    assert readout["status"] == "COMPLETED" and len(wires) == count + 1
    assert wires[-1]["messages"][:-2] == public_messages(before["messages"])
    assert wires[-1]["messages"][-1]["content"] == result["messages"][0]["content"]
    # The actually reached post-state also retains the same known input and lineage.
    post = sorted(captured.glob("steps/*/call.json"))[-1].parent
    prepared = tmp_path / "post-current"
    prepare_handoff_call(post, prepared, source_version=VERSION)
    post_frame = prepare_closed_f1_readout(plan, execution, prepared)
    assert post_frame["request"] == frame["request"]
    assert post_frame["actual_initial_capture"] == str(captured.resolve())


@pytest.mark.parametrize("mutation", ["known", "identity", "request", "running", "wire"])
def test_mismatched_or_unclosed_inputs_cannot_become_a_ready_frame(tmp_path, monkeypatch, mutation):
    plan, execution, captured, wires = closed_f1_fixture(tmp_path, monkeypatch)
    path = captured / "call.json"
    call = read_json(path)
    if mutation == "known":
        call["initial_observation"]["task"]["known_evidence"] = []
    elif mutation == "identity":
        call["public_message"]["message_id"] = "different-request"
    elif mutation == "request":
        call["request"]["query"] = "unrelated"
    elif mutation == "running":
        run = read_json(execution / "run.json")
        run["status"] = "RUNNING"
        write_json(execution / "run.json", run)
    else:
        wire = read_json(Path(plan["source_provider_request"]))
        wire["messages"].append({"role": "assistant", "content": "leaked old final answer"})
        write_json(Path(plan["source_provider_request"]), wire)
    write_json(path, call)
    count = len(wires)
    expected = {"known": "Actual resolved known input", "identity": "Fresh call identity",
        "request": "Fresh call identity", "running": "actual closed fresh execution",
        "wire": "actual provider exchange"}
    with pytest.raises(ValueError, match=expected[mutation]):
        prepare_closed_f1_readout(plan, execution, captured)
    assert len(wires) == count


@pytest.mark.parametrize("mode", ["native", "json_action"])
def test_appended_call_drops_hidden_reasoning_without_changing_public_content(mode):
    wire = {"messages": [{"role": "assistant", "content": "public history",
        "reasoning": "hidden-r", "reasoning_content": "hidden-c"}]}
    saved = copy.deepcopy(wire)
    call = {"host": {"tool_mode": mode}, "call_id": "fresh-call", "request": {"query": "code"}}
    request = append_fresh_request(wire, call)
    assert request["messages"][0] == {"role": "assistant", "content": "public history"}
    assert "hidden-" not in json.dumps(request) and wire == saved


@pytest.mark.parametrize("native", [True, False])
def test_initial_handoff_intervention_keeps_known_context_without_new_acquisition(
    tmp_path, monkeypatch, native,
):
    plan, execution, captured, wires = closed_f1_fixture(tmp_path, monkeypatch, native=native)
    call = read_json(captured / "call.json")
    handoff, = [a for a in call["initial_actions"] if a["kind"] == "HANDOFF"]
    frame = prepare_closed_f1_readout(plan, execution, captured)
    original_files = {p.relative_to(captured): p.read_bytes()
                      for p in captured.rglob("*") if p.is_file()}
    executed = []
    execute = EvidenceOperations.execute

    def record(operations, action, state):
        executed.append(action.kind)
        return execute(operations, action, state)

    monkeypatch.setattr(EvidenceOperations, "execute", record)
    count = len(wires)
    branch = tmp_path / "initial-handoff"
    result = replay_call(captured, branch, {"policy": "rules"}, source_version=VERSION,
        intervention={"first_action": handoff, "continuation_steps": 0})
    # HANDOFF terminates in the controller without calling the acquisition executor.
    assert result["status"] == "COMPLETED" and executed == []
    relative = Path(call["host_prefix_trace"])
    prefix = (captured / "before" / relative).read_bytes()
    trace = (branch / "runtime" / relative).read_bytes()
    assert trace.startswith(prefix)
    events = [json.loads(line) for line in trace[len(prefix):].splitlines()]
    decision, = [e for e in events if e.get("event") == "memory_control_step"
                 and e.get("phase") == "decision_output"]
    assert decision["selected"] == handoff["id"]
    assert decision["selection_mode"] == "intervention_first_action"
    assert decision["step"] == result["frozen_start_step"] == 0
    assert result["frozen_initial_observation_and_actions_equal"]
    assert result["frozen_request_and_allowance_equal"]
    assert result["retrieval_result"]["evidence"] == []
    assert result["retrieval_result"]["usage"]["read_operations"] == 0
    assert result["retrieval_result"]["usage"]["known_reference_reads"] > 0
    assert len(wires) == count
    readout = run_readout(captured, branch, branch / "host-readout", frame,
                         source_version=VERSION)
    assert readout["status"] == "COMPLETED" and len(wires) == count + 1
    assert wires[-1]["messages"][:-2] == frame["request"]["messages"][:-2]
    assert json.loads(wires[-1]["messages"][-1]["content"])["evidence"] == []
    assert original_files == {p.relative_to(captured): p.read_bytes()
                              for p in captured.rglob("*") if p.is_file()}
