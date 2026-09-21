"""Verify cleanup compatibility categories, receipt nodes, and test support imports."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PRODUCT_ROOT / "docs" / "cleanup" / "compatibility-registry.json"
AUDIT_PATH = PRODUCT_ROOT / "docs" / "cleanup" / "compatibility-dead-code-audit.json"
REVALIDATION_ROOT = PRODUCT_ROOT / "docs" / "revalidation"
CATEGORIES = {
    "PUBLIC_API",
    "PUBLIC_COMPAT",
    "TEST_COMPAT",
    "HISTORICAL_COMPAT",
    "INTERNAL_TEMPORARY",
}
TEST_ROOTS = (
    PRODUCT_ROOT / "runtime" / "tests",
    *(path / "tests" for path in sorted((PRODUCT_ROOT / "integrations").iterdir())),
)
SUPPORT_ROOTS = {
    "runtime/tests/integration/support",
    "integrations/python-client/tests/support",
    "integrations/mcp/tests/support",
}
NODE_PATTERN = re.compile(r"[^\s]+\.py::test_[A-Za-z0-9_\-\[\]]+")


def _read_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "milai-compatibility-registry-v1":
        raise ValueError("unsupported compatibility registry schema")
    if set(payload.get("categories", {})) != CATEGORIES:
        raise ValueError("compatibility registry categories are not the frozen five-category set")
    return payload


def _read_audit() -> dict[str, Any]:
    payload = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "milai-compatibility-dead-code-audit-v1":
        raise ValueError("unsupported compatibility dead-code audit schema")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("source_commit", ""))):
        raise ValueError("compatibility dead-code audit requires a full source commit")
    return payload


def _consumer_path(raw_path: str) -> Path:
    if raw_path.startswith("MiLAi-Lab/"):
        return PRODUCT_ROOT.parent / raw_path
    if raw_path.startswith("MiLAi-Artifact-Archive/"):
        return PRODUCT_ROOT.parent / raw_path
    return PRODUCT_ROOT / raw_path


def _verify_audit(entries: list[dict[str, Any]]) -> dict[str, int]:
    audit = _read_audit()
    dispositions = audit.get("dispositions")
    if not isinstance(dispositions, list):
        raise TypeError("compatibility dead-code audit dispositions must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for disposition in dispositions:
        if not isinstance(disposition, dict):
            raise TypeError("compatibility dead-code dispositions must be objects")
        entry_id = disposition.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in by_id:
            raise ValueError(f"invalid or duplicate audit disposition id: {entry_id!r}")
        if disposition.get("decision") not in {"RETAIN", "DELETE"}:
            raise ValueError(f"{entry_id}: invalid audit decision")
        if not isinstance(disposition.get("reason"), str) or not disposition["reason"]:
            raise ValueError(f"{entry_id}: audit reason is required")
        by_id[entry_id] = disposition

    registry_by_id = {entry["id"]: entry for entry in entries}
    if set(by_id) != set(registry_by_id):
        raise ValueError(
            "compatibility audit coverage drift: "
            f"missing={sorted(set(registry_by_id) - set(by_id))}, "
            f"extra={sorted(set(by_id) - set(registry_by_id))}"
        )

    retained_temporary = 0
    deleted = 0
    dimensions = {
        "production_consumers",
        "test_consumers",
        "cli_plugin_entrypoints",
        "lab_consumers",
        "receipt_consumers",
        "archive_consumers",
    }
    for entry_id, disposition in by_id.items():
        registry_entry = registry_by_id[entry_id]
        if disposition.get("category") != registry_entry["category"]:
            raise ValueError(f"{entry_id}: audit category does not match registry")
        decision = disposition["decision"]
        if decision == "DELETE":
            deleted += 1
            if registry_entry["category"] != "INTERNAL_TEMPORARY":
                raise ValueError(f"{entry_id}: only INTERNAL_TEMPORARY may be deleted")
        if registry_entry["category"] != "INTERNAL_TEMPORARY":
            continue
        checks = disposition.get("checks")
        if not isinstance(checks, dict) or set(checks) != dimensions:
            raise ValueError(f"{entry_id}: all six consumer dimensions are required")
        blockers = 0
        for dimension in sorted(dimensions):
            references = checks[dimension]
            if not isinstance(references, list) or not all(
                isinstance(reference, str) and reference for reference in references
            ):
                raise TypeError(f"{entry_id}: {dimension} must contain path strings")
            blockers += len(references)
            for reference in references:
                if not _consumer_path(reference).exists():
                    raise ValueError(f"{entry_id}: missing {dimension} path {reference!r}")
        if decision == "DELETE" and blockers:
            raise ValueError(f"{entry_id}: deletion candidate still has consumers")
        if decision == "RETAIN":
            retained_temporary += 1
            if not blockers:
                raise ValueError(f"{entry_id}: retained temporary entry lacks blocking evidence")
    return {
        "audit_dispositions": len(dispositions),
        "deleted": deleted,
        "retained_temporary": retained_temporary,
    }


def _receipt_nodes() -> set[str]:
    nodes: set[str] = set()
    for path in sorted(REVALIDATION_ROOT.rglob("*.json")):
        stack: list[Any] = [json.loads(path.read_text(encoding="utf-8"))]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str) and NODE_PATTERN.fullmatch(value):
                nodes.add(value)
    return nodes


def _top_level_test_nodes() -> set[str]:
    nodes: set[str] = set()
    for root in TEST_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(PRODUCT_ROOT).as_posix()
            for item in tree.body:
                is_test = isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    item.name.startswith("test_")
                )
                if is_test:
                    nodes.add(f"{relative}::{item.name}")
    return nodes


def _sibling_test_imports() -> list[str]:
    findings: list[str] = []
    for root in TEST_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(PRODUCT_ROOT).as_posix()
            if "/support/" in f"/{relative}":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for item in ast.walk(tree):
                imported: list[str] = []
                if isinstance(item, ast.ImportFrom) and item.module:
                    imported.append(item.module)
                elif isinstance(item, ast.Import):
                    imported.extend(alias.name for alias in item.names)
                for module in imported:
                    if any(part.startswith("test_") for part in module.split(".")):
                        findings.append(f"{relative}:{item.lineno}:{module}")
    return findings


def main() -> int:
    payload = _read_registry()
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise TypeError("compatibility registry entries must be a non-empty list")
    ids: set[str] = set()
    seen_categories: set[str] = set()
    declared_support_roots: set[str] = set()
    registered_nodes: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("compatibility registry entries must be objects")
        entry_id = entry.get("id")
        category = entry.get("category")
        if not isinstance(entry_id, str) or not entry_id or entry_id in ids:
            raise ValueError(f"invalid or duplicate compatibility entry id: {entry_id!r}")
        if category not in CATEGORIES:
            raise ValueError(f"{entry_id}: invalid compatibility category {category!r}")
        if not isinstance(entry.get("retention"), str) or not entry["retention"]:
            raise ValueError(f"{entry_id}: retention rationale is required")
        ids.add(entry_id)
        seen_categories.add(category)
        for raw_path in entry.get("paths", []):
            if not isinstance(raw_path, str) or not (PRODUCT_ROOT / raw_path).exists():
                raise ValueError(f"{entry_id}: missing registered path {raw_path!r}")
            if raw_path.endswith("/support"):
                declared_support_roots.add(raw_path)
        for node in entry.get("nodes", []):
            if not isinstance(node, str):
                raise TypeError(f"{entry_id}: pytest nodes must be strings")
            registered_nodes.add(node)
    if seen_categories != CATEGORIES:
        missing_categories = sorted(CATEGORIES - seen_categories)
        raise ValueError(f"registry does not populate categories: {missing_categories}")
    if declared_support_roots != SUPPORT_ROOTS:
        raise ValueError("registered test support roots do not match the active support packages")

    receipt_nodes = _receipt_nodes()
    if registered_nodes != receipt_nodes:
        raise ValueError(
            "receipt node registry drift: "
            f"missing={sorted(receipt_nodes-registered_nodes)}, "
            f"extra={sorted(registered_nodes-receipt_nodes)}"
        )
    collected_nodes = _top_level_test_nodes()
    missing_nodes = sorted(receipt_nodes - collected_nodes)
    if missing_nodes:
        raise ValueError(f"receipt-referenced pytest nodes are missing: {missing_nodes}")
    sibling_imports = _sibling_test_imports()
    if sibling_imports:
        raise ValueError(f"test modules import sibling tests directly: {sibling_imports}")
    audit_counts = _verify_audit(entries)
    print(
        json.dumps(
            {
                **audit_counts,
                "categories": len(seen_categories),
                "entries": len(entries),
                "receipt_nodes": len(receipt_nodes),
                "sibling_test_imports": 0,
                "support_roots": len(declared_support_roots),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
