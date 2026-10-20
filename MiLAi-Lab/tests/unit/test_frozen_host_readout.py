"""Fixed Host readouts preserve whole native/JSON batches and the original ledger."""
import copy
import json
import sys
from pathlib import Path

import pytest
from test_frozen_retrieval import native_request
from test_given_retrieval import no_http, prepared_given, source
from test_v13_5_functional_integration import prepared, scripted

from milai_lab.harness.artifact_io import read_json
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.runners.frozen_host_readout import (
    prepare_readout,
    readout_answer,
    run_readout,
    substitute_receipt,
)
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import frozen, message


@pytest.mark.parametrize("native", [True, False])
def test_fixed_readout_substitutes_only_target_and_keeps_complete_batch_and_accounting(
    tmp_path, monkeypatch, native,
):
    root = prepared(tmp_path, native=native, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        dynamic_memory=True, edit_interface_version="I2", memory_view_mode="staged",
        additional_reads=8, memory_control={"policy": "fixed_context", "max_control_steps": 5})
    snapshots = tmp_path / "snapshots"

    def reply(wire, n):
        if n == 1:
            if native:
                response = native_request({"query": "Cedar code"}, "first")
                response["tool_calls"].extend(
                    native_request({"query": "Cedar report"}, "second")["tool_calls"])
                return response
            return {"calls": [{"name": "milai_retrieve", "arguments": {"query": "Cedar code"}},
                              {"name": "milai_retrieve", "arguments": {"query": "Cedar report"}}]}
        return ({"role": "assistant", "content": "4312"} if native else {"answer": "4312"})

    wires = scripted(monkeypatch, reply, native=native)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the report", incoming_sources=[source()], retrieval_snapshots=snapshots)
    assert original["status"] == "COMPLETED", original.get("error")
    captured = min(snapshots.iterdir(), key=lambda path: read_json(path / "call.json")[
        "captured_epoch"])
    frame = prepare_readout(captured)
    assert frame["status"] == "READY" and len(frame["batch_call_ids"]) == 2
    assert frame["request"] == wires[1]
    old_frame = copy.deepcopy(frame)
    original_files = {str(path.relative_to(captured)): path.read_bytes()
                      for path in captured.rglob("*") if path.is_file()}
    result = replay_call(captured, tmp_path / "fixed", {"policy": "fixed", "reads": 0},
                         source_version="mechanical")
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["retrieval_result"]["evidence"] == []
    report = run_readout(captured, tmp_path / "fixed", tmp_path / "readout",
                         frame, source_version="mechanical")
    assert report["status"] == "COMPLETED" and report["answer"] == "4312"
    assert report["actual_http_attempts"] == 1 and len(wires) == 3
    assert report["generation_calls_after"] == report["generation_calls_before"] + 1
    assert report["budget_after"]["generation_requests"] == (
        report["budget_before"]["generation_requests"] + 1)
    assert report["budget_after"]["generation"]["unknown_usage"] == (
        report["budget_before"]["generation"]["unknown_usage"])
    observed = wires[-1]
    index = frame["target_message_index"]
    expected_messages = copy.deepcopy(frame["request"]["messages"])
    expected_messages[index]["content"] = result["messages"][0]["content"]
    assert observed["messages"] == expected_messages
    assert frame == old_frame
    assert {str(path.relative_to(captured)): path.read_bytes()
            for path in captured.rglob("*") if path.is_file()} == original_files
    for key, value in frame["request"].items():
        if key not in {"messages", "tool_choice", "response_format"}:
            assert observed[key] == value
    if native:
        assert observed["tool_choice"] == "none"
        assert observed["tools"] == frame["request"]["tools"]
    else:
        assert set(observed["response_format"]["json_schema"]["schema"]["properties"]) == {"answer"}
    assert read_json(tmp_path / "readout/request.json") == observed
    ledger = read_json(Path(frozen(root)["config"]["budget_path"]))
    assert ledger == report["budget_after"]
    with pytest.raises(FileExistsError):
        run_readout(captured, tmp_path / "fixed", tmp_path / "readout",
                    frame, source_version="mechanical")
    assert len(wires) == 3


