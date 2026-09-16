"""Bounded, idempotent rebuild for the optional Raw Evidence dense projection."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from milai.adapters import EmbeddingProvider
from milai.application.evidence_dense import (
    evidence_turn_embedding_text,
    evidence_turn_projection_version,
)
from milai.persistence import SessionContext
from milai.persistence.projection_repository import ProjectionRepository


def rebuild_evidence_dense(
    repository: ProjectionRepository,
    context: SessionContext,
    embedding: EmbeddingProvider,
    *,
    batch_size: int = 32,
    max_batches: int | None = None,
) -> dict[str, Any]:
    if embedding.identity.projection_dimensions != 128:
        raise ValueError("Evidence dense rebuild requires a 128d projection identity")
    if not 1 <= batch_size <= 128:
        raise ValueError("Evidence dense rebuild batch size must be between 1 and 128")
    if max_batches is not None and max_batches < 1:
        raise ValueError("Evidence dense rebuild max_batches must be positive")
    projection_version = evidence_turn_projection_version(embedding.identity)
    after: UUID | None = None
    projected = batches = 0
    while max_batches is None or batches < max_batches:
        items = repository.read_evidence_dense_backfill_batch(
            context,
            after_evidence_id=after,
            limit=batch_size,
            model_id=embedding.identity.model_id,
            projection_version=projection_version,
        )
        if not items:
            break
        identities: list[UUID] = []
        texts: list[str] = []
        for item in items:
            evidence_id = item.get("evidence_id")
            content = item.get("content")
            if not isinstance(evidence_id, str) or not isinstance(content, str):
                raise RuntimeError("Evidence dense rebuild source is invalid")
            identities.append(UUID(evidence_id))
            texts.append(evidence_turn_embedding_text(content))
        vectors = embedding.embed_many(texts, batch_size)
        if len(vectors) != len(identities):
            raise RuntimeError("Evidence dense rebuild embedding cardinality drifted")
        repository.apply_evidence_dense_batch(
            context,
            dict(zip(identities, vectors, strict=True)),
            model_id=embedding.identity.model_id,
            projection_version=projection_version,
        )
        projected += len(identities)
        batches += 1
        after = identities[-1]
    remaining = repository.read_evidence_dense_backfill_batch(
        context,
        after_evidence_id=None,
        limit=1,
        model_id=embedding.identity.model_id,
        projection_version=projection_version,
    )
    return {
        "schema": "milai.evidence-dense-rebuild.v0.1",
        "status": "COMPLETE" if not remaining else "PARTIAL",
        "projected_count": projected,
        "batch_count": batches,
        "remaining": bool(remaining),
        "model_id": embedding.identity.model_id,
        "projection_version": projection_version,
        "automatic_retries": 0,
        "canonical_mutation": False,
    }


__all__ = ["rebuild_evidence_dense"]
