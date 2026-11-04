"""Conditional scheduling preserves ordinary coverage and complete pair forwards."""
from __future__ import annotations

import copy
import json
import math
import os
import sys
from collections import Counter

import pytest

from conditional_training import (
    conditional_change_targets,
    conditional_relative_loss,
    conditional_training_groups,
)
from train_bounded_laya import training_microbatches, training_stages


def training_pool():
    rows = []
    for index in range(35):
        label = index % 3 == 0
        rows.append({"state": {"candidate": {"text": str(index // 2)},
            "task": {"retrieval_request": {"query": "query", "read_goal": {
                "purpose": "base" if index % 2 == 0 else "condition"}}}},
            "gold": {"applicability": {"probabilities": {
                "satisfies": float(label), "does_not_satisfy": float(not label)}}},
            "metadata": {"event_id": str(index), "split": "train", "family": "f",
                         "query_unit": "q"}})
    pairs = [{"left_event": str(i), "right_event": str(i + 1), "family": "f",
              "query_unit": "q", "left_label": i % 3 == 0,
              "right_label": (i + 1) % 3 == 0,
              "kind": "stable" if i % 3 == 1 else "change"} for i in range(0, 20, 2)]
    return rows, pairs


def test_full_pass_retains_unpaired_positive_units_and_pairs_in_every_forward():
    rows, pairs = training_pool()
    before = copy.deepcopy((rows, pairs))
    groups = conditional_training_groups(rows, pairs, 0)
    updates = math.ceil(len(rows) / 16) * 2
    stages = training_stages(len(rows), 2, 0, updates, [2, 4, 6], row_groups=groups)
    windows = [w for _, ws in stages for w in ws]
    assert [step for step, _ in stages] == [2, 4, 6]
    assert [len(w) for w in windows] == [16, 16, 3, 16, 16, 3]
    assert Counter(draw for w in windows for draw in w) == Counter(
        (epoch, i) for epoch in (1, 2) for i in range(35))
    forwards = [micro for window in windows for micro in training_microbatches(window, 2)]
    for epoch in (1, 2):
        for pair in pairs:
            left, right = (epoch, int(pair['left_event'])), (epoch, int(pair['right_event']))
            assert any(left in forward and right in forward for forward in forwards)
    assert (rows, pairs) == before
    assert stages == training_stages(len(rows), 2, 0, updates, [2, 4, 6], row_groups=groups)


@pytest.mark.parametrize("mutation", ["label", "query", "candidate", "dev", "unknown", "shared"])
def test_no_unknown_stale_or_duplicated_pair_can_create_training_exposure(mutation):
    rows, pairs = training_pool()
    if mutation == "label":
        pairs[0]['left_label'] = False
    elif mutation in {"query", "candidate"}:
        if mutation == "query":
            rows[0]['state']['task']['retrieval_request']['query'] = 'other'
        else:
            rows[0]['state']['candidate']['text'] = 'other'
    elif mutation == "dev":
        rows[0]['metadata']['split'] = 'dev'
    elif mutation == "unknown":
        rows[0]['gold'] = {}
    else:
        pairs.append(copy.deepcopy(pairs[0]))
    with pytest.raises(ValueError):
        conditional_training_groups(rows, pairs, 0)


def test_group_budget_does_not_pad_drop_or_repeat_units():
    rows, pairs = training_pool()
    groups = conditional_training_groups(rows, pairs, 0)
    for budget in (2, 4):
        with pytest.raises(ValueError, match="full passes"):
            training_stages(35, 1, 0, budget, row_groups=groups)


def test_relative_targets_balance_change_families_without_stable_or_extra_exposures():
    rows, pairs = training_pool()
    pairs[0]['family'] = 'rare'
    for index in (0, 1):
        rows[index]['metadata']['family'] = 'rare'
    before = copy.deepcopy((rows, pairs))
    groups = conditional_training_groups(rows, pairs, 0)
    targets = conditional_change_targets(rows, pairs)
    expected = [p for p in pairs if p['kind'] == 'change']
    assert len(targets) == len(expected)
    assert all(list(indices) in groups for indices in targets)
    assert math.isclose(sum(weight for _, weight in targets.values()), len(expected))
    assert math.isclose(targets[(0, 1)][1] / len(expected), .5)
    assert math.isclose(sum(w for ids, (_, w) in targets.items() if ids != (0, 1))
                        / len(expected), .5)
    assert targets[(0, 1)][0] == 1 and targets[(2, 3)][0] == -1
    assert (4, 5) not in targets  # Stable-negative pair.
    assert all(i < 20 for indices in targets for i in indices)  # Unpaired units excluded.
    assert (rows, pairs) == before


@pytest.mark.parametrize('direction', [1., -1.])
def test_relative_loss_moves_both_conditions_and_is_option_order_invariant(direction):
    torch = pytest.importorskip('torch')
    keys = [['satisfies', 'does_not_satisfy']] * 2
    logits = torch.zeros((2, 2), requires_grad=True)
    loss = conditional_relative_loss(logits, keys, direction)
    assert math.isclose(loss.item(), math.log(2), rel_tol=1e-6)
    loss.backward()
    expected = torch.tensor([[-.5, .5], [.5, -.5]]) * direction
    torch.testing.assert_close(logits.grad, expected)
    improved = logits.detach() - .1 * logits.grad
    assert conditional_relative_loss(improved, keys, direction) < loss
    # Flip only one row's option slots; semantic margins and gradients must agree.
    shuffled = improved.clone()
    shuffled[1] = shuffled[1].flip(0)
    shuffled_keys = [keys[0], list(reversed(keys[1]))]
    torch.testing.assert_close(conditional_relative_loss(shuffled, shuffled_keys, direction),
                               conditional_relative_loss(improved, keys, direction))
    # Per-row logit offsets must not change either applicability margin.
    shifted = improved + torch.tensor([[8.], [-5.]])
    torch.testing.assert_close(conditional_relative_loss(shifted, keys, direction),
                               conditional_relative_loss(improved, keys, direction))


@pytest.mark.parametrize('condition_weight', [0., .25])
@pytest.mark.parametrize('parallel_mode,precision', [('legacy-dp', 'float32'), ('single', 'bf16')])
def test_native_grouped_unit_fit_uses_exact_rows_and_scaled_component_weights(
    tmp_path, monkeypatch, condition_weight, parallel_mode, precision,
):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3" or torch.cuda.device_count() != 2:
        pytest.skip("Native trainer uses allocated physical GPUs 2,3")
    from laya.common import DecisionModel
    from laya.train import save_checkpoint

    import train_bounded_laya
    from milai_lab.harness.artifact_io import read_json, write_json
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits

    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nquery\nbase\ncondition\n")
    tok = transformers.BertTokenizer(vocab_file=str(vocab))
    encoder = transformers.BertModel(transformers.BertConfig(
        vocab_size=8, hidden_size=16, intermediate_size=24, num_hidden_layers=1,
        num_attention_heads=2, max_position_embeddings=512))
    base = tmp_path / "base"
    save_checkpoint(DecisionModel(encoder, head_layers=0, n_act=1), tok,
                    {"head_layers": 0, "act_costs": {}}, str(base))
    rows, pairs = training_pool()
    rows, pairs = rows[:4], pairs[:2]
    for i, row in enumerate(rows):
        row['questions'] = {'applicability': {'type': 'choice', 'instructions': 'Choose',
            'criteria': {'satisfies': 'yes', 'does_not_satisfy': 'no'}}}
        row['metadata'].update(row=i, state_id=i, task='instruction_applicability',
                               component='a' if i < 2 else 'b')
    dev = copy.deepcopy(rows[0])
    dev['metadata'].update(split='dev', family='dev', query_unit='dev', event_id='dev', state_id=4)
    data = tmp_path / 'data'
    data.mkdir()
    for name, values in [('train', rows), ('dev', [dev]), ('pairs', pairs)]:
        (data / (name + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in values))
    write_json(data / 'mixture.json', {'a': .8, 'b': .2})
    budget = tmp_path / 'budget.json'
    write_json(budget, RunBudget(RunLimits(), budget).state)
    output = tmp_path / 'fit'
    monkeypatch.setattr(sys, 'argv', ['train_bounded_laya.py', str(data), str(base), str(output),
        '--budget', str(budget), '--task', 'mixed_retrieval', '--objective', 'set',
        '--mixture', str(data / 'mixture.json'), '--mixture-loss-scale', '1.25',
        '--conditional-pairs', str(data / 'pairs.jsonl'), '--epochs', '1',
        '--conditional-loss-weight', str(condition_weight),
        '--optimizer-updates', '1', '--eval-at-updates', '1', '--micro-batch-size', '2',
        '--max-len', '256', '--head-max-len', '96', '--shuffle-options',
        '--parallel-mode', parallel_mode, '--precision', precision])
    train_bounded_laya.main()
    run = read_json(output / 'run.json')
    assert run['status'] == 'COMPLETED' and run['optimizer_updates'] == 1
    assert run['train_sequence_rows'] == run['planned_sequence_rows'] == 4
    assert run['train_batch_forwards'] == 2
    assert run['conditional_loss_weight'] == condition_weight
    assert run['sampled_component_rows'] == {'a': 2, 'b': 2}
    sampling = read_json(output / 'sampling.json')
    assert sum(s['weight'] for s in sampling if s['component'] == 'a') / 4 == 1
    assert sum(s['weight'] for s in sampling if s['component'] == 'b') / 4 == .25
    assert (output / 'checkpoints/update-1').is_dir()
    if condition_weight:
        assert run['conditional_pair_draws'] == run['conditional_change_pairs'] == 2
        losses = [json.loads(line) for line in
                  (output / 'conditional-losses.jsonl').read_text().splitlines()]
        assert len(losses) == 2
        for row in losses:
            assert row['update'] == row['data_pass'] == 1 and row['window_change_pairs'] == 2
            assert row['family_weight'] == 1
            assert math.isclose(row['optimizer_contribution'], .25 * row['relative_loss'] / 2,
                                rel_tol=1e-6)
    else:
        assert not (output / 'conditional-losses.jsonl').exists()
