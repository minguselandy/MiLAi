from __future__ import annotations

from pathlib import Path

import pytest
from evals.dg20.matched_q6_eval import (
    ARM_A,
    ARM_B,
    ARMS,
    BUDGETS,
    PRODUCT_SCHEMA,
    DG20S5EvaluationError,
    _compare_budget,
    _first_gold_rank,
    _matched_causal_reader_records,
    _prepare_scoring_records,
    _safety_cost,
    _state_correctness,
    seal_s5_product,
)
from scripts.run_dg20_s5_matched_q6 import (
    DG20S5RunError,
    _assert_case_pairing,
    _session_id,
)


def test_seal_rejects_evaluation_truth_before_product_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_ids = tuple(f"case-{index}" for index in range(10))
    monkeypatch.setattr("evals.dg20.matched_q6_eval._case_ids", lambda: case_ids)
    records = [
        {
            "case_id": case_id,
            "arm": arm,
            "token_budget": budget,
            "answers": ["forbidden"],
            "memory_query_ir": {"required_slots": ["PRODUCT_QUERY_SLOT"]},
        }
        for case_id in case_ids
        for arm in ARMS
        for budget in BUDGETS
    ]
    product = {
        "schema": PRODUCT_SCHEMA,
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "records": records,
    }

    with pytest.raises(DG20S5EvaluationError, match="evaluation truth leaked"):
        seal_s5_product(product, tmp_path / "sealed.json")


def test_seal_allows_product_query_ir_required_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_ids = tuple(f"case-{index}" for index in range(10))
    monkeypatch.setattr("evals.dg20.matched_q6_eval._case_ids", lambda: case_ids)
    product = {
        "schema": PRODUCT_SCHEMA,
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "records": [
            {
                "case_id": case_id,
                "arm": arm,
                "token_budget": budget,
                "memory_query_ir": {"required_slots": ["PRODUCT_QUERY_SLOT"]},
            }
            for case_id in case_ids
            for arm in ARMS
            for budget in BUDGETS
        ],
    }

    output = tmp_path / "sealed.json"
    seal_s5_product(product, output)
    assert output.is_file()


def test_compare_budget_reports_mediator_gain_without_correct_regression() -> None:
    labels = {
        "c1": {"answer_session_ids": ["session-one"]},
        **{f"c{i}": {"answer_session_ids": [f"session-{i}"]} for i in range(2, 11)},
    }
    baseline = [_scored_row(f"c{i}", ARM_A, hit=(i > 2)) for i in range(1, 11)]
    candidate = [_scored_row(f"c{i}", ARM_B, hit=True) for i in range(1, 11)]
    baseline[0]["answer_score"] = {"exact_match": 1}
    candidate[0]["answer_score"] = {"exact_match": 1}

    comparison = _compare_budget(
        baseline,
        candidate,
        budget=2_048,
        labels=labels,
        baseline_summary={
            "required_evidence_set_coverage": 0.8,
            "normalized_f1": 0.4,
            "exact_match_count": 1,
        },
        candidate_summary={
            "required_evidence_set_coverage": 1.0,
            "normalized_f1": 0.5,
            "exact_match_count": 1,
        },
    )

    assert comparison["missing_requirement_improved_case_count"] == 2
    assert comparison["required_evidence_set_coverage_delta"] == 0.2
    assert comparison["already_correct_regression_count"] == 0
    assert comparison["ineligible_context_changed_count"] == 0


def test_state_and_safety_metrics_bind_typed_negative_gates() -> None:
    records = []
    for index in range(2):
        records.append(
            {
                "arm": ARM_B,
                "token_budget": 2_048,
                "wrong_complete": False,
                "query_latency_ms": 1.0,
                "context_tokens": 10,
                "evidence_items": [{}],
                "recovery": {
                    "initial_requirement_state_epoch": 0,
                    "initial_requirement_state_digest": "state",
                    "decision": {
                        "requirement_state_epoch": 0,
                        "requirement_state_digest": "state",
                        "selected_action": None,
                    },
                    "extra_pass_count": index,
                    "provider_calls": 0,
                    "automatic_retries": 0,
                    "canonical_mutation": False,
                },
            }
        )
    state = _state_correctness(
        records,
        {
            "hard_gate": {
                "state_digest_rejection_correctness": {
                    "numerator": 4,
                    "denominator": 4,
                }
            }
        },
    )
    cost = _safety_cost(
        records,
        {"hard_gate": {"wrong_scope_authority_revoke": {"observed": 0}}},
        candidate_scored=records,
    )

    assert state["stale_state_negative_rejection_rate"] == 1.0
    assert state["execution_state_digest_mismatch_count"] == 0
    assert cost["max_extra_pass_count_per_query"] == 1
    assert cost["governance_violation_count"] == 0


