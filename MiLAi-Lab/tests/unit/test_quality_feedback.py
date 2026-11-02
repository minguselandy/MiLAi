"""Known quality targets, unchanged pair support, and masked tensor gradients."""

import copy
import math

import pytest

from quality_feedback import (
    QUALITY_MODES,
    choose_quality_checkpoint,
    outcome,
    quality_counts,
    quality_event_weights,
    quality_pair_loss,
    score_quality_feedback,
    targets,
    validate_quality_pool,
)
from retrieval_feedback import RESOURCE_FIELDS, pair_loss


def example():
    lower = dict.fromkeys(RESOURCE_FIELDS, 0)
    higher = {**lower, "read_operations": 1}
    return {"state": {"text": "Original observed state"}, "questions": {"next": {"criteria": {
        "read": "READ", "stop": "HANDOFF", "view": "REFRESH_VIEW", "unreviewed": "READ"}}},
        "gold": {}, "metadata": {"family": "A", "row": 0, "state_id": 0, "training_event": "a"},
        "feedback": {"comparisons": [
            {"left": "read", "right": "stop", "answer": "left", "delivery": "unknown",
             "basis": {"quality_before_resource_tiebreak": {"answer": "tie", "delivery": "unknown"},
                       "resource_order": {"left": lower, "right": higher}}},
            {"left": "read", "right": "view", "answer": "unknown", "delivery": "left",
             "basis": {"quality_before_resource_tiebreak": {
                           "answer": "unknown", "delivery": "left"},
                       "resource_order": {"left": higher, "right": lower}}},
        ]}}


def test_modes_separate_tie_cost_and_unknown_without_changing_saved_data():
    row = example()
    before = copy.deepcopy(row)
    validate_quality_pool([row])
    pairs = row["feedback"]["comparisons"]
    assert targets(pairs, "answer", "quality-direction") == []
    assert targets(pairs, "answer", "quality-tie") == [("read", "stop", .5)]
    assert targets(pairs, "answer", "quality-cost") == [("read", "stop", 1.0)]
    for mode in QUALITY_MODES:
        assert targets(pairs, "delivery", mode) == [("read", "view", 1.0)]
    assert row == before


def test_incomparable_cost_keeps_a_half_target_and_cannot_override_quality():
    row = example()
    pair = row["feedback"]["comparisons"][0]
    pair["basis"]["resource_order"]["left"]["retrieval_generation_requests"] = 1
    pair["answer"] = "tie"
    validate_quality_pool([row])
    assert targets([pair], "answer", "quality-cost") == [("read", "stop", .5)]
    row["feedback"]["comparisons"][1]["delivery"] = "right"
    with pytest.raises(ValueError, match="quality/cost evidence"):
        validate_quality_pool([row])


def test_tie_gradient_moves_to_zero_cost_direction_moves_apart_and_unknown_is_unpressured():
    torch = pytest.importorskip("torch")
    pairs = example()["feedback"]["comparisons"]
    keys = ["read", "stop", "view", "unreviewed"]
    gradients = {}
    for mode in QUALITY_MODES:
        logits = torch.tensor([1000.0, 0.0, 5000.0, -4000.0, -float("inf")], requires_grad=True)
        loss = quality_pair_loss(logits, keys, pairs, "answer", mode)
        loss.backward()
        assert torch.isfinite(loss) and torch.isfinite(logits.grad).all()
        assert logits.grad[2:].tolist() == [0, 0, 0]
        gradients[mode] = logits.grad[:2].tolist()
    assert gradients["quality-tie"] == [.5, -.5]
    assert gradients["quality-direction"] == [0, 0]
    # At a non-saturated positive margin, the cost target explicitly favors read.
    logits = torch.tensor([1.0, 0.0, 0.0, 0.0], requires_grad=True)
    quality_pair_loss(logits, keys, pairs, "answer", "quality-cost").backward()
    assert logits.grad[0] < 0 < logits.grad[1]
    logits = torch.zeros(4, requires_grad=True)
    quality_pair_loss(logits, keys, pairs, "delivery", "quality-tie").backward()
    assert logits.grad[1] == 0 and logits.grad[2] > 0  # Answer unknown did not mask delivery.


