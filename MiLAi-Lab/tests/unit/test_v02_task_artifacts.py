from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "tools/v02_task_artifacts.py"
    spec = importlib.util.spec_from_file_location("v02_task_artifacts", path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_resume_keeps_deliverable_but_not_last_message_or_sources(tmp_path: Path) -> None:
    source = tmp_path / "prior"
    target = tmp_path / "fresh"
    source.mkdir()
    (source / "sources").mkdir()
    (source / "sources/contract.txt").write_text("old source snapshot")
    (source / "answer.txt").write_text("temporary conversation answer")
    (source / "brief.md").write_text("reviewable deliverable")
    manifest = module().carry_task_artifacts(source, target)
    assert [entry["path"] for entry in manifest] == ["brief.md"]
    assert (target / "brief.md").read_text() == "reviewable deliverable"
    assert not (target / "answer.txt").exists()
    assert not (target / "sources").exists()


def test_resume_refuses_symlink_to_unmounted_data_before_copying(tmp_path: Path) -> None:
    source = tmp_path / "prior"
    source.mkdir()
    outside = tmp_path / "evaluation.json"
    outside.write_text("not allowed in Host")
    (source / "a.md").write_text("deliverable")
    (source / "b.json").symlink_to(outside)
    target = tmp_path / "fresh"
    with pytest.raises(ValueError, match="symlinks"):
        module().carry_task_artifacts(source, target)
    assert not target.exists()