def test_same_snapshot_pairing_requires_arm_independent_seed() -> None:
    records = [
        {
            "arm": arm,
            "token_budget": budget,
            "source_snapshot_digest": "snapshot",
            "provider": {"seed": 7},
        }
        for budget in BUDGETS
        for arm in ARMS
    ]
    _assert_case_pairing(records, "case", "snapshot")
    records[-1]["provider"] = {"seed": 8}
    with pytest.raises(DG20S5RunError, match="seed was not matched"):
        _assert_case_pairing(records, "case", "snapshot")


def test_scoring_projection_includes_official_derived_operands() -> None:
    source_ref = "longmemeval://case/case/session/1/session-answer/turn/0"
    prepared = _prepare_scoring_records(
        [
            {
                "case_id": "case",
                "arm": ARM_B,
                "token_budget": 2_048,
                "evidence_items": [],
                "selected_source_refs": ["case:s1:session-answer:t0"],
                "retrieval_trace": [],
                "derived_result": {
                    "operands": [
                        {
                            "source_ref": source_ref,
                            "source_span": "user: exact answer-bearing event",
                            "source_timestamp": "2023-01-01T00:00:00+00:00",
                            "system_timestamp": "2026-01-01T00:00:00+00:00",
                            "evidence_ids": ["evidence-1"],
                        }
                    ]
                },
            }
        ]
    )

    assert prepared[0]["evidence_items"][0]["source_ref"] == source_ref
    assert prepared[0]["scoring_projection"]["derived_operand_count"] == 1
    assert prepared[0]["retrieval_trace"][0]["session_id"] == "session-answer"


def test_identical_prompt_uses_one_real_reader_observation_for_causal_score() -> None:
    baseline = {
        "case_id": "case",
        "arm": ARM_A,
        "token_budget": 2_048,
        "context_sha256": "context",
        "answer": "exact baseline",
        "provider": {
            "prompt_sha256": "prompt",
            "answer_sha256": "answer-a",
            "seed": 7,
        },
    }
    candidate = {
        **baseline,
        "arm": ARM_B,
        "answer": "raw nondeterministic boundary",
        "provider": {
            "prompt_sha256": "prompt",
            "answer_sha256": "answer-b",
            "seed": 7,
        },
    }

    paired, report = _matched_causal_reader_records([baseline, candidate])

    assert paired[1]["answer"] == "exact baseline"
    assert paired[1]["raw_answer"] == "raw nondeterministic boundary"
    assert report["raw_identical_prompt_answer_divergence_count"] == 1


def test_compact_source_ref_session_parser() -> None:
    assert (
        _session_id("case:s11:session-d7c27deef2b8b978c1728ea3:t7")
        == "session-d7c27deef2b8b978c1728ea3"
    )
    assert _session_id("not-a-longmemeval-ref") is None


def test_gold_rank_accepts_answer_bearing_atom_label_shape() -> None:
    rank = _first_gold_rank(
        [
            {"rank": 1, "session_id": "noise"},
            {"rank": 2, "session_id": "gold-session"},
        ],
        {"atoms": [{"session_id": "gold-session"}]},
    )
    assert rank == 2


def _scored_row(case_id: str, arm: str, *, hit: bool) -> dict[str, object]:
    session = "session-one" if case_id == "c1" else f"session-{case_id[1:]}"
    return {
        "case_id": case_id,
        "arm": arm,
        "token_budget": 2_048,
        "retrieved_atom_ids": [f"{case_id}-atom"] if hit else [],
        "answer_score": {"exact_match": 0},
        "operator_execution_correct": hit,
        "operator_safety_correct": True,
        "context_sha256": "same",
        "recovery": {"decision": {"selected_action": None}},
        "retrieval_trace": [
            {
                "rank": 1,
                "source_id": f"{case_id}:s0:{session}:t0",
                "session_id": session,
            }
        ],
    }
