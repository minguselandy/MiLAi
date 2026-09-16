"""Single-call verified reads, followed by a second fresh content observation.

This is NOT a Batch gate, HTTP authorization, immutable snapshot, or cross-call
cache. Successful close proves two observations, not continuous immutability
between them. Symlinks (including directory aliases) and parent-traversal '..'
components are deliberately unsupported, even when traversal would be harmless.
Strict JSON here means raw UTF-8 decoding plus duplicate-key/nonfinite-number
rejection, not a Unicode-scalar guarantee for escaped strings. Business output
acceptance remains the responsibility of the original stronger contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


class AdmissionReadError(ValueError):
    """A read scope cannot establish its requested evidence contract."""


@dataclass
class _Entry:
    expected: str
    identity: tuple | None = None
    data: bytes | None = None
    parsed: object = None
    parsed_ready: bool = False


def _identity(value: os.stat_result) -> tuple:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionReadError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(value):
    raise AdmissionReadError("NONFINITE_JSON_NUMBER: " + value)


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise AdmissionReadError("NONFINITE_JSON_NUMBER: " + value)
    return result


class AdmissionReadScope:
    """Explicit one-call scope; every fresh scope rereads its complete inputs.

    Any failed read/parse poisons the whole scope. A caught failure is re-raised at
    close. If body execution already raised, its original exception is preserved;
    additional read/closing failures are attached as exception notes.
    """

    def __init__(self):
        self._entries: dict[Path, _Entry] = {}
        self._closed = False
        self._entered = False
        self._failure: BaseException | None = None
        self._close_failures: list[BaseException] = []
        self._stats = {
            "first_read_attempts": 0,
            "first_reads": 0,
            "first_hashes": 0,
            "first_bytes": 0,
            "json_parses": 0,
            "repeat_references": 0,
            "closing_read_attempts": 0,
            "closing_reads": 0,
            "closing_hashes": 0,
            "closing_bytes": 0,
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    @property
    def status(self) -> str:
        if self._closed:
            return (
                "CLOSED_FAILED" if self._failure is not None else "CLOSED_VERIFIED_TWO_OBSERVATIONS"
            )
        return "POISONED" if self._failure is not None else "ACTIVE"

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    @property
    def close_failures(self) -> tuple[BaseException, ...]:
        return tuple(self._close_failures)

    def _active(self):
        if self._closed:
            raise AdmissionReadError("READ_SCOPE_ALREADY_CLOSED")
        if self._failure is not None:
            raise AdmissionReadError("READ_SCOPE_POISONED") from self._failure

    def _poison(self, exc: BaseException):
        if self._failure is None:
            self._failure = exc

    def __enter__(self):
        self._active()
        if self._entered:
            exc = AdmissionReadError("READ_SCOPE_CANNOT_BE_REENTERED")
            self._poison(exc)
            raise exc
        self._entered = True
        return self

    def _regular_bytes(self, path: Path, *, closing: bool) -> tuple[bytes, tuple, str]:
        phase = "closing" if closing else "first"
        self._stats[phase + "_read_attempts"] += 1
        # Resolve only to reject aliases, never silently switch the requested path.
        if path.resolve(strict=True) != path:
            raise AdmissionReadError("SYMLINK_PATH_NOT_SUPPORTED")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise AdmissionReadError("REGULAR_FILE_REQUIRED")
            chunks = []
            while chunk := os.read(fd, 1024 * 1024):
                self._stats[phase + "_bytes"] += len(chunk)
                chunks.append(chunk)
            data = b"".join(chunks)
            self._stats[phase + "_reads"] += 1
            digest = hashlib.sha256(data).hexdigest()
            self._stats[phase + "_hashes"] += 1
            after = os.fstat(fd)
            linked = path.stat(follow_symlinks=False)
            if (
                _identity(before) != _identity(after)
                or _identity(after) != _identity(linked)
                or len(data) != after.st_size
                or path.resolve(strict=True) != path
            ):
                raise AdmissionReadError("FILE_CHANGED_DURING_OBSERVATION")
            return data, _identity(after), digest
        finally:
            os.close(fd)

    def _entry(self, path: Path | str, expected_sha256: str) -> _Entry:
        self._active()
        try:
            if not isinstance(expected_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_sha256
            ):
                raise AdmissionReadError("EXACT_LOWERCASE_SHA256_REQUIRED")
            supplied = Path(os.fspath(path))
            # Never collapse link/../file or missing/../file into another object.
            # pathlib retains '..' components; inspect them before abspath/resolve.
            if ".." in supplied.parts:
                raise AdmissionReadError("PARENT_TRAVERSAL_NOT_SUPPORTED")
            canonical = Path(os.path.abspath(supplied))
            if canonical in self._entries:
                entry = self._entries[canonical]
                if entry.expected != expected_sha256:
                    raise AdmissionReadError("CONFLICTING_EXPECTED_FILE_HASH")
                self._stats["repeat_references"] += 1
                return entry
            entry = _Entry(expected_sha256)
            self._entries[canonical] = entry
            data, identity, digest = self._regular_bytes(canonical, closing=False)
            entry.identity = identity
            if digest != expected_sha256:
                raise AdmissionReadError("INITIAL_CONTENT_HASH_MISMATCH")
            entry.data = data
            return entry
        except BaseException as exc:
            self._poison(exc)
            raise

    def read_bytes(self, path: Path | str, expected_sha256: str) -> bytes:
        entry = self._entry(path, expected_sha256)
        assert entry.data is not None
        return entry.data  # bytes are immutable; the internal JSON is never exposed.

    def read_json(self, path: Path | str, expected_sha256: str):
        entry = self._entry(path, expected_sha256)
        try:
            if not entry.parsed_ready:
                self._stats["json_parses"] += 1
                entry.parsed = json.loads(
                    entry.data.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=_constant,
                    parse_float=_finite_float,
                )
                entry.parsed_ready = True
            return copy.deepcopy(entry.parsed)
        except BaseException as exc:
            self._poison(exc)
            raise

    def _close(self, body_error: BaseException | None = None):
        if self._closed:
            raise AdmissionReadError("READ_SCOPE_ALREADY_CLOSED")
        primary = body_error if body_error is not None else self._failure
        if body_error is not None:
            if self._failure is not None and self._failure is not body_error:
                body_error.add_note("Earlier scope failure: " + repr(self._failure))
            self._poison(body_error)
        try:
            for path, entry in self._entries.items():
                try:
                    _, identity, digest = self._regular_bytes(path, closing=True)
                    if digest != entry.expected or identity != entry.identity:
                        raise AdmissionReadError(
                            "CLOSING_CONTENT_OR_PATH_IDENTITY_MISMATCH: " + str(path)
                        )
                except BaseException as exc:
                    self._close_failures.append(exc)
                    self._poison(exc)
                    if primary is None:
                        primary = exc
                    else:
                        primary.add_note("Additional closing failure: " + repr(exc))
        finally:
            self._closed = True
            self._entries.clear()
        if primary is not None:
            raise primary

    def close(self):
        """Second fresh read/hash of every visited path, even after poisoning."""
        self._close()

    def __exit__(self, exc_type, exc, traceback):
        self._close(exc)
        return False
