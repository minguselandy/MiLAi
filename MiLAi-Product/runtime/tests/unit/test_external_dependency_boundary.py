from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_IMPORT_ROOTS = {
    "graphiti_core",
    "hindsight",
    "mem0",
    "memory_intention",
    "openviking",
    "reme",
}


def test_runtime_has_no_external_memory_framework_imports() -> None:
    source_root = Path(__file__).parents[2] / "src" / "milai"
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.partition(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.partition(".")[0]}
            else:
                continue
            forbidden = roots & FORBIDDEN_IMPORT_ROOTS
            if forbidden:
                violations.append(f"{path}: {sorted(forbidden)}")
    assert not violations, "\n".join(violations)
