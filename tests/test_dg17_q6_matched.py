from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

from evals.dg17.q6_matched import (
    BASELINE_CORRECT_2048,
    _operator_measurement,
    _score_retrieval_fixed_ideal,
    _semantic_measurement,
    evaluate_development_gate,
    summarize_matched_records,
)
from scripts.run_dg16_lme10_compare import _context_record
from scripts.run_dg17_q6_matched import (
    Q6RunError,
    _aggregate_governance_safety,
    _load_shadow,
    _shadow_cost_overlay,
    run,
)


def _cell(case_id: str, budget: int, *, exact: int, f1: float) -> dict[str, object]:
    return {
        "case_id": case_id,
        "token_budget": budget,
        "query_class": "TEMPORAL",
        "answer_score": {"exact_match": exact, "normalized_f1": f1},
        "retrieval_score": {"relevant_coverage_at_k": 1.0},
        "retrieved_atom_ids": [f"{case_id}-atom"],
        "required_atom_count": 1,
        "answer_bearing_span_hit_count": 1,
        "answer_bearing_span_count": 1,
        "answer_bearing_source_turn_hit_count": 1,
        "answer_bearing_source_turn_count": 1,
        "requirement_binding_true_count": 1,
        "requirement_binding_predicted_count": 1,
        "operator_applicable": True,
        "operator_execution_correct": True,
        "operator_safety_correct": True,
        "wrong_complete": False,
        "strict_em_boundary_candidate": False,
        "query_latency_ms": 10.0,
        "answer_path_latency_ms": 100.0,
    }


def test_q6_summary_and_development_gate_keep_frozen_thresholds() -> None:
    case_ids = [
        "9a707b82",
        "a82c026e",
        "case-3",
        "case-4",
        "case-5",
        "case-6",
        "case-7",
        "case-8",
        "case-9",
        "case-10",
    ]
    records = [
        _cell(case_id, budget, exact=int(index < 6), f1=0.6)
        for budget in (512, 2048)
        for index, case_id in enumerate(case_ids)
    ]
    summaries = summarize_matched_records(records)
    gate = evaluate_development_gate(summaries, records)

    assert summaries["2048"]["exact_match_count"] == 6
    assert summaries["2048"]["required_evidence_set_coverage"] == 1.0
    assert summaries["2048"]["answer_bearing_span_recall"] == 1.0
    assert summaries["2048"]["requirement_binding_precision"] == 1.0
    assert gate["status"] == "PASS"
    assert gate["thresholds_changed"] is False
    assert set(gate["preserved_baseline_correct_2048"]) == BASELINE_CORRECT_2048


def test_q6_operator_measurement_separates_safe_partial_from_wrong_complete() -> None:
    label = {
        "gold_ir": {"operator": "COUNT_DISTINCT"},
        "atoms": [{"span": {"text": "Charlotte"}} for _ in range(5)],
    }

    partial = _operator_measurement(
        "2e6d26dc",
        label,
        {"status": "PARTIAL", "reason": "EVENT_TIME_UNRESOLVED"},
    )
    wrong = _operator_measurement(
        "2e6d26dc",
        label,
        {"status": "COMPLETE", "value": 4},
    )

    assert partial["operator_execution_correct"] is False
    assert partial["operator_safety_correct"] is True
    assert partial["wrong_complete"] is False
    assert wrong["operator_safety_correct"] is False
    assert wrong["wrong_complete"] is True


def test_q6_terminal_complete_without_required_evidence_is_wrong_complete() -> None:
    label = {"gold_ir": {"operator": "LOOKUP"}, "atoms": []}

    result = _operator_measurement(
        "lookup-case",
        label,
        None,
        terminal_sufficiency={"status": "COMPLETE"},
        requirements_complete=False,
    )

    assert result["terminal_sufficiency_complete"] is True
    assert result["operator_safety_correct"] is False
    assert result["wrong_complete"] is True


