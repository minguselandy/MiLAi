from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.application.errors import CanonicalOperationError
from milai.persistence import Database, SessionContext

_SAFE_DATABASE_CODES = {
    "AUTHORITY_INSUFFICIENT",
    "GROUNDING_BLOCKED",
    "IDEMPOTENCY_CONFLICT",
    "INVALID_DECISION",
    "INVALID_PROPOSAL",
    "ISSUE_REVISION_CONFLICT",
    "OPERATION_NOT_ENABLED",
    "PROPOSAL_ALREADY_DECIDED",
    "PROPOSAL_NOT_FOUND",
    "SELF_REVIEW_FORBIDDEN",
    "TENANT_MISMATCH",
    "VERSION_CONFLICT",
}


@dataclass(frozen=True, slots=True)
class CreateProposalCommand:
    idempotency_key: str
    request_fingerprint: str
    target_claim_id: UUID | None
    operation: str
    expected_version_id: UUID | None
    proposed_patch: dict[str, object]
    supporting_evidence_refs: list[UUID]
    contradicting_evidence_refs: list[UUID]
    scope_predicate: dict[str, object]
    requested_authority: str
    derivation_policy_id: str
    model_id: str | None
    template_id: str | None
    derivation_snapshot: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReviewProposalCommand:
    proposal_id: UUID
    decision: str
    policy_version: str
    reason_code: str
    idempotency_key: str
    request_fingerprint: str


