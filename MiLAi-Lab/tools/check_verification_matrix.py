"""Check that the simple Lab CI file groups cover every active Python source."""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from milai_lab.application import APPLICATION_SOURCE_FILES
from milai_lab.harness.source_identity import CANONICAL_PACKAGE_SOURCE_FILES

LAB = Path(__file__).resolve().parents[1]
MATRIX = LAB / "configs/lab-verification-matrix.json"
ROOT = LAB.parent
_STRICT_PATTERNS = frozenset(
    {
        "src/milai_lab/contracts/*.py",
        "src/milai_lab/application/*.py",
        "src/milai_lab/application/world.py",
        "src/milai_lab/memory/*.py",
        "src/milai_lab/integrations/**/*.py",
        "src/milai_lab/integrations/memory/mem0.py",
        "src/milai_lab/integrations/memory/simplemem.py",
        "src/milai_lab/harness/benchmark_execution.py",
        "src/milai_lab/harness/artifact_io.py",
        "src/milai_lab/providers/request_pipeline.py",
    }
)


def verify_source_ownership(
    matrix: dict[str, Any], lab: Path, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check declared owners against actual sources and actual strict mypy commands."""
    if config["tool"]["mypy"].get("strict") is not True:
        raise ValueError("LAB_VERIFICATION_STRICT_DISABLED")
    source_root = lab / matrix["source_root"]
    sources = {str(path.relative_to(lab)) for path in source_root.rglob("*.py")}
    checked: dict[str, set[str]] = {"Core": set(), "Foundation": set(), "External": set()}
    for group, key in (("Core", "core_mypy_paths"), ("External", "external_mypy_paths")):
        for item in matrix[key]:
            path = lab / item
            checked[group].update(
                str(part.relative_to(lab))
                for part in (path.rglob("*.py") if path.is_dir() else [path])
            )
    checked["Core"].add(matrix["core_optional_protocol"])
    excluded = config["tool"]["mypy"]["exclude"]
    checked["Foundation"] = {
        item
        for item in sources
        if not re.search(excluded, str(Path(item).relative_to(matrix["source_root"])))
    }
    for pattern in matrix["foundation_explicit_globs"]:
        checked["Foundation"].update(str(path.relative_to(lab)) for path in lab.glob(pattern))
    rows = matrix.get("source_owners", [])
    coverage: list[dict[str, Any]] = []
    for item in sorted(sources):
        candidates = [
            row
            for row in rows
            if item == row["prefix"]
            or (row["prefix"].endswith("/") and item.startswith(row["prefix"]))
        ]
        if not candidates:
            raise ValueError("LAB_VERIFICATION_OWNER_MISSING:" + item)
        longest = max(len(row["prefix"]) for row in candidates)
        candidates = [row for row in candidates if len(row["prefix"]) == longest]
        if len(candidates) != 1 or not candidates[0].get("owner"):
            raise ValueError("LAB_VERIFICATION_OWNER_AMBIGUOUS:" + item)
        row = candidates[0]
        parts = Path(item).parts
        owner = (
            parts[2]
            if len(parts) > 3
            else (
                "architecture"
                if Path(item).stem in {"boundary", "tools_boundary", "import_graph"}
                else "entrypoints"
            )
        )
        if row["owner"] != owner:
            raise ValueError("LAB_VERIFICATION_OWNER_CHANGED:" + item)
        groups = row.get("ci_groups", [])
        if not groups or any(
            group not in checked or item not in checked[group] for group in groups
        ):
            raise ValueError("LAB_VERIFICATION_GROUP_UNCHECKED:" + item)
        coverage.append({"path": item, "owner": row["owner"], "ci_groups": groups})
    for row in rows:
        if not any(
            item == row["prefix"]
            or (row["prefix"].endswith("/") and item.startswith(row["prefix"]))
            for item in sources
        ):
            raise ValueError("LAB_VERIFICATION_OWNER_STALE:" + row["prefix"])
    if {row["pattern"] for row in matrix.get("strict_required", [])} != _STRICT_PATTERNS:
        raise ValueError("LAB_VERIFICATION_STRICT_REQUIREMENT_MISSING")
    for row in matrix["strict_required"]:
        required = {str(path.relative_to(lab)) for path in lab.glob(row["pattern"])}
        if not required or not row.get("ci_groups"):
            raise ValueError("LAB_VERIFICATION_STRICT_REQUIREMENT_EMPTY:" + row["pattern"])
        for group in row["ci_groups"]:
            if group not in checked or not required <= checked[group]:
                raise ValueError("LAB_VERIFICATION_STRICT_REQUIREMENT_UNCHECKED:" + row["pattern"])
    packages = {**CANONICAL_PACKAGE_SOURCE_FILES, "application": APPLICATION_SOURCE_FILES}
    if set(matrix.get("canonical_packages", [])) != set(packages):
        raise ValueError("LAB_VERIFICATION_CANONICAL_PACKAGE_OWNER_MISSING")
    for package, registered in packages.items():
        actual = {item for item in sources if item.startswith("src/milai_lab/" + package + "/")}
        if actual != set(registered) or len(registered) != len(set(registered)):
            raise ValueError("LAB_VERIFICATION_SOURCE_REGISTRATION_DRIFT:" + package)
    return coverage


def _workflow_job(path: Path, name: str) -> str:
    contents = path.read_text()
    match = re.search(rf"(?m)^  {re.escape(name)}:\s*$", contents)
    if match is None:
        raise ValueError(f"LAB_VERIFICATION_JOB_MISSING:{path.name}:{name}")
    end = re.search(r"(?m)^  [a-z][a-z0-9-]*:\s*$", contents[match.end() :])
    return contents[match.end() : match.end() + end.start() if end else len(contents)]


def _require(job: str, value: str, label: str) -> None:
    if value not in job:
        raise ValueError(f"LAB_VERIFICATION_WORKFLOW_DRIFT:{label}:{value}")


def _pytest_targets(job: str) -> set[str]:
    commands = re.findall(r"(?m)^\s*uv run --no-sync pytest[^\n]*", job)
    return set(
        re.findall(
            r"tests/(?:unit|integration|integrations|contracts|architecture|application|memory)/"
            r"test_[\w]+\.py",
            "\n".join(commands),
        )
    )


def _pytest_commands(job: str) -> list[str]:
    return re.findall(r"(?m)^\s*uv run --no-sync pytest[^\n]*", job)


def _marked_local_artifacts() -> tuple[set[str], int]:
    nodes: set[str] = set()
    collected = 0
    for path in (LAB / "tests").rglob("test_*.py"):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "local_artifacts"
                and isinstance(decorator.value, ast.Attribute)
                and decorator.value.attr == "mark"
                for decorator in node.decorator_list
            ):
                nodes.add(f"{path.relative_to(LAB)}::{node.name}")
                cases = 1
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "parametrize"
                    ):
                        values = decorator.args[1]
                        if not isinstance(values, (ast.List, ast.Tuple)):
                            raise ValueError("LAB_VERIFICATION_DYNAMIC_LOCAL_ASSET_CASES")
                        cases *= len(values.elts)
                collected += cases
    return nodes, collected


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
        _require(core, "uv run --no-sync mypy " + " ".join(matrix["core_mypy_paths"]), workflow)
        _require(core, "-m 'not regression and not local_artifacts'", workflow)
        _require(core, "uv run --no-sync mypy " + matrix["core_optional_protocol"], workflow)
        _require(
            core, "uv run --no-sync pytest -q " + matrix["core_optional_protocol_test"], workflow
        )
        for item in matrix["core_pytest_ignores"]:
            _require(core, "--ignore=" + item, workflow)
        actual_ignores = set(re.findall(r"--ignore=(tests/[^\s\\]+)", core))
        if actual_ignores != set(matrix["core_pytest_ignores"]):
            raise ValueError(f"LAB_VERIFICATION_EXTRA_OR_MISSING_IGNORE:{workflow}")
        _require(foundation, "uv run --no-sync mypy " + matrix["foundation_discovery"], workflow)
        _require(
            foundation,
            "uv run --no-sync mypy " + " ".join(matrix["foundation_explicit_globs"]),
            workflow,
        )
        if not set(matrix["foundation_tests"]) <= _pytest_targets(foundation):
            raise ValueError(f"LAB_VERIFICATION_FOUNDATION_PYTEST_DRIFT:{workflow}")
        freshness_commands = [
            command
            for command in _pytest_commands(foundation)
            if "tests/unit/test_freshness_projection.py" in command
        ]
        if (
            len(freshness_commands) != 1
            or "-m 'not local_artifacts'" not in (freshness_commands[0])
        ):
            raise ValueError(f"LAB_VERIFICATION_FOUNDATION_LOCAL_ASSET_GATE:{workflow}")
        _require(
            external, "uv run --no-sync mypy " + " ".join(matrix["external_mypy_paths"]), workflow
        )
        _require(external, "tools/prepare_external_memory_v26_assets.py --prepare", workflow)
        _require(external, "en_core_web_sm-3.8.0-py3-none-any.whl", workflow)
        _require(external, matrix["simplemem_source_prepare"], workflow)
        _require(
            external,
            "uv pip install --python .venv/bin/python -r " + matrix["simplemem_dependencies"],
            workflow,
        )
        if set(matrix["external_tests"]) != _pytest_targets(external):
            raise ValueError(f"LAB_VERIFICATION_EXTERNAL_PYTEST_DRIFT:{workflow}")
    gate = _workflow_job(ROOT / ".github/workflows/fast.yml", "fast-gate")
    _require(gate, "LAB_EXTERNAL: ${{ needs.lab-external-fast.result }}", "fast-gate")
    _require(gate, 'for result in "$LAB" "$LAB_LANGMEM" "$LAB_EXTERNAL"', "fast-gate")
    _require(gate, "if [[ \"$result\" != 'success' ]]", "fast-gate")


def main() -> None:
    matrix = json.loads(MATRIX.read_text())
    if matrix.get("kind") != "MILAI_LAB_VERIFICATION_MATRIX_V1":
        raise ValueError("LAB_VERIFICATION_MATRIX_KIND_CHANGED")
    source_root = LAB / matrix["source_root"]
    sources = {path.resolve() for path in source_root.rglob("*.py")}
    config = tomllib.loads((LAB / "pyproject.toml").read_text())
    ownership = verify_source_ownership(matrix, LAB, config)
    excluded = {
        path
        for path in sources
        if re.search(config["tool"]["mypy"]["exclude"], str(path.relative_to(source_root)))
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
    marked, collected = _marked_local_artifacts()
    if marked != set(matrix["local_artifact_tests"]):
        raise ValueError("LAB_VERIFICATION_LOCAL_ARTIFACT_MARKER_MISMATCH")
    if collected != matrix["local_artifact_collected_nodes"]:
        raise ValueError("LAB_VERIFICATION_LOCAL_ARTIFACT_NODE_COUNT_MISMATCH")
    if not matrix["local_artifact_owner"]:
        raise ValueError("LAB_VERIFICATION_LOCAL_ARTIFACT_OWNER_MISSING")
    integration = {str(path.relative_to(LAB)) for path in (LAB / "tests/integration").rglob("*.py")}
    if integration != set(matrix["integration_tests"]):
        raise ValueError("LAB_VERIFICATION_INTEGRATION_TEST_OWNER_MISMATCH")
    for target in matrix["external_tests"]:
        external_test = (LAB / target).read_text()
        if "pytest.skip(" in external_test or "pytest.importorskip(" in external_test:
            raise ValueError("LAB_VERIFICATION_EXTERNAL_TEST_CAN_SKIP:" + target)
    for name in (
        "core_mypy_paths",
        "external_mypy_paths",
        "foundation_tests",
        "external_tests",
        "core_pytest_ignores",
    ):
        for item in matrix[name]:
            if not (LAB / item).exists():
                raise ValueError("LAB_VERIFICATION_PATH_MISSING:" + item)
    core_sources: set[Path] = set()
    for item in matrix["core_mypy_paths"]:
        path = (LAB / item).resolve()
        core_sources.update(path.rglob("*.py") if path.is_dir() else [path])
    external_sources = {(LAB / item).resolve() for item in matrix["external_mypy_paths"]}
    if not core_sources <= sources or not external_sources <= sources:
        raise ValueError("LAB_VERIFICATION_SOURCE_OUTSIDE_PACKAGE")
    protocol = (LAB / matrix["core_optional_protocol"]).resolve()
    protocol_test = LAB / matrix["core_optional_protocol_test"]
    if protocol.exists() != protocol_test.exists():
        raise ValueError("LAB_VERIFICATION_PROTOCOL_TEST_MISMATCH")
    _check_workflows(matrix)
    print(
        json.dumps(
            {
                "active_sources": len(sources),
                "foundation_discovery": len(sources - excluded),
                "foundation_explicit": len(explicit),
                "excluded_recovered": len(excluded & explicit),
                "core_direct": len(core_sources),
                "external_direct": len(external_sources),
                "optional_tests_owned": len(matrix["core_pytest_ignores"]),
                "private_asset_tests": collected,
                "integration_tests": len(integration),
                "protocol_contract_present": protocol.exists(),
            },
            sort_keys=True,
        )
    )
    print(
        json.dumps(
            {
                "owned_sources": len(ownership),
                "strict_required_groups": len(matrix["strict_required"]),
                "canonical_packages": matrix["canonical_packages"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