def test_q6_runner_refuses_non_authorizing_preflight_before_external_calls(
    tmp_path: Path,
) -> None:
    preflight = tmp_path / "preflight.json"
    payload = json.dumps(
        {
            "status": "Q6_PREFLIGHT_COMPLETE_EXTERNAL_EXECUTION_PAUSED",
            "execution_authorized": False,
        },
        sort_keys=True,
    ).encode()
    preflight.write_bytes(payload)

    with pytest.raises(Q6RunError, match="does not authorize external execution"):
        run(
            run_id="must-not-run",
            output_root=tmp_path / "output",
            preflight=preflight,
            preflight_sha256=hashlib.sha256(payload).hexdigest(),
            q3c_shadow_report=tmp_path / "missing-shadow.json",
            reader_url="http://127.0.0.1:1",
            tokenizer_path=tmp_path / "missing-tokenizer",
            env_file=tmp_path / "missing-env",
            mcp_concurrency=1,
            projection_batch_size=1,
        )

    assert not (tmp_path / "output").exists()


def test_q6_ndcg_ideal_is_fixed_by_labels_not_prediction_length() -> None:
    scored = _score_retrieval_fixed_ideal(
        [{"session_id": "relevant-a"}],
        ["relevant-a", "relevant-b"],
    )

    assert scored["relevant_coverage_at_k"] == 0.5
    assert float(scored["ndcg_at_k"]) < 1.0
    assert scored["ndcg_ideal_relevant_count"] == 2
    assert scored["ndcg_denominator_policy"] == (
        "ALL_RELEVANT_SESSIONS_FIXED_FROM_LABELS"
    )


def test_q6_atom_coverage_requires_source_turn_identity_not_text_only() -> None:
    query = "What hotel did I use on my last trip?"
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
        )
    )
    label = {
        "atoms": [
            {
                "atom_id": "atom-1",
                "slot": "LOOKUP_ANSWER",
                "source_turn_ref": "case-one:s0:session-a:t1",
                "span": {"text": "I stayed at Hotel X."},
            }
        ]
    }
    record = {
        "context": "I stayed at Hotel X.",
        "evidence_items": [
            {
                "evidence_id": "evidence-wrong-source",
                "source_ref": "case-one:s1:session-b:t1",
                "content": "user: I stayed at Hotel X.",
            }
        ],
    }

    measured = _semantic_measurement(record, label, plan)

    assert measured["retrieved_atom_ids"] == []
    assert measured["answer_bearing_span_recall"] == 0.0
    assert measured["answer_bearing_source_turn_recall"] == 0.0
    assert measured["coverage_identity_policy"] == (
        "SOURCE_TURN_REF_PLUS_NORMALIZED_SPAN_TEXT"
    )


def test_q6_shadow_overlay_reports_cost_without_fabricating_quality_delta(
    tmp_path: Path,
) -> None:
    shadow = {
        "status": "Q3C_SHADOW_CHARACTERIZED",
        "aggregate": {
            "case_count": 29,
            "wrong_promoted_hint": 7,
            "schema_or_span_rejections": 3,
        },
        "teacher_target_in_prompt": False,
        "deterministic_requirement_ids_in_prompt": False,
        "fixture_split": "AUTHORED_DEV_NO_HELDOUT_CLAIM",
        "q3d_gate": {"eligible": False},
        "rows": [
            {
                "case_id": f"current10:case-{index}",
                "minimal_hint": {
                    "wrong_promoted": False,
                    "receipt": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "timing": {"total_ms": 10.0},
                    }
                },
            }
            for index in range(10)
        ]
        + [
            {
                "case_id": f"unseen-{index}",
                "minimal_hint": {"receipt": None, "wrong_promoted": False},
            }
            for index in range(19)
        ],
    }
    path = tmp_path / "shadow.json"
    path.write_text(json.dumps(shadow), encoding="utf-8")
    summaries = {
        "512": {"normalized_f1": 0.5, "answer_path_latency_ms_mean": 100.0},
        "2048": {"normalized_f1": 0.6, "answer_path_latency_ms_mean": 200.0},
    }

    loaded = _load_shadow(path)
    overlay = _shadow_cost_overlay(loaded, summaries)

    assert overlay["status"] == "COUNTERFACTUAL_COST_OVERLAY_NOT_EXECUTED_ARM"
    assert overlay["executed_product_arm"] is False
    assert overlay["quality_effect_measured"] is False
    assert overlay["wrong_promoted_hint_current10"] == 0
    assert overlay["coverage_delta_after_hint"] is None
    assert overlay["queries_changed_by_hint"] is None
    assert overlay["budgets"]["2048"]["source_normalized_f1_reference"] == 0.6
    assert overlay["budgets"]["2048"]["semantic_hint_call_rate"] == 1.0
    assert overlay["budgets"]["2048"]["semantic_hint_latency_ms_mean"] == 10.0
    assert (
        overlay["budgets"]["2048"][
            "counterfactual_quality_per_second_if_cost_added"
        ]
        < 3.0
    )


