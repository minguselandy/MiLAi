from __future__ import annotations

from pathlib import Path

from scripts import run_dg10_bfcl_dev_aggregate as aggregate

COMPOSITE = Path(
    "/cra/memory/mx_memory/evidence/dg10-bfcl-multiturn-scoring/"
    "dg10-bfcl-multiturn-scoring-remediation-v3-2026-08-21-140d3b4274c2/"
    "composite-scoring-ledger.jsonl"
)


def test_bfcl_dev_aggregate_is_exact_complete_and_test_closed() -> None:
    report = aggregate.build_report(COMPOSITE)

    assert report["status"] == (
        "BFCL_ADAPTED_LOCAL_NON_LIVE_216_DEV_CHARACTERIZATION_COMPLETE"
    )
    assert report["quality_outcome"] == "MODEL_QUALITY_BELOW_TARGET"
    assert report["coverage"]["dev_case_count"] == 216
    assert report["coverage"]["dev_fraction"] <= 0.10
    assert report["aggregates"]["official_valid_count"] == 119
    assert report["aggregates"]["adapted_official_checker_accuracy"] == 0.550926
    assert report["aggregates"]["single_turn_supported"]["valid_count"] == 106
    assert report["aggregates"]["multi_turn"]["valid_count"] == 1
    assert report["aggregates"]["java_javascript"]["valid_count"] == 12
    assert report["request_accounting_latest_complete_evidence"][
        "local_vllm_requests"
    ] == 1785
    assert report["test_access_authorized"] is False
    assert report["bfcl_test_labels_or_outputs_opened"] is False
