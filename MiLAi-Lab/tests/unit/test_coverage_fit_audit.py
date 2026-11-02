"""Coverage fits must preserve source derivations, replay, development and optimizer recipe."""
import copy
import json

import pytest
from test_feedback_coverage import fixture
from test_quality_fit_audit import plans_for_adapter

from analyze_coverage_feedback_fit import coverage_analysis_plan
from feedback_coverage import compile_coverage_controls
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def plans(tmp_path):
    source, data = tmp_path / "source", tmp_path / "data"
    source.mkdir()
    data.mkdir()
    rows = fixture()
    write_rows(source / "train.jsonl", rows)
    for filename in ("dev.jsonl", "feedback-dev.jsonl"):
        (source / filename).write_text('{"fixed_development":"opaque"}\n')
    derived = compile_coverage_controls(rows)
    for name, values in derived["arms"].items():
        folder = data / name
        folder.mkdir()
        write_rows(folder / "train.jsonl", values)
        for filename in ("dev.jsonl", "feedback-dev.jsonl"):
            (folder / filename).write_bytes((source / filename).read_bytes())
    write_json(data / "source-slot-mapping.json", {"mapping": derived["mapping"]})
    write_json(data / "preparation.json", {k: v for k, v in derived.items()
                                          if k not in {"arms", "mapping"}})
    quality, original = plans_for_adapter()
    for spec in [*quality["plans"], original["plans"][0]]:
        spec["argv"][2] = str(source)
        spec["argv"].extend(["--feedback-dev-data", str(source / "feedback-dev.jsonl")])
    study = {"source_data": str(source), "data_root": str(data), "target": "answer",
        "quality_mode": "quality-direction", "common_families": derived["eligible_families"],
        "common_initialization": quality["common_initialization"],
        "base_runtime": quality["base_runtime"], "training_overlay": quality["training_overlay"],
        "plans": []}
    baseline = quality["plans"][0]
    for arm in ("initial_only", "initial_post"):
        spec = copy.deepcopy(baseline)
        spec.update(run_id="coverage-" + arm, arm="answer", coverage_arm=arm,
            source_cohort=len(study["common_families"]), output=str(tmp_path / ("fit-" + arm)),
            compute_phase=arm)
        spec["argv"][2] = str(data / arm)
        spec["argv"][4] = spec["output"]
        spec["argv"][spec["argv"].index("--compute-phase") + 1] = arm
        spec["argv"][spec["argv"].index("--feedback-dev-data") + 1] = str(
            data / arm / "feedback-dev.jsonl")
        study["plans"].append(spec)
    return study, quality, original, data


def test_matched_new_fits_do_not_relabel_the_full_q_reference_as_the_control(tmp_path):
    study, quality, original, _ = plans(tmp_path)
    before = copy.deepcopy((study, quality, original))
    result = coverage_analysis_plan(study, quality, original)
    assert (study, quality, original) == before
    assert result["coverage_derivation"]["eligible_families"] == ["A", "B"]
    assert [p["coverage_arm"] for p in result["plans"]] == ["initial_only", "initial_post"]
    assert all(p["source_cohort"] == 2 and p["quality_mode"] == "quality-direction"
               for p in result["plans"])
    assert result["unmatched_full_Q_reference_run_id"] == "quality-direction"


@pytest.mark.parametrize("mutation", ["post_copy", "replay", "dev", "mapping", "cohort"])
def test_data_or_identity_drift_is_rejected_before_native_fit_audit(tmp_path, mutation):
    study, quality, original, data = plans(tmp_path)
    if mutation == "post_copy":
        rows = read_jsonl(data / "initial_only/train.jsonl")
        rows[1] = read_jsonl(data / "initial_post/train.jsonl")[1]
        write_rows(data / "initial_only/train.jsonl", rows)
    elif mutation == "replay":
        path = data / "initial_post/train.jsonl"
        rows = read_jsonl(path)
        rows[-1], rows[-2] = rows[-2], rows[-1]
        write_rows(path, rows)
    elif mutation == "dev":
        (data / "initial_only/dev.jsonl").write_text("changed development\n")
    elif mutation == "mapping":
        path = data / "source-slot-mapping.json"
        value = read_json(path)
        value["mapping"][1]["initial_only_source_index"] = 1
        write_json(path, value)
    else:
        study["common_families"].reverse()
    with pytest.raises(ValueError):
        coverage_analysis_plan(study, quality, original)


@pytest.mark.parametrize("mutation", ["budget", "scope", "device", "target"])
def test_coverage_cannot_silently_change_another_training_axis(tmp_path, mutation):
    study, quality, original, _ = plans(tmp_path)
    spec = study["plans"][0]
    if mutation == "budget":
        argv = spec["argv"]
        argv[argv.index("--optimizer-updates") + 1] = "193"
    elif mutation == "scope":
        spec["argv"].append("--freeze-encoder")
    elif mutation == "device":
        spec["environment"]["CUDA_VISIBLE_DEVICES"] = "0,1"
    else:
        study["target"] = "delivery"
    with pytest.raises(ValueError):
        coverage_analysis_plan(study, quality, original)
