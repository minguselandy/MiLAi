from __future__ import annotations

from datetime import UTC, datetime

from milai.application.decision_engine import DEFAULT_DECISION_ENGINE
from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.application.query_operators import execute_query_operator
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import RequirementBinding


def _raw_match() -> RequirementBinding:
    return RequirementBinding.model_construct(
        requirement_id="requirement:1:answer",
        interpretation_id="interpretation:1",
        status="MATCH",
    )


def test_raw_match_never_becomes_an_operator_operand() -> None:
    assert operator_operands_from_raw_bindings((_raw_match(),)) == ()


def test_canonical_authority_does_not_prove_natural_language_operand_role() -> None:
    reference = datetime(2026, 9, 2, tzinfo=UTC)
    request = RetrievalRequest(
        route="L1",
        query="How many fish are in my tank?",
        reference_time=reference,
        as_of=reference,
        system_as_of=reference,
    )
    plan = QueryPlanner().plan(request)
    canonical = {
        "kind": "CANONICAL_STATE",
        "claim_version_id": "claim-version:poster",
        "authority_class": "CANONICAL_STATE",
        "content": "I bought ten fish posters for the office.",
        "observed_at": "2026-01-01T00:00:00+00:00",
    }
    operator_result = execute_query_operator(plan, (canonical,))
    assert operator_result is not None and operator_result["status"] == "OK"
    operator_result = {
        **operator_result,
        "operand_authority": "CANONICAL_GATE_ONLY",
    }

    decision = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=(canonical,),
        canonical_results=(canonical,),
        spans=(),
        interpretations=(),
        bindings=(),
        operator_result=operator_result,
        temporal_proof=None,
        request=request,
        plan=plan,
        mode="STRICT_OPERATOR",
    )

    assert decision.sufficiency_decision.complete is False


def test_absent_contract_does_not_restore_canonical_operand_inference() -> None:
    reference = datetime(2026, 9, 2, tzinfo=UTC)
    request = RetrievalRequest(
        route="L1",
        query="How many fish are in my tank?",
        reference_time=reference,
        as_of=reference,
        system_as_of=reference,
    )
    fresh_plan = QueryPlanner().plan(request)
    plan = fresh_plan.model_copy(
        update={"query_task_contract": None, "query_execution_plan": None}
    )
    canonical = {
        "kind": "CANONICAL_STATE",
        "claim_version_id": "claim-version:poster",
        "authority_class": "CANONICAL_STATE",
        "content": "I bought ten fish posters for the office.",
        "observed_at": "2026-01-01T00:00:00+00:00",
    }
    operator_result = execute_query_operator(plan, (canonical,))
    assert operator_result is not None and operator_result["status"] == "OK"

    decision = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=(canonical,),
        canonical_results=(canonical,),
        spans=(),
        interpretations=(),
        bindings=(),
        operator_result={**operator_result, "operand_authority": "CANONICAL_GATE_ONLY"},
        temporal_proof=None,
        request=request,
        plan=plan,
        mode="STRICT_OPERATOR",
    )

    assert decision.sufficiency_decision.complete is False


def test_natural_language_count_cannot_claim_closed_empty_authority() -> None:
    reference = datetime(2026, 9, 2, tzinfo=UTC)
    request = RetrievalRequest(
        route="L1",
        query="How many concerts did I attend in July 2026?",
        reference_time=reference,
        as_of=reference,
        system_as_of=reference,
    )
    plan = QueryPlanner().plan(request)
    assert plan.query_execution_plan is not None
    required = list(plan.query_execution_plan.completion.required_role_keys)
    decision = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=(),
        canonical_results=(),
        spans=(),
        interpretations=(),
        bindings=(),
        operator_result={
            "kind": "EVIDENCE_COMPOSITION_RESULT",
            "status": "COMPLETE",
            "operator": plan.operator,
            "result": 0,
            "operands": [],
            "operand_authority": "ACCEPTED_BINDING_ONLY",
            "hidden_model_calls": 0,
            "canonical_mutation": False,
            "completeness": {
                "required_slots": required,
                "filled_slots": required,
                "bounded_scan_complete": True,
                "source_partition_closed": True,
                "projection_watermark_covered": True,
                "deduplication_proven": True,
            },
        },
        temporal_proof=None,
        request=request,
        plan=plan,
        mode="STRICT_OPERATOR",
    )

    assert decision.sufficiency_decision.complete is False
