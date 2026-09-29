from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from milai_lab.import_graph import ImportTarget, module_name, scan_import_targets

_FORBIDDEN_IMPORT_ROOTS = frozenset({"evals", "milai", "milai_client", "research", "scripts"})
_FORBIDDEN_LITERAL_FRAGMENTS = (
    "/".join(("", "cra", "memory", "mx_memory")),
    "/".join(("MiLAi", "runtime")),
    "/".join(("MiLAi", "evals")),
)
# Baselines contains method assemblies as well as three complete memory facades.
# These concrete roles never relax the ban on methods importing runners/scorers.
_BASELINE_MEMORY = frozenset(
    {"langmem_mcp", "langmem_strict_tools", "langmem_revision_store", "langmem_instrumentation"}
)
_ALLOWED_LAYERS = {
    "contracts": frozenset({"contracts"}),
    "memory": frozenset({"contracts", "memory"}),
    "application": frozenset({"contracts", "application", "harness"}),
    "harness": frozenset({"contracts", "harness"}),
    "providers": frozenset({"contracts", "providers", "harness"}),
    "integrations": frozenset({"contracts", "memory", "providers", "integrations"}),
    "methods": frozenset(
        {
            "contracts",
            "memory",
            "application",
            "harness",
            "providers",
            "integrations",
            "methods",
            "datasets",
        }
    ),
    "datasets": frozenset({"contracts", "datasets", "harness"}),
    "scorers": frozenset({"contracts", "datasets", "scorers"}),
    "benchmarks": frozenset(
        {
            "contracts",
            "datasets",
            "scorers",
            "harness",
            "providers",
            "memory",
            "integrations",
            "benchmarks",
        }
    ),
    "analysis": frozenset({"contracts", "datasets", "harness", "methods", "analysis"}),
}
SHARED_LEAF_IMPORTS = {
    "milai_lab.harness.artifact_io": frozenset(),
    "milai_lab.memory.embeddings": frozenset(),
    "milai_lab.memory.presentation": frozenset({"milai_lab.contracts.request"}),
    "milai_lab.analysis.trace_accounting": frozenset({"milai_lab.harness.artifact_io"}),
}
FACADE_MODULES = {
    "milai_lab.methods.request_context": frozenset(
        {"milai_lab.contracts.request", "milai_lab.memory.presentation"}
    ),
    "milai_lab.baselines.langmem_mcp": frozenset({"milai_lab.memory.mcp"}),
    "milai_lab.baselines.langmem_strict_tools": frozenset({"milai_lab.memory.strict_tools"}),
    "milai_lab.baselines.langmem_revision_store": frozenset({"milai_lab.memory.revision_store"}),
    "milai_lab.runners.mem0_native": frozenset({"milai_lab.integrations.memory.mem0"}),
    "milai_lab.runners.simplemem_native": frozenset({"milai_lab.integrations.memory.simplemem"}),
    "milai_lab.providers.langmem_chat": frozenset({"milai_lab.providers.chat_bridge"}),
    "milai_lab.runners.langmem_foundation": frozenset(
        {"milai_lab.application.journal", "milai_lab.application.tools"}
    ),
}


@dataclass(frozen=True, slots=True)
class BoundaryFinding:
    path: str
    line: int
    code: str
    detail: str


def source_layer(module: str) -> str:
    if module == "milai_lab.harness.benchmark_execution":
        return "benchmarks"
    parts = module.split(".")
    layer = parts[1] if len(parts) > 1 else "entrypoint"
    if layer not in {*_ALLOWED_LAYERS, "baselines", "runners"}:
        return "entrypoint"
    if layer == "baselines":
        return "memory" if len(parts) > 2 and parts[2] in _BASELINE_MEMORY else "methods"
    return layer


