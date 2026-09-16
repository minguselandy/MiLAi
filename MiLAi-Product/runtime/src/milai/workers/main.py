from __future__ import annotations

import argparse
import logging
import signal
from threading import Event, Thread
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from psycopg import Error

from milai.adapters import (
    BoundedEmbeddingProvider,
    DeterministicHashEmbedding,
    EmbeddingProvider,
    EmbeddingUnavailable,
    ErasureProof,
    LocalContentAddressedBlobStore,
    OnnxSentenceTransformerEmbedding,
    SentenceTransformerEmbedding,
)
from milai.adapters.blob_store import BlobIntegrityError
from milai.adapters.http_models import HTTPEmbedding
from milai.application.evidence_dense import (
    evidence_turn_embedding_text,
    evidence_turn_projection_version,
)
from milai.config.settings import (
    RuntimeSettings,
    WorkerSettings,
    load_worker_settings,
    prepare_runtime_directories,
)
from milai.domain.projection_routing import ROUTING_VERSION, route_projection_event
from milai.observability import OperationTimer, configure_logging
from milai.persistence import Database, SessionContext
from milai.persistence.projection_repository import (
    ProjectionEvent,
    ProjectionName,
    ProjectionRepository,
    is_projection_ownership_lost,
    safe_worker_error,
)
from milai.workers.projection_batch import ProjectionBatchProcessor


class _ProjectionLeaseHeartbeat:
    """Keep one leased batch owned while its handler performs bounded slow work."""

    def __init__(
        self,
        repository: ProjectionRepository,
        *,
        context: SessionContext,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
        worker_id: str,
        lease_seconds: int,
        metrics: OperationTimer,
        logger: logging.Logger,
    ) -> None:
        self._repository = repository
        self._context = context
        self._projection = projection
        self._events = events
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._metrics = metrics
        self._logger = logger
        self._stop = Event()
        self._thread = Thread(
            target=self._run,
            name=f"projection-lease-{projection}",
            daemon=True,
        )

    def __enter__(self) -> _ProjectionLeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        interval_seconds = max(0.1, min(10.0, self._lease_seconds / 3))
        while not self._stop.wait(interval_seconds):
            try:
                renewal = self._metrics.call(
                    "projection_lease_renewal_ms",
                    self._repository.renew_many,
                    self._context,
                    self._projection,
                    self._events,
                    self._worker_id,
                    self._lease_seconds,
                )
            except Exception as exc:
                self._metrics.increment("projection_lease_renewal_failures")
                self._logger.warning(
                    "projection_lease_renewal_failed",
                    extra={
                        "safe_metadata": {
                            "projection": self._projection,
                            "event_count": len(self._events),
                            "error_code": safe_worker_error(exc),
                        }
                    },
                )
                continue
            self._metrics.increment("projection_lease_renewed_items", renewal.renewed_count)
            if renewal.ownership_lost_count:
                self._metrics.increment(
                    "projection_lease_ownership_lost_items",
                    renewal.ownership_lost_count,
                )
                self._logger.info(
                    "projection_lease_ownership_lost",
                    extra={
                        "safe_metadata": {
                            "projection": self._projection,
                            "event_count": len(self._events),
                            "ownership_lost_count": renewal.ownership_lost_count,
                            "renewed_count": renewal.renewed_count,
                        }
                    },
                )
            if renewal.renewed_count == 0:
                return


