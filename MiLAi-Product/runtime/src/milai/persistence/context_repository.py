from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.application.errors import ContextOperationError
from milai.persistence import Database, SessionContext

_SAFE_CONTEXT_CODES = {
    "CHAT_LINEAGE_INVALID",
    "CONTEXT_BUDGET_INFEASIBLE",
    "CONTEXT_DEPENDENCY_ADVANCED",
    "CONTEXT_ISSUE_OMITTED",
    "CONTEXT_POINTER_INVALID",
    "CONTEXT_POINTER_NOT_FOUND",
    "INVALID_CHAT_TURN",
    "INVALID_CONTEXT_CAPSULE",
    "INVALID_TASK_FREE_CONTEXT_CAPSULE",
    "LIVE_CONFIRMATION_REQUIRED",
    "RETRIEVAL_TRACE_NOT_FOUND",
}


@dataclass(frozen=True, slots=True)
class ContextMaterial:
    retrieval_trace_id: UUID
    claims: list[dict[str, Any]]
    open_issues: list[dict[str, Any]]
    evidence: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ContextValidationSnapshot:
    canonical_position: int
    open_issues: list[dict[str, Any]]
    capsule_status: str | None
    capsule_expires_at: datetime | None
    capsule_content_hash: str | None


@dataclass(frozen=True, slots=True)
class TaskFreeCapsuleValidation:
    valid: bool
    reason: str
    sections: dict[str, Any] | None = None
    capsule_id: UUID | None = None
    content_hash: str | None = None
    retrieval_trace_id: UUID | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    canonical_position: int | None = None
    gate_outcomes: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class RecordChatCommand:
    request_id: str
    query_fingerprint: str
    capsule_id: UUID | None
    retrieval_trace_id: UUID | None
    answer_text: str
    claim_version_ids: list[str]
    evidence_refs: list[str]
    issue_refs: list[str]
    action_sensitive: bool
    live_confirmation: bool
    abstention_reason: str | None
    duration_ms: int


class ContextRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def material(self, context: SessionContext, trace_id: UUID) -> ContextMaterial:
        with self._database.connection(
            context, read_only=True, isolation_level="REPEATABLE READ"
        ) as connection:
            trace = connection.execute(
                """
                SELECT accepted_candidates, requested_scope
                FROM milai.retrieval_trace
                WHERE tenant_id = %s AND trace_id = %s
                """,
                (context.tenant_id, trace_id),
            ).fetchone()
            if trace is None:
                raise ContextOperationError("RETRIEVAL_TRACE_NOT_FOUND")
            accepted = _array_of_objects(trace[0], "retrieval trace candidates")
            requested_scope = trace[1] if isinstance(trace[1], dict) else {}
            version_ids = [UUID(str(item["claim_version_id"])) for item in accepted]
            gate_row = connection.execute(
                "SELECT milai.evaluate_retrieval_trace_candidates(%s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    version_ids,
                    trace_id,
                ),
            ).fetchone()
            outcomes = _array_of_objects(
                gate_row[0] if gate_row is not None else None, "canonical gate"
            )
            if any(outcome.get("accepted") is not True for outcome in outcomes):
                raise ContextOperationError("CONTEXT_POINTER_INVALID")

            claim_rows = connection.execute(
                """
                SELECT version.claim_version_id, claim.claim_id,
                       claim.subject_id, claim.predicate, claim.claim_type,
                       version.payload, version.scope_predicate,
                       version.valid_time_from, version.valid_time_to,
                       version.authority, version.confidence,
                       version.canonical_commit_seq
                FROM milai.claim_version version
                JOIN milai.claim claim
                  ON claim.tenant_id = version.tenant_id
                 AND claim.claim_id = version.claim_id
                WHERE version.tenant_id = %s
                  AND version.claim_version_id = ANY(%s::uuid[])
                ORDER BY version.canonical_commit_seq, version.claim_version_id
                """,
                (context.tenant_id, version_ids),
            ).fetchall()
            selected_claim_ids = sorted({UUID(str(row[1])) for row in claim_rows}, key=str)
            issue_rows = connection.execute(
                """
                SELECT issue.issue_id, issue.target_claim_id, issue.status,
                       issue.issue_type, issue.revision, issue.required_authority,
                       issue.scope_predicate, issue.discharge_rule,
                       COALESCE(jsonb_agg(jsonb_build_object(
                         'relation_type', relation.relation_type,
                         'evidence_id', relation.evidence_id
                       ) ORDER BY relation.relation_type, relation.evidence_id)
                       FILTER (WHERE relation.relation_id IS NOT NULL), '[]'::jsonb)
                FROM milai.open_issue issue
                LEFT JOIN milai.grounding_relation relation
                  ON relation.tenant_id = issue.tenant_id
                 AND relation.open_issue_id = issue.issue_id
                WHERE issue.tenant_id = %s
                  AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
                  AND (
                    issue.target_claim_id = ANY(%s::uuid[])
                    OR issue.scope_predicate = '{}'::jsonb
                    OR issue.scope_predicate <@ %s::jsonb
                    OR issue.scope_predicate @> %s::jsonb
                  )
                GROUP BY issue.tenant_id, issue.issue_id
                ORDER BY issue.created_at, issue.issue_id
                """,
                (
                    context.tenant_id,
                    selected_claim_ids,
                    Jsonb(requested_scope),
                    Jsonb(requested_scope),
                ),
            ).fetchall()
            evidence_ids = sorted(
                {
                    UUID(str(evidence_id))
                    for outcome in outcomes
                    for evidence_id in outcome.get("evidence_ids", [])
                },
                key=str,
            )
            evidence_rows = connection.execute(
                """
                SELECT evidence.evidence_id, blob.content_hash,
                       blob.byte_length, blob.media_type,
                       evidence.permission_snapshot, evidence.retention_state,
                       evidence.source_type, evidence.source_ref,
                       evidence.observed_at
                FROM milai.evidence_record evidence
                JOIN milai.content_blob blob
                  ON blob.tenant_id = evidence.tenant_id
                 AND blob.blob_id = evidence.blob_id
                WHERE evidence.tenant_id = %s
                  AND evidence.evidence_id = ANY(%s::uuid[])
                  AND evidence.revoked_at IS NULL
                  AND evidence.retention_state = 'READABLE'
                  AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
                ORDER BY evidence.evidence_id
                """,
                (context.tenant_id, evidence_ids),
            ).fetchall()
        if len(evidence_rows) != len(evidence_ids):
            raise ContextOperationError("CONTEXT_POINTER_INVALID")
        claim_keys = (
            "claim_version_id",
            "claim_id",
            "subject_id",
            "predicate",
            "claim_type",
            "payload",
            "scope_predicate",
            "valid_time_from",
            "valid_time_to",
            "authority",
            "confidence",
            "canonical_commit_seq",
        )
        issue_keys = (
            "issue_id",
            "target_claim_id",
            "status",
            "issue_type",
            "revision",
            "required_authority",
            "scope_predicate",
            "discharge_rule",
            "branches",
        )
        evidence_keys = (
            "evidence_id",
            "content_hash",
            "byte_length",
            "media_type",
            "permission_snapshot",
            "retention_state",
            "source_type",
            "source_ref",
            "observed_at",
        )
        return ContextMaterial(
            retrieval_trace_id=trace_id,
            claims=[_json_safe(dict(zip(claim_keys, row, strict=True))) for row in claim_rows],
            open_issues=[_json_safe(dict(zip(issue_keys, row, strict=True))) for row in issue_rows],
            evidence=[
                _json_safe(dict(zip(evidence_keys, row, strict=True))) for row in evidence_rows
            ],
        )

    def validation_snapshot(
        self,
        context: SessionContext,
        issue_ids: list[UUID],
        capsule_id: UUID,
    ) -> ContextValidationSnapshot:
        """Read capsule lifecycle and canonical dependencies in one snapshot."""
        with self._database.connection(
            context, read_only=True, isolation_level="REPEATABLE READ"
        ) as connection:
            capsule_row = connection.execute(
                """
                SELECT status, expires_at, content_hash
                FROM milai.context_capsule
                WHERE tenant_id = %s AND capsule_id = %s
                  AND created_by_actor_id = %s
                """,
                (context.tenant_id, capsule_id, context.actor_id),
            ).fetchone()
            state_row = connection.execute(
                "SELECT milai.retrieval_projection_state(%s, %s)",
                (context.tenant_id, context.actor_id),
            ).fetchone()
            if state_row is None or not isinstance(state_row[0], dict):
                raise RuntimeError("retrieval projection state returned no object")
            rows = connection.execute(
                """
                SELECT issue.issue_id, issue.target_claim_id, issue.status,
                       issue.issue_type, issue.revision, issue.required_authority,
                       issue.scope_predicate, issue.discharge_rule,
                       COALESCE(jsonb_agg(jsonb_build_object(
                         'relation_type', relation.relation_type,
                         'evidence_id', relation.evidence_id
                       ) ORDER BY relation.relation_type, relation.evidence_id)
                       FILTER (WHERE relation.relation_id IS NOT NULL), '[]'::jsonb)
                FROM milai.open_issue issue
                LEFT JOIN milai.grounding_relation relation
                  ON relation.tenant_id = issue.tenant_id
                 AND relation.open_issue_id = issue.issue_id
                WHERE issue.tenant_id = %s
                  AND issue.issue_id = ANY(%s::uuid[])
                  AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
                GROUP BY issue.tenant_id, issue.issue_id
                ORDER BY issue.issue_id
                """,
                (context.tenant_id, issue_ids),
            ).fetchall()
        issue_keys = (
            "issue_id",
            "target_claim_id",
            "status",
            "issue_type",
            "revision",
            "required_authority",
            "scope_predicate",
            "discharge_rule",
            "branches",
        )
        return ContextValidationSnapshot(
            canonical_position=int(state_row[0]["canonical_snapshot_outbox_sequence"]),
            open_issues=[_json_safe(dict(zip(issue_keys, row, strict=True))) for row in rows],
            capsule_status=str(capsule_row[0]) if capsule_row is not None else None,
            capsule_expires_at=(
                capsule_row[1]
                if capsule_row is not None and isinstance(capsule_row[1], datetime)
                else None
            ),
            capsule_content_hash=(str(capsule_row[2]) if capsule_row is not None else None),
        )

    def create_capsule(
        self,
        context: SessionContext,
        trace_id: UUID,
        sections: dict[str, object],
        byte_budget: int,
        expires_at: datetime,
    ) -> dict[str, Any]:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    "SELECT milai.create_context_capsule(%s, %s, %s, %s, %s, %s)",
                    (
                        context.tenant_id,
                        context.actor_id,
                        trace_id,
                        Jsonb(sections),
                        byte_budget,
                        expires_at,
                    ),
                ).fetchone()
        except Error as exc:
            _raise_context_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("context capsule procedure returned no object")
        return _json_safe(row[0])

    def task_free_evidence(
        self,
        context: SessionContext,
        evidence_ids: list[UUID],
    ) -> list[dict[str, str]]:
        unique_ids = sorted(set(evidence_ids), key=str)
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT evidence.evidence_id, blob.content_hash
                FROM milai.evidence_record evidence
                JOIN milai.content_blob blob
                  ON blob.tenant_id = evidence.tenant_id
                 AND blob.blob_id = evidence.blob_id
                WHERE evidence.tenant_id = %s
                  AND evidence.evidence_id = ANY(%s::uuid[])
                  AND evidence.revoked_at IS NULL
                  AND evidence.retention_state = 'READABLE'
                  AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
                  AND blob.physical_delete_state = 'PRESENT'
                ORDER BY evidence.evidence_id
                """,
                (context.tenant_id, unique_ids),
            ).fetchall()
        if len(rows) != len(unique_ids):
            raise ContextOperationError("CONTEXT_POINTER_INVALID")
        return [
            {"evidence_id": str(row[0]), "content_hash": str(row[1])}
            for row in rows
        ]

    def create_task_free_capsule(
        self,
        context: SessionContext,
        trace_id: UUID,
        sections: dict[str, object],
        byte_budget: int,
        expires_at: datetime,
    ) -> dict[str, Any]:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    "SELECT milai.create_task_free_context_capsule(%s, %s, %s, %s, %s, %s)",
                    (
                        context.tenant_id,
                        context.actor_id,
                        trace_id,
                        Jsonb(sections),
                        byte_budget,
                        expires_at,
                    ),
                ).fetchone()
        except Error as exc:
            _raise_context_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("task-free context capsule procedure returned no object")
        return _json_safe(row[0])

    def validate_task_free_capsule(
        self,
        context: SessionContext,
        capsule_id: UUID,
        *,
        expected_coverage: dict[str, object],
        requested_scope: dict[str, object],
        required_authority: str,
        required_freshness: str,
        valid_at: datetime,
        known_at: datetime,
        historical: bool,
    ) -> TaskFreeCapsuleValidation:
        """Reauthorize and validate a receipt in one canonical read snapshot."""
        with self._database.connection(
            context, read_only=True, isolation_level="REPEATABLE READ"
        ) as connection:
            row = connection.execute(
                """
                SELECT capsule_id, status, protected_sections, content_hash,
                       retrieval_trace_id, expires_at, created_at
                FROM milai.context_capsule
                WHERE tenant_id = %s AND capsule_id = %s
                  AND created_by_actor_id = %s
                """,
                (context.tenant_id, capsule_id, context.actor_id),
            ).fetchone()
            if row is None:
                return TaskFreeCapsuleValidation(False, "RECEIPT_NOT_FOUND_OR_NOT_OWNED")
            raw_sections = row[2]
            if not isinstance(raw_sections, dict):
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            sections = dict(raw_sections)
            if set(sections) != {
                "MEMORY STATE VIEW",
                "OPEN ISSUE IDS",
                "RETRIEVED EVIDENCE",
                "TRACE POINTERS",
                "RECEIPT METADATA",
            }:
                return TaskFreeCapsuleValidation(False, "RECEIPT_NOT_TASK_FREE")
            metadata = sections.get("RECEIPT METADATA")
            if not isinstance(metadata, dict) or metadata.get("schema_version") != (
                "context-receipt-v0.1"
            ):
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            if metadata.get("requirement_coverage") != expected_coverage:
                return TaskFreeCapsuleValidation(False, "RECEIPT_COVERAGE_MISS")
            status = str(row[1])
            expires_at = row[5]
            issued_at = row[6]
            now = datetime.now(UTC)
            if status != "ACTIVE":
                return TaskFreeCapsuleValidation(False, "RECEIPT_INVALIDATED")
            if not isinstance(expires_at, datetime) or expires_at <= now:
                return TaskFreeCapsuleValidation(False, "RECEIPT_EXPIRED")

            projection_row = connection.execute(
                "SELECT milai.retrieval_projection_state(%s, %s)",
                (context.tenant_id, context.actor_id),
            ).fetchone()
            projection = projection_row[0] if projection_row is not None else None
            if not isinstance(projection, dict):
                raise RuntimeError("retrieval projection state returned no object")
            canonical_position = int(projection["canonical_snapshot_outbox_sequence"])
            stored_position = metadata.get("canonical_position")
            stored_invalidation = metadata.get("invalidation_sequence")
            if (
                isinstance(stored_position, bool)
                or not isinstance(stored_position, int)
                or stored_position != canonical_position
                or stored_invalidation != stored_position
            ):
                return TaskFreeCapsuleValidation(
                    False, "RECEIPT_CANONICAL_POSITION_CHANGED"
                )

            state_view = sections.get("MEMORY STATE VIEW")
            items = state_view.get("items") if isinstance(state_view, dict) else None
            if not isinstance(items, list) or not items:
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            try:
                version_ids = sorted(
                    {
                        UUID(str(item["claim_version_id"]))
                        for item in items
                        if isinstance(item, dict)
                    },
                    key=str,
                )
            except (KeyError, TypeError, ValueError):
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            if len(version_ids) != len(items):
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            gate_row = connection.execute(
                """
                SELECT milai.evaluate_canonical_candidates(
                  %s, %s, %s::uuid[], %s, %s, %s,
                  'ACTIVE', ARRAY['VERIFIED', 'PROVISIONAL']::text[],
                  %s, 0, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    version_ids,
                    required_authority,
                    Jsonb(requested_scope),
                    valid_at,
                    required_freshness,
                    known_at,
                    historical,
                ),
            ).fetchone()
            outcomes = _array_of_objects(
                gate_row[0] if gate_row is not None else None, "receipt canonical gate"
            )
            if len(outcomes) != len(version_ids) or any(
                outcome.get("accepted") is not True for outcome in outcomes
            ):
                return TaskFreeCapsuleValidation(
                    False,
                    "RECEIPT_DEPENDENCY_CHANGED",
                    gate_outcomes=tuple(outcomes),
                )

            gated_issue_ids = sorted(
                {
                    str(issue_id)
                    for outcome in outcomes
                    for issue_id in outcome.get("open_issue_ids", [])
                }
            )
            stored_issue_ids = sections.get("OPEN ISSUE IDS")
            if not isinstance(stored_issue_ids, list) or sorted(stored_issue_ids) != (
                gated_issue_ids
            ):
                return TaskFreeCapsuleValidation(False, "RECEIPT_OPEN_ISSUE_CHANGED")
            gated_evidence_ids = sorted(
                {
                    str(evidence_id)
                    for outcome in outcomes
                    for evidence_id in outcome.get("evidence_ids", [])
                }
            )
            stored_evidence = sections.get("RETRIEVED EVIDENCE")
            if not isinstance(stored_evidence, list):
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            try:
                pointer_ids = sorted(
                    {
                        UUID(str(item["pointer_id"]))
                        for item in stored_evidence
                        if isinstance(item, dict)
                    },
                    key=str,
                )
                stored_evidence_ids = sorted(
                    str(UUID(str(item["evidence_id"])))
                    for item in stored_evidence
                    if isinstance(item, dict)
                )
            except (KeyError, TypeError, ValueError):
                return TaskFreeCapsuleValidation(False, "RECEIPT_SHAPE_INVALID")
            if (
                len(pointer_ids) != len(stored_evidence)
                or stored_evidence_ids != gated_evidence_ids
            ):
                return TaskFreeCapsuleValidation(False, "RECEIPT_EVIDENCE_CHANGED")
            valid_pointer_rows = connection.execute(
                """
                SELECT pointer.pointer_id
                FROM milai.context_pointer pointer
                JOIN milai.evidence_record evidence
                  ON evidence.tenant_id = pointer.tenant_id
                 AND evidence.evidence_id = pointer.evidence_id
                JOIN milai.content_blob blob
                  ON blob.tenant_id = evidence.tenant_id
                 AND blob.blob_id = evidence.blob_id
                WHERE pointer.tenant_id = %s
                  AND pointer.capsule_id = %s
                  AND pointer.pointer_id = ANY(%s::uuid[])
                  AND pointer.state = 'ACTIVE'
                  AND evidence.revoked_at IS NULL
                  AND evidence.retention_state = 'READABLE'
                  AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
                  AND blob.physical_delete_state = 'PRESENT'
                  AND blob.content_hash = pointer.content_hash_snapshot
                  AND evidence.permission_snapshot = pointer.permission_snapshot
                  AND evidence.retention_state = pointer.retention_state_snapshot
                  AND pointer.pointer_hash = encode(sha256(convert_to(
                    evidence.evidence_id::text || ':' || blob.content_hash || ':' ||
                    evidence.permission_snapshot::text || ':' || evidence.retention_state,
                    'UTF8'
                  )), 'hex')
                ORDER BY pointer.pointer_id
                """,
                (context.tenant_id, capsule_id, pointer_ids),
            ).fetchall()
            if [UUID(str(pointer[0])) for pointer in valid_pointer_rows] != pointer_ids:
                return TaskFreeCapsuleValidation(False, "RECEIPT_POINTER_INVALID")

        return TaskFreeCapsuleValidation(
            True,
            "RECEIPT_REUSED",
            sections=sections,
            capsule_id=UUID(str(row[0])),
            content_hash=str(row[3]),
            retrieval_trace_id=UUID(str(row[4])),
            issued_at=issued_at,
            expires_at=expires_at,
            canonical_position=canonical_position,
            gate_outcomes=tuple(outcomes),
        )

    def get_capsule(self, context: SessionContext, capsule_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT capsule_id, status, protected_sections, content_hash,
                       retrieval_trace_id, byte_budget, byte_size, expires_at,
                       invalidated_at, invalidation_reason, created_at
                FROM milai.context_capsule
                WHERE tenant_id = %s AND capsule_id = %s
                """,
                (context.tenant_id, capsule_id),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "capsule_id",
            "status",
            "protected_sections",
            "content_hash",
            "retrieval_trace_id",
            "byte_budget",
            "byte_size",
            "expires_at",
            "invalidated_at",
            "invalidation_reason",
            "created_at",
        )
        return _json_safe(dict(zip(keys, row, strict=True)))

    def recover_pointer(self, context: SessionContext, pointer_id: UUID) -> dict[str, Any]:
        try:
            with self._database.connection(context, read_only=True) as connection:
                row = connection.execute(
                    "SELECT milai.recover_context_pointer(%s, %s, %s)",
                    (context.tenant_id, context.actor_id, pointer_id),
                ).fetchone()
        except Error as exc:
            _raise_context_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("context pointer procedure returned no object")
        return _json_safe(row[0])

    def record_chat(self, context: SessionContext, command: RecordChatCommand) -> UUID:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.record_chat_turn(
                      %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.request_id,
                        command.query_fingerprint,
                        command.capsule_id,
                        command.retrieval_trace_id,
                        command.answer_text,
                        Jsonb(command.claim_version_ids),
                        Jsonb(command.evidence_refs),
                        Jsonb(command.issue_refs),
                        command.action_sensitive,
                        command.live_confirmation,
                        command.abstention_reason,
                        command.duration_ms,
                    ),
                ).fetchone()
        except Error as exc:
            _raise_context_error(exc)
        if row is None:
            raise RuntimeError("chat trace procedure returned no id")
        return UUID(str(row[0]))

    def get_chat(self, context: SessionContext, chat_turn_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT chat_turn_id, request_id, query_fingerprint,
                       capsule_id, retrieval_trace_id, answer_text,
                       used_claim_version_ids, evidence_refs, open_issue_refs,
                       action_sensitive, live_confirmation, abstained,
                       abstention_reason, duration_ms, created_at
                FROM milai.chat_turn
                WHERE tenant_id = %s AND chat_turn_id = %s
                """,
                (context.tenant_id, chat_turn_id),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "chat_turn_id",
            "request_id",
            "query_fingerprint",
            "capsule_id",
            "retrieval_trace_id",
            "answer_text",
            "used_claim_version_ids",
            "evidence_refs",
            "open_issue_refs",
            "action_sensitive",
            "live_confirmation",
            "abstained",
            "abstention_reason",
            "duration_ms",
            "created_at",
        )
        return _json_safe(dict(zip(keys, row, strict=True)))


def _raise_context_error(error: Error) -> None:
    code = error.diag.message_primary
    if code not in _SAFE_CONTEXT_CODES:
        raise error
    raise ContextOperationError(code) from error


def _array_of_objects(value: object, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError(f"{source} returned a non-array result")
    return value


def _json_safe(values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if isinstance(value, UUID):
            values[key] = str(value)
        elif isinstance(value, datetime):
            values[key] = value.isoformat()
        elif isinstance(value, Decimal):
            values[key] = float(value)
    return values
