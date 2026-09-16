"""Export committed scoped records as byte-verifiable, non-executable artifacts.

The caller must verify SQLite/operation provenance separately. Export is not a
publication, build, training run, or proof that supplied source code is correct.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from v0219_record_check import content_hash


def artifact_bytes(state: dict, mapping: dict) -> dict[str, bytes]:
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("ARTIFACT_MAPPING_REQUIRED")
    result = {}
    for target, spec in mapping.items():
        name = spec.get("path")
        if (not isinstance(name, str) or not name or "\\" in name or "\x00" in name
                or ":" in name or name.startswith("/")
                or any(part in {"", ".", "..", ".git"} for part in name.split("/"))):
            raise ValueError("UNSAFE_ARTIFACT_PATH")
        if str(PurePosixPath(name)) != name or name in result:
            raise ValueError("DUPLICATE_OR_NONCANONICAL_ARTIFACT_PATH")
        row = state.get("records", {}).get(target)
        if (target not in state.get("objects", []) or not isinstance(row, dict)
                or row.get("object_id") != target):
            raise ValueError("COMMITTED_ARTIFACT_RECORD_MISSING")
        if spec.get("format") == "text":
            value = row.get(spec.get("field", "content"))
            if not isinstance(value, str) or not value.strip():
                raise ValueError("ARTIFACT_CONTENT_REQUIRED")
            result[name] = value.encode("utf-8")
        elif spec.get("format") == "json":
            result[name] = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                      indent=2, allow_nan=False).encode("utf-8")
        else:
            raise ValueError("UNKNOWN_ARTIFACT_FORMAT")
    for name in result:
        if any(str(parent) in result for parent in PurePosixPath(name).parents):
            raise ValueError("ARTIFACT_FILE_DIRECTORY_COLLISION")
    return result


def export_artifacts(state: dict, mapping: dict, directory: Path) -> dict:
    values = artifact_bytes(state, mapping)
    if not directory.is_absolute() or directory.is_symlink() or directory.exists():
        raise ValueError("FRESH_ABSOLUTE_ARTIFACT_DIRECTORY_REQUIRED")
    if any(parent.is_symlink() for parent in directory.parents):
        raise ValueError("ARTIFACT_PARENT_SYMLINK")
    directory.mkdir(parents=True, exist_ok=False)
    for name, raw in values.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    expected = {name: hashlib.sha256(raw).hexdigest() for name, raw in values.items()}
    if any(hashlib.sha256((directory / name).read_bytes()).hexdigest() != sha
           for name, sha in expected.items()):
        raise ValueError("EXPORTED_ARTIFACT_BYTES_CHANGED")
    return {"status": "SCOPED_RECORD_ARTIFACTS_EXPORTED", "scope": state.get("scope"),
            "world_version": state.get("version"), "state_sha256": content_hash(state),
            "mapping_sha256": content_hash(mapping), "files": expected,
            "files_executed": False, "external_publication": False,
            "execution_proven_by_exporter": False}
