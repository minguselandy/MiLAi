"""R04 same-scope verified digest reuse; original dynamic paths retain physical reads.

Synthetic development interface, not an admission certificate. Expected package
and independent receipt hashes must come from an external frozen caller contract.
No original module aliases or public readers are patched.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import threading
from contextlib import contextmanager
from pathlib import Path

from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope, _Entry
from v0222_scoped_evidence import _strict_json, verify_tree
from v0224_static_bundle import entry_bytes


class BundleReadError(AdmissionReadError):
    """The newly declared authority or its retained live obligations failed."""


def _canonical(value):
    if type(value) is not str or not Path(value).is_absolute() or str(Path(value)) != value:
        raise BundleReadError("CANONICAL_ABSOLUTE_AUTHORITY_PATH_REQUIRED")
    if ".." in Path(value).parts:
        raise BundleReadError("PARENT_TRAVERSAL_NOT_SUPPORTED")
    return Path(value)


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BundleReadError("EXACT_LOWERCASE_SHA256_REQUIRED")
    return value


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class BundleReadScope(AdmissionReadScope):
    """A fresh package and receipt observation for exactly one owner scope.

    Physical entries remain in the original close registry. Virtual entries have
    a separate registry and never pretend to be fresh observations of old paths.
    A physical-read context permanently promotes each path actually encountered;
    it does not pre-read dependencies or reorder the delegated validator.
    """

    def __init__(self, *, bundle_path, bundle_sha256, receipt_path, receipt_sha256, limits):
        super().__init__()
        self._owner = (os.getpid(), threading.get_ident())
        self._bundle_path = _canonical(str(bundle_path))
        self._receipt_path = _canonical(str(receipt_path))
        if self._bundle_path == self._receipt_path:
            raise BundleReadError("DISTINCT_EXTERNAL_AUTHORITY_FILES_REQUIRED")
        self._bundle_sha = _digest(bundle_sha256)
        self._receipt_sha = _digest(receipt_sha256)
        self._limits = limits
        self._authority = None
        self._index = None
        self._receipt = None
        self._virtual_entries = {}
        self._promoted = set()
        self._physical_depth = 0
        self._logical = {"member_reads": 0, "member_bytes": 0, "proof_uses": 0, "promotions": 0}

    def _active(self):
        super()._active()
        if self._owner != (os.getpid(), threading.get_ident()):
            exc = BundleReadError("BUNDLE_SCOPE_OWNER_DRIFT")
            self._poison(exc)
            raise exc

    @property
    def authority_stats(self):
        return {**self._logical, "authority_revision": "R03_BUNDLE_AUTHORITY"}

    def _parse_current_authority_bundle(self):
        """R04: reuse only this original physical entry's freshly verified SHA.

        No caller-supplied raw, digest, entry or transferable verification token.
        All original parser statements run; only its final duplicate SHA is omitted.
        Extra witness checks/local frames are not resource-exception equivalence.
        """
        from v0224_static_bundle import (
            FORMAT_REVISION,
            MAGIC,
            BundleIndex,
            BundleLimits,
            _constant,
            _digest,
            _environment,
            _freeze,
            _pairs,
            _path,
            _require,
            _roots,
            canonical_json,
        )

        try:
            self._active()
            if type(self) is not BundleReadScope or not self._entered:
                raise BundleReadError("ENTERED_CONCRETE_DIGEST_SCOPE_REQUIRED")
            witness_path, witness_expected = self._bundle_path, self._bundle_sha
            physical = AdmissionReadScope._entry(self, witness_path, witness_expected)
            raw, identity = physical.data, physical.identity
            limits = self._limits

            def verified_digest():
                self._active()
                if (
                    type(self) is not BundleReadScope
                    or not self._entered
                    or self._bundle_path != witness_path
                    or self._bundle_sha != witness_expected
                    or self._entries.get(witness_path) is not physical
                    or physical.expected != witness_expected
                    or type(raw) is not bytes
                    or physical.data is not raw
                    or identity is None
                    or physical.identity != identity
                ):
                    raise BundleReadError("CURRENT_PHYSICAL_DIGEST_WITNESS_REQUIRED")
                return witness_expected

            verified_digest()
            _require(
                type(raw) is bytes and isinstance(limits, BundleLimits), "BYTES_AND_LIMITS_REQUIRED"
            )
            prefix_size = len(MAGIC) + 8
            _require(
                len(raw) >= prefix_size and raw.startswith(MAGIC), "BUNDLE_MAGIC_OR_LENGTH_INVALID"
            )
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
            (files, blobs) = (header["files"], header["blobs"])
            _require(
                type(files) is dict and 0 < len(files) <= limits.max_paths,
                "BUNDLE_PATH_COUNT_LIMIT",
            )
            _require(
                type(blobs) is dict and 0 < len(blobs) <= limits.max_blobs,
                "BUNDLE_BLOB_COUNT_LIMIT",
            )
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
                (offset, length) = (bounds["offset"], bounds["length"])
                _require(
                    type(offset) is int
                    and type(length) is int
                    and (offset == cursor)
                    and (length >= 0),
                    "CONTIGUOUS_SORTED_BLOB_LAYOUT_REQUIRED",
                )
                stop = payload_offset + offset + length
                _require(stop <= len(raw), "BLOB_OUTSIDE_PAYLOAD")
                view = memoryview(raw)[payload_offset + offset : stop]
                _require(hashlib.sha256(view).hexdigest() == digest, "BLOB_SHA256_MISMATCH")
                cursor += length
            _require(payload_offset + cursor == len(raw), "UNREFERENCED_PAYLOAD_OR_PADDING")
            _environment(header["manifest_env"], files)
            return (
                physical,
                BundleIndex(
                    FORMAT_REVISION,
                    _freeze(header["roots"]),
                    _freeze(files),
                    _freeze(blobs),
                    _freeze(header["manifest_env"]),
                    payload_offset,
                    verified_digest(),
                    raw,
                ),
            )
        except BaseException as primary:
            self._poison(primary)
            raise

    def _ensure_authority(self):
        self._active()
        if self._authority is not None:
            return
        try:
            # Never ask a package or an unchecked receipt for its own trusted hash.
            receipt_entry = super()._entry(self._receipt_path, self._receipt_sha)
            receipt = _strict_json(receipt_entry.data.decode("utf-8"))
            expected_fields = {
                "status",
                "bundle_sha256",
                "format_revision",
                "verifier_files",
                "proof_roots",
                "fresh_roles",
                "environment",
                "classification_digest",
            }
            if type(receipt) is not dict or set(receipt) != expected_fields:
                raise BundleReadError("EXACT_EXTERNAL_RECEIPT_REQUIRED")
            if receipt["status"] != "INDEPENDENT_STATIC_BUNDLE_APPROVED":
                raise BundleReadError("INDEPENDENT_STATIC_APPROVAL_REQUIRED")
            if receipt["bundle_sha256"] != self._bundle_sha:
                raise BundleReadError("RECEIPT_BUNDLE_BINDING_MISMATCH")
            roles = receipt["fresh_roles"]
            if type(roles) is not dict:
                raise BundleReadError("EXACT_FRESH_ROLES_REQUIRED")
            for name, row in roles.items():
                _canonical(name)
                if type(row) is not dict or set(row) != {"sha256", "roles"}:
                    raise BundleReadError("EXACT_FRESH_ROLE_ROW_REQUIRED")
                _digest(row["sha256"])
                if (
                    type(row["roles"]) is not list
                    or not row["roles"]
                    or any(type(role) is not str or not role for role in row["roles"])
                    or len(set(row["roles"])) != len(row["roles"])
                ):
                    raise BundleReadError("NONEMPTY_DISTINCT_ROLE_NAMES_REQUIRED")
            classification_sha = hashlib.sha256(_canonical_json(roles)).hexdigest()
            if classification_sha != receipt["classification_digest"]:
                raise BundleReadError("FRESH_CLASSIFICATION_BINDING_MISMATCH")
            verifiers = receipt["verifier_files"]
            if type(verifiers) is not dict or not verifiers:
                raise BundleReadError("PINNED_STATIC_VERIFIERS_REQUIRED")
            for name, digest in verifiers.items():
                path = _canonical(name)
                _digest(digest)
                if name not in roles or roles[name]["sha256"] != digest:
                    raise BundleReadError("VERIFIER_MUST_REMAIN_FRESH")
                super()._entry(path, digest)
            roots = receipt["proof_roots"]
            if type(roots) is not list or not roots:
                raise BundleReadError("EXPLICIT_STATIC_PROOF_ROOTS_REQUIRED")
            keys = set()
            for row in roots:
                if type(row) is not dict or set(row) != {"path", "sha256", "purpose"}:
                    raise BundleReadError("EXACT_STATIC_PROOF_ROOT_REQUIRED")
                _canonical(row["path"])
                _digest(row["sha256"])
                if row["purpose"] != "STATIC_TREE" or row["path"] in keys:
                    raise BundleReadError("DISTINCT_STATIC_TREE_PURPOSE_REQUIRED")
                keys.add(row["path"])
            physical, index = self._parse_current_authority_bundle()
            # Interface format and environment are checked against authenticated index.
            if receipt["format_revision"] != index.format_revision:
                raise BundleReadError("BUNDLE_FORMAT_RECEIPT_MISMATCH")
            if receipt["environment"] != {
                "python": index.manifest_env["python"],
                "packages": dict(index.manifest_env["packages"]),
            }:
                raise BundleReadError("BUNDLE_ENVIRONMENT_RECEIPT_MISMATCH")
            for row in roots:
                if row not in index.roots:
                    raise BundleReadError("PROOF_ROOT_NOT_IN_SEALED_ROOT_SET")
            self._receipt = receipt
            self._index = index
            self._authority = physical.data
        except BaseException as exc:
            self._poison(exc)
            raise

    @contextmanager
    def physical_reads(self):
        self._active()
        self._physical_depth += 1
        try:
            yield
        except BaseException as exc:
            self._poison(exc)
            raise
        finally:
            self._physical_depth -= 1

    def _entry(self, path, expected_sha256):
        self._active()
        try:
            _digest(expected_sha256)
            supplied = Path(os.fspath(path))
            if ".." in supplied.parts:
                raise BundleReadError("PARENT_TRAVERSAL_NOT_SUPPORTED")
            canonical = Path(os.path.abspath(supplied))
            self._ensure_authority()
            virtual = self._virtual_entries.get(canonical)
            if virtual is not None and virtual.expected != expected_sha256:
                raise BundleReadError("CONFLICTING_EXPECTED_FILE_HASH")
            role = self._receipt["fresh_roles"].get(str(canonical))
            if role is not None and role["sha256"] != expected_sha256:
                raise BundleReadError("FRESH_ROLE_EXPECTED_HASH_CONFLICT")
            fresh = (
                role is not None
                or self._physical_depth
                or canonical in self._promoted
                or canonical in self._entries
            )
            if fresh or str(canonical) not in self._index.files:
                if canonical not in self._promoted:
                    self._promoted.add(canonical)
                    if virtual is not None:
                        self._logical["promotions"] += 1
                return super()._entry(canonical, expected_sha256)
            if virtual is not None:
                self._stats["repeat_references"] += 1
                return virtual
            raw = entry_bytes(self._authority, self._index, str(canonical), expected_sha256)
            entry = _Entry(expected=expected_sha256, data=raw)
            self._virtual_entries[canonical] = entry
            self._logical["member_reads"] += 1
            self._logical["member_bytes"] += len(raw)
            return entry
        except BaseException as exc:
            self._poison(exc)
            raise

    def _close(self, body_error=None):
        # Do not call _active here: an already poisoned scope must still perform
        # every physical closing observation and preserve its original failure.
        if not self._closed:
            errors = []
            if self._owner != (os.getpid(), threading.get_ident()):
                errors.append(BundleReadError("BUNDLE_SCOPE_OWNER_DRIFT"))
            if self._receipt is None:
                errors.append(BundleReadError("NO_VERIFIED_STATIC_AUTHORITY"))
            else:
                missing = [
                    name
                    for name in self._receipt["fresh_roles"]
                    if Path(name) not in self._entries
                    or self._entries[Path(name)].data is None
                    or self._entries[Path(name)].identity is None
                    or self._entries[Path(name)].expected
                    != self._receipt["fresh_roles"][name]["sha256"]
                ]
                if missing:
                    errors.append(
                        BundleReadError("FRESH_ROLE_COVERAGE_INCOMPLETE: " + repr(sorted(missing)))
                    )
            for error in errors:
                primary = body_error if body_error is not None else self._failure
                if primary is not None:
                    primary.add_note("Additional authority closing failure: " + repr(error))
                self._poison(error)
        try:
            return super()._close(body_error)
        finally:
            self._virtual_entries.clear()
            self._authority = self._index = self._receipt = None

    def verify_static_tree(self, path, digest, seen=None):
        self._active()
        try:
            if seen is not None and (type(seen) is not set or seen):
                raise BundleReadError("TREE_SEEN_MUST_START_EMPTY")
            self._ensure_authority()
            key = {"path": str(path), "sha256": digest, "purpose": "STATIC_TREE"}
            if key not in self._receipt["proof_roots"]:
                with self.physical_reads():
                    return verify_tree(self, path, digest, seen)
            # The proof replaces static traversal, never this root's live role.
            self.read_bytes(path, digest)
            env = self._receipt["environment"]
            if env["python"] is not None and platform.python_version() != env["python"]:
                raise BundleReadError("PYTHON_DRIFT")
            for name, version in env["packages"].items():
                if importlib.metadata.version(name) != version:
                    raise BundleReadError("DEPENDENCY_VERSION_DRIFT")
            self._logical["proof_uses"] += 1
        except BaseException as exc:
            self._poison(exc)
            raise
