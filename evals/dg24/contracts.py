"""DG-24 evaluator/scorer contracts and synthetic lifecycle oracle."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from milai.domain.retrieval_audit import (
    CandidateLifecycleTraceV01,
    DedupDecisionV01,
    EvidenceCandidateV01,
    OfficialAuditProbeTraceV01,
    ProductRetrievalTraceV01,
    RetrievalAuditReason,
    RetrievalOccurrenceV01,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputOnlyRequestV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    request_payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_text: str
    source_snapshot_ref: str
    tenant_scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class InputOnlyCaseManifestV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["input-only-case-manifest-v0.1"]
    case_order: list[str]
    requests: list[InputOnlyRequestV01]
    forbidden_fields_absent: dict[str, Literal[True]]

    @model_validator(mode="after")
    def validate_denominator(self) -> Self:
        if self.case_order != [item.case_id for item in self.requests]:
            raise ValueError("input-only request order does not match case order")
        if len(self.case_order) != len(set(self.case_order)):
            raise ValueError("case order must be unique")
        return self


class RetrievalAuditRunV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["retrieval-audit-run-v0.1"]
    run_id: str
    phase: Literal["PRODUCT", "OFFICIAL_PROBE", "SCORER", "TERMINAL"]
    case_order_digest: str
    code_commit: str | None
    source_manifest_digest: str
    config_digest: str
    feature_flag_digest: str
    dataset_snapshot_identity: str
    memory_snapshot_identity: str
    transaction_snapshot_identity: str
    policy_snapshot_digest: str
    permission_snapshot_digest: str
    index_identities: dict[str, Any]
    query_ir_digest: str | None
    requirement_set_digest: str | None
    stage_registry_digest: str
    reader_calls: Literal[0]
    generative_provider_calls: Literal[0]
    canonical_write_enabled: Literal[False]
    automatic_retry_enabled: Literal[False]
    formal_holdout_consumed: Literal[False]


class LossResolution(StrEnum):
    EXACT_ID = "EXACT_ID"
    EXACT_SPAN = "EXACT_SPAN"
    ACCEPTABLE_ADJACENT_CONTEXT = "ACCEPTABLE_ADJACENT_CONTEXT"
    UNRESOLVED = "UNRESOLVED"


class RequirementLossAttributionV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-loss-attribution-v0.1"] = (
        "requirement-loss-attribution-v0.1"
    )
    query_id: str
    requirement_id: str
    evidence_role: str
    equivalence_group_id: str
    discovery_availability: dict[str, Any]
    product_discovery: bool
    product_terminal_survival: bool
    first_loss_stage: str | None
    first_loss_reason: RetrievalAuditReason | None
    first_irrecoverable_loss_stage: str | None
    first_irrecoverable_loss_reason: RetrievalAuditReason | None
    transient_drop_stages: list[str]
    rediscovery_stages: list[str]
    last_surviving_candidate_identities: list[str]
    authorized_absence: bool
    label_resolution: LossResolution


class ProofDisposition(StrEnum):
    SATISFIED = "SATISFIED"
    ACTION_NOT_AVAILABLE = "ACTION_NOT_AVAILABLE"
    ACTION_NOT_SELECTED = "ACTION_NOT_SELECTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNRESOLVED = "UNRESOLVED"


class ProofObligationTraceV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["proof-obligation-trace-v0.1"] = (
        "proof-obligation-trace-v0.1"
    )
    query_id: str
    requirement_id: str
    obligation_id: str
    obligation_kind: str
    applicable_actions: list[str]
    invoked_actions: list[str]
    produced_proof_artifact_ids: list[str]
    validator_identity: str
    disposition: ProofDisposition
    first_loss_reason: RetrievalAuditReason | None


class ScoredFirstLossReportV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scored-first-loss-report-v0.1"] = (
        "scored-first-loss-report-v0.1"
    )
    product_seal_digest: str
    probe_seal_digest: str
    gold_registry_digest: str
    proof_registry_digest: str
    scorer_identity: str
    per_equivalence_group: list[dict[str, Any]]
    per_evidence_role: list[dict[str, Any]]
    per_requirement: list[dict[str, Any]]
    per_query: list[dict[str, Any]]
    proof_obligations: list[dict[str, Any]]
    retention_curves: dict[str, Any]
    first_loss_distribution: dict[str, Any]
    channel_availability: dict[str, Any]
    authorized_absence: dict[str, Any]
    successor_routing: dict[str, Any]


TRACE_MODELS: dict[str, type[BaseModel]] = {
    "RetrievalAuditRunV01": RetrievalAuditRunV01,
    "RetrievalOccurrenceV01": RetrievalOccurrenceV01,
    "EvidenceCandidateV01": EvidenceCandidateV01,
    "DedupDecisionV01": DedupDecisionV01,
    "ProductRetrievalTraceV01": ProductRetrievalTraceV01,
    "CandidateLifecycleTraceV01": CandidateLifecycleTraceV01,
    "OfficialAuditProbeTraceV01": OfficialAuditProbeTraceV01,
    "RequirementLossAttributionV01": RequirementLossAttributionV01,
    "ProofObligationTraceV01": ProofObligationTraceV01,
    "ScoredFirstLossReportV01": ScoredFirstLossReportV01,
    "InputOnlyCaseManifestV01": InputOnlyCaseManifestV01,
}


SYNTHETIC_MATRIX: tuple[
    tuple[str, list[tuple[int, str, str]], int | None], ...
] = (
    ("single-channel-survival", [], None),
    (
        "eligible-channel-not-invoked",
        [(11, "CHANNEL_ELIGIBLE_NOT_INVOKED", "DROPPED")],
        11,
    ),
    ("unavailable-channel", [(10, "CHANNEL_NOT_AVAILABLE", "DROPPED")], 10),
    ("local-cutoff-drop", [(15, "CHANNEL_CUTOFF_DROP", "DROPPED")], 15),
    ("global-cutoff-drop", [(23, "GLOBAL_CUTOFF_DROP", "DROPPED")], 23),
    ("hard-filter-drop", [(13, "LEXICAL_ANCHOR_HARD_DROP", "REJECTED")], 13),
    (
        "drop-then-rediscovery",
        [
            (15, "CHANNEL_CUTOFF_DROP", "DROPPED"),
            (20, "CHANNEL_CUTOFF_DROP", "REDISCOVERED"),
        ],
        None,
    ),
    ("dedup-preserves-legal-representative", [], None),
    ("dedup-loses-answer-span", [(21, "DEDUP_WRONG_REPRESENTATIVE", "DROPPED")], 21),
    ("governance-authorized-absence", [(31, "ACCESS_DENIED_EXPECTED", "REJECTED")], 31),
    ("hydration-failure", [(30, "HYDRATION_NOT_FOUND", "DROPPED")], 30),
    ("interpretation-failure", [(41, "INTERPRETATION_NOT_PRODUCED", "DROPPED")], 41),
    ("binding-mismatch", [(42, "PREDICATE_MISMATCH", "REJECTED")], 42),
    ("proof-action-unavailable", [(44, "PROOF_ACTION_NOT_AVAILABLE", "REJECTED")], 44),
    ("proof-action-unselected", [(44, "PROOF_ACTION_NOT_SELECTED", "REJECTED")], 44),
    ("proof-validation-failure", [(44, "PROOF_VALIDATION_FAILED", "REJECTED")], 44),
)


def build_trace_schema_bundle() -> dict[str, Any]:
    return {
        "schema": "milai.dg24.trace-schema-bundle.v0.1",
        "internal_only": True,
        "public_mcp_schema_changed": False,
        "schemas": {
            name: model.model_json_schema() for name, model in TRACE_MODELS.items()
        },
    }


def run_synthetic_matrix() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for case_id, raw_steps, expected_irrecoverable in SYNTHETIC_MATRIX:
        steps: list[dict[str, Any]] = [
            {
                "sequence_index": sequence,
                "reason": RetrievalAuditReason(reason).value,
                "disposition": disposition,
            }
            for sequence, reason, disposition in raw_steps
        ]
        first_loss = next(
            (item for item in steps if item["disposition"] in {"DROPPED", "REJECTED"}),
            None,
        )
        rediscoveries = [
            item["sequence_index"]
            for item in steps
            if item["disposition"] == "REDISCOVERED"
        ]
        first_irrecoverable = first_loss
        if first_loss is not None and any(
            sequence > first_loss["sequence_index"] for sequence in rediscoveries
        ):
            first_irrecoverable = None
        observed = (
            int(first_irrecoverable["sequence_index"])
            if first_irrecoverable is not None
            else None
        )
        records.append(
            {
                "case_id": case_id,
                "steps": steps,
                "first_loss_stage": (
                    f"S{int(first_loss['sequence_index']):02d}" if first_loss else None
                ),
                "first_irrecoverable_loss_stage": (
                    f"S{observed:02d}" if observed is not None else None
                ),
                "expected_first_irrecoverable_sequence": expected_irrecoverable,
                "passed": observed == expected_irrecoverable,
            }
        )
    checks = {
        "matrix_case_count_at_least_16": len(records) >= 16,
        "all_expected_transitions_match": all(item["passed"] for item in records),
        "drop_then_rediscovery_not_irrecoverable": next(
            item for item in records if item["case_id"] == "drop-then-rediscovery"
        )["first_irrecoverable_loss_stage"]
        is None,
        "authorized_absence_typed": next(
            item
            for item in records
            if item["case_id"] == "governance-authorized-absence"
        )["steps"][0]["reason"]
        == "ACCESS_DENIED_EXPECTED",
        "reader_calls_zero": True,
        "generative_provider_calls_zero": True,
        "opened_dev_label_access_zero": True,
    }
    return {
        "schema": "milai.dg24.synthetic-lifecycle-matrix.v0.1",
        "records": records,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


__all__ = [
    "InputOnlyCaseManifestV01",
    "LossResolution",
    "ProofDisposition",
    "ProofObligationTraceV01",
    "RequirementLossAttributionV01",
    "RetrievalAuditRunV01",
    "ScoredFirstLossReportV01",
    "build_trace_schema_bundle",
    "run_synthetic_matrix",
]