def test_runtime_context_archive_preserves_semantic_execution_metadata() -> None:
    context = "MILAI_MEMORY_DATA_BEGIN\nMILAI_MEMORY_DATA_END"
    context_digest = hashlib.sha256(context.encode()).hexdigest()
    receipt_mapping = [
        {
            "alias": "E1",
            "evidence_ids": ["evidence-one"],
            "source_turn_refs": ["case:s0:t0"],
            "claim_versions": [],
            "issue_revisions": [],
        }
    ]
    result = SimpleNamespace(
        usage={"retrieval_logical_calls": 1},
        provenance=(),
        selected_source_refs=(),
        raw_resolve={
            "derived_result": {"status": "COMPLETE", "value": 4},
            "query_plan": {"operator": "TEMPORAL_COUNT_DISTINCT"},
            "context_receipt": {
                "authority_class": "EVIDENCE_ONLY",
                "receipt_mapping": receipt_mapping,
            },
            "memory_context": {
                "semantic_context_digest": "a" * 64,
                "reader_context_digest": context_digest,
            },
            "items": [{"kind": "EVIDENCE_OBSERVATION", "content": "user: baked"}],
            "sufficiency_decision": {"status": "COMPLETE"},
            "search_trace": {"stop_stage": "SUFFICIENCY"},
        },
        context=context,
        declared_tokens=10,
        latency_ms=1.0,
    )
    case = SimpleNamespace(case_id="case", category="aggregation")

    record = _context_record(
        case=case,
        method_id="DG16-MILAI-MCP",
        budget=2048,
        result=result,
    )

    assert record["derived_result"] == {"status": "COMPLETE", "value": 4}
    assert record["query_plan"] == {"operator": "TEMPORAL_COUNT_DISTINCT"}
    assert record["context_receipt"] == {
        "authority_class": "EVIDENCE_ONLY",
        "receipt_mapping": receipt_mapping,
    }
    assert record["evidence_items"][0]["content"] == "user: baked"
    assert record["sufficiency_decision"] == {"status": "COMPLETE"}
    assert record["search_trace"] == {"stop_stage": "SUFFICIENCY"}
    assert record["context_identity"] == {
        "semantic_context_digest": "a" * 64,
        "reader_context_digest": context_digest,
        "receipt_mapping": receipt_mapping,
    }


def test_q6_governance_aggregator_refuses_zero_denominator_pass() -> None:
    receipts = [
        {
            "safety": {
                name: {"denominator": 1, "accepted": 0}
                for name in (
                    "wrong_scope",
                    "wrong_principal_write",
                    "revoked_evidence",
                    "canonical_promotion",
                    "silent_fallback",
                )
            }
        }
    ]
    contexts = [
        {
            "case_id": "case-one",
            "selected_source_refs": ["case-one:s0:session:t1"],
            "evidence_items": [{"evidence_id": "one"}],
        }
    ]

    result = _aggregate_governance_safety(receipts, contexts)

    assert result["status"] == "PARTIAL_DENIED_EVIDENCE_LIVE_DENOMINATOR_PENDING"
    assert result["zero_denominator_is_pass"] is False
    assert result["counters"]["wrong_scope"] == {
        "denominator": 1,
        "accepted": 0,
    }
    assert result["counters"]["denied_evidence"]["denominator"] == 0
    assert result["counters"]["cross_case_contamination"]["accepted"] == 0
    assert result["counters"]["label_leakage"]["accepted"] == 0


def test_q6_governance_aggregator_measures_contamination_and_label_leakage() -> None:
    receipts = [
        {
            "safety": {
                name: {"denominator": 1, "accepted": 0}
                for name in (
                    "wrong_scope",
                    "wrong_principal_write",
                    "revoked_evidence",
                    "canonical_promotion",
                    "silent_fallback",
                )
            }
        }
    ]
    contexts = [
        {
            "case_id": "case-one",
            "selected_source_refs": ["case-two:s0:session:t1"],
            "nested": {"gold_ir": {"operator": "LOOKUP"}},
        }
    ]

    result = _aggregate_governance_safety(receipts, contexts)

    assert result["status"] == "FAIL"
    assert result["counters"]["cross_case_contamination"]["accepted"] == 1
    assert result["counters"]["label_leakage"]["accepted"] == 1