class FoundationWorker:
    """Single-process, ordered outbox worker for Lean V1 projections."""

    def __init__(
        self,
        settings: RuntimeSettings | WorkerSettings,
        database: Database,
        *,
        repository: ProjectionRepository | None = None,
        blob_store: LocalContentAddressedBlobStore | None = None,
        embedding: EmbeddingProvider | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._stop = Event()
        self._logger = logging.getLogger(__name__)
        self._repository = repository
        self._blob_store = blob_store
        self._embedding = embedding
        self._worker_id = worker_id or f"local-{uuid4()}"
        self._context = SessionContext(settings.tenant_id, settings.local_actor_id)
        self._metrics = OperationTimer()
        self._projection_batch = (
            ProjectionBatchProcessor(
                repository,
                embedding,
                context=self._context,
                worker_id=self._worker_id,
                batch_size=settings.embedding_batch_size,
                metrics=self._metrics,
            )
            if repository is not None and embedding is not None
            else None
        )

    def request_stop(self) -> None:
        self._stop.set()

    def metrics_snapshot(self) -> dict[str, dict[str, float | int]]:
        return self._metrics.snapshot()

    def run_once(self) -> int:
        self._metrics.call("worker_ping_ms", self._database.ping)
        if self._repository is None:
            self._logger.info("foundation_worker_ready")
            return 0
        processed = 0
        projections = cast(tuple[ProjectionName, ...], ("evidence", "purge", "fts", "vector"))
        for projection in projections:
            projection_processed = 0
            while projection_processed < self._settings.worker_event_limit:
                remaining = self._settings.worker_event_limit - projection_processed
                events = self._metrics.call(
                    "projection_batch_lease_ms",
                    self._repository.lease_many,
                    self._context,
                    projection,
                    self._worker_id,
                    self._settings.worker_lease_seconds,
                    self._settings.worker_max_attempts,
                    min(self._settings.worker_projection_batch_size, remaining),
                )
                if not events:
                    break
                with _ProjectionLeaseHeartbeat(
                    self._repository,
                    context=self._context,
                    projection=projection,
                    events=events,
                    worker_id=self._worker_id,
                    lease_seconds=self._settings.worker_lease_seconds,
                    metrics=self._metrics,
                    logger=self._logger,
                ):
                    if projection == "evidence":
                        with self._metrics.measure("evidence_projection_batch_ms"):
                            self._process_evidence_batch(events)
                    else:
                        self._process_routed_batch(projection, events)
                processed += len(events)
                projection_processed += len(events)
            if projection_processed:
                self._metrics.call(
                    "projection_watermark_reconcile_ms",
                    self._repository.reconcile_watermark,
                    self._context,
                    projection,
                )
        self._logger.info(
            "outbox_worker_cycle",
            extra={
                "safe_metadata": {
                    "processed": processed,
                    "stage_metrics": self.metrics_snapshot(),
                }
            },
        )
        return processed

    def _process_routed_batch(
        self,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
    ) -> None:
        assert self._repository is not None
        skipped = tuple(
            event
            for event in events
            if route_projection_event(projection, event.event_type, event.payload).action
            == "ACK_NOT_APPLICABLE"
        )
        if skipped:
            self._metrics.increment("routing_ack_not_applicable_items", len(skipped))
            try:
                self._metrics.call(
                    "projection_skip_batch_ms",
                    self._repository.complete_skipped_batch,
                    self._context,
                    projection,
                    skipped,
                    self._worker_id,
                    routing_version=ROUTING_VERSION,
                )
            except Exception as exc:
                if not is_projection_ownership_lost(exc):
                    raise
                self._record_ownership_lost(projection, skipped, exc, phase="skip_completion")
        skipped_ids = {event.outbox_id for event in skipped}
        applicable = tuple(event for event in events if event.outbox_id not in skipped_ids)
        if projection in {"fts", "vector"} and applicable:
            self._process_search_events(cast(Literal["fts", "vector"], projection), applicable)
        elif projection == "purge" and applicable:
            with self._metrics.measure("purge_projection_batch_ms"):
                self._process_purge_batch(applicable)
        else:
            for event in applicable:
                with self._metrics.measure(f"{projection}_projection_ms"):
                    self._process(projection, event)

    def _process_search_events(
        self,
        projection: Literal["fts", "vector"],
        events: tuple[ProjectionEvent, ...],
    ) -> None:
        assert self._repository is not None
        index = 0
        while index < len(events):
            event = events[index]
            if event.event_type != "PURGE_EVIDENCE_DERIVATIVES":
                with self._metrics.measure(f"{projection}_projection_ms"):
                    self._process(projection, event)
                index += 1
                continue
            end = index + 1
            while end < len(events) and events[end].event_type == "PURGE_EVIDENCE_DERIVATIVES":
                end += 1
            batch = events[index:end]
            try:
                self._metrics.call(
                    "search_purge_projection_batch_ms",
                    self._repository.apply_search_purge_batch,
                    self._context,
                    projection,
                    batch,
                    self._worker_id,
                    routing_version=ROUTING_VERSION,
                )
                self._metrics.increment("search_purge_projection_batch_items", len(batch))
                self._metrics.increment("routing_apply_items", len(batch))
            except (Error, RuntimeError) as exc:
                self._fail_projection_events(projection, batch, exc)
            index = end

    def _process(self, projection: ProjectionName, event: ProjectionEvent) -> None:
        assert self._repository is not None
        result: dict[str, Any]
        try:
            route = route_projection_event(projection, event.event_type, event.payload)
            self._metrics.increment(f"routing_{route.action.casefold()}_items")
            if route.action == "ACK_NOT_APPLICABLE":
                result = {
                    "action": "EXPLICIT_SKIP",
                    "reason": route.reason,
                    "routing_version": route.routing_version,
                }
                self._metrics.call(
                    "projection_complete_ms",
                    self._repository.complete_routed,
                    self._context,
                    projection,
                    event,
                    self._worker_id,
                    result,
                    routing_version=route.routing_version,
                    applicability=route.action,
                    handler_outcome="EXPLICIT_SKIP",
                )
                return
            if projection in {"fts", "vector"}:
                embedding_values = None
                window_enabled = (
                    self._embedding is not None
                    and self._embedding.identity.projection_dimensions == 128
                )
                if window_enabled:
                    fragments = self._metrics.call(
                        "fragment_derivation_ms",
                        self._repository.projection_fragments,
                        self._context,
                        event,
                    )
                else:
                    fragments = ()
                if projection == "vector" and not window_enabled:
                    if self._embedding is None:
                        raise RuntimeError("embedding adapter is unavailable")
                    text = self._repository.projection_text(self._context, event)
                    if text is not None:
                        self._metrics.increment("embedding_logical_items")
                        self._metrics.increment("embedding_unique_items")
                        self._metrics.increment("embedding_inference_batches")
                        with self._metrics.measure("embedding_inference_ms"):
                            embedding_values = self._embedding.embed(text)
                if projection == "vector" and window_enabled:
                    assert self._embedding is not None
                    assert self._projection_batch is not None
                    batch = self._projection_batch.process(event, fragments)
                    result = {
                        **batch.handler_result,
                        "embedding_logical_items": batch.logical_items,
                        "embedding_unique_items": batch.unique_items,
                        "embedding_inference_batches": batch.inference_batches,
                        "embedding_cache_hits": batch.exact_dedup_hits,
                    }
                else:
                    result = self._metrics.call(
                        "projection_write_ms",
                        self._repository.apply_search,
                        self._context,
                        cast(Literal["fts", "vector"], projection),
                        event,
                        self._worker_id,
                        embedding_values,
                        model_id=(
                            self._embedding.identity.model_id
                            if self._embedding is not None
                            else "deterministic-hash-v1"
                        ),
                        projection_version=(
                            self._embedding.identity.key if self._embedding is not None else "1"
                        ),
                    )
                    if projection == "fts" and window_enabled:
                        assert self._embedding is not None
                        window_result = self._metrics.call(
                            "projection_write_ms",
                            self._repository.apply_window_search,
                            self._context,
                            "fts",
                            event,
                            self._worker_id,
                            fragments,
                            None,
                            model_id=self._embedding.identity.model_id,
                            projection_version=self._embedding.identity.key,
                        )
                        result = {**result, "window": window_result}
            else:
                result = self._metrics.call(
                    "projection_write_ms",
                    self._repository.apply_purge,
                    self._context,
                    event,
                    self._worker_id,
                )
                if result.get("primary_bytes_status") == "PENDING":
                    if self._blob_store is None:
                        raise RuntimeError("blob store is unavailable")
                    deletion_request_id = UUID(str(result["deletion_request_id"]))
                    try:
                        proof = self._blob_store.erase(
                            self._context.tenant_id,
                            str(result["storage_uri"]),
                            str(result["content_hash"]),
                        )
                        self._repository.complete_blob_erasure(
                            self._context,
                            UUID(str(result["blob_id"])),
                            self._worker_id,
                            proof,
                        )
                        result["primary_bytes_status"] = "ERASED"
                        result["erasure_disposition"] = proof.disposition
                        result["erasure_proof_hash"] = proof.proof_hash
                    except Exception as exc:
                        if is_projection_ownership_lost(exc):
                            raise
                        error_code = safe_worker_error(exc)
                        self._repository.record_purge_error(
                            self._context, deletion_request_id, error_code
                        )
                        raise
            self._metrics.call(
                "projection_complete_ms",
                self._repository.complete_routed,
                self._context,
                projection,
                event,
                self._worker_id,
                result,
                routing_version=route.routing_version,
                applicability=route.action,
                handler_outcome=str(result.get("action", "APPLIED"))[:128],
            )
        except Exception as exc:
            if is_projection_ownership_lost(exc):
                self._record_ownership_lost(
                    projection, (event,), exc, phase="handler_or_completion"
                )
                return
            error_code = safe_worker_error(exc)
            try:
                state = self._metrics.call(
                    "projection_fail_ms",
                    self._repository.fail,
                    self._context,
                    projection,
                    event,
                    self._worker_id,
                    error_code,
                    self._settings.worker_max_attempts,
                    self._settings.worker_retry_delay_seconds,
                )
            except Exception as failure_exc:
                if not is_projection_ownership_lost(failure_exc):
                    raise
                self._record_ownership_lost(
                    projection, (event,), failure_exc, phase="failure_bookkeeping"
                )
                return
            self._logger.warning(
                "projection_event_failed",
                extra={
                    "safe_metadata": {
                        "projection": projection,
                        "outbox_id": str(event.outbox_id),
                        "error_code": error_code,
                        "state": state,
                    }
                },
            )

    def _process_purge_batch(self, events: tuple[ProjectionEvent, ...]) -> None:
        assert self._repository is not None
        try:
            results = self._metrics.call(
                "purge_projection_write_batch_ms",
                self._repository.apply_purge_batch,
                self._context,
                events,
                self._worker_id,
            )
        except (Error, RuntimeError) as exc:
            self._fail_projection_events("purge", events, exc)
            return

        ready: list[ProjectionEvent] = []
        proofs: dict[UUID, ErasureProof] = {}
        for event in events:
            result = results[event.outbox_id]
            if result.get("primary_bytes_status") != "PENDING":
                ready.append(event)
                continue
            if self._blob_store is None:
                self._fail_projection_events(
                    "purge", (event,), RuntimeError("blob store is unavailable")
                )
                continue
            deletion_request_id = UUID(str(result["deletion_request_id"]))
            try:
                proof = self._blob_store.erase(
                    self._context.tenant_id,
                    str(result["storage_uri"]),
                    str(result["content_hash"]),
                )
            except (BlobIntegrityError, OSError) as exc:
                self._repository.record_purge_error(
                    self._context, deletion_request_id, safe_worker_error(exc)
                )
                self._fail_projection_events("purge", (event,), exc)
                continue
            proofs[UUID(str(result["blob_id"]))] = proof
            result["primary_bytes_status"] = "ERASED"
            result["erasure_disposition"] = proof.disposition
            result["erasure_proof_hash"] = proof.proof_hash
            ready.append(event)

        if not ready:
            return
        try:
            if proofs:
                self._metrics.call(
                    "blob_erasure_complete_batch_ms",
                    self._repository.complete_blob_erasure_batch,
                    self._context,
                    self._worker_id,
                    proofs,
                )
            ready_events = tuple(ready)
            self._metrics.call(
                "projection_complete_batch_ms",
                self._repository.complete_applied_batch,
                self._context,
                "purge",
                ready_events,
                self._worker_id,
                results,
                routing_version=ROUTING_VERSION,
            )
            self._metrics.increment("purge_projection_batch_items", len(ready_events))
        except (Error, RuntimeError) as exc:
            if is_projection_ownership_lost(exc):
                self._record_ownership_lost("purge", tuple(ready), exc, phase="batch_completion")
                return
            error_code = safe_worker_error(exc)
            for event in ready:
                result = results[event.outbox_id]
                blob_id = result.get("blob_id")
                if blob_id is None or UUID(str(blob_id)) not in proofs:
                    continue
                self._repository.record_purge_error(
                    self._context,
                    UUID(str(result["deletion_request_id"])),
                    error_code,
                )
            self._fail_projection_events("purge", tuple(ready), exc)

    def _fail_projection_events(
        self,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
        error: Exception,
    ) -> None:
        assert self._repository is not None
        if is_projection_ownership_lost(error):
            self._record_ownership_lost(
                projection, events, error, phase="handler_or_batch_completion"
            )
            return
        error_code = safe_worker_error(error)
        states: set[str] = set()
        ownership_lost = 0
        for event in events:
            try:
                states.add(
                    self._metrics.call(
                        "projection_fail_ms",
                        self._repository.fail,
                        self._context,
                        projection,
                        event,
                        self._worker_id,
                        error_code,
                        self._settings.worker_max_attempts,
                        self._settings.worker_retry_delay_seconds,
                    )
                )
            except Exception as failure_exc:
                if not is_projection_ownership_lost(failure_exc):
                    raise
                ownership_lost += 1
                self._record_ownership_lost(
                    projection,
                    (event,),
                    failure_exc,
                    phase="failure_bookkeeping",
                )
        self._logger.warning(
            "projection_batch_failed",
            extra={
                "safe_metadata": {
                    "projection": projection,
                    "event_count": len(events),
                    "first_outbox_id": str(events[0].outbox_id),
                    "error_code": error_code,
                    "states": sorted(states),
                    "ownership_lost_count": ownership_lost,
                }
            },
        )

    def _record_ownership_lost(
        self,
        projection: ProjectionName,
        events: tuple[ProjectionEvent, ...],
        error: Exception,
        *,
        phase: str,
    ) -> None:
        self._metrics.increment("projection_ownership_lost_dispositions")
        self._metrics.increment("projection_ownership_lost_items", len(events))
        self._logger.info(
            "projection_ownership_lost_nonfatal",
            extra={
                "safe_metadata": {
                    "projection": projection,
                    "event_count": len(events),
                    "first_outbox_id": str(events[0].outbox_id),
                    "phase": phase,
                    "disposition": "OWNERSHIP_LOST",
                    "error_code": safe_worker_error(error),
                }
            },
        )

    def _process_evidence_batch(self, events: tuple[ProjectionEvent, ...]) -> None:
        assert self._repository is not None
        owned_outbox_ids = {event.outbox_id for event in events}
        try:
            sources = self._repository.evidence_sources(self._context, events)
            content_by_outbox_id: dict[UUID, str] = {}
            batch_events: list[ProjectionEvent] = []
            for event in events:
                route = route_projection_event("evidence", event.event_type, event.payload)
                self._metrics.increment(f"routing_{route.action.casefold()}_items")
                if event.event_type != "EVIDENCE_INGESTED":
                    batch_events.append(event)
                    continue
                source = sources.get(event.aggregate_id)
                if source is None:
                    raise RuntimeError("Evidence projection source is unavailable")
                if not source.live_readable:
                    self._metrics.call(
                        "projection_complete_ms",
                        self._repository.complete_routed,
                        self._context,
                        "evidence",
                        event,
                        self._worker_id,
                        {
                            "action": "LIVE_GATE_REJECTED",
                            "reason": "EVIDENCE_NOT_LIVE_READABLE",
                            "routing_version": route.routing_version,
                        },
                        routing_version=route.routing_version,
                        applicability=route.action,
                        handler_outcome="LIVE_GATE_REJECTED",
                    )
                    owned_outbox_ids.discard(event.outbox_id)
                    self._metrics.increment("evidence_live_gate_rejected_items")
                    continue
                if self._blob_store is None:
                    raise RuntimeError("blob store is unavailable")
                raw = self._blob_store.read(
                    self._context.tenant_id,
                    source.storage_uri,
                    source.content_hash,
                    source.byte_length,
                )
                content_by_outbox_id[event.outbox_id] = raw.decode("utf-8")
                batch_events.append(event)
            if not batch_events:
                return
            dense_embeddings: dict[UUID, list[float]] = {}
            if (
                self._embedding is not None
                and self._embedding.identity.projection_dimensions == 128
            ):
                dense_sources = [
                    (event.aggregate_id, content_by_outbox_id[event.outbox_id])
                    for event in batch_events
                    if event.event_type == "EVIDENCE_INGESTED"
                    and event.outbox_id in content_by_outbox_id
                ]
                if dense_sources:
                    dense_batch_count = (
                        len(dense_sources) + self._settings.embedding_batch_size - 1
                    ) // self._settings.embedding_batch_size
                    self._metrics.increment("embedding_logical_items", len(dense_sources))
                    self._metrics.increment("embedding_unique_items", len(dense_sources))
                    self._metrics.increment("embedding_inference_batches", dense_batch_count)
                    try:
                        with self._metrics.measure("evidence_dense_embedding_ms"):
                            vectors = self._embedding.embed_many(
                                [
                                    evidence_turn_embedding_text(content)
                                    for _evidence_id, content in dense_sources
                                ],
                                self._settings.embedding_batch_size,
                            )
                    except EmbeddingUnavailable:
                        self._metrics.increment("evidence_dense_embedding_failed")
                    else:
                        if len(vectors) != len(dense_sources):
                            raise RuntimeError("Evidence dense embedding cardinality drifted")
                        dense_embeddings = {
                            evidence_id: vector
                            for (evidence_id, _content), vector in zip(
                                dense_sources, vectors, strict=True
                            )
                        }
            result = self._metrics.call(
                "evidence_projection_write_ms",
                self._repository.apply_evidence_batch,
                self._context,
                tuple(batch_events),
                self._worker_id,
                content_by_outbox_id,
                routing_version=ROUTING_VERSION,
                projection_version="evidence-search-v1",
            )
            owned_outbox_ids.difference_update(event.outbox_id for event in batch_events)
            if dense_embeddings:
                assert self._embedding is not None
                try:
                    self._metrics.call(
                        "evidence_dense_projection_write_ms",
                        self._repository.apply_evidence_dense_batch,
                        self._context,
                        dense_embeddings,
                        model_id=self._embedding.identity.model_id,
                        projection_version=evidence_turn_projection_version(
                            self._embedding.identity
                        ),
                    )
                except (Error, RuntimeError, ValueError) as exc:
                    self._metrics.increment("evidence_dense_projection_failed")
                    self._logger.warning(
                        "evidence_dense_projection_incomplete",
                        extra={
                            "safe_metadata": {
                                "event_count": len(dense_embeddings),
                                "error_code": safe_worker_error(exc),
                            }
                        },
                    )
            outcomes = result.get("outcomes")
            if isinstance(outcomes, list):
                for outcome in outcomes:
                    if isinstance(outcome, dict):
                        name = str(outcome.get("outcome", "UNKNOWN")).casefold()
                        self._metrics.increment(f"evidence_{name}_items")
        except (BlobIntegrityError, Error, OSError, RuntimeError, UnicodeDecodeError) as exc:
            error_code = safe_worker_error(exc)
            owned_events = tuple(event for event in events if event.outbox_id in owned_outbox_ids)
            if owned_events:
                self._fail_projection_events("evidence", owned_events, exc)
            self._logger.warning(
                "evidence_projection_batch_failed",
                extra={
                    "safe_metadata": {
                        "event_count": len(events),
                        "first_outbox_id": str(events[0].outbox_id),
                        "error_code": error_code,
                    }
                },
            )

    def run(self) -> None:
        while not self._stop.is_set():
            # A bounded cycle can leave eligible deliveries queued. Polling delay
            # belongs to an idle cycle, not between rounds of known work.
            if self.run_once() == 0 and self._stop.wait(
                self._settings.worker_poll_interval_seconds
            ):
                break


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MiLAi Lean V1 background worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate dependencies without leasing or processing queue jobs",
    )
    mode.add_argument(
        "--once",
        action="store_true",
        help="process one bounded worker cycle and exit",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    settings = load_worker_settings()
    prepare_runtime_directories(settings)
    configure_logging(settings.log_level, settings.log_format)
    database = Database(
        settings,
        dsn=_worker_dsn(settings),
        expected_role="milai_worker",
    )
    embedding_provider = _embedding_provider(settings)
    if settings.embedding_prewarm or args.check:
        warmup = embedding_provider.warmup()
        logging.getLogger(__name__).info(
            "embedding_warmup",
            extra={
                "safe_metadata": {
                    "state": warmup.state,
                    "duration_ms": warmup.duration_ms,
                    "provider": warmup.provider,
                    "model_id": warmup.model_id,
                    "error_code": warmup.error_code,
                }
            },
        )
    blob_store = LocalContentAddressedBlobStore(
        settings.blob_root,
        kek=settings.blob_kek,
        key_reference=settings.blob_key_reference,
        allow_plaintext_read=settings.data_mode != "LOCAL_PERSONAL_DATA",
    )

    if args.check:
        try:
            database.ping()
            logging.getLogger(__name__).info(
                "foundation_worker_dependencies_ready",
                extra={"safe_metadata": {"queue_mutated": False}},
            )
        finally:
            database.close()
        return

    repository = ProjectionRepository(database)
    worker_context = SessionContext(settings.tenant_id, settings.local_actor_id)
    worker = FoundationWorker(
        settings,
        database,
        repository=repository,
        blob_store=blob_store,
        embedding=embedding_provider,
    )
    referenced_hashes = repository.referenced_blob_hashes(worker_context)
    reconciliation = blob_store.reconcile_orphans(
        settings.tenant_id,
        referenced_hashes,
    )
    logging.getLogger(__name__).info(
        "blob_orphan_reconciliation",
        extra={"safe_metadata": reconciliation},
    )

    def stop_worker(_signum: int, _frame: object) -> None:
        worker.request_stop()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    try:
        worker.run_once() if args.once else worker.run()
    finally:
        database.close()


def _worker_dsn(settings: WorkerSettings) -> str:
    return settings.worker_database_dsn


def _embedding_provider(
    settings: RuntimeSettings | WorkerSettings,
) -> BoundedEmbeddingProvider:
    provider: EmbeddingProvider
    if settings.embedding_provider == "http_embeddings":
        assert settings.embedding_endpoint is not None
        assert settings.embedding_model_revision is not None
        provider = HTTPEmbedding(
            settings.embedding_endpoint,
            model_id=settings.embedding_model_id,
            revision=settings.embedding_model_revision,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
            timeout=settings.embedding_http_timeout_seconds,
        )
    elif settings.embedding_provider == "onnx_sentence_transformer":
        assert settings.embedding_model_path is not None
        provider = OnnxSentenceTransformerEmbedding(
            settings.embedding_model_path,
            model_id=settings.embedding_model_id,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
        )
    elif settings.embedding_provider == "sentence_transformers":
        assert settings.embedding_model_path is not None
        provider = SentenceTransformerEmbedding(
            settings.embedding_model_path,
            model_id=settings.embedding_model_id,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
        )
    else:
        provider = DeterministicHashEmbedding()
    return BoundedEmbeddingProvider(
        provider,
        max_concurrency=settings.embedding_max_concurrency,
        queue_timeout_seconds=(settings.embedding_http_timeout_seconds
                               if settings.embedding_provider == "http_embeddings" else None),
    )
