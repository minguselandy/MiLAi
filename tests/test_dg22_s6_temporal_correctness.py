from __future__ import annotations

import json
from pathlib import Path

from evals.dg22.temporal_correctness import (
    build_temporal_product,
    score_temporal_product,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_s6_product_is_label_free_and_synthetic_contract_passes(tmp_path: Path) -> None:
    product = build_temporal_product(_ROOT)

    assert product["labels_loaded"] is False
    assert product["label_path_or_digest_present"] is False
    assert all(product["product_checks"].values())
    assert all(row["passed"] for row in product["anchor_matrix"])
    assert all(row["passed"] for row in product["synthetic_count_matrix"])


def test_s6_scores_only_after_product_file_is_sealed(tmp_path: Path) -> None:
    path = tmp_path / "sealed-product.json"
    path.write_text(
        json.dumps(build_temporal_product(_ROOT), sort_keys=True), encoding="utf-8"
    )
    score = score_temporal_product(path)

    assert score["hard_gate"]["passed"]
    assert score["metrics"]["time_axis_substitution"] == 0
    assert score["metrics"]["opened_count_wrong_complete"] == 0
    assert score["scoring_label_identity"]["loaded_after_product_seal"] is True
