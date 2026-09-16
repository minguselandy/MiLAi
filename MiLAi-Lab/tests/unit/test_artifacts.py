from __future__ import annotations

import json
from pathlib import Path

import pytest

from milai_lab.harness.artifacts import RunArtifacts


def test_compact_artifact_writer(tmp_path: Path) -> None:
    artifacts = RunArtifacts(tmp_path / "run")
    terminal = artifacts.write_json("terminal.json", {"status": "PASS"})
    events = artifacts.append_jsonl("events.jsonl", {"event": "started"})

    assert json.loads(terminal.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(events.read_text(encoding="utf-8"))["event"] == "started"


def test_artifact_writer_rejects_receipt_amplification(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        RunArtifacts(tmp_path).write_json("receipt-001.json", {})

