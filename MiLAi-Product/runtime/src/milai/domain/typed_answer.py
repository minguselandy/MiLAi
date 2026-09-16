"""DG-25 typed OperatorResult authority and Reader conformance contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.requirement_state import canonical_sha256

TypedAnswerTypeV01 = Literal[
    "INTEGER",
    "NUMBER",
    "BOOLEAN",
    "DATE",
    "DURATION",
    "TEMPORAL_ORDER",
    "STATE",
    "EXPLANATION",
    "PREFERENCE_RATIONALE",
]
TypedRenderingRouteV01 = Literal[
    "DETERMINISTIC_FORMATTER",
    "CONSTRAINED_READER",
    "ABSTAIN",
]


class TypedAnswerLineageV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sufficiency_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    proof_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class TypedAnswerContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer_type: TypedAnswerTypeV01
    normalized_value: JsonValue | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    allowed_surface_variants: list[str] = Field(default_factory=list, max_length=32)
    allowed_evidence_refs: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        for values in (self.allowed_surface_variants, self.allowed_evidence_refs):
            if values != sorted(set(values)):
                raise ValueError("answer variants and Evidence refs must be sorted and unique")
        if self.answer_type in {"INTEGER", "NUMBER", "DURATION"} and self.unit is None:
            raise ValueError("numeric and duration answers require an explicit unit")
        return self


class ReaderValueConstraintsV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value_must_echo_operator: Literal[True] = True
    may_change_value: Literal[False] = False
    may_change_unit: Literal[False] = False


class TypedAnswerDecisionV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["typed-answer-decision-v0.1"] = "typed-answer-decision-v0.1"
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lineage: TypedAnswerLineageV01
    runtime_status: Literal["COMPLETE", "PARTIAL", "CONTESTED", "UNAVAILABLE"]
    answer_contract: TypedAnswerContractV01
    rendering_route: TypedRenderingRouteV01
    reader_constraints: ReaderValueConstraintsV01 = Field(default_factory=ReaderValueConstraintsV01)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        deterministic_types = {
            "INTEGER",
            "NUMBER",
            "BOOLEAN",
            "DATE",
            "DURATION",
            "TEMPORAL_ORDER",
            "STATE",
        }
        reader_types = {"EXPLANATION", "PREFERENCE_RATIONALE"}
        if self.runtime_status != "COMPLETE":
            if self.rendering_route != "ABSTAIN":
                raise ValueError("incomplete Runtime state must abstain")
        elif self.answer_contract.answer_type in deterministic_types:
            if self.rendering_route != "DETERMINISTIC_FORMATTER":
                raise ValueError("deterministic typed value cannot be delegated to Reader")
            if self.answer_contract.normalized_value is None:
                raise ValueError("complete deterministic answer requires a normalized value")
        elif self.answer_contract.answer_type in reader_types:
            if self.rendering_route != "CONSTRAINED_READER":
                raise ValueError("semantic rendering requires the constrained Reader route")
        material = self.model_dump(mode="json", exclude={"decision_digest"})
        if self.decision_digest != canonical_sha256(material):
            raise ValueError("typed answer decision digest mismatch")
        return self


def build_typed_answer_decision_v01(
    *,
    lineage: TypedAnswerLineageV01,
    runtime_status: Literal["COMPLETE", "PARTIAL", "CONTESTED", "UNAVAILABLE"],
    answer_contract: TypedAnswerContractV01,
    rendering_route: TypedRenderingRouteV01,
) -> TypedAnswerDecisionV01:
    reader_constraints = ReaderValueConstraintsV01()
    material = {
        "schema_version": "typed-answer-decision-v0.1",
        "lineage": lineage.model_dump(mode="json"),
        "runtime_status": runtime_status,
        "answer_contract": answer_contract.model_dump(mode="json"),
        "rendering_route": rendering_route,
        "reader_constraints": reader_constraints.model_dump(mode="json"),
    }
    return TypedAnswerDecisionV01(
        schema_version="typed-answer-decision-v0.1",
        decision_digest=canonical_sha256(material),
        lineage=lineage,
        runtime_status=runtime_status,
        answer_contract=answer_contract,
        rendering_route=rendering_route,
        reader_constraints=reader_constraints,
    )


class ReaderAnswerConformanceV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reader-answer-conformance-v0.1"] = "reader-answer-conformance-v0.1"
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: bool
    reason_code: str = Field(min_length=1, max_length=160)


def validate_reader_answer_v01(
    decision: TypedAnswerDecisionV01,
    payload: str | Mapping[str, object],
) -> ReaderAnswerConformanceV01:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return _conformance(decision, False, "READER_INVALID_JSON")
        if not isinstance(parsed, dict):
            return _conformance(decision, False, "READER_INVALID_JSON")
        value: Mapping[str, object] = parsed
    else:
        value = payload
    if decision.rendering_route != "CONSTRAINED_READER":
        return _conformance(decision, False, "READER_ROUTE_NOT_AUTHORIZED")
    if value.get("normalized_value") != decision.answer_contract.normalized_value:
        return _conformance(decision, False, "READER_OPERATOR_VALUE_MISMATCH")
    if value.get("unit") != decision.answer_contract.unit:
        return _conformance(decision, False, "READER_OPERATOR_UNIT_MISMATCH")
    if value.get("asserts_complete") is not True:
        return _conformance(decision, False, "READER_COMPLETENESS_MISMATCH")
    evidence_refs = value.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) for item in evidence_refs
    ):
        return _conformance(decision, False, "READER_EVIDENCE_REFS_INVALID")
    if not set(evidence_refs).issubset(decision.answer_contract.allowed_evidence_refs):
        return _conformance(decision, False, "READER_EVIDENCE_REF_OUTSIDE_SET")
    return _conformance(decision, True, "READER_CONFORMANT")


def _conformance(
    decision: TypedAnswerDecisionV01,
    accepted: bool,
    reason_code: str,
) -> ReaderAnswerConformanceV01:
    return ReaderAnswerConformanceV01(
        decision_digest=decision.decision_digest,
        accepted=accepted,
        reason_code=reason_code,
    )


__all__ = [
    "ReaderAnswerConformanceV01",
    "ReaderValueConstraintsV01",
    "TypedAnswerContractV01",
    "TypedAnswerDecisionV01",
    "TypedAnswerLineageV01",
    "TypedAnswerTypeV01",
    "TypedRenderingRouteV01",
    "build_typed_answer_decision_v01",
    "validate_reader_answer_v01",
]
