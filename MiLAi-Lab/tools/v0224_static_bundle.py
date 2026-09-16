"""R03 fixed static bundle format and draft sealer; never independent approval.

Fresh dynamic roles are excluded from static payload membership. Original paths
are validated by the original scoped validator before sealing; a runtime bundle
changes authority and does not claim unchanged per-path R02 freshness.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

MAGIC = b"MILA-BUNDLE-V1\n"
FORMAT_REVISION = "V0224_STATIC_BUNDLE_V1"
_HEX = re.compile(r"[0-9a-f]{64}")


class StaticBundleError(ValueError):
    """A bundle cannot establish its explicitly bounded static authority."""


@dataclass(frozen=True)
class BundleLimits:
    max_header_bytes: int
    max_payload_bytes: int
    max_paths: int
    max_blobs: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise StaticBundleError("POSITIVE_INTEGER_BUNDLE_LIMITS_REQUIRED")


def canonical_json(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _require(condition, reason):
    if not condition:
        raise StaticBundleError(reason)


def _path(value):
    _require(type(value) is str and "\x00" not in value, "CANONICAL_ABSOLUTE_PATH_REQUIRED")
    path = Path(value)
    _require(
        path.is_absolute()
        and str(path) == value
        and path.parts[0] == "/"
        and ".." not in path.parts,
        "CANONICAL_ABSOLUTE_PATH_REQUIRED",
    )
    return value


def _digest(value):
    _require(type(value) is str and _HEX.fullmatch(value) is not None, "EXACT_SHA256_REQUIRED")
    return value


def _pairs(items):
    value = {}
    for key, item in items:
        _require(key not in value, "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _constant(value):
    raise StaticBundleError("NONFINITE_JSON_NUMBER")


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class BundleIndex:
    format_revision: str
    roots: tuple
    files: Mapping
    blobs: Mapping
    manifest_env: Mapping
    payload_offset: int
    bundle_sha256: str
    _source: bytes

    def member_bytes(self, path, expected_sha256):
        return entry_bytes(self._source, self, path, expected_sha256)


def _roots(rows):
    _require(type(rows) is list and bool(rows), "EXPLICIT_PROOF_ROOTS_REQUIRED")
    seen = set()
    for row in rows:
        _require(
            type(row) is dict and set(row) == {"path", "sha256", "purpose"},
            "EXACT_PROOF_ROOT_REQUIRED",
        )
        _path(row["path"])
        _digest(row["sha256"])
        _require(
            row["purpose"] == "STATIC_TREE" and row["path"] not in seen,
            "DISTINCT_STATIC_TREE_ROOTS_REQUIRED",
        )
        seen.add(row["path"])


def _packages(value):
    _require(type(value) is dict, "PACKAGES_MAPPING_REQUIRED")
    for key, version in value.items():
        _require(
            type(key) is str and bool(key) and type(version) is str and bool(version),
            "PACKAGE_NAME_VERSION_STRINGS_REQUIRED",
        )


def _environment(value, files):
    _require(
        type(value) is dict and set(value) == {"python", "packages", "sources"},
        "EXACT_MANIFEST_ENVIRONMENT_REQUIRED",
    )
    _require(type(value["python"]) is str and bool(value["python"]), "PYTHON_VERSION_REQUIRED")
    _packages(value["packages"])
    _require(type(value["sources"]) is dict, "COMPLETE_MANIFEST_SOURCE_MAP_REQUIRED")
    merged = {}
    for path, source in value["sources"].items():
        _path(path)
        _require(
            type(source) is dict and set(source) == {"sha256", "python", "packages"},
            "EXACT_MANIFEST_ENVIRONMENT_SOURCE_REQUIRED",
        )
        _digest(source["sha256"])
        _require(path not in files or files[path] == source["sha256"], "MANIFEST_SOURCE_PIN_DRIFT")
        _require(source["python"] == value["python"], "CONFLICTING_PYTHON_REQUIREMENTS")
        _packages(source["packages"])
        for name, version in source["packages"].items():
            _require(
                name not in merged or merged[name] == version, "CONFLICTING_PACKAGE_REQUIREMENTS"
            )
            merged[name] = version
    _require(merged == value["packages"], "INCOMPLETE_OR_EXTRA_PACKAGE_REQUIREMENTS")


def parse_bundle(raw: bytes, limits: BundleLimits) -> BundleIndex:
    """Validate complete canonical header and every unique payload blob, no IO."""
    _require(type(raw) is bytes and isinstance(limits, BundleLimits), "BYTES_AND_LIMITS_REQUIRED")
    prefix_size = len(MAGIC) + 8
    _require(len(raw) >= prefix_size and raw.startswith(MAGIC), "BUNDLE_MAGIC_OR_LENGTH_INVALID")
    header_size = int.from_bytes(raw[len(MAGIC) : prefix_size], "big")
    _require(0 < header_size <= limits.max_header_bytes, "BUNDLE_HEADER_LIMIT")
    payload_offset = prefix_size + header_size
    _require(payload_offset <= len(raw), "TRUNCATED_BUNDLE_HEADER")
    _require(len(raw) - payload_offset <= limits.max_payload_bytes, "BUNDLE_PAYLOAD_LIMIT")
    header_bytes = raw[prefix_size:payload_offset]
    header = json.loads(
        header_bytes.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
    )
    _require(
        type(header) is dict
        and set(header) == {"format_revision", "roots", "files", "blobs", "manifest_env"},
        "EXACT_BUNDLE_HEADER_REQUIRED",
    )
    _require(header["format_revision"] == FORMAT_REVISION, "UNSUPPORTED_BUNDLE_FORMAT")
    _require(canonical_json(header) == header_bytes, "CANONICAL_BUNDLE_HEADER_REQUIRED")
    _roots(header["roots"])
    files, blobs = header["files"], header["blobs"]
    _require(type(files) is dict and 0 < len(files) <= limits.max_paths, "BUNDLE_PATH_COUNT_LIMIT")
    _require(type(blobs) is dict and 0 < len(blobs) <= limits.max_blobs, "BUNDLE_BLOB_COUNT_LIMIT")
    for path, digest in files.items():
        _path(path)
        _digest(digest)
    _require(set(files.values()) == set(blobs), "EXACT_REFERENCED_BLOB_SET_REQUIRED")
    for root in header["roots"]:
        _require(
            root["path"] not in files or files[root["path"]] == root["sha256"],
            "ROOT_MEMBER_PIN_DRIFT",
        )
    cursor = 0
    for digest in sorted(blobs):
        _digest(digest)
        bounds = blobs[digest]
        _require(
            type(bounds) is dict and set(bounds) == {"offset", "length"},
            "EXACT_BLOB_BOUNDS_REQUIRED",
        )
        offset, length = bounds["offset"], bounds["length"]
        _require(
            type(offset) is int and type(length) is int and offset == cursor and length >= 0,
            "CONTIGUOUS_SORTED_BLOB_LAYOUT_REQUIRED",
        )
        stop = payload_offset + offset + length
        _require(stop <= len(raw), "BLOB_OUTSIDE_PAYLOAD")
        view = memoryview(raw)[payload_offset + offset : stop]
        _require(hashlib.sha256(view).hexdigest() == digest, "BLOB_SHA256_MISMATCH")
        cursor += length
    _require(payload_offset + cursor == len(raw), "UNREFERENCED_PAYLOAD_OR_PADDING")
    _environment(header["manifest_env"], files)
    return BundleIndex(
        FORMAT_REVISION,
        _freeze(header["roots"]),
        _freeze(files),
        _freeze(blobs),
        _freeze(header["manifest_env"]),
        payload_offset,
        hashlib.sha256(raw).hexdigest(),
        raw,
    )


def entry_bytes(raw: bytes, index: BundleIndex, path, expected_sha256: str) -> bytes:
    """Return original bytes only from the exact immutable buffer already parsed."""
    _require(type(index) is BundleIndex and raw is index._source, "INDEX_SOURCE_IDENTITY_MISMATCH")
    name = _path(str(path))
    _digest(expected_sha256)
    _require(index.files.get(name) == expected_sha256, "STATIC_MEMBER_OR_PIN_MISMATCH")
    bounds = index.blobs[expected_sha256]
    start = index.payload_offset + bounds["offset"]
    return raw[start : start + bounds["length"]]


def _fresh_roles(value):
    _require(type(value) is dict, "EXPLICIT_FRESH_ROLES_REQUIRED")
    for path, row in value.items():
        _path(path)
        _require(type(row) is dict and set(row) == {"sha256", "roles"}, "EXACT_FRESH_ROLE_REQUIRED")
        _digest(row["sha256"])
        _require(
            type(row["roles"]) is list
            and bool(row["roles"])
            and all(type(role) is str and bool(role) for role in row["roles"])
            and row["roles"] == sorted(set(row["roles"])),
            "SORTED_DISTINCT_FRESH_ROLES_REQUIRED",
        )


def seal_static_bundle(
    output_directory: Path, *, roots: list, fresh_roles: dict, limits: BundleLimits
) -> dict:
    """Validate original paths, seal once, write an unapproved candidate receipt.

    Writes static.bundle, candidate-receipt.json and seal-observation.json. Never
    accepts a PASS boolean/validator callback or manufactures independent approval.
    Any failure consumes the fresh output directory and records its actual cause.
    """
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    from v0220_evidence import dependencies
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_scoped_evidence import verify_tree

    output = Path(output_directory)
    _require(
        output.resolve() == output and not output.exists() and not output.is_symlink(),
        "FRESH_CANONICAL_SEAL_DIRECTORY_REQUIRED",
    )
    output.mkdir(parents=True, exist_ok=False)
    try:
        _roots(roots)
        _fresh_roles(fresh_roles)
        # Detach caller-owned containers; their later mutation cannot rewrite pins.
        roles = json.loads(canonical_json(fresh_roles))
        proof_roots = json.loads(canonical_json(roots))
        verifier_files = {}
        for path in dependencies([Path(__file__)]):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            name = str(path)
            verifier_files[name] = digest
            if name in roles:
                _require(roles[name]["sha256"] == digest, "VERIFIER_FRESH_PIN_CONFLICT")
                roles[name]["roles"] = sorted(set(roles[name]["roles"]) | {"SEAL_VERIFIER"})
            else:
                roles[name] = {"sha256": digest, "roles": ["SEAL_VERIFIER"]}
        environment = {"python": platform.python_version(), "packages": {}, "sources": {}}
        with AdmissionReadScope() as scope:
            for root in proof_roots:
                verify_tree(scope, Path(root["path"]), root["sha256"])
            for path, row in roles.items():
                scope.read_bytes(Path(path), row["sha256"])
            observed = {}
            for path, entry in scope._entries.items():
                _require(entry.data is not None, "OBSERVED_SOURCE_BYTES_REQUIRED")
                observed[str(path)] = {"sha256": entry.expected, "data": entry.data}
                value = entry.parsed
                if (
                    path.name == "manifest.json"
                    and isinstance(value, dict)
                    and all(
                        name in value for name in ("dependencies", "inputs", "python", "packages")
                    )
                ):
                    environment["sources"][str(path)] = {
                        "sha256": entry.expected,
                        "python": value["python"],
                        "packages": value["packages"],
                    }
                    for name, version in value["packages"].items():
                        _require(
                            name not in environment["packages"]
                            or environment["packages"][name] == version,
                            "CONFLICTING_PACKAGE_REQUIREMENTS",
                        )
                        environment["packages"][name] = version
        original_stats = scope.stats
        _require(scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS", "ORIGINAL_SCOPE_NOT_CLOSED")
        members = {path: row for path, row in observed.items() if path not in roles}
        unique = {}
        for row in members.values():
            old = unique.setdefault(row["sha256"], row["data"])
            _require(old == row["data"], "SAME_DIGEST_DIFFERENT_BYTES")
        blobs, chunks, cursor = {}, [], 0
        for digest in sorted(unique):
            data = unique[digest]
            blobs[digest] = {"offset": cursor, "length": len(data)}
            chunks.append(data)
            cursor += len(data)
        header = {
            "format_revision": FORMAT_REVISION,
            "roots": proof_roots,
            "files": {path: row["sha256"] for path, row in members.items()},
            "blobs": blobs,
            "manifest_env": environment,
        }
        _require(isinstance(limits, BundleLimits), "BYTES_AND_LIMITS_REQUIRED")
        _require(0 < len(members) <= limits.max_paths, "BUNDLE_PATH_COUNT_LIMIT")
        _require(0 < len(unique) <= limits.max_blobs, "BUNDLE_BLOB_COUNT_LIMIT")
        _require(cursor <= limits.max_payload_bytes, "BUNDLE_PAYLOAD_LIMIT")
        header_bytes = canonical_json(header)
        _require(len(header_bytes) <= limits.max_header_bytes, "BUNDLE_HEADER_LIMIT")
        raw = MAGIC + len(header_bytes).to_bytes(8, "big") + header_bytes + b"".join(chunks)
        index = parse_bundle(raw, limits)
        for path, row in members.items():
            _require(
                entry_bytes(raw, index, path, row["sha256"]) == row["data"],
                "SEALED_MEMBER_BYTES_CHANGED",
            )
        bundle_path = output / "static.bundle"
        with bundle_path.open("xb") as stream:
            stream.write(raw)
        persisted = bundle_path.read_bytes()
        _require(persisted == raw, "PERSISTED_BUNDLE_DRIFT")
        parse_bundle(persisted, limits)
        candidate = {
            "status": "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED",
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
            "format_revision": FORMAT_REVISION,
            "verifier_files": verifier_files,
            "proof_roots": proof_roots,
            "fresh_roles": roles,
            "environment": {key: environment[key] for key in ("python", "packages")},
            "classification_digest": hashlib.sha256(canonical_json(roles)).hexdigest(),
        }
        with (output / "seal-observation.json").open("xb") as stream:
            stream.write(
                canonical_json(
                    {
                        "status": (
                            "ORIGINAL_STATIC_VALIDATION_AND_BUNDLE_BYTES_CHECKED_"
                            "NOT_INDEPENDENT_APPROVAL"
                        ),
                        "observed_files": {path: row["sha256"] for path, row in observed.items()},
                        "static_logical_paths": len(members),
                        "static_logical_bytes": sum(len(row["data"]) for row in members.values()),
                        "unique_blobs": len(unique),
                        "unique_payload_bytes": cursor,
                        "physical_bundle_bytes": len(raw),
                        "original_scope_stats": original_stats,
                        "manifest_environment_sources": environment["sources"],
                    }
                )
            )
        with (output / "candidate-receipt.json").open("xb") as stream:
            stream.write(canonical_json(candidate))
        return candidate
    except BaseException as primary:
        try:
            with (output / "seal-failure.json").open("xb") as stream:
                stream.write(
                    canonical_json(
                        {
                            "status": "STATIC_BUNDLE_SEAL_FAILED",
                            "exception_type": type(primary).__name__,
                            "reason": str(primary),
                        }
                    )
                )
        except BaseException as secondary:
            primary.add_note("SECONDARY_SEAL_FAILURE_RECORD_ERROR: " + repr(secondary))
        raise
