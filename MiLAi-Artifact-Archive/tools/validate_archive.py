#!/usr/bin/env python3
"""Validate the archive catalog and optionally re-hash indexed legacy files."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import shutil
import subprocess
import tempfile
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


def mode_string(path: Path) -> str:
    return format(stat.S_IMODE(path.stat().st_mode), "04o")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_jsonl(path: Path, required: set[str]) -> tuple[int, str]:
    digest = hashlib.sha256()
    previous = ""
    count = 0
    with path.open("rb") as handle:
        for number, raw in enumerate(handle, 1):
            digest.update(raw)
            row = json.loads(raw)
            missing = required - row.keys()
            if missing:
                raise RuntimeError(f"{path}:{number} missing keys {sorted(missing)}")
            order_key = str(row.get("path") or row.get("legacy_relative_path"))
            if previous and order_key < previous:
                raise RuntimeError(f"{path}:{number} is not path-sorted")
            previous = order_key
            count += 1
    return count, digest.hexdigest()


def validate_archive(archive: Path, legacy: Path | None, check_legacy: bool) -> dict[str, Any]:
    archive = archive.resolve()
    index = load_json(archive / "manifests/archive-index.json")
    expected_entries = hashlib.sha256(canonical_json(index["files"])).hexdigest()
    if index["entries_sha256"] != expected_entries:
        raise RuntimeError("archive index entry binding mismatch")
    for entry in index["files"]:
        path = archive / entry["path"]
        if not path.is_file():
            raise RuntimeError(f"missing archive file: {path}")
        if path.stat().st_size != entry["size_bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"archive file identity mismatch: {path}")

    source_path = archive / "manifests/source-classification.jsonl"
    source_count, source_digest = validate_jsonl(
        source_path,
        {"schema_version", "entry_type", "path", "category", "size_bytes", "hash_policy"},
    )
    source_summary = load_json(archive / "manifests/source-classification.summary.json")
    if source_summary["inventory_rows"] != source_count or source_summary["inventory_sha256"] != source_digest:
        raise RuntimeError("source inventory summary mismatch")

    artifact_path = archive / "catalogs/legacy-artifacts.jsonl"
    artifact_count, artifact_digest = validate_jsonl(
        artifact_path,
        {
            "schema_version",
            "logical_run",
            "artifact_role",
            "legacy_relative_path",
            "legacy_absolute_path",
            "reported_status",
            "size_bytes",
            "sha256",
        },
    )
    artifact_summary = load_json(archive / "catalogs/legacy-artifacts.summary.json")
    if artifact_summary["artifact_count"] != artifact_count or artifact_summary["catalog_sha256"] != artifact_digest:
        raise RuntimeError("artifact catalog summary mismatch")

    preserved = load_json(archive / "preserved-user-work/manifest.json")
    for entry in preserved["entries"]:
        current = archive / entry["current_snapshot"]
        base = archive / entry["head_snapshot"]
        if sha256_file(current) != entry["current_sha256"]:
            raise RuntimeError(f"preserved current snapshot mismatch: {current}")
        if mode_string(current) != entry["current_mode"]:
            raise RuntimeError(f"preserved current mode mismatch: {current}")
        if sha256_file(base) != entry["head_sha256"]:
            raise RuntimeError(f"preserved HEAD snapshot mismatch: {base}")
        expected_base_mode = "0755" if entry["head_git_mode"] == "100755" else "0644"
        if mode_string(base) != expected_base_mode:
            raise RuntimeError(f"preserved HEAD mode mismatch: {base}")
    patch = archive / preserved["patch_path"]
    if sha256_file(patch) != preserved["patch_sha256"]:
        raise RuntimeError("preserved patch mismatch")
    with tempfile.TemporaryDirectory(prefix="milai-archive-validate-") as temporary:
        temp_root = Path(temporary)
        for entry in preserved["entries"]:
            destination = temp_root / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive / entry["head_snapshot"], destination)
        subprocess.run(["git", "apply", str(patch)], cwd=temp_root, check=True)
        for entry in preserved["entries"]:
            if sha256_file(temp_root / entry["path"]) != entry["current_sha256"]:
                raise RuntimeError(f"patch reconstruction mismatch: {entry['path']}")

    checked_legacy = 0
    checked_source = 0
    if check_legacy:
        if legacy is None:
            raise RuntimeError("--check-legacy requires --legacy-root")
        legacy = legacy.resolve()
        with artifact_path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                path = legacy / row["legacy_relative_path"]
                if not path.is_file() or path.stat().st_size != row["size_bytes"] or sha256_file(path) != row["sha256"]:
                    raise RuntimeError(f"legacy artifact drift: {path}")
                checked_legacy += 1
        with source_path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row["entry_type"] != "file" or not row.get("sha256"):
                    continue
                path = legacy / row["path"]
                if not path.is_file() or path.stat().st_size != row["size_bytes"] or sha256_file(path) != row["sha256"]:
                    raise RuntimeError(f"legacy source drift: {path}")
                checked_source += 1

    return {
        "valid": True,
        "archive_index_files": index["file_count"],
        "source_inventory_rows": source_count,
        "artifact_catalog_rows": artifact_count,
        "legacy_artifacts_rehashed": checked_legacy,
        "legacy_source_files_rehashed": checked_source,
        "archive_entries_sha256": index["entries_sha256"],
        "source_inventory_sha256": source_digest,
        "artifact_catalog_sha256": artifact_digest,
        "preserved_patch_sha256": preserved["patch_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--check-legacy", action="store_true")
    args = parser.parse_args()
    result = validate_archive(args.archive_root, args.legacy_root, args.check_legacy)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
