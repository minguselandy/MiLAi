#!/usr/bin/env python3
"""Build an index-backed archive catalog without modifying the legacy tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "milai-artifact-archive-v1"
USER_FILES = (
    "scripts/dg13u_u1_review.py",
    "tests/test_dg13u_u1_review.py",
)
CONTROL_MARKERS = (
    "receipt",
    "terminal",
    "run-lock",
    "run_lock",
    "results",
    "manifest",
    "summary",
    "decision",
    "ledger",
    "failure-index",
    "failure_index",
    "deliverable-index",
    "source-artifact-manifest",
)
STATUS_KEYS = (
    "terminal_status",
    "overall_status",
    "final_status",
    "release_status",
    "status",
    "disposition",
    "decision",
    "outcome",
)
RUN_KEYS = ("run_id", "attempt_id", "execution_id", "receipt_id", "goal_id")


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    write_bytes(path, canonical_json(value))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    count = 0
    digest = hashlib.sha256()
    with temporary.open("wb") as handle:
        for row in rows:
            raw = canonical_json(row)
            handle.write(raw)
            digest.update(raw)
            count += 1
    os.replace(temporary, path)
    return count, digest.hexdigest()


def run_git(legacy: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(legacy), *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def mode_string(mode: int) -> str:
    return format(stat.S_IMODE(mode), "04o")


def tree_aggregate(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in names:
            candidate = Path(root) / name
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            files += 1
            size += info.st_size
    return files, size


def aggregate_category(relative: Path, is_dir: bool) -> tuple[str, str] | None:
    parts = relative.parts
    name = relative.name
    if not parts:
        return None

    if parts[0] == "var":
        return "archive", "legacy experiment artifact byte store; cataloged separately"
    if parts[:2] == ("runtime", "var"):
        return "generated", "runtime operational data and content-addressed blobs"
    if parts[:2] == ("runtime", "backups"):
        return "generated", "runtime database backups"
    if parts[0] in {"logs", "refine-logs", "profile_output"}:
        return "generated", "runtime or experiment logs/profiles"
    if name in {".venv", "wheelhouse"} and is_dir:
        return "external", "installed or vendored third-party dependency tree"
    if parts[0] == ".aris":
        return "external", "external audit tool state"
    if name in {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"} and is_dir:
        return "generated", "tool cache"
    if name == "dist" and is_dir:
        return "generated", "build output"
    return None


def classify_file(relative: Path) -> tuple[str, str]:
    path = relative.as_posix()
    parts = relative.parts
    name = relative.name

    if name == ".env" or name.endswith(".local"):
        return "generated", "local environment or machine-specific configuration"
    if name.endswith((".log", ".prof", ".coverage")):
        return "generated", "runtime/test generated output"
    if name.endswith((".zip", ".tar", ".gz", ".whl")):
        return "archive", "binary snapshot or package retained as historical evidence"
    if parts[:2] == ("architecture", "v1.0"):
        return "product", "frozen logical architecture bundle"
    if parts[:2] == ("architecture", "v1.0-candidate"):
        return "archive", "superseded architecture candidate evidence"
    if parts and parts[0] == "runtime":
        return "product", "runtime source, migration, test, or configuration"
    if len(parts) >= 2 and parts[0] == "integrations":
        if parts[1] in {
            "python-client",
            "mcp",
            "openworker-mcp",
            "hooks",
            "langgraph",
            "autogen",
        }:
            return "product", "product integration package"
        return "lab", "unclassified integration retained for laboratory review"
    if parts and parts[0] == "contracts":
        return "product", "public/agent contract"
    if parts and parts[0] == "examples":
        return "product", "product integration example"
    if parts and parts[0] == ".github":
        return "product", "current build and release automation input"
    if parts and parts[0] in {"evals", "scripts", "tests", "research"}:
        return "lab", "evaluation, research, experiment runner, or harness test"
    if parts and parts[0] == "docs":
        if len(parts) >= 2 and parts[1] in {"adr", "runbooks", "security", "releases"}:
            return "product", "product architecture/operations/security documentation"
        if len(parts) >= 2 and parts[1] in {"reports", "reviews"}:
            return "archive", "historical report or review evidence"
        return "lab", "experiment contract, analysis, or development documentation"
    if name in {"AGENTS.md", ".gitignore", "MANIFEST.md"}:
        return "product", "repository governance or inventory"
    if name in {"EXPERIMENT_AUDIT.json", "EXPERIMENT_AUDIT.md"}:
        return "lab", "experiment audit"
    if name.startswith(("MiLAi_Logical_Architecture", "MiLAi_Lean_V1_实施合同", "MiLAi_Lean_V1_产品底座")):
        return "product", "current product architecture or implementation contract"
    if name.startswith(("MiLA_Current-State_Architecture", "MiLA_Real_Execution_Flow", "MiLAi_可用性与Agent接入")):
        return "product", "current-state product architecture or delivery document"
    if name in {"MiLAi技术升级需求说明_v2.md", "MiLAi开发实施与使用流程_v1.md"}:
        return "archive", "historical long-term design input"
    if name.endswith((".md", ".json", ".jsonl")):
        return "archive", "root historical goal, report, or evidence document"
    return "archive", "unassigned legacy root material retained for manual review"


def inventory_rows(legacy: Path, tracked: set[str], modified: set[str]) -> Iterable[dict[str, Any]]:
    for root, dirs, files in os.walk(legacy, topdown=True, followlinks=False):
        root_path = Path(root)
        relative_root = root_path.relative_to(legacy)
        if relative_root == Path(".git") or ".git" in relative_root.parts:
            dirs[:] = []
            continue

        kept_dirs: list[str] = []
        for directory in sorted(dirs):
            child = root_path / directory
            relative = child.relative_to(legacy)
            aggregated = aggregate_category(relative, True)
            if aggregated is None:
                kept_dirs.append(directory)
                continue
            category, reason = aggregated
            file_count, size_bytes = tree_aggregate(child)
            yield {
                "schema_version": SCHEMA_VERSION,
                "entry_type": "directory_aggregate",
                "path": relative.as_posix(),
                "category": category,
                "classification_reason": reason,
                "file_count": file_count,
                "size_bytes": size_bytes,
                "hash_policy": "index_only_no_tree_hash",
            }
        dirs[:] = kept_dirs

        for filename in sorted(files):
            source = root_path / filename
            relative = source.relative_to(legacy)
            if ".git" in relative.parts:
                continue
            info = source.lstat()
            category, reason = classify_file(relative)
            git_state = "untracked_or_ignored"
            relative_text = relative.as_posix()
            if relative_text in tracked:
                git_state = "modified" if relative_text in modified else "tracked_clean"
            sensitive = filename == ".env"
            row: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "entry_type": "file",
                "path": relative_text,
                "category": category,
                "classification_reason": reason,
                "size_bytes": info.st_size,
                "mode": mode_string(info.st_mode),
                "git_state": git_state,
                "hash_policy": "omitted_sensitive" if sensitive else "sha256",
            }
            if not sensitive:
                row["sha256"] = sha256_file(source)
            yield row


def artifact_role(name: str) -> str:
    lower = name.lower()
    for marker in CONTROL_MARKERS:
        if marker in lower:
            return marker.replace("_", "-")
    return "control-artifact"


def is_control_artifact(path: Path) -> bool:
    lower = path.name.lower()
    return path.suffix.lower() in {".json", ".jsonl"} and any(marker in lower for marker in CONTROL_MARKERS)


def find_scalar(value: Any, keys: tuple[str, ...], depth: int = 0) -> str | None:
    if depth > 3:
        return None
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float, bool)):
                return str(candidate)
        for child in value.values():
            found = find_scalar(child, keys, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, list) and depth < 2:
        for child in value[:20]:
            found = find_scalar(child, keys, depth + 1)
            if found is not None:
                return found
    return None


def artifact_metadata(path: Path) -> tuple[str | None, str | None, str | None]:
    if path.suffix.lower() == ".jsonl":
        return None, "LEDGER", None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "UNPARSEABLE_JSON", "json_parse_failed"
    run_id = find_scalar(value, RUN_KEYS)
    status = find_scalar(value, STATUS_KEYS)
    return run_id, status, None


def artifact_rows(legacy: Path) -> Iterable[dict[str, Any]]:
    artifact_root = legacy / "var"
    for root, dirs, files in os.walk(artifact_root, topdown=True, followlinks=False):
        dirs.sort()
        for filename in sorted(files):
            path = Path(root) / filename
            if not is_control_artifact(path):
                continue
            relative = path.relative_to(legacy)
            info = path.lstat()
            run_id, status, parse_note = artifact_metadata(path)
            logical_run = run_id or path.parent.name
            row: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "storage_mode": "legacy_path_index",
                "logical_run": logical_run,
                "artifact_role": artifact_role(filename),
                "legacy_relative_path": relative.as_posix(),
                "legacy_absolute_path": str(path.resolve()),
                "reported_status": status or "UNSPECIFIED",
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "sha256": sha256_file(path),
                "hash_policy": "sha256",
            }
            if parse_note:
                row["parse_note"] = parse_note
            yield row


def preserve_user_work(legacy: Path, archive: Path) -> dict[str, Any]:
    root = archive / "preserved-user-work"
    entries: list[dict[str, Any]] = []
    for relative_text in USER_FILES:
        relative = Path(relative_text)
        current_source = legacy / relative
        current_target = root / "current" / relative
        base_target = root / "head-base" / relative
        current_target.parent.mkdir(parents=True, exist_ok=True)
        base_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current_source, current_target)
        base_bytes = run_git(legacy, "show", f"HEAD:{relative_text}")
        write_bytes(base_target, base_bytes)
        current_mode = mode_string(current_source.lstat().st_mode)
        base_mode = run_git(legacy, "ls-tree", "HEAD", "--", relative_text).decode().split()[0]
        base_target.chmod(0o755 if base_mode == "100755" else 0o644)
        entries.append(
            {
                "path": relative_text,
                "current_snapshot": current_target.relative_to(archive).as_posix(),
                "current_sha256": sha256_file(current_target),
                "current_mode": current_mode,
                "head_snapshot": base_target.relative_to(archive).as_posix(),
                "head_sha256": sha256_file(base_target),
                "head_git_mode": base_mode,
            }
        )
    patch = run_git(legacy, "diff", "--binary", "--", *USER_FILES)
    patch_path = root / "dg13u-user-work.patch"
    write_bytes(patch_path, patch)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "legacy_root": str(legacy.resolve()),
        "legacy_head": run_git(legacy, "rev-parse", "HEAD").decode().strip(),
        "patch_path": patch_path.relative_to(archive).as_posix(),
        "patch_sha256": sha256_file(patch_path),
        "patch_size_bytes": patch_path.stat().st_size,
        "entries": entries,
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def summarize_inventory(path: Path) -> dict[str, Any]:
    category_counts: Counter[str] = Counter()
    category_bytes: Counter[str] = Counter()
    entry_counts: Counter[str] = Counter()
    hashed_files = 0
    sensitive_files = 0
    total_rows = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            total_rows += 1
            category_counts[row["category"]] += int(row.get("file_count", 1))
            category_bytes[row["category"]] += int(row["size_bytes"])
            entry_counts[row["entry_type"]] += 1
            if row.get("sha256"):
                hashed_files += 1
            if row.get("hash_policy") == "omitted_sensitive":
                sensitive_files += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory_rows": total_rows,
        "represented_file_count_by_category": dict(sorted(category_counts.items())),
        "represented_bytes_by_category": dict(sorted(category_bytes.items())),
        "entry_count_by_type": dict(sorted(entry_counts.items())),
        "hashed_file_count": hashed_files,
        "sensitive_metadata_only_count": sensitive_files,
        "inventory_sha256": sha256_file(path),
    }


def summarize_artifacts(path: Path) -> dict[str, Any]:
    roles: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    bytes_by_role: Counter[str] = Counter()
    unique_runs: set[str] = set()
    total = 0
    size = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            total += 1
            item_size = int(row["size_bytes"])
            size += item_size
            roles[row["artifact_role"]] += 1
            statuses[row["reported_status"]] += 1
            bytes_by_role[row["artifact_role"]] += item_size
            unique_runs.add(row["logical_run"])
    return {
        "schema_version": SCHEMA_VERSION,
        "storage_mode": "legacy_path_index",
        "artifact_count": total,
        "artifact_bytes": size,
        "logical_run_count": len(unique_runs),
        "artifact_count_by_role": dict(sorted(roles.items())),
        "artifact_bytes_by_role": dict(sorted(bytes_by_role.items())),
        "reported_status_count": dict(sorted(statuses.items())),
        "catalog_sha256": sha256_file(path),
    }


def render_report(
    legacy: Path,
    inventory: dict[str, Any],
    artifacts: dict[str, Any],
    preserved: dict[str, Any],
    captured_at: str,
) -> str:
    category_lines = "\n".join(
        f"| {category} | {count:,} | {inventory['represented_bytes_by_category'][category]:,} |"
        for category, count in inventory["represented_file_count_by_category"].items()
    )
    role_lines = "\n".join(
        f"| {role} | {count:,} | {artifacts['artifact_bytes_by_role'][role]:,} |"
        for role, count in artifacts["artifact_count_by_role"].items()
    )
    preserved_lines = "\n".join(
        f"- `{entry['path']}`: current `{entry['current_sha256']}`, HEAD `{entry['head_sha256']}`"
        for entry in preserved["entries"]
    )
    return f"""# MiLAi Split Audit

