"""Derived prefixes and event multiplicity must not inflate a family's loss."""

import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from train_bounded_laya import event_weights


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
