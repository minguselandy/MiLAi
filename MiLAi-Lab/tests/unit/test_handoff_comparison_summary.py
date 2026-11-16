"""F1 summaries bind actual packets and provider wires without grading absent outcomes."""

import copy
import json
import os
import shutil

import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_host_readout import substitute_receipt
from summarize_handoff_comparison import summarize


def fixture(tmp_path, native=True):
    capture = tmp_path / "captures" / "family--original"
    capture.mkdir(parents=True)
    root = tmp_path / "run"
    root.mkdir()
    actions = [
        {"id": "all", "kind": "HANDOFF", "target": "opened", "parameters": {}},
        {
            "id": "none",
            "kind": "HANDOFF",
            "target": "empty",
            "parameters": {"delivery_indices": []},
        },
    ]
    state = {"task": {"request": "Cedar code"}, "visible_evidence": [{"content": "4312"}]}
    write_json(
        capture / "call.json",
        {"call_id": "target", "host_prefix_trace": "bank/request-trace-1.jsonl",
         "initial_observation": state, "initial_actions": actions},
    )
    frame = {
        "status": "READY",
        "tool_mode": "native",
        "call_id": "target",
        "captured_call": str(capture),
        "target_message_index": 2,
        "request": {
            "messages": [
                {"role": "user", "content": "Cedar code"},
                {"role": "assistant", "tool_calls": [{"id": "target"}]},
                {"role": "tool", "tool_call_id": "target", "content": "original"},
            ],
            "tool_choice": "auto",
            "max_tokens": 64,
        },
    }
    if not native:
        frame["tool_mode"] = "json_action"
        frame["request"].pop("tool_choice")
        frame["request"]["messages"][1] = {
            "role": "assistant",
            "content": json.dumps(
                {"calls": [{"name": "milai_retrieve", "arguments": {"query": "Cedar code"}}]}
            ),
        }
        frame["request"]["response_format"] = {
            "json_schema": {
                "schema": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {"calls": {"type": "array"}},
                            "required": ["calls"],
                        },
                        {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                        },
                    ]
                }
            }
        }
    frame_path = tmp_path / "frame.json"
    write_json(frame_path, frame)
    write_json(root / "readout-frames/00000.json", frame)
    policies = [
        {
            "name": name,
            "capture": capture.name,
            "policy": {"policy": policy, "routing": "handoff_only"},
        }
        for name, policy in [("rules", "rules"), ("jev", "laya")]
    ]
    recipe_path = tmp_path / "policies.json"
    write_json(recipe_path, policies)
    write_json(
        root / "cohort.json",
        {
            "calls": [{"capture": str(capture)}],
            "policies": policies,
            "selected_capture_indices": [0],
            "unselected_capture_indices": [],
        },
    )
    write_json(
        root / "driver.json",
        {
            "pid": os.getpid(),
            "status": "COMPLETED",
            "source_version": "test-v1",
            "host_readout": True,
            "automatic_retry": False,
            "planned_positions": 2,
            "completed": [],
        },
    )
    cases = []
    for i, recipe in enumerate(policies):
        case = root / f"arm-{i:02d}/call-00000"
        cases.append(case)
        packet = {"evidence": [{"kind": "original_source", "content": "4312"}] if i == 0 else []}
        receipt = {"type": "tool", "tool_call_id": "target", "content": json.dumps(packet)}
        write_json(
            case / "replay.json",
            {
                "captured_call": str(capture),
                "source_version": "test-v1",
                "policy": recipe["policy"],
                "status": "COMPLETED",
                "prefix_operations_reexecuted": 0,
                "result": {
                    "status": "COMPLETED",
                    "attempt": 1,
                    "frozen_initial_observation_and_actions_equal": True,
                    "frozen_request_and_allowance_equal": True,
                    "retrieval_result": packet,
                    "messages": [receipt],
                },
            },
        )
        trace = case / "runtime/bank/request-trace-1.jsonl"
        trace.parent.mkdir(parents=True)
        events = [
            {
                "event": "memory_control_step",
                "phase": "decision_output",
                "selected": "old-read",
                "actions": [{"id": "old-read", "kind": "READ"}],
            },
            {"event": "handoff_comparison_input", "state": state, "actions": actions},
            {
                "event": "handoff_comparison_selection",
                "selected": actions[i]["id"],
                "selection_mode": "policy",
            },
            {
                "event": "memory_control_step",
                "phase": "decision_output",
                "selected": actions[i]["id"],
                "actions": actions,
                "retrieval_call_id": "target",
            },
        ]
        trace.write_text("".join(json.dumps(e) + "\n" for e in events))
        prefix = capture / "before/bank/request-trace-1.jsonl"
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.write_text(json.dumps(events[0]) + "\n")
        wire = substitute_receipt(frame, receipt)
        answer = "4312" if i == 0 else "unknown"
        response = {
            "id": "response-" + str(i),
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": answer if native else json.dumps({"answer": answer}),
                    },
                }
            ],
        }
        readout = case / "host-readout"
        write_json(readout / "frame.json", frame)
        write_json(readout / "request.json", wire)
        write_json(readout / "response.json", response)
        write_json(
            readout / "readout.json",
            {
                "captured_call": str(capture),
                "source_version": "test-v1",
                "status": "COMPLETED",
                "answer": answer,
                "actual_http_attempts": 1,
            },
        )
        (readout / "trace.jsonl").write_text(
            json.dumps(
                {"event": "vllm_response", "request": wire, "response_text": json.dumps(response)}
            )
            + "\n"
        )
    dispatch = {
        "output": str(root),
        "source_version": "test-v1",
        "planned_branches": 2,
        "argv": ["entry.py", str(recipe_path), str(root)],
        "pairs": [
            {
                "family": "family",
                "condition": "original",
                "capture": str(capture),
                "readout_frame": str(frame_path),
                "arm_names": ["rules", "jev"],
            }
        ],
    }
    return dispatch, cases


