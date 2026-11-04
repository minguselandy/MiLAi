"""Conditional supplied-request answers use real receipts and isolated test ledgers."""
import copy
import json
import runpy
import sys
from pathlib import Path

import pytest
from langgraph.store.sqlite import SqliteStore
from test_given_retrieval import prepared_given, source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.runners.frozen_host_message import memory_store_values
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import frozen, message, prepare
from milai_lab.runners.given_host_readout import given_readout_frame, run_given_readout


def declared_root(tmp_path, **kwargs):
    prepared_given(tmp_path, **kwargs)
    root = tmp_path / "declared"
    prepare(root, tmp_path / "settings.json", source_version="mechanical")
    return root


def captured_request(root, snapshots, **public_time):
    result = message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
        content="What is the reported Cedar code?", given_retrieval_request={"query": "Cedar code"},
        incoming_sources=[source()], retrieval_snapshots=snapshots, **public_time)
    assert result["status"] == "COMPLETED", result.get("error")
    captured, = snapshots.iterdir()
    return result, captured


def bank_values(call):
    directory = Path(call["source_bank_root"])
    with SqliteStore.from_conn_string(str(directory / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(call["binding"]["bank"]),
            call["binding"]["owner"], directory / "memory.lock",
            functional_contract="functional_v1")
        return memory_store_values(service)


def empty_given_branch(tmp_path, monkeypatch):
    root = declared_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content":
        '{"answer":"The returned packet is empty; the code is not established."}'}, native=True)
    original, captured = captured_request(root, tmp_path / "captures")
    call = read_json(captured / "call.json")
    handoff = next(a for a in call["initial_actions"] if a["kind"] == "HANDOFF")
    case = tmp_path / "branch"
    result = replay_call(captured, case, {"policy": "fixed_context"},
        source_version="mechanical", intervention={
            "first_action": handoff, "continuation_steps": 0})
    assert result["status"] == "COMPLETED" and not result["retrieval_result"]["evidence"]
    assert original["retrieval_result"]["evidence"]
    return root, captured, case, wires


def test_given_branch_reads_its_actual_packet_without_original_evidence_or_state_repair(
    tmp_path, monkeypatch,
):
    root, captured, case, wires = empty_given_branch(tmp_path, monkeypatch)
    call_bytes = (captured / "call.json").read_bytes()
    original = read_json(captured / "call.json")
    result_path = Path(original["source_root"]) / original["host_result_path"]
    result_bytes = result_path.read_bytes()
    output = tmp_path / "branch-readout"
    report = run_given_readout(captured, output, source_version="mechanical", replay_case=case)
    assert report["status"] == "COMPLETED" and len(wires) == 1
    assert report["actual_http_attempts"] == 1
    assert report["readout_origin"] == "actual_same_before_branch"
    delivered = json.loads(wires[0]["messages"][1]["content"])
    assert delivered["memory"] == read_json(case / "replay.json")["result"]["retrieval_result"]
    assert "4312" not in json.dumps(delivered)
    assert read_json(output / "frame.json")["schema"] == "given_request_branch_host_readout_v1"
    assert (captured / "call.json").read_bytes() == call_bytes
    assert result_path.read_bytes() == result_bytes
    assert read_json(Path(frozen(root)["config"]["budget_path"])) == report["budget_after"]
    # The original failure status must not be rewritten to manufacture a branch readout.
    failed_original = {**original, "status": "ORIGINAL_FAILED"}
    replay = read_json(case / "replay.json")
    frame = given_readout_frame(failed_original, replay["result"], frozen(root)["config"],
                                replay=replay)
    assert frame["status"] == "READY" and frame["original_call_status"] == "ORIGINAL_FAILED"


