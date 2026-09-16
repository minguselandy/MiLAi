#!/usr/bin/env python3
"""Validate the MiLAi logical-architecture candidate bundle with stdlib only."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_IDS = {
    "goals": {f"G{index}" for index in range(1, 10)},
    "invariants": {f"I-{index:02d}" for index in range(1, 13)},
    "transactions": {
        *(f"TX-{index:02d}" for index in range(1, 7)),
        "EP-01",
        "EP-02",
    },
    "roles": {
        "MIGRATION_OWNER",
        "API_RUNTIME",
        "STEWARD_EXECUTOR",
        "PROJECTION_WORKER",
        "AUDIT_RUNNER",
    },
    "freeze_gates": {f"AF-{index:02d}" for index in range(10)},
}

REQUIRED_FILES = {
    "README.md",
    "BASELINE.md",
    "AUTHOR_PREFLIGHT.md",
    "AF09_REMEDIATION.md",
    "OBJECTS.md",
    "PERMISSIONS.md",
    "INVARIANTS.md",
    "TRANSACTIONS.md",
    "RETRIEVAL_CONTEXT.md",
    "DELETION_RECOVERY.md",
    "THREAT_MODEL.md",
    "FREEZE_REVIEW.md",
    "CROSSWALK.md",
    "crosswalk.json",
    "architecture_manifest.json",
    "scripts/validate_bundle.py",
    "scripts/verify_lock.py",
    "scripts/refresh_manifest.py",
    "tests/test_bundle.py",
}

COVERAGE_FIELDS = ("design_refs", "implementations", "tests", "reports")
BANNER = "NO-GO FOR SCHEMA FREEZE"
BUNDLE_PROJECT_PREFIX = "architecture/v1.0-candidate/"
EXPECTED_MANIFEST_SCALARS = {
    "format_version": "milai-architecture-manifest-v1",
    "architecture_version": "1.0.0-candidate.5",
    "bundle_version": "1.0.0-candidate.5",
    "status": "CANDIDATE",
    "schema_status": "0.1.x EXPERIMENTAL",
    "freeze_status": "NO-GO",
    "hash_algorithm": "sha256",
    "manifest_self_lock": False,
}
EXPECTED_PENDING_REVIEW = {
    "gate": "AF-09",
    "status": "PENDING_INDEPENDENT_REVIEW",
    "independent_reviewer": None,
    "decision": None,
}


def _defaults() -> tuple[Path, Path]:
    script = Path(__file__).resolve()
    return script.parents[1], script.parents[3]


def _path_part(reference: str) -> str:
    """Return the repository path from a path#anchor::node reference."""
    return reference.split("#", 1)[0].split("::", 1)[0]


def _safe_repo_path(
    project_root: Path, reference: str
) -> tuple[Path | None, str | None]:
    path_text = _path_part(reference)
    candidate = Path(path_text)
    if not path_text or candidate.is_absolute() or ".." in candidate.parts:
        return None, f"unsafe repository-relative path: {reference!r}"
    resolved_root = project_root.resolve()
    resolved = (resolved_root / candidate).resolve(strict=False)
    if not resolved.is_relative_to(resolved_root):
        return None, f"path escapes project root: {reference!r}"
    return resolved, None


def _validate_references(
    references: Any,
    *,
    field: str,
    item_id: str,
    project_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(references, list) or not references:
        return [f"{item_id}.{field} must be a non-empty list"]
    for reference in references:
        if not isinstance(reference, str) or not reference.strip():
            errors.append(f"{item_id}.{field} contains a non-string/empty reference")
            continue
        path, path_error = _safe_repo_path(project_root, reference)
        if path_error:
            errors.append(f"{item_id}.{field}: {path_error}")
            continue
        assert path is not None
        if not path.is_file():
            errors.append(f"{item_id}.{field} target does not exist: {reference}")
            continue
        if field == "tests" and "::" in reference:
            node = reference.rsplit("::", 1)[1]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node):
                errors.append(f"{item_id}.tests has invalid test node: {reference}")
            elif f"def {node}(" not in path.read_text(encoding="utf-8"):
                errors.append(f"{item_id}.tests node does not exist: {reference}")
    return errors


