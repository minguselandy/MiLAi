"""Pair masks and independently normalized task/replay gradients of the new objective."""
import copy
import math
import sys

import pytest
from test_quality_fit_audit import closed_quality_fit

from analyze_feedback_fit import analyze, nominate_answer_first, validate_answer_first_exposure
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from quality_feedback import (
    answer_first_counts,
    answer_first_pairs,
    answer_first_weights,
    quality_event_weights,
    score_answer_first,
)
from train_bounded_laya import feedback_training_losses, main


def pair(left, right, answer, delivery):
    return {"left": left, "right": right, "answer": answer, "delivery": delivery,
            "basis": {"quality_before_resource_tiebreak": {
                "answer": answer, "delivery": delivery}}}


def row(family="A", event="event", index=0, pairs=None):
    return {"metadata": {"family": family, "training_event": event, "row": index},
        "feedback": {"comparisons": pairs if pairs is not None else [
            pair("a", "b", "tie", "right"), pair("a", "c", "unknown", "left"),
            pair("c", "d", "unknown", "unknown")]}}


def replay():
    return {"metadata": {"family": "old", "training_event": "old", "row": 99},
            "gold": {"next": {"probabilities": {"a": .5, "b": .5}}}}


def tensor_loss(rows, *, permutation=(0, 1, 2, 3)):
    torch = pytest.importorskip("torch")
    names = ["a", "b", "c", "d"]
    values = [[2., 0., -1., 5.], [4., -2., 0., 9.], [3., 2., -1., 8.]]
    logits = torch.tensor([[values[i][j] for j in permutation] for i in range(len(rows))],
                          dtype=torch.float64, requires_grad=True)
    keys = [[names[j] for j in permutation]] * len(rows)
    targets = torch.tensor([[.5, .5, 0., 0.]] * len(rows), dtype=torch.float64)[:, permutation]
    losses = feedback_training_losses(logits, targets,
        torch.ones_like(logits, dtype=torch.bool), keys, rows, "answer", None, "set",
        component_weights=answer_first_weights(rows, .25))
    return logits, losses


def test_answer_tie_remains_answer_and_auxiliary_uses_only_its_own_unknown_pairs():
    original = row()
    saved = copy.deepcopy(original)
    parts = answer_first_pairs(original["feedback"]["comparisons"])
    assert parts["answer"] == original["feedback"]["comparisons"][:1]
    assert parts["delivery_auxiliary"] == original["feedback"]["comparisons"][1:2]
    counts = answer_first_counts([original, replay()])
    assert (counts["target_pairs"], counts["tie_pairs"], counts["directional_pairs"],
            counts["unknown_pairs"], counts["answer_unknown_pairs"]) == (2, 1, 1, 1, 2)
    assert counts["components"]["delivery_auxiliary"] == {
        "states": 1, "pairs": 1, "directional_pairs": 1, "families": 1, "events": 1}
    assert original == saved


def test_actual_tensor_loss_is_point8_answer_point2_auxiliary_plus_point25_set_replay():
    rows = [row(), replay()]
    logits, losses = tensor_loss(rows)
    loss = losses.mean()
    expected_answer = .5 * (math.log1p(math.exp(-2)) + math.log1p(math.exp(2)))
    expected_delivery = math.log1p(math.exp(-3))
    expected_replay = (math.log(sum(math.exp(v) for v in [4, -2, 0, 9]))
                       - math.log(math.exp(4) + math.exp(-2)))
    assert loss.item() == pytest.approx(
        .8 * expected_answer + .2 * expected_delivery + .25 * expected_replay, abs=1e-12)
    loss.backward()
    assert logits.grad[0, 3] == 0  # Unknown pair/unreviewed action is not a negative.
    assert logits.grad[0, 1] < 0  # Answer tie pushes its margin towards zero.
    assert logits.grad[0, 2] > 0  # Delivery auxiliary has a real gradient in this same row.
    assert logits.grad[1, 0] < 0  # Accepted replay choice need not become uniform.


