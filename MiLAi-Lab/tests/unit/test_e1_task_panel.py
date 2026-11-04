"""Planned source denominators and real reached states cannot be repaired by selection."""
import copy

import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control import MemoryControlState
from prepare_e1_task_panel import prepare_panel


def cohort(tmp_path):
    histories = [{"id": name, "source_group": name, "split": "dev",
        "requests": [{"id": "q", "content": "Find the fact"}]} for name in ("A", "B", "C")]
    write_json(tmp_path / "fixture.json", {"histories": histories})
    write_json(tmp_path / "driver.json", {"status": "COMPLETED_WITH_FAILURES", "completed": [
        {"history": name, "request": "q", "conditional_readout": {"status": "FAILED"}}
        for name in ("A", "B")]})
    write_json(tmp_path / "input-freeze.json", {"config": {
        "memory_control": {"policy": "fixed_context"}}})
    state = MemoryControlState(task={"request": "Find the fact"}).project()
    actions = [{"id": key, "kind": kind, "target": "actual target", "parameters": {}}
               for key, kind in (("read", "READ"), ("stop", "HANDOFF"))]
    for name, selected in (("A", "stop"), ("B", "read")):
        path = tmp_path / "frozen-retrieval-calls" / name
        call = {"status": "ORIGINAL_COMPLETED", "call_id": name,
            "bank": name + "-q", "source_root": str(tmp_path), "host_request_generated": False,
            "public_message": {"message_id": "q", "content": "Find the fact"},
            "initial_observation": state, "initial_actions": actions,
            "control_events": [{"phase": "decision_output", "step": 1,
                                "selected": selected, "before": state, "actions": actions}]}
        write_json(path / "call.json", call)
        write_json(path / "steps/step-0001/call.json", {**call, "control_step": 1})
    return {"selection": {"source_ids": ["A", "B", "C"]}}


def test_failed_readout_and_missing_states_keep_the_full_denominator(tmp_path):
    protocol = cohort(tmp_path)
    result = prepare_panel(tmp_path, protocol)
    assert len(result["positions"]) == 3 and len(result["rows"]) == 1
    assert [p["status"] for p in result["positions"]] == [
        "ACTUAL_PRE_HANDOFF_EXPORTED", "NO_REACHED_FINAL_HANDOFF", "MISSING_ORIGINAL_CAPTURE"]
    assert result["positions"][0]["baseline_readout"]["status"] == "FAILED"
    row = result["rows"][0]
    assert row["gold"] == {} and list(row["questions"]["next"]["criteria"]) == ["read", "stop"]
    assert "baseline_readout" not in row["state"]


def test_different_source_order_or_live_collection_cannot_be_admitted(tmp_path):
    protocol = cohort(tmp_path)
    changed = copy.deepcopy(protocol)
    changed["selection"]["source_ids"].reverse()
    with pytest.raises(ValueError, match="source order"):
        prepare_panel(tmp_path, changed)
    write_json(tmp_path / "driver.json", {"status": "RUNNING"})
    with pytest.raises(ValueError, match="close"):
        prepare_panel(tmp_path, protocol)


def test_last_handoff_snapshot_cannot_be_reconstructed_from_an_earlier_state(tmp_path):
    protocol = cohort(tmp_path)
    path = tmp_path / "frozen-retrieval-calls/A/steps/step-0001/call.json"
    call = read_json(path)
    call["initial_observation"]["task"]["request"] = "Another request"
    write_json(path, call)
    with pytest.raises(ValueError, match="snapshot differs"):
        prepare_panel(tmp_path, protocol)
