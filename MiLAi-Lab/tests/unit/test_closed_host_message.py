"""Post-delivery snapshots bind actual provider requests without inventing known evidence."""
import copy
import json
import sys
from pathlib import Path

import httpx
import pytest
from test_frozen_host_message import VERSION, capture_root
from test_frozen_retrieval import native_request
from test_given_retrieval import source
from test_v13_5_functional_integration import prepared, scripted

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.request_pipeline import PreparedRequest, ResponseEvent
from milai_lab.runners.frozen_host_message import (
    HostMessageRecorder,
    HostResponseRecorder,
    capture_closed_host_message,
)
from milai_lab.runners.functional import message, prepare


def answer_after_retrieval(wire, ordinal):
    last = max(i for i, m in enumerate(wire["messages"]) if m["role"] == "user")
    if not any(m["role"] == "tool" for m in wire["messages"][last + 1:]):
        return native_request({"query": "Cedar code"}, call_id=f"call-{ordinal}")
    return {"role": "assistant", "content": "The reported code is 4312."}


def test_closed_bank_and_final_provider_input_precede_later_source_arrivals(tmp_path, monkeypatch):
    root = capture_root(tmp_path)
    wires = scripted(monkeypatch, answer_after_retrieval, native=True)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="first",
        content="What is the code?", incoming_sources=[source()], host_snapshots=captures)
    assert result["status"] == "COMPLETED", result.get("error")
    captured, = captures.iterdir()
    before = {p.relative_to(captured / "before"): p.read_bytes()
              for p in (captured / "before").rglob("*") if p.is_file()}
    ledger = result["budget_after"]
    report = capture_closed_host_message(captured, result)
    assert report["message_status"] == "COMPLETED"
    assert report["final_context_status"] == "BOUND_TO_COMPLETED_FINAL_GENERATION"
    final = report["final_context"]
    assert final["output_message_id"] == result["messages"][-1]["id"]
    assert final["messages"] == wires[-1]["messages"]
    assert any(m["role"] == "tool" and "4312" in m["content"] for m in final["messages"])
    boundary = report["pre_final_snapshot"]
    assert boundary["status"] == "CAPTURED_BEFORE_FINAL_RESPONSE_PERSISTENCE"
    assert boundary["output_message_id"] == final["output_message_id"]
    earlier = read_json(captured / boundary["inventory"])["memory_store_values"]
    final_source = result["final_capture"]["source_ref"]
    assert final_source not in [r["key"] for r in earlier]
    assert final_source in [r["key"] for r in report["memory_store_values"]]
    host = read_json(captured / "host.json")
    assert len(host["delivered_model_requests"]) == 2
    assert not any(m["type"] == "tool" for m in host["initial_baseline_context"])
    assert before == {p.relative_to(captured / "before"): p.read_bytes()
                      for p in (captured / "before").rglob("*") if p.is_file()}
    freeze = read_json(root / "input-freeze.json")
    assert read_json(Path(freeze["config"]["budget_path"])) == ledger
    retained = {p.relative_to(captured): p.read_bytes() for p in captured.rglob("*") if p.is_file()}
    later = message(root, bank="bank", owner="alice", session="host", message_id="later",
        content="Check again.", incoming_sources=[{**source(), "event_key": "later",
            "content": "A later source says the code is 9999."}], previous_host_message="first")
    assert later["status"] == "COMPLETED", later.get("error")
    assert "9999" not in json.dumps(report["memory_store_values"])
    assert "9999" in json.dumps(later["sources"])
    assert retained == {p.relative_to(captured): p.read_bytes()
                        for p in captured.rglob("*") if p.is_file()}


def test_failed_provider_request_keeps_unknown_usage_without_certifying_final_context(
    tmp_path, monkeypatch,
):
    root = capture_root(tmp_path)
    scripted(monkeypatch, lambda *_: httpx.ReadTimeout("unknown response"), native=True)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="failed",
        content="What is the code?", incoming_sources=[source()], host_snapshots=captures)
    assert result["status"] == "PROVIDER_ERROR"
    captured, = captures.iterdir()
    report = capture_closed_host_message(captured, result)
    assert report["message_status"] == "PROVIDER_ERROR" and report["final_context"] is None
    saved = read_json(captured / "after" / report["result_path"])
    assert saved["budget_after"]["generation"]["unknown_usage"] == 1
    host = read_json(captured / "host.json")
    assert host["initial_baseline_context"] and not host["delivered_model_requests"]


