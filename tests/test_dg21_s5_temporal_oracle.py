from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evals.dg21.temporal_channel_oracle import (
    SELECTED_OPENED_CASES,
    build_temporal_product_oracle,
    score_sealed_temporal_oracle,
    seal_temporal_product_oracle,
)

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json"
RECEIPT = ROOT / ("var/dg21/s5/dg21-s5-temporal-oracle-20260828-005/receipt.json")


def test_s5_temporal_oracle_seals_product_before_scoring_and_passes(
    tmp_path: Path,
) -> None:
    product = build_temporal_product_oracle(ROOT, run_id="test-dg21-s5")

    assert product["status"] == "PRODUCT_ORACLE_COMPLETE_UNSCORED"
    assert product["labels_loaded"] is False
    assert product["product_hard_gate"]["passed"] is True
    assert all(product["product_hard_gate"]["checks"].values())
    assert product["synthetic_matrix"]["event_point"]["passed"] is True
    assert product["synthetic_matrix"]["count_range"]["passed"] is True
    assert product["synthetic_matrix"]["undated_negative"]["passed"] is True
    assert (
        product["persistent_projection_feasibility"]["migration_or_table_created"]
        is False
    )
    assert product["persistent_projection_feasibility"]["wp06_status"] == (
        "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    )

    sealed_path = tmp_path / "sealed-product-oracle.json"
    seal = seal_temporal_product_oracle(product, sealed_path)
    assert seal["status"] == "SEALED_BEFORE_SCORING"

    score = score_sealed_temporal_oracle(sealed_path, labels_path=LABELS)
    assert score["status"] == "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT"
    assert score["temporal_lane"] == "PASS_QUERY_TIME_TEMPORAL_COMPLETENESS"
    assert score["wp06_status"] == "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    assert score["hard_gate"]["passed"] is True
    assert all(score["hard_gate"]["checks"].values())
    assert score["label_boundary"] == {
        "product_path_label_access_count": 0,
        "scorer_label_access_count": 1,
        "scoring_started_after_product_seal": True,
    }
    assert {case["case_id"] for case in score["cases"]} == set(SELECTED_OPENED_CASES)


def test_s5_opened_count_cases_remain_partial_instead_of_wrong_complete() -> None:
    product = build_temporal_product_oracle(ROOT, run_id="test-dg21-s5-partial")
    by_case = {case["case_id"]: case for case in product["cases"]}

    for case_id in ("2e6d26dc", "88432d0a"):
        arm = by_case[case_id]["arms"]["C_REPOSITORY_EVENT_RANGE_API"]
        assert arm["derived_status"] == "PARTIAL"
        assert arm["derived_reason"] == "EVENT_TIME_UNRESOLVED"
        assert arm["partition_watermark_proof_available"] is True
        assert arm["scan_items"] > arm["hydrated_items"]
        assert arm["hydrated_items"] <= 8

    point = by_case["gpt4_8279ba03"]["arms"]["C_REPOSITORY_EVENT_RANGE_API"]
    assert point["derived_status"] == "OK"
    assert point["operator_ready_delta"] == 1
    assert point["time_basis_correctness"] == "PASS"
    assert point["time_axis_substitution_count"] == 0


def test_s5_sealed_receipt_binds_every_artifact_and_source() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert receipt["status"] == "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT"
    assert receipt["temporal_lane"] == "PASS_QUERY_TIME_TEMPORAL_COMPLETENESS"
    assert receipt["wp06_status"] == "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    assert receipt["hard_gate"]["passed"] is True
    assert receipt["metrics"]["wrong_complete"] == 0
    assert receipt["metrics"]["schema_mutations"] == 0
    for key in (
        "plan",
        "entry_s4_receipt",
        "sealed_product_oracle",
        "score",
        "schema_entry_audit",
    ):
        identity = receipt[key]
        path = ROOT / identity["path"]
        assert path.stat().st_size == identity["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
    for relative, identity in receipt["source_identity_manifest"].items():
        path = ROOT / relative
        assert path.stat().st_size == identity["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
