"""Read static and dynamic import targets without executing inspected modules."""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ImportTarget:
    module: str | None
    line: int
    kind: str
    context: tuple[str, ...] = ()
    expression: str = ""


@dataclass(frozen=True, slots=True)
class StringValue:
    prefix: str
    complete: bool = True


def module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("milai_lab", *parts))


def _function_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _function_name(node.value, aliases)
        return None if base is None else base + "." + node.attr
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        base = _function_name(node.args[0], aliases)
        attribute = node.args[1]
        if base and isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
            return base + "." + attribute.value
    return None


def _strings(
    node: ast.AST, values: dict[str, tuple[StringValue, ...]], seen: frozenset[str] = frozenset()
) -> tuple[StringValue, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (StringValue(node.value),)
    if isinstance(node, ast.Name) and node.id not in seen:
        return values.get(node.id, ())
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _strings(node.left, values, seen)
        right = _strings(node.right, values, seen)
        if not left:
            return ()
        return tuple(
            StringValue(a.prefix + b.prefix if a.complete else a.prefix, a.complete and b.complete)
            for a in left
            for b in (right or (StringValue("", False),))
        )
    if isinstance(node, ast.JoinedStr):
        result: tuple[StringValue, ...] = (StringValue(""),)
        for part in node.values:
            following = (
                _strings(part.value, values, seen)
                if isinstance(part, ast.FormattedValue)
                else _strings(part, values, seen)
            )
            result = tuple(
                StringValue(
                    a.prefix + b.prefix if a.complete else a.prefix, a.complete and b.complete
                )
                for a in result
                for b in (following or (StringValue("", False),))
            )
        return result
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return tuple(value for part in node.elts for value in _strings(part, values, seen))
    if isinstance(node, ast.IfExp):
        return (*_strings(node.body, values, seen), *_strings(node.orelse, values, seen))
    return ()


def _bindings(
    tree: ast.AST,
    parent_aliases: dict[str, str] | None = None,
    parent_values: dict[str, tuple[StringValue, ...]] | None = None,
) -> tuple[dict[str, str], dict[str, tuple[StringValue, ...]]]:
    aliases: dict[str, str] = dict(parent_aliases or {})
    assignments: list[tuple[str, ast.AST]] = []

    def local_nodes(node: ast.AST) -> list[ast.AST]:
        if node is not tree and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            return []
        return [
            node,
            *(part for child in ast.iter_child_nodes(node) for part in local_nodes(child)),
        ]

    for node in local_nodes(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split(".")[0]] = (
                    name.name if name.asname else name.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for name in node.names:
                aliases[name.asname or name.name] = node.module + "." + name.name
        elif isinstance(node, ast.Assign):
            assignments.extend(
                (target.id, node.value) for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            assignments.append((node.target.id, node.value))
        elif isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name):
            assignments.append((node.target.id, node.iter))
    values: dict[str, tuple[StringValue, ...]] = dict(parent_values or {})
    for binding, _ in assignments:
        values.pop(binding, None)
    if isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for argument in (*tree.args.posonlyargs, *tree.args.args, *tree.args.kwonlyargs):
            values.pop(argument.arg, None)
    # A bounded fixed point handles aliases, concatenation and comprehensions without eval.
    for _ in range(len(assignments) + 1):
        changed = False
        for binding, expression in assignments:
            function = _function_name(expression, aliases)
            if (
                function
                and (function.startswith(("importlib.", "builtins.")) or function == "__import__")
                and aliases.get(binding) != function
            ):
                aliases[binding] = function
                changed = True
            strings = _strings(expression, values, frozenset({binding}))
            previous = values.get(binding, ())
            # Retain every possible literal binding; a later unknown value cannot
            # conceal an earlier import path or be treated as that safe literal.
            if not strings and previous:
                strings = (StringValue("", False),)
            combined = tuple(dict.fromkeys((*previous, *strings)))
            if combined and previous != combined:
                values[binding] = combined
                changed = True
        if not changed:
            break
    return aliases, values


def _relative(name: str, package: str) -> str | None:
    try:
        return importlib.util.resolve_name(name, package) if name.startswith(".") else name
    except (ImportError, ValueError):
        return None


def scan_import_targets(
    tree: ast.AST, module: str, *, is_package: bool = False
) -> tuple[ImportTarget, ...]:
    """Include imports in every function/guard and known dynamic loader aliases."""
    aliases, values = _bindings(tree)
    package = module if is_package else module.rpartition(".")[0]
    targets: list[ImportTarget] = []

    def visit(
        node: ast.AST,
        context: tuple[str, ...],
        aliases: dict[str, str],
        values: dict[str, tuple[StringValue, ...]],
    ) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            context = (*context, node.name)
            aliases, values = _bindings(node, aliases, values)
        if isinstance(node, ast.Import):
            targets.extend(
                ImportTarget(name.name, node.lineno, "static", context) for name in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            imported = _relative("." * node.level + (node.module or ""), package)
            targets.append(ImportTarget(imported, node.lineno, "static", context))
            if imported and imported.startswith("milai_lab"):
                targets.extend(
                    ImportTarget(imported + "." + part.name, node.lineno, "from_target", context)
                    for part in node.names
                    if part.name != "*"
                )
                if imported == "milai_lab" and any(part.name == "*" for part in node.names):
                    targets.append(ImportTarget(None, node.lineno, "wildcard_root", context))
        elif isinstance(node, ast.Call):
            function = _function_name(node.func, aliases)
            if function in {
                "__import__",
                "builtins.__import__",
                "importlib.import_module",
                "importlib.util.spec_from_file_location",
                "importlib.machinery.SourceFileLoader",
            }:
                argument = (
                    node.args[0]
                    if node.args
                    else next(
                        (item.value for item in node.keywords if item.arg in {"name", "location"}),
                        ast.Constant(None),
                    )
                )
                names = _strings(argument, values)
                kind = (
                    "file_load"
                    if function.endswith(("spec_from_file_location", "SourceFileLoader"))
                    else "dynamic"
                )
                packages: tuple[StringValue, ...] = (StringValue(package),)
                if function == "importlib.import_module":
                    package_arg = (
                        node.args[1]
                        if len(node.args) > 1
                        else next(
                            (item.value for item in node.keywords if item.arg == "package"), None
                        )
                    )
                    packages = _strings(package_arg, values) if package_arg is not None else ()
                level = (
                    node.args[4]
                    if len(node.args) > 4
                    else next((item.value for item in node.keywords if item.arg == "level"), None)
                )
                if function in {"__import__", "builtins.__import__"} and level is not None:
                    if isinstance(level, ast.Constant) and type(level.value) is int:
                        names = tuple(
                            StringValue("." * level.value + name.prefix, name.complete)
                            for name in names
                        )
                    else:
                        names = ()
                expression = ast.unparse(node)
                if not names:
                    targets.append(ImportTarget(None, node.lineno, kind, context, expression))
                for name in names:
                    resolved = (
                        _relative(name.prefix, packages[0].prefix)
                        if name.prefix.startswith(".") and packages
                        else None
                        if name.prefix.startswith(".")
                        else name.prefix
                    )
                    if resolved is not None and not name.complete:
                        resolved += "*"
                    targets.append(ImportTarget(resolved, node.lineno, kind, context, expression))
                if function in {"__import__", "builtins.__import__"}:
                    fromlist = (
                        node.args[3]
                        if len(node.args) > 3
                        else next(
                            (item.value for item in node.keywords if item.arg == "fromlist"), None
                        )
                    )
                    if fromlist is not None:
                        for name in names:
                            for part in _strings(fromlist, values):
                                resolved = _relative(name.prefix, package)
                                targets.append(
                                    ImportTarget(
                                        resolved + "." + part.prefix if resolved else None,
                                        node.lineno,
                                        "dynamic",
                                        context,
                                        expression,
                                    )
                                )
            elif function == "importlib.util.module_from_spec" or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"exec_module", "load_module"}
            ):
                targets.append(
                    ImportTarget(None, node.lineno, "loader_execution", context, ast.unparse(node))
                )
        for child in ast.iter_child_nodes(node):
            visit(child, context, aliases, values)

    visit(tree, (), aliases, values)
    return tuple(targets)
