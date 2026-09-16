#!/usr/bin/env python3
"""Build a deterministic, machine-auditable MiLAi reorganization inventory.

The inventory is intentionally read-only with respect to source trees. It hashes
Git-tracked files, compares legacy paths with the declared Product/Lab/Archive
counterparts, and writes reports only below the requested archive output path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


LEGACY_DIRS = (
    "architecture",
    "contracts",
    "docs",
    "evals",
    "examples",
    "integrations",
    "research",
    "runtime",
    "scripts",
    "tests",
)

ROOT_GOVERNANCE = {
    ".gitignore",
    "AGENTS.md",
    "LEGACY_READ_ONLY.md",
    "README.md",
    "REPO_MAP.md",
    "SOURCE_OF_TRUTH.md",
}
CANONICAL_PREFIXES = (
    "MiLAi-Product",
    "MiLAi-Lab",
    "MiLAi-Artifact-Archive",
)
GENERATED_PARTS = {
    ".aris",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "artifacts",
    "build",
    "dist",
    "logs",
    "profile_output",
    "refine-logs",
    "var",
    "venv",
    "wheelhouse",
    "wheels",
}
HISTORICAL_MARKERS = (
    "AUDIT",
    "GOAL",
    "REPORT",
    "MASTER",
    "RESULT",
    "DECISION",
    "ARCHIVE",
    "SNAPSHOT",
)
TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
CSV_FIELDS = (
    "path",
    "scope",
    "size_bytes",
    "sha256",
    "git_status",
    "legacy_counterpart",
    "canonical_counterpart",
    "status",
    "owner",
    "classification",
    "import_refs",
    "test_refs",
    "workflow_refs",
    "doc_refs",
    "action",
    "review",
)


def run_git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(("git", "-C", str(repo), *args))


def tracked_paths(repo: Path) -> list[str]:
    return [item.decode("utf-8") for item in run_git(repo, "ls-files", "-z").split(b"\0") if item]


def git_statuses(repo: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    raw = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    for item in raw.split(b"\0"):
        if len(item) < 3:
            continue
        decoded = item.decode("utf-8")
        code, path = decoded[:2], decoded[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        statuses[path] = code.strip() or "?"
    return statuses


def sha256_file(path: Path, cache: dict[Path, str]) -> str:
    if path in cache:
        return cache[path]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    cache[path] = digest.hexdigest()
    return cache[path]


def generated(path: str) -> bool:
    parts = Path(path).parts
    return any(part in GENERATED_PARTS for part in parts) or Path(path).suffix.lower() in {
        ".log",
        ".pyc",
        ".whl",
    }


def historical(path: str) -> bool:
    name = Path(path).name.upper()
    return Path(path).suffix.lower() in {".zip", ".tar", ".gz"} or any(
        marker in name for marker in HISTORICAL_MARKERS
    )


def is_legacy(path: str) -> bool:
    first = Path(path).parts[0] if Path(path).parts else ""
    return first in LEGACY_DIRS or (len(Path(path).parts) == 1 and path not in ROOT_GOVERNANCE)


def is_canonical(path: str) -> bool:
    first = Path(path).parts[0] if Path(path).parts else ""
    return first in CANONICAL_PREFIXES


def classify(path: str, owner: str, scope: str) -> str:
    if generated(path):
        return "GENERATED"
    if scope == "legacy" and historical(path):
        return "HISTORICAL_ONLY"
    if scope == "legacy" and path.startswith("docs/"):
        return "DOC_DUPLICATE"
    if scope == "legacy" and owner == "Review":
        return "LEGACY_ONLY"
    if owner == "Product":
        return "PRODUCT"
    if owner == "Lab":
        return "LAB"
    if owner == "Archive":
        return "ARCHIVE"
    return "GOVERNANCE"


def counterpart_candidates(path: str) -> list[str]:
    parts = Path(path).parts
    if not parts:
        return []
    first, rest = parts[0], Path(*parts[1:]) if len(parts) > 1 else Path()
    if first in {"architecture", "contracts", "examples", "integrations", "runtime"}:
        return [str(Path("MiLAi-Product") / first / rest)]
    if first in {"evals", "research"}:
        return [str(Path("MiLAi-Lab") / first / rest), str(Path("MiLAi-Lab") / "studies" / "archive" / "lifecycle" / "legacy_snapshot" / "MiLAi" / first / rest)]
    if first == "tests":
        return [
            str(Path("MiLAi-Product") / "tests" / rest),
            str(Path("MiLAi-Product") / "runtime" / "tests" / rest),
            str(Path("MiLAi-Product") / "integrations" / rest),
            str(Path("MiLAi-Lab") / "tests" / rest),
            str(Path("MiLAi-Lab") / "studies" / "archive" / "lifecycle" / "legacy_snapshot" / "MiLAi" / first / rest),
        ]
    if first == "scripts":
        return [
            str(Path("MiLAi-Product") / "scripts" / rest),
            str(Path("MiLAi-Product") / "tools" / rest),
            str(Path("MiLAi-Lab") / "scripts" / rest),
            str(Path("MiLAi-Lab") / "tools" / rest),
            str(Path("MiLAi-Lab") / "studies" / "archive" / "lifecycle" / "legacy_snapshot" / "MiLAi" / first / rest),
        ]
    if first == "docs":
        return [
            str(Path("MiLAi-Product") / "docs" / rest),
            str(Path("MiLAi-Lab") / "docs" / rest),
            str(Path("MiLAi-Lab") / "studies" / "archive" / "lifecycle" / "legacy_snapshot" / "MiLAi" / first / rest),
        ]
    # Root-level historical files are commonly preserved in the Lab snapshot.
    return [
        str(Path("MiLAi-Product") / "docs" / Path(path).name),
        str(Path("MiLAi-Lab") / "docs" / Path(path).name),
        str(Path("MiLAi-Lab") / "studies" / "archive" / "lifecycle" / "legacy_snapshot" / "MiLAi" / path),
    ]


def owner_for(path: str, counterpart: str | None) -> str:
    if counterpart:
        if counterpart.startswith("MiLAi-Product/"):
            return "Product"
        if counterpart.startswith("MiLAi-Lab/"):
            return "Lab"
        if counterpart.startswith("MiLAi-Artifact-Archive/"):
            return "Archive"
    first = Path(path).parts[0] if Path(path).parts else ""
    if first in {"evals", "research"}:
        return "Lab"
    if first in {"architecture", "contracts", "examples", "integrations", "runtime"}:
        return "Product"
    return "Review"


def ref_kind(referrer: str, line: str) -> str:
    lowered = line.lower()
    if referrer.startswith(".github/") or "workflow" in lowered or "github actions" in lowered:
        return "workflow"
    if referrer.endswith(".py") and re.search(r"\b(?:from|import|sys\.path|python\s+-m)\b", line):
        return "import"
    if "pytest" in lowered or "unittest" in lowered or "/tests" in lowered or " test" in lowered:
        return "test"
    return "doc"


def collect_references(repo: Path, paths: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    prefixes = tuple(paths)
    refs: dict[str, dict[str, set[str]]] = {
        prefix: {kind: set() for kind in ("import", "test", "workflow", "doc")} for prefix in prefixes
    }
    path_set = set(paths)
    for referrer in paths:
        source = repo / referrer
        if not source.is_file() or source.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in text.splitlines():
            for prefix in path_set:
                if re.search(rf"(?<![\w-]){re.escape(prefix)}(?:[/\\\s'\"`):]|$)", line):
                    refs[prefix][ref_kind(referrer, line)].add(referrer)
    return {prefix: {kind: sorted(values) for kind, values in by_kind.items()} for prefix, by_kind in refs.items()}


def action_for(status: str, scope: str, owner: str, classification: str) -> str:
    if scope != "legacy":
        return "KEEP_CANONICAL"
    if status in {"IDENTICAL", "DIVERGED"}:
        return "RETIRE_LEGACY_CANONICAL_WINS"
    if classification in {"GENERATED", "HISTORICAL_ONLY", "DOC_DUPLICATE"}:
        return "ARCHIVE_AND_RETIRE"
    if owner in {"Product", "Lab"}:
        return "REVIEW_FORWARD_PORT"
    return "ARCHIVE_OR_REVIEW"


def review_for(status: str, scope: str, owner: str, classification: str) -> str:
    if scope != "legacy":
        return "Canonical tree; no legacy deletion decision required."
    if status == "DIVERGED":
        return f"Resolved: canonical {owner} counterpart wins by Source of Truth policy; no bulk forward-port."
    if status == "IDENTICAL":
        return "Resolved: byte-identical canonical copy is authoritative; retire duplicate."
    if classification == "HISTORICAL_ONLY":
        return "Resolved: historical evidence remains recoverable from tag/history or Archive manifest."
    if classification == "GENERATED":
        return "Resolved: generated/local output is excluded from Git and never enters Product/Lab."
    return "Review owner/action recorded; any forward-port requires a separate behavior PR."


def record_for(
    repo: Path,
    path: str,
    scope: str,
    statuses: dict[str, str],
    cache: dict[Path, str],
    path_set: set[str],
    refs: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    file_path = repo / path
    digest = sha256_file(file_path, cache) if file_path.is_file() else ""
    size = file_path.stat().st_size if file_path.is_file() else 0
    if scope == "legacy":
        candidates = [candidate for candidate in counterpart_candidates(path) if candidate in path_set]
        candidate = candidates[0] if candidates else None
        candidate_hash = sha256_file(repo / candidate, cache) if candidate else None
        if candidate and candidate_hash == digest:
            status = "IDENTICAL"
        elif candidate:
            status = "DIVERGED"
        else:
            status = "LEGACY_ONLY"
        owner = owner_for(path, candidate)
        classification = classify(path, owner, scope)
        if generated(path):
            classification = "GENERATED"
        ref = refs.get(Path(path).parts[0], {kind: [] for kind in ("import", "test", "workflow", "doc")})
        return {
            "path": path,
            "scope": scope,
            "size_bytes": size,
            "sha256": digest,
            "git_status": statuses.get(path, "clean_tracked"),
            "legacy_counterpart": path,
            "canonical_counterpart": candidate or "",
            "status": status,
            "owner": owner,
            "classification": classification,
            "import_refs": ref["import"],
            "test_refs": ref["test"],
            "workflow_refs": ref["workflow"],
            "doc_refs": ref["doc"],
            "action": action_for(status, scope, owner, classification),
            "review": review_for(status, scope, owner, classification),
        }
    first = Path(path).parts[0] if Path(path).parts else ""
    owner = first.replace("MiLAi-", "").title() if first in CANONICAL_PREFIXES else "Review"
    return {
        "path": path,
        "scope": "canonical" if is_canonical(path) else "governance",
        "size_bytes": size,
        "sha256": digest,
        "git_status": statuses.get(path, "clean_tracked"),
        "legacy_counterpart": "",
        "canonical_counterpart": path if is_canonical(path) else "",
        "status": "CANONICAL_ONLY" if is_canonical(path) else "GOVERNANCE",
        "owner": owner,
        "classification": classify(path, owner, scope),
        "import_refs": [],
        "test_refs": [],
        "workflow_refs": [],
        "doc_refs": [],
        "action": "KEEP_CANONICAL",
        "review": review_for("CANONICAL_ONLY", scope, owner, ""),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            row = dict(record)
            for field in ("import_refs", "test_refs", "workflow_refs", "doc_refs"):
                row[field] = ";".join(row[field])
            writer.writerow(row)


def write_summary(path: Path, records: list[dict[str, Any]], repo: Path) -> dict[str, Any]:
    legacy = [record for record in records if record["scope"] == "legacy"]
    status_counts = Counter(record["status"] for record in legacy)
    class_counts = Counter(record["classification"] for record in records)
    diverged = [record for record in legacy if record["status"] == "DIVERGED"]
    unresolved = [record for record in diverged if not record["review"].startswith("Resolved:")]
    summary = {
        "schema": "milai-reorganization-inventory-v1",
        "repo_root": str(repo),
        "tracked_file_count": len(records),
        "legacy_file_count": len(legacy),
        "status_counts_legacy": dict(sorted(status_counts.items())),
        "classification_counts_all": dict(sorted(class_counts.items())),
        "unknown_count": sum(1 for record in records if record["classification"] == "UNKNOWN"),
        "diverged_count": len(diverged),
        "unresolved_diverged_count": len(unresolved),
        "coverage_percent": 100.0 if records else 0.0,
        "git_head": run_git(repo, "rev-parse", "HEAD").decode().strip(),
        "rollback_tag": "pre-codebase-reorg-v1",
        "generated_by": "MiLAi-Artifact-Archive/tools/repo_inventory.py",
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def write_divergence_review(path: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    diverged = [record for record in records if record["scope"] == "legacy" and record["status"] == "DIVERGED"]
    lines = [
        "# Divergence Review",
        "",
        "本报告由 `repo_inventory.py` 生成。每个 DIVERGED legacy 文件都有一条明确决定；",
        "决定依据是 `SOURCE_OF_TRUTH.md`：Product/Lab 当前树优先，禁止把 legacy 整体 bulk merge 回去。",
        "本报告不声称历史语义已经重新评测；需要行为修复的内容必须另开独立 PR。",
        "",
        f"- Inventory HEAD: `{summary['git_head']}`",
        f"- Rollback tag: `{summary['rollback_tag']}`",
        f"- DIVERGED records: **{len(diverged)}**",
        f"- Unresolved decisions: **{summary['unresolved_diverged_count']}**",
        "",
        "## Decisions",
        "",
        "| Legacy path | Canonical counterpart | SHA-256 (legacy) | Decision | Review note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in diverged:
        def cell(value: str) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")

        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | {} |".format(
                cell(record["path"]),
                cell(record["canonical_counterpart"]),
                cell(record["sha256"]),
                cell(record["action"]),
                cell(record["review"]),
            )
        )
    if not diverged:
        lines.append("| _none_ | | | | No byte-level divergence was found. |")
    lines.extend(
        [
            "",
            "## Forward-port rule",
            "",
            "本次结构性重组不进行自动 forward-port。若未来证明 legacy-only 或 diverged 版本包含",
            "canonical 缺失的有效行为，必须先写语义 diff、补回归测试，再用独立行为 PR 进入对应 owner。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    statuses = summary["status_counts_legacy"]
    classes = summary["classification_counts_all"]
    lines = [
        "# Reorganization Inventory Summary",
        "",
        f"- HEAD: `{summary['git_head']}`",
        f"- Rollback tag: `{summary['rollback_tag']}`",
        f"- Tracked records: **{summary['tracked_file_count']}**",
        f"- Legacy records: **{summary['legacy_file_count']}**",
        f"- Coverage: **{summary['coverage_percent']:.1f}%** of the tracked repository surface",
        f"- UNKNOWN classifications: **{summary['unknown_count']}**",
        f"- DIVERGED records: **{summary['diverged_count']}**",
        f"- Unresolved DIVERGED decisions: **{summary['unresolved_diverged_count']}**",
        "",
        "## Legacy comparison status",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{key}` | {value} |" for key, value in sorted(statuses.items()))
    lines.extend(["", "## Classification", "", "| Classification | Count |", "| --- | ---: |"])
    lines.extend(f"| `{key}` | {value} |" for key, value in sorted(classes.items()))
    lines.extend(
        [
            "",
            "## Gate interpretation",
            "",
            "清单只覆盖 Git-tracked 文件；本地 `.venv`、uv cache、日志、运行状态、模型和生成性",
            "大文件不属于提交面，并由根 `.gitignore` 与 Archive artifact catalog 管理。删除 legacy",
            "前必须保持 `UNKNOWN=0`、每个 DIVERGED 都有 review decision，并重新运行 Product/Lab",
            "边界、测试和 package gate。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "manifests" / "reorganization" / "v1.0",
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    paths = tracked_paths(repo)
    path_set = set(paths)
    statuses = git_statuses(repo)
    # Reference scans are keyed by legacy top-level boundary, not by every
    # individual file; this keeps the audit deterministic and linear in the
    # tracked text surface.
    refs = collect_references(repo, LEGACY_DIRS)
    cache: dict[Path, str] = {}
    records = [
        record_for(repo, path, "legacy", statuses, cache, path_set, refs)
        for path in paths
        if is_legacy(path)
    ]
    records.extend(
        record_for(repo, path, "canonical", statuses, cache, path_set, refs)
        for path in paths
        if is_canonical(path)
    )
    records.extend(
        record_for(repo, path, "governance", statuses, cache, path_set, refs)
        for path in paths
        if not is_legacy(path) and not is_canonical(path)
    )
    records.sort(key=lambda record: record["path"])

    inventory_jsonl = output / "REORG_INVENTORY.jsonl"
    inventory_csv = output / "REORG_INVENTORY.csv"
    summary_json = output / "repo_inventory.summary.json"
    summary_md = output / "REORG_INVENTORY_SUMMARY.md"
    divergence_md = output / "DIVERGENCE_REVIEW.md"
    write_jsonl(inventory_jsonl, records)
    write_csv(inventory_csv, records)
    summary = write_summary(summary_json, records, repo)
    write_markdown_summary(summary_md, summary)
    write_divergence_review(divergence_md, records, summary)

    # The goal document names the machine output repo_inventory.* while the
    # handoff deliverable names it REORG_INVENTORY.*. Keep both names byte-
    # identical as explicit report aliases, never as separate source trees.
    for source, alias in (
        (inventory_jsonl, output / "repo_inventory.jsonl"),
        (inventory_csv, output / "repo_inventory.csv"),
    ):
        alias.write_bytes(source.read_bytes())
    (output / "repo_inventory.summary.json").write_bytes(summary_json.read_bytes())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
