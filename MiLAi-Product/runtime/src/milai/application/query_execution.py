"""Mechanical QueryTaskContractV01 to internal execution-plan projection."""

from __future__ import annotations

from milai.domain.query_execution import (
    BindingPlanV01,
    CompletionContractV01,
    CompletionMode,
    CountSemantics,
    OperatorPlanV01,
    QueryExecutionPlanV01,
    TaskAcquisitionPlanV01,
    TaskAcquisitionTargetV01,
)
from milai.domain.query_task_contract import (
    CollectionKind,
    EvidenceTopology,
    ParseDisposition,
    QueryOperation,
    QueryTaskContractV01,
)


def derive_query_execution_plan_v01(
    contract: QueryTaskContractV01,
) -> QueryExecutionPlanV01:
    """Project typed semantics without rereading query text or inferring intent."""

    if contract.parse_disposition == ParseDisposition.UNSUPPORTED:
        raise ValueError("unsupported query has no executable plan")
    assert contract.operation is not None
    assert contract.evidence_topology is not None

    digest = contract.contract_digest
    hints_by_requirement = {
        hints.requirement_id: hints for hints in contract.retrieval_hints
    }
    required = tuple(item for item in contract.requirements if item.required)
    role_keys = tuple(item.role_key for item in required)

    acquisition = TaskAcquisitionPlanV01(
        source_contract_digest=digest,
        targets=tuple(
            TaskAcquisitionTargetV01(
                requirement=requirement,
                retrieval_hints=hints_by_requirement.get(requirement.requirement_id),
            )
            for requirement in contract.requirements
        ),
    )
    binding = BindingPlanV01(
        source_contract_digest=digest,
        requirements=contract.requirements,
    )
    operator = OperatorPlanV01(
        source_contract_digest=digest,
        operation=contract.operation,
        operand_role_keys=role_keys,
        operands=contract.operator_operands,
        count_semantics=_count_semantics(contract),
    )
    completion = CompletionContractV01(
        source_contract_digest=digest,
        mode=_completion_mode(contract),
        required_role_keys=role_keys,
        proof_obligations=contract.proof_obligations,
    )
    return QueryExecutionPlanV01(
        source_contract_digest=digest,
        acquisition=acquisition,
        binding=binding,
        operator=operator,
        completion=completion,
    )


def _count_semantics(contract: QueryTaskContractV01) -> CountSemantics:
    if contract.operation != QueryOperation.COUNT:
        return CountSemantics.NONE
    if any(
        requirement.required
        and requirement.collection.kind == CollectionKind.SCALAR_FACT
        for requirement in contract.requirements
    ):
        return CountSemantics.SCALAR_FACT
    return CountSemantics.MEMBER_SET


def _completion_mode(contract: QueryTaskContractV01) -> CompletionMode:
    assert contract.operation is not None
    assert contract.evidence_topology is not None
    if contract.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL:
        return CompletionMode.LOOKUP_READINESS
    if contract.evidence_topology == EvidenceTopology.MEMBER_SET:
        return CompletionMode.MEMBER_SET_CLOSED
    if contract.evidence_topology == EvidenceTopology.VERSION_CHAIN:
        return CompletionMode.VERSION_CHAIN_CLOSED
    if contract.evidence_topology == EvidenceTopology.CONFLICT_SET:
        return CompletionMode.CONFLICT_RESOLVED
    if contract.operation == QueryOperation.LOOKUP:
        return CompletionMode.LOOKUP_READINESS
    return CompletionMode.ALL_REQUIRED_ROLES


__all__ = ["derive_query_execution_plan_v01"]