def test_missing_component_does_not_transfer_mass_and_unknown_rows_do_not_dilute():
    unknown = row("unknown", pairs=[pair("a", "b", "unknown", "unknown")])
    rows = [row(pairs=[pair("a", "b", "left", "right")]), replay(), unknown]
    weights = answer_first_weights(rows, .25)
    assert weights == [{"answer": pytest.approx(2.4), "delivery_auxiliary": 0., "replay": 0.},
                       {"answer": 0., "delivery_auxiliary": 0., "replay": .75},
                       {"answer": 0., "delivery_auxiliary": 0., "replay": 0.}]
    short_logits, short_losses = tensor_loss(rows[:2])
    logits, losses = tensor_loss(rows)
    assert losses.mean().item() == pytest.approx(short_losses.mean().item())
    losses.mean().backward()
    short_losses.mean().backward()
    assert logits.grad[2].tolist() == [0.] * 4
    assert logits.grad[:2].tolist() == short_logits.grad.tolist()


def test_duplicate_events_do_not_change_component_source_mass():
    rows = [row(), row(index=1), row(event="other", index=2), row("B", "third", 3), replay()]
    weights = answer_first_weights(rows, .25)
    for component, mass in [("answer", .8), ("delivery_auxiliary", .2)]:
        assert sum(w[component] for w in weights) / len(rows) == pytest.approx(mass)
        assert weights[0][component] == weights[1][component]
        assert weights[0][component] * 2 == weights[2][component]
        assert sum(w[component] for w in weights[:3]) == weights[3][component]
    assert sum(w["replay"] for w in weights) / len(rows) == .25


def test_saved_logit_diagnostic_matches_training_task_loss_and_binding_permutations():
    rows = [row()]
    logits, losses = tensor_loss(rows)
    expected = losses.mean().item()
    predictions = [{"logits": dict(zip(["a", "b", "c", "d"], logits[0].tolist(), strict=True))}]
    report = score_answer_first(rows, predictions)
    assert report["weighted_task_pair_loss"] == pytest.approx(expected)
    losses.mean().backward()
    order = [3, 1, 0, 2]
    permuted, permuted_losses = tensor_loss(rows, permutation=order)
    assert permuted_losses.mean().item() == pytest.approx(expected)
    permuted_losses.mean().backward()
    assert [permuted.grad[0, order.index(i)].item() for i in range(4)] == logits.grad[0].tolist()


def test_task_only_diagnostic_keeps_missing_components_unknown_instead_of_zero_success():
    rows = [row(pairs=[pair("a", "b", "unknown", "unknown")])]
    report = score_answer_first(rows, [{"logits": {"a": 100., "b": -100.}}])
    assert report["weighted_task_pair_loss"] == 0.
    assert report["components"]["answer"]["family_event_pair_loss"] is None
    assert report["coverage"]["states_with_targets"] == 0


def test_delivery_control_can_match_total_mass_without_changing_historical_default():
    rows = [row(), replay()]
    old = quality_event_weights(rows, "delivery", "quality-tie", .25)
    new = quality_event_weights(rows, "delivery", "quality-tie", .25, normalize_total=False)
    assert old == pytest.approx([1.6, .4])
    assert new == pytest.approx([2., .5])
    assert sum(new) / len(rows) == 1.25


def test_nomination_is_limited_to_two_trained_points_and_has_no_task_success_claim():
    points = [{"update": update, "checkpoint": str(update), "answer_first": {
        "coverage": {"target_pairs": pairs}, "weighted_task_pair_loss": loss}}
        for update, loss, pairs in [(0, .1, 2), (16, .4, 2), (32, .2, 2),
                                   (64, .2, 2), (128, 0., 0)]]
    assert nominate_answer_first(points) == [
        {"update": 32, "checkpoint": "32"}, {"update": 64, "checkpoint": "64"}]
    assert nominate_answer_first(points[:1]) == []


