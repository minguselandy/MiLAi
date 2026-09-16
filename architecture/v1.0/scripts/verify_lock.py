#!/usr/bin/env python3
"""Verify SHA-256 locks for the MiLAi architecture candidate bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _defaults() -> tuple[Path, Path, Path]:
    script = Path(__file__).resolve()
    project = script.parents[3]
    return script.parents[1], project, project.parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(base: Path, relative: Any) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative:
        return None, f"invalid path value: {relative!r}"
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None, f"unsafe relative path: {relative!r}"
    resolved_base = base.resolve()
    resolved = (resolved_base / path).resolve(strict=False)
    if not resolved.is_relative_to(resolved_base):
        return None, f"path escapes lock base: {relative!r}"
    return resolved, None


def _verify_entries(
    entries: Any,
    *,
    bases: dict[str, Path],
    default_base: str | None,
    label: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(entries, list):
        return [f"{label} must be a list"]
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"{label}[{index}] must be an object")
            continue
        base_name = entry.get("base", default_base)
        if base_name not in bases:
            errors.append(f"{label}[{index}] has unknown base: {base_name!r}")
            continue
        relative = entry.get("path")
        key = (str(base_name), str(relative))
        if key in seen:
            errors.append(f"{label} has duplicate lock: {base_name}:{relative}")
            continue
        seen.add(key)
        path, path_error = _safe_path(bases[base_name], relative)
        if path_error:
            errors.append(f"{label}[{index}]: {path_error}")
            continue
        assert path is not None
        expected = entry.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"{label}[{index}] has invalid sha256")
            continue
        if not path.is_file():
            errors.append(f"locked file is missing: {base_name}:{relative}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(
                f"hash drift: {base_name}:{relative} expected={expected} actual={actual}"
            )
    return errors


def _git_output(
    repository: Path, arguments: list[str]
) -> tuple[bytes | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        return None, str(exc)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        return None, detail or f"git exited {result.returncode}"
    return result.stdout, None


def _verify_git_locks(entries: Any, workspace: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(entries, list):
        return ["git_locks must be a list"]
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"git_locks[{index}] must be an object")
            continue
        relative = entry.get("path")
        repository, path_error = _safe_path(workspace, relative)
        if path_error:
            errors.append(f"git_locks[{index}]: {path_error}")
            continue
        assert repository is not None
        if str(relative) in seen:
            errors.append(f"git_locks has duplicate repository: {relative}")
            continue
        seen.add(str(relative))
        if not repository.is_dir():
            errors.append(f"git repository is missing: workspace:{relative}")
            continue

        head, git_error = _git_output(repository, ["rev-parse", "HEAD"])
        if git_error:
            errors.append(f"cannot read git HEAD for {relative}: {git_error}")
            continue
        assert head is not None
        actual_commit = head.decode("ascii", errors="replace").strip()
        expected_commit = entry.get("commit")
        if actual_commit != expected_commit:
            errors.append(
                f"git commit drift: workspace:{relative} "
                f"expected={expected_commit} actual={actual_commit}"
            )

        expected_status_hash = entry.get("status_sha256")
        if expected_status_hash is not None:
            status, status_error = _git_output(
                repository,
                ["status", "--porcelain=v1", "--untracked-files=all"],
            )
            if status_error:
                errors.append(f"cannot read git status for {relative}: {status_error}")
            else:
                assert status is not None
                actual_status_hash = hashlib.sha256(status).hexdigest()
                if actual_status_hash != expected_status_hash:
                    errors.append(
                        f"git status drift: workspace:{relative} "
                        f"expected={expected_status_hash} actual={actual_status_hash}"
                    )

        expected_diff_hash = entry.get("diff_sha256")
        if expected_diff_hash is not None:
            diff, diff_error = _git_output(repository, ["diff", "--binary"])
            if diff_error:
                errors.append(f"cannot read git diff for {relative}: {diff_error}")
            else:
                assert diff is not None
                actual_diff_hash = hashlib.sha256(diff).hexdigest()
                if actual_diff_hash != expected_diff_hash:
                    errors.append(
                        f"git diff drift: workspace:{relative} "
                        f"expected={expected_diff_hash} actual={actual_diff_hash}"
                    )
    return errors


def collect_hash_errors(
    bundle_root: Path | None = None,
    project_root: Path | None = None,
    workspace_root: Path | None = None,
    scope: str = "all",
    verification_mode: str = "development",
    expected_manifest_sha256: str | None = None,
) -> list[str]:
    """Return manifest or hash failures without changing any files."""
    default_bundle, default_project, default_workspace = _defaults()
    bundle = (bundle_root or default_bundle).resolve()
    project = (project_root or default_project).resolve()
    workspace = (workspace_root or default_workspace).resolve()
    if scope not in {"bundle", "project", "all"}:
        return [f"unknown verification scope: {scope!r}"]
    if verification_mode not in {"development", "review", "release"}:
        return [f"unknown verification mode: {verification_mode!r}"]
    manifest_path = bundle / "architecture_manifest.json"
    if not manifest_path.is_file():
        return ["architecture_manifest.json is missing"]
    actual_manifest_sha256 = sha256_file(manifest_path)
    trust_anchor_required = verification_mode in {"review", "release"}
    if trust_anchor_required and expected_manifest_sha256 is None:
        return [
            f"{verification_mode} verification requires an external expected manifest SHA-256"
        ]
    if expected_manifest_sha256 is not None:
        if len(expected_manifest_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in expected_manifest_sha256
        ):
            return ["external expected manifest SHA-256 is invalid"]
        if actual_manifest_sha256 != expected_manifest_sha256:
            return [
                (
                    "external manifest trust anchor mismatch: "
                    f"expected={expected_manifest_sha256} "
                    f"actual={actual_manifest_sha256}"
                )
            ]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"architecture_manifest.json cannot be parsed: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]

    errors: list[str] = []
    if manifest.get("format_version") != "milai-architecture-manifest-v1":
        errors.append("manifest format_version mismatch")
    if manifest.get("architecture_version") != "1.0.0":
        errors.append("manifest architecture_version mismatch")
    if manifest.get("status") != "FROZEN":
        errors.append("manifest status must be FROZEN")
    if manifest.get("freeze_status") != "LOGICAL_ARCHITECTURE_FROZEN":
        errors.append("manifest freeze_status must be LOGICAL_ARCHITECTURE_FROZEN")

    bases = {"bundle": bundle, "project": project, "workspace": workspace}
    errors.extend(
        _verify_entries(
            manifest.get("locked_files"),
            bases=bases,
            default_base="bundle",
            label="locked_files",
        )
    )
    if scope in {"project", "all"}:
        source_locks = manifest.get("source_locks")
        if isinstance(source_locks, list) and scope == "project":
            source_locks = [
                entry
                for entry in source_locks
                if isinstance(entry, dict) and entry.get("base") == "project"
            ]
        errors.extend(
            _verify_entries(
                source_locks,
                bases=bases,
                default_base=None,
                label="source_locks",
            )
        )
    if scope == "all":
        errors.extend(_verify_git_locks(manifest.get("git_locks"), workspace))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=("bundle", "project", "all"),
        default="all",
        help="bundle only, bundle+project, or the complete workspace lock",
    )
    parser.add_argument(
        "--mode",
        choices=("development", "review", "release"),
        default="development",
        help="review/release require an external manifest digest trust anchor",
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        help="trusted manifest digest obtained outside the mutable candidate bundle",
    )
    arguments = parser.parse_args()
    errors = collect_hash_errors(
        scope=arguments.scope,
        verification_mode=arguments.mode,
        expected_manifest_sha256=arguments.expected_manifest_sha256,
    )
    if errors:
        print("MiLAi architecture lock verification: FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("MiLAi architecture lock verification: PASS (1.0.0 frozen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
