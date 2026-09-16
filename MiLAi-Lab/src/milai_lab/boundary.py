from __future__ import annotations

import argparse
import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_FORBIDDEN_IMPORT_ROOTS = frozenset({"evals", "milai", "milai_client", "research", "scripts"})
_FORBIDDEN_LITERAL_FRAGMENTS = (
    "/".join(("", "cra", "memory", "mx_memory")),
    "/".join(("MiLAi", "runtime")),
    "/".join(("MiLAi", "evals")),
)


@dataclass(frozen=True, slots=True)
class BoundaryFinding:
    path: str
    line: int
    code: str
    detail: str


def _import_root(name: str | None) -> str:
    return (name or "").split(".", maxsplit=1)[0]


def scan_active_source(root: Path) -> tuple[BoundaryFinding, ...]:
    findings: list[BoundaryFinding] = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        display = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _import_root(alias.name) in _FORBIDDEN_IMPORT_ROOTS:
                        findings.append(
                            BoundaryFinding(
                                display,
                                node.lineno,
                                "PRIVATE_PRODUCT_IMPORT",
                                alias.name,
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                if _import_root(node.module) in _FORBIDDEN_IMPORT_ROOTS:
                    findings.append(
                        BoundaryFinding(
                            display,
                            node.lineno,
                            "PRIVATE_PRODUCT_IMPORT",
                            node.module or "",
                        )
                    )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
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
    return tuple(findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check MiLAi Lab active-source boundaries")
    parser.add_argument("root", nargs="?", type=Path, default=Path("src/milai_lab"))
    args = parser.parse_args(argv)
    findings = scan_active_source(args.root)
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.code}: {finding.detail}")
    if findings:
        print(f"FAIL {len(findings)} active-boundary finding(s)")
        return 1
    print("PASS active package has no private product or legacy imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
