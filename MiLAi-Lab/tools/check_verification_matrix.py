"""Check that the simple Lab CI file groups cover every active Python source."""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
MATRIX = LAB / "configs/lab-verification-matrix.json"
ROOT = LAB.parent


def _workflow_job(path: Path, name: str) -> str:
    contents = path.read_text()
    match = re.search(rf"(?m)^  {re.escape(name)}:\s*$", contents)
    if match is None:
        raise ValueError(f"LAB_VERIFICATION_JOB_MISSING:{path.name}:{name}")
    end = re.search(r"(?m)^  [a-z][a-z0-9-]*:\s*$", contents[match.end():])
    return contents[match.end():match.end() + end.start() if end else len(contents)]


def _require(job: str, value: str, label: str) -> None:
    if value not in job:
        raise ValueError(f"LAB_VERIFICATION_WORKFLOW_DRIFT:{label}:{value}")


def _pytest_targets(job: str) -> set[str]:
    commands = re.findall(r"(?m)^\s*uv run --no-sync pytest[^\n]*", job)
    return set(re.findall(r"tests/(?:unit|integration)/test_[\w]+\.py",
                          "\n".join(commands)))


def _marked_local_artifacts() -> set[str]:
    nodes: set[str] = set()
    for path in (LAB / "tests/unit").glob("test_*.py"):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(isinstance(decorator, ast.Attribute)
                   and decorator.attr == "local_artifacts"
                   and isinstance(decorator.value, ast.Attribute)
                   and decorator.value.attr == "mark"
                   for decorator in node.decorator_list):
                nodes.add(f"{path.relative_to(LAB)}::{node.name}")
    return nodes


def _check_workflows(matrix: dict[str, Any]) -> None:
    for workflow, core_name, foundation_name, external_name in (
        ("fast.yml", "lab-fast", "lab-langmem-foundation-fast", "lab-external-fast"),
        ("ci.yml", "lab", "lab-langmem-foundation", "lab-external"),
    ):
        path = ROOT / ".github/workflows" / workflow
        core = _workflow_job(path, core_name)
        foundation = _workflow_job(path, foundation_name)
        external = _workflow_job(path, external_name)
        _require(core, "uv run --no-sync python tools/check_verification_matrix.py", workflow)
        _require(core, "uv run --no-sync ruff check src tests tools", workflow)
        _require(core, "uv run --no-sync mypy " + " ".join(matrix["core_mypy_paths"]),
                 workflow)
        _require(core, "-m 'not regression and not local_artifacts'", workflow)
        _require(core, "uv run --no-sync mypy " + matrix["core_optional_protocol"], workflow)
        _require(core, "uv run --no-sync pytest -q " + matrix["core_optional_protocol_test"],
                 workflow)
        for item in matrix["core_pytest_ignores"]:
            _require(core, "--ignore=" + item, workflow)
        actual_ignores = set(re.findall(r"--ignore=(tests/[^\s\\]+)", core))
        if actual_ignores != set(matrix["core_pytest_ignores"]):
            raise ValueError(f"LAB_VERIFICATION_EXTRA_OR_MISSING_IGNORE:{workflow}")
        _require(foundation, "uv run --no-sync mypy " + matrix["foundation_discovery"],
                 workflow)
        _require(foundation, "uv run --no-sync mypy " + " ".join(
            matrix["foundation_explicit_globs"]), workflow)
        if not set(matrix["foundation_tests"]) <= _pytest_targets(foundation):
            raise ValueError(f"LAB_VERIFICATION_FOUNDATION_PYTEST_DRIFT:{workflow}")
        _require(external, "uv run --no-sync mypy " + " ".join(
            matrix["external_mypy_paths"]), workflow)
        _require(external, "tools/prepare_external_memory_v26_assets.py --prepare", workflow)
        _require(external, "en_core_web_sm-3.8.0-py3-none-any.whl", workflow)
        if set(matrix["external_tests"]) != _pytest_targets(external):
            raise ValueError(f"LAB_VERIFICATION_EXTERNAL_PYTEST_DRIFT:{workflow}")
    gate = _workflow_job(ROOT / ".github/workflows/fast.yml", "fast-gate")
    _require(gate, "LAB_EXTERNAL: ${{ needs.lab-external-fast.result }}", "fast-gate")
    _require(gate, 'for result in "$LAB" "$LAB_LANGMEM" "$LAB_EXTERNAL"', "fast-gate")
    _require(gate, 'if [[ "$result" != \'success\' ]]', "fast-gate")


