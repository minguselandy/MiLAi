"""Third-arm audits retain failures and distinguish actual policy changes from answer noise."""

import json
import shutil

import pytest
from test_handoff_comparison_summary import fixture as paired_fixture

from current_raw_packet_tie import PROFILE
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_host_readout import substitute_receipt
from summarize_current_raw_packet_tie import summarize


def fixture(tmp_path, changed=True):
    old_dispatch, cases = paired_fixture(tmp_path)
    old_case = tmp_path / "original-rule"
    shutil.copytree(cases[0], old_case)
    case = cases[0]
    if changed:
        shutil.rmtree(case)
        shutil.copytree(cases[1], case)
    shutil.rmtree(cases[1])
    root = tmp_path / "run"
    capture = tmp_path / "captures/family--original"
    call = read_json(capture / "call.json")
    policies = read_json(tmp_path / "policies.json")[:1]
    write_json(tmp_path / "policies.json", policies)
    cohort = read_json(root / "cohort.json")
    cohort["policies"] = policies
    write_json(root / "cohort.json", cohort)
    driver = read_json(root / "driver.json")
    driver["planned_positions"] = 1
    write_json(root / "driver.json", driver)
    for path in (old_case, case):
        replay = read_json(path / "replay.json")
        replay["policy"] = policies[0]["policy"]
        packet = replay["result"]["retrieval_result"]
        packet["termination_reason"] = "policy_handoff"
        receipt = replay["result"]["messages"][0]
        receipt["content"] = json.dumps(packet)
        write_json(path / "replay.json", replay)
        frame = read_json(tmp_path / "frame.json")
        wire = substitute_receipt(frame, receipt)
        write_json(path / "host-readout/request.json", wire)
        trace_path = path / "host-readout/trace.jsonl"
        event = json.loads(trace_path.read_text())
        event["request"] = wire
        trace_path.write_text(json.dumps(event) + "\n")
    selected = call["initial_actions"][int(changed)]
    check = {"profile": PROFILE, "baseline": "all", "selected": selected["id"],
             "changed": changed, "scope": "test"}
    argv = ["python", "-u", "wrapper.py", str(tmp_path / "wrapper.json"),
            "entry.py", str(capture.parent), str(tmp_path / "policies.json"), str(root)]
    write_json(tmp_path / "wrapper.json", {
        "status": "COMPLETED", "profile": PROFILE, "selector_restored": True,
        "intervention_used": False, "automatic_retry": False, "argv": argv[4:],
        "recipes": str(tmp_path / "policies.json"),
        "policy_calls": [{**check, "state": call["initial_observation"],
                          "actions": call["initial_actions"]}],
    })
    return {
        "output": str(root), "base_runtime_source_version": "test-v1",
        "method_profile": PROFILE, "wrapper_receipt": str(tmp_path / "wrapper.json"),
        "argv": argv, "states": 1, "planned_branches": 1, "families": 1,
        "predeclared_changed_choices": int(changed),
        "pairs": [{**old_dispatch["pairs"][0], "arm_name": "rules",
                   "original_rule_case": str(old_case),
                   "original_rule_action": call["initial_actions"][0],
                   "predeclared_variant_action": selected, "changed_choice": changed,
                   "selector_check": check}],
    }, case


@pytest.mark.parametrize("changed", [True, False])
def test_changed_and_unchanged_inputs_are_bound_without_quality_claims(tmp_path, changed):
    dispatch, _ = fixture(tmp_path, changed)
    report = summarize(dispatch)
    row, = report["positions"]
    assert row["actual_packets_equal_to_rule"] is not changed
    assert row["actual_readout_requests_equal_to_rule"] is not changed
    assert row["selector_call_bound"]
    assert row["semantic_grade"] == row["delivery_grade"] == "unknown"


@pytest.mark.parametrize("mutation", ["selector", "action", "frame", "denominator", "marker"])
def test_execution_drift_is_rejected(tmp_path, mutation):
    dispatch, case = fixture(tmp_path)
    if mutation == "selector":
        path = tmp_path / "wrapper.json"
        data = read_json(path)
        data["policy_calls"][0]["baseline"] = "different"
        write_json(path, data)
    elif mutation == "action":
        dispatch["pairs"][0]["predeclared_variant_action"]["target"] = "different"
    elif mutation == "frame":
        path = tmp_path / "frame.json"
        data = read_json(path)
        data["request"]["messages"][0]["content"] = "different"
        write_json(path, data)
        write_json(tmp_path / "run/readout-frames/00000.json", data)
    elif mutation == "denominator":
        dispatch["planned_branches"] = 2
    else:
        path = case / "replay.json"
        data = read_json(path)
        packet = data["result"]["retrieval_result"]
        packet["termination_reason"] = "intervention_handoff"
        data["result"]["messages"][0]["content"] = json.dumps(packet)
        write_json(path, data)
    with pytest.raises(ValueError):
        summarize(dispatch)


def test_incomplete_provider_response_is_bound_without_promoting_answer(tmp_path):
    dispatch, case = fixture(tmp_path)
    path = case / "host-readout/readout.json"
    data = read_json(path)
    data.update(status="FAILED", answer=None, error="length")
    write_json(path, data)
    row, = summarize(dispatch)["positions"]
    assert row["readout"]["answer"] is None
    assert row["readout"]["incomplete_provider_response_bound"]
    trace_path = case / "host-readout/trace.jsonl"
    event = json.loads(trace_path.read_text())
    event["response_text"] = '{}'
    trace_path.write_text(json.dumps(event) + "\n")
    with pytest.raises(ValueError, match="Incomplete response"):
        summarize(dispatch)


@pytest.mark.parametrize("entered", [True, False])
def test_unclosed_or_unexecuted_case_keeps_declared_denominator(tmp_path, entered):
    dispatch, case = fixture(tmp_path)
    shutil.rmtree(case)
    if entered:
        case.mkdir(parents=True)
    path = tmp_path / "wrapper.json"
    wrapper = read_json(path)
    wrapper.update(status="FAILED", policy_calls=[])
    write_json(path, wrapper)
    path = tmp_path / "run/driver.json"
    driver = read_json(path)
    driver["status"] = "FAILED"
    write_json(path, driver)
    report = summarize(dispatch)
    row, = report["positions"]
    assert report["planned_positions"] == 1
    assert row["execution"] == ("ENTERED_WITHOUT_CLOSED_RESULT" if entered else "NOT_EXECUTED")
    assert row["readout"] is row["tool"] is None
    assert row["semantic_grade"] == "unknown"
