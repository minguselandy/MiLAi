from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from milai_lab.import_graph import scan_import_targets

_SCHEMA = "milai.lab.tools-product-dependencies.v1"
_CLASSIFICATIONS = frozenset({"PUBLIC", "TESTKIT", "LEGACY_PRIVATE"})


@dataclass(frozen=True, slots=True)
class ToolProductDependency:
    path: str
    module: str
    classification: str
    lines: tuple[int, ...]

    def record(self) -> dict[str, object]:
        return {
            "path": self.path,
            "module": self.module,
            "classification": self.classification,
            "lines": list(self.lines),
        }


@dataclass(frozen=True, slots=True)
class ToolsBoundaryFinding:
    path: str
    line: int
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ToolsBoundaryPolicy:
    product_import_roots: frozenset[str]
    public_modules: frozenset[str]
    testkit_prefixes: tuple[str, ...]
    grandfathered_private: frozenset[tuple[str, str]]
    dependencies: tuple[ToolProductDependency, ...]


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return value


def _object_list(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} must be a list of objects")
    return value


def _required_string(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _dependency(row: Mapping[str, object]) -> ToolProductDependency:
    classification = _required_string(row, "classification")
    if classification not in _CLASSIFICATIONS:
        raise ValueError(f"unsupported dependency classification: {classification}")
    raw_lines = row.get("lines")
    if (
        not isinstance(raw_lines, list)
        or not raw_lines
        or any(
            not isinstance(line, int) or isinstance(line, bool) or line < 1 for line in raw_lines
        )
    ):
        raise ValueError("dependency lines must be a non-empty list of positive integers")
    lines = tuple(sorted(set(raw_lines)))
    if list(lines) != raw_lines:
        raise ValueError("dependency lines must be sorted and unique")
    return ToolProductDependency(
        path=_required_string(row, "path"),
        module=_required_string(row, "module"),
        classification=classification,
        lines=lines,
    )


def load_tools_boundary_policy(path: Path) -> ToolsBoundaryPolicy:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema") != _SCHEMA:
        raise ValueError(f"inventory schema must be {_SCHEMA}")
    roots = frozenset(_string_list(raw.get("product_import_roots"), "product_import_roots"))
    public_modules = frozenset(_string_list(raw.get("public_modules"), "public_modules"))
    testkit_prefixes = tuple(_string_list(raw.get("testkit_prefixes"), "testkit_prefixes"))
    if not roots or any("." in root for root in roots):
        raise ValueError("product_import_roots must contain non-empty import roots")
    if any(module.split(".", maxsplit=1)[0] not in roots for module in public_modules):
        raise ValueError("public_modules contains a module outside Product roots")
    if any(prefix.split(".", maxsplit=1)[0] not in roots for prefix in testkit_prefixes):
        raise ValueError("testkit_prefixes contains a prefix outside Product roots")

    grandfathered_rows = _object_list(
        raw.get("grandfathered_private_imports"), "grandfathered_private_imports"
    )
    grandfathered_private = frozenset(
        (_required_string(row, "path"), _required_string(row, "module"))
        for row in grandfathered_rows
    )
    if len(grandfathered_private) != len(grandfathered_rows):
        raise ValueError("grandfathered_private_imports contains duplicates")
    for row in grandfathered_rows:
        _required_string(row, "reason")

    dependencies = tuple(
        sorted(
            (_dependency(row) for row in _object_list(raw.get("dependencies"), "dependencies")),
            key=lambda dependency: (dependency.path, dependency.module),
        )
    )
    identities = [(dependency.path, dependency.module) for dependency in dependencies]
    if len(identities) != len(set(identities)):
        raise ValueError("dependencies contains duplicate path/module identities")
    declared_private = {
        (dependency.path, dependency.module)
        for dependency in dependencies
        if dependency.classification == "LEGACY_PRIVATE"
    }
    if declared_private != grandfathered_private:
        raise ValueError(
            "LEGACY_PRIVATE dependencies must exactly match grandfathered_private_imports"
        )
    return ToolsBoundaryPolicy(
        product_import_roots=roots,
        public_modules=public_modules,
        testkit_prefixes=testkit_prefixes,
        grandfathered_private=grandfathered_private,
        dependencies=dependencies,
    )


def scan_tool_product_imports(
    root: Path, product_import_roots: frozenset[str]
) -> dict[tuple[str, str], tuple[int, ...]]:
    observed: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        display = f"{root.name}/{path.relative_to(root).as_posix()}"
        for target in scan_import_targets(tree, "tools." + path.stem):
            module = target.module
            if module and module.split(".", maxsplit=1)[0] in product_import_roots:
                observed[(display, module)].add(target.line)
    return {identity: tuple(sorted(lines)) for identity, lines in sorted(observed.items())}


def _classification(policy: ToolsBoundaryPolicy, path: str, module: str) -> str | None:
    if module in policy.public_modules:
        return "PUBLIC"
    if any(
        module == prefix or module.startswith(prefix + ".") for prefix in policy.testkit_prefixes
    ):
        return "TESTKIT"
    if (path, module) in policy.grandfathered_private:
        return "LEGACY_PRIVATE"
    return None


def _reviewed_tool_loader(path: Path, tree: ast.Module, expression: str) -> bool:
    """Preserve the existing offline frozen-checker and native-source audit loaders."""
    checker_names = {
        "audit_v0218_chain.py": ("v0218_frozen_checker", "checker_spec"),
        "audit_v0218_discovery.py": ("discovery_frozen_checker", "loader"),
        "audit_v0218_e2.py": ("discovery_frozen_checker", "loader"),
        "audit_v0218_baseline.py": ("baseline_frozen_checker", "loader"),
    }
    if path.name in checker_names:
        namespace, spec = checker_names[path.name]
        create = (
            f"importlib.util.spec_from_file_location('{namespace}', "
            "root / 'executed-source/v0218_checker.py')"
        )
        calls = {ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        return create in calls and expression in {
            create,
            f"importlib.util.module_from_spec({spec})",
            f"{spec}.loader.exec_module(checker)",
        }
    if path.name == "v02_readable_smoke_worker.py":
        create = "importlib.machinery.SourceFileLoader('reader', '/usr/local/bin/milai-read')"
        calls = {ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        return create in calls and expression in {
            create,
            "importlib.util.module_from_spec(spec)",
            "loader.exec_module(reader)",
        }
    if path.name == "check_v0217_admission.py":
        code = ast.unparse(tree)
        required = {
            "reward_path = root / 'supersede/src/supersede/reward.py'",
            "rollout_path = root / 'supersede/src/supersede/rollout.py'",
        }
        reviewed = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "reviewed_module"
        ]
        return (
            all(item in code for item in required)
            and set(reviewed)
            == {
                "reviewed_module(reward_path, 'v0217_native_reward')",
                "reviewed_module(rollout_path, 'v0217_native_rollout')",
            }
            and expression
            in {
                "importlib.util.spec_from_file_location(name, path)",
                "importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(module)",
            }
        )
    return False


def verify_tools_boundary(
    root: Path, inventory_path: Path
) -> tuple[tuple[ToolsBoundaryFinding, ...], tuple[ToolProductDependency, ...]]:
    policy = load_tools_boundary_policy(inventory_path)
    imports = scan_tool_product_imports(root, policy.product_import_roots)
    findings: list[ToolsBoundaryFinding] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for target in scan_import_targets(tree, "tools." + path.stem):
            if (
                target.module is None
                or "*" in target.module
                or target.kind in {"file_load", "loader_execution"}
            ) and not _reviewed_tool_loader(path, tree, target.expression):
                findings.append(
                    ToolsBoundaryFinding(
                        f"{root.name}/{path.relative_to(root).as_posix()}",
                        target.line,
                        "UNRESOLVED_TOOL_IMPORT",
                        target.expression or "relative import",
                    )
                )
    dependencies: list[ToolProductDependency] = []
    for (import_path, module), lines in imports.items():
        classification = _classification(policy, import_path, module)
        if classification is None:
            findings.append(
                ToolsBoundaryFinding(
                    import_path,
                    lines[0],
                    "NEW_PRIVATE_PRODUCT_IMPORT",
                    f"{module} is not a public/testkit module or an exact grandfathered dependency",
                )
            )
            continue
        dependencies.append(ToolProductDependency(import_path, module, classification, lines))

    actual = tuple(sorted(dependencies, key=lambda item: (item.path, item.module)))
    expected = policy.dependencies
    expected_records = {(item.path, item.module): item for item in expected}
    actual_records = {(item.path, item.module): item for item in actual}
    for identity in sorted(set(expected_records) | set(actual_records)):
        wanted = expected_records.get(identity)
        observed = actual_records.get(identity)
        if wanted != observed:
            item = observed or wanted
            assert item is not None
            findings.append(
                ToolsBoundaryFinding(
                    item.path,
                    item.lines[0],
                    "TOOLS_PRODUCT_INVENTORY_DRIFT",
                    f"expected={wanted.record() if wanted else None}; "
                    f"observed={observed.record() if observed else None}",
                )
            )
    return tuple(findings), actual


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check active Lab tools → Product dependencies")
    parser.add_argument("--root", type=Path, default=Path("tools"))
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("docs/tools-product-dependencies.json"),
    )
    args = parser.parse_args(argv)
    try:
        findings, dependencies = verify_tools_boundary(args.root, args.inventory)
    except (OSError, ValueError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"POLICY_INVALID: {exc}")
        return 1
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.code}: {finding.detail}")
    if findings:
        print(f"FAIL {len(findings)} active-tools boundary finding(s)")
        return 1
    private_count = sum(
        dependency.classification == "LEGACY_PRIVATE" for dependency in dependencies
    )
    print(
        "PASS active tools Product dependency inventory "
        f"({len({dependency.path for dependency in dependencies})} files, "
        f"{len(dependencies)} dependencies, {private_count} grandfathered private)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