def test_given_branch_with_changed_before_cannot_send_a_reader_request(tmp_path, monkeypatch):
    _, captured, case, wires = empty_given_branch(tmp_path, monkeypatch)
    replay = read_json(case / "replay.json")
    replay["result"]["frozen_initial_observation_and_actions_equal"] = False
    write_json(case / "replay.json", replay)
    with pytest.raises(ValueError, match="SAME_ACTUAL_BEFORE"):
        run_given_readout(captured, tmp_path / "rejected", source_version="mechanical",
                          replay_case=case)
    assert not wires


def test_given_branch_revocation_is_checked_in_the_actual_replay_bank(tmp_path, monkeypatch):
    root = declared_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: pytest.fail("Revoked branch must not call reader"))
    original, captured = captured_request(root, tmp_path / "captures")
    call = read_json(captured / "call.json")
    case = tmp_path / "branch"
    result = replay_call(captured, case, {"policy": "fixed_context"}, source_version="mechanical")
    assert result["retrieval_result"]["evidence"]
    bank = case / "runtime" / Path(call["source_bank_root"]).relative_to(call["source_root"])
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(call["binding"]["bank"]), call["binding"]["owner"],
                                bank / "memory.lock", functional_contract="functional_v1")
        ref = original["incoming_source_receipts"][0]["receipt"]["source_ref"]
        handle = service.source_fragments(ref)[0]["fragment_handle"]
        service.forget("removal", "forget", fragment_handles=[handle])
    report = run_given_readout(captured, tmp_path / "blocked", source_version="mechanical",
                              replay_case=case)
    assert report["status"] == "NOT_EXECUTED"
    assert report["reason"] == "GIVEN_READOUT_VISIBILITY_REVOKED"
    assert not wires and report["actual_http_attempts"] == 0


def test_given_branch_cli_keeps_known_incomplete_readout_and_moves_to_next_binding(
    tmp_path, monkeypatch,
):
    root = declared_root(tmp_path)
    _, captured = captured_request(root, tmp_path / "captures")
    call = read_json(captured / "call.json")
    handoff = next(a for a in call["initial_actions"] if a["kind"] == "HANDOFF")
    replies = iter([{"role": "assistant", "content": None, "_test_finish_reason": "length"},
                    {"role": "assistant", "content": '{"answer":"4312"}'}])
    wires = scripted(monkeypatch, lambda *_: next(replies), native=True)
    policies = tmp_path / "policies.json"
    write_json(policies, [
        {"name": "empty", "capture": captured.name, "policy": {"policy": "fixed_context"},
         "intervention": {"first_action": handoff, "continuation_steps": 0}},
        {"name": "raw", "capture": captured.name, "policy": {"policy": "fixed_context"}}])
    output = tmp_path / "compared"
    monkeypatch.setattr(sys, "argv", ["run_frozen_retrieval_calls.py", str(captured.parent),
        str(policies), str(output), "--source-version", "mechanical", "--given-readout",
        "--continue-known-readout-failures"])
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/run_frozen_retrieval_calls.py"),
                   run_name="__main__")
    driver = read_json(output / "driver.json")
    assert driver["status"] == "COMPLETED_WITH_MISSING_READOUTS"
    assert [r["host_readout_status"] for r in driver["completed"]] == ["FAILED", "COMPLETED"]
    assert len(wires) == 2
    assert "answer" not in read_json(output / "arm-00/call-00000/host-readout/readout.json")


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("extractive", [True, False])
def test_actual_packet_only_one_answer_original_allowance_and_no_source_write(
    tmp_path, monkeypatch, native, extractive,
):
    policy = ({"policy": "view_cache", "view_builder": "extractive", "max_control_steps": 4}
              if extractive else None)
    root = declared_root(tmp_path, policy=policy, native=native)
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": json.dumps({
        "answer": "4312; no further action performed."})}, native=True)
    result, captured = captured_request(root, tmp_path / "captures")
    assert not wires
    call = read_json(captured / "call.json")
    before = bank_values(call)
    original = Path(call["source_root"]) / call["host_result_path"]
    original_bytes = original.read_bytes()
    output = tmp_path / "readout"
    report = run_given_readout(captured, output, source_version="mechanical")
    assert report["status"] == "COMPLETED" and report["actual_http_attempts"] == len(wires) == 1
    assert report["generation_calls_after"] == report["generation_calls_before"] + 1
    assert report["budget_after"]["generation_requests"] == (
        result["budget_after"]["generation_requests"] + 1)
    assert report["budget_after"]["generation"]["unknown_usage"] == (
        result["budget_after"]["generation"]["unknown_usage"])
    assert read_json(Path(frozen(root)["config"]["budget_path"])) == report["budget_after"]
    assert len(wires[0]["messages"]) == 2 and "tools" not in wires[0]
    delivered = json.loads(wires[0]["messages"][1]["content"])
    assert delivered == {"request": result["content"], "retrieval_request": call["request"],
                         "memory": result["retrieval_result"]}
    assert read_json(output / "request.json") == wires[0]
    assert not report["host_request_generated"] and not report["answer_persisted_as_source"]
    assert bank_values(call) == before and original.read_bytes() == original_bytes
    assert result["final_answer"] is None
    with pytest.raises(FileExistsError):
        run_given_readout(captured, output, source_version="mechanical")
    assert len(wires) == 1


