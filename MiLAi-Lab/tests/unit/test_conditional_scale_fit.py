"""Synthetic native records exercise fixed endpoints, partial batches and evidence joins."""

import copy
import json
import random
import shutil
from pathlib import Path

import pytest
from test_conditional_applicability import fixture
from test_operation_curve_analysis import tensor_file

from analyze_conditional_scale_fit import (
    analyze_auxiliary,
    analyze_scale_fit,
    auxiliary_recipe,
    conditional_diagnostics,
)
from evaluate_bounded_laya import score_applicability_predictions
from milai_lab.datasets.conditional_applicability import compile_condition_union
from milai_lab.datasets.followir import applicability_input
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_mixture import event_weights
from train_bounded_laya import state_option_seed, training_microbatches, training_stages


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def complete_auxiliary_fixture(tmp_path):
    data, output, base = [tmp_path / name for name in ("data", "fit", "base")]
    for path in [data, output, base]:
        path.mkdir()
    train = []
    for i in range(17):
        row = applicability_input(f"query{i}", "purpose", {"text": f"candidate{i}"})
        row.update(
            gold={
                "applicability": {
                    "probabilities": {
                        "satisfies": float(i % 2 == 0),
                        "does_not_satisfy": float(i % 2 != 0),
                    }
                }
            },
            metadata={
                "event_id": f"train{i}",
                "family": f"train{i % 2}",
                "split": "train",
                "state_id": i,
                "row": i,
                "training_event": i,
                "task": "instruction_applicability",
            },
        )
        train.append(row)
    raw, groups = fixture()
    groups[0]["split"] = "dev"
    union = compile_condition_union(raw, groups, "promptriever")
    dev, pairs = union["matrix"], union["pairs"]
    native_dir, reviewed_dir = tmp_path / "native", tmp_path / "reviewed"
    for path in [native_dir, reviewed_dir]:
        write_rows(path / "matrix.jsonl", dev)
        write_rows(path / "condition-pairs.jsonl", pairs)
    changes = [p for p in pairs if p["kind"] == "change"]
    interpretation = tmp_path / "interpretation.json"
    write_json(
        interpretation,
        {"clear_requirement_changes": changes[:1], "native_label_inconsistencies": changes[1:]},
    )
    write_rows(data / "train.jsonl", train)
    spec = {
        "run_id": "synthetic-aux",
        "updates": 2,
        "draws": 17,
        "expected_pass1_tokens": sum(range(10, 27)),
        "argv": [
            "python",
            "train_bounded_laya.py",
            str(data),
            str(base),
            str(output),
            "--epochs",
            "1",
            "--task",
            "instruction_applicability",
            "--seed",
            "0",
            "--max-len",
            "8192",
            "--head-max-len",
            "384",
            "--micro-batch-size",
            "4",
            "--encoder-lr",
            "2.5e-5",
            "--head-lr",
            "1e-4",
            "--shuffle-options",
            "--evaluate-train",
            "--train-eval-final-only",
            "--dev-data",
            str(reviewed_dir / "matrix.jsonl"),
            "--compute-phase",
            "synthetic-phase",
            "--budget",
            str(tmp_path / "ledger.json"),
        ],
    }
    study = {
        "arms": [{"auxiliary": spec, "operation": {"run_id": "unused-operation"}}],
        "conditional_diagnostics": {
            "native": str(native_dir),
            "reviewed": str(reviewed_dir),
            "interpretation": str(interpretation),
        },
    }
    recipe = auxiliary_recipe(spec)
    lengths = {
        split: [
            {
                "event_id": row["metadata"]["event_id"],
                "question": "applicability",
                "sequence_tokens": 10 + i,
                "state_tokens_dropped": 0,
                "head_tokens_dropped": 0,
            }
            for i, row in enumerate(rows)
        ]
        for split, rows in [("train", train), ("dev", dev)]
    }
    write_json(output / "lengths.json", lengths)
    write_json(
        output / "sampling.json",
        [
            {
                "event_id": row["metadata"]["event_id"],
                "family": row["metadata"]["family"],
                "weight": weight,
            }
            for row, weight in zip(train, event_weights(train), strict=True)
        ],
    )
    stages = training_stages(17, 1, 0)
    write_json(output / "training-plan.json", stages)
    windows = stages[0][1]
    batches = [batch for window in windows for batch in training_microbatches(window, 4)]
    counts = {
        "train_sequence_rows": 17,
        "train_offered_rows": 17,
        "train_input_tokens": recipe["expected_train_tokens"],
        "train_offered_tokens": recipe["expected_train_tokens"],
        "train_batch_attempts": len(batches),
        "train_batch_forwards": len(batches),
        "train_device_forwards": sum(min(len(batch), 2) for batch in batches),
    }
    run = {
        k: value
        for k, value in recipe.items()
        if k not in {"output", "ledger", "compute_phase", "expected_draws", "expected_train_tokens"}
    }
    run.update(
        status="COMPLETED",
        pid=99999999,
        optimizer_updates=2,
        train_states=len(train),
        dev_states=len(dev),
        http_requests=0,
        calibration_test_loaded=False,
        **counts,
    )
    write_json(output / "run.json", run)
    orders = []
    for row in train:
        order = [0, 1]
        random.Random(state_option_seed(0, 1, row["metadata"]["state_id"])).shuffle(order)  # noqa: S311
        orders.append(order)
    write_json(output / "option-orders/1.json", orders)
    history = []
    for epoch in [0, 1]:
        point = {"epoch": epoch}
        evaluations = {"dev": dev}
        if epoch:
            evaluations["train"] = train
        for split, rows in evaluations.items():
            predictions = []
            for i, row in enumerate(rows):
                target = row["gold"].get("applicability", {}).get("probabilities", {})
                correct = max(target, key=target.get) if target else "satisfies"
                choice = (
                    correct
                    if epoch == 0 or split == "train"
                    else ("does_not_satisfy" if correct == "satisfies" else "satisfies")
                )
                prediction = {
                    "choice": choice,
                    "logits": {
                        key: float(key == choice)
                        for key in row["questions"]["applicability"]["criteria"]
                    },
                    "probabilities": {
                        key: 0.75 if key == choice else 0.25
                        for key in row["questions"]["applicability"]["criteria"]
                    },
                    "input_tokens": lengths[split][i]["sequence_tokens"],
                    "truncated": False,
                }
                predictions.append(prediction)
                write_json(output / split / str(epoch) / f"{i}.json", prediction)
            point[split] = score_applicability_predictions(rows, predictions)
            write_json(output / split / str(epoch) / "summary.json", point[split])
        history.append(point)
    write_json(output / "history.json", history)
    checkpoint = output / "checkpoint"
    checkpoint.mkdir()
    write_json(
        checkpoint / "rl_agent_config.json",
        {"training": {"milai_reader": {**run, "status": "RUNNING", "epoch": 1}}},
    )
    tensor_file(checkpoint / "model.safetensors", 1.0)
    shutil.copytree(checkpoint, output / "checkpoint_latest")
    write_json(
        output / "parameter-probes.json",
        {"encoder": {"changed_elements": 2}, "head": {"changed_elements": 1}},
    )
    compute = {
        **counts,
        "cpu_seconds": 1.0,
        "wall_seconds": 1.0,
        "runs": 1,
        "dev_sequence_rows": 2 * len(dev),
        "dev_input_tokens": 2 * sum(x["sequence_tokens"] for x in lengths["dev"]),
        "train_eval_sequence_rows": len(train),
        "train_eval_input_tokens": sum(x["sequence_tokens"] for x in lengths["train"]),
    }
    write_json(output / "compute.json", {**compute, "ledger": recipe["ledger"]})
    write_json(Path(recipe["ledger"]), {"compute": {"synthetic-phase": compute}})
    return study, spec, output


