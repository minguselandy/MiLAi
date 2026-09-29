"""Asset-free adapter boundaries; real SDK/database replay has a separate owner."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai_lab.harness import artifact_io, contextual_artifacts
from milai_lab.harness.source_identity import (
    ARTIFACT_IO_SOURCE_FILES,
    INTEGRATION_FACADE_FILES,
    INTEGRATION_SOURCE_FILES,
    REQUEST_SOURCE_FILES,
)
from milai_lab.integrations.memory import mem0, simplemem

LAB = Path(__file__).resolve().parents[2]


def test_old_paths_export_identical_canonical_objects() -> None:
    for relative, owner in zip(INTEGRATION_FACADE_FILES, (mem0, simplemem), strict=True):
        path = LAB / relative
        old = importlib.import_module("milai_lab.runners." + path.stem)
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Expr):
                assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module == owner.__name__
                for alias in node.names:
                    assert getattr(old, alias.asname or alias.name) is getattr(owner, alias.name)
            else:
                assert isinstance(node, ast.Assign) and len(node.targets) == 1
                assert isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__all__"
                assert isinstance(node.value, ast.List)
                assert all(
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                    for value in node.value.elts
                )
    from milai_lab.baselines import benchmark_memories

    assert benchmark_memories.mem0_dependency_identity is mem0.mem0_dependency_identity
    assert benchmark_memories.MEM0_SOURCE_COMMIT is mem0.MEM0_SOURCE_COMMIT


def test_integration_and_artifact_io_registry_cover_every_canonical_file() -> None:
    actual = {
        str(path.relative_to(LAB)) for path in (LAB / "src/milai_lab/integrations").rglob("*.py")
    }
    assert actual == set(INTEGRATION_SOURCE_FILES)
    assert set(
        (*INTEGRATION_SOURCE_FILES, *INTEGRATION_FACADE_FILES, *ARTIFACT_IO_SOURCE_FILES)
    ) <= set(REQUEST_SOURCE_FILES)


def test_integration_has_only_lower_imports_and_leaf_artifact_io() -> None:
    allowed = (
        "milai_lab.contracts.",
        "milai_lab.providers.",
        "milai_lab.memory.",
        "milai_lab.integrations.",
    )
    for relative in INTEGRATION_SOURCE_FILES:
        for node in ast.walk(ast.parse((LAB / relative).read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0
                modules = [node.module or ""]
            for module in modules:
                assert not module.startswith("milai_lab.") or (
                    module.startswith(allowed) or module == "milai_lab.harness.artifact_io"
                ), (relative, module)
    # Static and local baseline imports cannot borrow either compatibility runner.
    for path in (LAB / "src/milai_lab/baselines").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {
                    "milai_lab.runners.mem0_native",
                    "milai_lab.runners.simplemem_native",
                }


def test_import_does_not_load_sdk_or_runner_recipe() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        "from milai_lab.integrations.memory import mem0, simplemem; "
        "assert not any(name.startswith(('mem0', 'simplemem', 'milai_lab.runners', "
        "'milai_lab.baselines', 'milai_lab.methods', 'milai_lab.scorers')) "
        "for name in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and local import probe
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_artifact_io_same_objects_atomic_bytes_unknown_fields_and_digest(tmp_path: Path) -> None:
    for name in ("digest", "read_json", "write_json"):
        assert getattr(contextual_artifacts, name) is getattr(artifact_io, name)
    for node in ast.walk(ast.parse(Path(artifact_io.__file__).read_text())):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("milai_lab.")
        elif isinstance(node, ast.Import):
            assert all(not alias.name.startswith("milai_lab.") for alias in node.names)
    value = {"unknown": {"retain": True}, "unicode": "保留原文", "ordered": [2, 1]}
    path = tmp_path / "nested/artifact.json"
    artifact_io.write_json(path, value)
    frozen = json.loads(
        (LAB / "data/diagnostics/code-architecture-v12/mem0-contract-golden.json").read_text()
    )["contracts"]["artifact_io"]
    assert path.read_text() == frozen["json_bytes"]
    assert artifact_io.read_json(path) == value == frozen["roundtrip"]
    assert artifact_io.digest(value) == frozen["digest"]
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_mem0_source_pin_missing_wrong_and_package_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "mem0"
    package.mkdir()
    source = package / "native.py"
    source.write_text("# synthetic SDK bytes\n")
    direct = {"vcs_info": {"commit_id": mem0.MEM0_SOURCE_COMMIT}}
    distribution = SimpleNamespace(
        version="synthetic",
        read_text=lambda _name: json.dumps(direct),
        locate_file=lambda _name: package,
    )
    monkeypatch.setattr(mem0.importlib.metadata, "distribution", lambda _name: distribution)
    identity = mem0.mem0_dependency_identity()
    assert identity == {
        "version": "synthetic",
        "source_commit": mem0.MEM0_SOURCE_COMMIT,
        "source_sha256": {"native.py": hashlib.sha256(source.read_bytes()).hexdigest()},
    }
    for value in ({}, {"vcs_info": {"commit_id": "wrong"}}):
        direct.clear()
        direct.update(value)
        with pytest.raises(ValueError, match="BENCHMARK_MEM0_SOURCE_NOT_PINNED"):
            mem0.mem0_dependency_identity()


@pytest.mark.parametrize("failure", ["wrong_commit", "dirty"])
def test_simplemem_source_pin_guards_preserve_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(
        simplemem.subprocess,
        "check_output",
        lambda *args, **kwargs: "wrong" if failure == "wrong_commit" else simplemem.SOURCE_COMMIT,
    )
    monkeypatch.setattr(
        simplemem.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    with pytest.raises(
        ValueError,
        match="SIMPLEMEM_SOURCE_NOT_PINNED"
        if failure == "wrong_commit"
        else "SIMPLEMEM_SOURCE_CHANGED",
    ):
        simplemem.dependency_identity({"source_root": str(tmp_path)})
