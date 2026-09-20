"""Historical boundary evidence must fail closed after implementation drift."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import prepare_v0222_boundary as prepare_module
import v0222_boundary_batch as batch_module
from v0220_evidence import sha

pytestmark = pytest.mark.skipif(
    not (batch_module.PARENT_ROOT / "execution-binding.json").is_file(),
    reason="external historical V0222 evidence is not part of the Git checkout",
)


def parent_snapshot():
    """Read-only semantic SQL plus durable file hashes; never checkpoint the parent."""
    parent = batch_module.PARENT_ROOT
    connection = sqlite3.connect(f"file:{parent / 'batch.sqlite'}?mode=ro", uri=True)
    try:
        tables = {
            name: connection.execute(  # nosec: table names are the fixed tuple below.
                f'SELECT * FROM "{name}" ORDER BY rowid'  # noqa: S608
            ).fetchall()
            for name in ("meta", "episodes", "events", "artifacts", "launches")
        }
        assert dict(tables["meta"])["stop"] == batch_module.PARENT_STOP
    finally:
        connection.close()
    paths = [
        parent / "batch.sqlite",
        parent / "execution-binding.json",
        parent / "P3-independent-review.json",
        *(Path(path) for path, _ in batch_module.HISTORICAL_SOURCES),
    ]
    # SHM contains reader locks, not durable business data; do not compare it.
    wal = parent / "batch.sqlite-wal"
    if wal.exists():
        paths.append(wal)
    return {"tables": tables, "files": {str(path): sha(path) for path in paths}}


def test_historical_prepare_refuses_current_implementation_drift(tmp_path, monkeypatch):
    """A stale historical seal is evidence of drift, never current conformance."""
    before = parent_snapshot()
    root = (tmp_path / "TEST_ONLY_boundary_instance").resolve()
    monkeypatch.setattr(prepare_module, "ROOT", root)

    with pytest.raises(ValueError, match="IMPLEMENTATION_DRIFT"):
        prepare_module.prepare(root)

    assert not root.exists()
    assert parent_snapshot() == before
