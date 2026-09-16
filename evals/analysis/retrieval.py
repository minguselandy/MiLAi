from __future__ import annotations

from statistics import mean
from typing import Any


def merge_pool_records(
    cases: list[dict[str, Any]],
    base_records: dict[str, dict[str, Any]],
    repair_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_ids = [str(case["source_id"]) for case in cases]
    if set(base_records).difference(expected_ids) or set(repair_records).difference(
        expected_ids
    ):
        raise RuntimeError("resume pool contains an unexpected source ID")
    merged = []
    for source_id in expected_ids:
        record = repair_records.get(source_id, base_records.get(source_id))
        if record is None:
            raise RuntimeError("resume pool is missing a source ID")
        merged.append(record)
    return merged


def _average(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    return round(mean(float(record[field]) for record in records), 6)


def retrieval_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    multi = [record for record in records if record["category"] == "multi-session"]
    single = [record for record in records if record["category"] != "multi-session"]
    current_multi_hits = [record for record in multi if record["current_hit"]]
    old_multi_hits = [record for record in multi if record["old_hit"]]
    rerankers = [record["reranker"] for record in records if record["reranker"]]
    expected_rerankers = [record for record in records if record["reranker_expected"]]
    missing_rerankers = [record for record in expected_rerankers if not record["reranker"]]
    unexpected_rerankers = [
        record
        for record in records
        if not record["reranker_expected"] and record["reranker"]
    ]
    frozen_identity = {
        "model_id": "cross-encoder/ms-marco-MiniLM-L6-v2",
        "revision": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
        "model_sha256": "3573b6b9593cb2f75987a31815d409ca3dd8808629118fd20451bb1a5d90cec7",
    }
    identity_mismatches = [
        value
        for value in rerankers
        if any(value.get(field) != expected for field, expected in frozen_identity.items())
    ]
    return {
        "case_count": len(records),
        "multi_session_count": len(multi),
        "single_session_count": len(single),
        "multi_current_hit_at_3": _average(multi, "current_hit"),
        "multi_old_hit_at_3": _average(multi, "old_hit"),
        "multi_current_relevant_coverage_at_3": _average(multi, "current_coverage"),
        "multi_old_relevant_coverage_at_3": _average(multi, "old_coverage"),
        "multi_current_answer_span_survival_on_hit": _average(
            current_multi_hits, "current_answer_span"
        ),
        "multi_old_answer_span_survival_on_hit": _average(
            old_multi_hits, "old_answer_span"
        ),
        "single_current_relevant_coverage_at_3": _average(single, "current_coverage"),
        "single_old_relevant_coverage_at_3": _average(single, "old_coverage"),
        "memory_tokens_mean": round(mean(record["memory_tokens"] for record in records), 3),
        "memory_tokens_max": max(record["memory_tokens"] for record in records),
        "reranker_expected_case_count": len(expected_rerankers),
        "reranker_inference_batches": len(rerankers),
        "reranker_missing_case_count": len(missing_rerankers),
        "reranker_unexpected_case_count": len(unexpected_rerankers),
        "reranker_identity_mismatch_case_count": len(identity_mismatches),
        "reranker_scored_pairs": sum(int(value["pairs"]) for value in rerankers),
        "reranker_latency_ms_mean": round(
            mean(float(value["duration_ms"]) for value in rerankers), 3
        ),
        "reranker_latency_ms_max": round(
            max(float(value["duration_ms"]) for value in rerankers), 3
        ),
        "reranker_model_id": rerankers[0]["model_id"] if rerankers else None,
        "reranker_revision": rerankers[0]["revision"] if rerankers else None,
        "reranker_model_sha256": rerankers[0]["model_sha256"] if rerankers else None,
        "degraded_case_count": sum(bool(record["degraded_components"]) for record in records),
    }
