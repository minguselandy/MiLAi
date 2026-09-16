from __future__ import annotations

from pathlib import Path

from evals.dg22.temporal_correctness import build_temporal_product

_ROOT = Path(__file__).resolve().parents[3]


def test_dg22_local_anchor_and_relevant_unresolved_contract() -> None:
    product = build_temporal_product(_ROOT)

    assert all(row["passed"] for row in product["anchor_matrix"])
    assert all(row["passed"] for row in product["synthetic_count_matrix"])
    assert all(row["source_time_substitution"] is False for row in product["anchor_matrix"])
