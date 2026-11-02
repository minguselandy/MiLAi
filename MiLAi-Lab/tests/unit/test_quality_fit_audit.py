"""Closed synthetic receipts exercise the quality audit; no model weights are loaded."""
import copy
import json
import math
import random
import struct

import pytest

from analyze_feedback_fit import (
    analyze,
    choose_feedback_checkpoint,
    validate_quality_exposure,
    validate_quality_metric,
)
from analyze_operation_curve import recipe_from_plan
from analyze_quality_feedback_fit import quality_analysis_plan
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import score_operation_predictions
from quality_feedback import (
    QUALITY_MODES,
    quality_counts,
    quality_event_weights,
    score_quality_feedback,
)
from retrieval_feedback import RESOURCE_FIELDS, score_feedback
from train_bounded_laya import state_option_seed, training_stages


def row(identity, family, state, *, unknown=False, replay=False):
    kinds = {"read": "READ", "stop": "HANDOFF", "view": "REFRESH_VIEW"}
    costs = {key: {**dict.fromkeys(RESOURCE_FIELDS, 0), "read_operations": cost}
             for key, cost in (("read", 1), ("stop", 2), ("view", 0))}
    pairs = []
    for left, right, quality, final in (("read", "stop", "tie", "left"),
                                       ("read", "view", "left", "left"),
                                       ("stop", "view", "tie", "right")):
        pairs.append({"left": left, "right": right,
            "answer": "unknown" if unknown else final, "delivery": "unknown",
            "basis": {"quality_before_resource_tiebreak": {
                "answer": "unknown" if unknown else quality, "delivery": "unknown"},
                "resource_order": {"left": costs[left], "right": costs[right]}}})
    result = {"state": {"text": "Mechanical observed state"},
        "questions": {"next": {"criteria": kinds}}, "gold": {},
        "metadata": {"event_id": identity, "state_id": state, "row": state,
            "family": family, "label_status": "reviewed", "action_kinds": kinds,
            "collection_policy": "rules", "control_step": 0}}
    if replay:
        result["gold"] = {"next": {"probabilities": {"read": 1.0}}}
    else:
        result["feedback"] = {"comparisons": pairs}
    return result


