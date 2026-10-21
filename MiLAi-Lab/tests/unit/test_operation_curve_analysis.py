"""Synthetic completed artifacts test evidence joins; no trained model or real ledger is used."""
import json
import random
import shutil
import struct
from pathlib import Path

import pytest

from analyze_operation_curve import analyze, choose_checkpoint, recipe_from_plan
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import score_operation_predictions
from retrieval_feedback import feedback_dev_report, score_feedback
from retrieval_mixture import event_weights
from train_bounded_laya import state_option_seed, training_stages


def tensor_file(path, value):
    header = json.dumps({"probe": {"dtype": "F16", "shape": [2], "data_offsets": [0, 4]}}).encode()
    header += b" " * (-len(header) % 8)
    path.write_bytes(struct.pack("<Q", len(header)) + header + struct.pack("<2e", value, 1.0))


def row(identity, family, split, state_id, labelled=True):
    return {"state": {"task": {"request": identity}, "pending_candidates": []},
        "questions": {"next": {"type": "choice", "instructions": "Choose",
                               "criteria": {"read": "READ", "stop": "HANDOFF"}}},
        "gold": {"next": {"probabilities": {"read": 1.0}}} if labelled else {},
        "metadata": {"event_id": identity, "family": family, "state_id": state_id,
            "row": state_id, "split": split, "task": "memory_operation", "component": "history",
            "training_event": identity, "label_status": "reviewed",
            "action_kinds": {"read": "READ", "stop": "HANDOFF"}}}


