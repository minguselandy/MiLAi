"""Carry run-owned task deliverables into a fresh Host, without conversation/cache state."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

_EXCLUDED_PARTS = frozenset({
    "sources", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})


def carry_task_artifacts(source: Path, target: Path) -> list[dict[str, str]]:
    """Copy ordinary deliverables; never follow a model-created link into host data."""
    source = source.resolve(strict=True)
    files = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if _EXCLUDED_PARTS.intersection(relative.parts) or relative.as_posix() == "answer.txt":
            continue
        if path.is_symlink():
            raise ValueError(f"Task artifact symlinks require explicit review: {relative}")
        if path.is_file():
            files.append((path, relative))
    manifest = []
    for path, relative in files:
        destination = target / relative
        if destination.exists():
            raise ValueError(f"Task artifact would overwrite initialized content: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(
            destination.read_bytes()
        ).hexdigest()})
    return manifest
