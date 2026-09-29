"""Canonical Memory ownership and compatibility regressions; Foundation-owned."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

from milai_lab.harness.source_identity import MEMORY_FACADE_FILES

LAB = Path(__file__).resolve().parents[2]


def test_memory_facades_are_pure_exports_of_the_canonical_objects() -> None:
    for relative in MEMORY_FACADE_FILES:
        path = LAB / relative
        module = "milai_lab.baselines." + path.stem
        old = importlib.import_module(module)
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Expr):
                assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module is not None
                assert node.module.startswith("milai_lab.memory.")
                canonical = importlib.import_module(node.module)
                for alias in node.names:
                    assert getattr(old, alias.asname or alias.name) is getattr(
                        canonical, alias.name
                    )
            else:
                assert isinstance(node, ast.Assign)
                assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                assert node.targets[0].id == "__all__"
                assert isinstance(node.value, ast.List)
                assert all(
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                    for value in node.value.elts
                )


def test_agent_scope_and_read_factory_are_canonical_objects() -> None:
    from milai_lab.baselines import langmem_agent
    from milai_lab.contracts.scope import FoundationScope
    from milai_lab.memory.read_tools import create_memory_read_tool

    assert langmem_agent.FoundationScope is FoundationScope
    assert langmem_agent.create_memory_read_tool is create_memory_read_tool


def test_memory_implementation_has_no_upward_internal_imports() -> None:
    for path in (LAB / "src/milai_lab/memory").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, path
                modules = [node.module or ""]
            for module in modules:
                assert not module.startswith("milai_lab.") or module.startswith(
                    ("milai_lab.contracts.", "milai_lab.memory.")
                ), path
            if isinstance(node, ast.Call):
                assert not (isinstance(node.func, ast.Name) and node.func.id == "__import__"), path
                assert not (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                ), path


def test_memory_import_does_not_load_agent_recipe_or_methods() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        "from milai_lab.memory.mcp import MemoryMCP; "
        "from milai_lab.memory.read_tools import create_memory_read_tool; "
        "from milai_lab.memory.revision_store import ObservedStore, RevisionSidecar; "
        "assert not any(name.startswith(('milai_lab.baselines', 'milai_lab.methods', "
        "'milai_lab.runners', 'milai_lab.application')) for name in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
