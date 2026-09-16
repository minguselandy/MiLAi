"""Typed, role-indexed values accepted for query-local operator execution.

Bound operands are derived from grounded Evidence interpretations.  They are
not Canonical Memory and they deliberately preserve interpretation/span
identity: one Evidence record may contain more than one valid operand.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.query_task_contract import EvidenceRole, RequirementValueType


class BoundValueV01(BaseModel):
    """One normalized semantic value with its declared query-time type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value_type: RequirementValueType
    normalized_value: JsonValue
    unit: str | None = Field(default=None, min_length=1, max_length=64)


class BoundOperandV01(BaseModel):
    """An accepted value plus exact Binding-to-Evidence lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["bound-operand-v0.1"] = "bound-operand-v0.1"
    requirement_id: str = Field(min_length=1, max_length=128)
    role_key: str = Field(min_length=1, max_length=128)
    evidence_role: EvidenceRole
    value: BoundValueV01
    binding_ref: str = Field(min_length=1, max_length=256)
    interpretation_id: str = Field(min_length=1, max_length=256)
    span_id: str = Field(min_length=1, max_length=256)
    source_evidence_id: str = Field(min_length=1, max_length=512)
    source_turn_ref: str = Field(min_length=1, max_length=1_024)

    @property
    def operand_identity(self) -> tuple[str, str, str]:
        """Identity at semantic interpretation granularity, not Evidence ID."""

        return (self.requirement_id, self.interpretation_id, self.span_id)


class RoleIndexedBoundOperandsV01(BaseModel):
    """Immutable accepted operands with role- and requirement-level access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["role-indexed-bound-operands-v0.1"] = (
        "role-indexed-bound-operands-v0.1"
    )
    operands: tuple[BoundOperandV01, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_unique_semantic_operands(self) -> RoleIndexedBoundOperandsV01:
        identities = [item.operand_identity for item in self.operands]
        if len(identities) != len(set(identities)):
            raise ValueError("bound operands must have unique semantic identities")
        return self

    @property
    def covered_role_keys(self) -> tuple[str, ...]:
        return tuple(sorted({item.role_key for item in self.operands}))

    def for_role(self, role_key: str) -> tuple[BoundOperandV01, ...]:
        return tuple(item for item in self.operands if item.role_key == role_key)

    def for_requirement(self, requirement_id: str) -> tuple[BoundOperandV01, ...]:
        return tuple(
            item for item in self.operands if item.requirement_id == requirement_id
        )

    def missing_role_keys(self, required_role_keys: tuple[str, ...]) -> tuple[str, ...]:
        covered = set(self.covered_role_keys)
        return tuple(role for role in required_role_keys if role not in covered)


def build_role_indexed_bound_operands_v01(
    operands: tuple[BoundOperandV01, ...] | list[BoundOperandV01],
) -> RoleIndexedBoundOperandsV01:
    """Canonicalize ordering without collapsing values from the same Evidence."""

    ordered = tuple(
        sorted(
            operands,
            key=lambda item: (
                item.role_key,
                item.requirement_id,
                item.interpretation_id,
                item.span_id,
            ),
        )
    )
    return RoleIndexedBoundOperandsV01(operands=ordered)


__all__ = [
    "BoundOperandV01",
    "BoundValueV01",
    "RoleIndexedBoundOperandsV01",
    "build_role_indexed_bound_operands_v01",
]