def _validate_id_collection(
    data: dict[str, Any],
    *,
    key: str,
    project_root: Path,
) -> list[str]:
    errors: list[str] = []
    items = data.get(key)
    if not isinstance(items, list):
        return [f"{key} must be a list"]

    identifiers: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{key}[{index}] must be an object")
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str):
            errors.append(f"{key}[{index}].id must be a string")
            continue
        identifiers.append(identifier)

    found = set(identifiers)
    expected = EXPECTED_IDS[key]
    if found != expected:
        errors.append(
            f"{key} ID set mismatch: missing={sorted(expected - found)}, "
            f"extra={sorted(found - expected)}"
        )
    if len(identifiers) != len(found):
        errors.append(f"{key} contains duplicate IDs")

    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        identifier = item["id"]
        if key in {"goals", "invariants"}:
            statement = item.get("statement")
            if not isinstance(statement, str) or not statement.strip():
                errors.append(f"{identifier}.statement must be non-empty")
            for field in COVERAGE_FIELDS:
                errors.extend(
                    _validate_references(
                        item.get(field),
                        field=field,
                        item_id=identifier,
                        project_root=project_root,
                    )
                )
            if key == "invariants":
                for field in ("positive_tests", "negative_tests"):
                    errors.extend(
                        _validate_references(
                            item.get(field),
                            field="tests",
                            item_id=f"{identifier}.{field}",
                            project_root=project_root,
                        )
                    )
        elif key == "transactions":
            for field in COVERAGE_FIELDS:
                errors.extend(
                    _validate_references(
                        item.get(field),
                        field=field,
                        item_id=identifier,
                        project_root=project_root,
                    )
                )
        elif key == "roles":
            for field in ("design_refs", "implementations", "tests"):
                errors.extend(
                    _validate_references(
                        item.get(field),
                        field=field,
                        item_id=identifier,
                        project_root=project_root,
                    )
                )
        elif key == "freeze_gates":
            status = item.get("status")
            if status not in {"PASS_CANDIDATE", "PENDING_INDEPENDENT_REVIEW"}:
                errors.append(f"{identifier}.status is not an allowed candidate status")
            errors.extend(
                _validate_references(
                    item.get("evidence"),
                    field="evidence",
                    item_id=identifier,
                    project_root=project_root,
                )
            )
    return errors


def validate_crosswalk(data: Any, project_root: Path) -> list[str]:
    """Validate the crosswalk structure and all referenced repository evidence."""
    if not isinstance(data, dict):
        return ["crosswalk root must be an object"]
    errors: list[str] = []
    expected_scalars = {
        "format_version": "milai-architecture-crosswalk-v1",
        "architecture_version": "1.0.0-candidate.5",
        "status": "CANDIDATE",
        "schema_status": "0.1.x EXPERIMENTAL",
        "freeze_status": "NO-GO",
    }
    for key, expected in expected_scalars.items():
        if data.get(key) != expected:
            errors.append(f"crosswalk.{key} must equal {expected!r}")

    for key in EXPECTED_IDS:
        errors.extend(_validate_id_collection(data, key=key, project_root=project_root))

    gates = {
        item.get("id"): item
        for item in data.get("freeze_gates", [])
        if isinstance(item, dict)
    }
    for gate_id in sorted(EXPECTED_IDS["freeze_gates"] - {"AF-09"}):
        if gates.get(gate_id, {}).get("status") != "PASS_CANDIDATE":
            errors.append(f"{gate_id} must be PASS_CANDIDATE in candidate.5")
    if gates.get("AF-09", {}).get("status") != "PENDING_INDEPENDENT_REVIEW":
        errors.append("AF-09 must remain PENDING_INDEPENDENT_REVIEW in candidate.5")
    return errors


def _crosswalk_reference_paths(data: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    fields_by_collection = {
        "goals": COVERAGE_FIELDS,
        "invariants": (*COVERAGE_FIELDS, "positive_tests", "negative_tests"),
        "transactions": COVERAGE_FIELDS,
        "roles": ("design_refs", "implementations", "tests"),
        "freeze_gates": ("evidence",),
    }
    for collection, fields in fields_by_collection.items():
        items = data.get(collection)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in fields:
                values = item.get(field)
                if not isinstance(values, list):
                    continue
                references.update(
                    _path_part(value)
                    for value in values
                    if isinstance(value, str) and value
                )
    return references


def _lock_paths(entries: Any, *, base: str | None = None) -> list[str]:
    if not isinstance(entries, list):
        return []
    return [
        entry["path"]
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("path"), str)
        and (base is None or entry.get("base") == base)
    ]


