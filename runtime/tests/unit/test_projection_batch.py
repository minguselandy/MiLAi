from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from milai.adapters import DeterministicHashEmbedding
from milai.domain.retrieval_projection import ProjectionFragment
from milai.observability import OperationTimer
from milai.persistence import SessionContext
from milai.persistence.projection_repository import ProjectionEvent
from milai.workers.projection_batch import ProjectionBatchProcessor


class _Repository:
    def __init__(self) -> None:
        self.embeddings: list[list[float]] | None = None

    def apply_window_search(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        self.embeddings = args[5]
        return {"action": "UPSERTED"}


class _ScalarProvider:
    dimensions = 16
    identity = DeterministicHashEmbedding.identity

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [float(len(text))] * 16


def _event() -> ProjectionEvent:
    return ProjectionEvent(
        outbox_id=UUID("11111111-1111-4111-8111-111111111111"),
        outbox_sequence=1,
        event_type="CLAIM_CREATED",
        aggregate_type="claim",
        aggregate_id=UUID("22222222-2222-4222-8222-222222222222"),
        payload={},
        canonical_commit_seq=1,
        attempt_count=1,
        lease_expires_at=datetime.now(UTC),
    )


def test_projection_batch_scalar_fallback_counts_each_inference_and_exact_dedup() -> None:
    repository = _Repository()
    provider = _ScalarProvider()
    metrics = OperationTimer()
    processor = ProjectionBatchProcessor(
        repository,  # type: ignore[arg-type]
        provider,  # type: ignore[arg-type]
        context=SessionContext(
            UUID("33333333-3333-4333-8333-333333333333"),
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ),
        worker_id="unit-worker",
        batch_size=32,
        metrics=metrics,
    )
    fragments = (
        ProjectionFragment(0, "turn", 0, 0, ("user",), "same"),
        ProjectionFragment(1, "window", 0, 1, ("user", "assistant"), "same"),
        ProjectionFragment(2, "turn", 1, 1, ("assistant",), "different"),
    )

    result = processor.process(_event(), fragments)

    assert provider.calls == 2
    assert result.logical_items == 3
    assert result.unique_items == 2
    assert result.exact_dedup_hits == 1
    assert result.inference_batches == 2
    assert metrics.snapshot()["counts"]["embedding_inference_batches"] == 2
    assert repository.embeddings is not None
    assert repository.embeddings[0] == repository.embeddings[1]
