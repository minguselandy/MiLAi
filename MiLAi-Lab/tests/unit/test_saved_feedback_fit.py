"""Synthetic reload artifacts prove joins, masks and selection; no models are run."""

import copy
import json
from pathlib import Path

import pytest
from test_operation_curve_analysis import row, tensor_file

from analyze_saved_feedback_fit import select, verify_retention
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control_learning import score_operation_predictions
from retrieval_feedback import score_feedback


def prediction(length, prefer_read):
    return {"choice": "read" if prefer_read else "stop",
            "logits": {"read": float(prefer_read), "stop": float(not prefer_read)},
            "probabilities": {"read": .75 if prefer_read else .25,
                              "stop": .25 if prefer_read else .75},
            "input_tokens": length["sequence_tokens"], "truncated": False}


def fixture(tmp_path):
    data, native_root = tmp_path / "data", tmp_path / "native"
    data.mkdir()
    old = [row("operation-a", "A", "dev", 1), row("operation-b", "B", "dev", 2, False)]
    feedback = [row("legacy", "A", "dev", 0, False), row("new", "B", "dev", 0, False)]
    for i, item in enumerate(feedback):
        item["metadata"].update(collection_policy="rules", control_step=1)
        item["feedback"] = {"comparisons": [{"left": "read", "right": "stop", "answer": "left",
                                               "delivery": "right" if i == 0 else "unknown"}]}
    files = {"dev": old, "feedback": feedback, "legacy": feedback[:1], "combined": old+feedback}
    for name, values in files.items():
        (data / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in values))
    write_json(data / "protocol.json", {"feedback_dev": {"old_file": str(data / "legacy.jsonl")}})
    write_json(data / "fit-plan.json", {"protocol": str(data / "protocol.json")})
    lengths = {name: [{"event_id": r["metadata"]["event_id"], "question": "next",
                      "sequence_tokens": 10+i, "state_tokens_dropped": 0, "head_tokens_dropped": 0}
                     for i, r in enumerate(values)]
               for name, values in [("dev", old), ("feedback-dev", feedback)]}
    write_json(native_root / "lengths.json", lengths)
    write_json(native_root / "run.json", {"status": "COMPLETED", "optimizer_updates": 4,
                                          "pid": 99999999})
    ledger = tmp_path / "ledger.json"
    write_json(ledger, {"compute": {}})
    conditions = {"device": "cpu", "visible_cuda_devices": "", "threads": 4,
                  "max_len": 16384, "head_max_len": 2048, "operation_state": "shared",
                  "reference_compile_override": False, "mha_fastpath_enabled": False,
                  "loaded_weight_dtype": "torch.float32"}
    jobs, curve = [], []
    for update in [0, 2, 4]:
        checkpoint = tmp_path / f"checkpoint-{update}"
        checkpoint.mkdir()
        tensor_file(checkpoint / "model.safetensors", update)
        predictions = [prediction(length, True) for length in lengths["feedback-dev"]]
        for i, predicted in enumerate(predictions):
            write_json(native_root / "feedback-dev" / str(update) / f"{i}.json", predicted)
        curve.append({"update": update, "checkpoint": str(checkpoint),
            "saved_tensor_dtypes": {"F16": 1}, "feedback-dev": {
                target: score_feedback(feedback, predictions, target)
                for target in ("answer", "delivery")}})
        jobs.append({"update": update, "job_id": f"job-{update}", "checkpoint": str(checkpoint),
                     "data": str(data / ("feedback.jsonl" if update == 2 else "combined.jsonl")),
                     "states": 2 if update == 2 else 4, "task": "memory_feedback",
                     "output": str(tmp_path / f"job-{update}"), "phase": f"reload-{update}"})
    retention = {**jobs[1], "job_id": "retention-2", "data": str(data / "dev.jsonl"),
                 "states": 2, "task": "memory_operation", "output": str(tmp_path / "retention-2"),
                 "phase": "retention-2"}
    plan = {"fit_plan": str(data / "fit-plan.json"), "original_ledger": str(ledger),
        "conditions": conditions, "inputs": {"old_operations": str(data / "dev.jsonl"),
            "feedback": str(data / "feedback.jsonl"), "combined": str(data / "combined.jsonl"),
            "old_operation_states": 2, "old_operation_labelled": 1, "feedback_states": 2,
            "legacy_feedback_states": 1}, "common_base": jobs[0], "fits": [{"run_id": "unit",
            "candidates": [{"update": 0, "shared_job": jobs[0]["job_id"]}, *jobs[1:]],
            "selection_targets": ["answer", "delivery"],
            "conditional_retention_jobs": [retention]}]}
    native = {"status": "TERMINAL_NATIVE_FEEDBACK_CURVE_VERIFIED;SAVED_RELOAD_SELECTION_PENDING",
        "run_id": "unit", "recipe": {"data": str(data), "output": str(native_root),
            "feedback_dev_source": str(data / "feedback.jsonl"), "operation_state": "shared",
            "max_len": 16384, "head_max_len": 2048, "planned_optimizer_updates": 4},
        "curve": curve, "in_memory_selection": {"answer": {"update": 0}, "delivery": {"update": 0}}}
    for job in jobs:
        emit_job(plan, native, job)
    return plan, native