def import_allowed(source: str, target: str) -> bool:
    """Directory ownership is fixed here, independent of labels in the CI matrix."""
    if target == "milai_lab":
        return source_layer(source) in {"runners", "entrypoint"}
    layer = source_layer(source)
    if layer == "providers" and target in {
        "milai_lab.memory.presentation",
        "milai_lab.memory.embeddings",
    }:
        return True
    if layer == "integrations" and target == "milai_lab.harness.artifact_io":
        return True
    if source in FACADE_MODULES and target in FACADE_MODULES[source]:
        return True
    # Canonical memory must not route through old baseline aliases.
    if layer == "memory" and target.startswith("milai_lab.baselines"):
        return False
    return source_layer(target) in _ALLOWED_LAYERS.get(
        layer,
        frozenset(
            {
                "contracts",
                "memory",
                "application",
                "harness",
                "providers",
                "integrations",
                "methods",
                "datasets",
                "scorers",
                "analysis",
                "runners",
                "benchmarks",
                "product_adapter",
                "context_preflight",
                "longmemeval_gate",
                "entrypoint",
            }
        ),
    )


def _pure_facade(tree: ast.Module, module: str) -> tuple[tuple[int, str], ...]:
    bad: list[tuple[int, str]] = []
    typing_guards: set[str] = set()
    typing_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            typing_guards.update(
                name.asname or name.name for name in node.names if name.name == "TYPE_CHECKING"
            )
        elif isinstance(node, ast.Import):
            typing_modules.update(
                name.asname or name.name for name in node.names if name.name == "typing"
            )

    def check(nodes: list[ast.stmt], *, guarded: bool = False) -> None:
        for index, node in enumerate(nodes):
            if (
                not guarded
                and index == 0
                and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            if (
                isinstance(node, ast.ImportFrom)
                and node.module in (*FACADE_MODULES[module], "__future__", "typing")
                and all(name.name != "*" for name in node.names)
            ):
                continue
            if isinstance(node, ast.Import) and all(
                name.name in {*FACADE_MODULES[module], "typing"} for name in node.names
            ):
                continue
            if (
                not guarded
                and isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__all__"
                and isinstance(node.value, (ast.List, ast.Tuple))
                and all(
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                    for value in node.value.elts
                )
            ):
                continue
            if (
                not guarded
                and isinstance(node, ast.If)
                and not node.orelse
                and (
                    (isinstance(node.test, ast.Name) and node.test.id in typing_guards)
                    or (
                        isinstance(node.test, ast.Attribute)
                        and node.test.attr == "TYPE_CHECKING"
                        and isinstance(node.test.value, ast.Name)
                        and node.test.value.id in typing_modules
                    )
                )
            ):
                check(node.body, guarded=True)
                continue
            bad.append((node.lineno, type(node).__name__))

    check(tree.body)
    return tuple(bad)


def _approved_loader(tree: ast.Module, module: str, target: ImportTarget) -> bool:
    """Two existing pinned external-source loaders, with explicit origin/namespace checks."""
    if module == "milai_lab.integrations.memory.simplemem" and target.context == (
        "SimpleMemTextRuntime",
        "__init__",
    ):
        required: tuple[str, ...] = (
            "self.dependency = dependency_identity(policy)",
            "source = self.dependency['source_root']",
            "package_dir = Path(source) / 'simplemem'",
            "raise ValueError('SIMPLEMEM_IMPORT_SOURCE_CHANGED')",
        )
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        code = ast.unparse(function)
        if not all(part in code for part in required):
            return False
        return target.expression in {
            "importlib.util.spec_from_file_location('simplemem', package_dir / '__init__.py', "
            "submodule_search_locations=[str(package_dir)])",
            "importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(package)",
            "importlib.import_module('simplemem.core.' + name)",
        } and (target.module is None or target.module.startswith("simplemem"))
    if module == "milai_lab.datasets.merit" and target.context == ("_load_arc",):
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_load_arc"
        )
        code = ast.unparse(function)
        required = (
            "root = Path(selection['external_root']).resolve()",
            "package_dir = root / 'merit'",
            "if _sha256(root / relative) != expected:",
            "for relative, expected in selection['source_sha256'].items():",
            "raise ValueError('MERIT_IMPORT_OUTSIDE_PINNED_ROOT')",
            "package_name = f'_milai_pinned_merit_",
        )
        return (
            all(part in code for part in required)
            and target.expression
            in {
                "importlib.util.spec_from_file_location(package_name, package_dir / '__init__.py', "
                "submodule_search_locations=[str(package_dir)])",
                "importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(package)",
                "importlib.import_module(f'{package_name}.{part}')",
            }
            and (target.module is None or target.module.startswith("_milai_pinned_merit_"))
        )
    return False


