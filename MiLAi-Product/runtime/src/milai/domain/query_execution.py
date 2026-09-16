"""Internal execution plans mechanically projected from QueryTaskContractV01."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from milai.domain.query_task_contract import (
    OperatorOperandV01,
    ProofObligation,
    QueryOperation,
    RetrievalHintsV01,
    TypedRequirementV01,
)


class CountSemantics(StrEnum):
    NONE = "NONE"
    SCALAR_FACT = "SCALAR_FACT"
    MEMBER_SET = "MEMBER_SET"


class CompletionMode(StrEnum):
    LOOKUP_READINESS = "LOOKUP_READINESS"
    ALL_REQUIRED_ROLES = "ALL_REQUIRED_ROLES"
    MEMBER_SET_CLOSED = "MEMBER_SET_CLOSED"
    VERSION_CHAIN_CLOSED = "VERSION_CHAIN_CLOSED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"


class TaskAcquisitionTargetV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement: TypedRequirementV01
    retrieval_hints: RetrievalHintsV01 | None = None


class TaskAcquisitionPlanV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["task-acquisition-plan-v0.1"] = (
        "task-acquisition-plan-v0.1"
    )
    source_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: tuple[TaskAcquisitionTargetV01, ...]


class BindingPlanV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["binding-plan-v0.1"] = "binding-plan-v0.1"
    source_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: tuple[TypedRequirementV01, ...]


class OperatorPlanV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["operator-plan-v0.1"] = "operator-plan-v0.1"
    source_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: QueryOperation
    operand_role_keys: tuple[str, ...]
    operands: tuple[OperatorOperandV01, ...] = ()
    count_semantics: CountSemantics = CountSemantics.NONE


class CompletionContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["completion-contract-v0.1"] = (
        "completion-contract-v0.1"
    )
    source_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: CompletionMode
    required_role_keys: tuple[str, ...]
    proof_obligations: tuple[ProofObligation, ...]


class QueryExecutionPlanV01(BaseModel):
    """One drift-free bundle consumed by acquisition through completion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["query-execution-plan-v0.1"] = (
        "query-execution-plan-v0.1"
    )
    source_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition: TaskAcquisitionPlanV01
    binding: BindingPlanV01
    operator: OperatorPlanV01
    completion: CompletionContractV01


__all__ = [
    "BindingPlanV01",
    "CompletionContractV01",
    "CompletionMode",
    "CountSemantics",
    "OperatorPlanV01",
    "QueryExecutionPlanV01",
    "TaskAcquisitionPlanV01",
    "TaskAcquisitionTargetV01",
]
