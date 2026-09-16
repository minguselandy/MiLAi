"""Explicit scoped evidence IO; not Batch admission or a historical-carry policy.

The sole guard deliberately couples this adapter to the frozen read-scope
version's protected _active/_poison hooks. Semantic failures must poison the
owner's scope without closing it early or replacing the original exception.
No global reader substitution, implicit context, or cross-call PASS cache exists.

JSONL reuses verified bytes, but is parsed anew per call: AdmissionReadScope has
no JSONL parse-cache API. Scope.json_parses therefore counts JSON documents only.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import platform
from contextlib import contextmanager
from pathlib import Path

from v0220_evidence import LAB
from v0222_admission_read_scope import AdmissionReadScope


class ScopedEvidenceError(ValueError):
    """Frozen evidence failed an explicit structural or semantic check."""


@contextmanager
def _guard(scope: AdmissionReadScope):
    if not isinstance(scope, AdmissionReadScope):
        raise TypeError("EXPLICIT_ADMISSION_READ_SCOPE_REQUIRED")
    scope._active()
    try:
        yield
    except BaseException as exc:
        scope._poison(exc)
        raise


def _mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ScopedEvidenceError(name + "_MUST_BE_A_HASH_MAPPING")
    for path in value:
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ScopedEvidenceError(name + "_REQUIRES_ABSOLUTE_PATHS")
    return value


def _verify_files(scope: AdmissionReadScope, value, name: str) -> None:
    for path, digest in _mapping(value, name).items():
        scope.read_bytes(Path(path), digest)


def verify_manifest(scope: AdmissionReadScope, root: Path, expected_sha256: str) -> dict:
    """Validate original source, executed copies, inputs and environment anew."""
    with _guard(scope):
        root = Path(root)
        manifest = scope.read_json(root / "manifest.json", expected_sha256)
        if not isinstance(manifest, dict):
            raise ScopedEvidenceError("MANIFEST_OBJECT_REQUIRED")
        for path, digest in _mapping(manifest["dependencies"], "DEPENDENCIES").items():
            source = Path(path)
            relative = source.relative_to(LAB)
            scope.read_bytes(source, digest)
            scope.read_bytes(root / "executed-source" / relative, digest)
        _verify_files(scope, manifest["inputs"], "INPUTS")
        if platform.python_version() != manifest["python"]:
            raise ScopedEvidenceError("PYTHON_DRIFT")
        packages = manifest["packages"]
        if not isinstance(packages, dict):
            raise ScopedEvidenceError("PACKAGES_MAPPING_REQUIRED")
        for name, version in packages.items():
            if not isinstance(name, str) or not isinstance(version, str):
                raise ScopedEvidenceError("PACKAGE_NAME_AND_VERSION_STRINGS_REQUIRED")
            if importlib.metadata.version(name) != version:
                raise ScopedEvidenceError("DEPENDENCY_VERSION_DRIFT")
        return manifest


def verify_tree(
    scope: AdmissionReadScope,
    path: Path,
    expected_sha256: str,
    seen: set[tuple[str, str]] | None = None,
) -> None:
    """Follow only original explicit references, with private per-call tree state.

    Incoming hashes and manifest semantics are checked even for completed nodes.
    A node is completed only after all its references succeeded. Both active and
    completed sets are private to this invocation, never shared with another
    purpose or call. Optional seen must be an empty exact built-in set; it is
    retained for interface compatibility, not used as actual traversal state.
    """
    with _guard(scope):
        if seen is not None and (type(seen) is not set or seen):
            raise ScopedEvidenceError("TREE_SEEN_MUST_START_EMPTY")
        stack, completed = set(), set()

        def edges(node):
            if isinstance(node, list):
                for item in node:
                    yield from edges(item)
            elif isinstance(node, dict):
                for field in ("files", "dependencies", "inputs"):
                    for name, digest in _mapping(node.get(field, {}), field).items():
                        yield Path(name), digest
                hashes = node.get("hashes", {})
                if not isinstance(hashes, dict):
                    raise ScopedEvidenceError("HASHES_MAPPING_REQUIRED")
                for field, digest in hashes.items():
                    candidate = node.get(field)
                    if isinstance(candidate, str) and Path(candidate).is_absolute():
                        yield Path(candidate), digest
                for field in ("references", "entries"):
                    if field in node:
                        yield from edges(node[field])

        def visit(current, digest):
            current = Path(current)
            scope.read_bytes(current, digest)
            if current.suffix != ".json":
                return
            key = (str(current.resolve()), digest)
            value, loaded = None, False
            if current.name == "manifest.json":
                value = scope.read_json(current, digest)
                loaded = True
                if isinstance(value, dict) and all(
                    field in value for field in ("dependencies", "inputs", "python", "packages")
                ):
                    verify_manifest(scope, current.parent, digest)
            if key in completed:
                return
            if not loaded:
                value = scope.read_json(current, digest)
            references = list(edges(value))
            # Active recursion markers never bypass immediate reference hashes.
            for target, digest in references:
                scope.read_bytes(target, digest)
            if key in stack:
                return
            stack.add(key)
            try:
                for target, digest in references:
                    visit(target, digest)
                completed.add(key)
            finally:
                stack.remove(key)

        visit(path, expected_sha256)


def _strict_json(raw: str):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ScopedEvidenceError("DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    def constant(value):
        raise ScopedEvidenceError("NONFINITE_JSON_NUMBER: " + value)

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ScopedEvidenceError("NONFINITE_JSON_NUMBER: " + value)
        return result

    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float
    )


def read_artifact(scope: AdmissionReadScope, row) -> dict:
    """Check SQL and file dependency-map union; equal key sets are not required."""
    with _guard(scope):
        if row is None:
            raise ScopedEvidenceError("ARTIFACT_ROW_REQUIRED")
        path = Path(row["path"])
        if not path.is_absolute():
            raise ScopedEvidenceError("ARTIFACT_ABSOLUTE_PATH_REQUIRED")
        value = scope.read_json(path, row["sha256"])
        if not isinstance(value, dict):
            raise ScopedEvidenceError("ARTIFACT_OBJECT_REQUIRED")
        dependencies = _strict_json(row["dependencies"])
        _verify_files(scope, dependencies, "SQL_DEPENDENCIES")
        if "files" in value:
            if not isinstance(value["files"], dict) or not value["files"]:
                raise ScopedEvidenceError("EXPLICIT_NONEMPTY_ARTIFACT_FILES_REQUIRED")
            _verify_files(scope, value["files"], "ARTIFACT_FILES")
        return value


def read_pinned_events(scope: AdmissionReadScope, path: Path, expected_sha256: str) -> list[dict]:
    """Read fixed JSONL bytes, not an unpinned current mutable episode ledger.

    Empty files are allowed. Blank/non-object lines, duplicate keys, invalid raw
    UTF-8 and nonfinite numbers are rejected. This parses, but does not approve,
    event transitions or any particular historical unknown-reservation policy.
    """
    with _guard(scope):
        raw = scope.read_bytes(path, expected_sha256).decode("utf-8")
        events = []
        for line in raw.splitlines():
            value = _strict_json(line)
            if not isinstance(value, dict):
                raise ScopedEvidenceError("JSONL_EVENT_OBJECT_REQUIRED")
            events.append(value)
        return events