def test_closed_capture_requires_actual_result_and_unique_decoded_message_binding(
    tmp_path, monkeypatch,
):
    root = capture_root(tmp_path)
    scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "Acknowledged."}, native=True)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Acknowledge.", host_snapshots=captures)
    captured, = captures.iterdir()
    wrong = copy.deepcopy(result)
    wrong["message_id"] = "different"
    with pytest.raises(ValueError, match="exact returned public invocation"):
        capture_closed_host_message(captured, wrong)
    assert not (captured / "after").exists()
    host = read_json(captured / "host.json")
    host["delivered_model_requests"].append(copy.deepcopy(host["delivered_model_requests"][-1]))
    write_json(captured / "host.json", host)
    report = capture_closed_host_message(captured, result)
    assert report["message_status"] == "COMPLETED"
    assert report["final_context"] is None and len(report["delivered_request_candidates"]) == 2


def test_collector_closed_flag_retains_point_before_next_request(tmp_path, monkeypatch):
    import run_host_intent_retrieval

    root = capture_root(tmp_path)
    config = tmp_path / "config.json"
    freeze = read_json(root / "input-freeze.json")
    settings = copy.deepcopy(freeze["config"])
    settings["config_version"] = freeze["config_version"]
    write_json(config, {"entrypoints": {"functional": settings}})
    fixture = tmp_path / "fixture.json"
    write_json(fixture, {"histories": [{"id": "one", "source_group": "one", "split": "train",
        "continuous": True, "sources": [source()], "requests": [
            {"id": "first", "content": "Acknowledge."},
            {"id": "later", "content": "Acknowledge again.", "incoming_sources": [
                {**source(), "event_key": "later", "content": "LATER_ONLY_SOURCE"}]}]}]})
    scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "Done."}, native=True)
    output = tmp_path / "collection"
    monkeypatch.setattr(sys, "argv", ["collect", str(config), str(fixture), str(output),
        "--source-version", VERSION, "--policies", "fixed_context", "--interfaces", "rich",
        "--capture-closed-host-messages", "--continue-host-history"])
    run_host_intent_retrieval.main()
    driver = read_json(output / "driver.json")
    assert driver["status"] == "COMPLETED" and driver["capture_host_messages"]
    assert driver["capture_closed_host_messages"]
    assert all(len(row["closed_host_snapshots"]) == 1 for row in driver["completed"])
    first = read_json(Path(driver["completed"][0]["closed_host_snapshots"][0]))
    later = read_json(Path(driver["completed"][1]["closed_host_snapshots"][0]))
    assert "LATER_ONLY_SOURCE" not in json.dumps(first["memory_store_values"])
    assert "LATER_ONLY_SOURCE" in json.dumps(later["memory_store_values"])


def test_json_action_capture_records_actual_transformed_request_and_decoded_final_id(
    tmp_path, monkeypatch,
):
    original = prepared(tmp_path, native=False, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        host_source_arrivals=True, dynamic_memory=True, edit_interface_version="I2",
        memory_view_mode="staged", additional_reads=8,
        memory_control={"policy": "fixed_context", "max_control_steps": 6,
                        "delivery_selection": True})
    freeze = read_json(original / "input-freeze.json")
    settings = copy.deepcopy(freeze["config"])
    config = tmp_path / "json-config.json"
    write_json(config, settings)
    root = tmp_path / "json-root"
    prepare(root, config, source_version=VERSION, run_id=freeze["run_id"])

    def reply(_wire, ordinal):
        return ({"calls": [{"name": "milai_retrieve", "arguments": {"query": "Cedar code"}}]}
                if ordinal == 1 else {"answer": "The reported code is 4312."})

    wires = scripted(monkeypatch, reply)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="What is the code?", incoming_sources=[source()], host_snapshots=captures)
    assert result["status"] == "COMPLETED", result.get("error")
    captured, = captures.iterdir()
    report = capture_closed_host_message(captured, result)
    assert report["final_context"]["messages"] == wires[-1]["messages"]
    assert report["final_context"]["output_message_id"] == result["messages"][-1]["id"]
    assert result["final_answer"] == "The reported code is 4312." and len(wires) == 2


