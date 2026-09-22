"""Real CLI/DB proof of a bounded cycle, distinct from a successful queue drain."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psycopg
import pytest
from support.projection import _url
from support.projection import worker_runtime as worker_runtime
from test_projection_worker import _ingest

from milai.adapters import LocalContentAddressedBlobStore
from milai.config.settings import RuntimeSettings

pytestmark = pytest.mark.integration
PROJECTIONS = {"evidence", "purge", "fts", "vector"}


def _cli(
    settings: RuntimeSettings, mode: str, **overrides: str,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
    # No inherited Runtime credentials or model endpoint enters this worker.
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "MILAI_WORKER_DATABASE_URL": _url("MILAI_TEST_WORKER_DATABASE_URL"),
        "MILAI_BLOB_ROOT": str(settings.blob_root),
        "MILAI_TENANT_ID": str(settings.tenant_id),
        "MILAI_LOCAL_ACTOR_ID": str(settings.local_actor_id),
        "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
        "MILAI_EMBEDDING_PREWARM": "false",
        "MILAI_WORKER_EVENT_LIMIT": "3",
        "MILAI_WORKER_PROJECTION_BATCH_SIZE": "2",
        "MILAI_WORKER_POLL_INTERVAL_SECONDS": "60",
        "MILAI_WORKER_RETRY_DELAY_SECONDS": "60",
        "PGAPPNAME": f"worker-once-{settings.tenant_id}",
        **overrides,
    }
    result = subprocess.run(  # noqa: S603 -- installed CLI, synthetic isolated environment
        [str(Path(sys.executable).with_name("milai-worker")), mode],
        env=environment, capture_output=True, text=True, timeout=20, check=False,
    )
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        # A fresh process really released its PostgreSQL sessions at exit.
        assert owner.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s",
            (environment["PGAPPNAME"],),
        ).fetchone()[0] == 0
    return result, records


def _snapshot(settings: RuntimeSettings) -> tuple[list[Any], dict[str, int], int]:
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        deliveries = owner.execute(
            """SELECT projection_name, outbox_sequence, state, attempt_count,
                      lease_owner, last_error_code
               FROM milai.projection_delivery WHERE tenant_id = %s
               ORDER BY projection_name, outbox_sequence""",
            (settings.tenant_id,),
        ).fetchall()
        watermarks = dict(owner.execute(
            """SELECT projection_name, last_contiguous_outbox_sequence
               FROM milai.index_watermark WHERE tenant_id = %s""",
            (settings.tenant_id,),
        ).fetchall())
        documents = owner.execute(
            "SELECT count(*) FROM milai.evidence_search_document WHERE tenant_id = %s",
            (settings.tenant_id,),
        ).fetchone()[0]
    return deliveries, watermarks, documents


@pytest.mark.parametrize("queued", [0, 2, 5], ids=["empty", "below-limit", "above-limit"])
def test_once_is_one_bounded_cycle_per_projection(worker_runtime, queued: int) -> None:  # type: ignore[no-untyped-def]
    settings, app, _database = worker_runtime
    for index in range(queued):
        _ingest(app.test_client(), f"bounded worker item {index}")
    result, records = _cli(settings, "--once")
    assert result.returncode == 0, result.stderr
    cycles = [row["safe_metadata"] for row in records if row["event"] == "outbox_worker_cycle"]
    assert len(cycles) == 1
    expected = min(queued, 3)
    assert cycles[0]["processed"] == 4 * expected
    deliveries, watermarks, documents = _snapshot(settings)
    assert documents == expected
    assert set(watermarks) == PROJECTIONS
    for projection in PROJECTIONS:
        rows = [row for row in deliveries if row[0] == projection]
        delivered = [row for row in rows if row[2] == "DELIVERED"]
        assert len(delivered) == expected
        assert all(row[3] == 1 and row[4] is None for row in delivered)
        assert all(row[2] == "PENDING" and row[3] == 0 for row in rows[expected:])
        assert watermarks[projection] == (delivered[-1][1] if delivered else 0)
    counts = cycles[0]["stage_metrics"]["counts"]
    assert counts.get("projection_watermark_reconcile_ms", 0) == (4 if queued else 0)
    if queued:
        # A second process advances the remaining prefix, then a third is idle.
        second, _ = _cli(settings, "--once")
        assert second.returncode == 0, second.stderr
        assert _snapshot(settings)[2] == queued
        before = _snapshot(settings)
        idle, idle_records = _cli(settings, "--once")
        assert idle.returncode == 0, idle.stderr
        assert _snapshot(settings) == before
        idle_cycle = [r for r in idle_records if r["event"] == "outbox_worker_cycle"]
        assert len(idle_cycle) == 1
        assert idle_cycle[0]["safe_metadata"]["processed"] == 0


def test_check_leaves_queue_watermarks_and_orphans_untouched(worker_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, _database = worker_runtime
    _ingest(app.test_client(), "check must not project this evidence")
    store = LocalContentAddressedBlobStore(settings.blob_root)
    orphan = store.write(settings.tenant_id, b"unreferenced check blob")
    # Locate the synthetic content-addressed file without depending on URI parsing.
    path = next(settings.blob_root.rglob(orphan.content_hash))
    old = time.time() - 301
    os.utime(path, (old, old))
    before = _snapshot(settings)
    result, records = _cli(settings, "--check")
    assert result.returncode == 0, result.stderr
    assert _snapshot(settings) == before
    assert path.exists()
    assert any(r["event"] == "foundation_worker_dependencies_ready" for r in records)
    assert not any(r["event"] in {"outbox_worker_cycle", "blob_orphan_reconciliation"}
                   for r in records)
    once, once_records = _cli(settings, "--once")
    assert once.returncode == 0, once.stderr
    assert not path.exists()
    events = [r["event"] for r in once_records]
    assert events.index("blob_orphan_reconciliation") < events.index("outbox_worker_cycle")
    assert _snapshot(settings)[2] == 1


@pytest.mark.parametrize("max_attempts", [1, 5], ids=["dead-letter", "retry-pending"])
def test_once_processing_failure_is_durable_and_watermark_does_not_pass_gap(
    worker_runtime, max_attempts: int,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, _database = worker_runtime
    evidence = _ingest(app.test_client(), "synthetic unavailable blob")
    blob = next(settings.blob_root.rglob(evidence["content_hash"]))
    saved = blob.with_suffix(".withheld")
    blob.rename(saved)
    result, records = _cli(settings, "--once", MILAI_WORKER_MAX_ATTEMPTS=str(max_attempts))
    assert result.returncode == 0, result.stderr
    assert any(r["event"] == "evidence_projection_batch_failed" for r in records)
    deliveries, watermarks, documents = _snapshot(settings)
    row = next(row for row in deliveries if row[0] == "evidence")
    assert row[2] == ("DEAD_LETTER" if max_attempts == 1 else "PENDING")
    assert row[3] == 1 and row[4] is None and row[5]
    assert watermarks["evidence"] < row[1]
    assert documents == 0
    assert all(r[2] == "DELIVERED" for r in deliveries if r[0] != "evidence")
    saved.rename(blob)


def test_once_unhandled_database_failure_exits_nonzero_without_leasing(worker_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, _database = worker_runtime
    _ingest(app.test_client(), "must survive failed startup")
    before = _snapshot(settings)
    # A nonexistent database on the same owned server fails promptly and cannot lease work.
    dsn = _url("MILAI_TEST_WORKER_DATABASE_URL").rsplit("/", 1)[0] + "/worker_once_absent"
    result, records = _cli(
        settings, "--once", MILAI_WORKER_DATABASE_URL=dsn,
        MILAI_DATABASE_CONNECT_TIMEOUT_SECONDS="1",
    )
    assert result.returncode != 0
    assert not any(r["event"] == "outbox_worker_cycle" for r in records)
    assert _snapshot(settings) == before
