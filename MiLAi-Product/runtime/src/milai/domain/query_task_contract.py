"""Internal query planning contract for the MiLAi read path.

This contract is deliberately independent of retrieval implementations and the
public ``memory-query-ir-v0.2`` schema.  It describes the requested operation,
shape, explicit constraints, and ways to look for evidence.  It never proves
that Raw natural language carries a particular relation or operand value.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ParseDisposition(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    BEST_EFFORT_RECALL = "BEST_EFFORT_RECALL"
    UNSUPPORTED = "UNSUPPORTED"


class QueryOperation(StrEnum):
    LOOKUP = "LOOKUP"
    COLLECT_SET = "COLLECT_SET"
    COUNT = "COUNT"
    SUM = "SUM"
    DIVIDE = "DIVIDE"
    COMPARE = "COMPARE"
    TEMPORAL_FILTER = "TEMPORAL_FILTER"
    TEMPORAL_ORDER = "TEMPORAL_ORDER"
    TEMPORAL_DISTANCE = "TEMPORAL_DISTANCE"
    MULTI_JOIN = "MULTI_JOIN"
    PREFERENCE_RESOLVE = "PREFERENCE_RESOLVE"
    STATE_AS_OF = "STATE_AS_OF"
    VERSION_DIFF = "VERSION_DIFF"


class OutputShape(StrEnum):
    SCALAR = "SCALAR"
    LIST = "LIST"
    ORDERED_LIST = "ORDERED_LIST"
    STATE = "STATE"
    EXPLANATION = "EXPLANATION"


class OutputValueType(StrEnum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    DURATION = "DURATION"
    ENTITY = "ENTITY"
    STATE = "STATE"
    EXPLANATION = "EXPLANATION"
    ANY = "ANY"


class EvidenceTopology(StrEnum):
    SINGLE_ITEM = "SINGLE_ITEM"
    MULTI_OPERAND = "MULTI_OPERAND"
    MEMBER_SET = "MEMBER_SET"
    VERSION_CHAIN = "VERSION_CHAIN"
    CONFLICT_SET = "CONFLICT_SET"


class EvidenceRole(StrEnum):
    ANSWER_VALUE = "ANSWER_VALUE"
    COLLECTION_MEMBER = "COLLECTION_MEMBER"
    OPERAND = "OPERAND"
    NUMERATOR = "NUMERATOR"
    DENOMINATOR = "DENOMINATOR"
    LEFT_OPERAND = "LEFT_OPERAND"
    RIGHT_OPERAND = "RIGHT_OPERAND"
    EVENT = "EVENT"
    STATE = "STATE"
    PRIOR_STATE = "PRIOR_STATE"
    CURRENT_STATE = "CURRENT_STATE"
    TRANSITION = "TRANSITION"
    SUPPORT = "SUPPORT"
    CONFLICT_SIDE = "CONFLICT_SIDE"
    PROVENANCE = "PROVENANCE"


class RequirementValueType(StrEnum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    DURATION = "DURATION"
    ENTITY = "ENTITY"
    STATE = "STATE"
    ANY = "ANY"


class ParticipantRole(StrEnum):
    ACTOR = "ACTOR"
    EXPERIENCER = "EXPERIENCER"
    BENEFICIARY = "BENEFICIARY"
    OBJECT = "OBJECT"


class EvidenceSpeaker(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"
    ARTIFACT = "ARTIFACT"


class SourceConstraintProvenance(StrEnum):
    EXPLICIT_QUERY = "EXPLICIT_QUERY"
    SEMANTIC_INTERPRETATION = "SEMANTIC_INTERPRETATION"
    CALLER_HINT = "CALLER_HINT"
    NONE = "NONE"


class TemporalKind(StrEnum):
    NONE = "NONE"
    POINT = "POINT"
    RANGE = "RANGE"
    RELATION = "RELATION"
    CURRENT = "CURRENT"
    AS_OF = "AS_OF"


class TemporalAxis(StrEnum):
    EVENT_OCCURRENCE_TIME = "EVENT_OCCURRENCE_TIME"
    SOURCE_OBSERVED_TIME = "SOURCE_OBSERVED_TIME"
    VALID_TIME = "VALID_TIME"
    SYSTEM_TIME = "SYSTEM_TIME"


class TemporalBoundary(StrEnum):
    CLOSED_OPEN = "CLOSED_OPEN"
    CLOSED_CLOSED = "CLOSED_CLOSED"


class CollectionKind(StrEnum):
    SINGLE_VALUE = "SINGLE_VALUE"
    SCALAR_FACT = "SCALAR_FACT"
    MEMBER_SET = "MEMBER_SET"


class CollectionClosureBasis(StrEnum):
    NONE = "NONE"
    QUERY_RANGE = "QUERY_RANGE"
    SOURCE_PARTITION = "SOURCE_PARTITION"
    EXPLICIT_MEMBERS = "EXPLICIT_MEMBERS"
    CANONICAL_KEY = "CANONICAL_KEY"


class ProofObligation(StrEnum):
    GROUNDED_RELATION = "GROUNDED_RELATION"
    ALL_REQUIRED_ROLES = "ALL_REQUIRED_ROLES"
    RANGE_CLOSURE = "RANGE_CLOSURE"
    PARTITION_CLOSURE = "PARTITION_CLOSURE"
    IDENTITY_DEDUP = "IDENTITY_DEDUP"
    VERSION_CHAIN = "VERSION_CHAIN"
    CONFLICT_RESOLUTION = "CONFLICT_RESOLUTION"


class RequirementBindingOperandV01(BaseModel):
    """An operator operand that must be supplied by an accepted Binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["REQUIREMENT_BINDING"] = "REQUIREMENT_BINDING"
    operand_id: str = Field(min_length=1, max_length=128)
    requirement_id: str = Field(min_length=1, max_length=128)