@pytest.mark.parametrize("native", [True, False])
def test_actual_packets_and_wires_bound_without_grading_or_reexecuting_prefix(tmp_path, native):
    dispatch, _ = fixture(tmp_path, native)
    result = summarize(dispatch)
    assert result["planned_positions"] == 2 and result["conditions"] == 1
    assert result["comparisons"][0]["matched_completed_tools"]
    assert result["comparisons"][0]["actual_packets_equal"] is False
    assert result["comparisons"][0]["actual_readout_requests_equal"] is False
    assert [r["readout"]["answer"] for r in result["positions"]] == ["4312", "unknown"]
    assert all(r["semantic_grade"] == r["delivery_grade"] == "unknown" for r in result["positions"])


def test_unclosed_worker_is_not_reported_as_completed(tmp_path):
    dispatch, _ = fixture(tmp_path)
    path = tmp_path / "run/driver.json"
    driver = read_json(path)
    driver["status"] = "RUNNING"
    write_json(path, driver)
    with pytest.raises(ValueError, match="Unclosed F1"):
        summarize(dispatch)


def test_prior_f1_events_in_current_prefix_or_other_trace_are_not_new_decisions(tmp_path):
    dispatch, cases = fixture(tmp_path)
    capture = tmp_path / "captures/family--original"
    prefix_file = capture / "before/bank/request-trace-1.jsonl"
    prefix = prefix_file.read_bytes()
    historical = (json.dumps({"event": "handoff_comparison_input", "state": {}, "actions": []})
                  + "\n").encode()
    prefix_file.write_bytes(historical + prefix)
    for case in cases:
        trace = case / "runtime/bank/request-trace-1.jsonl"
        trace.write_bytes(historical + trace.read_bytes())
        (case / "runtime/bank/older-trace-0.jsonl").write_bytes(historical)
        with trace.open("a") as stream:
            stream.write(json.dumps({"event": "note", "text": "left\u2028right"},
                                    ensure_ascii=False) + "\n")
    report = summarize(dispatch)
    assert all(row["tool"]["new_decisions"] == 1 for row in report["positions"])
    assert all(row["tool"]["preserved_prefix_bytes"] == len(historical + prefix)
               for row in report["positions"])


