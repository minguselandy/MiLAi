"""R05 retained STATIC_TREE authority; later package path freshness is intentionally removed.

Only one owner Batch/PID/thread may reuse its cold-verified immutable static bytes.
All other live observations stay fresh. No R03/R04 freshness certificate is implied.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import threading
from contextlib import contextmanager
from pathlib import Path

from v0222_admission_read_scope import AdmissionReadScope, _Entry
from v0222_scoped_evidence import _strict_json, verify_tree
from v0224_static_bundle import BundleLimits, entry_bytes
from v0224_verified_digest_scope import (
    BundleReadError,
    _canonical,
    _canonical_json,
    _digest,
)
from v0224_verified_digest_scope import (
    BundleReadScope as OriginalScope,
)

_MINT = object()


def _configuration(bundle_path, bundle_sha256, receipt_path, receipt_sha256, limits):
    bundle, receipt = _canonical(str(bundle_path)), _canonical(str(receipt_path))
    if bundle == receipt or type(limits) is not BundleLimits:
        raise BundleReadError("EXACT_DISTINCT_RETAINED_AUTHORITY_CONFIG_REQUIRED")
    return bundle, _digest(bundle_sha256), receipt, _digest(receipt_sha256), limits


class _RetainedAuthority:
    """Opaque by API convention; not a sandbox against malicious Python reflection."""

    __slots__ = (
        "_config",
        "_counts",
        "_index",
        "_initial_stats",
        "_owner_identity",
        "_owner_object",
        "_raw",
        "_released",
    )

    def __init__(self, token, *, owner, config, raw, index, initial_stats):
        if token is not _MINT or owner is None:
            raise BundleReadError("FACTORY_INITIALIZED_RETAINED_AUTHORITY_REQUIRED")
        self._owner_object = owner
        self._owner_identity = (os.getpid(), threading.get_ident())
        self._config = config
        self._raw, self._index = raw, index
        self._released = False
        self._initial_stats = dict(initial_stats)
        self._counts = {
            "scope_uses": 0,
            "retained_bundle_reads": 0,
            "retained_bundle_bytes": 0,
            "retained_member_reads": 0,
            "retained_member_bytes": 0,
        }

    def _check(self, owner, config=None, *, allow_released=False):
        if owner is not self._owner_object or self._owner_identity != (
            os.getpid(),
            threading.get_ident(),
        ):
            raise BundleReadError("RETAINED_AUTHORITY_OWNER_DRIFT")
        if config is not None and config != self._config:
            raise BundleReadError("RETAINED_AUTHORITY_CONFIG_DRIFT")
        if self._released and not allow_released:
            raise BundleReadError("RETAINED_AUTHORITY_RELEASED")
        if not self._released and (
            self._index is None
            or self._raw is None
            or self._index._source is not self._raw
            or self._index.bundle_sha256 != self._config[1]
        ):
            raise BundleReadError("RETAINED_AUTHORITY_BUFFER_IDENTITY_DRIFT")

    def _borrow(self, owner, config):
        self._check(owner, config)
        return self._raw, self._index

    def release(self, *, owner):
        self._check(owner, allow_released=True)
        self._released = True
        self._raw = self._index = None

    def stats(self, *, owner):
        self._check(owner, allow_released=True)
        return {
            "authority_revision": "R05_COLD_PROCESS_STATIC_AUTHORITY",
            "released": self._released,
            "owner_pid": self._owner_identity[0],
            "initialization_physical_stats": dict(self._initial_stats),
            **self._counts,
        }


def initialize_retained_authority(
    *, owner, bundle_path, bundle_sha256, receipt_path, receipt_sha256, limits
):
    if owner is None:
        raise BundleReadError("EXPLICIT_BATCH_OWNER_REQUIRED")
    config = _configuration(bundle_path, bundle_sha256, receipt_path, receipt_sha256, limits)
    with OriginalScope(
        bundle_path=bundle_path,
        bundle_sha256=bundle_sha256,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        limits=limits,
    ) as scope:
        scope._ensure_authority()
        if str(scope._bundle_path) in scope._receipt["fresh_roles"]:
            raise BundleReadError("STATIC_AUTHORITY_FRESH_ROLE_CONFLICT")
        for path, row in scope._receipt["fresh_roles"].items():
            with scope.physical_reads():
                scope.read_bytes(Path(path), row["sha256"])
        for root in scope._receipt["proof_roots"]:
            scope.verify_static_tree(Path(root["path"]), root["sha256"])
        # References remain local until original first/close validation succeeds.
        raw, index = scope._authority, scope._index
    if scope.status != "CLOSED_VERIFIED_TWO_OBSERVATIONS":
        raise BundleReadError("COMPLETE_RETAINED_INITIALIZATION_REQUIRED")
    return _RetainedAuthority(
        _MINT, owner=owner, config=config, raw=raw, index=index, initial_stats=scope.stats
    )


class RetainedStaticReadScope(AdmissionReadScope):
    """Fresh dynamic scope; only STATIC_TREE and one fixed package input are retained."""

    def __init__(
        self,
        *,
        owner,
        retained_authority,
        bundle_path,
        bundle_sha256,
        receipt_path,
        receipt_sha256,
        limits,
    ):
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
        if type(retained_authority) is not _RetainedAuthority:
            raise BundleReadError("EXACT_FACTORY_RETAINED_AUTHORITY_REQUIRED")
        self._retained_owner = owner
        self._retained = retained_authority
        self._retained_config = _configuration(
            bundle_path, bundle_sha256, receipt_path, receipt_sha256, limits
        )
        self._retained._check(owner, self._retained_config)
        self._retained._counts["scope_uses"] += 1
        self._bundle_entry = None

    def _active(self):
        super()._active()
        if self._owner != (os.getpid(), threading.get_ident()):
            exc = BundleReadError("BUNDLE_SCOPE_OWNER_DRIFT")
            self._poison(exc)
            raise exc
        try:
            self._retained._check(self._retained_owner, self._retained_config)
        except BaseException as error:
            self._poison(error)
            raise

    @property
    def authority_stats(self):
        return {**self._logical, "authority_revision": "R05_COLD_PROCESS_STATIC_AUTHORITY"}

    def _ensure_authority(self):
        self._active()
        if not self._entered:
            error = BundleReadError("ENTERED_RETAINED_SCOPE_REQUIRED")
            self._poison(error)
            raise error
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
            if str(self._bundle_path) in roles:
                raise BundleReadError("STATIC_AUTHORITY_FRESH_ROLE_CONFLICT")
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
            raw, index = self._retained._borrow(self._retained_owner, self._retained_config)
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
            self._authority = raw
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
            if canonical == self._bundle_path:
                if expected_sha256 != self._bundle_sha:
                    raise BundleReadError("CONFLICTING_EXPECTED_FILE_HASH")
                if self._bundle_entry is None:
                    self._bundle_entry = _Entry(expected=self._bundle_sha, data=self._authority)
                else:
                    self._stats["repeat_references"] += 1
                self._retained._counts["retained_bundle_reads"] += 1
                self._retained._counts["retained_bundle_bytes"] += len(self._authority)
                return self._bundle_entry
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
            self._retained._counts["retained_member_reads"] += 1
            self._retained._counts["retained_member_bytes"] += len(raw)
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
            try:
                self._retained._check(self._retained_owner, self._retained_config)
            except BaseException as error:
                errors.append(error)
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
            self._bundle_entry = None
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
