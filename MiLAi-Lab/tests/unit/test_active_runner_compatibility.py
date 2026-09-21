from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

from milai_lab.runners import product02_context_gate, product03_openworker_usability

LAB = Path(__file__).resolve().parents[2]
TOOLS = LAB / "tools"


def _tool_module(filename: str, module_name: str) -> ModuleType:
    path = TOOLS / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_thin_wrapper(filename: str) -> None:
    path = TOOLS / filename
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    assert len(source.splitlines()) <= 20
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for node in tree.body
    )


def test_product02_context_gate_keeps_cli_and_import_compatibility(tmp_path: Path) -> None:
    wrapper = _tool_module("run_product02_context_gate.py", "c7_product02_context_gate")

    assert wrapper._parser is product02_context_gate._parser
    assert wrapper._run is product02_context_gate._run
    assert wrapper.main is product02_context_gate.main
    assert product02_context_gate.ROOT == LAB
    args = wrapper._parser().parse_args(
        [
            "--product-root",
            str(tmp_path / "product"),
            "--product-lock",
            str(tmp_path / "product.lock.json"),
            "--env-file",
            str(tmp_path / "runtime.env"),
            "--tokenizer-root",
            str(tmp_path / "tokenizer"),
            "--output",
            str(tmp_path / "result"),
            "--arm",
            "A0",
        ]
    )
    assert args.arm == "A0"
    assert args.case_count == 24
    assert args.budget == 4_096
    _assert_thin_wrapper("run_product02_context_gate.py")


def test_product03_openworker_keeps_cli_and_import_compatibility(tmp_path: Path) -> None:
    wrapper = _tool_module(
        "run_product03_openworker_usability.py", "c7_product03_openworker_usability"
    )

    assert wrapper._parser is product03_openworker_usability._parser
    assert wrapper._run_flows is product03_openworker_usability._run_flows
    assert wrapper._run_load is product03_openworker_usability._run_load
    assert wrapper.main is product03_openworker_usability.main
    args = wrapper._parser().parse_args(
        [
            "run-flows",
            "--container",
            "synthetic-container",
            "--run-label",
            "synthetic-run",
            "--output",
            str(tmp_path / "result.json"),
        ]
    )
    assert args.command == "run-flows"
    assert args.limit == len(product03_openworker_usability._FLOW_SPECS)
    _assert_thin_wrapper("run_product03_openworker_usability.py")
