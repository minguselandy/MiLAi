"""Fresh request arms consume fixed slots even when an actual attempt is absent or fails."""

import copy
import json
import sys
from pathlib import Path

import pytest
from test_known_budget_requests import completed_two_read_fixture

from allocate_known_budget_prefixes import allocate_record, resolve_record
from milai_lab.harness.artifact_io import read_json, write_json
from prepare_known_budget_requests import prepare_pair
from run_known_budget_request import run_condition


def fixture(tmp_path, monkeypatch, *, native=True):
    host, _, record, wires = completed_two_read_fixture(tmp_path, monkeypatch, native=native)
    record["primary_public_position"] = "original"
    preparation = prepare_pair(host, record, message_id="budget-probe", low=512, high=1024)
    return record, preparation, wires


def test_actual_pair_reserves_four_and_never_exports_original_second_read(tmp_path, monkeypatch):
    record, preparation, wires = fixture(tmp_path, monkeypatch)
    allocation = allocate_record(record, preparation)
    assert [s["role"] for s in allocation["slots"]] == [
        "initial", "first_read", "fresh_known_baseline", "fresh_known_limited"]
    second = record["selection"]["slots"]["second_read"]["capture"]
    assert allocation["second_read_provenance_only"]["capture"] == second
    before = copy.deepcopy(allocation)
    outputs = {arm: tmp_path / arm for arm in ["baseline", "limited"]}
    for arm, output in outputs.items():
        run_condition(preparation, output, arm)
    resolved = resolve_record(allocation, outputs)
    assert allocation == before
    assert len(wires) == 2
    assert len({s["capture"] for s in resolved["slots"]}) == 4
    assert second not in [s["capture"] for s in resolved["slots"]]
    assert all(s["status"] == "REACHED" for s in resolved["slots"])
    assert resolved["pair_comparison"]["same_known_evidence"]
    assert resolved["quality_labels"] == []
    from prepare_view_feedback_branches import fresh_inventory, select_allocated_states

    report = {"status": "FOUR_SLOT_ALLOCATION_RESOLVED_NO_QUALITY_LABELS", "records": [resolved]}
    inventory = fresh_inventory(report, "train")
    for role in ["initial", "first_read", "second_read"]:
        slot = record["selection"]["slots"][role]
        inventory.append({"path": slot["capture"], "capture": role, "family": record["family"],
            "split": "train", "collection_policy": record["collector"],
            "control_step": slot["control_step"], "eligible": True})
    selected, cells = select_allocated_states(inventory, report, [record["family"]], "train")
    assert len(selected) == len(cells) == 4
    assert second not in [e["path"] for e in selected]


@pytest.mark.parametrize("native", [True, False])
def test_controlled_readout_preserves_actual_known_input_and_uses_real_branch_receipt(
    tmp_path, monkeypatch, native,
):
    from milai_lab.runners.frozen_host_readout import run_readout
    from milai_lab.runners.frozen_retrieval import replay_call
    from prepare_known_budget_readout import prepare_controlled_readout
    from run_frozen_retrieval_calls import declared_readout_frame

    _, preparation, wires = fixture(tmp_path, monkeypatch, native=native)
    run = run_condition(preparation, tmp_path / "baseline", "baseline")
    captured = Path(run["call_captures"][0])
    original_files = {p.relative_to(captured): p.read_bytes()
                      for p in captured.rglob("*") if p.is_file()}
    frame = prepare_controlled_readout(preparation, captured)
    closed = read_json(Path(preparation["closed_capture"]) / "closed.json")
    assert frame["request"]["messages"][:-2] == closed["final_context"]["messages"]
    assert frame["source_final_request"] == wires[1]
    assert not frame["host_request_generated"] and not frame["original_answer_loaded_as_input"]
    assert frame["request"]["messages"][-1]["content"] == ""
    frame_file = tmp_path / "frame.json"
    write_json(frame_file, frame)
    policies = [{"capture": captured.name, "host_readout_frame": str(frame_file)}]
    assert declared_readout_frame(captured, policies) == frame
    replay = tmp_path / "branch"
    result = replay_call(captured, replay, {"policy": "fixed", "reads": 0},
                         source_version="mechanical")
    assert result["status"] == "COMPLETED"
    readout = run_readout(captured, replay, tmp_path / "readout", frame,
                         source_version="mechanical")
    assert readout["status"] == "COMPLETED" and len(wires) == 3
    assert wires[-1]["messages"][:-2] == closed["final_context"]["messages"]
    assert wires[-1]["messages"][-1]["content"] == result["messages"][0]["content"]
    if native:
        assert wires[-1]["tool_choice"] == "none"
    else:
        schema = wires[-1]["response_format"]["json_schema"]["schema"]
        assert set(schema["properties"]) == {"answer"}
    assert readout["generation_calls_after"] == readout["generation_calls_before"] + 1
    assert readout["budget_after"]["generation_requests"] == (
        readout["budget_before"]["generation_requests"] + 1)
    assert original_files == {p.relative_to(captured): p.read_bytes()
                              for p in captured.rglob("*") if p.is_file()}


