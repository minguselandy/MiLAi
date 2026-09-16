from __future__ import annotations

import json
import zipfile
from pathlib import Path

from milai.operations.packaging import (
    build_package_release_manifest,
    package_install_cases,
)


def _package_fixture(root: Path) -> None:
    package = root / "runtime"
    (package / ".venv/lib/python3.11/site-packages").mkdir(parents=True)
    (package / "dist").mkdir()
    (package / "pyproject.toml").write_text(
        """[project]
name = "milai-runtime"
version = "0.1.0"
requires-python = ">=3.11,<3.13"

[tool.hatch.build.targets.wheel]
packages = ["src/milai"]
""",
        encoding="utf-8",
    )
    (package / "uv.lock").write_text(
        '[[package]]\nname = "milai-runtime"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    with zipfile.ZipFile(package / "dist/milai_runtime-0.1.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr("milai/py.typed", b"")
    (package / "dist/milai_runtime-0.1.0.tar.gz").write_bytes(b"source")


def test_package_manifest_and_install_case_share_data_driven_inventory(tmp_path: Path) -> None:
    _package_fixture(tmp_path)
    output = tmp_path / "manifest.json"

    manifest = build_package_release_manifest(
        tmp_path,
        output,
        package_roots=("runtime",),
        snapshot_date="2026-08-24",
    )
    cases = package_install_cases(tmp_path, package_roots=("runtime",))

    assert [item["name"] for item in manifest["packages"]] == ["milai-runtime"]
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    assert [(case.name, case.import_name) for case in cases] == [("milai-runtime", "milai")]


def test_install_case_can_select_new_artifacts_from_a_shared_wheel_root(
    tmp_path: Path,
) -> None:
    _package_fixture(tmp_path)
    wheel_root = tmp_path / "wheels"
    wheel_root.mkdir()
    shared = wheel_root / "milai_runtime-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(shared, "w") as wheel:
        wheel.writestr("milai/py.typed", b"")

    cases = package_install_cases(
        tmp_path,
        package_roots=("runtime",),
        wheel_root=wheel_root,
    )

    assert [case.wheel for case in cases] == [shared]