def test_response_observer_delegates_without_mutating_wire_or_exporting_reasoning(tmp_path):
    recorder = HostMessageRecorder(tmp_path / "capture", tmp_path / "root", tmp_path / "bank",
                                   {}, lambda path: path.mkdir())
    recorder.ready({})
    calls = []

    class Inner:
        def on_response(self, event):
            calls.append(event.stage)

    messages = [{"role": "assistant", "content": "Visible text", "reasoning_content": "PRIVATE"},
                {"role": "tool", "content": "Actual public tool body"}]
    before = copy.deepcopy(messages)
    event = ResponseEvent("decoded_message", PreparedRequest(messages, []), {}, "final-id")
    HostResponseRecorder(recorder, Inner()).on_response(event)
    assert messages == before and calls == ["decoded_message"]
    saved, = recorder.row["delivered_model_requests"]
    assert "reasoning_content" not in saved["messages"][0]
    assert saved["messages"][1] == before[1] and saved["output_message_id"] == "final-id"


def test_snapshot_failure_keeps_the_actual_completed_public_outcome(tmp_path, monkeypatch):
    import run_host_intent_retrieval

    root = capture_root(tmp_path)
    freeze = read_json(root / "input-freeze.json")
    config = tmp_path / "config.json"
    settings = {**freeze["config"], "config_version": freeze["config_version"]}
    write_json(config, {"entrypoints": {"functional": settings}})
    fixture = tmp_path / "fixture.json"
    write_json(fixture, {"histories": [{"id": "one", "source_group": "one", "split": "train",
        "sources": [source()], "requests": [{"id": "q", "content": "Acknowledge."}]}]})
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "Done."}, native=True)

    def failed_snapshot(*_args):
        raise OSError("synthetic snapshot failure")

    monkeypatch.setattr("milai_lab.runners.frozen_host_message.capture_closed_host_message",
                        failed_snapshot)
    output = tmp_path / "collection"
    monkeypatch.setattr(sys, "argv", ["collect", str(config), str(fixture), str(output),
        "--source-version", VERSION, "--policies", "fixed_context", "--interfaces", "rich",
        "--capture-closed-host-messages"])
    with pytest.raises(OSError, match="synthetic snapshot failure"):
        run_host_intent_retrieval.main()
    driver = read_json(output / "driver.json")
    assert driver["status"] == "FAILED" and len(wires) == 1
    row, = driver["completed"]
    assert row["status"] == "COMPLETED" and row["answer"] == "Done."
    assert row["closed_host_capture_status"] == "FAILED_RETAINED"


def test_pre_final_recording_failure_retains_real_completed_response(tmp_path, monkeypatch):
    from milai_lab.runners import frozen_retrieval

    root = capture_root(tmp_path)
    scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "Done."}, native=True)
    original_copy = frozen_retrieval.copy_call_root

    def fail_only_final(root, bank, target):
        if target.name.startswith("final-input-"):
            raise OSError("synthetic pre-final snapshot failure")
        return original_copy(root, bank, target)

    monkeypatch.setattr(frozen_retrieval, "copy_call_root", fail_only_final)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Acknowledge.", host_snapshots=captures)
    captured, = captures.iterdir()
    report = capture_closed_host_message(captured, result)
    assert result["status"] == "COMPLETED" and result["final_answer"] == "Done."
    assert report["final_context_status"] == "BOUND_TO_COMPLETED_FINAL_GENERATION"
    assert report["pre_final_snapshot"]["status"] == "FAILED_RETAINED"
    assert report["pre_final_snapshot"]["error"] == "synthetic pre-final snapshot failure"
