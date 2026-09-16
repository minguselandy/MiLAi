"""Default-off, process-local Formation projection for product canaries.

The projection is deliberately noncanonical and non-durable.  It may select
source Evidence identities, but request-time database governance remains the
only authority that can hydrate those identities into retrieval candidates.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any, Literal
from uuid import UUID

from milai.application.evidence import EvidenceIngested
from milai.application.formation_engine import DEFAULT_FORMATION_ENGINE
from milai.application.formation_generalization import (
    PRODUCER_IDENTITY,
    FormationGeneralizationError,
    GeneralizedFormationBundle,
)
from milai.application.formation_recollection import (
    FormationRecollectionError,
    recollect_with_formation,
)
from milai.domain.evidence import EvidenceIngestRequest
from milai.domain.formation_artifact import (
    FormationEntityCandidateV01,
    FormationEventCandidateV01,
)
from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateTransitionV01,
)
from milai.domain.memory_formation import MemoryFormationBundleV01
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext

FormationProjectionMode = Literal["OFF", "SHADOW", "CANARY"]
FormationSelectionStatus = Literal["SELECTED", "NO_MATCH", "RAW_FALLBACK"]

PROJECTION_IDENTITY = "formation-sidecar-inmemory-v0.2"
PROJECTION_SCHEMA_VERSION = "formation-source-selection-v0.2"
_MAX_SOURCES_PER_PARTITION = 1024
_MAX_SELECTED_EVIDENCE = 24


@dataclass(frozen=True, slots=True, order=True)
class FormationPartitionKey:
    tenant_id: UUID
    project_id: str
    subject_id: str


@dataclass(frozen=True, slots=True)
class FormationSemanticProjection:
    """Internal query-selected artifacts; ``safe_trace`` never serializes them."""

    state_assertions: tuple[FormationStateAssertionV01, ...] = ()
    state_transitions: tuple[FormationStateTransitionV01, ...] = ()
    event_candidates: tuple[FormationEventCandidateV01, ...] = ()
    entity_candidates: tuple[FormationEntityCandidateV01, ...] = ()


@dataclass(frozen=True, slots=True)
class FormationProjectionSelection:
    status: FormationSelectionStatus
    reason_code: str
    evidence_ids: tuple[str, ...] = ()
    project_id: str | None = None
    subject_id: str | None = None
    source_count: int = 0
    required_facets: tuple[str, ...] = ()
    covered_facets: tuple[str, ...] = ()
    formation_complete: bool = False
    projection_identity: str = PROJECTION_IDENTITY
    projection_schema_version: str = PROJECTION_SCHEMA_VERSION
    projection_digest: str | None = None
    source_snapshot_digest: str | None = None
    source_watermark_digest: str | None = None
    access_snapshot_digest: str | None = None
    build_epoch: int | None = None
    canonical_mutation: bool = False
    model_calls: int = 0
    semantic_projection: FormationSemanticProjection | None = None

    def safe_trace(self) -> dict[str, object]:
        """Return content-free diagnostic material suitable for persisted traces."""

        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "selected_source_count": len(self.evidence_ids),
            "partition_source_count": self.source_count,
            "project_id": self.project_id,
            "subject_id": self.subject_id,
            "required_facets": list(self.required_facets),
            "covered_facets": list(self.covered_facets),
            "formation_complete": self.formation_complete,
            "projection_identity": self.projection_identity,
            "projection_schema_version": self.projection_schema_version,
            "projection_digest": self.projection_digest,
            "source_snapshot_digest": self.source_snapshot_digest,
            "source_watermark_digest": self.source_watermark_digest,
            "access_snapshot_digest": self.access_snapshot_digest,
            "build_epoch": self.build_epoch,
            "canonical_mutation": False,
            "model_calls": 0,
        }


@dataclass(frozen=True, slots=True)
class _Partition:
    key: FormationPartitionKey
    sources: tuple[dict[str, Any], ...]
    bundle: GeneralizedFormationBundle
    episode_bundle: MemoryFormationBundleV01
    source_watermark_digest: str
    access_snapshot_digest: str
    projection_digest: str
    build_epoch: int


@dataclass(frozen=True, slots=True)
class _PendingPartition:
    """Raw-preserving source snapshot awaiting one query-time Formation build."""

    key: FormationPartitionKey
    sources: tuple[dict[str, Any], ...]
    previous: _Partition | None


class FormationProjectionStore:
    """Thread-safe ephemeral Formed sidecar with Raw-authority fallbacks."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._partitions: dict[
            FormationPartitionKey, _Partition | _PendingPartition
        ] = {}
        self._evidence_partition: dict[tuple[UUID, str], FormationPartitionKey] = {}
        self._failures: dict[FormationPartitionKey, str] = {}

    def observe_ingest(
        self,
        context: SessionContext,
        request: EvidenceIngestRequest,
        result: EvidenceIngested,
    ) -> None:
        """Observe a committed ingest; ineligible Evidence stays on the Raw path."""

        source = _formation_source(request, result)
        if source is None:
            return
        key = FormationPartitionKey(
            tenant_id=context.tenant_id,
            project_id=str(source["scope_id"]),
            subject_id=request.subject_id,
        )
        evidence_key = (context.tenant_id, str(result.evidence_id))
        with self._lock:
            existing_key = self._evidence_partition.get(evidence_key)
            if existing_key is not None and existing_key != key:
                self._failures[key] = "FORMATION_EVIDENCE_PARTITION_COLLISION"
                return
            existing = self._partitions.get(key)
            sources_by_id = {
                str(item["evidence_id"]): dict(item)
                for item in (existing.sources if existing is not None else ())
            }
            evidence_id = str(result.evidence_id)
            if sources_by_id.get(evidence_id) == source:
                return
            if evidence_id in sources_by_id:
                self._failures[key] = "FORMATION_EVIDENCE_IDENTITY_COLLISION"
                return
            if len(sources_by_id) >= _MAX_SOURCES_PER_PARTITION:
                self._failures[key] = "FORMATION_PARTITION_SOURCE_LIMIT"
                return
            sources_by_id[evidence_id] = source
            previous = existing.previous if isinstance(existing, _PendingPartition) else existing
            self._partitions[key] = _PendingPartition(
                key=key,
                sources=_ordered_sources(tuple(sources_by_id.values())),
                previous=previous,
            )
            self._evidence_partition[evidence_key] = key
            self._failures.pop(key, None)

    def revoke(self, context: SessionContext, evidence_id: UUID) -> None:
        """Invalidate one committed source and deterministically rebuild its partition."""

        evidence_key = (context.tenant_id, str(evidence_id))
        with self._lock:
            key = self._evidence_partition.pop(evidence_key, None)
            if key is None:
                return
            existing = self._partitions.get(key)
            if existing is None:
                self._failures.pop(key, None)
                return
            sources = tuple(
                item for item in existing.sources if item["evidence_id"] != str(evidence_id)
            )
            if not sources:
                self._partitions.pop(key, None)
                self._failures.pop(key, None)
                return
            previous = existing.previous if isinstance(existing, _PendingPartition) else existing
            self._partitions[key] = _PendingPartition(
                key=key,
                sources=_ordered_sources(sources),
                previous=previous,
            )
            self._failures.pop(key, None)

    def drop_project(self, context: SessionContext, project_id: str) -> None:
        """Fail closed when a namespace cleanup has been accepted."""

        with self._lock:
            keys = [
                key
                for key in self._partitions
                if key.tenant_id == context.tenant_id and key.project_id == project_id
            ]
            for key in keys:
                partition = self._partitions.pop(key)
                for source in partition.sources:
                    self._evidence_partition.pop(
                        (context.tenant_id, str(source["evidence_id"])),
                        None,
                    )
                self._failures.pop(key, None)

    def select(
        self,
        context: SessionContext,
        request: RetrievalRequest,
    ) -> FormationProjectionSelection:
        """Select source IDs plus internal artifacts; traces remain content-free."""

        project_id = _single_requested_project(request.requested_scope)
        if project_id is None:
            return _fallback("FORMATION_PROJECT_SCOPE_NOT_EXACT")
        with self._lock:
            candidates = [
                partition
                for key, partition in self._partitions.items()
                if key.tenant_id == context.tenant_id and key.project_id == project_id
            ]
            subject_hints = set(request.entities)
            if request.subject_id is not None:
                subject_hints.add(request.subject_id)
            matched = [
                partition for partition in candidates if partition.key.subject_id in subject_hints
            ]
            if matched:
                candidates = matched
            if not candidates:
                return _fallback("FORMATION_PARTITION_NOT_FOUND", project_id=project_id)
            if len(candidates) != 1:
                return _fallback("FORMATION_SUBJECT_AMBIGUOUS", project_id=project_id)
            partition = candidates[0]
            failure = self._failures.get(partition.key)
            if failure is not None:
                return _fallback(
                    failure,
                    project_id=project_id,
                    subject_id=partition.key.subject_id,
                )
            sources = tuple(
                dict(item)
                for item in partition.sources
                if _source_visible_as_of(item, request.as_of)
            )
            if not sources:
                return _fallback(
                    "FORMATION_NO_SOURCES_AS_OF",
                    project_id=project_id,
                    subject_id=partition.key.subject_id,
                )
            try:
                if isinstance(partition, _PendingPartition):
                    previous = (
                        partition.previous
                        if len(sources) == len(partition.sources)
                        else None
                    )
                    built = _build_partition(partition.key, sources, previous=previous)
                    if len(sources) == len(partition.sources):
                        self._partitions[partition.key] = built
                    partition = built
                elif len(sources) != len(partition.sources):
                    partition = _build_partition(partition.key, sources, previous=None)
            except (FormationGeneralizationError, ValueError, TypeError):
                return _fallback(
                    "FORMATION_AS_OF_VIEW_BUILD_FAILED",
                    project_id=project_id,
                    subject_id=partition.key.subject_id,
                )

        try:
            recollection = recollect_with_formation(
                query=request.query or "",
                formation=partition.bundle.formation,
                state_changes=partition.bundle.state_changes,
                source_records=sources,
                raw_candidate_evidence_ids=(),
                representation="FORMED_ONLY",
            )
        except (FormationRecollectionError, ValueError, TypeError):
            return _partition_result(
                partition,
                status="RAW_FALLBACK",
                reason_code="FORMATION_SELECTION_FAILED",
            )
        selected = tuple(recollection.accepted_evidence_ids[:_MAX_SELECTED_EVIDENCE])
        reason_code = "FORMATION_SOURCES_SELECTED"
        if not selected:
            selected = _episode_selected_evidence_ids(
                partition.episode_bundle,
                request.query or "",
            )
            if selected:
                reason_code = "FORMATION_EPISODE_SOURCES_SELECTED"
        return _partition_result(
            partition,
            status="SELECTED" if selected else "NO_MATCH",
            reason_code=reason_code if selected else "FORMATION_NO_MATCH",
            evidence_ids=selected,
            required_facets=tuple(recollection.required_facets),
            covered_facets=tuple(recollection.covered_facets),
            formation_complete=recollection.complete,
            semantic_projection=_selected_semantic_projection(
                partition.bundle,
                evidence_ids=set(selected),
                state_assertion_digests=set(recollection.selected_state_assertion_digests),
                state_transition_digests=set(recollection.selected_state_transition_digests),
                event_candidate_digests=set(recollection.selected_event_candidate_digests),
                entity_candidate_digests=set(recollection.selected_entity_candidate_digests),
            ),
        )


