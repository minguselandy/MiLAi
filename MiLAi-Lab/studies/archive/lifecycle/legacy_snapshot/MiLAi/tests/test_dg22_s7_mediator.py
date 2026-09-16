from __future__ import annotations

from pathlib import Path

from evals.dg22.mediator import (
    ARMS,
    build_mediator_product,
    score_mediator_product,
    seal_mediator_product,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_s7_product_seals_before_labels_with_exact_denominator(tmp_path: Path) -> None:
    product = build_mediator_product(_ROOT)

    assert product["labels_loaded"] is False
    assert product["formal_holdout_consumed"] is False
    assert product["candidate_default"] is False
    assert len(product["records"]) == 100
    assert set(product["arms"]) == set(ARMS)
    path = tmp_path / "sealed.json"
    seal_mediator_product(product, path)
    assert path.exists()


def test_s7_mediator_hard_gates(tmp_path: Path) -> None:
    path = tmp_path / "sealed.json"
    seal_mediator_product(build_mediator_product(_ROOT), path)
    score = score_mediator_product(path)

    assert score["status"] == "PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION"
    assert score["hard_gate"]["passed"]
    assert score["metrics"]["required_evidence_coverage_2048"] >= 12
    assert score["metrics"]["required_evidence_coverage_512"] >= 10
    assert score["metrics"]["accepted_binding_precision"] == 1.0
    assert score["metrics"]["wrong_complete"] == 0
