"""Foundation owns compatibility with the two benchmark runner imports."""

from __future__ import annotations

import ast
from pathlib import Path

from milai_lab.harness import benchmark_execution
from milai_lab.harness.source_identity import BENCHMARK_EXECUTION_SOURCE_FILES
from milai_lab.runners import memsyco_native, merit_native

LAB = Path(__file__).resolve().parents[2]
SHARED = {
    "prepare_manifest",
    "start_job",
    "finish_job",
    "source_identity",
    "trace_costs",
    "sha",
    "validate_config",
}


def test_old_merit_names_and_memsyco_imports_are_canonical_same_objects() -> None:
    for symbol in SHARED:
        assert getattr(merit_native, symbol) is getattr(benchmark_execution, symbol)
        assert getattr(memsyco_native, symbol) is getattr(benchmark_execution, symbol)
    tree = ast.parse((LAB / "src/milai_lab/runners/merit_native.py").read_text())
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in SHARED
        for node in tree.body
    )
    tree = ast.parse((LAB / "src/milai_lab/runners/memsyco_native.py").read_text())
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "milai_lab.runners.merit_native"
        for node in ast.walk(tree)
    )


def test_common_owner_depends_only_on_contracts_and_the_stdlib_io_leaf() -> None:
    assert BENCHMARK_EXECUTION_SOURCE_FILES == ("src/milai_lab/harness/benchmark_execution.py",)
    tree = ast.parse((LAB / BENCHMARK_EXECUTION_SOURCE_FILES[0]).read_text())
    allowed = {"milai_lab.contracts.benchmark", "milai_lab.harness.artifact_io"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("milai_lab"):
            assert node.module in allowed
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith("milai_lab") for alias in node.names)
