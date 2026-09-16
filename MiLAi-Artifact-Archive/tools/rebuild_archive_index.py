#!/usr/bin/env python3
"""Refresh only the Archive repository closure index.

Unlike build_archive.py, this tool never reads or rewrites legacy catalogs,
snapshots, or source trees. It is used after adding a versioned archive report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--legacy-head", default="pre-codebase-reorg-v1")
    parser.add_argument("--captured-at", default="2026-09-17T00:00:00+08:00")
    args = parser.parse_args()

    archive = args.archive_root.resolve()
    previous = json.loads((archive / "manifests/archive-index.json").read_text(encoding="utf-8"))
    files = []
    for path in sorted(archive.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(archive).as_posix()
        if relative == "manifests/archive-index.json":
            continue
        files.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})

    index = {
        "schema_version": previous.get("schema_version", "milai-artifact-archive-v1"),
        "captured_at": args.captured_at,
        "legacy_root": previous.get("legacy_root", "/cra/memory/mx_memory/MiLAi"),
        "legacy_head": args.legacy_head,
        "file_count": len(files),
        "files": files,
        "entries_sha256": hashlib.sha256(canonical_json(files)).hexdigest(),
    }
    (archive / "manifests/archive-index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
