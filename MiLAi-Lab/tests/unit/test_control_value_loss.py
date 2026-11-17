"""Known tied outcomes train value calibration; unknown/unexecuted actions stay masked."""
import copy

import pytest

from milai_lab.methods.small_control_learning import state_loss, window_loss


def test_known_false_ties_calibrate_values_without_inventing_pair_directions():
    torch = pytest.importorskip("torch")
    scores = torch.zeros(4, requires_grad=True)
    supervision = {"observed_action_ids": ["a", "b", "unknown"],
        "preferences": [{"left": "a", "right": "b", "outcome": "tie"}],
        "observed_values": {"a": 0., "b": 0., "unknown": None}, "value_loss_weight": .25}
    original = copy.deepcopy(supervision)
    loss = state_loss(scores, ["a", "b", "unknown", "unexecuted"], supervision)
    loss.backward()
    assert scores.grad.tolist() == [.0625, .0625, 0., 0.]
    assert supervision == original
    supervision["observed_values"]["unexecuted"] = 0.
    with pytest.raises(ValueError, match="actually observed"):
        state_loss(scores, ["a", "b", "unknown", "unexecuted"], supervision)


def test_value_unknown_single_action_and_default_pair_compatibility():
    torch = pytest.importorskip("torch")
    scores = torch.tensor([0.], requires_grad=True)
    unknown = {"observed_action_ids": ["a"], "observed_values": {"a": None},
               "value_loss_weight": .25}
    assert state_loss(scores, ["a"], unknown) is None
    known = {**unknown, "observed_values": {"a": 1.}}
    state_loss(scores, ["a"], known).backward()
    assert scores.grad.item() == -.125
    assert state_loss(scores, ["a"], {**known, "value_loss_weight": 0}) is None
    with pytest.raises(ValueError, match="unit interval"):
        state_loss(scores, ["a"], {**known, "observed_values": {"a": float("nan")}})


def test_pair_and_value_use_separate_global_window_denominators_across_microbatches():
    torch = pytest.importorskip("torch")
    functional = torch.nn.functional
    a = torch.tensor([.7, -.2, 3.], requires_grad=True)
    b = torch.tensor([.1, -.5, 4.], requires_grad=True)
    supervision = [
        {"observed_action_ids": ["good", "bad"], "preferences": [
            {"left": "good", "right": "bad", "outcome": "left"}],
         "observed_values": {"good": 1., "bad": 0.}, "value_loss_weight": .25},
        {"observed_action_ids": ["good", "bad"], "preferences": [
            {"left": "good", "right": "bad", "outcome": "tie"}],
         "observed_values": {"good": 0., "bad": 0.}, "value_loss_weight": .25}]
    ids, weights = ["good", "bad", "unexecuted"], [.5, 1.]
    # Union denominator1.5, pair denominator.5, value denominator1.5.
    scales = {"pair": 3., "value": 1.}
    losses = [state_loss(s, ids, labels, component_scales=scales)
              for s, labels in zip([a, b], supervision, strict=True)]
    combined, denominator = window_loss(losses, weights)
    expected = functional.softplus(a[1]-a[0]) + .25 * (
        .5*functional.binary_cross_entropy_with_logits(a[:2], torch.tensor([1., 0.])) +
        functional.binary_cross_entropy_with_logits(b[:2], torch.zeros(2))) / 1.5
    assert denominator == 1.5 and torch.allclose(combined, expected)
    joint_gradients = torch.autograd.grad(combined, [a, b], retain_graph=True)
    for loss, weight in zip(losses, weights, strict=True):
        (loss * weight / denominator).backward()
    assert torch.allclose(a.grad, joint_gradients[0]) and torch.allclose(b.grad, joint_gradients[1])
    assert a.grad[-1].item() == b.grad[-1].item() == 0.