def emit_job(plan, native, job):
    rows = read_jsonl(Path(job["data"]))
    lengths = read_json(Path(native["recipe"]["output"]) / "lengths.json")
    by_id = {r["event_id"]: r for values in lengths.values() for r in values}
    output = Path(job["output"])
    predictions = []
    for i, item in enumerate(rows):
        payload = project_operation_payload(item, plan["conditions"]["operation_state"])
        write_json(output / "calls" / str(i) / "input.json",
                   {k: payload[k] for k in ("state", "questions")})
        prefer_read = job["update"] == 0 or (job["update"] == 4
                                            and item["metadata"]["event_id"] != "new")
        predicted = prediction(by_id[item["metadata"]["event_id"]], prefer_read)
        predictions.append(predicted)
        write_json(output / "calls" / str(i) / "output.json", predicted)
    write_json(output / "run.json", {**plan["conditions"], "status": "COMPLETED", "pid": 99999999,
        "data": job["data"], "checkpoint": job["checkpoint"], "planned_states": len(rows),
        "completed_states": len(rows), "task": job["task"],
        "http_requests": 0, "calibrated": False})
    compute = {"cpu_seconds": 1.0, "wall_seconds": 1.0, "runs": 1, "sequence_rows": len(rows),
               "forwards": len(rows), "state_tokenizations": len(rows),
               "input_tokens": sum(p["input_tokens"] for p in predictions)}
    write_json(output / "compute.json", {**compute, "ledger": plan["original_ledger"]})
    ledger = read_json(Path(plan["original_ledger"]))
    ledger["compute"][job["phase"]] = compute
    write_json(Path(plan["original_ledger"]), ledger)
    results = ({target: score_feedback(rows, predictions, target)
                for target in ("answer", "delivery")} if job["task"] == "memory_feedback" else
               score_operation_predictions(rows, predictions))
    write_json(output / "results.json", results)


def test_saved_candidates_change_ce_selection_and_keep_combined_job_denominators(tmp_path):
    plan, native = fixture(tmp_path)
    result = select(plan, native)
    assert result["deployment_selection"]["answer"]["update"] == 0
    assert result["deployment_selection"]["delivery"]["update"] == 2
    assert result["native_in_memory_selection"]["delivery"]["update"] == 0
    assert result["pending_retention_updates"] == [2]
    assert result["curve"][0]["old_operation"]["counts"]["labelled"] == 1
    assert result["curve"][0]["feedback-dev"]["answer"]["coverage"]["feedback_states"] == 2
    assert "replay_states" not in result["curve"][0]["feedback-dev"]["answer"]["coverage"]
    raw = read_json(Path(plan["common_base"]["output"]) / "results.json")
    assert raw["answer"]["coverage"]["replay_states"] == 2
    assert result["curve"][1]["feedback-dev"]["delivery"]["families_with_direction"] == 1
    assert result["curve"][1]["in_memory_gpu_vs_saved_cpu_choice_changes"] == 2


@pytest.mark.parametrize("change", ["missing", "input", "threads", "checkpoint", "ledger",
                                    "summary", "dtype", "data", "native_running", "native_metric"])
def test_changed_or_incomplete_evidence_never_binds_a_selection(tmp_path, change):
    plan, native = fixture(tmp_path)
    job = plan["fits"][0]["candidates"][-1]
    output = Path(job["output"])
    if change == "missing":
        (output / "calls/3/output.json").unlink()
    elif change == "input":
        write_json(output / "calls/3/input.json", {"state": {}, "questions": {}})
    elif change in {"threads", "checkpoint", "data"}:
        path = output / "run.json"
        value = read_json(path)
        value[change] = 1 if change == "threads" else "another-path"
        write_json(path, value)
    elif change == "ledger":
        path = Path(plan["original_ledger"])
        value = read_json(path)
        value["compute"][job["phase"]]["input_tokens"] += 1
        write_json(path, value)
    elif change == "summary":
        path = output / "results.json"
        value = read_json(path)
        value["answer"]["counts"]["ordered_correctly"] += 1
        write_json(path, value)
    elif change == "dtype":
        native["curve"][-1]["saved_tensor_dtypes"] = {"F32": 1}
    elif change == "native_running":
        path = Path(native["recipe"]["output"]) / "run.json"
        value = read_json(path)
        value["status"] = "RUNNING"
        write_json(path, value)
    else:
        native["curve"][-1]["feedback-dev"]["answer"]["counts"]["ordered_correctly"] = 0
    with pytest.raises((ValueError, FileNotFoundError)):
        select(plan, native)


def test_retention_waits_for_selected_job_and_does_not_reselect_after_old_skill_loss(tmp_path):
    plan, native = fixture(tmp_path)
    selection = select(plan, native)
    with pytest.raises(FileNotFoundError):
        verify_retention(plan, native, selection)
    job = plan["fits"][0]["conditional_retention_jobs"][0]
    emit_job(plan, native, job)
    before = copy.deepcopy(selection)
    report = verify_retention(plan, native, selection)
    assert report["selected_old_operation"]["answer"]["family_macro_acceptance"] == 1
    assert report["selected_old_operation"]["delivery"]["family_macro_acceptance"] == 0
    assert report["deployment_selection"]["delivery"]["update"] == 2
    assert selection == before
    selection["deployment_selection"]["delivery"]["update"] = 0
    with pytest.raises(ValueError, match="Selection changed"):
        verify_retention(plan, native, selection)
