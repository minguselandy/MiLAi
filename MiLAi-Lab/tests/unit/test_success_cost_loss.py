"""Measured cheaper-success ranking is separate from quality and partial-label masks."""
import copy

import pytest

from milai_lab.methods.small_control_learning import state_loss, window_loss


def labels():
    return {"observed_action_ids": ["cheap", "dear", "failed", "unknown"],
        "observed_values": {"cheap": 1., "dear": 1., "failed": 0., "unknown": None},
        "success_cost_witness_values": {"cheap": 1., "dear": 1., "failed": 0., "unknown": None},
        "observed_costs": {"cheap": {"material_UTF8_tokens": 3},
                           "dear": {"material_UTF8_tokens": 7}},
        "success_cost_loss_weight": 1., "success_cost_preferences": [
            {"left": "cheap", "right": "dear", "outcome": "left",
             "axis": "material_UTF8_tokens"}]}


def test_only_observed_agreed_success_pair_gets_cost_gradient():
    torch = pytest.importorskip("torch")
    scores = torch.zeros(5, requires_grad=True)
    data = labels()
    original = copy.deepcopy(data)
    loss = state_loss(scores, ["cheap", "dear", "failed", "unknown", "unexecuted"], data)
    loss.backward()
    assert scores.grad.tolist() == [-.5, .5, 0., 0., 0.]
    assert data == original
    repeated = {**data, "success_cost_preferences": data["success_cost_preferences"] * 5}
    assert state_loss(scores, ["cheap", "dear", "failed", "unknown", "unexecuted"],
                      repeated).item() == loss.item()


@pytest.mark.parametrize("field,value", [
    ("observed_values", None), ("observed_values", 0.),
    ("success_cost_witness_values", None), ("success_cost_witness_values", 0.),
])
def test_unknown_failed_or_single_witness_cannot_be_a_cheap_success(field, value):
    torch = pytest.importorskip("torch")
    data = labels()
    data[field]["cheap"] = value
    with pytest.raises(ValueError, match="both known success"):
        state_loss(torch.zeros(4), ["cheap", "dear", "failed", "unknown"], data)


@pytest.mark.parametrize("bad", [None, -1, float("nan"), float("inf"), True])
def test_missing_nonfinite_or_invalid_measured_cost_is_rejected(bad):
    torch = pytest.importorskip("torch")
    data = labels()
    data["observed_costs"]["cheap"]["material_UTF8_tokens"] = bad
    with pytest.raises(ValueError, match="known finite nonnegative"):
        state_loss(torch.zeros(4), ["cheap", "dear", "failed", "unknown"], data)


def test_wrong_axis_direction_and_unexecuted_bindings_fail_instead_of_adding_negatives():
    torch = pytest.importorskip("torch")
    ids = ["cheap", "dear", "failed", "unknown", "unexecuted"]
    for mutation, message in [("axis", "actual measured resource"),
                              ("direction", "unequal measured costs"),
                              ("tie", "unequal measured costs"),
                              ("unexecuted", "actually observed")]:
        data = labels()
        pair = data["success_cost_preferences"][0]
        if mutation == "axis":
            pair["axis"] = "legacy_ASCII_JSON_packet_token_proxy"
        elif mutation == "direction":
            pair["outcome"] = "right"
        elif mutation == "tie":
            data["observed_costs"]["cheap"]["material_UTF8_tokens"] = 7
        else:
            pair["left"] = "unexecuted"
        with pytest.raises(ValueError, match=message):
            state_loss(torch.zeros(5), ids, data)


def test_zero_default_preserves_exact_old_quality_value_loss_and_masks():
    torch = pytest.importorskip("torch")
    f = torch.nn.functional
    scores = torch.tensor([.7, -.2, 1.5, 8., 9.], requires_grad=True)
    data = {"observed_action_ids": ["cheap", "dear", "failed", "unknown"],
        "preferences": [{"left": "cheap", "right": "failed", "outcome": "left"}],
        "observed_values": {"cheap": 1., "dear": 1., "failed": 0., "unknown": None},
        "value_loss_weight": .5}
    ids = ["cheap", "dear", "failed", "unknown", "unexecuted"]
    expected = f.softplus(scores[2] - scores[0]) + .5 * f.binary_cross_entropy_with_logits(
        scores[:3], torch.tensor([1., 1., 0.]))
    old = state_loss(scores, ids, data)
    assert torch.equal(old, expected)
    data.update(success_cost_loss_weight=0., success_cost_preferences=[{"invalid": "ignored"}])
    assert torch.equal(state_loss(scores, ids, data), old)
    old.backward()
    assert scores.grad[3:].tolist() == [0., 0.]
    for value in (-1., float("nan")):
        with pytest.raises(ValueError, match="finite and nonnegative"):
            state_loss(scores, ids, {**data, "success_cost_loss_weight": value})


def test_independent_component_source_denominators_equal_full_and_microbatch_gradients():
    torch = pytest.importorskip("torch")
    f = torch.nn.functional
    ids = ["cheap", "dear", "failed", "unknown", "unexecuted"]
    a = torch.tensor([.7, -.2, 1.5, 8., 9.], requires_grad=True)
    b = torch.tensor([.1, -.5, 2., 7., 9.], requires_grad=True)
    unknown = torch.zeros(5, requires_grad=True)
    q = labels()
    q.update(success_cost_preferences=[], observed_values={"cheap": 1., "failed": 0.},
             preferences=[{"left": "cheap", "right": "failed", "outcome": "left"}],
             value_loss_weight=.5)
    cost = labels()
    cost.update(value_loss_weight=.5, observed_values={"cheap": 1., "dear": 1.})
    masked = {"observed_action_ids": ["cheap"], "observed_values": {"cheap": None},
              "success_cost_loss_weight": 1., "value_loss_weight": .5}
    # Source/window weights .25/.5, union/value denominator .75; quality .25; cost .5.
    scales = {"pair": 3., "value": 1., "success_cost": 1.5}
    losses = [state_loss(s, ids, data, component_scales=scales)
              for s, data in zip([a, b, unknown], [q, cost, masked], strict=True)]
    assert losses[2] is None
    joint, denominator = window_loss(losses, [.25, .5, 1.])
    expected = f.softplus(a[2] - a[0]) + .5 * (
        .25 * f.binary_cross_entropy_with_logits(a[[0, 2]], torch.tensor([1., 0.]))
        + .5 * f.binary_cross_entropy_with_logits(b[:2], torch.ones(2))) / .75
    expected = expected + f.softplus(b[1] - b[0])
    assert denominator == .75 and torch.allclose(joint, expected)
    reference = torch.autograd.grad(expected, [a, b], retain_graph=True)
    for loss, weight in zip(losses[:2], [.25, .5], strict=True):
        (loss * weight / denominator).backward()
    assert torch.allclose(a.grad, reference[0]) and torch.allclose(b.grad, reference[1])
    assert a.grad[3:].tolist() == b.grad[3:].tolist() == [0., 0.]
    assert unknown.grad is None
