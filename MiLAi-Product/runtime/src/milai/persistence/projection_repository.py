from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.domain.projection_routing import ProjectionAction, ProjectionLane
from milai.domain.retrieval_projection import ProjectionFragment, derive_projection_fragments
from milai.persistence import Database, SessionContext

if TYPE_CHECKING:
    from milai.adapters.blob_store import ErasureProof

ProjectionName = ProjectionLane


@dataclass(frozen=True, slots=True)
class ProjectionEvent:
    outbox_id: UUID
    outbox_sequence: int
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    canonical_commit_seq: int | None
    attempt_count: int
    lease_expires_at: datetime
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvidenceProjectionSource:
    evidence_id: UUID
    storage_uri: str
    content_hash: str
    byte_length: int
    live_readable: bool


@dataclass(frozen=True, slots=True)
class ProjectionLeaseRenewal:
    disposition: Literal["RENEWED", "TERMINAL", "OWNERSHIP_LOST"]
    requested_count: int
    renewed_count: int
    delivered_count: int
    ownership_lost_count: int
    lease_expires_at: datetime | None


class ProjectionOwnershipLost(RuntimeError):
    """The worker no longer owns the durable delivery lease."""


class ProjectionRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def referenced_blob_hashes(self, context: SessionContext) -> set[str]:
        """Return canonical CAS identities visible to the worker tenant."""
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT content_hash
                FROM milai.content_blob
                WHERE tenant_id = %s
                """,
                (context.tenant_id,),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def lease(
        self,
        context: SessionContext,
        projection: ProjectionName,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
    ) -> ProjectionEvent | None:
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.lease_projection_event(%s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    worker_id,
                    lease_seconds,
                    max_attempts,
                ),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        payload = _object(row[0], "lease_projection_event")
        return ProjectionEvent(
            outbox_id=UUID(str(payload["outbox_id"])),
            outbox_sequence=int(payload["outbox_sequence"]),
            event_type=str(payload["event_type"]),
            aggregate_type=str(payload["aggregate_type"]),
            aggregate_id=UUID(str(payload["aggregate_id"])),
            payload=_object(payload["payload"], "outbox payload"),
            canonical_commit_seq=(
                int(payload["canonical_commit_seq"])
                if payload["canonical_commit_seq"] is not None
                else None
            ),
            attempt_count=int(payload["attempt_count"]),
            lease_expires_at=_datetime(payload["lease_expires_at"]),
        )

    def lease_many(
        self,
        context: SessionContext,
        projection: ProjectionName,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        batch_size: int,
    ) -> tuple[ProjectionEvent, ...]:
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.lease_projection_event_batch(%s, %s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    worker_id,
                    lease_seconds,
                    max_attempts,
                    batch_size,
                ),
            ).fetchone()
        if row is None or not isinstance(row[0], list):
            raise RuntimeError("projection batch lease returned a non-array")
        return tuple(_projection_event(item) for item in row[0])

    def renew_many(
        self,
        context: SessionContext,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
        lease_seconds: int,
    ) -> ProjectionLeaseRenewal:
        if not events:
            raise ValueError("projection lease renewal requires at least one event")
        statement_timeout_ms = min(5_000, max(250, lease_seconds * 500))
        with self._database.connection(
            context, statement_timeout_ms=statement_timeout_ms
        ) as connection:
            row = connection.execute(
                """
                SELECT milai.renew_projection_event_batch(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    worker_id,
                    [event.outbox_id for event in events],
                    lease_seconds,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("projection lease renewal returned no result")
        value = _object(row[0], "renew_projection_event_batch")
        disposition = str(value.get("disposition"))
        if disposition not in {"RENEWED", "TERMINAL", "OWNERSHIP_LOST"}:
            raise RuntimeError("projection lease renewal returned an invalid disposition")
        counts = tuple(
            int(value.get(name, -1))
            for name in (
                "requested_count",
                "renewed_count",
                "delivered_count",
                "ownership_lost_count",
            )
        )
        requested, renewed, delivered, ownership_lost = counts
        if (
            requested != len(events)
            or min(counts) < 0
            or renewed + delivered + ownership_lost != requested
        ):
            raise RuntimeError("projection lease renewal returned inconsistent counts")
        expires_at = value.get("lease_expires_at")
        return ProjectionLeaseRenewal(
            disposition=cast(Literal["RENEWED", "TERMINAL", "OWNERSHIP_LOST"], disposition),
            requested_count=requested,
            renewed_count=renewed,
            delivered_count=delivered,
            ownership_lost_count=ownership_lost,
            lease_expires_at=_datetime(expires_at) if expires_at is not None else None,
        )

    def evidence_sources(
        self,
        context: SessionContext,
        events: tuple[ProjectionEvent, ...],
    ) -> dict[UUID, EvidenceProjectionSource]:
        evidence_ids = [
            event.aggregate_id for event in events if event.event_type == "EVIDENCE_INGESTED"
        ]
        if not evidence_ids:
            return {}
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT evidence.evidence_id, blob.storage_uri,
                       evidence.content_hash, blob.byte_length,
                       evidence.revoked_at IS NULL
                         AND evidence.retention_state = 'READABLE'
                         AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
                         AS live_readable
                FROM milai.evidence_record evidence
                JOIN milai.content_blob blob
                  ON blob.tenant_id = evidence.tenant_id
                 AND blob.blob_id = evidence.blob_id
                WHERE evidence.tenant_id = %s
                  AND evidence.evidence_id = ANY(%s::uuid[])
                """,
                (context.tenant_id, evidence_ids),
            ).fetchall()
        return {
            row[0]: EvidenceProjectionSource(
                evidence_id=row[0],
                storage_uri=str(row[1]),
                content_hash=str(row[2]),
                byte_length=int(row[3]),
                live_readable=bool(row[4]),
            )
            for row in rows
        }

    def apply_evidence_batch(
        self,
        context: SessionContext,
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
        content_by_outbox_id: dict[UUID, str],
        *,
        routing_version: str,
        projection_version: str,
    ) -> dict[str, Any]:
        items = [
            {
                "outbox_id": str(event.outbox_id),
                "content": content_by_outbox_id.get(event.outbox_id),
            }
            for event in events
        ]
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.apply_evidence_projection_batch(%s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    worker_id,
                    Jsonb(items),
                    routing_version,
                    projection_version,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Evidence projection batch returned no result")
        return _object(row[0], "apply_evidence_projection_batch")

    def apply_evidence_dense_batch(
        self,
        context: SessionContext,
        embeddings: dict[UUID, list[float]],
        *,
        model_id: str,
        projection_version: str,
    ) -> dict[str, Any]:
        if not embeddings:
            return {"status": "NOT_APPLICABLE", "projected_count": 0}
        if any(len(vector) != 128 for vector in embeddings.values()):
            raise ValueError("Evidence dense projection requires 128-dimensional vectors")
        items = [
            {"evidence_id": str(evidence_id), "embedding": vector}
            for evidence_id, vector in sorted(embeddings.items(), key=lambda item: str(item[0]))
        ]
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.upsert_evidence_dense_128(%s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    Jsonb(items),
                    model_id,
                    projection_version,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Evidence dense projection returned no result")
        return _object(row[0], "upsert_evidence_dense_128")

    def read_evidence_dense_backfill_batch(
        self,
        context: SessionContext,
        *,
        after_evidence_id: UUID | None,
        limit: int,
        model_id: str,
        projection_version: str,
    ) -> list[dict[str, Any]]:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                "SELECT milai.read_evidence_dense_backfill_batch(%s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    after_evidence_id,
                    limit,
                    model_id,
                    projection_version,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Evidence dense backfill returned no result")
        value = _object(row[0], "read_evidence_dense_backfill_batch")
        items = value.get("items")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise RuntimeError("Evidence dense backfill items are invalid")
        return items

    def readiness_status(
        self,
        context: SessionContext,
        target_outbox_ids: tuple[UUID, ...],
        required_projections: tuple[ProjectionName, ...],
        expected_versions: dict[ProjectionName, str],
    ) -> dict[str, Any]:
        with self._database.connection(context, read_only=True) as connection:
            if len(target_outbox_ids) == 1:
                row = connection.execute(
                    "SELECT milai.projection_readiness_status(%s, %s, %s, %s, %s)",
                    (
                        context.tenant_id,
                        context.actor_id,
                        target_outbox_ids[0],
                        list(required_projections),
                        Jsonb(expected_versions),
                    ),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT milai.projection_readiness_status_many(%s, %s, %s, %s, %s)",
                    (
                        context.tenant_id,
                        context.actor_id,
                        list(target_outbox_ids),
                        list(required_projections),
                        Jsonb(expected_versions),
                    ),
                ).fetchone()
        if row is None:
            raise RuntimeError("projection readiness returned no result")
        return _object(row[0], "projection_readiness_status")

    def reconcile_watermark(
        self,
        context: SessionContext,
        projection: ProjectionName,
    ) -> int:
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.reconcile_projection_watermark(%s, %s, %s)",
                (context.tenant_id, context.actor_id, projection),
            ).fetchone()
        if row is None:
            raise RuntimeError("watermark reconciliation returned no result")
        return int(row[0])

    def projection_text(self, context: SessionContext, event: ProjectionEvent) -> str | None:
        raw_version_id = event.payload.get("claim_version_id")
        if raw_version_id is None:
            return None
        try:
            version_id = UUID(str(raw_version_id))
        except ValueError:
            return None
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT concat_ws(' ', claim.subject_id, claim.predicate,
                                  claim.claim_type, version.payload::text)
                FROM milai.claim_version version
                JOIN milai.claim claim
                  ON claim.tenant_id = version.tenant_id
                 AND claim.claim_id = version.claim_id
                WHERE version.tenant_id = %s AND version.claim_version_id = %s
                """,
                (context.tenant_id, version_id),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def projection_fragments(
        self, context: SessionContext, event: ProjectionEvent
    ) -> tuple[ProjectionFragment, ...]:
        raw_version_id = event.payload.get("claim_version_id")
        if raw_version_id is None:
            return ()
        try:
            version_id = UUID(str(raw_version_id))
        except ValueError:
            return ()
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(
                         NULLIF(version.payload ->> 'memory_text', ''),
                         concat_ws(' ', claim.subject_id, claim.predicate,
                                   claim.claim_type, version.payload::text)
                       )
                FROM milai.claim_version version
                JOIN milai.claim claim
                  ON claim.tenant_id = version.tenant_id
                 AND claim.claim_id = version.claim_id
                WHERE version.tenant_id = %s AND version.claim_version_id = %s
                """,
                (context.tenant_id, version_id),
            ).fetchone()
        if row is None:
            return ()
        return derive_projection_fragments(str(row[0]))

    def apply_search(
        self,
        context: SessionContext,
        projection: Literal["fts", "vector"],
        event: ProjectionEvent,
        worker_id: str,
        embedding: list[float] | None,
        *,
        model_id: str = "deterministic-hash-v1",
        projection_version: str = "1",
    ) -> dict[str, Any]:
        with self._database.connection(context) as connection:
            if projection == "vector":
                connection.execute(
                    "SELECT set_config('milai.embedding_model_id', %s, true), "
                    "set_config('milai.embedding_projection_version', %s, true)",
                    (model_id, projection_version),
                )
            row = connection.execute(
                "SELECT milai.apply_search_projection(%s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    event.outbox_id,
                    worker_id,
                    embedding,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("search projection returned no result")
        return _object(row[0], "apply_search_projection")

    def apply_window_search(
        self,
        context: SessionContext,
        projection: Literal["fts", "vector"],
        event: ProjectionEvent,
        worker_id: str,
        fragments: tuple[ProjectionFragment, ...],
        embeddings: list[list[float]] | None,
        *,
        model_id: str,
        projection_version: str,
    ) -> dict[str, Any]:
        if event.event_type != "PURGE_EVIDENCE_DERIVATIVES" and not fragments:
            return {"action": "NO_OP", "reason": "NO_CLAIM_VERSION"}
        if projection == "vector" and event.event_type != "PURGE_EVIDENCE_DERIVATIVES":
            if embeddings is None or len(embeddings) != len(fragments):
                raise ValueError("window vector embeddings must align with fragments")
        calls: list[tuple[ProjectionFragment, list[float] | None]]
        if event.event_type == "PURGE_EVIDENCE_DERIVATIVES":
            calls = [
                (
                    ProjectionFragment(0, "turn", 0, 0, ("memory",), "purge"),
                    None,
                )
            ]
        else:
            calls = [
                (fragment, embeddings[index] if embeddings is not None else None)
                for index, fragment in enumerate(fragments)
            ]
        result: dict[str, Any] | None = None
        with self._database.connection(context) as connection:
            for fragment, embedding in calls:
                row = connection.execute(
                    """
                    SELECT milai.apply_window_search_projection(
                      %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        projection,
                        event.outbox_id,
                        worker_id,
                        fragment.ordinal,
                        fragment.kind,
                        fragment.turn_start,
                        fragment.turn_end,
                        fragment.content_text,
                        list(fragment.roles),
                        embedding,
                        model_id,
                        projection_version,
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError("window search projection returned no result")
                result = _object(row[0], "apply_window_search_projection")
        assert result is not None
        return {**result, "fragment_count": len(fragments)}

    def apply_purge(
        self, context: SessionContext, event: ProjectionEvent, worker_id: str
    ) -> dict[str, Any]:
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.apply_purge_projection(%s, %s, %s, %s)",
                (context.tenant_id, context.actor_id, event.outbox_id, worker_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("purge projection returned no result")
        return _object(row[0], "apply_purge_projection")

    def apply_purge_batch(
        self,
        context: SessionContext,
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
    ) -> dict[UUID, dict[str, Any]]:
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.apply_purge_projection_batch(%s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    worker_id,
                    [event.outbox_id for event in events],
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("purge projection batch returned no result")
        payload = _object(row[0], "apply_purge_projection_batch")
        outcomes = payload.get("outcomes")
        if not isinstance(outcomes, list):
            raise RuntimeError("purge projection batch returned non-array outcomes")
        results: dict[UUID, dict[str, Any]] = {}
        for value in outcomes:
            result = _object(value, "apply_purge_projection_batch outcome")
            outbox_id = UUID(str(result["outbox_id"]))
            results[outbox_id] = result
        if set(results) != {event.outbox_id for event in events}:
            raise RuntimeError("purge projection batch returned incomplete outcomes")
        return results

    def apply_search_purge_batch(
        self,
        context: SessionContext,
        projection: Literal["fts", "vector"],
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
        *,
        routing_version: str,
    ) -> dict[str, Any]:
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT milai.apply_search_purge_projection_batch(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    worker_id,
                    [event.outbox_id for event in events],
                    routing_version,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("search purge projection batch returned no result")
        return _object(row[0], "apply_search_purge_projection_batch")

    def complete_blob_erasure(
        self,
        context: SessionContext,
        blob_id: UUID,
        worker_id: str,
        proof: ErasureProof,
    ) -> None:
        with self._database.connection(context) as connection:
            connection.execute(
                """
                SELECT milai.complete_blob_erasure(
                  %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    blob_id,
                    worker_id,
                    proof.disposition,
                    proof.proof_hash,
                    proof.storage_uri,
                    proof.content_hash,
                ),
            ).fetchone()

    def complete_blob_erasure_batch(
        self,
        context: SessionContext,
        worker_id: str,
        proofs: dict[UUID, ErasureProof],
    ) -> dict[str, Any]:
        items = [
            {
                "blob_id": str(blob_id),
                "disposition": proof.disposition,
                "proof_hash": proof.proof_hash,
                "storage_uri": proof.storage_uri,
                "content_hash": proof.content_hash,
            }
            for blob_id, proof in proofs.items()
        ]
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.complete_blob_erasure_batch(%s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    worker_id,
                    Jsonb(items),
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("blob erasure batch returned no result")
        return _object(row[0], "complete_blob_erasure_batch")

    def record_purge_error(
        self, context: SessionContext, deletion_request_id: UUID, error_code: str
    ) -> None:
        with self._database.connection(context) as connection:
            connection.execute(
                "SELECT milai.record_purge_error(%s, %s, %s, %s)",
                (context.tenant_id, context.actor_id, deletion_request_id, error_code),
            ).fetchone()

    def complete(
        self,
        context: SessionContext,
        projection: ProjectionName,
        event: ProjectionEvent,
        worker_id: str,
        result: dict[str, Any],
    ) -> int:
        result_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self._database.connection(context) as connection:
            row = connection.execute(
                "SELECT milai.complete_projection_event(%s, %s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    event.outbox_id,
                    worker_id,
                    result_hash,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("projection completion returned no watermark")
        return int(row[0])

    def complete_routed(
        self,
        context: SessionContext,
        projection: ProjectionName,
        event: ProjectionEvent,
        worker_id: str,
        result: dict[str, Any],
        *,
        routing_version: str,
        applicability: ProjectionAction,
        handler_outcome: str,
    ) -> int:
        result_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT milai.complete_projection_event_routed(
                  %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    event.outbox_id,
                    worker_id,
                    result_hash,
                    routing_version,
                    applicability,
                    handler_outcome,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("routed projection completion returned no watermark")
        return int(row[0])

    def complete_skipped_batch(
        self,
        context: SessionContext,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
        *,
        routing_version: str,
    ) -> dict[str, Any]:
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT milai.complete_projection_skip_batch(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    worker_id,
                    [event.outbox_id for event in events],
                    routing_version,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("projection skip batch returned no result")
        return _object(row[0], "complete_projection_skip_batch")

    def complete_applied_batch(
        self,
        context: SessionContext,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
        results: dict[UUID, dict[str, Any]],
        *,
        routing_version: str,
    ) -> dict[str, Any]:
        items = [
            {
                "outbox_id": str(event.outbox_id),
                "result_hash": hashlib.sha256(
                    json.dumps(
                        results[event.outbox_id],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "handler_outcome": str(results[event.outbox_id].get("action", "APPLIED"))[:128],
            }
            for event in events
        ]
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT milai.complete_projection_apply_batch(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    worker_id,
                    Jsonb(items),
                    routing_version,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("projection apply batch returned no result")
        return _object(row[0], "complete_projection_apply_batch")

    def metrics_snapshot(self, context: SessionContext) -> dict[str, Any]:
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT delivery.projection_name, event.event_type,
                       COALESCE(delivery.applicability, 'LEGACY') AS applicability,
                       COALESCE(delivery.handler_outcome, 'UNRECORDED') AS handler_outcome,
                       delivery.state, count(*) AS logical_items,
                       COALESCE(sum(delivery.attempt_count), 0) AS attempts,
                       COALESCE(avg(EXTRACT(EPOCH FROM (
                         delivery.delivered_at - event.created_at
                       )) * 1000) FILTER (WHERE delivery.delivered_at IS NOT NULL), 0)
                         AS queue_to_delivery_ms
                FROM milai.projection_delivery delivery
                JOIN milai.outbox_event event
                  ON event.tenant_id = delivery.tenant_id
                 AND event.outbox_id = delivery.outbox_id
                WHERE delivery.tenant_id = %s
                GROUP BY delivery.projection_name, event.event_type,
                         delivery.applicability, delivery.handler_outcome, delivery.state
                ORDER BY delivery.projection_name, event.event_type,
                         delivery.applicability, delivery.handler_outcome, delivery.state
                """,
                (context.tenant_id,),
            ).fetchall()
            watermarks = connection.execute(
                """
                SELECT projection_name, last_contiguous_outbox_sequence
                FROM milai.index_watermark
                WHERE tenant_id = %s ORDER BY projection_name
                """,
                (context.tenant_id,),
            ).fetchall()
            lease_health = connection.execute(
                """
                SELECT
                  count(*) FILTER (WHERE state = 'PROCESSING'),
                  count(*) FILTER (
                    WHERE state = 'PROCESSING'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= CURRENT_TIMESTAMP
                  ),
                  count(*) FILTER (
                    WHERE state <> 'PROCESSING'
                      AND (lease_owner IS NOT NULL OR lease_expires_at IS NOT NULL)
                  )
                FROM milai.projection_delivery
                WHERE tenant_id = %s
                """,
                (context.tenant_id,),
            ).fetchone()
        if lease_health is None:
            raise RuntimeError("projection lease-health query returned no result")
        return {
            "deliveries": [
                {
                    "projection": str(row[0]),
                    "event_type": str(row[1]),
                    "applicability": str(row[2]),
                    "handler_outcome": str(row[3]),
                    "state": str(row[4]),
                    "logical_items": int(row[5]),
                    "attempts": int(row[6]),
                    "queue_to_delivery_ms": float(row[7]),
                }
                for row in rows
            ],
            "watermarks": {str(row[0]): int(row[1]) for row in watermarks},
            "lease_health": {
                "processing_count": int(lease_health[0]),
                "expired_processing_count": int(lease_health[1]),
                "terminal_lease_residue_count": int(lease_health[2]),
            },
        }

    def fail(
        self,
        context: SessionContext,
        projection: ProjectionName,
        event: ProjectionEvent,
        worker_id: str,
        error_code: str,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> str:
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT milai.fail_projection_event(
                  %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    context.tenant_id,
                    context.actor_id,
                    projection,
                    event.outbox_id,
                    worker_id,
                    error_code,
                    max_attempts,
                    retry_delay_seconds,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("projection failure returned no state")
        return str(row[0])


def _object(value: object, source: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{source} returned a non-object")
    return value


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _projection_event(value: object) -> ProjectionEvent:
    payload = _object(value, "lease_projection_event_batch item")
    return ProjectionEvent(
        outbox_id=UUID(str(payload["outbox_id"])),
        outbox_sequence=int(payload["outbox_sequence"]),
        event_type=str(payload["event_type"]),
        aggregate_type=str(payload["aggregate_type"]),
        aggregate_id=UUID(str(payload["aggregate_id"])),
        payload=_object(payload["payload"], "outbox payload"),
        canonical_commit_seq=(
            int(payload["canonical_commit_seq"])
            if payload["canonical_commit_seq"] is not None
            else None
        ),
        attempt_count=int(payload["attempt_count"]),
        lease_expires_at=_datetime(payload["lease_expires_at"]),
        created_at=_datetime(payload["created_at"]),
    )


def safe_worker_error(error: Exception) -> str:
    if isinstance(error, ProjectionOwnershipLost):
        return "LEASE_LOST"
    if isinstance(error, Error):
        primary = error.diag.message_primary or "DATABASE_ERROR"
        if primary.isascii() and primary.replace("_", "").isalnum():
            return primary[:128]
    name = type(error).__name__.upper()
    normalized = "".join(character if character.isalnum() else "_" for character in name)
    return (normalized or "WORKER_ERROR")[:128]


def is_projection_ownership_lost(error: Exception) -> bool:
    return isinstance(error, ProjectionOwnershipLost) or safe_worker_error(error) == "LEASE_LOST"
