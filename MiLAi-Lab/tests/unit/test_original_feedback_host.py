"""Original saved policies bind without Host selection, missing-case loss or duplicate execution."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from prepare_original_feedback_host import bind_study, inspect_bindings, prepare_study
from run_host_saved_cpu import saved_cpu_loading


def study_fixture(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "model.safetensors").write_bytes(b"mechanical placeholder, never loaded")
    batches = []
    for index in range(4):
        histories = [
            {
                "id": f"family-{i}",
                "source_group": f"family-{i}",
                "split": "dev",
                "continuous": True,
                "sources": [],
                "requests": [
                    {
                        "id": "first",
                        "content": "Current reported value?",
                        "incoming_sources": [
                            {
                                "session_id": "source",
                                "event_key": f"fact-{i}",
                                "role": "user",
                                "content": f"The value is {i}.",
                            }
                        ],
                    },
                    {"id": "later", "content": "Current reported value?", "incoming_sources": []},
                ],
            }
            for i in range(index * 2, index * 2 + 2)
        ]
        path = tmp_path / f"batch-{index}.json"
        write_json(path, {"schema": "mechanical", "histories": histories})
        batches.append({"histories": str(path), "groups": [h["source_group"] for h in histories]})
    config_path = tmp_path / "config.json"
    config = {
        "entrypoints": {
            "functional": {
                "memory_control": {
                    "checkpoint": str(base),
                    "state_projection": "shared_actions",
                    "max_len": 16384,
                    "head_max_len": 2048,
                    "device": "cpu",
                    "threads": 4,
                    "policy": "fixed_context",
                },
                "config_version": "mechanical",
                "budget_path": str(tmp_path / "only-budget.json"),
                "host": {"temperature": 1, "tool_mode": "json_action"},
            }
        }
    }
    write_json(config_path, config)
    protocol_path = tmp_path / "protocol.json"
    write_json(protocol_path, {"dev_batches": batches, "bound_config": str(config_path)})
    plans = [
        {
            "run_id": f"source{n}-{arm}",
            "arm": arm,
            "source_cohort": n,
            "output": str(tmp_path / "fits" / f"source{n}-{arm}"),
        }
        for arm in ["answer", "continued-ce", "delivery"]
        for n in [32, 64, 128]
    ]
    nine_path = tmp_path / "nine.json"
    write_json(
        nine_path,
        {
            "protocol": str(protocol_path),
            "common_initialization": str(base),
            "plans": plans,
            "frozen_lab": str(tmp_path / "original-runtime"),
            "source_version": "original",
        },
    )
    study = prepare_study(nine_path, tmp_path / "study")
    return study, batches, config


def close_fit(study, fit, saved, *, updates=None):
    selected = {}
    for target in fit["targets"]:
        update = (updates or {}).get(target, 12)
        checkpoint = (
            Path(study["common_initialization"])
            if update == 0
            else Path(fit["fit_output"]) / "checkpoints" / f"update-{update}"
        )
        checkpoint.mkdir(parents=True, exist_ok=True)
        if update:
            (checkpoint / "model.safetensors").write_bytes(b"mechanical placeholder, never loaded")
        selected[target] = {
            "update": update,
            "checkpoint": str(checkpoint),
            "metric": 0.5,
            "condition": study["inference"],
        }
    common = {
        "run_id": fit["run_id"],
        "conditions": study["inference"],
        "deployment_selection": selected,
    }
    write_json(
        saved / fit["run_id"] / "selection.json",
        {**common, "status": "SAVED_CPU_FEEDBACK_SELECTION_VERIFIED"},
    )
    write_json(
        saved / fit["run_id"] / "retention.json",
        {
            **common,
            "status": "SAVED_CPU_SELECTION_AND_RETENTION_VERIFIED;HOST_EVALUATION_PENDING",
            "selected_old_operation": {
                target: {"family_macro_acceptance": 0.7} for target in selected
            },
        },
    )


def test_original_histories_are_preserved_and_all_nine_closures_are_required(tmp_path):
    study, batches, config = study_fixture(tmp_path)
    assert read_json(Path(study["histories"]))["histories"] == [
        h for b in batches for h in read_json(Path(b["histories"]))["histories"]
    ]
    assert read_json(Path(study["config_template"])) == config
    saved = tmp_path / "saved"
    close_fit(study, study["fits"][0], saved)
    inspection = inspect_bindings(study, saved)
    assert inspection["ready_fits"] == 1 and len(inspection["fits"]) == 9
    with pytest.raises(ValueError, match="all nine"):
        bind_study(
            study,
            inspection,
            tmp_path / "bound",
            python="python",
            attention_wrapper="attention.py",
            inference_wrapper="inference.py",
        )
    assert not (tmp_path / "bound").exists()


def test_shared_CE_selection_and_update_zero_keep_aliases_without_duplicate_runs(tmp_path):
    study, _, config = study_fixture(tmp_path)
    saved = tmp_path / "saved"
    for i, fit in enumerate(study["fits"]):
        close_fit(study, fit, saved, updates={"answer": 0} if i == 0 else None)
    inspection = inspect_bindings(study, saved)
    before = copy.deepcopy(inspection)
    result = bind_study(
        study,
        inspection,
        tmp_path / "bound",
        python="python",
        attention_wrapper="attention.py",
        inference_wrapper="inference.py",
        host_site_packages=str(tmp_path / "host packages"),
    )
    assert inspection == before
    assert result["host_site_packages"] == str(tmp_path / "host packages")
    assert result["unique_arms"] == 11 and result["planned_positions"] == 176
    assert len(result["arms"][2]["aliases"]) == 2
    ce = [
        a
        for a in result["arms"]
        if any(isinstance(x, dict) and "continued-ce" in x["run_id"] for x in a["aliases"])
    ]
    assert len(ce) == 3 and all(len(a["aliases"]) == 2 for a in ce)
    for arm in result["arms"]:
        assert arm["argv"][-2:] == ["--host-site-packages", str(tmp_path / "host packages")]
        assert str(tmp_path / "host packages") not in arm["environment"]["PYTHONPATH"]
        actual = read_json(Path(arm["config"]))
        settings = actual["entrypoints"]["functional"]
        settings["config_version"] = config["entrypoints"]["functional"]["config_version"]
        settings["memory_control"]["policy"] = "fixed_context"
        settings["memory_control"]["checkpoint"] = study["common_initialization"]
        assert actual == config
        assert "--continue-host-history" in arm["argv"] and "--native-probe" not in arm["argv"]
        assert arm["status"] == "NOT_EXECUTED" and not Path(arm["output"]).exists()


def test_retention_cannot_change_selection_and_CE_views_can_use_distinct_points(tmp_path):
    study, _, _ = study_fixture(tmp_path)
    saved = tmp_path / "saved"
    fit = next(f for f in study["fits"] if f["objective"] == "continued-ce")
    close_fit(study, fit, saved, updates={"answer": 48, "delivery": 24})
    row = next(r for r in inspect_bindings(study, saved)["fits"] if r["run_id"] == fit["run_id"])
    assert {p["update"] for p in row["deployment_selection"].values()} == {24, 48}
    path = saved / fit["run_id"] / "retention.json"
    retention = read_json(path)
    retention["deployment_selection"]["answer"]["update"] = 96
    write_json(path, retention)
    with pytest.raises(ValueError, match="identity"):
        inspect_bindings(study, saved)


def fake_loader(dtype="torch.float32"):
    class Decision:
        def __init__(self, checkpoint, max_len, head_max_len, device="cpu"):
            self.device = device
            self.max_len, self.head_max_len = max_len, head_max_len
            self.model = SimpleNamespace(
                encoder=SimpleNamespace(config=SimpleNamespace(reference_compile=None)),
                parameters=lambda: iter([SimpleNamespace(dtype=dtype)]),
            )

    torch = SimpleNamespace(
        get_num_threads=lambda: 4,
        backends=SimpleNamespace(mha=SimpleNamespace(get_fastpath_enabled=lambda: False)),
    )
    return Decision, torch


def test_inference_wrapper_records_actual_conditions_and_restores_constructor(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    decision, torch = fake_loader()
    original = decision.__init__
    records = []
    with saved_cpu_loading(decision, torch, records.append):
        instance = decision(tmp_path, 16384, 2048)
        assert instance.model.encoder.config.reference_compile is False
    assert records[0]["status"] == "VERIFIED" and decision.__init__ is original
    decision, torch = fake_loader("torch.float16")
    original = decision.__init__
    with pytest.raises(ValueError, match="saved CPU"):
        with saved_cpu_loading(decision, torch, records.append):
            decision(tmp_path, 16384, 2048)
    assert records[-1]["status"] == "INFERENCE_CONDITION_MISMATCH"
    assert decision.__init__ is original


def completed_arm(dispatch, arm, *, start=1):
    root = Path(arm["output"])
    fixture = read_json(Path(dispatch["study"]["histories"]))
    write_json(root / "fixture.json", fixture)
    profile = arm["policy"] + "-rich"
    config = read_json(Path(arm["config"]))
    config["entrypoints"]["functional"]["config_version"] += "-" + profile
    config["entrypoints"]["functional"]["retrieval_tool"] = "rich"
    write_json(root / (profile + "-config.json"), config)
    driver = {
        "status": "FAILED",
        "source_version": dispatch["study"]["source_version"],
        "planned_positions": 16,
        "native_probe": False,
        "given_requests": False,
        "continue_host_history": True,
        "cpu_seconds": 10,
        "started_epoch": start,
        "finished_epoch": start + 1,
        "completed": [
            {
                "history": "family-0",
                "request": "first",
                "policy": arm["policy"],
                "interface": "rich",
                "status": "COMPLETED",
            }
        ],
        "active": {"history": "family-0", "request": "later"},
    }
    write_json(root / "driver.json", driver)
    before = {
        "generation": {"known_tokens": 0, "unknown_usage": 0},
        "embedding": {"known_tokens": 0, "unknown_usage": 0},
        "generation_requests": 0,
        "compute": {"model": {"cpu_seconds": 0}},
    }
    after = copy.deepcopy(before)
    after["generation"].update(known_tokens=10, unknown_usage=1)
    after["generation_requests"] = 2
    after["compute"]["model"]["cpu_seconds"] = 2
    write_json(root / "budget-before.json", before)
    write_json(root / "budget-after.json", after)
    result_path = root / profile / "banks/bank/first-result.json"
    write_json(
        result_path,
        {
            "status": "COMPLETED",
            "bank": "family-0",
            "message_id": "first",
            "content": "Current reported value?",
            "final_answer": "The value is 0.",
            "messages": [
                {"type": "human", "content": "Current reported value?"},
                {"type": "ai", "content": "The value is 0.", "tool_calls": []},
            ],
        },
    )
    return result_path


def bound_fixture(tmp_path):
    study, _, _ = study_fixture(tmp_path)
    saved = tmp_path / "saved"
    for fit in study["fits"]:
        close_fit(study, fit, saved)
    return bind_study(
        study,
        inspect_bindings(study, saved),
        tmp_path / "bound",
        python="python",
        attention_wrapper="attention",
        inference_wrapper="inference",
    )


def test_summary_keeps_zero_calls_failure_missing_positions_and_unknown_costs(tmp_path):
    from summarize_original_feedback_host import summarize

    dispatch = bound_fixture(tmp_path)
    arm = dispatch["arms"][0]
    result_path = completed_arm(dispatch, arm)
    review = {
        "arm_id": arm["id"],
        "history": "family-0",
        "request": "first",
        "result_path": str(result_path),
        "answer": "The value is 0.",
        "grade": "correct",
        "rationale": "Matches the reported original Source value.",
        "source_refs": [["source", "fact-0", "user"]],
    }
    report = summarize(dispatch, [review])
    assert report["planned_positions"] == dispatch["planned_positions"]
    first = report["arms"][0]
    assert first["execution_counts"] == {
        "RESULT_RETAINED": 1,
        "ENTERED_WITHOUT_RETAINED_RESULT": 1,
        "NOT_EXECUTED": 14,
    }
    assert first["semantic_counts"] == {"correct": 1, "unknown": 15}
    assert first["zero_call_results"] == first["confirmed_task_successes"] == 1
    assert first["tool_count_unknown"] == 15
    assert first["costs"]["generation"]["unknown_usage"] == 1
    assert first["costs"]["compute"]["model"]["cpu_seconds"] == 2
    assert all(a["status"] == "NOT_EXECUTED" and a["costs"] is None for a in report["arms"][1:])
    with pytest.raises(ValueError, match="exact actual"):
        summarize(dispatch, [{**review, "answer": "A different old answer."}])
    with pytest.raises(ValueError, match="available at this prefix"):
        summarize(dispatch, [{**review, "source_refs": [["future", "unknown", "user"]]}])


def test_summary_rejects_overlapping_ledger_intervals_and_counts_only_current_calls(tmp_path):
    from summarize_original_feedback_host import current_tools, summarize

    dispatch = bound_fixture(tmp_path)
    completed_arm(dispatch, dispatch["arms"][0], start=1)
    completed_arm(dispatch, dispatch["arms"][1], start=1.5)
    with pytest.raises(ValueError, match="Overlapping"):
        summarize(dispatch, [])
    result = {
        "messages": [
            {"type": "human"},
            {"type": "ai", "tool_calls": [{"name": "milai_retrieve"}]},
            {"type": "tool", "name": "milai_retrieve"},
            {"type": "human"},
            {"type": "ai", "tool_calls": []},
        ]
    }
    assert current_tools(result) == {"tool_attempts": 0, "tool_returns": 0, "tool_errors": 0}
    assert current_tools({"messages": []}) == {
        "tool_attempts": None,
        "tool_returns": None,
        "tool_errors": None,
    }


def test_failed_inference_wrapper_before_native_driver_retains_unknown_conditions(tmp_path):
    from summarize_original_feedback_host import summarize

    dispatch = bound_fixture(tmp_path)
    arm = dispatch["arms"][0]
    write_json(
        Path(arm["output"] + "-inference.json"),
        {"status": "FAILED_RETAINED", "model_loads": [], "error": "incomplete audit"},
    )
    result = summarize(dispatch, [])
    assert result["arms"][0]["inference_condition_status"] == "FAILED_ATTEMPT_INCOMPLETE_AUDIT"
    assert result["arms"][0]["status"] == "WRAPPER_FAILED_RETAINED_NO_NATIVE_DRIVER"
    assert result["arms"][0]["zero_call_results"] == 0
    assert result["arms"][0]["tool_count_unknown"] == 16
    assert result["arms"][0]["semantic_counts"] == {"unknown": 16}


def test_delivery_judgment_binds_final_provider_input_separately_from_correct_answer(tmp_path):
    from summarize_original_feedback_host import final_host_receipts, summarize

    dispatch = bound_fixture(tmp_path)
    arm = dispatch["arms"][0]
    path = completed_arm(dispatch, arm)
    packet = {
        "role": "tool",
        "name": "milai_retrieve",
        "tool_call_id": "t",
        "content": '{"schema":"milai_retrieval_result_v1","evidence":[]}',
    }
    result = read_json(path)
    result["attempt"] = 0
    result["messages"][-1]["id"] = "final"
    result["messages"][1:1] = [
        {
            "type": "ai",
            "id": "request",
            "tool_calls": [{"id": "t", "name": "milai_retrieve", "args": {"query": "value"}}],
        },
        {**packet, "type": "tool"},
    ]
    write_json(path, result)
    final_wire = [
        {"role": "user", "content": result["content"]},
        {
            "role": "assistant",
            "content": '{"calls":[{"name":"milai_retrieve","arguments":{"query":"value"}}]}',
        },
        packet,
    ]
    trace = path.with_name("first-trace-0.jsonl")
    trace.write_text(
        json.dumps(
            {
                "event": "vllm_response",
                "receipt": {"id": "final"},
                "request": {"messages": final_wire},
            }
        )
        + "\n"
    )
    boundary, receipts = final_host_receipts(path, result)
    assert boundary["status"] == "BOUND_TO_ACTUAL_COMPLETED_FINAL_PROVIDER_INPUT"
    assert receipts == [packet]
    review = {
        "arm_id": arm["id"],
        "history": "family-0",
        "request": "first",
        "result_path": str(path),
        "answer": result["final_answer"],
        "grade": "correct",
        "rationale": "Answer matches source; this does not prove delivered support.",
        "source_refs": [["source", "fact-0", "user"]],
    }
    row = summarize(dispatch, [review])["positions"][0]
    assert row["confirmed_task_success"] and row["delivery_grade"] == "unknown"
    review["delivery"] = {
        "grade": "insufficient",
        "rationale": "Actual packet has no evidence.",
        "visible_tool_receipts": [packet],
    }
    row = summarize(dispatch, [review])["positions"][0]
    assert row["semantic_grade"] == "correct" and row["delivery_grade"] == "insufficient"
    review["delivery"]["visible_tool_receipts"] = []
    with pytest.raises(ValueError, match="final-input Tool"):
        summarize(dispatch, [review])
    boundary, receipts = final_host_receipts(path, {**result, "failure_delivery": {}})
    assert boundary["status"] == "NO_BOUND_COMPLETED_FINAL_INPUT" and receipts is None
