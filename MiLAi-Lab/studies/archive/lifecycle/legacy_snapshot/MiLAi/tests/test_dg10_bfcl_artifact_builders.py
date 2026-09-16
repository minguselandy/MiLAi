from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_dg10_bfcl_case_manifest as case_manifest
from scripts import build_dg10_bfcl_execution_identity as execution_identity
from scripts import build_dg10_bfcl_worker_closure as worker_closure
from scripts import dg10_remediation as remediation


@pytest.mark.parametrize(
    "module",
    [worker_closure, execution_identity],
)
def test_bfcl_builder_reference_rejects_symlink_components(
    module: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    target = tmp_path / "sealed/material.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "material.json"
    link.symlink_to(target)

    with pytest.raises(remediation.RemediationError, match="unsafe BFCL"):
        module._reference(link)


def test_bfcl_manifest_fixed_material_rejects_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(case_manifest, "ROOT", tmp_path)
    target = tmp_path / "sealed/closure.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "closure.json"
    link.symlink_to(target)

    with pytest.raises(case_manifest.BfclManifestError, match="missing, unsafe"):
        case_manifest._fixed_material(link, expected=link, label="closure")


def test_bfcl_builders_derive_material_hashes_without_mutable_placeholders() -> None:
    assert not hasattr(worker_closure, "R2_CLOSURE_SHA256")
    assert not hasattr(execution_identity, "WORKER_CLOSURE_SHA256")
    assert not hasattr(case_manifest, "DEFAULT_CLOSURE_SHA256")
    assert not hasattr(case_manifest, "EXECUTION_IDENTITY_SHA256")
