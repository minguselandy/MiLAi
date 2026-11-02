import copy
import math
import sys

import pytest

from replay_objective_diagnostic import loss_geometry
from train_bounded_laya import feedback_training_losses


def feedback_row(answer='left', quality='left'):
    return {'feedback': {'comparisons': [
        {'left': 'a', 'right': 'b', 'answer': answer, 'delivery': 'unknown',
         'basis': {'quality_before_resource_tiebreak': {
             'answer': quality, 'delivery': 'unknown'}}}]}}


def mixed_loss(mode):
    torch = pytest.importorskip('torch')
    logits = torch.tensor([[2., -1., 0., 99.], [4., -2., 0., 99.]], requires_grad=True)
    target = torch.tensor([[1 / 3, 1 / 3, 1 / 3, 0.], [.5, .5, 0., 0.]])
    mask = torch.tensor([[True, True, True, False]] * 2)
    rows = [feedback_row(), {'gold': {'next': {'probabilities': {'a': .5, 'b': .5}}}}]
    original = copy.deepcopy(rows)
    loss = feedback_training_losses(logits, target, mask, [['a', 'b', 'c']] * 2,
                                    rows, 'answer', 'quality-direction', mode)
    loss.sum().backward()
    assert rows == original
    return loss.detach(), logits.grad


def test_only_replay_changes_and_confident_accepted_choice_is_not_pushed_down():
    torch = pytest.importorskip('torch')
    ce_loss, ce_grad = mixed_loss('soft-ce')
    set_loss, set_grad = mixed_loss('set')
    assert ce_loss[0].item() == pytest.approx(math.log1p(math.exp(-3)))
    assert torch.equal(ce_loss[:1], set_loss[:1])
    assert torch.equal(ce_grad[0], set_grad[0])
    assert ce_loss[1] > 3 and set_loss[1] < .02
    assert ce_grad[1, 0] > 0 > set_grad[1, 0]
    assert set_grad[1, 2] > 0
    assert torch.equal(set_grad[:, 3], torch.zeros(2))


def test_unknown_feedback_remains_zero_and_single_positive_replay_is_unchanged():
    torch = pytest.importorskip('torch')
    results = []
    for objective in ('soft-ce', 'set'):
        logits = torch.tensor([[3., -1.], [3., -1.]], requires_grad=True)
        target = torch.tensor([[.5, .5], [1., 0.]])
        loss = feedback_training_losses(logits, target, torch.ones_like(target, dtype=torch.bool),
            [['a', 'b']] * 2, [feedback_row('unknown', 'unknown'), {}],
            'answer', 'quality-direction', objective)
        loss.sum().backward()
        assert logits.grad[0].tolist() == [0., 0.]
        results.append((loss.detach(), logits.grad))
    assert torch.allclose(results[0][0], results[1][0], atol=1e-7)
    assert torch.allclose(results[0][1], results[1][1], atol=1e-7)


def test_default_keeps_legacy_pair_and_soft_ce_replay():
    torch = pytest.importorskip('torch')
    logits = torch.tensor([[2., -1.], [2., -1.]])
    target = torch.tensor([[.5, .5], [.5, .5]])
    loss = feedback_training_losses(logits, target, torch.ones_like(target, dtype=torch.bool),
        [['a', 'b']] * 2, [feedback_row(), {}], 'answer', None)
    assert loss[0].item() == pytest.approx(math.log1p(math.exp(-3)))
    assert loss[1].item() == pytest.approx(math.log1p(math.exp(-3)) + 1.5)


def test_analytical_gradients_match_tensor_losses_and_permuted_bindings():
    torch = pytest.importorskip('torch')
    values = {'a': 4., 'b': -2., 'c': 0.}
    target = {'a': .5, 'b': .5, 'c': 0.}
    result = loss_geometry(values, target)
    from train_bounded_laya import decision_loss

    for objective, field in [('soft-ce', 'ce_gradient'), ('set', 'set_gradient')]:
        logits = torch.tensor([list(values.values())], dtype=torch.float64, requires_grad=True)
        loss = decision_loss(logits, torch.tensor([list(target.values())], dtype=torch.float64),
                             torch.ones_like(logits, dtype=torch.bool), objective)
        loss.sum().backward()
        assert logits.grad[0].tolist() == pytest.approx(list(result[field].values()), abs=1e-12)
    reverse = loss_geometry(dict(reversed(list(values.items()))), target)
    assert reverse['soft_ce'] == pytest.approx(result['soft_ce'])
    assert reverse['set_loss'] == pytest.approx(result['set_loss'])
    assert reverse['set_gradient'] == pytest.approx(result['set_gradient'])


def test_all_accepted_actions_have_zero_set_gradient_without_uniformizing():
    result = loss_geometry({'a': 10., 'b': -10.}, {'a': .5, 'b': .5})
    assert result['set_loss'] == pytest.approx(0)
    assert result['set_gradient_l1'] < 1e-14
    assert result['ce_gradient_l1'] > .99


def test_replay_flag_cannot_silently_change_non_pair_training(monkeypatch, tmp_path, capsys):
    from train_bounded_laya import main

    monkeypatch.setattr(sys, 'argv', ['train_bounded_laya.py', str(tmp_path / 'data'),
        str(tmp_path / 'checkpoint'), str(tmp_path / 'output'), '--budget',
        str(tmp_path / 'budget.json'), '--replay-objective', 'set'])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert '--replay-objective applies only to pair training' in capsys.readouterr().err
    assert not (tmp_path / 'output').exists()