def main() -> None:
    matrix = json.loads(MATRIX.read_text())
    if matrix.get("kind") != "MILAI_LAB_VERIFICATION_MATRIX_V1":
        raise ValueError("LAB_VERIFICATION_MATRIX_KIND_CHANGED")
    source_root = LAB / matrix["source_root"]
    sources = {path.resolve() for path in source_root.rglob("*.py")}
    config = tomllib.loads((LAB / "pyproject.toml").read_text())
    excluded = {
        path for path in sources
        if re.search(config["tool"]["mypy"]["exclude"],
                     str(path.relative_to(source_root)))
    }
    explicit: set[Path] = set()
    for pattern in matrix["foundation_explicit_globs"]:
        matches = {path.resolve() for path in LAB.glob(pattern)}
        if not matches:
            raise ValueError("LAB_VERIFICATION_EMPTY_GLOB:" + pattern)
        explicit.update(matches)
    if sources != (sources - excluded) | explicit:
        missing = sorted(str(path.relative_to(LAB)) for path in excluded - explicit)
        raise ValueError("LAB_VERIFICATION_UNCHECKED_SOURCE:" + repr(missing))
    if set(matrix["core_pytest_ignores"]) != (
        set(matrix["foundation_tests"]) | set(matrix["external_tests"])
    ):
        raise ValueError("LAB_VERIFICATION_OPTIONAL_TEST_OWNER_MISMATCH")
    if _marked_local_artifacts() != set(matrix["local_artifact_tests"]):
        raise ValueError("LAB_VERIFICATION_LOCAL_ARTIFACT_MARKER_MISMATCH")
    if not matrix["local_artifact_owner"]:
        raise ValueError("LAB_VERIFICATION_LOCAL_ARTIFACT_OWNER_MISSING")
    integration = {str(path.relative_to(LAB))
                   for path in (LAB / "tests/integration").rglob("*.py")}
    if integration != set(matrix["integration_tests"]):
        raise ValueError("LAB_VERIFICATION_INTEGRATION_TEST_OWNER_MISMATCH")
    external_test = (LAB / matrix["external_tests"][0]).read_text()
    if "pytest.skip(" in external_test or "pytest.importorskip(" in external_test:
        raise ValueError("LAB_VERIFICATION_EXTERNAL_TEST_CAN_SKIP")
    for name in ("core_mypy_paths", "external_mypy_paths", "foundation_tests",
                 "external_tests", "core_pytest_ignores"):
        for item in matrix[name]:
            if not (LAB / item).exists():
                raise ValueError("LAB_VERIFICATION_PATH_MISSING:" + item)
    core_sources: set[Path] = set()
    for item in matrix["core_mypy_paths"]:
        path = (LAB / item).resolve()
        core_sources.update(path.rglob("*.py") if path.is_dir() else [path])
    external_sources = {(LAB / item).resolve()
                        for item in matrix["external_mypy_paths"]}
    if not core_sources <= sources or not external_sources <= sources:
        raise ValueError("LAB_VERIFICATION_SOURCE_OUTSIDE_PACKAGE")
    protocol = (LAB / matrix["core_optional_protocol"]).resolve()
    protocol_test = LAB / matrix["core_optional_protocol_test"]
    if protocol.exists() != protocol_test.exists():
        raise ValueError("LAB_VERIFICATION_PROTOCOL_TEST_MISMATCH")
    _check_workflows(matrix)
    print(json.dumps({"active_sources": len(sources),
                      "foundation_discovery": len(sources - excluded),
                      "foundation_explicit": len(explicit),
                      "excluded_recovered": len(excluded & explicit),
                      "core_direct": len(core_sources),
                      "external_direct": len(external_sources),
                      "optional_tests_owned": len(matrix["core_pytest_ignores"]),
                      "private_asset_tests": len(matrix["local_artifact_tests"]),
                      "integration_tests": len(integration),
                      "protocol_contract_present": protocol.exists()}, sort_keys=True))


if __name__ == "__main__":
    main()