def test_cli_branch_preparation_keeps_denominators_and_declared_frames(tmp_path, monkeypatch):
    import prepare_view_feedback_branches

    record, preparation, wires = fixture(tmp_path, monkeypatch)
    allocation = allocate_record(record, preparation)
    fixed_path = tmp_path / "allocation.json"
    collection = tmp_path / "collection"
    write_json(fixed_path, {"status": "FOUR_SLOT_ALLOCATION_FIXED_BEFORE_FRESH_EXECUTION",
        "collection": str(collection), "records": [allocation]})
    outputs = {arm: tmp_path / arm for arm in ["baseline", "limited"]}
    for arm, output in outputs.items():
        run_condition(preparation, output, arm)
    resolved_path = tmp_path / "resolved.json"
    write_json(resolved_path, {"status": "FOUR_SLOT_ALLOCATION_RESOLVED_NO_QUALITY_LABELS",
        "input": str(fixed_path), "collection": str(collection),
        "records": [resolve_record(allocation, outputs)]})
    write_json(collection / "driver.json", {"status": "COMPLETED", "source_version": "mechanical"})
    write_json(collection / "fixture.json", {"histories": [{"id": "bank", "continuous": True,
        "source_group": record["family"], "split": "train", "requests": [{"id": "original"}]}]})
    calls = collection / "frozen-retrieval-calls"
    calls.symlink_to(Path(record["selection"]["capture"]).parent, target_is_directory=True)
    output = tmp_path / "branches"
    monkeypatch.setattr(sys, "argv", ["prepare", str(collection), "--groups", record["family"],
        "--prefix-allocation", str(resolved_path), "--include-control-steps",
        "--output", str(output)])
    prepare_view_feedback_branches.main()
    report = read_json(output / "selection.json")
    assert report["states"] == report["per_group_maximum"] == 4
    assert len(report["prefix_cells"]) == 4 and len(report["controlled_readout_frames"]) == 2
    assert len(wires) == 2 and not report["operation_labels_added"]
    second = record["selection"]["slots"]["second_read"]["capture"]
    assert second in [e["path"] for e in report["inventory"]]
    assert second not in [e["path"] for e in report["selected"]]
    policies = read_json(output / "policies.json")
    for policy in policies:
        assert ("host_readout_frame" in policy) == policy["capture"].startswith("fresh--")
    raw = (output / "raw-selected-states.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in raw]
    assert len(rows) == 4


def test_unexecuted_and_failed_without_state_keep_reserved_cells(tmp_path, monkeypatch):
    record, preparation, _ = fixture(tmp_path, monkeypatch)
    allocation = allocate_record(record, preparation)
    outputs = {arm: tmp_path / arm for arm in ["baseline", "limited"]}
    pending = resolve_record(allocation, outputs)
    assert [s["status"] for s in pending["slots"][-2:]] == ["NOT_EXECUTED"] * 2
    limited = preparation["conditions"][1]
    write_json(outputs["limited"] / "run.json", {
        "status": "FAILED_RETAINED", "family": record["family"], "arm": "limited",
        "request": limited["request"], "source_snapshot": preparation["source_snapshot"],
        "call_captures": [], "error": "failure before initial observation"})
    resolved = resolve_record(allocation, outputs)
    assert [s["capture"] for s in resolved["slots"][-2:]] == [None, None]
    assert resolved["slots"][-1]["status"] == "NO_UNIQUE_ACTUAL_CALL"
    assert resolved["slots"][-1]["run_status"] == "FAILED_RETAINED"


def test_pre_execution_ineligibility_keeps_original_three(tmp_path, monkeypatch):
    record, preparation, _ = fixture(tmp_path, monkeypatch)
    preparation.update(status="INELIGIBLE_RETAINED", conditions=[])
    allocation = allocate_record(record, preparation)
    resolved = resolve_record(allocation, {})
    assert [s["role"] for s in resolved["slots"]] == [
        "initial", "first_read", "second_read", "condition_unavailable"]
    assert resolved["slots"][2]["capture"] == record["selection"]["slots"]["second_read"]["capture"]
    assert resolved["slots"][3]["status"] == "MISSING"
    with pytest.raises(ValueError, match="pre-execution"):
        resolve_record(allocation, {"baseline": tmp_path})


def test_wrong_arm_identity_is_rejected_without_replacement(tmp_path, monkeypatch):
    record, preparation, _ = fixture(tmp_path, monkeypatch)
    allocation = allocate_record(record, preparation)
    outputs = {arm: tmp_path / arm for arm in ["baseline", "limited"]}
    report = run_condition(preparation, outputs["baseline"], "baseline")
    captured = Path(report["call_captures"][0])
    call = read_json(captured / "call.json")
    call["request"]["limits"]["max_return_tokens"] = 999
    write_json(captured / "call.json", call)
    with pytest.raises(ValueError, match="identity"):
        resolve_record(allocation, outputs)


def test_collection_prepares_all_families_before_executing_any_fresh_arm(tmp_path, monkeypatch):
    from prepare_known_budget_collection import prepare_collection

    record, preparation, wires = fixture(tmp_path, monkeypatch)
    collection = tmp_path / "collection"
    collection.mkdir()
    (collection / "frozen-host-messages").symlink_to(
        Path(preparation["closed_capture"]).parent, target_is_directory=True)
    missing = {**record, "family": "missing-family", "status": "NO_ACTUAL_PRIMARY_CALL",
               "selection": None}
    selection = {"status": "PRIMARY_PREFIX_INVENTORY_CREATED;NO_BRANCH_QUALITY_LABELS",
                 "collection": str(collection), "records": [record, missing]}
    output = tmp_path / "prepared"
    report = prepare_collection(selection, output, low=512, high=1024,
                                runtime_python=sys.executable)
    assert report["family_units"] == 2 and report["fresh_pair_eligible"] == 1
    assert len(report["jobs"]) == 2 and len(wires) == 2
    assert not (output / "fresh-requests").exists()
    allocated = read_json(output / "allocation.json")["records"]
    assert [len(r["slots"]) for r in allocated] == [4, 4]
    assert allocated[1]["slots"][0]["status"] == "MISSING"
    assert read_json(output / "arm-output-map.json")["missing-family"] == {}
    for job in report["jobs"]:
        assert job["status"] == "NOT_EXECUTED" and not job["automatic_retry"]
