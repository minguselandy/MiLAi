from __future__ import annotations

from evals.ml_closure.longmemeval_contexts import _formation_delivery
from evals.ml_closure.longmemeval_contract import INPUT_PATH
from evals.ml_repair.mlr01_delivery import compare_concurrency, select_case_ids
from evals.ml_repair.mlr01_v03 import v03_selections
from evals.paper.datasets.longmemeval import load_inputs


def test_r2_selection_is_deterministic_stratified_and_label_free() -> None:
    _partition, cases = load_inputs(INPUT_PATH)

    selected_32, details_32 = select_case_ids(cases, 32)
    repeated_32, repeated_details = select_case_ids(tuple(reversed(cases)), 32)
    selected_128, details_128 = select_case_ids(cases, 128)

    assert selected_32 == repeated_32
    assert details_32 == repeated_details
    assert len(selected_32) == len(set(selected_32)) == 32
    assert len(selected_128) == len(set(selected_128)) == 128
    assert set(selected_32).issubset(selected_128)
    assert details_32["label_fields_accessed"] is False
    assert details_32["identity_field"] == "source_id_as_question_id"
    assert [details_32["strata"][str(index)]["selected"] for index in range(4)] == [
        8,
        8,
        8,
        8,
    ]
    assert [details_128["strata"][str(index)]["selected"] for index in range(4)] == [
        32,
        32,
        32,
        32,
    ]


def test_v03_selections_exclude_v02_diagnostics_and_each_other() -> None:
    _partition, cases = load_inputs(INPUT_PATH)
    v02_ids, _details = select_case_ids(cases, 128)

    r2_e_ids, r2_e, r2_b_ids, r2_b = v03_selections(cases)

    assert len(r2_e_ids) == len(set(r2_e_ids)) == 8
    assert len(r2_b_ids) == len(set(r2_b_ids)) == 128
    assert set(v02_ids).isdisjoint(r2_e_ids)
    assert set(v02_ids).isdisjoint(r2_b_ids)
    assert set(r2_e_ids).isdisjoint(r2_b_ids)
    assert r2_e["selected_case_order_sha256"] == (
        "f109411b2719f9ff6a175c05f173f7de7573a3d6a4a70c9159dce229b9ef5f17"
    )
    assert r2_b["selected_case_order_sha256"] == (
        "084be2a5155189ee729b6067ec203233cd1cd2c8150da89f4cbdec15f3d2b92a"
    )


def test_formation_delivery_accounting_uses_fixed_machine_facts() -> None:
    delivery = _formation_delivery(
        {
            "partition_source_count": 10,
            "selected_source_count": 2,
            "hydrated_source_count": 2,
            "semantic_artifact_count": 3,
            "applied": True,
            "fallback_taken": False,
            "source_snapshot_digest": "a" * 64,
            "source_watermark_digest": "b" * 64,
            "access_snapshot_digest": "c" * 64,
            "build_epoch": 1,
        },
        mode="CANARY",
    )

    assert delivery == {
        "formation_eligible": True,
        "formation_attempted": True,
        "formation_applied": True,
        "formed_artifact_count": 3,
        "hydrated_source_count": 2,
        "raw_fallback_taken": False,
        "fallback_reason": None,
        "projection_freshness": {
            "status": "CURRENT",
            "build_epoch": 1,
            "source_snapshot_digest_present": True,
            "source_watermark_digest_present": True,
            "access_snapshot_digest_present": True,
        },
    }


def test_r2_concurrency_selection_rejects_more_than_twenty_percent_p95_regression() -> (
    None
):
    four = {
        "status": "PASS",
        "latency_ms": {"p95": 100.0},
        "unexpected_persistent_worker_exits": 0,
        "projection_metrics_failures": 0,
    }
    accepted = compare_concurrency(
        four,
        {
            "status": "PASS",
            "latency_ms": {"p95": 119.0},
            "unexpected_persistent_worker_exits": 0,
            "projection_metrics_failures": 0,
        },
    )
    rejected = compare_concurrency(
        four,
        {
            "status": "PASS",
            "latency_ms": {"p95": 121.0},
            "unexpected_persistent_worker_exits": 0,
            "projection_metrics_failures": 0,
        },
    )

    assert accepted["selected_stateful_processes"] == 8
    assert accepted["eight_process_lane_accepted"] is True
    assert rejected["selected_stateful_processes"] == 4
    assert rejected["eight_process_lane_accepted"] is False
