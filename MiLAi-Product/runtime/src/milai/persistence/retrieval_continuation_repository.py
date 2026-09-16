from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.application.errors import RetrievalContinuationError
from milai.domain.retrieval_continuation import RetrievalContinuationState
from milai.persistence import Database, SessionContext


@dataclass(frozen=True, slots=True)
class RetrievalContinuationRootWrite:
    state_id: UUID
    query_digest: str
    request_digest: str
    snapshot_as_of: datetime
    canonical_position: int | None
    selected_evidence_ids: tuple[str, ...]
    seen_evidence_ids: tuple[str, ...]
    frontier_evidence_ids: tuple[str, ...]
    online_ineligible_count: int
    state_digest: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RetrievalContinuationSuccessorWrite:
    state_id: UUID
    predecessor_state_id: UUID
    operation_fingerprint: str
    selected_evidence_ids: tuple[str, ...]
    seen_evidence_ids: tuple[str, ...]
    frontier_evidence_ids: tuple[str, ...]
    discarded_evidence_ids: tuple[str, ...]
    online_ineligible_count: int
    state_digest: str


@dataclass(frozen=True, slots=True)
class RetrievalContinuationWriteResult:
    state: RetrievalContinuationState
    replayed: bool


class RetrievalContinuationRepository:
    """PostgreSQL boundary for immutable retrieval continuation pages."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_owned(
        self,
        context: SessionContext,
        state_id: UUID,
    ) -> RetrievalContinuationState | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT state_id, root_state_id, predecessor_state_id, generation,
                       payload_semantics_version, query_digest, request_digest, snapshot_as_of,
                       canonical_position, selected_evidence_ids,
                       seen_evidence_ids, frontier_evidence_ids,
                       online_ineligible_count, operation_fingerprint, state_digest,
                       created_at, expires_at
                FROM milai.retrieval_continuation_state
                WHERE tenant_id = %s
                  AND created_by_actor_id = %s
                  AND state_id = %s
                """,
                (context.tenant_id, context.actor_id, state_id),
            ).fetchone()
        return _state(row) if row is not None else None

    def create_root(
        self,
        context: SessionContext,
        command: RetrievalContinuationRootWrite,
    ) -> RetrievalContinuationWriteResult:
        payload = {
            "state_id": str(command.state_id),
            "query_digest": command.query_digest,
            "request_digest": command.request_digest,
            "snapshot_as_of": command.snapshot_as_of.isoformat(),
            "canonical_position": command.canonical_position,
            "selected_evidence_ids": list(command.selected_evidence_ids),
            "seen_evidence_ids": list(command.seen_evidence_ids),
            "frontier_evidence_ids": list(command.frontier_evidence_ids),
            "online_ineligible_count": command.online_ineligible_count,
            "state_digest": command.state_digest,
            "expires_at": command.expires_at.isoformat(),
        }
        return self._write(
            context,
            "SELECT milai.create_retrieval_continuation_root_v2(%s, %s, %s)",
            (context.tenant_id, context.actor_id, Jsonb(payload)),
        )

    def create_successor(
        self,
        context: SessionContext,
        command: RetrievalContinuationSuccessorWrite,
    ) -> RetrievalContinuationWriteResult:
        payload = {
            "state_id": str(command.state_id),
            "predecessor_state_id": str(command.predecessor_state_id),
            "operation_fingerprint": command.operation_fingerprint,
            "selected_evidence_ids": list(command.selected_evidence_ids),
            "seen_evidence_ids": list(command.seen_evidence_ids),
            "frontier_evidence_ids": list(command.frontier_evidence_ids),
            "discarded_evidence_ids": list(command.discarded_evidence_ids),
            "online_ineligible_count": command.online_ineligible_count,
            "state_digest": command.state_digest,
        }
        return self._write(
            context,
            "SELECT milai.create_retrieval_continuation_successor_v2(%s, %s, %s)",
            (context.tenant_id, context.actor_id, Jsonb(payload)),
        )

    def _write(
        self,
        context: SessionContext,
        statement: str,
        params: tuple[object, ...],
    ) -> RetrievalContinuationWriteResult:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(statement, params).fetchone()
        except Error as exc:
            code = exc.diag.message_primary or "RETRIEVAL_CONTINUATION_REJECTED"
            if code in {
                "GENERATION_LIMIT_REACHED",
                "INVALID_RETRIEVAL_CONTINUATION",
                "OPERATION_CONFLICT",
                "RETRIEVAL_CONTINUATION_EXPIRED",
                "RETRIEVAL_CONTINUATION_NOT_FOUND",
                "ROOT_STATE_LIMIT_REACHED",
                "STATE_SIZE_LIMIT_REACHED",
                "SUCCESSOR_LIMIT_REACHED",
                "TENANT_MISMATCH",
            }:
                raise RetrievalContinuationError(code) from exc
            raise
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("retrieval continuation procedure returned no result")
        response: dict[str, Any] = row[0]
        state = self.get_owned(context, UUID(str(response["state_id"])))
        if state is None:
            raise RuntimeError("persisted retrieval continuation is not readable")
        return RetrievalContinuationWriteResult(
            state=state,
            replayed=bool(response.get("replayed")),
        )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RuntimeError("retrieval continuation identity list is invalid")
    return tuple(str(item) for item in value)


def _state(row: tuple[Any, ...]) -> RetrievalContinuationState:
    return RetrievalContinuationState(
        state_id=UUID(str(row[0])),
        root_state_id=UUID(str(row[1])),
        predecessor_state_id=UUID(str(row[2])) if row[2] is not None else None,
        generation=int(row[3]),
        payload_semantics_version=str(row[4]),
        query_digest=str(row[5]),
        request_digest=str(row[6]),
        snapshot_as_of=row[7],
        canonical_position=int(row[8]) if row[8] is not None else None,
        selected_evidence_ids=_string_tuple(row[9]),
        seen_evidence_ids=_string_tuple(row[10]),
        frontier_evidence_ids=_string_tuple(row[11]),
        online_ineligible_count=int(row[12]),
        operation_fingerprint=str(row[13]) if row[13] is not None else None,
        state_digest=str(row[14]),
        created_at=row[15],
        expires_at=row[16],
    )


__all__ = [
    "RetrievalContinuationRepository",
    "RetrievalContinuationRootWrite",
    "RetrievalContinuationSuccessorWrite",
    "RetrievalContinuationWriteResult",
]
