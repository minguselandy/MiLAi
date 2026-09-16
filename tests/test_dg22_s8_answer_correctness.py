from __future__ import annotations

from pathlib import Path

from evals.dg22.answer_correctness import (
    build_answer_context_product,
    seal_answer_context_product,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_s8_context_product_has_frozen_40_cell_denominator(tmp_path: Path) -> None:
    product = build_answer_context_product(_ROOT, run_id="synthetic-s8")

    assert product["status"] == "CONTEXTS_FROZEN_UNREAD"
    assert product["labels_loaded"] is False
    assert product["retrieval_frozen"] is True
    assert len(product["records"]) == 40
    assert all("answer" not in row for row in product["records"])
    seal_answer_context_product(product, tmp_path / "contexts.json")