def test_component_exposure_audit_counts_actual_repeated_pairs_not_unique_sources():
    counts = answer_first_counts([row(), row()])
    measured = {name + "_" + field: support.get(field, 0)
        for name, support in counts["components"].items()
        for field in ("states", "pairs", "directional_pairs", "tie_pairs")}
    validate_answer_first_exposure({"sampled_answer_first_components": measured}, counts)
    assert measured["answer_states"] == 2
    assert counts["components"]["answer"]["families"] == 1
    measured["delivery_auxiliary_pairs"] = 0
    with pytest.raises(ValueError, match="pair exposure"):
        validate_answer_first_exposure({"sampled_answer_first_components": measured}, counts)


def test_answer_first_cli_requires_declared_answer_and_set_replay(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["train_bounded_laya", str(tmp_path / "data"),
        str(tmp_path / "base"), str(tmp_path / "output"), "--budget", "unused.json",
        "--objective", "pair", "--feedback-target", "answer", "--task", "memory_operation",
        "--optimizer-updates", "1", "--feedback-dev-data", "dev.jsonl",
        "--pair-supervision", "answer-first"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--replay-objective set" in capsys.readouterr().err
    assert not (tmp_path / "output").exists()


def test_closed_masked_fit_audit_preserves_support_and_only_nominates(tmp_path):
    plan, root = closed_quality_fit(tmp_path, "quality-tie")
    argv = plan["plans"][0]["argv"]
    argv[argv.index("--pair-supervision") + 1] = "answer-first"
    argv.extend(["--replay-objective", "set"])
    train = read_jsonl(tmp_path / "data/train.jsonl")
    feedback = read_jsonl(tmp_path / "data/feedback-dev.jsonl")
    run = read_json(root / "run.json")
    run.update(pair_supervision="answer-first", replay_objective="set",
        pair_mass_mode="component-sum", feedback_pool=answer_first_counts(train),
        answer_first_component_masses={"answer": .8, "delivery_auxiliary": .2, "replay": .25})
    draws = [i for _, windows in read_json(root / "training-plan.json")
             for window in windows for _, i in window]
    counts = answer_first_counts([train[i] for i in draws])
    run["sampled_answer_first_components"] = {name + "_" + field: support.get(field, 0)
        for name, support in counts["components"].items()
        for field in ("states", "pairs", "directional_pairs", "tie_pairs")}
    write_json(root / "run.json", run)
    for folder in (root / "checkpoints/update-1", root / "checkpoint"):
        write_json(folder / "rl_agent_config.json", {"training": {"milai_reader": run}})
    sampling = read_json(root / "sampling.json")
    for record, weight in zip(sampling, answer_first_weights(train, .25), strict=True):
        record.update(weight=1., answer_first_component_weights=weight)
    write_json(root / "sampling.json", sampling)
    history = read_json(root / "history.json")
    for point in history:
        directory = root / "feedback-dev" / str(point["optimizer_updates"])
        predictions = [read_json(directory / f"{i}.json") for i in range(len(feedback))]
        metric = score_answer_first(feedback, predictions)
        summary = read_json(directory / "summary.json")
        summary["answer_first"] = metric
        write_json(directory / "summary.json", summary)
        point["feedback-dev"]["answer_first"] = metric
    write_json(root / "history.json", history)
    compute = read_json(root / "compute.json")
    compute.update({"train_answer_first_" + k: v
                    for k, v in run["sampled_answer_first_components"].items()})
    write_json(root / "compute.json", compute)
    write_json(tmp_path / "ledger.json", {"compute": {"unit": {
        k: v for k, v in compute.items() if k != "ledger"}}})
    result = analyze(plan, "unit", answer_first=True, replay_objective="set")
    assert result["in_memory_selection"] is result["deployment_selection"] is None
    assert result["offline_nominations"][0]["update"] == 1
    assert "ACTUAL_CHOICE_SELECTION_PENDING" in result["status"]
    # Unknown auxiliary mass cannot silently be redirected to answer-known states.
    sampling[0]["answer_first_component_weights"]["answer"] += .2
    write_json(root / "sampling.json", sampling)
    with pytest.raises(ValueError, match="Independent answer/auxiliary/replay weights"):
        analyze(plan, "unit", answer_first=True, replay_objective="set")
