from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dg10_workflow


def test_active_workflow_has_no_legacy_ai_acceptance_dependency() -> None:
    evidence = dg10_workflow.validate()
    assert evidence["status"] == "PASS"
    assert evidence["development_ai_audits"] == 0
    assert evidence["legacy_imports"] == 0
    assert evidence["active_entrypoint_count"] >= 8


def test_active_workflow_rejects_a_legacy_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = tmp_path / "active.py"
    active.write_text("from scripts import dg10_post_r3_provider_gate\n", encoding="utf-8")
    registry = json.loads(dg10_workflow.REGISTRY.read_text(encoding="utf-8"))
    registry["active_entrypoints"] = ["active.py"]
    registry_path = tmp_path / "workflow.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(dg10_workflow.WorkflowError, match="imports legacy workflow"):
        dg10_workflow.validate(tmp_path, registry_path)


def test_import_parser_tracks_from_import_members() -> None:
    imports = dg10_workflow._imports("from scripts import safe, unsafe\nimport json\n")
    assert imports == {"scripts", "scripts.safe", "scripts.unsafe", "json"}
