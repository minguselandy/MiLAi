from __future__ import annotations

import hashlib
from typing import Literal, cast

from pydantic import JsonValue

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import execution_operator_from_ir
from milai.domain.retrieval import QueryOperator, QueryPlan, RetrievalRequest
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    MemoryPlannerTrace,
    MemoryQueryConstraints,
    MemoryQueryIRV02,
    MemoryQueryStep,
)


class QueryPlanner:
    """Sole final owner for safe, deterministic executable query plans."""

    VERSION = "lean-query-plan-v12-dg17-ir-v02"

    def __init__(self, compiler: MemoryQueryCompiler | None = None) -> None:
        self._compiler = compiler or MemoryQueryCompiler()

    def plan(
        self,
        request: RetrievalRequest,
        *,
        require_user_confirmation: bool = False,
        context_budget: int = 8_000,
        minimum_outbox_sequence: int | None = None,
        access_intent: str | None = None,
        candidate_cap: int = 256,
        deadline_ms: int = 2_000,
        reranker_candidate_cap: int = 20,
        hard_partitions: tuple[str, ...] = (),
        vector_policy: str = "LEGACY",
        reranker_policy: str = "LEGACY",
    ) -> QueryPlan:
        entities = _safe_entity_addresses(request)
        reference_time = request.reference_time or request.as_of
        query_ir = (
            _exact_state_ir(request)
            if request.route == "L0"
            else self._compiler.compile(
                request.query or "",
                reference_time=reference_time,
                scope=request.requested_scope,
            )
        )
        operator: QueryOperator | None
        operator_arguments: dict[str, JsonValue]
        if request.route == "L0":
            operator, operator_arguments = None, {}
        else:
            operator, operator_arguments = execution_operator_from_ir(query_ir)
        return QueryPlan(
            planner_version=self.VERSION,
            intent="EXACT_CURRENT" if request.route == "L0" else "HYBRID_SEARCH",
            entities=entities,
            time_constraint={
                "valid_as_of": request.as_of.isoformat(),
                "query_reference_time": reference_time.isoformat(),
                "system_as_of": request.system_as_of.isoformat(),
            },
            scope_predicate=request.requested_scope,
            required_authority=request.required_authority,
            required_lifecycle=request.required_lifecycle,
            accepted_epistemic_statuses=request.accepted_epistemic_statuses,
            required_freshness=request.required_freshness,
            minimum_confidence=request.minimum_confidence,
            require_user_confirmation=require_user_confirmation,
            complexity=request.route,
            consistency_mode=request.consistency,
            minimum_outbox_sequence=minimum_outbox_sequence,
            context_budget=context_budget,
            access_intent=cast(Literal["POSSIBLE", "REQUIRED"] | None, access_intent),
            candidate_cap=candidate_cap,
            deadline_ms=deadline_ms,
            reranker_candidate_cap=reranker_candidate_cap,
            hard_partitions=list(hard_partitions),
            vector_policy=cast(
                Literal["LEGACY", "SPARSE_INSUFFICIENCY_ONLY"], vector_policy
            ),
            reranker_policy=cast(
                Literal["LEGACY", "CONDITIONAL_SMALL_SET"], reranker_policy
            ),
            routes=[request.route],
            operator=operator,
            operator_arguments=operator_arguments,
            memory_query_ir=query_ir,
            time_reference=reference_time,
        )


def _safe_entity_addresses(request: RetrievalRequest) -> list[str]:
    entities: list[str] = []
    if request.claim_id is not None:
        entities.append(f"claim:{request.claim_id}")
    for kind, value in (
        ("subject", request.subject_id),
        ("predicate", request.predicate),
        ("claim_type", request.claim_type),
    ):
        if value is not None:
            entities.append(f"{kind}_sha256:{hashlib.sha256(value.encode()).hexdigest()}")
    entities.extend(
        f"entity_sha256:{hashlib.sha256(value.encode()).hexdigest()}"
        for value in request.entities
    )
    entities.extend(
        f"memory_type_sha256:{hashlib.sha256(value.encode()).hexdigest()}"
        for value in request.memory_types
    )
    return entities


def _exact_state_ir(request: RetrievalRequest) -> MemoryQueryIRV02:
    addresses: list[dict[str, JsonValue]] = []
    if request.claim_id is not None:
        addresses.append({"claim_id": str(request.claim_id)})
    identity = {
        "subject_digest": _digest_or_none(request.subject_id),
        "predicate_digest": _digest_or_none(request.predicate),
        "claim_type_digest": _digest_or_none(request.claim_type),
    }
    if all(value is not None for value in identity.values()):
        addresses.append(cast(dict[str, JsonValue], identity))
    requirement = EvidenceRequirementV02(
        slot_id="EXACT_STATE",
        interpretation_kind="STATE_OBSERVATION",
        predicate_constraints=["canonical_state"],
        value_type="ANY",
    )
    return MemoryQueryIRV02(
        mode="STATE",
        answer_shape="STATE",
        constraints=MemoryQueryConstraints(
            state_addresses=addresses,
            scope=dict(request.requested_scope) or None,
        ),
        requirements=[requirement],
        steps=[
            MemoryQueryStep(
                kind="RETRIEVE",
                outputs=["canonical_candidates"],
                constraints={
                    "operator_family": "LOOKUP",
                    "lane": "CANONICAL_STATE",
                    "exact_address": True,
                },
                budget={
                    "embedding_calls": 0,
                    "vector_search_calls": 0,
                    "reranker_calls": 0,
                    "broad_scan_calls": 0,
                },
            ),
            MemoryQueryStep(
                kind="BIND_SLOT",
                inputs=["canonical_candidates"],
                outputs=["EXACT_STATE"],
                constraints={"gate": "CANONICAL_STATE"},
            ),
        ],
        completeness="ALL_REQUIRED_BINDINGS",
        planner_trace=MemoryPlannerTrace(
            source="DETERMINISTIC",
            compiler_version=QueryPlanner.VERSION,
            auxiliary_model_calls=0,
            reason_code="EXACT_STATE_ADDRESS",
        ),
    )


def _digest_or_none(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value is not None else None


__all__ = ["QueryPlanner"]
