from __future__ import annotations

from pathlib import Path

import pytest
from build_ua_inventory import ROOT, inventory_files
from milai.operations.release_safety import scan_archive_bytes


def test_inventory_rejects_missing_required_target(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="required inventory target is missing"):
        inventory_files(tmp_path, ("missing",))


def test_inventory_excludes_nested_cache(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    (candidate / ".cache").mkdir(parents=True)
    (candidate / ".cache/ignored").write_text("cache", encoding="utf-8")
    (candidate / "kept.txt").write_text("kept", encoding="utf-8")
    assert [path.name for path in inventory_files(tmp_path, ("candidate",))] == [
        "kept.txt"
    ]


def test_inventory_rejects_symlink(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "target").write_text("target", encoding="utf-8")
    (candidate / "link").symlink_to("target")
    with pytest.raises(ValueError, match="must not contain symlinks"):
        inventory_files(tmp_path, ("candidate",))


def test_declared_inventory_contains_role_bootstrap_and_no_cache() -> None:
    paths = {path.relative_to(ROOT).as_posix() for path in inventory_files()}
    assert ".gitignore" in paths
    assert "MiLAi_Agent执行效率与Token优化设计开发文档_v1.md" in paths
    assert "runtime/docker/initdb/010_roles.sh" in paths
    assert not any(".cache" in Path(path).parts for path in paths)


def test_current_runtime_sdist_is_allowlisted_and_secret_free() -> None:
    archives = sorted((ROOT / "runtime/dist").glob("milai_runtime-*.tar.gz"))
    assert len(archives) == 1
    archive = archives[0]
    result = scan_archive_bytes(
        archive.relative_to(ROOT).as_posix(),
        archive.name,
        archive.read_bytes(),
        [],
    )
    assert result.member_count > 0
    assert result.forbidden_members == []
    assert result.unsafe_archives == []