def _formation_source(
    request: EvidenceIngestRequest,
    result: EvidenceIngested,
) -> dict[str, Any] | None:
    permission = dict(request.permission_snapshot)
    projects = permission.get("project_ids")
    if (
        request.speaker not in {"user", "assistant"}
        or request.source_context is None
        or request.retention_state != "READABLE"
        or permission.get("readable") is not True
        or not isinstance(projects, list)
        or len(projects) != 1
        or not isinstance(projects[0], str)
        or not projects[0]
    ):
        return None
    return {
        "evidence_id": str(result.evidence_id),
        "source_ref": request.source_ref,
        "scope_id": projects[0],
        "subject_id": request.subject_id,
        "speaker": request.speaker,
        "content": request.content,
        "content_hash": hashlib.sha256(request.content.encode("utf-8")).hexdigest(),
        "observed_at": request.observed_at.isoformat(),
        "source_context": request.source_context.model_dump(mode="json"),
        "session_id": request.source_context.session_id,
        "permission_snapshot": permission,
        "retention_state": request.retention_state,
        "access_decision": "ALLOWED",
        "revoked_at": None,
    }


def _ordered_sources(
    sources: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        sorted(
            (dict(item) for item in sources),
            key=lambda item: (str(item["source_ref"]), str(item["evidence_id"])),
        )
    )