def test_frame_excludes_hidden_inventory_and_rejects_different_public_request(
    tmp_path, monkeypatch,
):
    root = declared_root(tmp_path)
    scripted(monkeypatch, lambda *_: pytest.fail("No model call in frame preparation"))
    result, captured = captured_request(root, tmp_path / "captures")
    call = read_json(captured / "call.json")
    result["sources"] = [{"content": "Unreturned secret code: 987654321"}]
    result["final_answer"] = "This invented previous answer must never enter input."
    frame = given_readout_frame(call, result, frozen(root)["config"])
    assert "987654321" not in json.dumps(frame)
    assert result["final_answer"] not in json.dumps(frame)
    changed = copy.deepcopy(call)
    changed["public_message"]["content"] = "A different question"
    with pytest.raises(ValueError, match="PUBLIC_REQUEST_CHANGED"):
        given_readout_frame(changed, result, frozen(root)["config"])
    changed = copy.deepcopy(call)
    changed["host_request_generated"] = True
    with pytest.raises(ValueError, match="REQUIRES_SUPPLIED_REQUEST"):
        given_readout_frame(changed, result, frozen(root)["config"])


@pytest.mark.parametrize("finish,content", [("length", '{"answer":"partial"}'), ("stop", None)])
def test_incomplete_final_answer_is_retained_without_reasoning_recovery(
    tmp_path, monkeypatch, finish, content,
):
    root = declared_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": content,
        "reasoning_content": "Do not turn this into an answer.", "_test_finish_reason": finish},
        native=True)
    _, captured = captured_request(root, tmp_path / "captures")
    with pytest.raises(IncompleteChatResponse):
        run_given_readout(captured, tmp_path / "readout", source_version="mechanical")
    report = read_json(tmp_path / "readout/readout.json")
    assert report["status"] == "FAILED" and "answer" not in report
    assert report["actual_http_attempts"] == len(wires) == 1
    assert report["budget_after"]["generation_requests"] == 1
    assert report["budget_after"]["generation"]["unknown_usage"] == 0


def test_actual_bank_message_allowance_is_not_reset_for_readout(tmp_path, monkeypatch):
    prepared_given(tmp_path)
    config = read_json(tmp_path / "settings.json")
    config["max_calls_per_message"] = 1
    config["host"]["max_calls"] = 1
    config["http_ownership_domain"]["clients"][0]["max_calls"] = 1
    config_path = tmp_path / "limited.json"
    config_path.write_text(json.dumps(config))
    root = tmp_path / "limited"
    prepare(root, config_path, source_version="mechanical")
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": '{"answer":"4312"}'},
                     native=True)
    _, captured = captured_request(root, tmp_path / "captures")
    run_given_readout(captured, tmp_path / "first", source_version="mechanical")
    with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
        run_given_readout(captured, tmp_path / "over-capacity", source_version="mechanical")
    report = read_json(tmp_path / "over-capacity/readout.json")
    assert report["status"] == "FAILED" and report["actual_http_attempts"] == 0
    assert report["generation_calls_before"] == 1 and len(wires) == 1
    assert report["budget_before"] == report["budget_after"]