class QueryReferenceTimeOperandV01(BaseModel):
    """The query's resolved runtime clock, not a retrievable Evidence role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["QUERY_REFERENCE_TIME"] = "QUERY_REFERENCE_TIME"
    operand_id: str = Field(min_length=1, max_length=128)
    value: datetime
    timezone: str = Field(min_length=1, max_length=128)

    @field_validator("value")
    @classmethod
    def validate_aware_value(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("query-reference-time operand must include a timezone offset")
        return value


OperatorOperandV01 = Annotated[
    RequirementBindingOperandV01 | QueryReferenceTimeOperandV01,
    Field(discriminator="kind"),
]


class OutputContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shape: OutputShape
    value_type: OutputValueType
    unit: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.shape == OutputShape.STATE and self.value_type != OutputValueType.STATE:
            raise ValueError("STATE output shape requires STATE value type")
        if self.shape == OutputShape.EXPLANATION and self.value_type != OutputValueType.EXPLANATION:
            raise ValueError("EXPLANATION output shape requires EXPLANATION value type")
        return self


class SubjectContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: str | None = Field(default=None, min_length=1, max_length=256)
    surface_forms: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("surface_forms")
    @classmethod
    def validate_unique_surface_forms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("subject surface forms must be non-empty and unique")
        return value


class ParticipantConstraintV01(BaseModel):
    """Semantic participant; never an Evidence source-speaker restriction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ParticipantRole
    identity: str = Field(min_length=1, max_length=256)


class ValueContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value_type: RequirementValueType = RequirementValueType.ANY
    unit: str | None = Field(default=None, min_length=1, max_length=64)