@pytest.mark.parametrize("finish", ["length", "tool_calls", "capacity", "interrupt"])
def test_readout_keeps_first_incomplete_response_and_never_repairs(tmp_path, monkeypatch, finish):
    root = prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        edit_interface_version="I2", memory_view_mode="staged",
        dynamic_memory=True, memory_control={"policy": "fixed", "max_control_steps": 4})
    snapshots = tmp_path / "snapshots"

    def reply(wire, n):
        if n == 1:
            return native_request({"query": "Cedar code"})
        if n == 3 and finish == "interrupt":
            raise KeyboardInterrupt("synthetic readout interruption")
        response = {"role": "assistant", "content": "4312"}
        if n == 3:
            response["_test_finish_reason"] = finish
        return response

    wires = scripted(monkeypatch, reply, native=True)
    original = message(root, bank="b", owner="alice", session="host", message_id="q",
        content="Find code", incoming_sources=[source()], retrieval_snapshots=snapshots)
    assert original["status"] == "COMPLETED"
    captured, = snapshots.iterdir()
    frame = prepare_readout(captured)
    replay_call(captured, tmp_path / "fixed", {"policy": "fixed"}, source_version="mechanical")
    if finish == "capacity":
        frame["request"]["messages"][0]["content"] += " word" * 40000
    expected = (CapacityExceeded if finish == "capacity" else
                KeyboardInterrupt if finish == "interrupt" else IncompleteChatResponse)
    with pytest.raises(expected):
        run_readout(captured, tmp_path / "fixed", tmp_path / "readout",
                    frame, source_version="mechanical")
    report = read_json(tmp_path / "readout/readout.json")
    assert report["status"] == "FAILED"
    assert report["actual_http_attempts"] == (0 if finish == "capacity" else 1)
    assert (tmp_path / "readout/response.json").exists() is (finish in {"length", "tool_calls"})
    assert "answer" not in report
    assert len(wires) == (2 if finish == "capacity" else 3)
    if finish == "interrupt":
        assert report["budget_after"]["generation"]["unknown_usage"] == (
            report["budget_before"]["generation"]["unknown_usage"] + 1)


def test_projection_rejects_partial_batch_and_does_not_add_missing_context(tmp_path):
    frame = {"status": "NO_POST_TOOL_HOST_INPUT", "scope": "synthetic", "call_id": "target"}
    with pytest.raises(ValueError, match="CONTEXT_UNAVAILABLE"):
        substitute_receipt(frame, {"type": "tool", "tool_call_id": "target", "content": "{}"})
    report = run_readout(tmp_path / "no-capture", tmp_path / "no-replay", tmp_path / "readout",
                         frame, source_version="mechanical")
    assert report["status"] == "NOT_EXECUTED"
    assert report["actual_http_attempts"] == 0
    # A model's attempt to request another tool cannot become a final answer.
    with pytest.raises(IncompleteChatResponse):
        readout_answer({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "", "tool_calls": [{"id": "new"}]}}]}, "native", {})
    captured, original = tmp_path / "captured", tmp_path / "original"
    (captured / "before").mkdir(parents=True)
    original.mkdir()
    (captured / "before/trace.jsonl").write_text("")
    (captured / "call.json").write_text(json.dumps({
        "call_id": "target", "host": {"tool_mode": "native"}, "host_request_generated": True,
        "host_result_path": "result.json",
        "host_prefix_trace": "trace.jsonl", "source_root": str(original)}))
    (original / "result.json").write_text('{"status":"COMPLETED"}')
    incomplete = {"messages": [
        {"role": "assistant", "tool_calls": [{"id": "target"}, {"id": "other"}]},
        {"role": "tool", "tool_call_id": "target", "content": "{}"}]}
    (original / "trace.jsonl").write_text(json.dumps({
        "event": "vllm_response", "request": incomplete}) + "\n")
    with pytest.raises(ValueError, match="INCOMPLETE_NATIVE_BATCH"):
        prepare_readout(captured)
    incomplete["messages"].append({
        "role": "tool", "tool_call_id": "other", "content": "{}"})
    (original / "result.json").write_text('{"status":"FAILED"}')
    (original / "trace.jsonl").write_text(json.dumps({
        "event": "vllm_capacity_rejected", "request": incomplete}) + "\n")
    failed_origin = prepare_readout(captured)
    assert failed_origin["status"] == "READY"
    assert failed_origin["original_host_status"] == "FAILED"
    assert failed_origin["original_event"] == "vllm_capacity_rejected"
    (original / "result.json").unlink()
    with pytest.raises(ValueError, match="ORIGINAL_HOST_NOT_CLOSED"):
        prepare_readout(captured)