Captured at: `{captured_at}`  
Legacy root: `{legacy.resolve()}`  
Legacy HEAD: `{preserved['legacy_head']}`

## Result

The legacy directory is not a reproducible product repository: nearly all
current source, configuration, documentation and experiment outputs are outside
its six-file Git index. The split must therefore use curated snapshot commits,
not history rewriting.

This archive preserves an index-backed map of legacy evidence and a complete
classification of retained source material. It does not modify or duplicate
the legacy artifact byte store.

## Source classification

| Category | Represented files | Bytes |
| --- | ---: | ---: |
{category_lines}

- inventory rows: `{inventory['inventory_rows']:,}`
- individually SHA-256 hashed files: `{inventory['hashed_file_count']:,}`
- sensitive metadata-only files: `{inventory['sensitive_metadata_only_count']:,}`
- source inventory SHA-256: `{inventory['inventory_sha256']}`

Generated and external dependency trees are aggregated to keep the manifest
small. Source/config/document files remain individually addressable.

## Legacy control artifacts

| Artifact role | Count | Bytes |
| --- | ---: | ---: |
{role_lines}

- indexed artifacts: `{artifacts['artifact_count']:,}`
- indexed bytes: `{artifacts['artifact_bytes']:,}`
- logical run identifiers: `{artifacts['logical_run_count']:,}`
- catalog SHA-256: `{artifacts['catalog_sha256']}`

