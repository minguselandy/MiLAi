"""Core-only negative fixtures for the active DAG and import-path checker."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from milai_lab.boundary import FACADE_MODULES, import_allowed, scan_active_source
from milai_lab.import_graph import scan_import_targets
from milai_lab.tools_boundary import verify_tools_boundary

LAB = Path(__file__).resolve().parents[2]
# Fixed prohibited directions from the reviewed v12 ownership rules. These
# inputs must survive a widening of the production policy; never filter them
# through import_allowed or derive them from the checker's private layer table.
PROHIBITED_TARGETS = {
    "contracts": (
        "memory",
        "application",
        "harness",
        "providers",
        "integrations",
        "methods",
        "datasets",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "memory": (
        "application",
        "harness",
        "providers",
        "integrations",
        "methods",
        "datasets",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "application": (
        "memory",
        "providers",
        "integrations",
        "methods",
        "datasets",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "harness": (
        "memory",
        "application",
        "providers",
        "integrations",
        "methods",
        "datasets",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "providers": (
        "memory",
        "application",
        "integrations",
        "methods",
        "datasets",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "integrations": (
        "application",
        "harness",
        "methods",
        "datasets",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "methods": ("scorers", "benchmarks", "analysis", "runners"),
    "datasets": (
        "memory",
        "application",
        "providers",
        "integrations",
        "methods",
        "scorers",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "scorers": (
        "memory",
        "application",
        "harness",
        "providers",
        "integrations",
        "methods",
        "benchmarks",
        "analysis",
        "runners",
    ),
    "benchmarks": ("application", "methods", "analysis", "runners"),
    "analysis": (
        "memory",
        "application",
        "providers",
        "integrations",
        "scorers",
        "benchmarks",
        "runners",
    ),
}
FORBIDDEN = [
    (source, target) for source, targets in PROHIBITED_TARGETS.items() for target in targets
]
ALLOWED_CONTROLS = (
    ("contracts", "milai_lab.contracts.request"),
    ("memory", "milai_lab.contracts.scope"),
    ("application", "milai_lab.harness.artifact_io"),
    ("harness", "milai_lab.contracts.benchmark"),
    ("providers", "milai_lab.harness.contextual_artifacts"),
    ("integrations", "milai_lab.providers.contextual_vllm"),
    ("methods", "milai_lab.methods.langmem_recipe"),
    ("datasets", "milai_lab.harness.artifact_io"),
    ("scorers", "milai_lab.datasets.contextual"),
    ("benchmarks", "milai_lab.contracts.benchmark"),
    ("analysis", "milai_lab.methods.milai_m1.decision_basis"),
)


def _source(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.mark.parametrize(("source", "target"), FORBIDDEN)
def test_each_forbidden_layer_direction_is_rejected(
    tmp_path: Path,
    source: str,
    target: str,
) -> None:
    _source(
        tmp_path,
        source + "/implementation.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        f"    from milai_lab.{target} import implementation\n",
    )
    assert not import_allowed(
        f"milai_lab.{source}.implementation", f"milai_lab.{target}.implementation"
    )
    assert "LAYER_IMPORT" in {item.code for item in scan_active_source(tmp_path)}


@pytest.mark.parametrize(("source", "target"), ALLOWED_CONTROLS)
def test_reviewed_allowed_direction_controls(tmp_path: Path, source: str, target: str) -> None:
    _source(tmp_path, source + "/implementation.py", f"import {target}\n")
    assert import_allowed(f"milai_lab.{source}.implementation", target)
    assert scan_active_source(tmp_path) == ()


@pytest.mark.parametrize(
    "content",
    [
        "def nested():\n    from ..runners import writer_policy\n",
        "from milai_lab import runners\n",
        "import importlib as loader\nloader.import_module('milai_lab.runners.writer_policy')\n",
        "from importlib import import_module as load\n"
        "load('..runners.writer_policy', __package__)\n",
        "from importlib import import_module as load\n"
        "load('..runners.writer_policy', 'milai_lab.providers')\n",
        "from builtins import __import__ as load\nload('milai_lab.runners.writer_policy')\n",
        "load = __import__\nload('milai_lab', fromlist=['runners'])\n",
        "__import__('runners', {}, {}, ['writer_policy'], 2)\n",
        "import importlib\n"
        "load = importlib.import_module\nload('milai_lab.' + 'runners.writer_policy')\n",
        "import importlib\n"
        "getattr(importlib, 'import_module')('milai_lab.runners.writer_policy')\n",
        "import importlib\nname = input()\nimportlib.import_module(name)\n",
        "import importlib\nname = 'os'\nname = input()\nimportlib.import_module(name)\n",
        "import importlib.util as loader\nloader.spec_from_file_location('safe_name', input())\n",
    ],
)
def test_nested_relative_and_dynamic_import_paths_are_rejected(
    tmp_path: Path, content: str
) -> None:
    _source(tmp_path, "providers/probe.py", content)
    assert {item.code for item in scan_active_source(tmp_path)} & {
        "LAYER_IMPORT",
        "UNRESOLVED_IMPORT",
    }


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("providers/probe.py", "milai_lab.harness.benchmark_execution"),
        ("providers/probe.py", "milai_lab.memory.mcp"),
        ("integrations/probe.py", "milai_lab.harness.contextual_artifacts"),
        ("memory/probe.py", "milai_lab.baselines.langmem_mcp"),
        ("contracts/probe.py", "langmem"),
        ("contracts/probe.py", "mem0"),
        ("contracts/probe.py", "httpx"),
        ("baselines/another_recipe.py", "milai_lab.runners.writer_policy"),
        ("baselines/langmem_instrumentation.py", "milai_lab.methods.langmem_recipe"),
    ],
)
def test_exact_leaf_and_concrete_baseline_roles(tmp_path: Path, source: str, target: str) -> None:
    _source(tmp_path, source, f"import {target}\n")
    assert scan_active_source(tmp_path)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("providers/probe.py", "milai_lab.memory.presentation"),
        ("providers/probe.py", "milai_lab.memory.embeddings"),
        ("integrations/probe.py", "milai_lab.harness.artifact_io"),
        ("methods/probe.py", "milai_lab.baselines.langmem_instrumentation"),
        ("baselines/langmem_benchmark.py", "milai_lab.datasets.contextual"),
        ("contracts/probe.py", "typing_extensions"),
    ],
)
def test_actual_shared_leaf_and_recipe_edges_are_allowed(
    tmp_path: Path,
    source: str,
    target: str,
) -> None:
    _source(tmp_path, source, f"import {target}\n")
    assert scan_active_source(tmp_path) == ()


@pytest.mark.parametrize(
    "relative",
    [
        "harness/artifact_io.py",
        "memory/presentation.py",
        "memory/embeddings.py",
        "analysis/trace_accounting.py",
    ],
)
@pytest.mark.parametrize(
    "target", ["langmem", "milai_lab.methods.langmem_recipe", "milai_lab.memory.mcp"]
)
def test_approved_leaf_closure_cannot_grow_policy_or_sdk_dependencies(
    tmp_path: Path,
    relative: str,
    target: str,
) -> None:
    _source(tmp_path, relative, f"import {target}\n")
    assert any(item.code.startswith("SHARED_LEAF") for item in scan_active_source(tmp_path))


@pytest.mark.parametrize("module", sorted(FACADE_MODULES))
@pytest.mark.parametrize(
    "logic",
    [
        "def hidden():\n    return None\n",
        "alias = object()\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    alias = object()\n",
        "if True:\n    from milai_lab.contracts import request\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    def hidden():\n        pass\n",
        "__all__ = build_exports()\n",
    ],
)
def test_complete_facades_reject_executable_logic(tmp_path: Path, module: str, logic: str) -> None:
    _source(tmp_path, module.removeprefix("milai_lab.").replace(".", "/") + ".py", logic)
    assert "FACADE_LOGIC" in {item.code for item in scan_active_source(tmp_path)}


def test_facade_typing_guard_only_allows_imports(tmp_path: Path) -> None:
    _source(
        tmp_path,
        "methods/request_context.py",
        '"""Compatibility."""\nimport typing as t\nif t.TYPE_CHECKING:\n'
        "    from milai_lab.contracts.request import RequestContext as RequestContext\n"
        '__all__ = ["RequestContext"]\n',
    )
    assert scan_active_source(tmp_path) == ()


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        (
            "integrations/memory/simplemem.py",
            'package_dir = Path(source) / "simplemem"',
            'package_dir = Path(source) / "milai_lab"',
        ),
        (
            "integrations/memory/simplemem.py",
            '"simplemem",\n                package_dir',
            '"milai_lab.methods",\n                package_dir',
        ),
        ("datasets/merit.py", 'package_dir = root / "merit"', 'package_dir = root / "milai_lab"'),
        ("datasets/merit.py", 'f"_milai_pinned_merit_', 'f"milai_lab.methods.'),
    ],
)
def test_existing_pinned_sdk_loader_origin_and_namespace_are_enforced(
    tmp_path: Path,
    relative: str,
    old: str,
    new: str,
) -> None:
    original = (LAB / "src/milai_lab" / relative).read_text()
    assert old in original
    _source(tmp_path, relative, original.replace(old, new))
    assert "UNRESOLVED_IMPORT" in {item.code for item in scan_active_source(tmp_path)}


@pytest.mark.parametrize(
    "content",
    [
        "import importlib as i\ni.import_module('milai_mcp.server')\n",
        "from importlib import import_module as load\nload('milai_mcp.' + 'server')\n",
        "from builtins import __import__ as load\nload('milai_mcp.server')\n",
        "import importlib\nimportlib.import_module(input())\n",
    ],
)
def test_tools_use_the_same_alias_and_unknown_path_scanner(tmp_path: Path, content: str) -> None:
    tools = tmp_path / "tools"
    _source(tools, "probe.py", content)
    findings, _ = verify_tools_boundary(tools, LAB / "docs/tools-product-dependencies.json")
    assert {item.code for item in findings} & {
        "NEW_PRIVATE_PRODUCT_IMPORT",
        "UNRESOLVED_TOOL_IMPORT",
    }


def test_import_reader_preserves_complete_finite_external_sdk_targets() -> None:
    targets = scan_import_targets(
        ast.parse(
            "from importlib import import_module as load\n"
            "modules=[load('sdk.' + name) for name in ('store','search')]\n"
        ),
        "milai_lab.integrations.probe",
    )
    assert {item.module for item in targets if item.kind == "dynamic"} == {
        "sdk.store",
        "sdk.search",
    }
