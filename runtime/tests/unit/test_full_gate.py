from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai.operations import full_gate


def test_runtime_full_gate_uses_fresh_database_and_writes_terminal_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(full_gate, "load_runtime_environment", lambda _path: None)
    monkeypatch.setattr(
        full_gate,
        "load_settings",
        lambda: SimpleNamespace(
            database_dsn="postgresql://api@127.0.0.1/source",
            steward_database_dsn="postgresql://steward@127.0.0.1/source",
        ),
    )
    monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", "postgresql://owner@127.0.0.1/source")
    monkeypatch.setenv("MILAI_WORKER_DATABASE_URL", "postgresql://worker@127.0.0.1/source")
    monkeypatch.setenv("MILAI_AUDIT_DATABASE_URL", "postgresql://audit@127.0.0.1/source")
    created: list[str] = []
    monkeypatch.setattr(
        full_gate,
        "_create_database",
        lambda _source, database: created.append(database),
    )
    monkeypatch.setattr(
        full_gate,
        "_drop_database",
        lambda _source, _database: {"status": "PASS"},
    )
    monkeypatch.setattr(
        full_gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="12 passed in 1.25s\n", stderr=""
        ),
    )
    env_file = tmp_path / "runtime/.env"
    report_path = tmp_path / "report.json"

    result = full_gate.run_runtime_full_gate(env_file, report_path)

    assert result["status"] == "PASS"
    assert result["pytest_passed"] == 12
    assert result["cleanup"] == {"status": "PASS"}
    assert created == [result["database"]]
    assert json.loads(report_path.read_text(encoding="utf-8"))["run_id"] == result["run_id"]
