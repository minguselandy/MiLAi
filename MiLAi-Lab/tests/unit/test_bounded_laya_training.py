"""Derived prefixes and event multiplicity must not inflate a family's loss."""

import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from train_bounded_laya import compute_counts, decision_loss, event_weights


def test_loss_mass_is_equal_by_family_then_event_not_prefix_count():
    rows = [{"metadata": {"family": family, "row": event}}
            for family, event, copies in (("a", 0, 7), ("a", 1, 2), ("b", 2, 1))
            for _ in range(copies)]
    weights = event_weights(rows)
    mass = defaultdict(float)
    for row, weight in zip(rows, weights, strict=True):
        mass[row["metadata"]["family"], row["metadata"]["row"]] += weight
    assert sum(weights) == pytest.approx(len(rows))
    assert mass["a", 0] == pytest.approx(2.5)
    assert mass["a", 1] == pytest.approx(2.5)
    assert mass["b", 2] == pytest.approx(5)


def test_semantic_questions_on_one_source_row_do_not_inherit_prefix_multiplicity():
    rows = [{"metadata": {"family": "a", "row": 4, "training_event": event}}
            for event, copies in (("birth", 7), ("death", 2)) for _ in range(copies)]
    rows.append({"metadata": {"family": "b", "row": 9}})
    weights = event_weights(rows)
    assert sum(weights[:7]) == pytest.approx(2.5)
    assert sum(weights[7:9]) == pytest.approx(2.5)
    assert weights[9] == pytest.approx(5)


def test_set_loss_accepts_mass_on_either_positive_and_ignores_padding():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[2.0, -1.0, 0.5, 100.0]], requires_grad=True)
    target = torch.tensor([[0.5, 0.5, 0.0, 0.0]])
    mask = torch.tensor([[True, True, True, False]])
    actual = decision_loss(logits, target, mask, "set")
    expected = -torch.log(torch.softmax(logits[0, :3], 0)[:2].sum())
    assert actual.item() == pytest.approx(expected.item())
    actual.sum().backward()
    assert logits.grad[0, 3] == 0
    assert logits.grad[0, 2] > 0
    assert torch.isfinite(logits.grad).all()


def test_single_positive_set_equals_ce_and_multiple_positives_differ():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([[4.0, -2.0, 0.0]])
    mask = torch.ones_like(logits, dtype=torch.bool)
    single = torch.tensor([[1.0, 0.0, 0.0]])
    assert decision_loss(logits, single, mask, "set").item() == pytest.approx(
        decision_loss(logits, single, mask, "soft-ce").item(), abs=1e-6)
    multiple = torch.tensor([[0.5, 0.5, 0.0]])
    assert decision_loss(logits, multiple, mask, "set").item() < 0.02
    assert decision_loss(logits, multiple, mask, "soft-ce").item() > 3


def test_train_evaluation_does_not_overwrite_optimization_or_partial_attempts():
    run = {"train_sequence_rows": 208, "train_input_tokens": 579397,
           "train_batch_forwards": 53, "train_device_forwards": 106,
           "train_batch_attempts": 54, "train_offered_rows": 212,
           "train_offered_tokens": 590488}
    counts = compute_counts(run, {
        "train": Counter(forwards=258, sequence_rows=258, input_tokens=715857),
        "dev": Counter(forwards=90, sequence_rows=90, input_tokens=233571)})
    assert all(counts[k] == value for k, value in run.items())
    assert counts["train_eval_forwards"] == counts["train_eval_sequence_rows"] == 258
    assert counts["train_eval_input_tokens"] == 715857
    assert counts["dev_input_tokens"] == 233571
    assert counts["train_input_tokens"] + counts["train_eval_input_tokens"] == 1295254