def closed_quality_fit(tmp_path, mode):
    data, base, root = [tmp_path / name for name in ("data", "base", "fit")]
    data.mkdir()
    train = [row("train", "T", 0), row("unknown", "U", 1, unknown=True),
             row("replay", "R", 2, replay=True)]
    old = [row("old", "D", 3, replay=True)]
    feedback = [row("legacy", "A", 4), row("new", "B", 5, unknown=True)]
    for name, rows in (("train", train), ("dev", old), ("feedback-dev", feedback),
                       ("legacy", feedback[:1])):
        (data / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows))
    protocol = tmp_path / "protocol.json"
    write_json(protocol, {"feedback_dev": {"old_file": str(data / "legacy.jsonl")}})
    argv = ["python", "train_bounded_laya.py", str(data), str(base), str(root),
        "--task", "memory_operation", "--objective", "pair", "--optimizer-updates", "1",
        "--eval-at-updates", "1", "--seed", "0", "--max-len", "16384", "--head-max-len", "2048",
        "--encoder-lr", "2.5e-5", "--head-lr", "1e-4", "--micro-batch-size", "1",
        "--operation-state", "shared_actions", "--compute-phase", "unit",
        "--budget", str(tmp_path / "ledger.json"), "--feedback-dev-data",
        str(data / "feedback-dev.jsonl"), "--feedback-target", "answer", "--replay-weight", ".25",
        "--shuffle-options", "--pair-supervision", mode]
    plan = {"source_version": "mechanical", "protocol": str(protocol),
            "plans": [{"run_id": "unit", "arm": "answer", "argv": argv,
                       "environment": {"CUDA_VISIBLE_DEVICES": "2,3"}}]}
    recipe = recipe_from_plan({**plan["plans"][0], "source_version": "mechanical"})
    stages = training_stages(3, 1, 0, 1, [1])
    draws = [pair for _, windows in stages for window in windows for pair in window]
    counts = quality_counts([train[i] for _, i in draws], "answer", mode)
    run = {**recipe, "status": "COMPLETED", "pid": 999999999, "optimizer_updates": 1,
        "evaluation_points": [1], "evaluate_initial_dev": True,
        "train_states": 3, "dev_states": 1, "train_sequence_rows": 16, "train_input_tokens": 160,
        "feedback_target": "answer", "replay_weight": .25, "pair_supervision": mode,
        "device": "cuda", "physical_gpus": [2, 3],
        "feedback_pool": quality_counts(train, "answer", mode)}
    for key in ("feedback_states", "replay_states", "directional_pairs",
                "tie_pairs", "unknown_pairs"):
        run["sampled_" + key] = counts.get(key, 0)
    for field, key in (("feedback_target_states", "states_with_targets"),
                       ("target_pairs", "target_pairs"),
                       ("cost_only_direction_pairs", "cost_only_direction_pairs")):
        run["sampled_" + field] = counts.get(key, 0)
    run.update(feedback_nonzero_logit_gradient_rows=counts["states_with_targets"],
        replay_nonzero_logit_gradient_rows=counts["replay_states"],
        nonzero_logit_gradient_rows=counts["states_with_targets"] + counts["replay_states"])
    write_json(root / "run.json", run)
    write_json(root / "training-plan.json", stages)
    write_json(root / "sampling.json", [{"event_id": r["metadata"]["event_id"],
        "family": r["metadata"]["family"], "weight": w}
        for r, w in zip(train, quality_event_weights(train, "answer", mode, .25), strict=True)])
    lengths = {name: [{"event_id": r["metadata"]["event_id"], "question": "next",
        "sequence_tokens": 10, "state_tokens_dropped": 0, "head_tokens_dropped": 0} for r in rows]
        for name, rows in (("train", train), ("dev", old), ("feedback-dev", feedback))}
    write_json(root / "lengths.json", lengths)
    for data_pass in {p for p, _ in draws}:
        orders = []
        for r in train:
            order = [0, 1, 2]
            rng = random.Random(state_option_seed(0, data_pass, r["metadata"]["state_id"]))  # noqa: S311
            rng.shuffle(order)
            orders.append(order)
        write_json(root / "option-orders" / f"{data_pass}.json", orders)
    history = []
    for update in (0, 1):
        point = {"optimizer_updates": update}
        for split, rows in (("dev", old), ("feedback-dev", feedback)):
            values = ([3., 0., 0.] if split == "dev"
                      else [1., 2., 0.] if update == 0 else [1., 0., 2.])
            keys = ["read", "stop", "view"]
            probabilities = {key: math.exp(v)/sum(math.exp(x) for x in values)
                             for key, v in zip(keys, values, strict=True)}
            prediction = {"choice": max(keys, key=lambda k: probabilities[k]),
                "logits": dict(zip(keys, values, strict=True)), "probabilities": probabilities,
                "truncated": False, "input_tokens": 10}
            predictions = [copy.deepcopy(prediction) for _ in rows]
            for i, p in enumerate(predictions):
                write_json(root / split / str(update) / f"{i}.json", p)
            if split == "dev":
                metric = score_operation_predictions(rows, predictions)
            else:
                metric = {target: score_feedback(rows, predictions, target)
                          for target in ("answer", "delivery")}
                for name, kind in (("pure_quality", "quality-tie"),
                                   ("quality_cost", "quality-cost")):
                    metric[name] = {target: score_quality_feedback(rows, predictions, target, kind)
                                    for target in ("answer", "delivery")}
            point[split] = metric
            write_json(root / split / str(update) / "summary.json", metric)
        history.append(point)
    write_json(root / "history.json", history)
    header = json.dumps({"unit": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}}).encode()
    for folder in (base, root / "checkpoints/update-1", root / "checkpoint"):
        write_json(folder / "rl_agent_config.json", {"training": {"milai_reader": run}})
        (folder / "model.safetensors").write_bytes(
            struct.pack("<Q", len(header)) + header + b"\0\0")
    write_json(root / "parameter-probes.json", {
        "scope": "synthetic receipts, not measured weights"})
    compute = {"dev_sequence_rows": 2, "dev_input_tokens": 20,
               "feedback-dev_sequence_rows": 4, "feedback-dev_input_tokens": 40}
    for key in ("feedback_target_states", "target_pairs", "cost_only_direction_pairs"):
        compute["train_" + key] = run["sampled_" + key]
    for key in ("nonzero_logit_gradient_rows", "feedback_nonzero_logit_gradient_rows",
                "replay_nonzero_logit_gradient_rows"):
        compute["train_" + key] = run[key]
    write_json(root / "compute.json", {**compute, "ledger": recipe["ledger"]})
    write_json(tmp_path / "ledger.json", {"compute": {"unit": compute}})
    return plan, root


