"""New reservations cannot recycle exposed families or depend on input row order."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_selection_partition import reserve


def test_new_reservation_excludes_exposed_family_and_preserves_all_variants():
    groups = [{"family": f"f{i}", "max_steps": 4, "rows": [i * 2, i * 2 + 1],
               "question_ids": [f"4hop__{i}", f"2hop__{i}"]} for i in range(6)]
    first = reserve(groups, {"f0", "f1"}, {4: 3}, 42)
    assert first == reserve(list(reversed(groups)), {"f0", "f1"}, {4: 3}, 42)
    assert len(first) == 3 and {g["family"] for g in first}.isdisjoint({"f0", "f1"})
    assert all(g["question_id"].startswith("4hop") for g in first)
    assert all(len(g["protected_source_rows"]) == 2 for g in first)
    with pytest.raises(ValueError, match="Only 4 unused"):
        reserve(groups, {"f0", "f1"}, {4: 5}, 42)
