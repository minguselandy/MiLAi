"""Canonical ownership, pure compatibility and dependency-free request imports."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from milai_lab.contracts import request
from milai_lab.harness.source_identity import (
    CONTRACT_SOURCE_FILES,
    MEMORY_SOURCE_FILES,
    REQUEST_SOURCE_FILES,
)
from milai_lab.memory import presentation
from milai_lab.methods import request_context

LAB = Path(__file__).resolve().parents[2]


def test_old_request_exports_are_the_canonical_objects() -> None:
    for name in ("MemoryPlacement", "ModelView", "RequestContext"):
        assert getattr(request_context, name) is getattr(request, name)
    for name in ("json_action_calls", "record_material", "render_request", "render_system"):
        assert getattr(request_context, name) is getattr(presentation, name)
    assert request.RequestContext.__module__ == "milai_lab.contracts.request"
    assert presentation.render_request.__module__ == "milai_lab.memory.presentation"


def test_old_request_module_is_a_pure_facade() -> None:
    path = LAB / "src/milai_lab/methods/request_context.py"
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module in {"milai_lab.contracts.request", "milai_lab.memory.presentation"}
        else:
            assert isinstance(node, ast.Assign)
            assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            assert node.targets[0].id == "__all__"
            assert isinstance(node.value, ast.List)
            assert all(isinstance(value, ast.Constant) and isinstance(value.value, str)
                       for value in node.value.elts)


def test_request_imports_need_no_optional_dependencies() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        "import milai_lab.contracts.memory, milai_lab.contracts.operations; "
        "from milai_lab.contracts.request import RequestContext, MemoryPlacement; "
        "from milai_lab.memory.presentation import render_request; "
        "from milai_lab.methods import request_context; "
        "assert request_context.RequestContext is RequestContext; "
        "assert render_request(RequestContext('base', ()), MemoryPlacement.SYSTEM); "
        "assert not any(name.startswith(('langmem', 'langchain', 'langgraph', 'mem0', "
        "'simplemem', 'SimpleMem', 'psycopg', 'transformers', 'tokenizers')) "
        "for name in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-S", "-c", code],  # noqa: S603
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_canonical_request_packages_have_only_lower_imports() -> None:
    paths = [*(LAB / "src/milai_lab/contracts").rglob("*.py"),
             LAB / "src/milai_lab/memory/__init__.py",
             LAB / "src/milai_lab/memory/presentation.py"]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, path
                modules = [node.module or ""]
            for module in modules:
                assert module.split(".")[0] in sys.stdlib_module_names or (
                    module.startswith("milai_lab.contracts.")), path


def test_request_source_registry_covers_every_canonical_module() -> None:
    for package, registered in (("contracts", CONTRACT_SOURCE_FILES),
                                ("memory", MEMORY_SOURCE_FILES)):
        assert set(registered) == {path.relative_to(LAB).as_posix()
                                   for path in (LAB / "src/milai_lab" / package).rglob("*.py")}
        assert set(registered) <= set(REQUEST_SOURCE_FILES)
    assert "src/milai_lab/harness/source_identity.py" in REQUEST_SOURCE_FILES
    assert "src/milai_lab/methods/request_context.py" in REQUEST_SOURCE_FILES
    assert len(REQUEST_SOURCE_FILES) == len(set(REQUEST_SOURCE_FILES))