def _build_partition(
    key: FormationPartitionKey,
    sources: tuple[dict[str, Any], ...],
    *,
    previous: _Partition | None,
) -> _Partition:
    ordered = _ordered_sources(sources)
    engine_result = DEFAULT_FORMATION_ENGINE.build(ordered)
    bundle = engine_result.generalized
    source_watermark_digest = canonical_sha256(
        [
            {
                "evidence_id": item["evidence_id"],
                "content_hash": item["content_hash"],
                "observed_at": item["observed_at"],
            }
            for item in ordered
        ]
    )
    access_snapshot_digest = canonical_sha256(
        [
            {
                "evidence_id": item["evidence_id"],
                "permission_snapshot": item["permission_snapshot"],
                "retention_state": item["retention_state"],
            }
            for item in ordered
        ]
    )
    projection_material: Mapping[str, object] = {
        "projection_identity": PROJECTION_IDENTITY,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "tenant_id": str(key.tenant_id),
        "project_id": key.project_id,
        "subject_id": key.subject_id,
        "source_snapshot_digest": bundle.formation.source_snapshot_digest,
        "source_watermark_digest": source_watermark_digest,
        "access_snapshot_digest": access_snapshot_digest,
        "producer_identity": PRODUCER_IDENTITY,
    }
    projection_digest = canonical_sha256(projection_material)
    build_epoch = (
        previous.build_epoch
        if previous is not None and previous.projection_digest == projection_digest
        else (previous.build_epoch + 1 if previous is not None else 1)
    )
    return _Partition(
        key=key,
        sources=ordered,
        bundle=bundle,
        episode_bundle=engine_result.episode.bundle,
        source_watermark_digest=source_watermark_digest,
        access_snapshot_digest=access_snapshot_digest,
        projection_digest=projection_digest,
        build_epoch=build_epoch,
    )


