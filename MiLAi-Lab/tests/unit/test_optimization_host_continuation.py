import copy
import sys
from pathlib import Path

import pytest
from test_original_feedback_host import bound_fixture, completed_arm

import prepare_optimization_host_continuation as continuation
import run_bound_optimization_host as runner
from milai_lab.harness.artifact_io import read_json, write_json
from prepare_optimization_host_continuation import prepare, validate_continuation
from summarize_optimization_host_continuations import summarize_all, summarize_arm
from summarize_original_feedback_host import position_bank


def retain_failed_attempt(dispatch_path, arm_id, history_id, request_id, *, start=1):
    dispatch = read_json(dispatch_path)
    arm = next(a for a in dispatch["arms"] if a["id"] == arm_id)
    result_path = completed_arm(dispatch, arm, start=start)
    root = Path(arm["output"])
    fixture = read_json(Path(dispatch["study"]["histories"]))
    history = next(h for h in fixture["histories"] if h["id"] == history_id)
    request = next(q for q in history["requests"] if q["id"] == request_id)
    bank = position_bank(history, request)
    native = read_json(root / "driver.json")
    native["planned_positions"] = dispatch["study"]["positions_per_unique_arm"]
    native["completed"][0].update(history=history_id, request=request_id, status="FAILED")
    native["active"] = {"history": history_id, "request": request_id}
    write_json(root / "driver.json", native)
    result = read_json(result_path)
    result.update(status="FAILED", bank=bank, message_id=request_id)
    result.pop("final_answer")
    write_json(result_path, result)
    write_json(
        Path(str(root) + "-inference.json"),
        {
            "status": "FAILED_RETAINED",
            "native_decision_module_file": str(
                Path(dispatch["study"]["runtime"]) / "src/milai_lab/providers/laya_local.py"
            ),
            "model_loads": [],
        },
    )
    owner = dispatch_path.parent / "orchestration" / arm_id / "driver.json"
    write_json(
        owner,
        {
            "status": "FAILED_RETAINED",
            "pid": 90000001,
            "child_pid": 90000002,
            "dispatch": str(dispatch_path),
            "arm_id": arm_id,
            "output": arm["output"],
            "argv": arm["argv"],
            "environment": arm["environment"],
        },
    )
    write_json(
        root / (arm["policy"] + "-rich") / "bank-index.json",
        [{"identity": {"bank": bank, "owner": "development-user"}, "id": result_path.parent.name}],
    )
    return root


def fixture(tmp_path, *, continuous=False):
    dispatch = bound_fixture(tmp_path)
    dispatch.update(
        status="OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED",
        arms=dispatch["arms"][:6],
        unique_arms=6,
        planned_positions=96,
    )
    dispatch["study"].update(
        positions_per_unique_arm=16,
        execution_id="original-dev",
        task_conditions={},
        dispatch_scope="Synthetic development cohort",
    )
    path = tmp_path / "bound/dispatch.json"
    data_path = Path(dispatch["study"]["histories"])
    data = read_json(data_path)
    data["histories"][0]["continuous"] = continuous
    write_json(data_path, data)
    write_json(path, dispatch)
    arm_id = "jev_initialization"
    root = retain_failed_attempt(path, arm_id, "family-0", "first")
    return path, arm_id, root


def test_only_never_entered_independent_bank_tasks_are_prepared(tmp_path):
    parent, arm_id, root = fixture(tmp_path)
    original = read_json(parent)
    result = prepare(parent, arm_id)
    assert result["remaining_positions"] == 15 and result["excluded_attempts"] == 1
    assert result["original_arm_positions"] == 16 and result["original_cohort_positions"] == 96
    dispatch_path = Path(result["dispatch"])
    child = read_json(dispatch_path)
    assert child["arms"][0]["checkpoint"] == original["arms"][2]["checkpoint"]
    assert read_json(Path(child["arms"][0]["config"])) == read_json(
        Path(original["arms"][2]["config"])
    )
    data = read_json(Path(child["study"]["histories"]))
    assert [q["id"] for q in data["histories"][0]["requests"]] == ["later"]
    assert read_json(root / "driver.json")["completed"][0]["status"] == "FAILED"
    validate_continuation(dispatch_path, for_launch=True)
    with pytest.raises(ValueError, match="no closed owner"):
        prepare(parent, arm_id)