The full legacy `var/` tree remains external. A catalog status is the status
reported by the artifact, not a fresh validity judgment.

## Preserved user work

{preserved_lines}

- binary-safe patch SHA-256: `{preserved['patch_sha256']}`
- patch bytes: `{preserved['patch_size_bytes']}`

The snapshots and patch are copies only. The tracked legacy files were neither
staged nor reset.

## Split recommendation

Create two independent sibling repositories:

1. `MiLAi-Product`: Runtime, python-client, MCP, OpenWorker-MCP, hooks,
   LangGraph and AutoGen packages, contracts, frozen architecture and minimal
   product operations docs.
2. `MiLAi-Lab`: evaluation, benchmark, research, historical Goal material and
   experiment harnesses, pinned to exact Product wheel/contract identities.

Freeze the legacy input with an explicit tag before retirement. Product must
never import Lab. Archive output is an index/preservation boundary, not an
executable fallback or a replacement Product/Lab source tree.

## Known boundary facts

- `architecture/v1.0` bundle validation passes, while the broader project
  source lock has pre-existing drift.
- Runtime's non-integration core passed when three cross-boundary tests were
  excluded; those tests must be moved or repaired during the split.
- Experiment code has hundreds of direct Runtime imports, including private
  symbols; an immediate public-API-only cut would not be credible.
