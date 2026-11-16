"""Matched intervention recipes and direct stored-weight checks for encoder freezing."""
import copy
import json
import struct

import pytest
from test_quality_fit_audit import plans_for_adapter

from analyze_regularized_feedback_fit import (
    checkpoint_tensor_changes,
    regularization_analysis_plan,
    verify_parameter_scope,
)


def study_plans():
    quality, original = plans_for_adapter()
    baseline = quality["plans"][0]
    study = {"baseline_run_id": baseline["run_id"],
        "common_initialization": quality["common_initialization"],
        "base_runtime": quality["base_runtime"], "training_overlay": "/regularization",
        "label_smoothing": .05, "plans": []}
    for intervention in ("freeze-encoder", "soft-target"):
        spec = copy.deepcopy(baseline)
        spec.update(run_id=intervention, arm="answer", intervention=intervention,
                    output="/output/" + intervention, compute_phase=intervention)
        spec["argv"][4] = spec["output"]
        spec["argv"][spec["argv"].index("--compute-phase") + 1] = spec["compute_phase"]
        if intervention == "freeze-encoder":
            spec["argv"].append("--freeze-encoder")
        else:
            spec["argv"][1] = "/regularization/train_bounded_laya.py"
            spec["argv"].extend(["--pair-label-smoothing", ".05"])
            spec["environment"]["PYTHONPATH"] = (
                "/frozen/base/src:/regularization:/frozen/base/tools")
        study["plans"].append(spec)
    return study, quality, original


def test_only_two_declared_controls_preserve_the_original_and_quality_recipes():
    study, quality, original = study_plans()
    before = copy.deepcopy((study, quality, original))
    result = regularization_analysis_plan(study, quality, original)
    assert [p["intervention"] for p in result["plans"]] == ["freeze-encoder", "soft-target"]
    assert all(p["quality_mode"] == "quality-direction" for p in result["plans"])
    assert (study, quality, original) == before


@pytest.mark.parametrize("mutation", ["budget", "epsilon", "both", "device", "baseline"])
def test_control_adapter_rejects_extra_recipe_changes(mutation):
    study, quality, original = study_plans()
    if mutation == "budget":
        argv = study["plans"][0]["argv"]
        argv[argv.index("--optimizer-updates") + 1] = "193"
    elif mutation == "epsilon":
        study["plans"][1]["argv"][-1] = ".1"
    elif mutation == "both":
        study["plans"][1]["argv"].append("--freeze-encoder")
    elif mutation == "device":
        study["plans"][0]["environment"]["CUDA_VISIBLE_DEVICES"] = "0,1"
    else:
        study["baseline_run_id"] = "different-baseline"
    with pytest.raises(ValueError):
        regularization_analysis_plan(study, quality, original)


def tensor_file(path, encoder, head):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({
        "encoder.weight": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]},
        "head.weight": {"dtype": "F16", "shape": [1], "data_offsets": [2, 4]},
    }).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + struct.pack("<2e", encoder, head))


def test_saved_frozen_encoder_is_checked_at_every_declared_point(tmp_path):
    base = tmp_path / "base/model.safetensors"
    first = tmp_path / "update-1/model.safetensors"
    final = tmp_path / "update-2/model.safetensors"
    tensor_file(base, 1., 1.)
    tensor_file(first, 1., 2.)
    tensor_file(final, 1., 3.)
    native = {"recipe": {"base_checkpoint": str(base.parent), "freeze_encoder": True},
        "curve": [{"update": 0, "checkpoint": str(base.parent)},
                  {"update": 1, "checkpoint": str(first.parent)},
                  {"update": 2, "checkpoint": str(final.parent)}]}
    report = verify_parameter_scope(native)
    assert len(report) == 2
    for row in report:
        assert row["groups"]["encoder"]["changed_tensors"] == []
        assert row["groups"]["non_encoder"]["changed_tensors"] == ["head.weight"]
    tensor_file(first, 1.5, 2.)
    with pytest.raises(ValueError, match="Frozen encoder changed"):
        verify_parameter_scope(native)
    native["recipe"]["freeze_encoder"] = False
    assert verify_parameter_scope(native)[0]["groups"]["encoder"]["changed_tensors"] == [
        "encoder.weight"]


def test_truncated_stored_tensor_cannot_pass_literal_equality(tmp_path):
    base, bad = tmp_path / "base", tmp_path / "bad"
    tensor_file(base, 1., 2.)
    bad.write_bytes(base.read_bytes()[:-1])
    with pytest.raises(ValueError, match="payload is incomplete"):
        checkpoint_tensor_changes(base, bad)
