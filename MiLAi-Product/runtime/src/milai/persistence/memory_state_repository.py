from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from milai.domain.memory_state import CanonicalStateAddress
from milai.persistence.database import Database, SessionContext


@dataclass(frozen=True, slots=True)
class StateAddressResolution:
    addressable: bool
    reachable: bool
    claim_id: UUID | None
    claim_version_id: UUID | None
    subject: str | None
    predicate: str | None
    claim_type: str | None


class StateAddressRepository:
    """Resolve a canonical Claim/version using only authoritative Core tables."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def resolve(
        self,
        context: SessionContext,
        *,
        claim_id: UUID | None,
        state_key: CanonicalStateAddress | None,
        requested_scope: dict[str, object],
        valid_at: datetime,
        known_at: datetime,
        allow_historical: bool,
    ) -> StateAddressResolution:
        subject = state_key.subject if state_key is not None else None
        predicate = state_key.predicate if state_key is not None else None
        claim_type = state_key.claim_type if state_key is not None else None
        with self._database.connection(
            context,
            read_only=True,
            isolation_level="REPEATABLE READ",
        ) as connection:
            row = connection.execute(
                """
                WITH addressed AS (
                  SELECT claim.claim_id, claim.subject_id, claim.predicate,
                         claim.claim_type
                  FROM milai.claim claim
                  WHERE claim.tenant_id = %s
                    AND (
                      (%s::uuid IS NOT NULL AND claim.claim_id = %s::uuid)
                      OR (
                        %s::uuid IS NULL
                        AND claim.subject_id = %s::text
                        AND claim.predicate = %s::text
                        AND claim.claim_type = %s::text
                      )
                    )
                    AND EXISTS (
                      SELECT 1
                      FROM milai.claim_version scoped
                      WHERE scoped.tenant_id = claim.tenant_id
                        AND scoped.claim_id = claim.claim_id
                        AND scoped.scope_predicate @> %s::jsonb
                    )
                  ORDER BY claim.claim_id
                  LIMIT 2
                ), candidate AS (
                  SELECT version.claim_version_id, addressed.claim_id,
                         addressed.subject_id, addressed.predicate,
                         addressed.claim_type
                  FROM addressed
                  JOIN milai.claim_version version
                    ON version.tenant_id = %s
                   AND version.claim_id = addressed.claim_id
                  WHERE version.scope_predicate @> %s::jsonb
                    AND (
                      %s::boolean
                      OR version.claim_version_id = (
                        SELECT head.current_claim_version_id
                        FROM milai.claim_head head
                        WHERE head.tenant_id = version.tenant_id
                          AND head.claim_id = version.claim_id
                      )
                    )
                    AND version.system_time <= %s::timestamptz
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s::timestamptz)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s::timestamptz)
                  ORDER BY version.system_time DESC,
                           version.canonical_commit_seq DESC,
                           version.claim_version_id
                  LIMIT 1
                )
                SELECT (SELECT count(*) = 1 FROM addressed) AS addressable,
                       candidate.claim_version_id, candidate.claim_id,
                       candidate.subject_id, candidate.predicate,
                       candidate.claim_type
                FROM (SELECT 1) singleton
                LEFT JOIN candidate ON true
                """,
                (
                    context.tenant_id,
                    claim_id,
                    claim_id,
                    claim_id,
                    subject,
                    predicate,
                    claim_type,
                    Jsonb(requested_scope),
                    context.tenant_id,
                    Jsonb(requested_scope),
                    allow_historical,
                    known_at,
                    valid_at,
                    valid_at,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("state address query returned no row")
        resolved_claim_version = UUID(str(row[1])) if row[1] is not None else None
        resolved_claim = UUID(str(row[2])) if row[2] is not None else None
        return StateAddressResolution(
            addressable=bool(row[0]),
            reachable=resolved_claim_version is not None,
            claim_id=resolved_claim,
            claim_version_id=resolved_claim_version,
            subject=str(row[3]) if row[3] is not None else None,
            predicate=str(row[4]) if row[4] is not None else None,
            claim_type=str(row[5]) if row[5] is not None else None,
        )