_EPISODE_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_EPISODE_STOP = frozenset(
    {
        "the",
        "and",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
        "did",
        "was",
        "were",
        "have",
        "has",
        "had",
        "that",
        "this",
        "with",
        "from",
        "about",
        "my",
        "your",
        "our",
    }
)


def _episode_selected_evidence_ids(
    bundle: MemoryFormationBundleV01,
    query: str,
) -> tuple[str, ...]:
    """Select whole SemanticEpisodes; never truncate a dialogue unit."""

    terms = {
        token
        for token in _EPISODE_WORD.findall(query.casefold())
        if len(token) > 2 and token not in _EPISODE_STOP
    }
    ranked: list[tuple[int, str, tuple[str, ...]]] = []
    for episode in bundle.episode_candidates:
        score = len(terms.intersection(episode.topic_terms))
        if score <= 0:
            continue
        ids = tuple(span.evidence_id for span in episode.source_spans)
        ranked.append((score, episode.episode_digest, ids))
    selected: list[str] = []
    for _score, _digest, ids in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if len(selected) + len(ids) > _MAX_SELECTED_EVIDENCE:
            continue
        selected.extend(ids)
    return tuple(dict.fromkeys(selected))


def _single_requested_project(scope: Mapping[str, object]) -> str | None:
    projects = scope.get("project_ids")
    if (
        isinstance(projects, list)
        and len(projects) == 1
        and isinstance(projects[0], str)
        and projects[0]
    ):
        return projects[0]
    return None


