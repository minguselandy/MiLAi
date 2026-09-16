from __future__ import annotations

from typing import Any

import pytest

from evals.dg16.lme10 import (
    BUDGETS,
    METHODS,
    compare_summaries,
    load_public_dev_cases,
    load_public_dev_labels,
    score_records,
    summarize_lifecycle,
    summarize_records,
)


def _records() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    case_ids = tuple(f"case-{index}" for index in range(10))
    labels = {
        case_id: {"answers": ["blue"], "answer_session_ids": [f"s-{case_id}"]}
        for case_id in case_ids
    }
    records: list[dict[str, Any]] = []
    for case_id in case_ids:
        for method_id in METHODS:
            for budget in BUDGETS:
                records.append(
                    {
                        "case_id": case_id,
                        "method_id": method_id,
                        "token_budget": budget,
                        "answer": "blue" if method_id == METHODS[0] else "red",
                        "retrieval_trace": [{"rank": 1, "session_id": f"s-{case_id}"}],
                        "query_latency_ms": 20 if method_id == METHODS[0] else 10,
                        "context_tokens": budget / 2,
                        "usage": {
                            "retrieval_logical_calls": int(method_id == METHODS[0])
                        },
                        "provider": {
                            "provider_latency_ms": 100,
                            "tokenize_latency_ms": 5,
                            "prompt_tokens": budget,
                            "completion_tokens": 4,
                            "provider_calls": 1,
                        },
                    }
                )
    return records, labels


def test_public_dev_ten_case_selection_is_label_free_and_unique() -> None:
    cases, selection = load_public_dev_cases()
    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == 10
    assert selection["formal_holdout_consumed"] is False
    assert selection["formal_source_id_overlap"] == []
    assert all(case.history_events for case in cases)


def test_public_dev_labels_share_the_frozen_input_session_identity() -> None:
    cases, _selection = load_public_dev_cases()
    labels, _identity = load_public_dev_labels(tuple(case.case_id for case in cases))
    for case in cases:
        input_sessions = {session.session_id for session in case.sessions}
        assert set(labels[case.case_id]["answer_session_ids"]).issubset(input_sessions)


def test_scoring_and_online_summary_keep_the_paired_denominator() -> None:
    records, labels = _records()
    scored = score_records(records, labels)
    summary = summarize_records(scored)
    assert len(scored) == 40
    assert summary["DG16-MILAI-MCP"]["512"]["normalized_f1"] == 1
    assert summary["LME-BM25-T"]["2048"]["normalized_f1"] == 0
    assert summary["DG16-MILAI-MCP"]["512"]["answer_path_latency_ms"]["mean"] == 125


def test_lifecycle_summary_and_comparison_are_explicit() -> None:
    records, labels = _records()
    online = summarize_records(score_records(records, labels))
    lifecycle_rows = []
    for case_index in range(10):
        for method_id in METHODS:
            milai = method_id == "DG16-MILAI-MCP"
            lifecycle_rows.append(
                {
                    "case_id": f"case-{case_index}",
                    "method_id": method_id,
                    "event_count": 12,
                    "runtime_start_ms": 10 if milai else 0,
                    "ingest_ms": 20 if milai else 1,
                    "finalize_ms": 30 if milai else 1,
                    "query_ms": 40 if milai else 20,
                    "cleanup_ms": 50 if milai else 1,
                    "runtime_close_ms": 10 if milai else 0,
                    "total_lifecycle_ms": 160 if milai else 25,
                    "logical_mcp_calls": 14 if milai else 0,
                    "physical_mcp_batches": 4 if milai else 0,
                }
            )
    lifecycle = summarize_lifecycle(lifecycle_rows)
    comparison = compare_summaries(online, lifecycle)
    assert lifecycle["DG16-MILAI-MCP"]["sequential_cases_per_hour"] == 22500
    assert comparison["by_budget"]["512"]["normalized_f1_delta"] == 1
    assert comparison["full_lifecycle_ratio_milai_over_bm25"] == 6.4


def test_scoring_rejects_an_incomplete_denominator() -> None:
    records, labels = _records()
    with pytest.raises(Exception, match="denominator"):
        score_records(records[:-1], labels)
