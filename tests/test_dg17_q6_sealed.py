from __future__ import annotations

from scripts.run_dg17_q6_sealed import (
    _governance_from_sealed_contexts,
    _scoring_record,
    _semantic_source_refs,
)


def test_q6_sealed_reconstructs_selected_evidence_from_snapshot() -> None:
    source_ref = "longmemeval://case/case-one/session/0/session-a/turn/0"
    context = {
        "context": "MILAI_MEMORY_DATA_BEGIN\nMILAI_MEMORY_DATA_END",
        "context_identity": {"reader_context_digest": "a" * 64},
        "query_latency_ms": 12.0,
        "semantic_mediators": {
            "selected_source_refs": [source_ref],
            "derived_result": {"status": "PARTIAL"},
            "sufficiency": {"status": "UNSATISFIED"},
        },
    }
    generation = {
        "case_id": "case-one",
        "token_budget": 512,
        "policy": "DG17_QUERY_SPECIFIC_STOP",
        "answer": "answer",
        "provider": {"provider_latency_ms": 1.0, "tokenize_latency_ms": 1.0},
    }
    source_events = {
        source_ref: {
            "source_ref": source_ref,
            "role": "user",
            "content": "I stayed at Hotel X.",
            "original_session_id": "session-a",
            "evidence_id": "evidence-a",
            "observed_at": "2026-08-27T00:00:00Z",
        }
    }

    record = _scoring_record(
        generation,
        context=context,
        source_events=source_events,
    )

    assert record["evidence_items"][0]["content"] == "user: I stayed at Hotel X."
    assert record["retrieval_trace"][0]["session_id"] == "session-a"
    assert record["derived_result"] == {"status": "PARTIAL"}
    assert record["sufficiency_decision"] == {"status": "UNSATISFIED"}


def test_q6_sealed_governance_keeps_denied_evidence_gate_pending() -> None:
    source_ref = "longmemeval://case/case-one/session/0/session-a/turn/0"
    contexts = [
        {
            "case_id": "case-one",
            "semantic_mediators": {
                "selected_source_refs": [source_ref],
                "scope_authority": {"canonical_mutation": False},
                "derived_result": {"canonical_mutation": False},
            },
        }
    ]

    result = _governance_from_sealed_contexts(contexts)

    assert result["status"] == "PARTIAL_DENIED_EVIDENCE_LIVE_DENOMINATOR_PENDING"
    assert result["zero_denominator_is_pass"] is False
    assert result["counters"]["cross_case_contamination"]["accepted"] == 0
    assert result["counters"]["evaluation_label_leakage"]["accepted"] == 0
    assert result["counters"]["canonical_mutation"]["accepted"] == 0
    assert result["counters"]["denied_evidence"]["denominator"] == 0


def test_q6_sealed_semantic_refs_include_exact_derived_operands() -> None:
    selected = "longmemeval://case/case-one/session/0/session-a/turn/0"
    operand = "longmemeval://case/case-one/session/1/session-b/turn/0"

    refs = _semantic_source_refs(
        {
            "derived_result": {
                "operands": [
                    {"source_ref": selected},
                    {"source_ref": operand},
                    {"source_ref": operand},
                ]
            }
        },
        selected=[selected],
    )

    assert refs == [selected, operand]