def validate_manifest(manifest: Any, crosswalk: Any) -> list[str]:
    """Validate candidate state and complete lock coverage, not hash values."""
    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]
    errors: list[str] = []
    for key, expected in EXPECTED_MANIFEST_SCALARS.items():
        if manifest.get(key) != expected:
            errors.append(f"manifest.{key} must equal {expected!r}")

    declared = manifest.get("required_files")
    if not isinstance(declared, list) or set(declared) != REQUIRED_FILES:
        errors.append("manifest required_files does not exactly match bundle contract")

    locked_paths = _lock_paths(manifest.get("locked_files"))
    expected_locked = REQUIRED_FILES - {"architecture_manifest.json"}
    if set(locked_paths) != expected_locked:
        errors.append(
            "manifest locked_files must exactly cover every required bundle file "
            "except architecture_manifest.json"
        )
    if len(locked_paths) != len(set(locked_paths)):
        errors.append("manifest locked_files contains duplicate paths")

    if manifest.get("review") != EXPECTED_PENDING_REVIEW:
        errors.append(
            "manifest.review must remain the unsigned AF-09 pending review record"
        )

    if isinstance(crosswalk, dict):
        project_locks = set(_lock_paths(manifest.get("source_locks"), base="project"))
        bundle_locks = set(locked_paths)
        for reference in sorted(_crosswalk_reference_paths(crosswalk)):
            if reference.startswith(BUNDLE_PROJECT_PREFIX):
                relative = reference.removeprefix(BUNDLE_PROJECT_PREFIX)
                if relative == "architecture_manifest.json":
                    continue
                if relative not in bundle_locks:
                    errors.append(
                        f"crosswalk reference is not bundle-locked: {reference}"
                    )
            elif reference not in project_locks:
                errors.append(
                    f"crosswalk reference is not project source-locked: {reference}"
                )
    return errors


def collect_errors(
    bundle_root: Path | None = None,
    project_root: Path | None = None,
) -> list[str]:
    """Return all bundle validation failures without mutating the repository."""
    default_bundle, default_project = _defaults()
    bundle = (bundle_root or default_bundle).resolve()
    project = (project_root or default_project).resolve()
    errors: list[str] = []
    crosswalk_data: Any = None
    manifest_data: Any = None

    for relative in sorted(REQUIRED_FILES):
        target = bundle / relative
        if not target.is_file():
            errors.append(f"missing required artifact: {relative}")

    readme = bundle / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for marker in (
            "Status：`CANDIDATE — NOT FROZEN`",
            "Schema：`0.1.x EXPERIMENTAL`",
            "Implementation：`CANDIDATE`",
            "Freeze：`NO-GO FOR SCHEMA FREEZE`",
        ):
            if marker not in text:
                errors.append(f"README candidate banner missing: {marker}")

    for name in (
        "AUTHOR_PREFLIGHT.md",
        "AF09_REMEDIATION.md",
        "OBJECTS.md",
        "PERMISSIONS.md",
        "INVARIANTS.md",
        "TRANSACTIONS.md",
        "RETRIEVAL_CONTEXT.md",
        "DELETION_RECOVERY.md",
        "THREAT_MODEL.md",
        "FREEZE_REVIEW.md",
        "CROSSWALK.md",
    ):
        path = bundle / name
        if path.is_file() and BANNER not in path.read_text(encoding="utf-8"):
            errors.append(f"{name} is missing the NO-GO banner")

    freeze_review = bundle / "FREEZE_REVIEW.md"
    if freeze_review.is_file():
        review_text = freeze_review.read_text(encoding="utf-8")
        for marker in (
            "Review status：`PENDING_INDEPENDENT_REVIEW`",
            "Decision：`PENDING`",
            "Reviewer: SAME INDEPENDENT REVIEWER ASSIGNED FOR CANDIDATE.5 REREVIEW",
        ):
            if marker not in review_text:
                errors.append(f"FREEZE_REVIEW candidate state missing: {marker}")

    author_preflight = bundle / "AUTHOR_PREFLIGHT.md"
    if author_preflight.is_file():
        preflight_text = author_preflight.read_text(encoding="utf-8")
        for marker in (
            "Review type：`AUTHOR_PREFLIGHT_NOT_INDEPENDENT`",
            "Result：`CANDIDATE.5_REMEDIATED_READY_FOR_REREVIEW`",
            "Independent reviewer: SAME REVIEWER ASSIGNED FOR REREVIEW",
            "Independent decision: PENDING",
            "AF-09: PENDING_INDEPENDENT_REVIEW",
        ):
            if marker not in preflight_text:
                errors.append(f"AUTHOR_PREFLIGHT boundary missing: {marker}")

    crosswalk_path = bundle / "crosswalk.json"
    if crosswalk_path.is_file():
        try:
            crosswalk_data = json.loads(crosswalk_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"crosswalk.json cannot be parsed: {exc}")
        else:
            errors.extend(validate_crosswalk(crosswalk_data, project))

    manifest_path = bundle / "architecture_manifest.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"architecture_manifest.json cannot be parsed: {exc}")
        else:
            errors.extend(validate_manifest(manifest_data, crosswalk_data))

    return errors


def main() -> int:
    errors = collect_errors()
    if errors:
        print("MiLAi architecture bundle validation: FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("MiLAi architecture bundle validation: PASS (candidate, not frozen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