@pytest.mark.parametrize("mutation", ["prefix", "call", "attempt"])
def test_current_trace_provenance_or_call_identity_drift_is_rejected(tmp_path, mutation):
    dispatch, cases = fixture(tmp_path)
    trace = cases[0] / "runtime/bank/request-trace-1.jsonl"
    if mutation == "prefix":
        trace.write_bytes(b" " + trace.read_bytes())
    elif mutation == "call":
        events = [json.loads(line) for line in trace.open()]
        events[-1]["retrieval_call_id"] = "different-call"
        trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    else:
        path = cases[0] / "replay.json"
        replay = read_json(path)
        replay["result"]["attempt"] = 2
        write_json(path, replay)
    with pytest.raises(ValueError):
        summarize(dispatch)


def test_new_acquisition_before_handoff_input_is_not_mistaken_for_history(tmp_path):
    dispatch, cases = fixture(tmp_path)
    trace = cases[0] / "runtime/bank/request-trace-1.jsonl"
    events = [json.loads(line) for line in trace.open()]
    events.insert(1, {"event": "memory_control_step", "phase": "decision_output",
                      "selected": "new-read", "actions": [{"id": "new-read", "kind": "READ"}],
                      "retrieval_call_id": "target"})
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ValueError, match="exactly one delivery decision"):
        summarize(dispatch)


@pytest.mark.parametrize(
    "mutation", ["state", "menu", "acquisition", "receipt", "wire", "provider"]
)
def test_actual_condition_or_delivery_drift_is_rejected(tmp_path, mutation):
    dispatch, cases = fixture(tmp_path)
    case = cases[1]
    trace = case / "runtime/bank/request-trace-1.jsonl"
    events = [json.loads(line) for line in trace.open()]
    if mutation == "state":
        events[1]["state"]["task"]["request"] = "different purpose"
    elif mutation == "menu":
        events[1]["actions"].reverse()
    elif mutation == "acquisition":
        events[-1]["actions"] = [{"id": "new-read", "kind": "READ"}]
        events[-1]["selected"] = "new-read"
    elif mutation == "receipt":
        p = case / "replay.json"
        replay = read_json(p)
        replay["result"]["messages"][0]["content"] = '{"evidence":["unexecuted"]}'
        write_json(p, replay)
    elif mutation == "wire":
        p = case / "host-readout/request.json"
        wire = read_json(p)
        wire["messages"][0]["content"] = "different context"
        write_json(p, wire)
    else:
        p = case / "host-readout/trace.jsonl"
        event = json.loads(p.read_text())
        event["request"]["max_tokens"] = 128
        p.write_text(json.dumps(event) + "\n")
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ValueError):
        summarize(dispatch)


def test_failed_and_unexecuted_branches_keep_denominator_and_no_answers(tmp_path):
    dispatch, cases = fixture(tmp_path)
    p = cases[0] / "host-readout/readout.json"
    report = read_json(p)
    report.update(status="FAILED", error="incomplete provider response")
    del report["answer"]
    write_json(p, report)
    shutil.rmtree(cases[1])
    result = summarize(dispatch)
    assert result["planned_positions"] == 2
    assert result["positions"][0]["readout"]["answer"] is None
    assert result["positions"][1]["execution"] == "NOT_EXECUTED"
    assert result["comparisons"][0]["actual_packets_equal"] is None


def test_stale_or_different_original_readout_frame_is_rejected(tmp_path):
    dispatch, _ = fixture(tmp_path)
    frame = copy.deepcopy(read_json(tmp_path / "frame.json"))
    frame["request"]["messages"][0]["content"] = "later context"
    write_json(tmp_path / "run/readout-frames/00000.json", frame)
    with pytest.raises(ValueError, match="pre-execution binding"):
        summarize(dispatch)


