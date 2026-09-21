from __future__ import annotations

import ast
from pathlib import Path


def _is_integration_marker(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "integration"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _has_module_integration_marker(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets
        ):
            continue
        value = statement.value
        if _is_integration_marker(value):
            return True
        if isinstance(value, (ast.List, ast.Tuple)) and any(
            _is_integration_marker(element) for element in value.elts
        ):
            return True
    return False


def test_every_integration_module_declares_the_integration_marker() -> None:
    integration_root = Path(__file__).resolve().parents[1] / "integration"
    modules = sorted(integration_root.glob("test_*.py"))
    assert modules
    missing = [path.name for path in modules if not _has_module_integration_marker(path)]
    assert missing == []