def test_known_pair_mean_and_option_permutation_preserve_semantic_loss_and_gradients():
    torch = pytest.importorskip("torch")
    row = example()
    pairs = row["feedback"]["comparisons"]
    keys = list(row["questions"]["next"]["criteria"])
    values = [2.0, 0.0, 0.0, 100.0]
    one = quality_pair_loss(torch.tensor(values), keys, pairs, "answer", "quality-tie")
    pairs[1]["basis"]["quality_before_resource_tiebreak"]["answer"] = "tie"
    pairs[1]["answer"] = "right"
    two = quality_pair_loss(torch.tensor(values), keys, pairs, "answer", "quality-tie")
    assert two.item() == one.item()  # Two equally difficult pairs do not double a state's loss.
    observed = []
    for order in ([0, 1, 2, 3], [3, 2, 0, 1]):
        logits = torch.tensor([values[i] for i in order], requires_grad=True)
        loss = quality_pair_loss(logits, [keys[i] for i in order], pairs, "answer", "quality-tie")
        loss.backward()
        observed.append({keys[i]: logits.grad[j].item() for j, i in enumerate(order)})
    assert observed[0] == observed[1]


def test_unknown_states_do_not_dilute_known_mass_and_tie_cost_weights_and_draws_match():
    known = example()
    replay = {**copy.deepcopy(known), "gold": {"next": {"probabilities": {"read": 1.0}}}}
    del replay["feedback"]
    replay["metadata"].update(family="old", row=1, state_id=1, training_event="old")
    unknown = copy.deepcopy(known)
    unknown["metadata"].update(family="unknown", row=2, state_id=2, training_event="unknown")
    for pair in unknown["feedback"]["comparisons"]:
        pair["answer"] = pair["basis"]["quality_before_resource_tiebreak"]["answer"] = "unknown"
    rows = [known, replay, unknown]
    before = copy.deepcopy(rows)
    weights = quality_event_weights(rows, "answer", "quality-tie", .25)
    assert weights == pytest.approx([2.4, .6, 0])
    assert weights == quality_event_weights(rows, "answer", "quality-cost", .25)
    original = quality_event_weights(rows[:2], "answer", "quality-tie", .25)
    assert sum(w*loss for w, loss in zip(weights, [3, 5, 999], strict=True))/3 == pytest.approx(
        sum(w*loss for w, loss in zip(original, [3, 5], strict=True))/2)
    assert quality_event_weights(rows, "answer", "quality-direction", .25) == pytest.approx(
        [0, .6, 0])
    assert len(weights) == len(rows)
    assert rows == before
    assert quality_counts(rows, "answer", "quality-tie")["target_pairs"] == 1
    assert quality_counts(rows, "answer", "quality-cost")["cost_only_direction_pairs"] == 1


def test_original_direction_loss_unchanged_and_known_ties_have_zero_gradient_at_equal_scores():
    torch = pytest.importorskip("torch")
    pairs = example()["feedback"]["comparisons"]
    values = torch.tensor([.2, -.1, .7, 8.0], requires_grad=True)
    keys = ["read", "stop", "view", "unreviewed"]
    assert quality_pair_loss(values, keys, pairs, "delivery", "quality-direction").item() == (
        pair_loss(values, keys, pairs, "delivery").item())
    equal = torch.zeros(4, requires_grad=True)
    loss = quality_pair_loss(equal, keys, pairs, "answer", "quality-tie")
    loss.backward()
    assert loss.item() == pytest.approx(math.log(2)) and equal.grad.tolist() == [0, 0, 0, 0]


def test_quality_evaluation_is_independent_of_cost_and_keeps_unknown_out_of_loss():
    row = example()
    prediction = {"logits": {"read": 1.0, "stop": 0.0, "view": 5000.0, "unreviewed": 9000.0}}
    result = score_quality_feedback([row], [prediction], "answer")
    expected = .5*(math.log1p(math.exp(-1)) + math.log1p(math.exp(1)))
    assert result["family_macro_state_known_pair_loss"] == pytest.approx(expected)
    assert result["directional"]["family_macro_state_pair_accuracy"] is None
    assert outcome(row["feedback"]["comparisons"][0], "answer", "quality-cost") == "left"
    points = [{"update": u, "pure_quality": {"answer": {"directional": {
        "family_macro_state_pair_accuracy": value}}}, "cost_score": cost}
              for u, value, cost in [(0, .8, .1), (12, .8, .9), (24, .7, 1.0)]]
    assert choose_quality_checkpoint(points, "answer")["update"] == 0