def test_identical_delivery_with_different_answers_is_not_a_policy_quality_label(tmp_path):
    dispatch, cases = fixture(tmp_path)
    left, right = cases
    replay = read_json(right / "replay.json")
    replay["result"] = read_json(left / "replay.json")["result"]
    write_json(right / "replay.json", replay)
    trace = right / "runtime/bank/request-trace-1.jsonl"
    events = [json.loads(line) for line in trace.open()]
    events[-2]["selected"] = events[-1]["selected"] = "all"
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    wire = read_json(left / "host-readout/request.json")
    write_json(right / "host-readout/request.json", wire)
    p = right / "host-readout/trace.jsonl"
    event = json.loads(p.read_text())
    event["request"] = wire
    p.write_text(json.dumps(event) + "\n")
    result = summarize(dispatch)
    pair = result["comparisons"][0]
    assert pair["actual_packets_equal"] and pair["actual_readout_requests_equal"]
    assert pair["quality_comparison"] == "unreviewed"
    assert [r["readout"]["answer"] for r in result["positions"]] == ["4312", "unknown"]


def test_actual_replay_cli_and_readout_artifacts_are_accepted(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from test_frozen_control_steps import captured_after
    from test_frozen_retrieval import native_request
    from test_given_retrieval import source
    from test_v13_5_functional_integration import prepared, scripted

    from milai_lab.runners.frozen_host_readout import prepare_readout
    from milai_lab.runners.functional import message
    from milai_lab.runners.handoff_comparison import prepare_handoff_call
    from run_frozen_retrieval_calls import main as replay_main

    original = prepared(
        tmp_path,
        native=True,
        memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1",
        retrieval_tool="rich",
        business_tools=[],
        dynamic_memory=True,
        edit_interface_version="I2",
        memory_view_mode="staged",
        additional_reads=8,
        memory_control={
            "policy": "fixed_context",
            "max_control_steps": 6,
            "delivery_selection": True,
        },
    )

    def reply(wire, number):
        if number == 1:
            return native_request(
                {
                    "query": "Cedar code",
                    "read_goal": {
                        "evidence": ["original_source"],
                        "required_points": ["Cedar", "code"],
                    },
                }
            )
        packet = json.loads(
            next(m["content"] for m in reversed(wire["messages"]) if m["role"] == "tool")
        )
        return {"role": "assistant", "content": "4312" if packet["evidence"] else "unknown"}

    scripted(monkeypatch, reply, native=True)
    snapshots = tmp_path / "original-captures"
    result = message(
        original,
        bank="bank",
        owner="alice",
        session="host",
        message_id="q",
        content="Find the Cedar code",
        incoming_sources=[source()],
        retrieval_snapshots=snapshots,
        retrieval_step_snapshots=True,
    )
    assert result["status"] == "COMPLETED", result.get("error")
    captured = captured_after(snapshots, "READ")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    capture = inputs / "family--original"
    prepare_handoff_call(captured, capture, source_version="test-v1")
    frame_path = tmp_path / "actual-frame.json"
    write_json(frame_path, prepare_readout(capture))

    class Model:
        def __init__(self, *args, **kwargs):
            self.counters = {"forwards": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            return {"choice": "handoff_select_none"}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    policies = [
        {
            "name": name,
            "capture": capture.name,
            "policy": {
                "policy": policy,
                "routing": "handoff_only",
                "reads": 4,
                "checkpoint": "scripted",
                "device": "cpu",
                "state_projection": "shared_actions",
            },
        }
        for name, policy in [("rules", "rules"), ("jev", "laya")]
    ]
    recipe = tmp_path / "actual-policies.json"
    write_json(recipe, policies)
    output = tmp_path / "actual-run"
    argv = [
        "entry",
        str(inputs),
        str(recipe),
        str(output),
        "--source-version",
        "test-v1",
        "--host-readout",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    replay_main()
    report = summarize(
        {
            "output": str(output),
            "argv": argv,
            "source_version": "test-v1",
            "planned_branches": 2,
            "pairs": [
                {
                    "family": "family",
                    "condition": "original",
                    "capture": str(capture),
                    "readout_frame": str(frame_path),
                    "arm_names": ["rules", "jev"],
                }
            ],
        }
    )
    assert report["execution_counts"] == {"RESULT_RETAINED": 2}
    assert report["comparisons"][0]["matched_completed_tools"]
    assert report["comparisons"][0]["actual_packets_equal"] is False
    assert all(
        row["readout"]["actual_completed_provider_input_bound"] for row in report["positions"]
    )
