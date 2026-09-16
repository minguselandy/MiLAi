from __future__ import annotations

from evals.dg16.external_lme10 import BUDGETS, METHODS, load_cases, summarize_scored


def test_external_lme10_selection_is_label_free_and_stable() -> None:
    cases, selection = load_cases()
    assert len(cases) == 10
    assert tuple(case.case_id for case in cases) == tuple(selection["source_ids"])
    assert selection["formal_holdout_consumed"] is False
    assert selection["formal_source_id_overlap"] == []
    assert sum(len(case.sessions) for case in cases) == 475


def test_external_lme10_summary_requires_all_cells() -> None:
    records = []
    for method in METHODS:
        for budget in BUDGETS:
            for ordinal in range(10):
                records.append(
                    {
                        "case_id": str(ordinal),
                        "method_id": method,
                        "token_budget": budget,
                        "context_tokens": budget,
                        "query_latency_ms": 10.0,
                        "answer_score": {"exact_match": 1, "normalized_f1": 1.0},
                        "retrieval_score": {
                            "hit_at_k": 1,
                            "relevant_coverage_at_k": 1.0,
                        },
                        "provider": {
                            "tokenize_latency_ms": 2.0,
                            "provider_latency_ms": 20.0,
                            "prompt_tokens": budget + 100,
                        },
                    }
                )
    summary = summarize_scored(records)
    assert summary["GRAPHITI-OSS"]["512"]["normalized_f1"] == 1.0
    assert summary["OPENVIKING-FIND"]["2048"]["answer_path_latency_ms"]["mean"] == 32.0