class TemporalContractV01(BaseModel):
    """Calendar semantics stay in the source timezone until Runtime resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TemporalKind = TemporalKind.NONE
    axis: TemporalAxis | None = None
    reference_time: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    boundary: TemporalBoundary | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    related_requirement_ids: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_temporal_shape(self) -> Self:
        for value in (self.reference_time, self.start, self.end):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("temporal values must include a timezone offset")
        if len(self.related_requirement_ids) != len(set(self.related_requirement_ids)):
            raise ValueError("related temporal requirements must be unique")
        if self.kind == TemporalKind.NONE:
            if any(
                value is not None
                for value in (
                    self.axis,
                    self.reference_time,
                    self.start,
                    self.end,
                    self.boundary,
                    self.timezone,
                )
            ) or self.related_requirement_ids:
                raise ValueError("NONE temporal contract cannot carry temporal semantics")
        elif self.axis is None:
            raise ValueError("temporal contract requires an explicit time axis")
        elif self.kind in {TemporalKind.POINT, TemporalKind.AS_OF}:
            if self.start is None or self.end is not None or self.boundary is not None:
                raise ValueError("POINT and AS_OF require one resolved instant")
        elif self.kind == TemporalKind.RANGE:
            if self.start is None or self.end is None or self.start >= self.end:
                raise ValueError("RANGE requires start < end")
            if self.boundary is None:
                raise ValueError("RANGE requires an explicit boundary convention")
        elif self.kind == TemporalKind.RELATION:
            if len(self.related_requirement_ids) < 2:
                raise ValueError("RELATION requires at least two requirement identities")
            if self.start is not None or self.end is not None or self.boundary is not None:
                raise ValueError("RELATION cannot masquerade as an absolute interval")
        elif self.kind == TemporalKind.CURRENT and any(
            value is not None for value in (self.start, self.end, self.boundary)
        ):
            raise ValueError("CURRENT is resolved at execution and cannot carry fixed bounds")
        return self


class SourceContractV01(BaseModel):
    """Evidence origin is independent from event participants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preferred_speakers: tuple[EvidenceSpeaker, ...] = ()
    allowed_speakers: tuple[EvidenceSpeaker, ...] | None = None
    provenance: SourceConstraintProvenance = SourceConstraintProvenance.NONE

    @model_validator(mode="after")
    def validate_source_policy(self) -> Self:
        if len(self.preferred_speakers) != len(set(self.preferred_speakers)):
            raise ValueError("preferred speakers must be unique")
        if self.allowed_speakers is not None:
            if not self.allowed_speakers or len(self.allowed_speakers) != len(
                set(self.allowed_speakers)
            ):
                raise ValueError("allowed speakers must be non-empty and unique")
            if self.provenance != SourceConstraintProvenance.EXPLICIT_QUERY:
                raise ValueError("hard source restrictions require explicit-query provenance")
            if not set(self.preferred_speakers).issubset(self.allowed_speakers):
                raise ValueError("preferred speakers must be allowed")
        if self.provenance == SourceConstraintProvenance.NONE and self.preferred_speakers:
            raise ValueError("source preferences require semantic provenance")
        return self


class CollectionContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CollectionKind = CollectionKind.SINGLE_VALUE
    minimum: int = Field(default=1, ge=0)
    maximum: int | None = Field(default=1, ge=1)
    distinct: bool = False
    identity_key: str | None = Field(default=None, min_length=1, max_length=128)
    closure_basis: CollectionClosureBasis = CollectionClosureBasis.NONE

    @model_validator(mode="after")
    def validate_collection_shape(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("collection maximum cannot be below minimum")
        if self.kind in {CollectionKind.SINGLE_VALUE, CollectionKind.SCALAR_FACT}:
            if self.minimum != 1 or self.maximum != 1:
                raise ValueError("single values and scalar facts require exactly one binding")
            if self.distinct or self.identity_key is not None:
                raise ValueError("single values and scalar facts cannot request set deduplication")
        elif self.maximum == 1:
            raise ValueError("member sets cannot use a single-item maximum")
        if self.distinct and self.identity_key is None:
            raise ValueError("distinct collection requires an identity key")
        if (
            self.closure_basis != CollectionClosureBasis.NONE
            and self.kind != CollectionKind.MEMBER_SET
        ):
            raise ValueError("collection closure only applies to member sets")
        return self


class TypedRequirementV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=128)
    role_key: str = Field(min_length=1, max_length=128)
    evidence_role: EvidenceRole
    subject: SubjectContractV01 = Field(default_factory=SubjectContractV01)
    relation: str | None = Field(default=None, min_length=1, max_length=256)
    participants: tuple[ParticipantConstraintV01, ...] = Field(default=(), max_length=16)
    value: ValueContractV01 = Field(default_factory=ValueContractV01)
    temporal: TemporalContractV01 = Field(default_factory=TemporalContractV01)
    source: SourceContractV01 = Field(default_factory=SourceContractV01)
    collection: CollectionContractV01 = Field(default_factory=CollectionContractV01)
    required: bool = True

    @model_validator(mode="after")
    def validate_participants(self) -> Self:
        identities = [(item.role, item.identity) for item in self.participants]
        if len(identities) != len(set(identities)):
            raise ValueError("semantic participants must be unique")
        if (
            self.evidence_role == EvidenceRole.COLLECTION_MEMBER
            and self.collection.kind != CollectionKind.MEMBER_SET
        ):
            raise ValueError("collection-member role requires MEMBER_SET semantics")
        return self


