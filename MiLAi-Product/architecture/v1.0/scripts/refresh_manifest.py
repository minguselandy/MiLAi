#!/usr/bin/env python3
"""Refresh only already-declared MiLAi architecture SHA-256 locks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ManifestRefreshError(RuntimeError):
    """The declared lock set is unsafe, incomplete, or cannot be refreshed."""


def _defaults() -> tuple[Path, Path, Path]:
    script = Path(__file__).resolve()
    project = script.parents[3]
    return script.parents[1], project, project.parent


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_locked_file(base: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ManifestRefreshError(f"{label} has an invalid path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ManifestRefreshError(f"{label} has an unsafe path: {relative!r}")
    resolved_base = base.resolve()
    resolved = (resolved_base / path).resolve(strict=False)
    if not resolved.is_relative_to(resolved_base):
        raise ManifestRefreshError(f"{label} escapes its lock base: {relative!r}")
    if not resolved.is_file():
        raise ManifestRefreshError(f"{label} target is missing: {relative}")
    return resolved


def _refresh_entries(
    entries: Any,
    *,
    bases: dict[str, Path],
    default_base: str | None,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ManifestRefreshError(f"{label} must be a list")
    refreshed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise ManifestRefreshError(f"{label}[{index}] must be an object")
        entry = dict(raw_entry)
        base_name = entry.get("base", default_base)
        if base_name not in bases:
            raise ManifestRefreshError(
                f"{label}[{index}] has unknown base: {base_name!r}"
            )
        relative = entry.get("path")
        key = (str(base_name), str(relative))
        if key in seen:
            raise ManifestRefreshError(f"{label} has duplicate lock: {key}")
        seen.add(key)
        if base_name == "bundle" and relative == "architecture_manifest.json":
            raise ManifestRefreshError("architecture_manifest.json must not self-lock")
        target = _resolve_locked_file(
            bases[str(base_name)], relative, f"{label}[{index}]"
        )
        entry["sha256"] = _sha256_file(target)
        refreshed.append(entry)
    return sorted(
        refreshed,
        key=lambda entry: (str(entry.get("base", default_base)), str(entry["path"])),
    )


def refresh_manifest(
    bundle_root: Path | None = None,
    project_root: Path | None = None,
    workspace_root: Path | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Return a refreshed manifest and optionally replace it atomically.

    The function never discovers or adds files. It hashes exactly the existing
    locked_files/source_locks declarations and leaves Git locks unchanged.
    """

    default_bundle, default_project, default_workspace = _defaults()
    bundle = (bundle_root or default_bundle).resolve()
    project = (project_root or default_project).resolve()
    workspace = (workspace_root or default_workspace).resolve()
    manifest_path = bundle / "architecture_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestRefreshError(f"cannot read architecture manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestRefreshError("manifest root must be an object")
    if manifest.get("manifest_self_lock") is not False:
        raise ManifestRefreshError("manifest_self_lock must remain false")

    bases = {"bundle": bundle, "project": project, "workspace": workspace}
    refreshed = dict(manifest)
    refreshed["locked_files"] = _refresh_entries(
        manifest.get("locked_files"),
        bases=bases,
        default_base="bundle",
        label="locked_files",
    )
    refreshed["source_locks"] = _refresh_entries(
        manifest.get("source_locks"),
        bases=bases,
        default_base=None,
        label="source_locks",
    )

    if write:
        payload = json.dumps(refreshed, ensure_ascii=False, indent=2) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".architecture-manifest-", dir=bundle
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, manifest_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return refreshed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and calculate declared locks without writing the manifest",
    )
    arguments = parser.parse_args()
    try:
        refreshed = refresh_manifest(write=not arguments.check)
    except ManifestRefreshError as exc:
        parser.exit(1, f"MiLAi architecture manifest refresh: FAILED\n- {exc}\n")
    print(
        "MiLAi architecture manifest refresh: "
        f"PASS ({len(refreshed['locked_files'])} bundle locks, "
        f"{len(refreshed['source_locks'])} source locks)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
