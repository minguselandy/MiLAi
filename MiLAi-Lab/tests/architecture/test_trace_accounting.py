"""Core accounting uses the frozen real trace formulas and error boundaries."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from writer_contract_probe import accounting_contract

from milai_lab.analysis.trace_accounting import _accounting

LAB = Path(__file__).resolve().parents[2]
GOLDEN = LAB / "data/diagnostics/code-architecture-v12"


def test_trace_accounting_matches_whole_frozen_contract(tmp_path: Path) -> None:
    expected = json.loads((GOLDEN / "writer-accounting-golden.json").read_text())["contracts"][
        "trace_accounting"
    ]
    actual = json.dumps(accounting_contract(_accounting, str(tmp_path)), ensure_ascii=False)
    assert json.loads(actual.replace(str(tmp_path), "<TMP>")) == expected


def test_trace_accounting_import_needs_only_standard_library() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(LAB / 'src')!r}); "
        "from milai_lab.analysis.trace_accounting import _accounting; "
        "assert callable(_accounting); "
        "assert not any(name.startswith(('langmem', 'langchain', 'langgraph', 'httpx', "
        "'milai_lab.runners', 'milai_lab.methods', 'milai_lab.providers', "
        "'milai_lab.application', 'milai_lab.integrations')) for name in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 -- fixed local import probe
        [sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stdout + result.stderr
    path = LAB / "src/milai_lab/analysis/trace_accounting.py"
    imports = [
        node.module
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("milai_lab")
    ]
    assert imports == ["milai_lab.harness.artifact_io"]