@pytest.mark.parametrize("unknown_usage", [False, True])
def test_sequence_reads_each_actual_packet_before_next_arrival_and_retains_failed_answer(
    tmp_path, monkeypatch, unknown_usage,
):
    original = prepared_given(tmp_path)
    config = tmp_path / "entrypoints.json"
    settings = {**frozen(original)["config"], "config_version": "given-readout-unit-v1"}
    config.write_text(json.dumps({"entrypoints": {"functional": settings}}))
    future = {**source(), "event_key": "correction", "content": "Cedar code is now 6754."}
    fixture = {"histories": [{"id": "sequence", "source_group": "authored-unit-test",
        "split": "dev", "continuous": True, "sources": [], "requests": [
            {"id": "p0", "content": "What is the Cedar code?",
             "retrieval_request": {"query": "Cedar code"}, "incoming_sources": [source()]},
            {"id": "p1", "content": "What is the Cedar code?",
             "retrieval_request": {"query": "Cedar code"}, "incoming_sources": [future]},
        ]}]}
    path = tmp_path / "histories.json"
    path.write_text(json.dumps(fixture))

    def respond(wire, ordinal):
        assert ("6754" in wire["messages"][-1]["content"]) is (ordinal == 2)
        return {"role": "assistant", "content": json.dumps({"answer": str(ordinal)}),
                "_test_finish_reason": "length" if ordinal == 1 else "stop",
                **({"_test_usage": None} if unknown_usage and ordinal == 1 else {})}

    wires = scripted(monkeypatch, respond, native=True)
    script = Path(__file__).resolve().parents[2] / "tools/run_host_intent_retrieval.py"
    output = tmp_path / "sequence"
    monkeypatch.setattr(sys, "argv", [str(script), str(config),
        str(path), str(output), "--source-version", "mechanical", "--policies", "fixed_context",
        "--interfaces", "rich", "--given-requests", "--given-readouts"])
    if unknown_usage:
        with pytest.raises(IncompleteChatResponse):
            runpy.run_path(str(script), run_name="__main__")
    else:
        runpy.run_path(str(script), run_name="__main__")
    driver = read_json(output / "driver.json")
    count = 1 if unknown_usage else 2
    assert driver["status"] == ("FAILED" if unknown_usage else "COMPLETED_WITH_FAILURES")
    assert len(wires) == count
    assert [row["status"] for row in driver["completed"]] == ["COMPLETED"] * count
    expected = ["FAILED"] if unknown_usage else ["FAILED", "COMPLETED"]
    assert [row["conditional_readout"]["status"] for row in driver["completed"]] == expected
    assert all(row["answer"] is None for row in driver["completed"])
    assert len(list((output / "frozen-retrieval-calls").glob("*/call.json"))) == count
    bank = next((output / "fixed_context-rich/banks").iterdir())
    final = [read_json(p) for p in bank.glob("*-result.json")]
    assert all(s["role"] != "assistant" for result in final for s in result["sources"])


def test_failed_view_generation_does_not_become_an_answer_or_another_model_call(
    tmp_path, monkeypatch,
):
    root = declared_root(tmp_path, policy={"policy": "view_cache", "max_control_steps": 4})
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "{}",
        "_test_finish_reason": "length"}, native=True)
    captures = tmp_path / "captures"
    result = message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
        content="What is the Cedar code?", given_retrieval_request={"query": "Cedar code"},
        incoming_sources=[source()], retrieval_snapshots=captures)
    assert result["status"] == "FAILED" and len(wires) == 1
    captured, = captures.iterdir()
    report = run_given_readout(captured, tmp_path / "readout", source_version="mechanical")
    assert report["status"] == "NOT_EXECUTED" and report["actual_http_attempts"] == 0
    assert report["reason"] == "GIVEN_RETRIEVAL_NOT_COMPLETED" and "answer" not in report
    assert len(wires) == 1 and not (tmp_path / "readout/request.json").exists()