- Build outputs, virtual environments and operational data account for most
  workspace size and belong in neither new source repository.

## Validation

Run `python3 tools/validate_archive.py --check-legacy` from this repository.
It verifies archive closure, JSONL ordering/schema, all indexed legacy hashes,
the preserved snapshots and that the patch recreates the current user files
from their preserved HEAD bases.
"""


def build_archive(legacy: Path, archive: Path, captured_at: str) -> None:
    legacy = legacy.resolve()
    archive = archive.resolve()
    if legacy == archive or legacy in archive.parents:
        raise SystemExit("archive root must not be inside the legacy repository")
    if not (legacy / ".git").is_dir():
        raise SystemExit(f"legacy root is not a Git worktree: {legacy}")
    archive.mkdir(parents=True, exist_ok=True)

    tracked = set(run_git(legacy, "ls-files", "-z").decode().split("\0"))
    tracked.discard("")
    modified = set(run_git(legacy, "diff", "--name-only", "-z").decode().split("\0"))
    modified.discard("")

    inventory_path = archive / "manifests/source-classification.jsonl"
    write_jsonl(
        inventory_path,
        sorted(inventory_rows(legacy, tracked, modified), key=lambda row: row["path"]),
    )
    inventory_summary = summarize_inventory(inventory_path)
    inventory_summary.update(
        {
            "captured_at": captured_at,
            "legacy_root": str(legacy),
            "legacy_head": run_git(legacy, "rev-parse", "HEAD").decode().strip(),
            "legacy_tracked_file_count": len(tracked),
            "legacy_modified_tracked_files": sorted(modified),
        }
    )
    write_json(archive / "manifests/source-classification.summary.json", inventory_summary)

    artifact_path = archive / "catalogs/legacy-artifacts.jsonl"
    write_jsonl(
        artifact_path,
        sorted(artifact_rows(legacy), key=lambda row: row["legacy_relative_path"]),
    )
    artifact_summary = summarize_artifacts(artifact_path)
    artifact_summary.update(
        {
            "captured_at": captured_at,
            "legacy_root": str(legacy),
            "catalog_scope": "legacy var control artifacts only",
        }
    )
    write_json(archive / "catalogs/legacy-artifacts.summary.json", artifact_summary)

    preserved = preserve_user_work(legacy, archive)
    report = render_report(legacy, inventory_summary, artifact_summary, preserved, captured_at)
    write_bytes(archive / "reports/SPLIT_AUDIT.md", report.encode("utf-8"))

    indexed_files = []
    for path in sorted(archive.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(archive).as_posix()
        if relative == "manifests/archive-index.json":
            continue
        indexed_files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    archive_index = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "legacy_root": str(legacy),
        "legacy_head": preserved["legacy_head"],
        "file_count": len(indexed_files),
        "files": indexed_files,
        "entries_sha256": sha256_bytes(canonical_json(indexed_files)),
    }
    write_json(archive / "manifests/archive-index.json", archive_index)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument(
        "--captured-at",
        default=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    args = parser.parse_args()
    build_archive(args.legacy_root, args.archive_root, args.captured_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
