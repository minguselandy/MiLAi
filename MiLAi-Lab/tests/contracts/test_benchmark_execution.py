"""The common lifecycle owns existing status, error, file and cost behavior."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from benchmark_execution_probe import capture

from milai_lab.harness.benchmark_execution import source_identity
from milai_lab.harness.source_identity import (
    BENCHMARK_EXECUTION_SOURCE_FILES,
    CONTRACT_SOURCE_FILES,
)

LAB = Path(__file__).resolve().parents[2]


def test_common_execution_matches_frozen_complete_contract() -> None:
    fixture = json.loads(
        (LAB / "data/diagnostics/code-architecture-v12/benchmark-execution-golden.json").read_text()
    )
    assert capture(canonical=True) == fixture["contracts"]


def test_source_identity_orders_and_hashes_all_current_canonical_sources() -> None:
    actual = source_identity(LAB)
    expected = [
        *sorted((LAB / "src/milai_lab").rglob("*.py")),
        LAB / "tools/run_unified_benchmarks.py",
        LAB / "pyproject.toml",
    ]
    assert list(actual["source_sha256"]) == [str(path.relative_to(LAB)) for path in expected]
    for path in expected:
        assert (
            actual["source_sha256"][str(path.relative_to(LAB))]
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )
    assert (
        set(BENCHMARK_EXECUTION_SOURCE_FILES + CONTRACT_SOURCE_FILES)
        <= actual["source_sha256"].keys()
    )
    assert list(actual["environment_packages"]) == sorted(actual["environment_packages"])


def test_common_execution_core_import_loads_no_optional_sdk_or_runner() -> None:
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import milai_lab.harness.benchmark_execution
assert not any(name.startswith(('milai_lab.runners', 'milai_lab.providers', 'milai_lab.methods',
    'milai_lab.baselines', 'milai_lab.datasets', 'langmem', 'langchain', 'langgraph', 'mcp',
    'mem0', 'simplemem', 'transformers', 'tokenizers', 'httpx', 'psycopg')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(LAB / "src")], check=True)  # noqa: S603
