from __future__ import annotations

import ast
import re
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_INACTIVE_SOURCES = {
    PROJECT_ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py",
}
LEGACY_IDENTITY_ALIASES = {
    "DG10_PREFETCH_V1",
    "DG11_GROUPED_COMPACT_V3",
    "DG11_TURN_WINDOW_V1",
    "dg11-grouped-compact-v1",
    "dg11-1",
}
NON_SEMANTIC_PRODUCT_NAME = re.compile(
    r"(?i)(dg[-_ ]?(?:10|11|12)|benchmark|cupid|horizon|beam|memora|longmemeval)"
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_active_integrations_do_not_import_runtime_internals() -> None:
    violations: list[str] = []
    for path in (PROJECT_ROOT / "integrations").glob("*/src/**/*.py"):
        if path in LEGACY_INACTIVE_SOURCES:
            continue
        forbidden = sorted(
            name
            for name in _imports(path)
            if name == "milai" or name.startswith("milai.")
        )
        if forbidden:
            violations.append(f"{path.relative_to(PROJECT_ROOT)}: {forbidden}")
    assert not violations, "\n".join(violations)


def test_runtime_does_not_import_non_product_layers() -> None:
    forbidden_roots = {"evals", "integrations", "scripts", "tests", "var"}
    violations: list[str] = []
    for path in (PROJECT_ROOT / "runtime/src/milai").rglob("*.py"):
        forbidden = sorted(
            name
            for name in _imports(path)
            if name.partition(".")[0] in forbidden_roots
        )
        if forbidden:
            violations.append(f"{path.relative_to(PROJECT_ROOT)}: {forbidden}")
    assert not violations, "\n".join(violations)


def test_integrations_do_not_declare_runtime_dependency() -> None:
    violations: list[str] = []
    for path in (PROJECT_ROOT / "integrations").glob("*/pyproject.toml"):
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        dependencies = project.get("dependencies", [])
        if any(
            dependency.split("[", 1)[0].startswith("milai-runtime")
            for dependency in dependencies
        ):
            violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert not violations, "\n".join(violations)


def test_active_product_names_are_semantic_or_explicit_legacy_aliases() -> None:
    roots = [PROJECT_ROOT / "runtime/src", *(PROJECT_ROOT / "integrations").glob("*/src")]
    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path in LEGACY_INACTIVE_SOURCES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                elif isinstance(node, (ast.Name, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    value = node.id if isinstance(node, ast.Name) else node.name
                else:
                    continue
                if NON_SEMANTIC_PRODUCT_NAME.search(value) and value not in LEGACY_IDENTITY_ALIASES:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {value!r}")
    assert not violations, "\n".join(violations)
