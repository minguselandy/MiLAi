from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from milai.adapters import EmbeddingProvider
from milai.domain.retrieval_projection import ProjectionFragment
from milai.observability import OperationTimer
from milai.persistence import SessionContext
from milai.persistence.projection_repository import ProjectionEvent, ProjectionRepository


@dataclass(frozen=True, slots=True)
class ProjectionBatchResult:
    handler_result: dict[str, object]
    logical_items: int
    unique_items: int
    inference_batches: int
    exact_dedup_hits: int


class ProjectionBatchProcessor:
    """Embed one ordered projection event in tensor batches before its atomic write."""

    def __init__(
        self,
        repository: ProjectionRepository,
        embedding: EmbeddingProvider,
        *,
        context: SessionContext,
        worker_id: str,
        batch_size: int,
        metrics: OperationTimer,
    ) -> None:
        self._repository = repository
        self._embedding = embedding
        self._context = context
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._metrics = metrics

    def process(
        self,
        event: ProjectionEvent,
        fragments: tuple[ProjectionFragment, ...],
    ) -> ProjectionBatchResult:
        unique_texts = list(dict.fromkeys(fragment.content_text for fragment in fragments))
        logical_items = len(fragments)
        exact_dedup_hits = logical_items - len(unique_texts)
        method = getattr(self._embedding, "embed_many", None)
        inference_batches = (
            (
                ceil(len(unique_texts) / self._batch_size)
                if method is not None
                else len(unique_texts)
            )
            if unique_texts
            else 0
        )
        self._metrics.increment("embedding_logical_items", logical_items)
        self._metrics.increment("embedding_unique_items", len(unique_texts))
        self._metrics.increment("embedding_inference_batches", inference_batches)
        self._metrics.increment("embedding_cache_hits", exact_dedup_hits)

        vectors: list[list[float]]
        if not unique_texts:
            vectors = []
        else:
            with self._metrics.measure("embedding_inference_ms"):
                if method is None:
                    vectors = [self._embedding.embed(text) for text in unique_texts]
                else:
                    vectors = method(unique_texts, self._batch_size)
        by_text = dict(zip(unique_texts, vectors, strict=True))
        ordered_vectors = [by_text[fragment.content_text] for fragment in fragments]
        with self._metrics.measure("projection_write_ms"):
            result = self._repository.apply_window_search(
                self._context,
                "vector",
                event,
                self._worker_id,
                fragments,
                ordered_vectors,
                model_id=self._embedding.identity.model_id,
                projection_version=self._embedding.identity.key,
            )
        return ProjectionBatchResult(
            handler_result=result,
            logical_items=logical_items,
            unique_items=len(unique_texts),
            inference_batches=inference_batches,
            exact_dedup_hits=exact_dedup_hits,
        )
