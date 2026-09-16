from __future__ import annotations

from evals.benchmark import dg11_measurement as measurement


def test_scorer_v2_normalizes_number_currency_unit_and_date() -> None:
    assert measurement.score_v2("twenty five dollars", ["$25"])["exact_match"] == 1
    assert measurement.score_v2("2 hours", ["two hrs"])["exact_match"] == 1
    assert measurement.score_v2("August 5, 2023", ["8/5/2023"])["exact_match"] == 1


def test_scorer_v2_normalizes_explicit_abstention() -> None:
    assert measurement.score_v2("I don't know", ["UNKNOWN"])["exact_match"] == 1


def test_recompute_keeps_three_arm_denominator_and_derives_compile_metrics() -> None:
    records = []
    for index in range(50):
        case_id = f"longmemeval:case-{index}"
        for arm, answer, sessions, context in (
            ("NO_MEMORY", "UNKNOWN", [], "MEMORY_STATUS=NO_MEMORY"),
            ("NAIVE_RAG", "UNKNOWN", [f"other-{index}"], "irrelevant"),
            ("MILAI_T3A", "twenty five dollars", [f"answer-{index}"], "user: paid $25"),
        ):
            score = measurement.score_normalized_em_f1_v1(answer, ["$25"])
            records.append(
                {
                    "case_id": case_id,
                    "category": "knowledge-update",
                    "arm": arm,
                    "answer": answer,
                    "gold_answers": ["$25"],
                    "score": score,
                    "retrieval_recall_at_k": 1.0 if arm == "MILAI_T3A" else 0.0,
                    "retrieval_relevant_coverage_at_k": 1.0 if arm == "MILAI_T3A" else 0.0,
                    "retrieved_session_ids": sessions,
                    "memory_context": context,
                    "memory_tokens": 10,
                    "prompt_tokens": 20,
                    "model_calls": 1,
                    "hidden_model_calls": 0,
                }
            )
    result = measurement.recompute(
        records,
        relevant_sessions={f"case-{index}": [f"answer-{index}"] for index in range(50)},
    )

    assert result["case_count"] == 50
    assert result["record_count"] == 150
    assert result["arms"]["MILAI_T3A"]["answer_span_survival_on_hit"] == 1.0
    assert result["arms"]["MILAI_T3A"]["hit_and_answer_span_missing_count"] == 0
    assert result["arms"]["MILAI_T3A"]["answer_session_rank_mean_on_hit"] == 1.0
    assert result["arms"]["MILAI_T3A"]["scorer_v2"]["exact_match_mean"] == 1.0