class RetrievalHintsV01(BaseModel):
    """Non-authoritative query surfaces; never used as Binding truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=128)
    phrases: tuple[str, ...] = Field(default=(), max_length=32)
    surface_terms: tuple[str, ...] = Field(default=(), max_length=64)
    entity_aliases: tuple[str, ...] = Field(default=(), max_length=32)
    morphological_variants: tuple[str, ...] = Field(default=(), max_length=32)
    language_tags: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_hints(self) -> Self:
        for field_name in (
            "phrases",
            "surface_terms",
            "entity_aliases",
            "morphological_variants",
            "language_tags",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)) or any(not item.strip() for item in values):
                raise ValueError(f"{field_name} must contain non-empty unique values")
        return self


class QueryTaskContractV01(BaseModel):
    """One query-local semantic contract; it is never Canonical Memory state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["query-task-contract-v0.1"] = "query-task-contract-v0.1"
    parse_disposition: ParseDisposition
    operation: QueryOperation | None = None
    output: OutputContractV01 | None = None
    evidence_topology: EvidenceTopology | None = None
    requirements: tuple[TypedRequirementV01, ...] = Field(default=(), max_length=32)
    operator_operands: tuple[OperatorOperandV01, ...] = Field(default=(), max_length=32)
    proof_obligations: tuple[ProofObligation, ...] = Field(default=(), max_length=16)
    retrieval_hints: tuple[RetrievalHintsV01, ...] = Field(default=(), max_length=32)
    reason_code: str = Field(min_length=1, max_length=160)

    @field_validator("proof_obligations")
    @classmethod
    def validate_proof_order(
        cls, value: tuple[ProofObligation, ...]
    ) -> tuple[ProofObligation, ...]:
        if len(value) != len(set(value)):
            raise ValueError("proof obligations must be unique")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.parse_disposition == ParseDisposition.UNSUPPORTED:
            if any(
                (
                    self.operation is not None,
                    self.output is not None,
                    self.evidence_topology is not None,
                    bool(self.requirements),
                    bool(self.operator_operands),
                    bool(self.proof_obligations),
                    bool(self.retrieval_hints),
                )
            ):
                raise ValueError("UNSUPPORTED query cannot carry executable semantics")
            return self

        if self.operation is None or self.output is None or self.evidence_topology is None:
            raise ValueError("executable query requires operation, output, and evidence topology")
        if not self.requirements or not any(item.required for item in self.requirements):
            raise ValueError("executable query requires at least one required Evidence role")
        if self.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL:
            if self.operation != QueryOperation.LOOKUP:
                raise ValueError("BEST_EFFORT_RECALL is limited to non-operator lookup")
            if set(self.proof_obligations) != {ProofObligation.GROUNDED_RELATION}:
                raise ValueError(
                    "BEST_EFFORT_RECALL requires grounded relation validation without strict proof"
                )

        requirement_ids = [item.requirement_id for item in self.requirements]
        role_keys = [item.role_key for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement identities must be unique")
        if len(role_keys) != len(set(role_keys)):
            raise ValueError("requirement role keys must be unique")
        hint_ids = [item.requirement_id for item in self.retrieval_hints]
        if len(hint_ids) != len(set(hint_ids)) or not set(hint_ids).issubset(requirement_ids):
            raise ValueError("retrieval hints must uniquely address existing requirements")
        temporal_refs = {
            ref
            for item in self.requirements
            for ref in item.temporal.related_requirement_ids
        }
        if not temporal_refs.issubset(requirement_ids):
            raise ValueError("temporal relations must reference existing requirements")
        operand_ids = [item.operand_id for item in self.operator_operands]
        if len(operand_ids) != len(set(operand_ids)):
            raise ValueError("operator operand identities must be unique")
        operand_requirement_ids = {
            item.requirement_id
            for item in self.operator_operands
            if isinstance(item, RequirementBindingOperandV01)
        }
        if not operand_requirement_ids.issubset(requirement_ids):
            raise ValueError("operator operands must reference existing requirements")

        self._validate_operation_shape()
        return self

    def _validate_operation_shape(self) -> None:
        operation = self.operation
        output = self.output
        evidence_topology = self.evidence_topology
        if operation is None or output is None or evidence_topology is None:
            return

        if (
            operation == QueryOperation.LOOKUP
            and ProofObligation.GROUNDED_RELATION not in self.proof_obligations
        ):
            raise ValueError("LOOKUP requires grounded relation validation")

        if operation == QueryOperation.COUNT:
            if output.shape != OutputShape.SCALAR or output.value_type != OutputValueType.INTEGER:
                raise ValueError("COUNT requires a scalar integer output")
            scalar_fact = any(
                item.required and item.collection.kind == CollectionKind.SCALAR_FACT
                for item in self.requirements
            )
            member_set = any(
                item.required and item.collection.kind == CollectionKind.MEMBER_SET
                for item in self.requirements
            )
            if scalar_fact == member_set:
                raise ValueError("COUNT must select exactly one scalar-fact or member-set meaning")
            if scalar_fact and evidence_topology != EvidenceTopology.SINGLE_ITEM:
                raise ValueError("scalar count fact requires SINGLE_ITEM topology")
            if member_set:
                if evidence_topology != EvidenceTopology.MEMBER_SET:
                    raise ValueError("member count requires MEMBER_SET topology")
                if ProofObligation.IDENTITY_DEDUP not in self.proof_obligations:
                    raise ValueError("member count requires identity/dedup proof")
                if not {
                    ProofObligation.RANGE_CLOSURE,
                    ProofObligation.PARTITION_CLOSURE,
                }.intersection(self.proof_obligations):
                    raise ValueError("member count requires a closed range or source partition")

        if operation == QueryOperation.COLLECT_SET:
            if evidence_topology != EvidenceTopology.MEMBER_SET:
                raise ValueError("COLLECT_SET requires MEMBER_SET topology")
            if output.shape not in {OutputShape.LIST, OutputShape.ORDERED_LIST}:
                raise ValueError("COLLECT_SET requires a list output")
        if operation == QueryOperation.DIVIDE:
            self._require_roles(EvidenceRole.NUMERATOR, EvidenceRole.DENOMINATOR)
        if operation == QueryOperation.COMPARE:
            self._require_roles(EvidenceRole.LEFT_OPERAND, EvidenceRole.RIGHT_OPERAND)
        if operation == QueryOperation.TEMPORAL_ORDER:
            event_count = sum(
                item.required and item.evidence_role == EvidenceRole.EVENT
                for item in self.requirements
            )
            if evidence_topology != EvidenceTopology.MULTI_OPERAND or event_count < 2:
                raise ValueError(f"{operation} requires two event operands")
        if operation == QueryOperation.TEMPORAL_DISTANCE:
            self._validate_temporal_distance_operands()
        elif self.operator_operands:
            raise ValueError("typed operator operands are not defined for this operation")
        if (
            operation == QueryOperation.MULTI_JOIN
            and evidence_topology != EvidenceTopology.MULTI_OPERAND
        ):
            raise ValueError("MULTI_JOIN requires MULTI_OPERAND topology")
        if operation == QueryOperation.VERSION_DIFF:
            if evidence_topology != EvidenceTopology.VERSION_CHAIN:
                raise ValueError("VERSION_DIFF requires VERSION_CHAIN topology")
            self._require_roles(
                EvidenceRole.PRIOR_STATE,
                EvidenceRole.CURRENT_STATE,
                EvidenceRole.TRANSITION,
            )
            if ProofObligation.VERSION_CHAIN not in self.proof_obligations:
                raise ValueError("VERSION_DIFF requires version-chain proof")
        if self.evidence_topology == EvidenceTopology.CONFLICT_SET:
            if not any(
                item.required and item.evidence_role == EvidenceRole.CONFLICT_SIDE
                for item in self.requirements
            ):
                raise ValueError("CONFLICT_SET requires conflict-side Evidence")
            if ProofObligation.CONFLICT_RESOLUTION not in self.proof_obligations:
                raise ValueError("CONFLICT_SET requires conflict-resolution proof")

    def _validate_temporal_distance_operands(self) -> None:
        if self.evidence_topology != EvidenceTopology.MULTI_OPERAND:
            raise ValueError("TEMPORAL_DISTANCE requires MULTI_OPERAND topology")
        if len(self.operator_operands) != 2:
            raise ValueError("TEMPORAL_DISTANCE requires exactly two typed operands")

        requirements = {item.requirement_id: item for item in self.requirements}
        binding_operands = [
            item
            for item in self.operator_operands
            if isinstance(item, RequirementBindingOperandV01)
        ]
        reference_operands = [
            item
            for item in self.operator_operands
            if isinstance(item, QueryReferenceTimeOperandV01)
        ]
        if len(binding_operands) not in {1, 2} or len(reference_operands) not in {0, 1}:
            raise ValueError(
                "TEMPORAL_DISTANCE supports event-to-event or event-to-query-reference"
            )
        if len(binding_operands) + len(reference_operands) != 2:
            raise ValueError("TEMPORAL_DISTANCE operand sources do not form a binary operation")
        if any(
            not requirements[item.requirement_id].required
            or requirements[item.requirement_id].evidence_role != EvidenceRole.EVENT
            for item in binding_operands
        ):
            raise ValueError("TEMPORAL_DISTANCE Binding operands must reference required events")

    def _require_roles(self, *roles: EvidenceRole) -> None:
        present = {item.evidence_role for item in self.requirements if item.required}
        missing = set(roles).difference(present)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"{self.operation} is missing required Evidence roles: {names}")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def contract_digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


__all__ = [
    "CollectionClosureBasis",
    "CollectionContractV01",
    "CollectionKind",
    "EvidenceRole",
    "EvidenceSpeaker",
    "EvidenceTopology",
    "OperatorOperandV01",
    "OutputContractV01",
    "OutputShape",
    "OutputValueType",
    "ParseDisposition",
    "ParticipantConstraintV01",
    "ParticipantRole",
    "ProofObligation",
    "QueryOperation",
    "QueryReferenceTimeOperandV01",
    "QueryTaskContractV01",
    "RequirementBindingOperandV01",
    "RequirementValueType",
    "RetrievalHintsV01",
    "SourceConstraintProvenance",
    "SourceContractV01",
    "SubjectContractV01",
    "TemporalAxis",
    "TemporalBoundary",
    "TemporalContractV01",
    "TemporalKind",
    "TypedRequirementV01",
    "ValueContractV01",
]