def test_cli_retains_given_request_without_claiming_an_actual_host_context(tmp_path, monkeypatch):
    import httpx

    root = prepared_given(tmp_path)
    snapshots = tmp_path / "snapshots"
    monkeypatch.setattr(httpx.Client, "send", no_http)
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find code", incoming_sources=[source()], retrieval_snapshots=snapshots,
        given_retrieval_request={"query": "Cedar code"})
    assert result["status"] == "COMPLETED"
    policies = tmp_path / "policies.json"
    policies.write_text('[{"name":"fixed","policy":{"policy":"fixed"}}]')
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    import run_frozen_retrieval_calls

    monkeypatch.setattr(sys, "argv", ["run_frozen_retrieval_calls", str(snapshots),
        str(policies), str(tmp_path / "matrix"), "--source-version", "mechanical",
        "--host-readout"])
    run_frozen_retrieval_calls.main()
    driver = read_json(tmp_path / "matrix/driver.json")
    assert driver["planned_positions"] == len(driver["completed"]) == 1
    assert driver["status"] == "COMPLETED_WITH_MISSING_READOUTS"
    assert driver["completed"][0]["host_readout_status"] == "NOT_EXECUTED"
    assert driver["completed"][0]["host_readout_reason"] == "NO_HOST_REQUEST_ORIGIN"


@pytest.mark.parametrize("keep_collecting,unknown_usage", [
    (False, False), (True, False), (True, True)])
def test_cli_keeps_known_failed_readout_and_never_retries_it(
    tmp_path, monkeypatch, keep_collecting, unknown_usage,
):
    root = prepared_given(tmp_path)
    snapshots = tmp_path / "snapshots"

    def reply(_wire, number):
        if number in (1, 3):
            # Original request is legal; the same tool request in a final-only readout is invalid.
            return native_request({"query": "Cedar code"}, f"call-{number}")
        return {"role": "assistant", "content": "4312"}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported code", incoming_sources=[source()],
        retrieval_snapshots=snapshots)
    assert result["status"] == "COMPLETED"
    policies = tmp_path / "policies.json"
    policies.write_text(json.dumps([
        {"name": name, "policy": {"policy": "fixed"}} for name in ("first", "second")]))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    import run_frozen_retrieval_calls
    from milai_lab.runners import frozen_host_readout

    actual_readout = frozen_host_readout.run_readout

    def readout_with_usage_status(*args, **kwargs):
        try:
            return actual_readout(*args, **kwargs)
        except IncompleteChatResponse:
            if unknown_usage:
                # Exercise the collector's treatment of an unresolved accounting receipt.
                path = args[2] / "readout.json"
                report = read_json(path)
                report["budget_after"]["generation"]["unknown_usage"] += 1
                path.write_text(json.dumps(report))
            raise

    monkeypatch.setattr(frozen_host_readout, "run_readout", readout_with_usage_status)

    monkeypatch.setattr(sys, "argv", ["run_frozen_retrieval_calls", str(snapshots),
        str(policies), str(tmp_path / "matrix"), "--source-version", "mechanical",
        "--host-readout", *(["--continue-known-readout-failures"] if keep_collecting else [])])
    continues = keep_collecting and not unknown_usage
    if continues:
        run_frozen_retrieval_calls.main()
    else:
        with pytest.raises(IncompleteChatResponse):
            run_frozen_retrieval_calls.main()
    driver = read_json(tmp_path / "matrix/driver.json")
    assert driver["completed"][0]["host_readout_status"] == "FAILED"
    assert len(driver["completed"]) == (2 if continues else 1)
    assert len(wires) == (4 if continues else 3)
    if continues:
        assert driver["completed"][1]["host_readout_status"] == "COMPLETED"
        assert driver["status"] == "COMPLETED_WITH_MISSING_READOUTS"
