from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from milai.config.settings import load_settings
from milai.persistence.projection_repository import (
    ProjectionEvent,
    ProjectionOwnershipLost,
    is_projection_ownership_lost,
    safe_worker_error,
)
from milai.workers.main import FoundationWorker, _parser


class FakeDatabase:
    def __init__(self) -> None:
        self.ping_count = 0

    def ping(self) -> None:
        self.ping_count += 1


class OwnershipRepository:
    def __init__(self, lost_event_id: UUID) -> None:
        self.lost_event_id = lost_event_id
        self.fail_calls: list[UUID] = []
        self.completed: list[UUID] = []

    def apply_search(self, *args: Any, **_kwargs: Any) -> dict[str, object]:
        event = args[2]
        assert isinstance(event, ProjectionEvent)
        if event.outbox_id == self.lost_event_id:
            raise ProjectionOwnershipLost("lease moved to another worker")
        return {"action": "UPSERTED"}

    def complete_routed(self, *args: Any, **_kwargs: Any) -> int:
        event = args[2]
        assert isinstance(event, ProjectionEvent)
        self.completed.append(event.outbox_id)
        return event.outbox_sequence

    def fail(self, *args: Any, **_kwargs: Any) -> str:
        event = args[2]
        assert isinstance(event, ProjectionEvent)
        self.fail_calls.append(event.outbox_id)
        return "PENDING"


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    return load_settings(
        {
            "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
            "MILAI_STEWARD_DATABASE_URL": (
                "postgresql://milai_steward:secret@127.0.0.1:15432/milai"
            ),
            "MILAI_BLOB_ROOT": str(tmp_path / "blobs"),
            "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "MILAI_API_TOKEN": "test-token-with-at-least-32-characters",
            "MILAI_CAUSAL_TOKEN_SECRET": "test-causal-secret-with-at-least-32-characters",
        }
    )


def _event(outbox_id: str, sequence: int) -> ProjectionEvent:
    return ProjectionEvent(
        outbox_id=UUID(outbox_id),
        outbox_sequence=sequence,
        event_type="CLAIM_VERSION_COMMITTED",
        aggregate_type="claim",
        aggregate_id=UUID("22222222-2222-4222-8222-222222222222"),
        payload={"claim_version_id": "33333333-3333-4333-8333-333333333333"},
        canonical_commit_seq=sequence,
        attempt_count=1,
        lease_expires_at=datetime.now(UTC),
    )


def test_foundation_worker_once_only_checks_readiness(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = FakeDatabase()
    worker = FoundationWorker(settings, database)  # type: ignore[arg-type]
    worker.run_once()
    assert database.ping_count == 1


def test_worker_check_and_once_are_explicit_mutually_exclusive_modes() -> None:
    assert _parser().parse_args(["--check"]).check is True
    assert _parser().parse_args(["--once"]).once is True
    with pytest.raises(SystemExit):
        _parser().parse_args(["--check", "--once"])


def test_worker_drains_active_cycles_then_waits_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = FoundationWorker(_settings(tmp_path), FakeDatabase())  # type: ignore[arg-type]
    results = iter((1024, 4, 0))
    trace: list[tuple[str, float]] = []

    def cycle() -> int:
        result = next(results)
        trace.append(("cycle", result))
        return result

    def wait(seconds: float) -> bool:
        trace.append(("wait", seconds))
        return True

    monkeypatch.setattr(worker, "run_once", cycle)
    monkeypatch.setattr(worker._stop, "wait", wait)
    worker.run()
    assert trace == [("cycle", 1024), ("cycle", 4), ("cycle", 0), ("wait", 1.0)]


def test_worker_honors_stop_after_active_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = FoundationWorker(_settings(tmp_path), FakeDatabase())  # type: ignore[arg-type]
    cycles = []

    def cycle() -> int:
        cycles.append(1)
        worker.request_stop()
        return 1024

    monkeypatch.setattr(worker, "run_once", cycle)
    worker.run()
    assert cycles == [1]


def test_worker_does_not_start_a_cycle_after_stop(tmp_path: Path) -> None:
    database = FakeDatabase()
    worker = FoundationWorker(_settings(tmp_path), database)  # type: ignore[arg-type]
    worker.request_stop()
    worker.run()
    assert database.ping_count == 0


def test_projection_ownership_loss_has_stable_classification() -> None:
    error = ProjectionOwnershipLost("payload must not affect classification")

    assert is_projection_ownership_lost(error)
    assert safe_worker_error(error) == "LEASE_LOST"
    assert not is_projection_ownership_lost(RuntimeError("ordinary handler failure"))


def test_worker_does_not_fail_lost_ownership_and_continues_later_event(
    tmp_path: Path,
) -> None:
    first = _event("11111111-1111-4111-8111-111111111111", 1)
    second = _event("44444444-4444-4444-8444-444444444444", 2)
    repository = OwnershipRepository(first.outbox_id)
    worker = FoundationWorker(
        _settings(tmp_path),
        FakeDatabase(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        worker_id="ownership-test-worker",
    )

    worker._process("fts", first)
    worker._process("fts", second)

    assert repository.fail_calls == []
    assert repository.completed == [second.outbox_id]
    counts = worker.metrics_snapshot()["counts"]
    assert counts["projection_ownership_lost_dispositions"] == 1
    assert counts["projection_ownership_lost_items"] == 1
