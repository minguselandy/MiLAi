"""Independent mechanical replay of candidate static semantics, never approval.

This tool accepts external pins for unapproved candidate artifacts and its own
verifier dependency closure. It never opens an APPROVED runtime receipt or uses
the runtime shortcut. Original verify_tree/read_json execute against bundle
member bytes and physically fresh role bytes in a private replay scope.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
from pathlib import Path

from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope, _Entry
from v0222_scoped_evidence import _strict_json, verify_tree
from v0224_static_bundle import BundleLimits, canonical_json, entry_bytes, parse_bundle


class BundleRevalidationError(ValueError):
    """The candidate cannot establish the declared mechanical static proof."""


def _require(condition, message):
    if not condition:
        raise BundleRevalidationError(message)


def _path(value):
    _require(type(value) is str and "\x00" not in value, "CANONICAL_INPUT_PATH_REQUIRED")
    path = Path(value)
    _require(
        path.is_absolute()
        and str(path) == value
        and path.parts[0] == "/"
        and ".." not in path.parts,
        "CANONICAL_INPUT_PATH_REQUIRED",
    )
    return path


def _digest(value):
    _require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "EXACT_EXTERNAL_SHA256_REQUIRED",
    )
    return value


def _plain(value):
    from collections.abc import Mapping

    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


class _ReplayScope(AdmissionReadScope):
    """Private data adapter; public original parser/copy and guard are unchanged."""

    def __init__(self, raw, index, roles):
        super().__init__()
        self.raw, self.index, self.roles = raw, index, roles
        self.virtual = {}
        self.logical = {}

    def _entry(self, path, expected_sha256):
        self._active()
        try:
            _digest(expected_sha256)
            supplied = Path(os.fspath(path))
            if ".." in supplied.parts:
                raise AdmissionReadError("PARENT_TRAVERSAL_NOT_SUPPORTED")
            canonical = Path(os.path.abspath(supplied))
            name = str(canonical)
            previous = self.logical.get(name)
            if previous is not None and previous.expected != expected_sha256:
                raise AdmissionReadError("CONFLICTING_EXPECTED_FILE_HASH")
            if name in self.roles:
                _require(
                    self.roles[name]["sha256"] == expected_sha256, "REPLAY_FRESH_ROLE_HASH_CONFLICT"
                )
            if name in self.roles or name not in self.index.files:
                entry = super()._entry(canonical, expected_sha256)
            elif canonical in self.virtual:
                self._stats["repeat_references"] += 1
                entry = self.virtual[canonical]
            else:
                entry = _Entry(
                    expected=expected_sha256,
                    data=entry_bytes(self.raw, self.index, name, expected_sha256),
                )
                self.virtual[canonical] = entry
            self.logical[name] = entry
            return entry
        except BaseException as exc:
            self._poison(exc)
            raise

    def _close(self, body_error=None):
        try:
            return super()._close(body_error)
        finally:
            self.virtual.clear()


def _candidate(candidate, index, bundle_sha256):
    fields = {
        "status",
        "bundle_sha256",
        "format_revision",
        "verifier_files",
        "proof_roots",
        "fresh_roles",
        "environment",
        "classification_digest",
    }
    _require(
        type(candidate) is dict and set(candidate) == fields, "EXACT_UNAPPROVED_CANDIDATE_REQUIRED"
    )
    _require(
        candidate["status"] == "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED",
        "DRAFT_CANDIDATE_REQUIRED_NO_APPROVED_RECEIPT",
    )
    _require(
        candidate["bundle_sha256"] == bundle_sha256
        and candidate["format_revision"] == index.format_revision,
        "CANDIDATE_BUNDLE_FORMAT_OR_HASH_DRIFT",
    )
    _require(candidate["proof_roots"] == _plain(index.roots), "EXACT_CANDIDATE_ROOTS_REQUIRED")
    roles = candidate["fresh_roles"]
    _require(type(roles) is dict, "EXPLICIT_CANDIDATE_FRESH_ROLES_REQUIRED")
    for name, row in roles.items():
        _path(name)
        _require(type(row) is dict and set(row) == {"sha256", "roles"}, "EXACT_FRESH_ROLE_ROW")
        _digest(row["sha256"])
        labels = row["roles"]
        _require(
            type(labels) is list
            and bool(labels)
            and all(type(label) is str and bool(label) for label in labels)
            and labels == sorted(set(labels)),
            "SORTED_DISTINCT_FRESH_ROLE_LABELS_REQUIRED",
        )
    _require(not set(roles) & set(index.files), "STATIC_AND_FRESH_CLASSIFICATIONS_OVERLAP")
    _require(
        hashlib.sha256(canonical_json(roles)).hexdigest() == candidate["classification_digest"],
        "CANDIDATE_CLASSIFICATION_DIGEST_DRIFT",
    )
    verifiers = candidate["verifier_files"]
    _require(type(verifiers) is dict and bool(verifiers), "CANDIDATE_VERIFIER_PINS_REQUIRED")
    for name, digest in verifiers.items():
        _path(name)
        _digest(digest)
        _require(name in roles and roles[name]["sha256"] == digest, "CANDIDATE_VERIFIER_NOT_FRESH")
    _require(
        candidate["environment"]
        == {key: _plain(index.manifest_env[key]) for key in ("python", "packages")},
        "CANDIDATE_ENVIRONMENT_DRIFT",
    )
    return roles


def revalidate_candidate(
    output_directory,
    *,
    candidate_path,
    candidate_sha256,
    bundle_path,
    bundle_sha256,
    observation_path,
    observation_sha256,
    verifier_files,
    limits,
):
    """Write only a mechanical result after both physical read scopes close.

    All expected hashes are supplied externally. No real fixture or measurement
    is authorized by this function; callers must separately approve that work.
    """
    from v0222_scoped_cpu_guard import require_cpu_network_guard

    require_cpu_network_guard()
    from v0220_evidence import dependencies

    output = _path(str(output_directory))
    _require(
        output.resolve() == output and not output.exists() and not output.is_symlink(),
        "FRESH_REVALIDATION_OUTPUT_REQUIRED",
    )
    output.mkdir(parents=True, exist_ok=False)
    try:
        _require(isinstance(limits, BundleLimits), "FIXED_BUNDLE_LIMITS_REQUIRED")
        expected_sources = {str(path) for path in dependencies([Path(__file__).resolve()])}
        _require(
            type(verifier_files) is dict and set(verifier_files) == expected_sources,
            "COMPLETE_REVALIDATOR_SOURCE_PINS_REQUIRED",
        )
        controls = [
            (candidate_path, candidate_sha256),
            (bundle_path, bundle_sha256),
            (observation_path, observation_sha256),
        ]
        paths = [_path(str(path)) for path, _ in controls]
        _require(
            len(set(paths)) == 3 and not set(map(str, paths)) & set(verifier_files),
            "DISTINCT_EXTERNAL_CONTROL_INPUTS_REQUIRED",
        )
        for _, digest in controls:
            _digest(digest)
        for name, digest in verifier_files.items():
            _path(name)
            _digest(digest)
        with AdmissionReadScope() as physical:
            for name, digest in verifier_files.items():
                physical.read_bytes(Path(name), digest)
            candidate_raw, raw, observed_raw = [
                physical.read_bytes(path, digest)
                for path, (_, digest) in zip(paths, controls, strict=True)
            ]
            candidate = _strict_json(candidate_raw.decode("utf-8"))
            observed = _strict_json(observed_raw.decode("utf-8"))
            index = parse_bundle(raw, limits)
            roles = _candidate(candidate, index, bundle_sha256)
            _require(
                observed["status"]
                == "ORIGINAL_STATIC_VALIDATION_AND_BUNDLE_BYTES_CHECKED_NOT_INDEPENDENT_APPROVAL",
                "ORIGINAL_SEAL_OBSERVATION_REQUIRED",
            )
            expected_logical = {
                **dict(index.files),
                **{name: row["sha256"] for name, row in roles.items()},
            }
            _require(
                observed["observed_files"] == expected_logical,
                "ORIGINAL_OBSERVATION_CLASSIFICATION_COVERAGE_DRIFT",
            )
            _require(
                not set(map(str, paths)) & set(expected_logical),
                "AUTHORITY_CANNOT_BE_ITS_OWN_SOURCE_PROOF",
            )
            with _ReplayScope(raw, index, roles) as replay:
                # Original algorithm, parser and environment checks, no root shortcut.
                for root in candidate["proof_roots"]:
                    verify_tree(replay, Path(root["path"]), root["sha256"])
                # The sealer also reads every fresh role, including verifier-only files.
                for name, row in roles.items():
                    replay.read_bytes(Path(name), row["sha256"])
                actual_logical = {name: entry.expected for name, entry in replay.logical.items()}
                _require(actual_logical == expected_logical, "REPLAY_LOGICAL_CLOSURE_DRIFT")
                _require(
                    set(map(str, replay.virtual)) == set(index.files),
                    "UNVISITED_STATIC_MEMBER_OR_OMITTED_TREE_EDGE",
                )
                environment = {
                    "python": platform.python_version(),
                    "packages": {},
                    "sources": {},
                }
                for name, entry in replay.logical.items():
                    value = entry.parsed
                    if (
                        Path(name).name == "manifest.json"
                        and isinstance(value, dict)
                        and all(
                            key in value for key in ("dependencies", "inputs", "python", "packages")
                        )
                    ):
                        environment["sources"][name] = {
                            "sha256": entry.expected,
                            "python": value["python"],
                            "packages": value["packages"],
                        }
                        for package, version in value["packages"].items():
                            _require(
                                package not in environment["packages"]
                                or environment["packages"][package] == version,
                                "REPLAY_ENVIRONMENT_REQUIREMENTS_CONFLICT",
                            )
                            environment["packages"][package] = version
                _require(
                    environment == _plain(index.manifest_env)
                    and environment["sources"] == observed["manifest_environment_sources"],
                    "COMPLETE_MANIFEST_ENVIRONMENT_REPLAY_DRIFT",
                )
                static_bytes = sum(
                    len(entry.data) for name, entry in replay.logical.items() if name in index.files
                )
                logical_bytes = sum(len(entry.data) for entry in replay.logical.values())
                _require(
                    observed["static_logical_paths"] == len(index.files)
                    and observed["static_logical_bytes"] == static_bytes
                    and observed["unique_blobs"] == len(index.blobs)
                    and observed["unique_payload_bytes"] == len(raw) - index.payload_offset
                    and observed["physical_bundle_bytes"] == len(raw),
                    "ORIGINAL_SEAL_VOLUME_DRIFT",
                )
                old_stats = observed["original_scope_stats"]
                _require(
                    old_stats["first_reads"] == old_stats["closing_reads"] == len(expected_logical)
                    and old_stats["first_hashes"]
                    == old_stats["closing_hashes"]
                    == len(expected_logical)
                    and old_stats["first_bytes"] == old_stats["closing_bytes"] == logical_bytes
                    and old_stats["json_parses"] == replay.stats["json_parses"]
                    and old_stats["repeat_references"] == replay.stats["repeat_references"],
                    "ORIGINAL_LOGICAL_STATS_REPLAY_DRIFT",
                )
            _require(
                replay.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS", "REPLAY_FRESH_SCOPE_NOT_CLOSED"
            )
            logical_stats = dict(replay.stats)
            for phase in ("first", "closing"):
                for kind in ("read_attempts", "reads", "hashes"):
                    logical_stats[phase + "_" + kind] = len(expected_logical)
                logical_stats[phase + "_bytes"] = logical_bytes
            _require(
                all(type(value) is int for value in old_stats.values())
                and old_stats == logical_stats,
                "EXACT_ORIGINAL_LOGICAL_STATS_REQUIRED",
            )
            physical_files = {
                str(path): entry.expected for path, entry in physical._entries.items()
            }
        _require(
            physical.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS",
            "EXTERNAL_AUTHORITY_SCOPE_NOT_CLOSED",
        )
        result = {
            "status": "MECHANICAL_STATIC_REVALIDATION_COMPLETE_NOT_APPROVAL",
            "runtime_authorized": False,
            "candidate_status": candidate["status"],
            "files": {**physical_files, **{name: row["sha256"] for name, row in roles.items()}},
            "proof_roots": candidate["proof_roots"],
            "classification_digest": candidate["classification_digest"],
            "bundle_sha256": bundle_sha256,
            "manifest_environment": environment,
            "logical_files": actual_logical,
            "static_logical_paths": len(index.files),
            "static_logical_bytes": static_bytes,
            "replay_physical_stats": replay.stats,
            "external_control_physical_stats": physical.stats,
            "original_scope_stats": old_stats,
            "logical_replay_stats": logical_stats,
            "meaning": "Original verify_tree semantics replayed, not just blob equality. "
            "Virtual member IO is logical; fresh roles and external inputs have "
            "physical first/close observations. Independent approval remains external.",
        }
        with (output / "mechanical-revalidation.json").open("xb") as stream:
            stream.write(canonical_json(result))
        return result
    except BaseException as primary:
        try:
            with (output / "revalidation-failure.json").open("xb") as stream:
                stream.write(
                    canonical_json(
                        {
                            "status": "MECHANICAL_REVALIDATION_FAILED",
                            "exception_type": type(primary).__name__,
                            "reason": str(primary),
                        }
                    )
                )
        except BaseException as secondary:
            primary.add_note("SECONDARY_REVALIDATION_RECORD_FAILURE: " + repr(secondary))
        raise
