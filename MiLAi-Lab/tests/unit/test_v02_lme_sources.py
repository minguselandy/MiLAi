from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "tools/export_v02_lme_sources.py"
SPEC = importlib.util.spec_from_file_location("v02_lme_export", PATH)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def record(case: str) -> dict:
    return {"question_id": case, "question": "ordinary request", "question_date": "2026/09/05",
            "answer": "OFFLINE_ONLY", "answer_session_ids": ["s1"],
            "haystack_session_ids": ["answer_secret", "answer_secret"],
            "haystack_dates": ["d1", "d2"],
            "haystack_sessions": [[{"role": "user", "content": 'literal { } "question_id": "b"',
                                    "has_answer": True}],
                                  [{"role": "assistant", "content": "distractor", "gold": True}]]}


def test_whitelist_export_preserves_all_history_without_labels(tmp_path: Path) -> None:
    source = tmp_path / "population.json"
    data = json.dumps([record("a"), record("b")]).encode()
    source.write_bytes(data)
    output = tmp_path / "export"
    manifest = exporter.export(source, hashlib.sha256(data).hexdigest(), {"a"}, {"a"}, output)
    result = json.loads((output / "sources/a.json").read_text())
    assert len(result["sessions"]) == 2
    assert [s["session_id"] for s in result["sessions"]] == ["session-0", "session-1"]
    assert "answer_secret" not in json.dumps(result)
    assert result["sessions"][1]["turns"][0]["content"] == "distractor"
    assert "OFFLINE_ONLY" not in json.dumps(result)
    assert "has_answer" not in json.dumps(result) and '"gold"' not in json.dumps(result)
    assert manifest["records_json_decoded"] == 1
    assert manifest["nonwhitelisted_records_decoded"] == 0
    assert not (output / "sources/b.json").exists()
    assert json.loads((output / "labels/a.json").read_text())["reference_answer"] == "OFFLINE_ONLY"


def test_export_refuses_nonopened_case_before_reading(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="whitelist"):
        exporter.export(tmp_path / "missing.json", "invalid", {"not-opened"}, {"a"},
                        tmp_path / "output")


def test_export_refuses_identity_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("[]")
    with pytest.raises(ValueError, match="identity"):
        exporter.export(source, "bad", {"a"}, {"a"}, tmp_path / "output")
