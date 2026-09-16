from __future__ import annotations

from pathlib import Path

from evals.dg22.accuracy_oracle import (
    build_label_free_product,
    score_sealed_product,
    seal_product,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_dg22_s1_separates_product_inventory_from_gold(tmp_path: Path) -> None:
    product = build_label_free_product(_ROOT, run_id="test-s1")
    sealed = tmp_path / "sealed.json"
    seal_product(product, sealed)
    score = score_sealed_product(sealed)

    assert product["label_access_count"] == 0
    assert product["formal_holdout_consumed"] is False
    assert score["status"] == "PASS_SAFE_ORACLE"
    assert score["metrics"] == {
        "safe_oracle_reachable_requirement_count": 15,
        "safe_oracle_requirement_denominator": 15,
        "safe_oracle_normalized_recall_ceiling": 1.0,
        "safe_oracle_reachable_atom_count": 23,
        "required_evidence_atom_denominator": 23,
    }


def test_dg22_s1_assigns_exactly_one_first_loss_per_requirement(tmp_path: Path) -> None:
    sealed = tmp_path / "sealed.json"
    seal_product(build_label_free_product(_ROOT, run_id="test-s1-loss"), sealed)
    score = score_sealed_product(sealed)

    identities = {(row["case_id"], row["requirement_id"]) for row in score["records"]}
    assert len(score["records"]) == len(identities) == 15
    assert all(row["current_first_loss"] for row in score["records"])
    assert score["hard_gate"]["checks"]["one_first_loss_per_requirement"]
