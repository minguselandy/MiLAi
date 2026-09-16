from __future__ import annotations

import pytest

from evals.analysis import merge_pool_records, retrieval_summary


def _record(source_id: str, marker: str) -> dict[str, object]:
    return {"source_id": source_id, "marker": marker}


def test_merge_pool_records_repairs_only_requested_cases_in_input_order() -> None:
    cases = [{"source_id": "a"}, {"source_id": "b"}]

    merged = merge_pool_records(
        cases,
        {"a": _record("a", "base"), "b": _record("b", "empty")},
        {"b": _record("b", "repaired")},
    )

    assert [record["source_id"] for record in merged] == ["a", "b"]
    assert [record["marker"] for record in merged] == ["base", "repaired"]


def test_merge_pool_records_rejects_unexpected_or_missing_ids() -> None:
    with pytest.raises(RuntimeError, match="unexpected"):
        merge_pool_records(
            [{"source_id": "a"}],
            {"a": _record("a", "base")},
            {"x": _record("x", "repair")},
        )
    with pytest.raises(RuntimeError, match="missing"):
        merge_pool_records([{"source_id": "a"}], {}, {})


def test_production_reranker_denominator_excludes_abstained_empty_retrievals() -> None:
    identity = {
        "model_id": "cross-encoder/ms-marco-MiniLM-L6-v2",
        "revision": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
        "model_sha256": "3573b6b9593cb2f75987a31815d409ca3dd8808629118fd20451bb1a5d90cec7",
        "pairs": 10,
        "duration_ms": 2.0,
    }
    base = {
        "category": "multi-session",
        "current_hit": 0,
        "old_hit": 0,
        "current_coverage": 0.0,
        "old_coverage": 0.0,
        "current_answer_span": 0,
        "old_answer_span": 0,
        "memory_tokens": 10,
        "degraded_components": [],
        "reranker_result_count": 0,
    }
    summary = retrieval_summary(
        [
            {**base, "source_id": "retrieved", "reranker_expected": True, "reranker": identity},
            {**base, "source_id": "abstained", "reranker_expected": False, "reranker": None},
        ]
    )

    assert summary["reranker_expected_case_count"] == 1
    assert summary["reranker_inference_batches"] == 1
    assert summary["reranker_missing_case_count"] == 0
    assert summary["reranker_unexpected_case_count"] == 0
    assert summary["reranker_identity_mismatch_case_count"] == 0
