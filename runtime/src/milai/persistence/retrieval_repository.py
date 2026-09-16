from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic, sleep
from typing import Any, Literal
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.application.errors import CausalConsistencyError
from milai.persistence import Database, DatabaseUnavailable, SessionContext

CandidateSource = Literal["l0", "exact", "fts", "vector", "recent", "canonical"]

_EXACT_VECTOR_SCOPE_LIMIT = 4_096
_FTS_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_EVIDENCE_RECALL_PREFIX = re.compile(
    r"^\s*recall\s+previous\s+history\s+evidence\s*:\s*",
    re.IGNORECASE,
)
_FTS_STOPWORDS = frozenset(
    {
        "a",
        "am",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


def _fts_terms(value: str) -> list[str]:
    """Extract bounded content terms for safe natural-language recall."""
    raw = [match.group(0).casefold() for match in _FTS_TOKEN.finditer(value)]
    selected = [token for token in raw if len(token) > 1 and token not in _FTS_STOPWORDS]
    if not selected:
        selected = [token for token in raw if token]
    return list(dict.fromkeys(selected))[:32]


def evidence_query_terms(value: str) -> list[str]:
    """Expose the exact bounded terms used by governed Evidence FTS."""

    return _fts_terms(_EVIDENCE_RECALL_PREFIX.sub("", value, count=1))


def _fts_query(value: str) -> str:
    """Build a bounded OR query without allowing query-syntax injection."""
    return " | ".join(_fts_terms(value))


def _normalized_partition(values: Sequence[str]) -> list[str]:
    return sorted({value.strip().casefold() for value in values if value.strip()})


def _source_observed_bounds(
    value: dict[str, object] | None,
) -> tuple[datetime | None, datetime | None]:
    if value is None:
        return None, None
    raw_start, raw_end = value.get("start"), value.get("end")
    if not isinstance(raw_start, str) or not isinstance(raw_end, str):
        raise ValueError("source-observed range requires typed start and end")
    try:
        start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source-observed range is not ISO-8601") from exc
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise ValueError("source-observed range must be an aware closed-open interval")
    return start, end


class ProjectionUnavailable(RuntimeError):
    def __init__(self, component: Literal["fts", "vector", "evidence_dense"]) -> None:
        super().__init__(f"{component} projection is unavailable")
        self.component = component


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    claim_version_id: UUID
    score: float
    source: CandidateSource


@dataclass(frozen=True, slots=True)
class ProjectionState:
    canonical_snapshot_outbox_sequence: int
    fts_watermark: int
    vector_watermark: int
    fts_dead_letter: bool
    vector_dead_letter: bool
    evidence_watermark: int = 0
    evidence_dead_letter: bool = False


@dataclass(frozen=True, slots=True)
class GatedBatch:
    projection_state: ProjectionState
    outcomes: list[dict[str, Any]]
    claims: list[dict[str, Any]]


CausalWaitOutcome = Literal["REACHED", "TIMEOUT", "DEAD_LETTER"]


@dataclass(frozen=True, slots=True)
class CausalWaitResult:
    outcome: CausalWaitOutcome
    state: ProjectionState
    waited_ms: int


@dataclass(frozen=True, slots=True)
class RetrievalTraceCommand:
    request_id: str
    route: Literal["L0", "L1"]
    consistency: str
    query_fingerprint: str
    query_plan: dict[str, object]
    requested_scope: dict[str, object]
    as_of: datetime
    required_authority: str
    canonical_snapshot: int
    fts_watermark: int
    vector_watermark: int
    accepted: list[dict[str, object]]
    rejected: list[dict[str, object]]
    fallback_used: bool
    fallback_reason: str | None
    abstained: bool
    abstention_reason: str | None
    duration_ms: int
    minimum_outbox_sequence: int | None
    causal_wait_outcome: str | None
    causal_waited_ms: int
    execution_trace: dict[str, object]
    stage_metrics: dict[str, object]


class RetrievalRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def projection_state(
        self, context: SessionContext, *, statement_timeout_ms: int | None = None
    ) -> ProjectionState:
        with self._database.connection(
            context, read_only=True, statement_timeout_ms=statement_timeout_ms
        ) as connection:
            return _projection_state(connection, context)

    def outbox_position(self, context: SessionContext, outbox_ids: list[UUID]) -> int:
        unique_ids = sorted(set(outbox_ids), key=str)
        if not unique_ids or len(unique_ids) > 16:
            raise CausalConsistencyError("INVALID_CAUSAL_REQUEST")
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                "SELECT milai.resolve_outbox_position(%s, %s, %s::uuid[])",
                (context.tenant_id, context.actor_id, unique_ids),
            ).fetchone()
        if row is None:
            raise RuntimeError("outbox position query returned no result")
        maximum = row[0]
        if maximum is None:
            raise CausalConsistencyError("OUTBOX_POSITION_NOT_FOUND")
        return int(maximum)

    def wait_for_outbox_sequence(
        self,
        context: SessionContext,
        minimum_outbox_sequence: int,
        timeout_ms: int,
    ) -> CausalWaitResult:
        started = monotonic()
        deadline = started + timeout_ms / 1_000
        while True:
            with self._database.connection(context, read_only=True) as connection:
                row = connection.execute(
                    "SELECT milai.causal_projection_status(%s, %s, %s)",
                    (context.tenant_id, context.actor_id, minimum_outbox_sequence),
                ).fetchone()
            if row is None or not isinstance(row[0], dict):
                raise RuntimeError("causal projection status returned no object")
            value = row[0]
            if not bool(value["position_exists"]):
                raise CausalConsistencyError("CAUSAL_SEQUENCE_NOT_FOUND")
            state = ProjectionState(
                canonical_snapshot_outbox_sequence=int(value["canonical_snapshot_outbox_sequence"]),
                fts_watermark=int(value["fts_watermark"]),
                vector_watermark=int(value["vector_watermark"]),
                fts_dead_letter=bool(value["fts_dead_letter"]),
                vector_dead_letter=bool(value["vector_dead_letter"]),
                evidence_watermark=int(value.get("evidence_watermark", 0)),
                evidence_dead_letter=bool(value.get("evidence_dead_letter", False)),
            )
            dead_letter = bool(value["blocking_dead_letter"])
            elapsed_ms = max(0, int((monotonic() - started) * 1_000))
            if (
                state.fts_watermark >= minimum_outbox_sequence
                and state.vector_watermark >= minimum_outbox_sequence
            ):
                return CausalWaitResult("REACHED", state, elapsed_ms)
            if dead_letter:
                return CausalWaitResult("DEAD_LETTER", state, elapsed_ms)
            remaining = deadline - monotonic()
            if remaining <= 0:
                return CausalWaitResult("TIMEOUT", state, elapsed_ms)
            sleep(min(0.02, remaining))

    def l0_candidates(
        self,
        context: SessionContext,
        *,
        claim_id: UUID | None,
        subject_id: str | None,
        predicate: str | None,
        claim_type: str | None,
    ) -> list[RetrievalCandidate]:
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT head.current_claim_version_id
                FROM milai.claim claim
                JOIN milai.claim_head head
                  ON head.tenant_id = claim.tenant_id
                 AND head.claim_id = claim.claim_id
                WHERE claim.tenant_id = %s
                  AND (%s::uuid IS NULL OR claim.claim_id = %s)
                  AND (%s::text IS NULL OR claim.subject_id = %s)
                  AND (%s::text IS NULL OR claim.predicate = %s)
                  AND (%s::text IS NULL OR claim.claim_type = %s)
                ORDER BY claim.claim_id
                LIMIT 2
                """,
                (
                    context.tenant_id,
                    claim_id,
                    claim_id,
                    subject_id,
                    subject_id,
                    predicate,
                    predicate,
                    claim_type,
                    claim_type,
                ),
            ).fetchall()
        return [RetrievalCandidate(row[0], 1.0, "l0") for row in rows]

    def search_evidence(
        self,
        context: SessionContext,
        query: str,
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        query_terms = evidence_query_terms(query)
        if not query_terms:
            return []
        tsquery = " | ".join(query_terms)
        with self._database.connection(
            context, read_only=True, statement_timeout_ms=statement_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT milai.search_evidence_projection(%s, %s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    tsquery,
                    Jsonb(requested_scope),
                    as_of,
                    limit,
                    "evidence-search-v1",
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Evidence search returned no result")
        return _array_of_objects(row[0], "search_evidence_projection")

    def hydrate_evidence_adjacency(
        self,
        context: SessionContext,
        *,
        anchor_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
    ) -> list[dict[str, Any]]:
        """Read bounded structured neighbors; governance is enforced inside SQL."""

        if not 1 <= len(anchor_evidence_ids) <= 24:
            raise ValueError("adjacency hydration requires between 1 and 24 anchors")
        if not 1 <= max_items <= 120:
            raise ValueError("adjacency hydration max_items must be between 1 and 120")
        anchors = [UUID(value) for value in dict.fromkeys(anchor_evidence_ids)]
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                "SELECT milai.hydrate_evidence_adjacency(%s, %s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    anchors,
                    Jsonb(requested_scope),
                    as_of,
                    max_items,
                    "evidence-search-v1",
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Evidence adjacency hydration returned no result")
        return _array_of_objects(row[0], "hydrate_evidence_adjacency")

    def hydrate_evidence_by_ids(
        self,
        context: SessionContext,
        *,
        evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Hydrate sidecar-selected source Evidence through live governance."""

        unique_ids = list(dict.fromkeys(evidence_ids))
        if not 1 <= len(unique_ids) <= 24:
            raise ValueError("Evidence ID hydration requires between 1 and 24 IDs")
        if not 1 <= max_items <= 24:
            raise ValueError("Evidence ID hydration max_items must be between 1 and 24")
        identifiers = [UUID(value) for value in unique_ids]
        with self._database.connection(
            context,
            read_only=True,
            statement_timeout_ms=statement_timeout_ms,
        ) as connection:
            row = connection.execute(
                "SELECT milai.hydrate_evidence_projection_by_id("
                "%s, %s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    identifiers,
                    Jsonb(requested_scope),
                    as_of,
                    max_items,
                    "evidence-search-v1",
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Evidence ID hydration returned no result")
        return _array_of_objects(row[0], "hydrate_evidence_projection_by_id")

    def scan_evidence_range(
        self,
        context: SessionContext,
        requested_scope: dict[str, object],
        range_start: datetime,
        range_end: datetime,
        max_items: int,
        *,
        statement_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        with self._database.connection(
            context, read_only=True, statement_timeout_ms=statement_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT milai.scan_evidence_projection_range(%s, %s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    Jsonb(requested_scope),
                    range_start,
                    range_end,
                    max_items,
                    "evidence-search-v1",
                ),
            ).fetchone()
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Evidence range scan returned no object")
        result = dict(row[0])
        # This repository function is backed by evidence_record.observed_at.
        # Keep that physical fact explicit so an event-occurrence query cannot
        # mistake a complete source-time partition for a complete event-time
        # partition.
        result["scan_axis"] = "SOURCE_OBSERVED_TIME"
        return result

    def search_evidence_event_range(
        self,
        context: SessionContext,
        requested_scope: dict[str, object],
        event_range_start: datetime,
        event_range_end: datetime,
        as_of: datetime,
        max_items: int,
        *,
        statement_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Return a complete governed Evidence snapshot for query-time event filtering.

        The existing projection is physically keyed by source-observed time.  This
        method therefore scans the entire readable partition at ``as_of``; it never
        presents a source-time slice as an event-time range.  The application layer
        may promote the result to an event-range proof only after deterministic
        event normalization and exact range filtering.
        """

        for value in (event_range_start, event_range_end, as_of):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("event range snapshot requires timezone-aware values")
        if event_range_start >= event_range_end:
            raise ValueError("event range snapshot requires start < end")
        if not 1 <= max_items <= 2_000:
            raise ValueError("event range snapshot max_items must be between 1 and 2000")
        snapshot_end = as_of.astimezone(UTC)
        if snapshot_end < datetime.max.replace(tzinfo=UTC):
            snapshot_end += timedelta(microseconds=1)
        result = self.scan_evidence_range(
            context,
            requested_scope,
            datetime.min.replace(tzinfo=UTC),
            snapshot_end,
            max_items,
            statement_timeout_ms=statement_timeout_ms,
        )
        result.update(
            {
                "partition_kind": "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF",
                "source_snapshot_axis": "SOURCE_OBSERVED_TIME",
                "source_snapshot_end": snapshot_end.isoformat(),
                "event_range_start": event_range_start.astimezone(UTC).isoformat(),
                "event_range_end": event_range_end.astimezone(UTC).isoformat(),
                "event_range_boundary": "CLOSED_OPEN",
                "event_normalization_owner": "DETERMINISTIC_RUNTIME",
                "event_normalization_version": "query-time-event-v1",
            }
        )
        return result

    def search_evidence_dense(
        self,
        context: SessionContext,
        embedding: list[float],
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        model_id: str,
        projection_version: str,
        source_observed_range: dict[str, object] | None = None,
        statement_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        if len(embedding) != 128:
            raise ValueError("Evidence dense query requires a 128-dimensional vector")
        source_start, source_end = _source_observed_bounds(source_observed_range)
        with self._database.connection(
            context, read_only=True, statement_timeout_ms=statement_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT milai.search_evidence_dense_128(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    embedding,
                    Jsonb(requested_scope),
                    as_of,
                    source_start,
                    source_end,
                    limit,
                    model_id,
                    projection_version,
                ),
            ).fetchone()
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Evidence dense search returned no object")
        return dict(row[0])

    def search_fts(
        self,
        context: SessionContext,
        query: str,
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        entities: Sequence[str] = (),
        memory_types: Sequence[str] = (),
        statement_timeout_ms: int | None = None,
    ) -> list[RetrievalCandidate]:
        fts_query = _fts_query(query)
        fts_terms = _fts_terms(query)
        entity_partition = _normalized_partition(entities)
        type_partition = _normalized_partition(memory_types)
        try:
            with self._database.connection(
                context,
                read_only=True,
                statement_timeout_ms=statement_timeout_ms,
            ) as connection:
                rows = connection.execute(
                    """
                    WITH query AS (
                      SELECT to_tsquery('simple', %s) AS value
                    ), terms AS (
                      SELECT plainto_tsquery('simple', term) AS value
                      FROM unnest(%s::text[]) AS term
                    ), document_source AS (
                      SELECT fragment.tenant_id, fragment.claim_version_id,
                             fragment.content_text, fragment.search_vector,
                             fragment.scope_predicate, fragment.valid_time_from,
                             fragment.valid_time_to, fragment.canonical_commit_seq
                      FROM milai.search_document_fragment fragment
                      WHERE fragment.tenant_id = %s
                      UNION ALL
                      SELECT document.tenant_id, document.claim_version_id,
                             document.content_text, document.search_vector,
                             document.scope_predicate, document.valid_time_from,
                             document.valid_time_to, document.canonical_commit_seq
                      FROM milai.search_document document
                      WHERE document.tenant_id = %s
                        AND NOT EXISTS (
                          SELECT 1 FROM milai.search_document_fragment fragment
                          WHERE fragment.tenant_id = document.tenant_id
                            AND fragment.claim_version_id = document.claim_version_id
                        )
                    ), scored AS (
                      SELECT document.claim_version_id,
                           ts_rank_cd(document.search_vector, query.value) AS score,
                           (SELECT count(*) FROM terms
                            WHERE document.search_vector @@ terms.value) AS term_coverage,
                           document.canonical_commit_seq
                    FROM document_source document
                    JOIN milai.claim_version version
                      ON version.tenant_id = document.tenant_id
                     AND version.claim_version_id = document.claim_version_id
                    JOIN milai.claim claim
                      ON claim.tenant_id = version.tenant_id
                     AND claim.claim_id = version.claim_id
                    CROSS JOIN query
                    WHERE document.search_vector @@ query.value
                      AND document.scope_predicate @> %s
                      AND (document.valid_time_from IS NULL
                           OR document.valid_time_from <= %s)
                      AND (document.valid_time_to IS NULL
                           OR document.valid_time_to > %s)
                      AND (
                        %s::boolean OR EXISTS (
                          SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                          WHERE strpos(lower(concat_ws(
                            ' ', claim.subject_id, claim.predicate,
                            claim.claim_type, version.payload::text
                          )), entity.value) > 0
                        )
                      )
                      AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                    ), ranked AS (
                      SELECT scored.*,
                             row_number() OVER (
                               PARTITION BY claim_version_id
                               ORDER BY term_coverage DESC, score DESC,
                                        canonical_commit_seq DESC
                             ) AS parent_rank
                      FROM scored
                    )
                    SELECT claim_version_id, score
                    FROM ranked
                    WHERE parent_rank = 1
                    ORDER BY term_coverage DESC, score DESC,
                             canonical_commit_seq DESC, claim_version_id
                    LIMIT %s
                    """,
                    (
                        fts_query,
                        fts_terms,
                        context.tenant_id,
                        context.tenant_id,
                        Jsonb(requested_scope),
                        as_of,
                        as_of,
                        not entity_partition,
                        entity_partition,
                        not type_partition,
                        type_partition,
                        limit,
                    ),
                ).fetchall()
        except DatabaseUnavailable:
            raise
        except Error as exc:
            raise ProjectionUnavailable("fts") from exc
        return [RetrievalCandidate(row[0], float(row[1]), "fts") for row in rows]

    def exact_candidates(
        self,
        context: SessionContext,
        query: str,
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        entities: Sequence[str] = (),
        memory_types: Sequence[str] = (),
        statement_timeout_ms: int | None = None,
    ) -> list[RetrievalCandidate]:
        """Resolve explicit canonical identities without relying on a projection."""
        identity = query.strip()
        if not identity:
            return []
        entity_partition = _normalized_partition(entities)
        type_partition = _normalized_partition(memory_types)
        with self._database.connection(
            context,
            read_only=True,
            statement_timeout_ms=statement_timeout_ms,
        ) as connection:
            rows = connection.execute(
                """
                SELECT version.claim_version_id
                FROM milai.claim claim
                JOIN milai.claim_head head
                  ON head.tenant_id = claim.tenant_id
                 AND head.claim_id = claim.claim_id
                JOIN milai.claim_version version
                  ON version.tenant_id = head.tenant_id
                 AND version.claim_version_id = head.current_claim_version_id
                WHERE claim.tenant_id = %s
                  AND version.scope_predicate @> %s
                  AND (version.valid_time_from IS NULL
                       OR version.valid_time_from <= %s)
                  AND (version.valid_time_to IS NULL
                       OR version.valid_time_to > %s)
                  AND (
                    %s::boolean OR EXISTS (
                      SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                      WHERE strpos(lower(concat_ws(
                        ' ', claim.subject_id, claim.predicate,
                        claim.claim_type, version.payload::text
                      )), entity.value) > 0
                    )
                  )
                  AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                  AND (
                    claim.claim_id::text = %s
                    OR version.claim_version_id::text = %s
                    OR lower(claim.subject_id) = lower(%s)
                    OR lower(claim.predicate) = lower(%s)
                    OR lower(claim.claim_type) = lower(%s)
                  )
                ORDER BY version.canonical_commit_seq DESC, version.claim_version_id
                LIMIT %s
                """,
                (
                    context.tenant_id,
                    Jsonb(requested_scope),
                    as_of,
                    as_of,
                    not entity_partition,
                    entity_partition,
                    not type_partition,
                    type_partition,
                    identity,
                    identity,
                    identity,
                    identity,
                    identity,
                    limit,
                ),
            ).fetchall()
        return [RetrievalCandidate(row[0], 1.0, "exact") for row in rows]

    def search_vector(
        self,
        context: SessionContext,
        embedding: list[float],
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        entities: Sequence[str] = (),
        memory_types: Sequence[str] = (),
        model_id: str = "deterministic-hash-v1",
        projection_version: str = "1",
        statement_timeout_ms: int | None = None,
    ) -> list[RetrievalCandidate]:
        if len(embedding) not in {16, 128}:
            raise ValueError("search embedding must contain 16 or 128 values")
        entity_partition = _normalized_partition(entities)
        type_partition = _normalized_partition(memory_types)
        vector_literal = "[" + ",".join(f"{value:.17g}" for value in embedding) + "]"
        scope_count_parameters = (
            context.tenant_id,
            model_id,
            projection_version,
            Jsonb(requested_scope),
            as_of,
            as_of,
            not entity_partition,
            entity_partition,
            not type_partition,
            type_partition,
            _EXACT_VECTOR_SCOPE_LIMIT + 1,
        )
        parameters: tuple[Any, ...]
        exact_parameters: tuple[Any, ...]
        if len(embedding) == 128:
            scope_count_statement = """
                SELECT count(*)
                FROM (
                  SELECT 1
                  FROM milai.search_embedding_window_128 embedding
                  JOIN milai.claim_version version
                    ON version.tenant_id = embedding.tenant_id
                   AND version.claim_version_id = embedding.claim_version_id
                  JOIN milai.claim claim
                    ON claim.tenant_id = version.tenant_id
                   AND claim.claim_id = version.claim_id
                  WHERE embedding.tenant_id = %s
                    AND embedding.model_id = %s
                    AND embedding.projection_version = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                  LIMIT %s
                ) bounded_scope
            """
            exact_statement = """
                WITH scoped AS MATERIALIZED (
                  SELECT embedding.claim_version_id,
                         embedding.embedding,
                         embedding.canonical_commit_seq,
                         embedding.fragment_id
                  FROM milai.search_embedding_window_128 embedding
                  JOIN milai.claim_version version
                    ON version.tenant_id = embedding.tenant_id
                   AND version.claim_version_id = embedding.claim_version_id
                  JOIN milai.claim claim
                    ON claim.tenant_id = version.tenant_id
                   AND claim.claim_id = version.claim_id
                  WHERE embedding.tenant_id = %s
                    AND embedding.model_id = %s
                    AND embedding.projection_version = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                ), candidates AS (
                  SELECT scoped.claim_version_id,
                         1 - (scoped.embedding <=> %s::public.vector) AS score,
                         scoped.embedding <=> %s::public.vector AS distance,
                         scoped.canonical_commit_seq,
                         row_number() OVER (
                           PARTITION BY scoped.claim_version_id
                           ORDER BY scoped.embedding <=> %s::public.vector,
                                    scoped.canonical_commit_seq DESC,
                                    scoped.fragment_id
                         ) AS parent_rank
                  FROM scoped
                )
                SELECT claim_version_id, score
                FROM candidates
                WHERE parent_rank = 1
                ORDER BY distance, canonical_commit_seq DESC, claim_version_id
                LIMIT %s
            """
            exact_parameters = (
                context.tenant_id,
                model_id,
                projection_version,
                Jsonb(requested_scope),
                as_of,
                as_of,
                not entity_partition,
                entity_partition,
                not type_partition,
                type_partition,
                vector_literal,
                vector_literal,
                vector_literal,
                limit,
            )
            approximate_statement = """
                WITH candidates AS (
                  SELECT embedding.claim_version_id,
                         1 - (embedding.embedding <=> %s::public.vector) AS score,
                         embedding.embedding <=> %s::public.vector AS distance,
                         embedding.canonical_commit_seq,
                         row_number() OVER (
                           PARTITION BY embedding.claim_version_id
                           ORDER BY embedding.embedding <=> %s::public.vector,
                                    embedding.canonical_commit_seq DESC,
                                    embedding.fragment_id
                         ) AS parent_rank
                  FROM milai.search_embedding_window_128 embedding
                  JOIN milai.claim_version version
                    ON version.tenant_id = embedding.tenant_id
                   AND version.claim_version_id = embedding.claim_version_id
                  JOIN milai.claim claim
                    ON claim.tenant_id = version.tenant_id
                   AND claim.claim_id = version.claim_id
                  WHERE embedding.tenant_id = %s
                    AND embedding.model_id = %s
                    AND embedding.projection_version = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                )
                SELECT claim_version_id, score
                FROM candidates
                WHERE parent_rank = 1
                ORDER BY distance, canonical_commit_seq DESC, claim_version_id
                LIMIT %s
            """
            parameters = (
                vector_literal,
                vector_literal,
                vector_literal,
                context.tenant_id,
                model_id,
                projection_version,
                Jsonb(requested_scope),
                as_of,
                as_of,
                not entity_partition,
                entity_partition,
                not type_partition,
                type_partition,
                limit,
            )
        else:
            scope_count_statement = """
                SELECT count(*)
                FROM (
                  SELECT 1
                  FROM milai.search_embedding embedding
                  JOIN milai.claim_version version
                    ON version.tenant_id = embedding.tenant_id
                   AND version.claim_version_id = embedding.claim_version_id
                  JOIN milai.claim claim
                    ON claim.tenant_id = version.tenant_id
                   AND claim.claim_id = version.claim_id
                  WHERE embedding.tenant_id = %s
                    AND embedding.model_id = %s
                    AND embedding.projection_version = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                  LIMIT %s
                ) bounded_scope
            """
            exact_statement = """
                WITH scoped AS MATERIALIZED (
                  SELECT embedding.claim_version_id,
                         embedding.embedding,
                         embedding.canonical_commit_seq
                  FROM milai.search_embedding embedding
                  JOIN milai.claim_version version
                    ON version.tenant_id = embedding.tenant_id
                   AND version.claim_version_id = embedding.claim_version_id
                  JOIN milai.claim claim
                    ON claim.tenant_id = version.tenant_id
                   AND claim.claim_id = version.claim_id
                  WHERE embedding.tenant_id = %s
                    AND embedding.model_id = %s
                    AND embedding.projection_version = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                )
                SELECT scoped.claim_version_id,
                       1 - (scoped.embedding <=> %s::public.vector) AS score
                FROM scoped
                ORDER BY scoped.embedding <=> %s::public.vector,
                         scoped.canonical_commit_seq DESC,
                         scoped.claim_version_id
                LIMIT %s
            """
            exact_parameters = (
                context.tenant_id,
                model_id,
                projection_version,
                Jsonb(requested_scope),
                as_of,
                as_of,
                not entity_partition,
                entity_partition,
                not type_partition,
                type_partition,
                vector_literal,
                vector_literal,
                limit,
            )
            approximate_statement = """
                SELECT embedding.claim_version_id,
                       1 - (embedding.embedding <=> %s::public.vector) AS score
                FROM milai.search_embedding embedding
                JOIN milai.claim_version version
                  ON version.tenant_id = embedding.tenant_id
                 AND version.claim_version_id = embedding.claim_version_id
                JOIN milai.claim claim
                  ON claim.tenant_id = version.tenant_id
                 AND claim.claim_id = version.claim_id
                WHERE embedding.tenant_id = %s
                  AND embedding.model_id = %s
                  AND embedding.projection_version = %s
                  AND version.scope_predicate @> %s
                  AND (version.valid_time_from IS NULL
                       OR version.valid_time_from <= %s)
                  AND (version.valid_time_to IS NULL
                       OR version.valid_time_to > %s)
                  AND (
                    %s::boolean OR EXISTS (
                      SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                      WHERE strpos(lower(concat_ws(
                        ' ', claim.subject_id, claim.predicate,
                        claim.claim_type, version.payload::text
                      )), entity.value) > 0
                    )
                  )
                  AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                ORDER BY embedding.embedding <=> %s::public.vector,
                         embedding.canonical_commit_seq DESC,
                         embedding.claim_version_id
                LIMIT %s
            """
            parameters = (
                vector_literal,
                context.tenant_id,
                model_id,
                projection_version,
                Jsonb(requested_scope),
                as_of,
                as_of,
                not entity_partition,
                entity_partition,
                not type_partition,
                type_partition,
                vector_literal,
                limit,
            )
        try:
            with self._database.connection(
                context,
                read_only=True,
                statement_timeout_ms=statement_timeout_ms,
            ) as connection:
                scope_count_row = connection.execute(
                    scope_count_statement, scope_count_parameters
                ).fetchone()
                scope_count = int(scope_count_row[0]) if scope_count_row is not None else 0
                if scope_count <= _EXACT_VECTOR_SCOPE_LIMIT:
                    rows = connection.execute(exact_statement, exact_parameters).fetchall()
                else:
                    connection.execute(
                        "SELECT set_config('hnsw.iterative_scan', 'strict_order', true)"
                    ).fetchone()
                    rows = connection.execute(approximate_statement, parameters).fetchall()
        except DatabaseUnavailable:
            raise
        except Error as exc:
            raise ProjectionUnavailable("vector") from exc
        return [RetrievalCandidate(row[0], float(row[1]), "vector") for row in rows]

    def recent_canonical_candidates(
        self,
        context: SessionContext,
        query: str,
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        entities: Sequence[str] = (),
        memory_types: Sequence[str] = (),
        statement_timeout_ms: int | None = None,
    ) -> list[RetrievalCandidate]:
        """Return query-relevant current heads, preferring the newest canonical commits."""
        fts_query = _fts_query(query)
        fts_terms = _fts_terms(query)
        entity_partition = _normalized_partition(entities)
        type_partition = _normalized_partition(memory_types)
        with self._database.connection(
            context,
            read_only=True,
            statement_timeout_ms=statement_timeout_ms,
        ) as connection:
            rows = connection.execute(
                """
                WITH query AS (
                  SELECT to_tsquery('simple', %s) AS value
                ), terms AS (
                  SELECT plainto_tsquery('simple', term) AS value
                  FROM unnest(%s::text[]) AS term
                ), current_claim AS (
                  SELECT version.claim_version_id,
                         version.canonical_commit_seq,
                         to_tsvector('simple', concat_ws(
                           ' ', claim.subject_id, claim.predicate,
                           claim.claim_type, version.payload::text
                         )) AS search_vector,
                         to_tsvector(
                           'simple', COALESCE((
                             SELECT string_agg(parts[2], ' ')
                             FROM regexp_matches(
                               COALESCE(version.payload ->> 'memory_text', ''),
                               '(^|\n)(user:[^\n]*)', 'g'
                             ) AS parts
                           ), '')
                         ) AS user_vector
                  FROM milai.claim claim
                  JOIN milai.claim_head head
                    ON head.tenant_id = claim.tenant_id
                   AND head.claim_id = claim.claim_id
                  JOIN milai.claim_version version
                    ON version.tenant_id = head.tenant_id
                   AND version.claim_version_id = head.current_claim_version_id
                  WHERE claim.tenant_id = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                )
                SELECT current_claim.claim_version_id,
                       ts_rank_cd(current_claim.search_vector, query.value) AS score,
                       ts_rank_cd(current_claim.user_vector, query.value) AS user_score,
                       (SELECT count(*) FROM terms
                        WHERE current_claim.search_vector @@ terms.value) AS term_coverage,
                       (SELECT count(*) FROM terms
                        WHERE current_claim.user_vector @@ terms.value) AS user_term_coverage
                FROM current_claim, query
                WHERE current_claim.search_vector @@ query.value
                ORDER BY user_term_coverage DESC, term_coverage DESC,
                         user_score DESC, score DESC,
                         current_claim.canonical_commit_seq DESC,
                         current_claim.claim_version_id
                LIMIT %s
                """,
                (
                    fts_query,
                    fts_terms,
                    context.tenant_id,
                    Jsonb(requested_scope),
                    as_of,
                    as_of,
                    not entity_partition,
                    entity_partition,
                    not type_partition,
                    type_partition,
                    limit,
                ),
            ).fetchall()
        return [RetrievalCandidate(row[0], float(row[1]), "recent") for row in rows]

    def canonical_search(
        self,
        context: SessionContext,
        query: str,
        requested_scope: dict[str, object],
        as_of: datetime,
        limit: int,
        *,
        entities: Sequence[str] = (),
        memory_types: Sequence[str] = (),
        statement_timeout_ms: int | None = None,
    ) -> list[RetrievalCandidate]:
        fts_query = _fts_query(query)
        fts_terms = _fts_terms(query)
        entity_partition = _normalized_partition(entities)
        type_partition = _normalized_partition(memory_types)
        with self._database.connection(
            context,
            read_only=True,
            statement_timeout_ms=statement_timeout_ms,
        ) as connection:
            rows = connection.execute(
                """
                WITH query AS (
                  SELECT to_tsquery('simple', %s) AS value
                ), terms AS (
                  SELECT plainto_tsquery('simple', term) AS value
                  FROM unnest(%s::text[]) AS term
                ), current_claim AS (
                  SELECT version.claim_version_id,
                         version.canonical_commit_seq,
                         to_tsvector('simple', concat_ws(
                           ' ', claim.subject_id, claim.predicate,
                           claim.claim_type, version.payload::text
                         )) AS search_vector,
                         to_tsvector(
                           'simple', COALESCE((
                             SELECT string_agg(parts[2], ' ')
                             FROM regexp_matches(
                               COALESCE(version.payload ->> 'memory_text', ''),
                               '(^|\n)(user:[^\n]*)', 'g'
                             ) AS parts
                           ), '')
                         ) AS user_vector
                  FROM milai.claim claim
                  JOIN milai.claim_head head
                    ON head.tenant_id = claim.tenant_id
                   AND head.claim_id = claim.claim_id
                  JOIN milai.claim_version version
                    ON version.tenant_id = head.tenant_id
                   AND version.claim_version_id = head.current_claim_version_id
                  WHERE claim.tenant_id = %s
                    AND version.scope_predicate @> %s
                    AND (version.valid_time_from IS NULL
                         OR version.valid_time_from <= %s)
                    AND (version.valid_time_to IS NULL
                         OR version.valid_time_to > %s)
                    AND (
                      %s::boolean OR EXISTS (
                        SELECT 1 FROM unnest(%s::text[]) AS entity(value)
                        WHERE strpos(lower(concat_ws(
                          ' ', claim.subject_id, claim.predicate,
                          claim.claim_type, version.payload::text
                        )), entity.value) > 0
                      )
                    )
                    AND (%s::boolean OR lower(claim.claim_type) = ANY(%s::text[]))
                )
                SELECT current_claim.claim_version_id,
                       ts_rank_cd(current_claim.search_vector, query.value) AS score,
                       ts_rank_cd(current_claim.user_vector, query.value) AS user_score,
                       (SELECT count(*) FROM terms
                        WHERE current_claim.search_vector @@ terms.value) AS term_coverage,
                       (SELECT count(*) FROM terms
                        WHERE current_claim.user_vector @@ terms.value) AS user_term_coverage
                FROM current_claim, query
                WHERE current_claim.search_vector @@ query.value
                ORDER BY user_term_coverage DESC, term_coverage DESC,
                         user_score DESC, score DESC,
                         current_claim.canonical_commit_seq DESC,
                         current_claim.claim_version_id
                LIMIT %s
                """,
                (
                    fts_query,
                    fts_terms,
                    context.tenant_id,
                    Jsonb(requested_scope),
                    as_of,
                    as_of,
                    not entity_partition,
                    entity_partition,
                    not type_partition,
                    type_partition,
                    limit,
                ),
            ).fetchall()
        return [RetrievalCandidate(row[0], float(row[1]), "canonical") for row in rows]

    def gate_and_hydrate(
        self,
        context: SessionContext,
        claim_version_ids: list[UUID],
        required_authority: str,
        requested_scope: dict[str, object],
        as_of: datetime,
        required_lifecycle: str,
        accepted_epistemic_statuses: Sequence[str],
        required_freshness: str,
        minimum_confidence: float,
        system_as_of: datetime,
        *,
        allow_historical: bool = False,
        statement_timeout_ms: int | None = None,
    ) -> GatedBatch:
        with self._database.connection(
            context,
            read_only=True,
            isolation_level="REPEATABLE READ",
            statement_timeout_ms=statement_timeout_ms,
        ) as connection:
            row = connection.execute(
                """
                SELECT milai.evaluate_canonical_candidates(
                  %s::uuid, %s::uuid, %s::uuid[], %s::text, %s::jsonb,
                  %s::timestamptz, %s::text, %s::text[], %s::text,
                  %s::numeric, %s::timestamptz, %s::boolean
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    claim_version_ids,
                    required_authority,
                    Jsonb(requested_scope),
                    as_of,
                    required_lifecycle,
                    accepted_epistemic_statuses,
                    required_freshness,
                    minimum_confidence,
                    system_as_of,
                    allow_historical,
                ),
            ).fetchone()
            outcomes = _array_of_objects(row[0] if row is not None else None, "canonical gate")
            accepted_ids = [
                UUID(str(outcome["claim_version_id"]))
                for outcome in outcomes
                if outcome.get("accepted") is True
            ]
            rows = connection.execute(
                """
                SELECT version.claim_version_id, claim.claim_id,
                       claim.subject_id, claim.predicate, claim.claim_type,
                       version.version_number, version.payload,
                       version.scope_predicate, version.valid_time_from,
                       version.valid_time_to, version.system_time,
                       version.lifecycle, version.epistemic_status,
                       version.freshness, version.authority, version.confidence,
                       version.derivation_policy_id, version.model_id,
                       version.template_id, version.canonical_commit_seq
                FROM milai.claim_version version
                JOIN milai.claim claim
                  ON claim.tenant_id = version.tenant_id
                 AND claim.claim_id = version.claim_id
                WHERE version.tenant_id = %s
                  AND version.claim_version_id = ANY(%s::uuid[])
                """,
                (context.tenant_id, accepted_ids),
            ).fetchall()
            state = _projection_state(connection, context)
        keys = (
            "claim_version_id",
            "claim_id",
            "subject_id",
            "predicate",
            "claim_type",
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
            "canonical_commit_seq",
        )
        claims = [_json_safe(dict(zip(keys, claim, strict=True))) for claim in rows]
        return GatedBatch(state, outcomes, claims)

    def record_trace(self, context: SessionContext, command: RetrievalTraceCommand) -> UUID:
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT milai.record_retrieval_trace(
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    command.request_id,
                    command.route,
                    command.consistency,
                    command.query_fingerprint,
                    Jsonb(command.query_plan),
                    Jsonb(command.requested_scope),
                    command.as_of,
                    command.required_authority,
                    command.canonical_snapshot,
                    command.fts_watermark,
                    command.vector_watermark,
                    Jsonb(command.accepted),
                    Jsonb(command.rejected),
                    command.fallback_used,
                    command.fallback_reason,
                    command.abstained,
                    command.abstention_reason,
                    command.duration_ms,
                    command.minimum_outbox_sequence,
                    command.causal_wait_outcome,
                    command.causal_waited_ms,
                    Jsonb(command.execution_trace),
                    Jsonb(command.stage_metrics),
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("retrieval trace procedure returned no trace id")
        return UUID(str(row[0]))

    def get_trace(self, context: SessionContext, trace_id: UUID) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT trace_id, request_id, route, consistency,
                       query_fingerprint, query_plan, requested_scope, as_of,
                       required_authority, canonical_snapshot_outbox_sequence,
                       fts_watermark, vector_watermark, accepted_candidates,
                       rejected_candidates, fallback_used, fallback_reason,
                       abstained, abstention_reason, duration_ms, created_at,
                       created_by_actor_id, minimum_outbox_sequence,
                       causal_wait_outcome, causal_waited_ms,
                       execution_trace, stage_metrics
                FROM milai.retrieval_trace
                WHERE tenant_id = %s AND trace_id = %s
                """,
                (context.tenant_id, trace_id),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "trace_id",
            "request_id",
            "route",
            "consistency",
            "query_fingerprint",
            "query_plan",
            "requested_scope",
            "as_of",
            "required_authority",
            "canonical_snapshot_outbox_sequence",
            "fts_watermark",
            "vector_watermark",
            "accepted_candidates",
            "rejected_candidates",
            "fallback_used",
            "fallback_reason",
            "abstained",
            "abstention_reason",
            "duration_ms",
            "created_at",
            "created_by_actor_id",
            "minimum_outbox_sequence",
            "causal_wait_outcome",
            "causal_waited_ms",
            "execution_trace",
            "stage_metrics",
        )
        return _json_safe(dict(zip(keys, row, strict=True)))


def _projection_state(connection: Any, context: SessionContext) -> ProjectionState:
    row = connection.execute(
        "SELECT milai.retrieval_projection_state(%s, %s)",
        (context.tenant_id, context.actor_id),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise RuntimeError("retrieval projection state returned no object")
    value = row[0]
    return ProjectionState(
        canonical_snapshot_outbox_sequence=int(value["canonical_snapshot_outbox_sequence"]),
        fts_watermark=int(value["fts_watermark"]),
        vector_watermark=int(value["vector_watermark"]),
        fts_dead_letter=bool(value["fts_dead_letter"]),
        vector_dead_letter=bool(value["vector_dead_letter"]),
        evidence_watermark=int(value.get("evidence_watermark", 0)),
        evidence_dead_letter=bool(value.get("evidence_dead_letter", False)),
    )


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