def scan_active_source(root: Path) -> tuple[BoundaryFinding, ...]:
    findings: list[BoundaryFinding] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        display = path.relative_to(root).as_posix()
        module = module_name(path, root)
        if module in FACADE_MODULES:
            findings.extend(
                BoundaryFinding(display, line, "FACADE_LOGIC", detail)
                for line, detail in _pure_facade(tree, module)
            )
        for target in scan_import_targets(tree, module, is_package=path.name == "__init__.py"):
            name = target.module
            approved = _approved_loader(tree, module, target)
            if name is None or "*" in name or target.kind in {"file_load", "loader_execution"}:
                if not approved:
                    findings.append(
                        BoundaryFinding(
                            display,
                            target.line,
                            "UNRESOLVED_IMPORT",
                            target.expression or "relative import",
                        )
                    )
                continue
            if name.split(".")[0] in _FORBIDDEN_IMPORT_ROOTS:
                findings.append(
                    BoundaryFinding(display, target.line, "PRIVATE_PRODUCT_IMPORT", name)
                )
            if (
                source_layer(module) == "contracts"
                and not name.startswith("milai_lab.")
                and name.split(".")[0] not in sys.stdlib_module_names | {"typing_extensions"}
            ):
                findings.append(BoundaryFinding(display, target.line, "CONTRACT_SDK_IMPORT", name))
            if name == "milai_lab" or name.startswith("milai_lab."):
                # from X import a class is also scanned as a possible submodule;
                # enforce its owning module, avoiding fabricated leaf class names.
                owned = name
                if target.kind == "from_target":
                    owned = name.rpartition(".")[0]
                    if owned in {"milai_lab", *("milai_lab." + layer for layer in _ALLOWED_LAYERS)}:
                        owned = name
                if not import_allowed(module, owned):
                    findings.append(BoundaryFinding(display, target.line, "LAYER_IMPORT", name))
                if module in SHARED_LEAF_IMPORTS and owned not in SHARED_LEAF_IMPORTS[module]:
                    findings.append(
                        BoundaryFinding(display, target.line, "SHARED_LEAF_IMPORT", name)
                    )
            elif (
                module in SHARED_LEAF_IMPORTS and name.split(".")[0] not in sys.stdlib_module_names
            ):
                findings.append(BoundaryFinding(display, target.line, "SHARED_LEAF_SDK", name))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for fragment in _FORBIDDEN_LITERAL_FRAGMENTS:
                    if fragment in node.value:
                        findings.append(
                            BoundaryFinding(display, node.lineno, "HARDCODED_LEGACY_PATH", fragment)
                        )
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                value = node.func.value
                if (
                    node.func.attr in {"append", "insert"}
                    and isinstance(value, ast.Attribute)
                    and value.attr == "path"
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "sys"
                ):
                    findings.append(
                        BoundaryFinding(display, node.lineno, "SYS_PATH_MUTATION", node.func.attr)
                    )
    return tuple(dict.fromkeys(findings))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check MiLAi Lab source ownership and boundaries")
    parser.add_argument("root", nargs="?", type=Path, default=Path("src/milai_lab"))
    args = parser.parse_args(argv)
    findings = scan_active_source(args.root)
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.code}: {finding.detail}")
    if findings:
        print(f"FAIL {len(findings)} active-boundary finding(s)")
        return 1
    print("PASS active package DAG, pure facades, shared leaves and import paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