def test_later_revocation_cannot_be_bypassed_with_a_captured_tool_receipt(tmp_path, monkeypatch):
    root = declared_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: pytest.fail("Revoked packet must not reach a model"))
    result, captured = captured_request(root, tmp_path / "captures")
    call = read_json(captured / "call.json")
    directory = Path(call["source_bank_root"])
    with SqliteStore.from_conn_string(str(directory / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(call["binding"]["bank"]),
            call["binding"]["owner"], directory / "memory.lock",
            functional_contract="functional_v1")
        ref = result["incoming_source_receipts"][0]["receipt"]["source_ref"]
        handle = service.source_fragments(ref)[0]["fragment_handle"]
        service.forget("removal", "forget", fragment_handles=[handle])
    report = run_given_readout(captured, tmp_path / "readout", source_version="mechanical")
    assert report["status"] == "NOT_EXECUTED"
    assert report["reason"] == "GIVEN_READOUT_VISIBILITY_REVOKED"
    assert not wires and report["actual_http_attempts"] == 0
    assert not (tmp_path / "readout/request.json").exists()
    assert "4312" not in json.dumps(report)


def test_actual_known_delivery_cannot_be_omitted_from_a_claimed_host_readout(tmp_path, monkeypatch):
    root = declared_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: pytest.fail(
        "A packet-only reader lacks prior context"))
    result, _ = captured_request(root, tmp_path / "first-capture")
    reference = result["retrieval_result"]["evidence"][0]["ref"]
    captures = tmp_path / "known-capture"
    second = message(root, bank="corpus", owner="alice", session="evaluation", message_id="p1",
        content="What is the reported Cedar code?", given_retrieval_request={"query": "Cedar code",
            "task_context": {"known_evidence_refs": [reference]}}, retrieval_snapshots=captures)
    assert second["status"] == "COMPLETED", second.get("error")
    captured, = captures.iterdir()
    with pytest.raises(ValueError, match="CANNOT_RECONSTRUCT_PRIOR_HOST_KNOWLEDGE"):
        run_given_readout(captured, tmp_path / "readout", source_version="mechanical")
    assert not wires and not (tmp_path / "readout/request.json").exists()


def test_declared_public_query_time_is_not_replaced_by_source_capture_time(tmp_path, monkeypatch):
    root = declared_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": '{"answer":"4312"}'},
                     native=True)
    declared = {"occurred_at": "2026-06-09T10:00:00Z", "query_time": "2026-06-08"}
    result, captured = captured_request(root, tmp_path / "captures", **declared)
    run_given_readout(captured, tmp_path / "readout", source_version="mechanical")
    actual = json.loads(wires[0]["messages"][-1]["content"])
    assert actual["public_request_time"] == declared
    assert actual["request"] == result["content"] and actual["memory"] == result["retrieval_result"]


def test_frame_projection_does_not_reload_tokenizer_to_copy_validated_settings(
    tmp_path, monkeypatch,
):
    from transformers import AutoTokenizer

    root = declared_root(tmp_path)
    scripted(monkeypatch, lambda *_: pytest.fail("Frame preparation must not call a model"))
    result, captured = captured_request(root, tmp_path / "captures")
    call, settings = read_json(captured / "call.json"), frozen(root)["config"]
    expected = given_readout_frame(call, result, settings)
    monkeypatch.setattr(AutoTokenizer, "from_pretrained", lambda *_args, **_kwargs: pytest.fail(
        "Pure frame projection must not load a tokenizer"))
    assert given_readout_frame(call, result, settings) == expected
    settings["capacity"].pop("enable_thinking")  # The existing HostCapacity default is False.
    assert given_readout_frame(call, result, settings) == expected