class CanonicalRepository:
    def __init__(self, database: Database, steward_database: Database) -> None:
        self._database = database
        self._steward_database = steward_database

    def create_proposal(
        self, context: SessionContext, command: CreateProposalCommand
    ) -> dict[str, Any]:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.create_operation_proposal(
                      %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.idempotency_key,
                        command.request_fingerprint,
                        command.target_claim_id,
                        command.operation,
                        command.expected_version_id,
                        Jsonb(command.proposed_patch),
                        command.supporting_evidence_refs,
                        command.contradicting_evidence_refs,
                        Jsonb(command.scope_predicate),
                        command.requested_authority,
                        command.derivation_policy_id,
                        command.model_id,
                        command.template_id,
                        Jsonb(command.derivation_snapshot),
                    ),
                ).fetchone()
        except Error as exc:
            _raise_canonical_error(exc)
        if row is None:
            raise RuntimeError("proposal procedure returned no result")
        return _procedure_result(row[0])

    def review_proposal(
        self, context: SessionContext, command: ReviewProposalCommand
    ) -> dict[str, Any]:
        try:
            with self._steward_database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.review_operation_proposal(
                      %s, %s, %s, %s, 'USER', %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.proposal_id,
                        command.decision,
                        command.policy_version,
                        command.reason_code,
                        command.idempotency_key,
                        command.request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            _raise_canonical_error(exc)
        if row is None:
            raise RuntimeError("review procedure returned no result")
        return _procedure_result(row[0])

    def get_proposal(self, context: SessionContext, proposal_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT proposal_id, target_claim_id, operation, expected_version_id,
                       proposed_patch, supporting_evidence_refs,
                       contradicting_evidence_refs, scope_predicate,
                       requested_authority, derivation_policy_id, model_id,
                       template_id, derivation_snapshot, proposer_actor_id,
                       status, created_at
                FROM milai.operation_proposal
                WHERE tenant_id = %s AND proposal_id = %s
                """,
                (context.tenant_id, proposal_id),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "proposal_id",
            "target_claim_id",
            "operation",
            "expected_version_id",
            "proposed_patch",
            "supporting_evidence_refs",
            "contradicting_evidence_refs",
            "scope_predicate",
            "requested_authority",
            "derivation_policy_id",
            "model_id",
            "template_id",
            "derivation_snapshot",
            "proposer_actor_id",
            "status",
            "created_at",
        )
        return _json_safe(dict(zip(keys, row, strict=True)))

    def list_proposals(
        self, context: SessionContext, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT proposal_id, target_claim_id, operation, expected_version_id,
                       proposed_patch, supporting_evidence_refs,
                       contradicting_evidence_refs, scope_predicate,
                       requested_authority, derivation_policy_id, model_id,
                       template_id, derivation_snapshot, proposer_actor_id,
                       status, created_at
                FROM milai.operation_proposal
                WHERE tenant_id = %s AND (%s::text IS NULL OR status = %s::text)
                ORDER BY created_at DESC, proposal_id
                LIMIT %s
                """,
                (context.tenant_id, status, status, limit),
            ).fetchall()
        keys = (
            "proposal_id",
            "target_claim_id",
            "operation",
            "expected_version_id",
            "proposed_patch",
            "supporting_evidence_refs",
            "contradicting_evidence_refs",
            "scope_predicate",
            "requested_authority",
            "derivation_policy_id",
            "model_id",
            "template_id",
            "derivation_snapshot",
            "proposer_actor_id",
            "status",
            "created_at",
        )
        return [_json_safe(dict(zip(keys, row, strict=True))) for row in rows]

    def get_claim(self, context: SessionContext, claim_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT claim_id, subject_id, predicate, claim_type,
                       claim_version_id, version_number, payload, scope_predicate,
                       valid_time_from, valid_time_to, system_time, lifecycle,
                       epistemic_status, freshness, authority, confidence,
                       canonical_commit_seq, has_live_grounding, has_live_block,
                       has_live_open_issue, effective_status
                FROM milai.effective_claim_state
                WHERE tenant_id = %s AND claim_id = %s AND is_current
                """,
                (context.tenant_id, claim_id),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "claim_id",
            "subject_id",
            "predicate",
            "claim_type",
            "claim_version_id",
            "version_number",
            "payload",
            "scope_predicate",
            "valid_time_from",
            "valid_time_to",
            "system_time",
            "lifecycle",
            "epistemic_status",
            "freshness",
            "authority",
            "confidence",
            "canonical_commit_seq",
            "has_live_grounding",
            "has_live_block",
            "has_live_open_issue",
            "effective_status",
        )
        return _json_safe(dict(zip(keys, row, strict=True)))

    def get_claim_versions(self, context: SessionContext, claim_id: UUID) -> list[dict[str, Any]]:
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT claim_version_id, version_number, payload, scope_predicate,
                       valid_time_from, valid_time_to, system_time, lifecycle,
                       epistemic_status, freshness, authority, confidence,
                       derivation_policy_id, model_id, template_id,
                       steward_decision_id, canonical_commit_seq
                FROM milai.claim_version
                WHERE tenant_id = %s AND claim_id = %s
                ORDER BY version_number
                """,
                (context.tenant_id, claim_id),
            ).fetchall()
        keys = (
            "claim_version_id",
            "version_number",
            "payload",
            "scope_predicate",
            "valid_time_from",
            "valid_time_to",
            "system_time",
            "lifecycle",
            "epistemic_status",
            "freshness",
            "authority",
            "confidence",
            "derivation_policy_id",
            "model_id",
            "template_id",
            "steward_decision_id",
            "canonical_commit_seq",
        )
        return [_json_safe(dict(zip(keys, row, strict=True))) for row in rows]

    def list_open_issues(self, context: SessionContext, status: str | None) -> list[dict[str, Any]]:
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT issue_id, target_claim_id, issue_type, status, revision,
                       scope_predicate, discharge_rule, required_authority,
                       created_from_proposal_id, resolved_by_decision_id,
                       resolved_at, created_at
                FROM milai.open_issue
                WHERE tenant_id = %s AND (%s::text IS NULL OR status = %s::text)
                ORDER BY created_at, issue_id
                """,
                (context.tenant_id, status, status),
            ).fetchall()
        return [_issue_row(row) for row in rows]

    def get_open_issue(self, context: SessionContext, issue_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT issue_id, target_claim_id, issue_type, status, revision,
                       scope_predicate, discharge_rule, required_authority,
                       created_from_proposal_id, resolved_by_decision_id,
                       resolved_at, created_at
                FROM milai.open_issue
                WHERE tenant_id = %s AND issue_id = %s
                """,
                (context.tenant_id, issue_id),
            ).fetchone()
            if row is None:
                return None
            branches = connection.execute(
                """
                SELECT relation_type, evidence_id
                FROM milai.grounding_relation
                WHERE tenant_id = %s AND open_issue_id = %s
                ORDER BY relation_type, evidence_id
                """,
                (context.tenant_id, issue_id),
            ).fetchall()
            transitions = connection.execute(
                """
                SELECT transition_id, from_status, to_status,
                       from_revision, to_revision, event_type, proposal_id,
                       decision_id, policy_version, canonical_commit_seq,
                       created_at, created_by_actor_id
                FROM milai.open_issue_transition
                WHERE tenant_id = %s AND issue_id = %s
                ORDER BY to_revision, created_at, transition_id
                """,
                (context.tenant_id, issue_id),
            ).fetchall()
        result = _issue_row(row)
        result["branches"] = [
            {"relation_type": relation_type, "evidence_id": str(evidence_id)}
            for relation_type, evidence_id in branches
        ]
        transition_keys = (
            "transition_id",
            "from_status",
            "to_status",
            "from_revision",
            "to_revision",
            "event_type",
            "proposal_id",
            "decision_id",
            "policy_version",
            "canonical_commit_seq",
            "created_at",
            "created_by_actor_id",
        )
        result["transitions"] = [
            _json_safe(dict(zip(transition_keys, transition, strict=True)))
            for transition in transitions
        ]
        return result


def _issue_row(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "issue_id",
        "target_claim_id",
        "issue_type",
        "status",
        "revision",
        "scope_predicate",
        "discharge_rule",
        "required_authority",
        "created_from_proposal_id",
        "resolved_by_decision_id",
        "resolved_at",
        "created_at",
    )
    return _json_safe(dict(zip(keys, row, strict=True)))


def _json_safe(values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if isinstance(value, (UUID, datetime)):
            values[key] = value.isoformat() if isinstance(value, datetime) else str(value)
        elif isinstance(value, Decimal):
            values[key] = float(value)
        elif isinstance(value, list):
            values[key] = [str(item) if isinstance(item, UUID) else item for item in value]
    return values


def _procedure_result(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("canonical procedure returned a non-object result")
    return value


def _raise_canonical_error(error: Error) -> None:
    code = error.diag.message_primary
    if code not in _SAFE_DATABASE_CODES:
        raise error
    raise CanonicalOperationError(code) from error