def _source_visible_as_of(source: Mapping[str, object], as_of: datetime) -> bool:
    observed_at = source.get("observed_at")
    if not isinstance(observed_at, str):
        return False
    try:
        observed = datetime.fromisoformat(observed_at)
    except ValueError:
        return False
    return observed.tzinfo is not None and observed <= as_of


def _partition_result(
    partition: _Partition,
    *,
    status: FormationSelectionStatus,
    reason_code: str,
    evidence_ids: tuple[str, ...] = (),
    required_facets: tuple[str, ...] = (),
    covered_facets: tuple[str, ...] = (),
    formation_complete: bool = False,
    semantic_projection: FormationSemanticProjection | None = None,
) -> FormationProjectionSelection:
    return FormationProjectionSelection(
        status=status,
        reason_code=reason_code,
        evidence_ids=evidence_ids,
        project_id=partition.key.project_id,
        subject_id=partition.key.subject_id,
        source_count=len(partition.sources),
        required_facets=required_facets,
        covered_facets=covered_facets,
        formation_complete=formation_complete,
        projection_digest=partition.projection_digest,
        source_snapshot_digest=partition.bundle.formation.source_snapshot_digest,
        source_watermark_digest=partition.source_watermark_digest,
        access_snapshot_digest=partition.access_snapshot_digest,
        build_epoch=partition.build_epoch,
        semantic_projection=semantic_projection,
    )


def _selected_semantic_projection(
    bundle: GeneralizedFormationBundle,
    *,
    evidence_ids: set[str],
    state_assertion_digests: set[str],
    state_transition_digests: set[str],
    event_candidate_digests: set[str],
    entity_candidate_digests: set[str],
) -> FormationSemanticProjection:
    """Keep only artifacts selected by recollection and rooted in selected Evidence."""

    return FormationSemanticProjection(
        state_assertions=tuple(
            item
            for item in bundle.state_changes.assertions
            if item.artifact_digest in state_assertion_digests
            and item.span.evidence_id in evidence_ids
        ),
        state_transitions=tuple(
            item
            for item in bundle.state_changes.transitions
            if item.artifact_digest in state_transition_digests
            and item.span.evidence_id in evidence_ids
        ),
        event_candidates=tuple(
            item
            for item in bundle.formation.event_candidates
            if item.artifact_digest in event_candidate_digests
            and item.span.evidence_id in evidence_ids
        ),
        entity_candidates=tuple(
            item
            for item in bundle.formation.entity_candidates
            if item.artifact_digest in entity_candidate_digests
            and item.span.evidence_id in evidence_ids
        ),
    )


def _fallback(
    reason_code: str,
    *,
    project_id: str | None = None,
    subject_id: str | None = None,
) -> FormationProjectionSelection:
    return FormationProjectionSelection(
        status="RAW_FALLBACK",
        reason_code=reason_code,
        project_id=project_id,
        subject_id=subject_id,
    )


__all__ = [
    "PROJECTION_IDENTITY",
    "PROJECTION_SCHEMA_VERSION",
    "FormationProjectionMode",
    "FormationProjectionSelection",
    "FormationProjectionStore",
    "FormationSemanticProjection",
]
