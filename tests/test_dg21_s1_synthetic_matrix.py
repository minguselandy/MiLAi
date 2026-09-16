from __future__ import annotations

from evals.dg21.synthetic_matrix import run_synthetic_matrix


def test_dg21_s1_synthetic_selector_matrix_passes_all_gates() -> None:
    result = run_synthetic_matrix()

    assert result["status"] == "PASS_POLICY_SYNTHETIC_MATRIX"
    assert result["hard_gate"]["passed"]
    assert result["cell_count"] == 36
    assert all(record["passed"] for record in result["records"])
    assert all(
        coverage["positive"] >= 1 and coverage["negative"] >= 1
        for coverage in result["coverage"]["profiles"].values()
    )


def test_dg21_s1_matrix_is_content_free_and_zero_authority() -> None:
    result = run_synthetic_matrix()

    encoded = repr(result["records"]).casefold()
    assert "question" not in encoded
    assert "answer" not in encoded
    assert "gold" not in encoded
    assert result["safety"] == {
        "provider_calls": 0,
        "reader_calls": 0,
        "automatic_retries": 0,
        "canonical_mutations": 0,
        "formal_holdout_consumed": False,
    }