def test_touched_continuous_bank_cannot_be_cold_restarted(tmp_path):
    parent, arm_id, _ = fixture(tmp_path, continuous=True)
    with pytest.raises(ValueError, match="touched bank"):
        prepare(parent, arm_id)
    assert not (parent.parent / "continuations").exists()


def test_entered_without_a_retained_result_is_excluded(tmp_path):
    parent, arm_id, root = fixture(tmp_path)
    driver = read_json(root / "driver.json")
    driver["active"] = {"history": "family-0", "request": "later"}
    write_json(root / "driver.json", driver)
    result = prepare(parent, arm_id)
    assert result["remaining_positions"] == 14 and result["excluded_attempts"] == 2


@pytest.mark.parametrize("change", ["request", "checkpoint", "new_prior_entry"])
def test_admission_rechecks_conditions_and_unattempted_identity(tmp_path, change):
    parent, arm_id, root = fixture(tmp_path)
    result = prepare(parent, arm_id)
    path = Path(result["dispatch"])
    dispatch = read_json(path)
    if change == "request":
        file = Path(dispatch["study"]["histories"])
        data = read_json(file)
        data["histories"][0]["requests"][0]["content"] = "Changed public task"
        write_json(file, data)
    elif change == "checkpoint":
        file = Path(dispatch["arms"][0]["config"])
        data = read_json(file)
        data["entrypoints"]["functional"]["memory_control"]["checkpoint"] = "different"
        write_json(file, data)
    else:
        file = root / "driver.json"
        data = read_json(file)
        data["active"] = {"history": "family-0", "request": "later"}
        write_json(file, data)
    with pytest.raises(ValueError, match="exact unattempted"):
        validate_continuation(path, for_launch=True)


def test_aggregation_keeps_failed_prefix_and_original_denominators(tmp_path):
    parent, arm_id, _ = fixture(tmp_path)
    result = prepare(parent, arm_id)
    pending = summarize_arm(parent, arm_id, [])
    assert pending["planned_positions"] == 16 and pending["parent_cohort_planned_positions"] == 96
    assert pending["attempted_positions"] == 1 and pending["native_failed"] == 1
    assert pending["execution_counts"]["NOT_EXECUTED"] == 15
    segment = Path(result["dispatch"])
    retain_failed_attempt(segment, arm_id, "family-0", "later", start=3)
    combined = summarize_arm(parent, arm_id, [])
    assert combined["original_native_status"] == "FAILED"
    assert combined["attempted_positions"] == 2 and combined["native_failed"] == 2
    assert combined["execution_counts"]["NOT_EXECUTED"] == 14
    assert combined["semantic_counts"] == {"unknown": 16}
    second = prepare(parent, arm_id)
    assert second["remaining_positions"] == 14 and second["excluded_attempts"] == 2
    with pytest.raises(ValueError, match="stale"):
        validate_continuation(segment, for_launch=True)
    cohort = summarize_all(parent, [])
    assert cohort["planned_positions"] == 96 and len(cohort["positions"]) == 96
    assert read_json(parent)["planned_positions"] == 96


def test_arm_report_does_not_hide_another_live_arm_in_a_cohort_report(tmp_path):
    parent, arm_id, _ = fixture(tmp_path)
    dispatch = read_json(parent)
    other = copy.deepcopy(dispatch["arms"][0])
    write_json(Path(other["output"]) / "driver.json", {"status": "RUNNING"})
    assert summarize_arm(parent, arm_id, [])["planned_positions"] == 16
    with pytest.raises(ValueError, match="Close actual Host jobs"):
        summarize_all(parent, [])


def test_coordinator_revalidates_continuation_before_any_child_start(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "active_model_owners", lambda: [])
    monkeypatch.setattr(runner, "read_json", lambda _: {"continuation": {}})

    def reject(path, *, for_launch):
        assert path == tmp_path / "dispatch.json" and for_launch
        raise ValueError("continuation admission checked")

    monkeypatch.setattr(continuation, "validate_continuation", reject)
    monkeypatch.setattr(sys, "argv", ["runner", str(tmp_path / "dispatch.json"),
                                    "arm", str(tmp_path / "owner")])
    with pytest.raises(ValueError, match="continuation admission checked"):
        runner.main()
    assert not (tmp_path / "owner").exists()
