#!/usr/bin/env python3
"""Fail-fast checks for the three-bundle MiLAi repository boundary."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Iterable


LEGACY_ROOTS = {
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
}
FORBIDDEN_TRACKED_PARTS = {
    ".aris",
    ".env",
    ".pytest_cache",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
    ".uv-cache",
    "backups",
    "build",
    "dist",
    "logs",
    "var",
    "venv",
    "wheelhouse",
    "wheels",
}


def tracked(root: Path) -> list[str]:
    raw = subprocess.check_output(("git", "-C", str(root), "ls-files", "-z"))
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def import_root(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def scan_python(paths: Iterable[Path], forbidden: set[str]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for directory in paths:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                blocked = sorted({name for name in names if import_root(name) in forbidden})
                if blocked:
                    findings.append(
                        {
                            "path": path.relative_to(root_for(path)).as_posix(),
                            "line": node.lineno,
                            "kind": "forbidden_import",
                            "detail": blocked,
                        }
                    )
    return findings


def root_for(path: Path) -> Path:
    for parent in (path, *path.parents):
        if (parent / ".git").is_dir() or (parent / ".git").is_file():
            return parent
    return path.anchor and Path(path.anchor) or path


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    paths = tracked(repo)
    findings: list[dict[str, object]] = []

    for path in paths:
        parts = Path(path).parts
        if parts and parts[0] in LEGACY_ROOTS:
            findings.append({"path": path, "kind": "retired_root_path", "detail": parts[0]})
        if any(part in FORBIDDEN_TRACKED_PARTS for part in parts):
            findings.append({"path": path, "kind": "forbidden_generated_path", "detail": parts})

    for bundle in ("MiLAi-Product", "MiLAi-Lab", "MiLAi-Artifact-Archive"):
        bundle_root = repo / bundle
        for nested in bundle_root.rglob(".git"):
            if nested != bundle_root / ".git":
                findings.append(
                    {"path": nested.relative_to(repo).as_posix(), "kind": "nested_git", "detail": "remove clone metadata"}
                )

    findings.extend(
        scan_python(
            [repo / "MiLAi-Product" / "runtime" / "src", repo / "MiLAi-Product" / "integrations"],
            {"evals", "research", "scripts", "milai_lab", "MiLAi_Lab", "MiLAi_Artifact_Archive"},
        )
    )
    findings.extend(
        scan_python(
            [repo / "MiLAi-Lab" / "src" / "milai_lab"],
            {"milai", "milai_client", "milai_openworker_mcp", "milai_hooks", "evals", "research", "scripts"},
        )
    )
    findings.extend(
        scan_python(
            [repo / "MiLAi-Artifact-Archive" / "tools"],
            {"milai", "milai_lab", "milai_client", "milai_openworker_mcp"},
        )
    )

    result = {
        "schema": "milai-boundary-check-v1",
        "tracked_paths": len(paths),
        "findings": findings,
        "status": "PASS" if not findings else "FAIL",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
