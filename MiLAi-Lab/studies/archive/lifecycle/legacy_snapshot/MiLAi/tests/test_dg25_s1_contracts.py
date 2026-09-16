from __future__ import annotations

from evals.dg25.synthetic_matrix import negative_contract_report, run_synthetic_matrix


def test_dg25_s1_synthetic_matrix_covers_all_contract_families() -> None:
    matrix = run_synthetic_matrix()
    records = {item["case_id"]: item for item in matrix["records"]}

    assert matrix["hard_gate"]["passed"] is True
    assert matrix["counts"]["total"] >= 35
    assert set(matrix["counts"]["by_category"]) == {
        "ANSWER",
        "IDENTITY",
        "PLAN",
        "PROOF",
        "TEMPORAL",
    }
    for case_id in (
        "plan-stale-state-epoch-snapshot",
        "plan-aggregate-budget-overflow",
        "plan-proof-action-required",
        "plan-optional-cannot-shrink-baseline-cap",
        "time-dst-timezone",
        "time-ambiguous-relational-anchor",
        "identity-twins-multiple-entities-one-span",
        "identity-repeated-event-across-turns",
        "proof-max-items-hit",
        "proof-unprojected-with-raw-fallback",
        "proof-dead-letter-gap",
        "proof-access-snapshot-invalid",
        "reader-value-mismatch",
        "reader-unit-mismatch",
        "reader-invalid-json",
    ):
        assert records[case_id]["passed"] is True


def test_dg25_s1_negative_report_has_no_wrong_complete_or_stale_acceptance() -> None:
    report = negative_contract_report(run_synthetic_matrix())

    assert report["hard_gate"]["passed"] is True
    assert report["negative_case_count"] >= 15
    assert report["wrong_complete"] == 0
    assert report["stale_acceptance"] == 0
    assert report["budget_overflow_acceptance"] == 0
    assert report["reader_mismatch_acceptance"] == 0