def test_fixed_epoch_keeps_worse_dev_endpoint_and_exact_partial_batch(tmp_path):
    study, spec, _ = complete_auxiliary_fixture(tmp_path)
    result = analyze_scale_fit(study, spec["run_id"])
    assert result["curve"][0]["dev"]["family_macro_accuracy"] == 1.0
    assert result["curve"][1]["dev"]["family_macro_accuracy"] == 0.0
    assert not result["selected_on_dev"] and not result["deployment_verified"]
    assert result["last_window_size"] == 1 and result["training_draws"] == 17
    assert result["compute_already_recorded"]["train_device_forwards"] == 9
    unknown = result["curve"][1]["conditional"]["reviewed"]["all_reviewed"]["strata"]["unknown"]
    assert unknown["pairs"] == 1 and unknown["family_macro_query_pair_joint_accuracy"] is None


@pytest.mark.parametrize(
    "change",
    [
        "running",
        "tokens",
        "duplicate_pass",
        "missing_prediction",
        "option_order",
        "metric",
        "checkpoint_epoch",
        "weights_alias",
        "ledger",
        "parameter_probe",
        "split",
        "clipping",
    ],
)
def test_native_auxiliary_evidence_must_close_before_reload(tmp_path, change):
    study, spec, output = complete_auxiliary_fixture(tmp_path)
    if change == "missing_prediction":
        (output / "dev/1/0.json").unlink()
    elif change == "weights_alias":
        tensor_file(output / "checkpoint_latest/model.safetensors", 2.0)
    else:
        name = {
            "running": "run.json",
            "tokens": "run.json",
            "duplicate_pass": "training-plan.json",
            "option_order": "option-orders/1.json",
            "metric": "dev/1/summary.json",
            "checkpoint_epoch": "checkpoint/rl_agent_config.json",
            "parameter_probe": "parameter-probes.json",
            "clipping": "lengths.json",
            "ledger": "compute.json",
            "split": "run.json",
        }[change]
        path = output / name
        value = read_json(path)
        if change == "running":
            value["status"] = "RUNNING"
        elif change == "tokens":
            value["train_input_tokens"] += 1
        elif change == "duplicate_pass":
            value[0][1][-1].append([2, 0])
        elif change == "option_order":
            value[0].reverse()
        elif change == "metric":
            value["counts"]["correct"] += 1
        elif change == "checkpoint_epoch":
            value["training"]["milai_reader"]["epoch"] = 2
        elif change == "parameter_probe":
            value["encoder"]["changed_elements"] = 0
        elif change == "clipping":
            value["train"][0]["state_tokens_dropped"] = 1
        elif change == "ledger":
            value["cpu_seconds"] += 1
        else:
            value["dev_source"] = "different-dev"
        write_json(path, value)
    with pytest.raises((ValueError, FileNotFoundError)):
        analyze_auxiliary(study, spec)


def test_semantic_subsets_cannot_hide_native_inconsistency_or_change_inputs(tmp_path):
    study, _, output = complete_auxiliary_fixture(tmp_path)
    rows = read_jsonl(Path(study["conditional_diagnostics"]["reviewed"]) / "matrix.jsonl")
    predictions = [read_json(output / "dev/0" / f"{i}.json") for i in range(len(rows))]
    path = Path(study["conditional_diagnostics"]["interpretation"])
    subsets = read_json(path)
    subsets["native_label_inconsistencies"] = []
    write_json(path, subsets)
    with pytest.raises(ValueError, match="partition all computed changes"):
        conditional_diagnostics(study, rows, predictions)
    altered = copy.deepcopy(rows)
    altered[0]["state"]["candidate"]["text"] = "different material"
    with pytest.raises(ValueError, match="same visible inputs"):
        conditional_diagnostics(study, altered, predictions)


def test_epoch_recipe_cannot_silently_become_fixed_update_budget(tmp_path):
    _, spec, _ = complete_auxiliary_fixture(tmp_path)
    spec["argv"].extend(["--optimizer-updates", "2"])
    with pytest.raises(ValueError, match="one complete epoch"):
        auxiliary_recipe(spec)
