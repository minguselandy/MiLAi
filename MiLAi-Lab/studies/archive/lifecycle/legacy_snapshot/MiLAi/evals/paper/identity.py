"""Deterministic source identities used by the DG11 paper freeze."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
EXCLUDED_FILE_SUFFIXES = (".pyc", ".pyo")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def source_inventory(root: Path) -> dict[str, Any]:
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = sorted(
            name for name in directory_names if name not in EXCLUDED_DIRECTORY_NAMES
        )
        base = Path(directory)
        for name in sorted(file_names):
            if name.endswith(EXCLUDED_FILE_SUFFIXES):
                continue
            path = base / name
            relative = path.relative_to(root).as_posix()
            file_stat = path.lstat()
            mode = stat.S_IMODE(file_stat.st_mode)
            if path.is_symlink():
                target = os.readlink(path)
                digest = hashlib.sha256(target.encode()).hexdigest()
                entries.append(
                    {
                        "kind": "symlink",
                        "mode": f"{mode:04o}",
                        "path": relative,
                        "sha256": digest,
                        "size": len(target.encode()),
                        "target": target,
                    }
                )
            elif path.is_file():
                entries.append(
                    {
                        "kind": "file",
                        "mode": f"{mode:04o}",
                        "path": relative,
                        "sha256": sha256_file(path),
                        "size": file_stat.st_size,
                    }
                )
    entries.sort(key=lambda item: str(item["path"]))
    canonical = b"".join(
        json.dumps(
            item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        + b"\n"
        for item in entries
    )
    return {
        "entries": entries,
        "excluded_directory_names": sorted(EXCLUDED_DIRECTORY_NAMES),
        "excluded_file_suffixes": list(EXCLUDED_FILE_SUFFIXES),
        "file_count": len(entries),
        "inventory_root_sha256": hashlib.sha256(canonical).hexdigest(),
        "root": str(root),
        "total_bytes": sum(int(item["size"]) for item in entries),
    }


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout


def git_source_identity(root: Path) -> dict[str, Any]:
    root = root.resolve()
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").decode(
        errors="surrogateescape"
    )
    diff = _git(root, "diff", "--binary", "HEAD") + _git(
        root, "diff", "--binary", "--cached", "HEAD"
    )
    inventory = source_inventory(root)
    return {
        "commit": commit,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "dirty": bool(status),
        "inventory": inventory,
        "root": str(root),
        "status_porcelain": status.splitlines(),
    }


def git_tracked_identity(root: Path) -> dict[str, Any]:
    """Freeze tracked source without recursively inventorying large untracked datasets."""

    root = root.resolve()
    names = [
        item.decode(errors="surrogateescape")
        for item in _git(root, "ls-files", "-z").split(b"\0")
        if item
    ]
    entries: list[dict[str, Any]] = []
    for name in sorted(names):
        path = root / name
        file_stat = path.lstat()
        mode = stat.S_IMODE(file_stat.st_mode)
        if path.is_symlink():
            target = os.readlink(path)
            entries.append(
                {
                    "kind": "symlink",
                    "mode": f"{mode:04o}",
                    "path": name,
                    "sha256": hashlib.sha256(target.encode()).hexdigest(),
                    "size": len(target.encode()),
                    "target": target,
                }
            )
        elif path.is_file():
            entries.append(
                {
                    "kind": "file",
                    "mode": f"{mode:04o}",
                    "path": name,
                    "sha256": sha256_file(path),
                    "size": file_stat.st_size,
                }
            )
        else:
            raise FileNotFoundError(f"tracked path is absent or unsupported: {path}")
    canonical = b"".join(
        json.dumps(
            item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        + b"\n"
        for item in entries
    )
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").decode(
        errors="surrogateescape"
    )
    diff = _git(root, "diff", "--binary", "HEAD") + _git(
        root, "diff", "--binary", "--cached", "HEAD"
    )
    return {
        "commit": commit,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "dirty": bool(status),
        "file_count": len(entries),
        "inventory_root_sha256": hashlib.sha256(canonical).hexdigest(),
        "root": str(root),
        "status_porcelain": status.splitlines(),
        "total_bytes": sum(int(item["size"]) for item in entries),
        "tracked_entries": entries,
    }


def license_identity(root: Path) -> dict[str, Any]:
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.name.lower().startswith("license")
    )
    if not candidates:
        raise FileNotFoundError(f"license file not found in {root}")
    path = candidates[0]
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
    }
