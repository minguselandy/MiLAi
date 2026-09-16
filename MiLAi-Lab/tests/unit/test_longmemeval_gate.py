from __future__ import annotations

import pytest

from milai_lab.longmemeval_gate import (
    AnswerBearingSpanLabel,
    ArmMetrics,
    ReaderVisibleUnit,
    admission_checks,
    evidence_budget,
    exact_answer_evidence_metrics,
    paired_bootstrap_interval,
    ranked_session_metrics,
    reader_visible_gold_session_metrics,
    strict_json_answer,
    strict_json_judgment,
)


def _arm(**changes: float | int) -> ArmMetrics:
    values: dict[str, float | int] = {
        "case_count": 500,
        "system_context_success_rate": 1.0,
        "session_recall_at_5": 0.2,
        "session_ndcg_at_5": 0.1,
        "all_required_evidence_group_coverage": 0.10,
        "reader_visible_gold_session_coverage": 0.2,
        "qwen_judge_accuracy": 0.20,
        "strict_wrong_complete": 0,
        "p50_latency_ms": 50.0,
        "p95_latency_ms": 100.0,
        "leak_count": 0,
    }
    values.update(changes)
    return ArmMetrics(**values)  # type: ignore[arg-type]


def test_budget_is_derived_then_bounded_by_public_product_cap() -> None:
    assert (
        evidence_budget(
            usable_model_context=65_536,
            fixed_prompt_tokens=712,
            answer_reserve_tokens=1_024,
            safety_margin_tokens=256,
            product_cap=8_192,
        )
        == 8_192
    )


def test_retrieval_and_session_group_metrics_preserve_required_groups() -> None:
    ranked = ranked_session_metrics(["s2", "s2", "s3", "s1"], ["s1", "s2"])
    assert ranked["session_recall_at_5"] == 1.0
    assert ranked["session_hit_at_5"] == 1
    partial = reader_visible_gold_session_metrics(["s2"], ["s1", "s2"])
    assert partial == {
        "reader_visible_gold_session_coverage": 0.5,
        "all_required_evidence_group_coverage": 0,
    }


def test_session_hit_does_not_masquerade_as_answer_turn_or_span_coverage() -> None:
    source = "The bicycle lock is cobalt blue."
    metrics = exact_answer_evidence_metrics(
        discovered_source_turn_refs=["memory://session/s1/turn/0"],
        visible_units=[
            ReaderVisibleUnit(
                source_turn_refs=("memory://session/s1/turn/0",),
                text="[E1]\nThe session contains unrelated setup.",
            )
        ],
        source_text_by_turn_ref={"memory://session/s1/turn/1": source},
        labels=[
            AnswerBearingSpanLabel(
                source_turn_ref="memory://session/s1/turn/1",
                start=4,
                end=len(source),
                text="bicycle lock is cobalt blue.",
            )
        ],
    )

    assert reader_visible_gold_session_metrics(["s1"], ["s1"])[
        "reader_visible_gold_session_coverage"
    ] == 1.0
    assert metrics == {
        "answer_bearing_turn_recall": 0.0,
        "reader_visible_answer_turn_coverage": 0.0,
        "reader_visible_answer_span_coverage": 0.0,
    }


def test_exact_answer_turn_and_source_span_are_reader_visible() -> None:
    source_ref = "memory://session/s1/turn/1"
    source = "The bicycle lock is cobalt blue."
    answer = "cobalt blue"
    start = source.index(answer)
    metrics = exact_answer_evidence_metrics(
        discovered_source_turn_refs=[source_ref],
        visible_units=[
            ReaderVisibleUnit(
                source_turn_refs=(source_ref,),
                text=f"[E1 EVIDENCE WINDOW]\n{source}",
            )
        ],
        source_text_by_turn_ref={source_ref: source},
        labels=[
            AnswerBearingSpanLabel(
                source_turn_ref=source_ref,
                start=start,
                end=start + len(answer),
                text=answer,
            )
        ],
    )

    assert metrics == {
        "answer_bearing_turn_recall": 1.0,
        "reader_visible_answer_turn_coverage": 1.0,
        "reader_visible_answer_span_coverage": 1.0,
    }


def test_turn_only_label_does_not_invent_span_coverage() -> None:
    source_ref = "memory://session/s1/turn/1"
    metrics = exact_answer_evidence_metrics(
        discovered_source_turn_refs=[source_ref],
        visible_units=[ReaderVisibleUnit(source_turn_refs=(source_ref,), text="visible")],
        source_text_by_turn_ref={source_ref: "source"},
        labels=[AnswerBearingSpanLabel(source_turn_ref=source_ref)],
    )

    assert metrics["reader_visible_answer_span_coverage"] is None


def test_strict_provider_schemas_reject_extra_or_wrong_typed_fields() -> None:
    assert strict_json_answer({"answer": "Vim"}) == "Vim"
    assert strict_json_judgment({"correct": True}) is True
    with pytest.raises(ValueError):
        strict_json_answer({"answer": "Vim", "reason": "extra"})
    with pytest.raises(ValueError):
        strict_json_judgment({"correct": 1})


def test_paired_bootstrap_is_deterministic_and_matched() -> None:
    left = [False] * 60 + [True] * 40
    right = [True] * 10 + [False] * 50 + [True] * 40
    assert paired_bootstrap_interval(left, right, samples=1_000, seed=7) == (
        paired_bootstrap_interval(left, right, samples=1_000, seed=7)
    )


def test_final_admission_checks_apply_every_frozen_threshold() -> None:
    baseline = _arm()
    candidate = _arm(
        all_required_evidence_group_coverage=0.15,
        qwen_judge_accuracy=0.22,
        p95_latency_ms=150.0,
    )
    assert all(admission_checks(baseline, candidate, paired_ci_lower=-0.01).values())
