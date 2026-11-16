"""Feedback initialization is bound only after compact saved selection and matching evidence."""

import copy
import sys

import pytest

from compact_training_closure import bind_feedback, recipe_from_plan, selected_train_job
from milai_lab.harness.artifact_io import read_json, write_json


def inputs(tmp_path):
    checkpoint = str(tmp_path / "compact-operation/checkpoints/update-262")
    operation = {
        "source_version": "original+compact",
        "argv": [
            "python",
            "train_bounded_laya.py",
            str(tmp_path / "data"),
            "initial-base",
            str(tmp_path / "compact-operation"),
            "--operation-state",
            "compact_actions",
            "--task",
            "mixed_retrieval",
            "--objective",
            "soft-ce",
            "--seed",
            "0",
            "--max-len",
            "12288",
            "--head-max-len",
            "2048",
            "--encoder-lr",
            "2.5e-5",
            "--head-lr",
            "1e-4",
            "--micro-batch-size",
            "2",
            "--optimizer-updates",
            "524",
            "--eval-at-updates",
            "32",
            "64",
            "128",
            "262",
            "393",
            "524",
            "--compute-phase",
            "compact-op",
            "--budget",
            str(tmp_path / "budget.json"),
        ],
    }
    conditions = {"operation_state": "compact_actions", "max_len": 12288}
    selection = {
        "status": "COMPACT_OPERATION_SAVED_CURVE_VERIFIED;MATCHING_TRAIN_PENDING",
        "selection": {"update": 262, "checkpoint": checkpoint, "metric": 0.7},
        "conditions": conditions,
        "recipe": recipe_from_plan(operation),
    }
    train = {
        "status": "COMPACT_OPERATION_MATCHING_SELECTED_TRAIN_VERIFIED",
        "checkpoint": checkpoint,
        "conditions": conditions,
    }
    runtime = str(tmp_path / "feedback-runtime")
    original_run = str(tmp_path / "original-feedback")
    audit = {
        "status": "ACTUAL_ORIGINAL_EXPOSURE_AND_COMPACT_SDK_INPUTS_VERIFIED;NO_MODEL_RUN",
        "stage": "feedback",
        "runtime": runtime,
        "original_run": original_run,
        "explicit_tokenizer_binding": True,
        "tokenizer_used": checkpoint + "/tokenizer",
    }
    source_plan = tmp_path / "nine.json"
    write_json(source_plan, {"protocol": "original-protocol.json"})
    study = {
        "operation": operation,
        "feedback_template": {
            "argv": ["python", "train_bounded_laya.py", "data", None, "out"],
            "initialization_pending": True,
            "source_version": "original+compact",
            "run_id": "compact-feedback",
            "arm": "answer",
            "source_cohort": 128,
        },
        "source_nine_plan": str(source_plan),
        "runtime_overlays": {"feedback": {"runtime": runtime}},
        "original_feedback_control": {"output": original_run},
    }
    plan = {
        "operation_selected_train_template": {
            "checkpoint": None,
            "argv": ["evaluate", "data", None],
            "checkpoint_argument_index": 2,
        },
        "feedback_saved_template": {
            "fit_plan": None,
            "common_base": {
                "checkpoint": None,
                "argv": ["evaluate", "data", None],
                "checkpoint_argument_index": 2,
            },
            "fits": [{"candidates": [{"update": 0, "checkpoint": None}]}],
        },
    }
    return study, plan, selection, train, audit


def test_selected_train_and_feedback_bind_to_actual_compact_checkpoint_without_mutating_templates(
    tmp_path,
):
    study, plan, selection, train, audit = inputs(tmp_path)
    before = copy.deepcopy((study, plan, selection, train, audit))
    job = selected_train_job(plan, selection)
    assert job["checkpoint"] == job["argv"][2] == selection["selection"]["checkpoint"]
    bound = bind_feedback(study, plan, selection, train, audit)
    checkpoint = selection["selection"]["checkpoint"]
    assert bound["fit_plan"]["plans"][0]["argv"][3] == checkpoint
    assert bound["saved_plan"]["common_base"]["argv"][2] == checkpoint
    assert bound["saved_plan"]["fits"][0]["candidates"][0]["checkpoint"] == checkpoint
    assert (study, plan, selection, train, audit) == before


@pytest.mark.parametrize(
    "change",
    [
        "shared",
        "other_checkpoint",
        "wrong_tokenizer",
        "unbound_tokenizer",
        "other_operation_recipe",
    ],
)
def test_mismatched_initializer_or_unverified_tokenizer_cannot_enter_feedback(tmp_path, change):
    study, plan, selection, train, audit = inputs(tmp_path)
    if change == "shared":
        selection["conditions"]["operation_state"] = "shared_actions"
    elif change == "other_checkpoint":
        train["checkpoint"] = str(tmp_path / "other")
    elif change == "wrong_tokenizer":
        audit["tokenizer_used"] = str(tmp_path / "shared-base/tokenizer")
    elif change == "unbound_tokenizer":
        audit["explicit_tokenizer_binding"] = False
    else:
        selection["recipe"]["data"] = str(tmp_path / "other-operation-data")
    with pytest.raises(ValueError, match="actual compact"):
        bind_feedback(study, plan, selection, train, audit)


def test_partial_selection_cannot_bind_even_a_train_diagnostic(tmp_path):
    _, plan, selection, _, _ = inputs(tmp_path)
    selection["status"] = "PARTIAL_CURVE"
    with pytest.raises(ValueError, match="full saved"):
        selected_train_job(plan, selection)


def test_binding_cli_writes_one_consistent_fit_and_saved_plan(tmp_path, monkeypatch):
    import compact_training_closure

    values = inputs(tmp_path)
    paths = []
    names = ("study", "saved", "selection", "train", "tokenizer")
    for name, value in zip(names, values, strict=True):
        path = tmp_path / (name + ".json")
        write_json(path, value)
        paths.append(str(path))
    output = tmp_path / "bound.json"
    monkeypatch.setattr(sys, "argv", ["bind", "bind-feedback", *paths, str(output)])
    compact_training_closure.main()
    record = read_json(output)
    saved_path = tmp_path / "bound-saved-plan.json"
    fit_path = tmp_path / "bound-fit-plan.json"
    assert read_json(saved_path) == record["saved_plan"]
    assert read_json(fit_path) == record["fit_plan"]
    assert record["saved_plan"]["fit_plan"] == str(fit_path.resolve())
    assert record["model_calls"] == 0
