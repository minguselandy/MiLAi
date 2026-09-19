"""Small append-only evidence and dependency sealing utilities; no corpus evaluation."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]


def _current_lab_path(path: Path) -> Path:
    """Resolve an absolute dependency recorded before the Lab was relocated.

    Historical evidence manifests contain absolute source paths.  The active
    Lab now lives under the monorepo, so the old prefix must not be treated as
    a second source tree during validation.  Only paths containing the exact
    ``MiLAi-Lab`` component are remapped, and the mapped file must exist.
    """

    try:
        path.relative_to(LAB)
    except ValueError:
        pass
    else:
        return path
    try:
        marker = path.parts.index("MiLAi-Lab")
    except ValueError:
        return path
    candidate = LAB.joinpath(*path.parts[marker + 1 :])
    return candidate if candidate.is_file() else path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def dependencies(entries: list[Path]) -> list[Path]:
    pending, seen = list(entries), set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                candidate = LAB / "tools" / (name.split(".")[0] + ".py")
                if candidate.is_file():
                    pending.append(candidate)
    return sorted(seen | {LAB / "pyproject.toml", LAB / "uv.lock"})


def seal(root: Path, *, entries: list[Path], inputs: list[Path], contract: dict) -> dict:
    if root.exists():
        raise ValueError("FRESH_EVIDENCE_ROOT_REQUIRED")
    root.mkdir(parents=True)
    files = dependencies(entries)
    manifest = {
        "contract": contract,
        "dependencies": {str(p): sha(p) for p in files},
        "inputs": {str(p): sha(p) for p in inputs},
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name) for name in ["jsonschema", "httpx", "pytest"]
        },
    }
    for path in files:
        target = root / "executed-source" / path.relative_to(LAB)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(path.read_bytes())
    save(root / "manifest.json", manifest)
    return manifest


def validate(root: Path, *, manifest_sha256: str | None = None) -> dict:
    if manifest_sha256 is not None and sha(root / "manifest.json") != manifest_sha256:
        raise ValueError("MANIFEST_DRIFT")
    manifest = read(root / "manifest.json")
    for name, expected in manifest["dependencies"].items():
        path = Path(name)
        current_path = _current_lab_path(path)
        if not current_path.is_file():
            raise ValueError("IMPLEMENTATION_SOURCE_UNAVAILABLE")
        if (
            sha(current_path) != expected
            or sha(root / "executed-source" / current_path.relative_to(LAB)) != expected
        ):
            raise ValueError("IMPLEMENTATION_DRIFT")
    for name, expected in manifest["inputs"].items():
        if sha(Path(name)) != expected:
            raise ValueError("INPUT_DRIFT")
    if platform.python_version() != manifest["python"]:
        raise ValueError("PYTHON_DRIFT")
    if any(
        importlib.metadata.version(name) != version
        for name, version in manifest["packages"].items()
    ):
        raise ValueError("DEPENDENCY_VERSION_DRIFT")
    return manifest
