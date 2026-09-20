"""Build the cleanup baseline module inventory with Python's standard library."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import tomllib

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCT_ROOT.parent
LAB_ROOT = REPO_ROOT / "MiLAi-Lab"
ARCHIVE_ROOT = REPO_ROOT / "MiLAi-Artifact-Archive"
OUTPUT_ROOT = PRODUCT_ROOT / "docs" / "cleanup"
JSON_PATH = OUTPUT_ROOT / "module-inventory.json"
MARKDOWN_PATH = OUTPUT_ROOT / "MODULE_INVENTORY.md"
BASELINE_PATH = OUTPUT_ROOT / "cleanup-baseline.json"

PRODUCTION_ROOTS = (
    PRODUCT_ROOT / "runtime" / "src",
    *(path / "src" for path in sorted((PRODUCT_ROOT / "integrations").iterdir())),
    PRODUCT_ROOT / "tools",
    LAB_ROOT / "src",
    LAB_ROOT / "tools",
    ARCHIVE_ROOT / "tools",
)
TEST_ROOTS = (
    PRODUCT_ROOT / "runtime" / "tests",
    *(path / "tests" for path in sorted((PRODUCT_ROOT / "integrations").iterdir())),
    LAB_ROOT / "tests",
)
PYPROJECTS = (
    PRODUCT_ROOT / "runtime" / "pyproject.toml",
    *(path / "pyproject.toml" for path in sorted((PRODUCT_ROOT / "integrations").iterdir())),
    LAB_ROOT / "pyproject.toml",
)
EXCLUDED_PARTS = frozenset(
    {".git", ".venv", "__pycache__", "build", "dist", ".mypy_cache", ".pytest_cache"}
)
PRODUCT_IMPORT_PREFIXES = (
    "milai",
    "milai_client",
    "milai_mcp",
    "milai_openworker_mcp",
    "milai_hooks",
    "milai_langgraph",
    "milai_autogen",
)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _active_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*.py")
        if not EXCLUDED_PARTS.intersection(path.parts)
        and "studies/archive" not in path.as_posix()
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _imports(tree: ast.Module) -> list[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            values.add(prefix + (node.module or ""))
    return sorted(values)


def _test_nodes(path: Path, tree: ast.Module) -> list[str]:
    relative = (
        path.relative_to(PRODUCT_ROOT).as_posix()
        if PRODUCT_ROOT in path.parents
        else _relative(path)
    )
    return [
        f"{relative}::{node.name}"
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]


def _literal_strings(node: ast.AST) -> list[str]:
    values: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.append(child.value)
    return values


def _public_surface(path: Path, tree: ast.Module) -> dict[str, Any] | None:
    if path.name != "__init__.py" and "facade" not in (ast.get_docstring(tree) or "").lower():
        return None
    exports: list[str] = []
    reexports: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            reexports.extend(_literal_import_names(node))
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                exports.extend(_literal_strings(node))
    return {
        "path": _relative(path),
        "declared_all": sorted(set(exports)),
        "reexports": sorted(set(reexports)),
    }


def _literal_import_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    prefix = ""
    if isinstance(node, ast.ImportFrom):
        prefix = "." * node.level + ((node.module + ".") if node.module else "")
    return [prefix + alias.name for alias in node.names]


def _compatibility_facade(path: Path, tree: ast.Module) -> dict[str, str] | None:
    doc = ast.get_docstring(tree) or ""
    lowered = doc.lower()
    if "compatibility facade" not in lowered and "compatibility shim" not in lowered:
        return None
    category = "UNKNOWN"
    if "public" in lowered or path.name in {"host_adapter.py", "context_preparation.py"}:
        category = "PUBLIC_COMPAT"
    elif "historical" in lowered:
        category = "HISTORICAL_COMPAT"
    elif "temporary" in lowered:
        category = "INTERNAL_TEMPORARY"
    return {"path": _relative(path), "category": category, "docstring": doc.splitlines()[0]}


def _entrypoints() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in PYPROJECTS:
        if not path.exists():
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        for group in ("scripts", "gui-scripts"):
            for name, target in sorted(project.get(group, {}).items()):
                entries.append(
                    {"name": name, "target": target, "kind": group, "source": _relative(path)}
                )
        poetry_scripts = data.get("tool", {}).get("poetry", {}).get("scripts", {})
        for name, target in sorted(poetry_scripts.items()):
            entries.append(
                {"name": name, "target": target, "kind": "poetry.scripts", "source": _relative(path)}
            )
    return entries


def _receipt_nodes() -> list[str]:
    nodes: set[str] = set()
    for path in sorted((PRODUCT_ROOT / "docs" / "revalidation").rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        stack: list[Any] = [data]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str) and re.fullmatch(
                r"[^\s]+\.py::test_[A-Za-z0-9_\-\[\]]+", value
            ):
                nodes.add(value)
    return sorted(nodes)


def _main() -> dict[str, Any]:
    production = sorted({path for root in PRODUCTION_ROOTS for path in _active_python_files(root)})
    tests = sorted({path for root in TEST_ROOTS for path in _active_python_files(root)})
    all_files = production + tests
    module_imports: list[dict[str, Any]] = []
    test_nodes: list[str] = []
    public_surfaces: list[dict[str, Any]] = []
    facades: list[dict[str, str]] = []
    lab_product_imports: list[dict[str, Any]] = []
    parse_failures: list[str] = []
    for path in all_files:
        tree = _parse(path)
        if tree is None:
            parse_failures.append(_relative(path))
            continue
        imports = _imports(tree)
        module_imports.append({"path": _relative(path), "imports": imports})
        if path in tests:
            test_nodes.extend(_test_nodes(path, tree))
        surface = _public_surface(path, tree)
        if surface is not None:
            public_surfaces.append(surface)
        facade = _compatibility_facade(path, tree)
        if facade is not None:
            facades.append(facade)
        if LAB_ROOT in path.parents:
            product_imports = [
                item
                for item in imports
                if item.lstrip(".").split(".", 1)[0] in PRODUCT_IMPORT_PREFIXES
            ]
            if product_imports:
                lab_product_imports.append(
                    {"path": _relative(path), "imports": product_imports}
                )
    hotspots: list[dict[str, Any]] = [
        {"path": _relative(path), "bytes": path.stat().st_size}
        for path in sorted(all_files, key=lambda item: item.stat().st_size, reverse=True)
        if path.stat().st_size >= 30_000
    ]
    thresholds = {
        str(limit): sum(item["bytes"] >= limit for item in hotspots)
        for limit in (30_000, 60_000, 100_000)
    }
    receipt_nodes = _receipt_nodes()
    missing_receipt_nodes = sorted(set(receipt_nodes) - set(test_nodes))
    path_groups = Counter(
        path.parts[path.parts.index("MiLAi-Product") + 1]
        if "MiLAi-Product" in path.parts
        else "MiLAi-Lab"
        if LAB_ROOT in path.parents
        else "MiLAi-Artifact-Archive"
        for path in production
    )
    manifest = json.loads((PRODUCT_ROOT / "product.manifest.json").read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {
        "schema_version": "milai-codebase-module-inventory-v1",
        "source": {
            "git_commit": baseline["baseline_commit"],
            "product_tree_sha256": manifest["tree_sha256"],
            "product_manifest_sha256": _sha256(PRODUCT_ROOT / "product.manifest.json"),
        },
        "scope": {
            "production_roots": [_relative(path) for path in PRODUCTION_ROOTS if path.exists()],
            "test_roots": [_relative(path) for path in TEST_ROOTS if path.exists()],
            "excluded": ["virtual/build/cache directories", "MiLAi-Lab/studies/archive/**"],
        },
        "counts": {
            "python_production_files": len(production),
            "python_test_files": len(tests),
            "pytest_nodes": len(test_nodes),
            "receipt_test_node_ids": len(receipt_nodes),
            "production_files_by_owner": dict(sorted(path_groups.items())),
            "hotspots_by_minimum_bytes": thresholds,
        },
        "entrypoints": _entrypoints(),
        "production_files": [_relative(path) for path in production],
        "test_files": [_relative(path) for path in tests],
        "public_import_surfaces": public_surfaces,
        "compatibility_facades": facades,
        "hotspots": hotspots,
        "module_imports": module_imports,
        "pytest_nodes": sorted(test_nodes),
        "receipt_test_node_ids": receipt_nodes,
        "missing_receipt_test_node_ids": missing_receipt_nodes,
        "lab_product_imports": lab_product_imports,
        "parse_failures": parse_failures,
    }


def _markdown(data: dict[str, Any]) -> str:
    counts = data["counts"]
    lines = [
        "# MiLAi module inventory",
        "",
        f"Source commit: `{data['source']['git_commit']}`",
        "",
        "## Counts",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Python production files | {counts['python_production_files']} |",
        f"| Python test files | {counts['python_test_files']} |",
        f"| Pytest top-level nodes | {counts['pytest_nodes']} |",
        f"| Receipt-referenced pytest node IDs | {counts['receipt_test_node_ids']} |",
        f"| Files >= 30 KB | {counts['hotspots_by_minimum_bytes']['30000']} |",
        f"| Files >= 60 KB | {counts['hotspots_by_minimum_bytes']['60000']} |",
        f"| Files >= 100 KB | {counts['hotspots_by_minimum_bytes']['100000']} |",
        "",
        "## Largest active Python files",
        "",
        "| Bytes | Path |",
        "| ---: | --- |",
    ]
    lines.extend(f"| {item['bytes']} | `{item['path']}` |" for item in data["hotspots"][:40])
    lines.extend(
        [
            "",
            "## Entrypoints",
            "",
            "| Name | Target | Source |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| `{item['name']}` | `{item['target']}` | `{item['source']}` |"
        for item in data["entrypoints"]
    )
    lines.extend(
        [
            "",
            "## Compatibility facades",
            "",
            "| Category | Path |",
            "| --- | --- |",
        ]
    )
    lines.extend(
        f"| `{item['category']}` | `{item['path']}` |"
        for item in data["compatibility_facades"]
    )
    lines.extend(
        [
            "",
            "## Receipt node compatibility",
            "",
            f"All `{len(data['receipt_test_node_ids'])}` referenced node IDs are present: "
            + ("`YES`" if not data["missing_receipt_test_node_ids"] else "`NO`"),
            "",
            "The complete node set, public-import surfaces, module import graph, and Lab→Product imports are in [`module-inventory.json`](module-inventory.json).",
            "",
            "## Lab → Product imports",
            "",
            f"`{len(data['lab_product_imports'])}` active Lab files contain Product-package imports. These are baseline observations, not newly approved private dependencies:",
            "",
        ]
    )
    lines.extend(
        f"- `{item['path']}` → " + ", ".join(f"`{name}`" for name in item["imports"])
        for item in data["lab_product_imports"]
    )
    lines.extend(
        [
            "",
            "## Scope notes",
            "",
            "- `MiLAi-Lab/studies/archive/**` is deliberately excluded and remains immutable.",
            "- Build, virtual-environment, cache, and distribution directories are excluded.",
            "- Inventory is observational and uses only Python's standard library.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = _main()
    rendered_json = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    rendered_markdown = _markdown(data)
    if args.check:
        stale = []
        if not JSON_PATH.exists() or JSON_PATH.read_text(encoding="utf-8") != rendered_json:
            stale.append(_relative(JSON_PATH))
        if not MARKDOWN_PATH.exists() or MARKDOWN_PATH.read_text(encoding="utf-8") != rendered_markdown:
            stale.append(_relative(MARKDOWN_PATH))
        if stale:
            raise SystemExit("stale module inventory: " + ", ".join(stale))
    else:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(rendered_json, encoding="utf-8")
        MARKDOWN_PATH.write_text(rendered_markdown, encoding="utf-8")
    print(json.dumps(data["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