@pytest.mark.parametrize("mode", QUALITY_MODES)
def test_complete_quality_audit_uses_pure_quality_and_preserves_cost_diagnostic(tmp_path, mode):
    plan, root = closed_quality_fit(tmp_path, mode)
    result = analyze(plan, "unit", quality_mode=mode)
    assert result["in_memory_selection"]["answer"]["update"] == 0
    assert choose_feedback_checkpoint(result["curve"], "answer")["update"] == 1
    assert result["deployment_selection"] is None
    assert read_json(root / "sampling.json")[1]["weight"] == 0
    with pytest.raises(ValueError, match="quality selection rule"):
        analyze(plan, "unit")


@pytest.mark.parametrize("field", ["weight", "quality_metric", "gradient"])
def test_quality_audit_rejects_changed_weights_metrics_or_gradient_exposure(tmp_path, field):
    plan, root = closed_quality_fit(tmp_path, "quality-tie")
    if field == "weight":
        path = root / "sampling.json"
        saved = read_json(path)
        saved[1]["weight"] = .01
    elif field == "quality_metric":
        path = root / "feedback-dev/1/summary.json"
        saved = read_json(path)
        saved["pure_quality"]["answer"]["coverage"]["unknown_pairs"] = 0
    else:
        path = root / "run.json"
        saved = read_json(path)
        saved["feedback_nonzero_logit_gradient_rows"] = 100
    write_json(path, saved)
    with pytest.raises(ValueError):
        analyze(plan, "unit", quality_mode="quality-tie")


def test_quality_metric_and_gradient_checks_preserve_null_masks_and_zero_measurements():
    validate_quality_metric({"score": None, "count": 0}, {"score": None, "count": 0})
    with pytest.raises(ValueError):
        validate_quality_metric({"score": 0, "count": 0}, {"score": None, "count": 0})
    run = {"sampled_feedback_target_states": 2, "sampled_target_pairs": 3,
        "sampled_cost_only_direction_pairs": 0, "nonzero_logit_gradient_rows": 0,
        "feedback_nonzero_logit_gradient_rows": 0, "replay_nonzero_logit_gradient_rows": 0}
    validate_quality_exposure(run, {
        "states_with_targets": 2, "target_pairs": 3, "replay_states": 1})


def plans_for_adapter():
    baseline = {"run_id": "base", "arm": "answer", "source_cohort": 128,
        "cwd": "/frozen/base", "output": "/output/base", "compute_phase": "original",
        "environment": {"CUDA_VISIBLE_DEVICES": "2,3",
                        "PYTHONPATH": "/frozen/base/src:/frozen/base/tools"},
        "argv": ["python", "/frozen/base/tools/train_bounded_laya.py", "/data", "/init",
                 "/output/base", "--optimizer-updates", "192", "--compute-phase", "original"]}
    original = {"source_version": "base", "frozen_lab": "/frozen/base",
        "common_initialization": "/init", "protocol": "/protocol", "plans": [baseline]}
    quality = {"base_runtime": "/frozen/base", "common_initialization": "/init",
        "training_overlay": "/overlay", "source_cohort": 128, "target": "answer",
        "first_comparison": list(QUALITY_MODES), "plans": []}
    for mode in QUALITY_MODES:
        spec = copy.deepcopy(baseline)
        spec.update(run_id=mode, arm=mode, output="/output/"+mode, compute_phase=mode)
        spec["argv"][1] = "/overlay/train_bounded_laya.py"
        spec["argv"][4] = spec["output"]
        spec["argv"][-1] = mode
        spec["argv"].extend(["--pair-supervision", mode])
        spec["environment"]["PYTHONPATH"] = "/frozen/base/src:/overlay:/frozen/base/tools"
        quality["plans"].append(spec)
    return quality, original


def test_quality_plan_reuses_exact_budget_and_keeps_original_plan_immutable():
    quality, original = plans_for_adapter()
    before = copy.deepcopy((quality, original))
    adapted = quality_analysis_plan(quality, original)
    assert [p["quality_mode"] for p in adapted["plans"]] == list(QUALITY_MODES)
    assert all(p["arm"] == "answer" for p in adapted["plans"])
    assert (quality, original) == before
    quality["plans"][0]["argv"][6] = "193"
    with pytest.raises(ValueError, match="budget/recipe"):
        quality_analysis_plan(quality, original)
