from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/reports/UA-current-byte-inventory-2026-08-17.json"
INCLUDE = (
    ".github",
    ".gitignore",
    "AGENTS.md",
    "MiLAi_Agent执行效率与Token优化设计开发文档_v1.md",
    "MiLAi_可用性与Agent接入设计开发文档_v1.md",
    "architecture/v1.0",
    "contracts",
    "docs/adr",
    "docs/reports",
    "docs/runbooks",
    "docs/security",
    "docs/known-limitations-agent-integration-0.1.md",
    "evals",
    "examples",
    "integrations",
    "runtime/migrations",
    "runtime/alembic.ini",
    "runtime/src",
    "runtime/tests",
    "runtime/dist",
    "runtime/pyproject.toml",
    "runtime/uv.lock",
    "runtime/compose.yaml",
    "runtime/docker",
    "runtime/.env.example",
    "runtime/.python-version",
    "runtime/README.md",
    "runtime/var/models/all-MiniLM-L6-v2",
    "scripts",
    "tests",
)
EXCLUDED_PARTS = {
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}


def inventory_files(
    root: Path = ROOT, include: tuple[str, ...] = INCLUDE
) -> list[Path]:
    result: set[Path] = set()
    for relative in include:
        target = root / relative
        if not target.exists():
            raise FileNotFoundError(f"required inventory target is missing: {relative}")
        if target.is_symlink():
            raise ValueError(f"inventory target must not be a symlink: {relative}")
        if target.is_file():
            result.add(target)
        elif target.is_dir():
            for path in target.rglob("*"):
                relative_parts = path.relative_to(root).parts
                if EXCLUDED_PARTS.intersection(relative_parts):
                    continue
                if path.is_symlink():
                    raise ValueError(
                        "inventory source must not contain symlinks: "
                        f"{path.relative_to(root).as_posix()}"
                    )
                if path.is_file():
                    result.add(path)
    result.discard(root / OUTPUT.relative_to(ROOT))
    return sorted(result, key=lambda path: path.relative_to(root).as_posix())


def files() -> list[Path]:
    return inventory_files()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "size": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in files()
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    inventory = {
        "format": "milai-ua-current-byte-inventory-v1",
        "excludes_secrets": True,
        "entry_count": len(entries),
        "entries_sha256": hashlib.sha256(canonical).hexdigest(),
        "entries": entries,
    }
    OUTPUT.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
