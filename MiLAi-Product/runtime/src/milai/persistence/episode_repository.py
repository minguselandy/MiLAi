from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from psycopg import Error

from milai.application.errors import CanonicalOperationError
from milai.persistence import Database, SessionContext

_SAFE_DATABASE_CODES = {
    "EPISODE_NOT_FOUND",
    "EPISODE_REFERENCE_INVALID",
    "EPISODE_REVISION_CONFLICT",
    "IDEMPOTENCY_CONFLICT",
    "INVALID_EPISODE",
    "INVALID_SETTLEMENT",
    "SETTLEMENT_NOT_AUTHORIZED",
    "SETTLEMENT_REFERENCE_INVALID",
    "TENANT_MISMATCH",
}


@dataclass(frozen=True, slots=True)
class CreateEpisodeCommand:
    subject_id: str
    evidence_refs: list[UUID]
    chat_turn_refs: list[UUID]
    context_capsule_refs: list[UUID]
    idempotency_key: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class SettleEpisodeCommand:
    episode_id: UUID
    expected_revision: int
    residual_proposal_ids: list[UUID]
    open_issue_ids: list[UUID]
    confirmation: str
    idempotency_key: str
    request_fingerprint: str


class EpisodeRepository:
    def __init__(self, database: Database, steward_database: Database) -> None:
        self._database = database
        self._steward_database = steward_database

    def create(self, context: SessionContext, command: CreateEpisodeCommand) -> dict[str, Any]:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.create_episode(
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.subject_id,
                        command.evidence_refs,
                        command.chat_turn_refs,
                        command.context_capsule_refs,
                        command.idempotency_key,
                        command.request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            _raise_episode_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Episode capture returned a non-object result")
        return cast(dict[str, Any], _json_safe(row[0]))

    def settle(self, context: SessionContext, command: SettleEpisodeCommand) -> dict[str, Any]:
        try:
            with self._steward_database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.settle_episode(
                      %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.episode_id,
                        command.expected_revision,
                        command.residual_proposal_ids,
                        command.open_issue_ids,
                        command.confirmation,
                        command.idempotency_key,
                        command.request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            _raise_episode_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Episode settlement returned a non-object result")
        return cast(dict[str, Any], _json_safe(row[0]))

    def get(self, context: SessionContext, episode_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            episode = connection.execute(
                """
                SELECT episode_id, subject_id, status, revision, evidence_refs,
                       chat_turn_refs, context_capsule_refs, settled_at, created_at
                FROM milai.episode
                WHERE tenant_id = %s AND episode_id = %s
                """,
                (context.tenant_id, episode_id),
            ).fetchone()
            if episode is None:
                return None
            settlement = connection.execute(
                """
                SELECT settlement_id, from_revision, to_revision,
                       residual_proposal_ids, open_issue_ids,
                       expired_context_capsule_ids, created_at
                FROM milai.episode_settlement
                WHERE tenant_id = %s AND episode_id = %s
                """,
                (context.tenant_id, episode_id),
            ).fetchone()
            transitions = connection.execute(
                """
                SELECT transition_id, from_status, to_status, from_revision,
                       to_revision, event_type, settlement_id, created_at
                FROM milai.episode_transition
                WHERE tenant_id = %s AND episode_id = %s
                ORDER BY to_revision, created_at, transition_id
                """,
                (context.tenant_id, episode_id),
            ).fetchall()
        episode_keys = (
            "episode_id",
            "subject_id",
            "status",
            "revision",
            "evidence_refs",
            "chat_turn_refs",
            "context_capsule_refs",
            "settled_at",
            "created_at",
        )
        result = dict(zip(episode_keys, episode, strict=True))
        settlement_keys = (
            "settlement_id",
            "from_revision",
            "to_revision",
            "residual_proposal_ids",
            "open_issue_ids",
            "expired_context_capsule_ids",
            "created_at",
        )
        transition_keys = (
            "transition_id",
            "from_status",
            "to_status",
            "from_revision",
            "to_revision",
            "event_type",
            "settlement_id",
            "created_at",
        )
        result["settlement"] = (
            dict(zip(settlement_keys, settlement, strict=True)) if settlement else None
        )
        result["transitions"] = [
            dict(zip(transition_keys, transition, strict=True)) for transition in transitions
        ]
        return cast(dict[str, Any], _json_safe(result))


def _raise_episode_error(error: Error) -> None:
    code = error.diag.message_primary
    if code not in _SAFE_DATABASE_CODES:
        raise error
    raise CanonicalOperationError(code) from error


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value
