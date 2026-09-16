"""Official read-only retrieval audit probes.

This entrypoint reuses the production repository and deterministic application
query transforms.  It deliberately stops before span projection, Binding,
RequirementState, Sufficiency, and operator execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from milai.adapters import EmbeddingProvider, EmbeddingUnavailable
from milai.application.acquisition import (
    apply_probe_source_policy,
    probe_query,
    rank_evidence_turns,
)
from milai.application.appointment_composition import (
    normalize_query_time_event_scan,
    prioritize_temporal_evidence,
)
from milai.application.evidence_dense import evidence_turn_projection_version
from milai.domain.acquisition import AcquisitionPlan, AcquisitionProbe
from milai.domain.retrieval import QueryPlan
from milai.domain.retrieval_audit import (
    EvidenceRecordIdentityV01,
    OfficialAuditProbeTraceV01,
    RetrievalDocumentIdentityV01,
    RetrievalOccurrenceV01,
    canonical_sha256,
)
from milai.persistence import DatabaseStatementTimeout, SessionContext
from milai.persistence.retrieval_repository import ProjectionUnavailable

OFFICIAL_AUDIT_EXECUTOR_IDENTITY = "milai-official-retrieval-audit-probe-v0.1"
OFFLINE_CUTOFFS = (8, 16, 32, 64)


class OfficialRetrievalAuditProbeExecutor:
    """Run one widest authorized official call and derive all cut views offline."""

    def __init__(self, repository: object, embedding: EmbeddingProvider) -> None:
        self._repository = repository
        self._embedding = embedding

    def execute_probe(
        self,
        *,
        run_identity: str,
        product_seal_digest: str,
        request_identity: str,
        requirement_id: str,
        channel: str,
        probe: AcquisitionProbe | None,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        context: SessionContext,
        requested_scope: dict[str, object],
        as_of: datetime,
        requested_audit_cap: int,
        snapshot_identity: str,
        scope_digest: str,
        policy_digest: str,
        index_identity: str,
    ) -> OfficialAuditProbeTraceV01:
        if requested_audit_cap < 1 or requested_audit_cap > 2_000:
            raise ValueError("audit cap is outside the verified official repository bound")
        query = probe_query(probe) if probe is not None else channel
        items: list[dict[str, Any]] = []
        disposition, reason = "UNAVAILABLE", "CHANNEL_NOT_AVAILABLE"
        if channel in {"FTS_RAW", "FTS_ENRICHED"}:
            if probe is None:
                disposition, reason = "NOT_INVOKED", "CHANNEL_NOT_ENABLED"
            else:
                method = getattr(self._repository, "search_evidence", None)
                if callable(method):
                    try:
                        raw = method(
                            context,
                            query,
                            requested_scope,
                            as_of,
                            requested_audit_cap,
                        )
                    except ProjectionUnavailable:
                        reason = "INDEX_REPRESENTATION_MISSING"
                    except DatabaseStatementTimeout:
                        disposition, reason = "TIMEOUT", "CHANNEL_NOT_AVAILABLE"
                    else:
                        governed = apply_probe_source_policy(probe, raw)
                        items = rank_evidence_turns(governed, query)
                        disposition, reason = "EXECUTED", "EXECUTED"
                else:
                    reason = "CHANNEL_NOT_AVAILABLE"
        elif channel == "EVIDENCE_DENSE":
            if probe is None:
                disposition, reason = "NOT_INVOKED", "CHANNEL_NOT_ENABLED"
            elif acquisition_plan.global_constraints.event_occurrence_range is not None:
                disposition, reason = "UNAVAILABLE", "TEMPORAL_SCOPE_MISROUTED"
            else:
                method = getattr(self._repository, "search_evidence_dense", None)
                if not callable(method) or self._embedding.identity.projection_dimensions != 128:
                    reason = "INDEX_REPRESENTATION_MISSING"
                else:
                    try:
                        vector = self._embedding.embed(query)
                        payload = method(
                            context,
                            vector,
                            requested_scope,
                            as_of,
                            requested_audit_cap,
                            model_id=self._embedding.identity.model_id,
                            projection_version=evidence_turn_projection_version(
                                self._embedding.identity
                            ),
                            source_observed_range=(
                                acquisition_plan.global_constraints.source_observed_range
                            ),
                        )
                    except (EmbeddingUnavailable, ProjectionUnavailable):
                        reason = "INDEX_REPRESENTATION_MISSING"
                    except DatabaseStatementTimeout:
                        disposition, reason = "TIMEOUT", "CHANNEL_NOT_AVAILABLE"
                    else:
                        raw = payload.get("items") if isinstance(payload, Mapping) else None
                        if (
                            isinstance(payload, Mapping)
                            and payload.get("status") == "COMPLETE"
                            and isinstance(raw, list)
                        ):
                            items = apply_probe_source_policy(probe, raw)
                            disposition, reason = "EXECUTED", "EXECUTED"
                        else:
                            disposition, reason = "PARTIAL", "INDEX_REPRESENTATION_MISSING"
        elif channel == "SOURCE_OBSERVED_RANGE_SCAN":
            bounded = acquisition_plan.global_constraints.source_observed_range
            method = getattr(self._repository, "scan_evidence_range", None)
            if not _closed_open_range(bounded):
                disposition, reason = "NOT_APPLICABLE", "TEMPORAL_SCOPE_MISROUTED"
            elif not callable(method):
                reason = "CHANNEL_NOT_AVAILABLE"
            else:
                assert bounded is not None
                try:
                    payload = method(
                        context,
                        requested_scope,
                        _timestamp(bounded["start"]),
                        _timestamp(bounded["end"]),
                        requested_audit_cap,
                    )
                except ProjectionUnavailable:
                    reason = "INDEX_REPRESENTATION_MISSING"
                except DatabaseStatementTimeout:
                    disposition, reason = "TIMEOUT", "CHANNEL_NOT_AVAILABLE"
                else:
                    raw = payload.get("items") if isinstance(payload, Mapping) else None
                    items = (
                        [dict(item) for item in raw if isinstance(item, Mapping)]
                        if isinstance(raw, list)
                        else []
                    )
                    status = (
                        str(payload.get("status", "BOUNDED_SCAN_INCOMPLETE"))
                        if isinstance(payload, Mapping)
                        else "BOUNDED_SCAN_INCOMPLETE"
                    )
                    disposition = "EXECUTED" if status == "COMPLETE" else "PARTIAL"
                    reason = status
        elif channel == "TEMPORAL_EVENT":
            bounded = acquisition_plan.global_constraints.event_occurrence_range
            method = getattr(self._repository, "search_evidence_event_range", None)
            if not _closed_open_range(bounded):
                disposition, reason = "NOT_APPLICABLE", "TEMPORAL_SCOPE_MISROUTED"
            elif not callable(method):
                reason = "CHANNEL_NOT_AVAILABLE"
            else:
                assert bounded is not None
                try:
                    payload = method(
                        context,
                        requested_scope,
                        _timestamp(bounded["start"]),
                        _timestamp(bounded["end"]),
                        as_of,
                        requested_audit_cap,
                    )
                except ProjectionUnavailable:
                    reason = "INDEX_REPRESENTATION_MISSING"
                except DatabaseStatementTimeout:
                    disposition, reason = "TIMEOUT", "CHANNEL_NOT_AVAILABLE"
                else:
                    if not isinstance(payload, Mapping):
                        disposition, reason = "PARTIAL", "PROOF_VALIDATION_FAILED"
                    else:
                        normalized = normalize_query_time_event_scan(
                            query_plan,
                            payload,
                            expected_range=(
                                _timestamp(bounded["start"]),
                                _timestamp(bounded["end"]),
                            ),
                        )
                        raw = normalized.get("items")
                        normalized_items = (
                            [dict(item) for item in raw if isinstance(item, Mapping)]
                            if isinstance(raw, list)
                            else []
                        )
                        items = prioritize_temporal_evidence(normalized, None)[
                            :requested_audit_cap
                        ]
                        disposition = "EXECUTED"
                        reason = str(
                            normalized.get("event_normalization_status", "PARTIAL")
                        )
                        if not normalized_items and items:
                            raise RuntimeError(
                                "TEMPORAL_AUDIT_NORMALIZATION_IDENTITY_INVALID"
                            )
        else:
            disposition, reason = "NOT_APPLICABLE", "CHANNEL_NOT_ENABLED"
        occurrences = [
            _occurrence(
                run_identity=run_identity,
                request_identity=request_identity,
                requirement_id=requirement_id,
                channel=channel,
                query=query,
                rank=rank,
                item=item,
                scope_digest=scope_digest,
                snapshot_identity=snapshot_identity,
                index_identity=index_identity,
            )
            for rank, item in enumerate(items[:requested_audit_cap], start=1)
            if isinstance(item.get("evidence_id"), str) and isinstance(item.get("source_ref"), str)
        ]
        cut_views = [
            {
                "cutoff": cutoff,
                "status": (
                    "AVAILABLE"
                    if cutoff <= requested_audit_cap
                    else "EXCEEDS_VERIFIED_OFFICIAL_AUDIT_CAP"
                ),
                "occurrence_ids": (
                    [item.occurrence_id for item in occurrences[:cutoff]]
                    if cutoff <= requested_audit_cap
                    else []
                ),
                "source_wide_result_digest": canonical_sha256(
                    [item.occurrence_id for item in occurrences]
                ),
            }
            for cutoff in OFFLINE_CUTOFFS
        ]
        return OfficialAuditProbeTraceV01(
            run_identity=run_identity,
            product_seal_digest=product_seal_digest,
            request_identity=request_identity,
            requirement_id=requirement_id,
            channel=channel,
            official_executor_identity=OFFICIAL_AUDIT_EXECUTOR_IDENTITY,
            repository_identity="milai.persistence.RetrievalRepository",
            index_identity=index_identity,
            snapshot_identity=snapshot_identity,
            scope_digest=scope_digest,
            policy_digest=policy_digest,
            query_digest=canonical_sha256(query),
            requested_audit_cap=requested_audit_cap,
            disposition=disposition,
            reason_code=reason,
            returned_occurrences=occurrences,
            offline_cut_views=cut_views,
            mutations={
                "canonical": False,
                "context": False,
                "seen_region_ledger": False,
                "watermark": False,
            },
            product_binding_consumed=False,
        )


def _occurrence(
    *,
    run_identity: str,
    request_identity: str,
    requirement_id: str,
    channel: str,
    query: str,
    rank: int,
    item: Mapping[str, Any],
    scope_digest: str,
    snapshot_identity: str,
    index_identity: str,
) -> RetrievalOccurrenceV01:
    evidence_id = str(item["evidence_id"])
    source_ref = str(item["source_ref"])
    content_hash = item.get("content_hash")
    if not isinstance(content_hash, str) or len(content_hash) != 64:
        content_hash = canonical_sha256(str(item.get("content", "")))
    occurrence_id = canonical_sha256(
        [run_identity, request_identity, requirement_id, channel, rank, evidence_id]
    )
    score = item.get("relevance_score", item.get("score"))
    raw_score = (
        float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
    )
    return RetrievalOccurrenceV01(
        occurrence_id=occurrence_id,
        request_identity=request_identity,
        requirement_id=requirement_id,
        channel=channel,
        channel_query_digest=canonical_sha256(query),
        channel_query_semantic_summary=" ".join(query.split())[:256],
        normalized_terms=sorted(set(query.casefold().split())),
        generated_feature_ids=["OFFICIAL_AUDIT_WIDE_RESULT"],
        retrieval_document_identity=RetrievalDocumentIdentityV01(
            projection_kind=channel,
            projection_version="official-runtime-current",
            index_identity=index_identity,
            document_id=evidence_id,
            source_locator=source_ref,
            content_digest=content_hash,
        ),
        evidence_record_identity=EvidenceRecordIdentityV01(
            tenant_scope_digest=scope_digest,
            evidence_id=evidence_id,
            source_identity="EVIDENCE_RECORD",
            source_ref=source_ref,
            content_hash=content_hash,
            observed_at=str(item.get("observed_at")) if item.get("observed_at") else None,
            retention_snapshot_digest=canonical_sha256([snapshot_identity, "retention"]),
            permission_snapshot_digest=canonical_sha256([snapshot_identity, "permission"]),
        ),
        raw_rank=rank,
        raw_score=raw_score,
        score_direction="HIGHER_IS_BETTER" if raw_score is not None else "NOT_EXPOSED",
        latency_ms=None,
    )


def _closed_open_range(value: Mapping[str, Any] | None) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("boundary") in {"CLOSED_OPEN", "POINT"}
        and isinstance(value.get("start"), str)
        and isinstance(value.get("end"), str)
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


__all__ = [
    "OFFICIAL_AUDIT_EXECUTOR_IDENTITY",
    "OFFLINE_CUTOFFS",
    "OfficialRetrievalAuditProbeExecutor",
]
