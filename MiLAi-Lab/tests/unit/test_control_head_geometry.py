"""The optional head can retain similarity geometry that block normalization discards."""
import pytest


def test_retained_statistics_distinguish_aligned_and_opposed_unit_vectors():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import build_action_head

    state = torch.full((1, 4), .5, requires_grad=True)
    actions = torch.tensor([[.5] * 4, [-.5] * 4], requires_grad=True)
    owners = torch.tensor([0, 0])
    previous = build_action_head(4, 4, feature_normalization="block_layernorm_v2")
    previous_scores = previous(state, actions, owners)
    assert previous_scores[0] == previous_scores[1]
    assert (state[owners] * actions).sum(-1).tolist() == [1., -1.]

    retained = build_action_head(4, 4, feature_normalization="block_layernorm_stats_v3")
    with torch.no_grad():
        for parameter in retained.parameters():
            parameter.zero_()
        # A single trainable hidden unit can use the retained product sum.
        retained.network[0].weight[0, 4 * 4 + 4] = 1
        retained.network[-1].weight[0, 0] = 1
    scores = retained(state, actions, owners)
    assert scores[0] > scores[1]
    (scores - torch.tensor([1., -1.])).square().sum().backward()
    assert torch.isfinite(state.grad).all() and torch.isfinite(actions.grad).all()
    statistics_gradient = retained.network[0].weight.grad[:, 16:]
    assert torch.isfinite(statistics_gradient).all() and statistics_gradient.abs().sum() > 0


@pytest.mark.parametrize("interaction", [False, True])
def test_zero_statistics_columns_preserve_previous_head_and_binding_permutation(interaction):
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import build_action_head

    width, hidden = 4, 8
    previous = build_action_head(width, hidden, set_interaction=interaction,
                                feature_normalization="block_layernorm_v2")
    retained = build_action_head(width, hidden, set_interaction=interaction,
                                feature_normalization="block_layernorm_stats_v3")
    previous_width = previous.network[0].in_features
    statistics_width = 2 * (5 if interaction else 4)
    assert retained.network[0].in_features == previous_width + statistics_width
    with torch.no_grad():
        retained.network[0].weight[:, :previous_width].copy_(previous.network[0].weight)
        retained.network[0].weight[:, previous_width:].zero_()
        retained.network[0].bias.copy_(previous.network[0].bias)
        retained.network[-1].load_state_dict(previous.network[-1].state_dict())
    states, actions = torch.randn(2, width), torch.randn(5, width)
    owners = torch.tensor([0, 0, 1, 1, 1])
    order = torch.tensor([1, 0, 4, 2, 3])
    expected = previous(states, actions, owners)
    actual = retained(states, actions, owners)
    assert torch.allclose(expected, actual, atol=1e-6)
    assert torch.allclose(actual[order], retained(states, actions[order], owners[order]), atol=1e-6)