def complete_fixture(tmp_path):
    data, output, base = [tmp_path / name for name in ("data", "fit", "base")]
    for folder in (data, output, base):
        folder.mkdir()
    train = [row(f"t{i}", "trainA" if i % 2 == 0 else "trainB", "train", i, i < 3)
             for i in range(4)]
    dev = [row(f"d{i}", "devA" if i < 3 else "devB", "dev", 100+i, i < 4)
           for i in range(5)]
    feedback = [row("feedback", "devA", "dev", 200, False)]
    feedback[0]["feedback"] = {"comparisons": [{"left": "read", "right": "stop",
                                               "answer": "left", "delivery": "right"}]}
    for name, rows in (("train", train), ("dev", dev), ("feedback", feedback)):
        (data / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    plan = {"source_version": "mechanical", "argv": ["python", "tools/train_bounded_laya.py",
        str(data), str(base), str(output), "--task", "memory_operation", "--objective", "soft-ce",
        "--operation-state", "shared", "--seed", "0", "--optimizer-updates", "4",
        "--eval-at-updates", "2", "4", "--evaluate-train", "--shuffle-options",
        "--gradient-checkpointing", "--max-len", "12288", "--head-max-len", "2048",
        "--encoder-lr", "2.5e-5", "--head-lr", "1e-4", "--micro-batch-size", "2",
        "--feedback-dev-data", str(data / "feedback.jsonl"), "--compute-phase", "test-fit",
        "--budget", str(tmp_path / "ledger.json")]}
    recipe = recipe_from_plan(plan)
    rows = {"train": train[:3], "dev": dev, "feedback-dev": feedback}
    lengths = {split: [{"event_id": r["metadata"]["event_id"], "question": "next",
        "sequence_tokens": 10000 if split == "dev" and i == 3 else 10+i,
        "state_tokens_dropped": 0, "head_tokens_dropped": 0} for i, r in enumerate(values)]
        for split, values in rows.items()}
    write_json(output / "lengths.json", lengths)
    write_json(output / "sampling.json", [{"event_id": r["metadata"]["event_id"],
        "family": r["metadata"]["family"], "weight": w}
        for r, w in zip(rows["train"], event_weights(rows["train"]), strict=True)])
    stages = training_stages(3, 1, 0, 4, [2, 4])
    write_json(output / "training-plan.json", stages)
    draws = [item for _, windows in stages for window in windows for item in window]
    run = {**recipe, "status": "COMPLETED", "pid": 99999999, "optimizer_updates": 4,
        "evaluation_points": [2, 4], "evaluate_initial_dev": True, "train_eval_final_only": False,
        "train_sequence_rows": 64, "train_input_tokens": sum(
            lengths["train"][i]["sequence_tokens"] for _, i in draws)}
    write_json(output / "run.json", run)
    for data_pass in sorted({p for p, _ in draws}):
        orders = []
        for r in rows["train"]:
            order = [0, 1]
            rng = random.Random(state_option_seed(0, data_pass, r["metadata"]["state_id"]))  # noqa: S311
            rng.shuffle(order)
            orders.append(order)
        write_json(output / "option-orders" / f"{data_pass}.json", orders)
    history = []
    for update in (0, 2, 4):
        point = {"optimizer_updates": update}
        for split, values in rows.items():
            predictions = []
            for i, _ in enumerate(values):
                selected = (i < 3 if update == 0 else i in (0, 3)) if split == "dev" else True
                choice = "read" if selected else "stop"
                prediction = {"choice": choice,
                    "logits": {"read": float(selected), "stop": float(not selected)},
                    "probabilities": {"read": .75 if selected else .25,
                                      "stop": .25 if selected else .75},
                    "input_tokens": lengths[split][i]["sequence_tokens"], "truncated": False}
                predictions.append(prediction)
                write_json(output / split / str(update) / f"{i}.json", prediction)
            score = ({target: score_feedback(values, predictions, target)
                      for target in ("answer", "delivery")} if split == "feedback-dev" else
                     score_operation_predictions(values, predictions))
            if split == "feedback-dev":
                score["coverage"] = feedback_dev_report(feedback, train, dev)
            point[split] = score
            write_json(output / split / str(update) / "summary.json", score)
        history.append(point)
        checkpoint = base if update == 0 else output / "checkpoints" / f"update-{update}"
        checkpoint.mkdir(parents=True, exist_ok=True)
        write_json(checkpoint / "rl_agent_config.json", {"training": {"milai_reader": {
            **run, "status": "RUNNING", "optimizer_updates": update}}})
        tensor_file(checkpoint / "model.safetensors", update)
    write_json(output / "history.json", history)
    shutil.copytree(output / "checkpoints/update-4", output / "checkpoint")
    compute = {"wall_seconds": 1.0, "cpu_seconds": 1.2, "runs": 1,
               "ledger": recipe["ledger"], "train_sequence_rows": 64,
               "train_input_tokens": run["train_input_tokens"]}
    for split, values in rows.items():
        prefix = "train_eval" if split == "train" else split
        compute[prefix + "_sequence_rows"] = len(values)*3
        compute[prefix + "_input_tokens"] = sum(r["sequence_tokens"] for r in lengths[split])*3
    write_json(output / "compute.json", compute)
    write_json(Path(recipe["ledger"]), {"compute": {"test-fit": {
        k: v for k, v in compute.items() if k != "ledger"}}})
    return recipe


def test_complete_curve_selects_macro_not_micro_and_earliest_tie(tmp_path):
    recipe = complete_fixture(tmp_path)
    result = analyze(recipe)
    assert result["in_memory_selection"]["update"] == 2
    assert result["curve"][0]["dev"]["counts"]["accepted"] == 3
    assert result["curve"][1]["dev"]["counts"]["accepted"] == 2
    assert result["curve"][1]["dev"]["buckets"]["length"][">8192"]["counts"]["labelled"] == 1
    assert result["curve"][0]["feedback-dev"]["answer"]["family_macro_state_pair_accuracy"] == 1
    assert result["curve"][0]["feedback-dev"]["delivery"]["family_macro_state_pair_accuracy"] == 0
    assert result["deployment_selection"] is None and result["training_draws_verified"] == 64
    assert all(c["tensor_dtypes"] == {"F16": 1} for c in result["saved_checkpoints"])


def test_initialization_is_eligible_without_claiming_a_learning_gain():
    points = [{"update": i, "dev": {"family_macro_acceptance": 0.5}} for i in (4, 0, 2)]
    assert choose_checkpoint(points)["update"] == 0


@pytest.mark.parametrize("change", ["running", "missing_prediction", "wrong_tokens",
                                    "wrong_options", "wrong_metric", "wrong_checkpoint",
                                    "final_copy"])
def test_incomplete_or_changed_evidence_cannot_produce_a_selection(tmp_path, change):
    recipe = complete_fixture(tmp_path)
    output = Path(recipe["output"])
    if change == "running":
        run = read_json(output / "run.json")
        run["status"] = "RUNNING"
        write_json(output / "run.json", run)
        (output / "history.json").unlink()
    elif change == "missing_prediction":
        (output / "dev/2/0.json").unlink()
    elif change == "wrong_tokens":
        p = output / "dev/2/0.json"
        value = read_json(p)
        value["input_tokens"] += 1
        write_json(p, value)
    elif change == "wrong_options":
        p = output / "option-orders/1.json"
        value = read_json(p)
        value[0].reverse()
        write_json(p, value)
    elif change == "wrong_metric":
        p = output / "dev/2/summary.json"
        value = read_json(p)
        value["counts"]["accepted"] += 1
        write_json(p, value)
    elif change == "wrong_checkpoint":
        p = output / "checkpoints/update-2/rl_agent_config.json"
        value = read_json(p)
        value["training"]["milai_reader"]["optimizer_updates"] = 3
        write_json(p, value)
    else:
        tensor_file(output / "checkpoint/model.safetensors", 0)
    with pytest.raises(ValueError):
        analyze(recipe)
