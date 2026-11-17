"""Declared base logits are architecture, not an exception-triggered fallback."""
import copy

import pytest

from milai_lab.methods.control_observation import control_input
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


def test_zero_residual_prior_aligns_original_binding_under_readout_reordering():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel

    state = MemoryControlState(task={"request": "Find evidence"})
    actions = [MemoryAction("stop", "HANDOFF", "Reader"),
               MemoryAction("open", "READ", "candidate", {"index": 0}),
               MemoryAction("discover", "SEARCH", "request")]
    row = control_input(state, actions)
    original = copy.deepcopy(row)
    model = SmallControlModel.__new__(SmallControlModel)
    model.config = SmallControlConfig("frozen_mlp", "unused", prior_policy="fixed_context",
                                     head_initialization="zero_output_v1")
    delta = torch.zeros(3, requires_grad=True)
    logits = model.with_prior(delta, row, ["discover", "stop", "open"])
    assert logits.tolist() == [1., 0., 0.]
    logits.sum().backward()
    assert delta.grad.tolist() == [1., 1., 1.] and row == original
    with pytest.raises(ValueError, match="complete original menu"):
        model.with_prior(torch.zeros(2), row, ["stop", "open"])


def test_zero_residual_head_is_exact_and_can_receive_actual_optimization():
    torch = pytest.importorskip("torch")
    from milai_lab.methods.small_control_model import build_action_head

    head = build_action_head(4, 8, feature_normalization="block_layernorm_v2",
                             initialization="zero_output_v1")
    state, actions = torch.randn(1, 4), torch.randn(3, 4)
    owners = torch.zeros(3, dtype=torch.long)
    assert head(state, actions, owners).tolist() == [0., 0., 0.]
    optimizer = torch.optim.AdamW(head.parameters(), lr=.01)
    loss = -head(state, actions, owners)[1]
    loss.backward()
    assert head.network[-1].weight.grad.abs().sum() > 0
    optimizer.step()
    assert head(state, actions, owners).abs().sum() > 0
