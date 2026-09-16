#!/usr/bin/env python3
"""Package explicit, already-produced DG-13U U1 evidence for read-only review."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts import dg13u_u1_aggregate as _aggregate_contract
except ImportError:  # pragma: no cover - direct script execution
    import dg13u_u1_aggregate as _aggregate_contract


AGGREGATE_SCHEMA = _aggregate_contract.AGGREGATE_SCHEMA
REPORT_SCHEMA = _aggregate_contract.REPORT_SCHEMA
RELEASE_LABEL = _aggregate_contract.RELEASE_LABEL
GATE_NAMES = _aggregate_contract.GATE_NAMES
REQUIRED_CASE_IDS = _aggregate_contract.REQUIRED_CASE_IDS
REQUIRED_ARTIFACT_SCHEMAS = _aggregate_contract.REQUIRED_ARTIFACT_SCHEMAS
BUNDLE_SCHEMA = "milai.dg13u.u1-review-bundle-manifest.v1"
TEST_GATE_RECEIPT_SCHEMA = "milai.dg13u.u1-test-gate-receipt.v1"
_TEST_GATE_EXECUTION_SCOPE = "FIXED_UNIT_AND_OWNING_TESTS_ONLY"
_TEST_GATE_SUITES = (
    ("u1-top-level-26-plus-u0-support", 27),
    ("python-client", 10),
    ("openworker-integration", 8),
)
_RECOVERY_PLAN_ARTIFACT = "recovery-resource-plan.json"
_SMOKE_COMMAND_DIAGNOSTIC_ARTIFACT = "smoke-command-diagnostic.json"
_SMOKE_COMMAND_DIAGNOSTIC_SCHEMA = "milai.dg13u.u1-smoke-command-diagnostic.v1"
_PROVIDER_FAULT_CASE_IDS = frozenset(
    {
        "U1-PROVIDER-DOWN",
        "U1-PROVIDER-MALFORMED",
        "U1-PROVIDER-TIMEOUT",
    }
)
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 20_000
_MAX_ARCHIVE_DEPTH = 4
_SAFE_SENTINELS = frozenset(
    {
        "",
        "absent",
        "false",
        "none",
        "not_present",
        "redacted",
        "removed",
        "[redacted]",
        "<redacted>",
    }
)
_PRIVATE_KEY_BLOCK = re.compile(
    rb"-----BEGIN ([A-Z ]*)PRIVATE KEY-----\s+"
    rb"[A-Za-z0-9+/=\r\n]{32,}\s+-----END \1PRIVATE KEY-----"
)
_SECRET_TEXT_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)authorization\s*[:=]\s*(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{8,}"),
    re.compile(rb"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|password|secret|token)\b\s*[:=]\s*[\"']?[A-Za-z0-9+/_.=-]{12,}"
    ),
)
_ARCHIVE_SECRET_TEXT_PATTERNS = (
    _PRIVATE_KEY_BLOCK,
    *_SECRET_TEXT_PATTERNS[1:4],
)
_BINARY_SECRET_TEXT_PATTERNS = (
    _PRIVATE_KEY_BLOCK,
    _SECRET_TEXT_PATTERNS[1],
    _SECRET_TEXT_PATTERNS[3],
)
_ARCHIVE_AUTHORIZATION = re.compile(
    rb"(?i)authorization\s*[:=]\s*(?:bearer|basic)\s+([A-Za-z0-9+/_.=-]{8,})"
)
_SAFE_ARCHIVE_CREDENTIAL_VALUES = frozenset(
    {
        b"do-not-store",
        b"dummy-token",
        b"example-token",
        b"fake-token",
        b"not-a-real-token",
        b"placeholder-token",
        b"reader-token",
        b"sample-token",
        b"synthetic-token",
        b"test-token",
    }
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class BundleError(RuntimeError):
    """Explicit evidence cannot be packaged without weakening review boundaries."""


@dataclass(frozen=True, slots=True)
class _InputFile:
    path: Path
    raw: bytes
    sha256: str
    size: int
    archive_members_scanned: int
    archive_uncompressed_bytes: int


@dataclass(slots=True)
class _ArchiveScanBudget:
    members: int = 0
    uncompressed_bytes: int = 0

    def account(self, size: int, label: str) -> None:
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > _MAX_ARCHIVE_MEMBER_BYTES
        ):
            raise BundleError(f"archive member size is invalid in {label}")
        self.members += 1
        self.uncompressed_bytes += size
        if self.members > _MAX_ARCHIVE_MEMBERS:
            raise BundleError(f"archive member count exceeds the bound in {label}")
        if self.uncompressed_bytes > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise BundleError(f"archive uncompressed size exceeds the bound in {label}")


@dataclass(frozen=True, slots=True)
class _BundleFile:
    logical_path: str
    source: _InputFile
    source_kind: str
    schema: str | None
    case_id: str | None = None
    run_id: str | None = None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _lexical_absolute(path: str | Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise BundleError(f"{label} must be an explicit absolute path")
    return Path(os.path.normpath(os.fspath(candidate)))


def _reject_symlink_chain(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode):
            raise BundleError(f"{label} symlink is forbidden")


def _read_explicit(path: str | Path, label: str) -> _InputFile:
    candidate = _lexical_absolute(path, label)
    _reject_symlink_chain(candidate, label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise BundleError(f"{label} must be an explicit readable regular file") from exc
    try:
        before = candidate.lstat()
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise BundleError(f"{label} must be an explicit regular file")
        if opened.st_size > _MAX_FILE_BYTES:
            raise BundleError(f"{label} exceeds the bounded file size")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, _MAX_FILE_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > _MAX_FILE_BYTES:
                raise BundleError(f"{label} exceeds the bounded file size")
        after = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise BundleError(f"{label} changed while being read")
    except OSError as exc:
        raise BundleError(f"{label} is unreadable") from exc
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    scan = _scan_explicit_payload(raw, candidate.name, label)
    return _InputFile(
        path=candidate,
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
        archive_members_scanned=scan.members,
        archive_uncompressed_bytes=scan.uncompressed_bytes,
    )


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    if "sha256" in normalized or normalized.endswith(("_present", "_count")):
        return False
    return normalized in {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
    } or normalized.endswith(("_password", "_secret", "_token"))


def _safe_archive_credential(value: bytes) -> bool:
    return value.lower() in _SAFE_ARCHIVE_CREDENTIAL_VALUES


def _safe_sensitive_value(value: object, *, archive_member: bool = False) -> bool:
    if value is None or value is False or value == 0:
        return True
    return isinstance(value, str) and (
        value.casefold() in _SAFE_SENTINELS
        or re.fullmatch(r"\$\{[A-Z][A-Z0-9_]{0,127}\}", value) is not None
        or (
            archive_member
            and _safe_archive_credential(value.encode("utf-8", errors="strict"))
        )
    )


def _json_has_secret(value: object, *, archive_member: bool = False) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                isinstance(key, str)
                and _sensitive_key(key)
                and not isinstance(item, (Mapping, list))
                and not _safe_sensitive_value(item, archive_member=archive_member)
            ):
                return True
            if _json_has_secret(item, archive_member=archive_member):
                return True
    elif isinstance(value, list):
        return any(
            _json_has_secret(item, archive_member=archive_member) for item in value
        )
    return False


def _reject_secret_patterns(
    raw: bytes, label: str, *, archive_member: bool = False
) -> None:
    patterns = (
        _ARCHIVE_SECRET_TEXT_PATTERNS if archive_member else _SECRET_TEXT_PATTERNS
    )
    for pattern in patterns:
        match = pattern.search(raw)
        if match is None:
            continue
        if archive_member and pattern is _ARCHIVE_SECRET_TEXT_PATTERNS[1]:
            authorizations = tuple(_ARCHIVE_AUTHORIZATION.finditer(raw))
            if authorizations and all(
                _safe_archive_credential(authorization.group(1))
                for authorization in authorizations
            ):
                continue
        raise BundleError(f"SECRET_LIKE_CONTENT in {label}")


def _reject_secret_like(
    raw: bytes,
    label: str,
    *,
    allow_opaque_binary: bool = False,
    archive_member: bool = False,
) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        if allow_opaque_binary:
            if any(pattern.search(raw) for pattern in _BINARY_SECRET_TEXT_PATTERNS):
                raise BundleError(f"SECRET_LIKE_CONTENT in {label}") from None
            return
        raise BundleError(f"{label} is not UTF-8 and cannot be secret-scanned") from exc
    _reject_secret_patterns(raw, label, archive_member=archive_member)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return
    if _json_has_secret(value, archive_member=archive_member):
        raise BundleError(f"SECRET_LIKE_CONTENT in {label}")


def _archive_kind(name: str) -> str | None:
    lowered = name.casefold()
    if lowered.endswith((".whl", ".zip")):
        return "zip"
    if lowered.endswith((".tar.gz", ".tgz", ".tar")):
        return "tar"
    return None


def _archive_member_path(name: str, label: str) -> PurePosixPath:
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or "\\" in name
        or re.match(r"^[A-Za-z]:", name) is not None
    ):
        raise BundleError(f"archive member path is invalid in {label}")
    normalized = name.removesuffix("/")
    member = PurePosixPath(normalized)
    if (
        not normalized
        or normalized in {".", ".."}
        or member.is_absolute()
        or member.as_posix() != normalized
        or any(part in {"", ".", ".."} for part in member.parts)
    ):
        raise BundleError(f"archive member path is invalid in {label}")
    return member


def _archive_member_mode(mode: int, label: str) -> None:
    permissions = stat.S_IMODE(mode)
    if permissions & 0o7002:
        raise BundleError(f"archive member mode is unsafe in {label}")


def _scan_explicit_payload(raw: bytes, name: str, label: str) -> _ArchiveScanBudget:
    budget = _ArchiveScanBudget()
    _scan_payload(
        raw,
        name=name,
        label=label,
        budget=budget,
        depth=0,
        allow_opaque_binary=False,
    )
    return budget


def _scan_payload(
    raw: bytes,
    *,
    name: str,
    label: str,
    budget: _ArchiveScanBudget,
    depth: int,
    allow_opaque_binary: bool,
) -> None:
    kind = _archive_kind(name)
    if kind is None:
        _reject_secret_like(
            raw,
            label,
            allow_opaque_binary=allow_opaque_binary,
            archive_member=allow_opaque_binary,
        )
        return
    if depth >= _MAX_ARCHIVE_DEPTH:
        raise BundleError(f"archive nesting exceeds the bound in {label}")
    if kind == "zip":
        _scan_zip(raw, label=label, budget=budget, depth=depth)
    else:
        _scan_tar(raw, label=label, budget=budget, depth=depth)


def _scan_zip(
    raw: bytes,
    *,
    label: str,
    budget: _ArchiveScanBudget,
    depth: int,
) -> None:
    stream = io.BytesIO(raw)
    if not zipfile.is_zipfile(stream):
        raise BundleError(f"archive content is invalid in {label}")
    seen: set[PurePosixPath] = set()
    try:
        with zipfile.ZipFile(io.BytesIO(raw), mode="r") as archive:
            _reject_secret_like(
                archive.comment,
                label,
                allow_opaque_binary=True,
                archive_member=True,
            )
            for member in archive.infolist():
                path = _archive_member_path(member.filename, label)
                if path in seen:
                    raise BundleError(f"duplicate archive member path in {label}")
                seen.add(path)
                budget.account(member.file_size, label)
                if member.flag_bits & 0x1:
                    raise BundleError(
                        f"encrypted archive member is forbidden in {label}"
                    )
                raw_mode = (member.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(raw_mode)
                if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise BundleError(f"archive member type is unsafe in {label}")
                if member.is_dir():
                    if file_type not in {0, stat.S_IFDIR}:
                        raise BundleError(f"archive member type is unsafe in {label}")
                    _archive_member_mode(raw_mode, label)
                    continue
                if file_type == stat.S_IFDIR:
                    raise BundleError(f"archive member type is unsafe in {label}")
                _archive_member_mode(raw_mode, label)
                member_raw = archive.read(member)
                if len(member_raw) != member.file_size:
                    raise BundleError(f"archive member size changed in {label}")
                member_label = f"{label} archive member {path.as_posix()}"
                _reject_secret_like(
                    member.filename.encode(),
                    member_label,
                    allow_opaque_binary=False,
                    archive_member=True,
                )
                _reject_secret_like(
                    member.comment + member.extra,
                    member_label,
                    allow_opaque_binary=True,
                    archive_member=True,
                )
                _scan_payload(
                    member_raw,
                    name=path.name,
                    label=member_label,
                    budget=budget,
                    depth=depth + 1,
                    allow_opaque_binary=True,
                )
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError(f"archive content is invalid in {label}") from exc


def _scan_tar(
    raw: bytes,
    *,
    label: str,
    budget: _ArchiveScanBudget,
    depth: int,
) -> None:
    seen: set[PurePosixPath] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
            for member in archive:
                path = _archive_member_path(member.name, label)
                if path in seen:
                    raise BundleError(f"duplicate archive member path in {label}")
                seen.add(path)
                budget.account(member.size, label)
                if not (member.isfile() or member.isdir()):
                    raise BundleError(f"archive member type is unsafe in {label}")
                _archive_member_mode(member.mode, label)
                member_label = f"{label} archive member {path.as_posix()}"
                metadata = _canonical(
                    {
                        "name": member.name,
                        "pax_headers": dict(sorted(member.pax_headers.items())),
                    }
                )
                _reject_secret_like(metadata, member_label, archive_member=True)
                if member.isdir():
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise BundleError(f"archive member is unreadable in {label}")
                member_raw = extracted.read(_MAX_ARCHIVE_MEMBER_BYTES + 1)
                if len(member_raw) != member.size:
                    raise BundleError(f"archive member size changed in {label}")
                _scan_payload(
                    member_raw,
                    name=path.name,
                    label=member_label,
                    budget=budget,
                    depth=depth + 1,
                    allow_opaque_binary=True,
                )
    except (tarfile.TarError, OSError) as exc:
        raise BundleError(f"archive content is invalid in {label}") from exc


def _json_object(source: _InputFile, label: str) -> dict[str, Any]:
    try:
        value = json.loads(source.raw)
    except json.JSONDecodeError as exc:
        raise BundleError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise BundleError(f"{label} must be a JSON object")
    return value


def _unique_inputs(paths: Sequence[str | Path], label: str) -> list[_InputFile]:
    if not paths:
        return []
    normalized = [_lexical_absolute(path, label) for path in paths]
    if len(normalized) != len(set(normalized)):
        raise BundleError(f"duplicate explicit {label} path")
    return [_read_explicit(path, label) for path in normalized]


def _validate_aggregate(
    source: _InputFile, reports: Sequence[_InputFile]
) -> tuple[dict[str, Any], dict[tuple[str, str], _InputFile]]:
    document = _json_object(source, "aggregate")
    if document.get("schema") != AGGREGATE_SCHEMA:
        raise BundleError("aggregate schema is invalid")
    if (
        document.get("status") != "PASS"
        or document.get("product_usable") is not True
        or document.get("release_label") != RELEASE_LABEL
        or document.get("release_label_earned") is not True
    ):
        raise BundleError("aggregate has not earned the U1 release label")
    gates = document.get("gates")
    if not isinstance(gates, Mapping) or set(gates) != set(GATE_NAMES):
        raise BundleError("aggregate gate set is invalid")
    for name in GATE_NAMES:
        gate = gates[name]
        if not isinstance(gate, Mapping) or gate.get("status") != "PASS":
            raise BundleError(f"{name} must be PASS")
        if gate.get("intrinsic_status") != "PASS":
            raise BundleError(f"{name} intrinsic status must be PASS")
    matrix = document.get("matrix")
    if (
        not isinstance(matrix, Mapping)
        or matrix.get("status") != "PASS"
        or matrix.get("required") != len(REQUIRED_CASE_IDS)
        or matrix.get("observed") != len(REQUIRED_CASE_IDS)
        or matrix.get("missing_case_ids") != []
        or matrix.get("unexpected_case_ids") != []
    ):
        raise BundleError("aggregate matrix is incomplete")

    by_identity: dict[tuple[str, str], _InputFile] = {}
    for report in reports:
        value = _json_object(report, "report")
        if value.get("schema") != REPORT_SCHEMA or value.get("status") != "PASS":
            raise BundleError("report schema/status is invalid")
        case_id = value.get("case_id")
        run_id = value.get("run_id")
        if not isinstance(case_id, str) or not isinstance(run_id, str):
            raise BundleError("report identity is invalid")
        if _SAFE_ID.fullmatch(case_id) is None or _SAFE_ID.fullmatch(run_id) is None:
            raise BundleError("report identity is not bundle-path safe")
        identity = (case_id, run_id)
        if identity in by_identity:
            raise BundleError("duplicate report identity")
        by_identity[identity] = report
    if {case_id for case_id, _run_id in by_identity} != set(REQUIRED_CASE_IDS):
        raise BundleError("explicit report case set does not match aggregate contract")
    if len(by_identity) != len(REQUIRED_CASE_IDS):
        raise BundleError("explicit report count does not match aggregate contract")

    rows = document.get("inputs")
    if not isinstance(rows, list) or len(rows) != len(REQUIRED_CASE_IDS):
        raise BundleError("aggregate input binding set is invalid")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise BundleError("aggregate input binding is invalid")
        identity = (row.get("case_id"), row.get("run_id"))
        if not all(isinstance(item, str) for item in identity):
            raise BundleError("aggregate input identity is invalid")
        typed_identity = (str(identity[0]), str(identity[1]))
        if typed_identity in seen or typed_identity not in by_identity:
            raise BundleError(
                "aggregate input identity does not match explicit reports"
            )
        report_path = row.get("report_path")
        if not isinstance(report_path, str):
            raise BundleError("aggregate report path binding is invalid")
        if (
            _lexical_absolute(report_path, "aggregate report path")
            != by_identity[typed_identity].path
        ):
            raise BundleError("aggregate report path binding mismatch")
        expected_sha = row.get("report_sha256")
        if (
            not _is_sha256(expected_sha)
            or expected_sha != by_identity[typed_identity].sha256
        ):
            raise BundleError("aggregate REPORT_SHA256 binding mismatch")
        seen.add(typed_identity)
    if seen != set(by_identity):
        raise BundleError("aggregate input binding is incomplete")
    return document, by_identity


def _artifact_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise BundleError("report artifact path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise BundleError("report artifact path escapes its report directory")
    return relative


def _artifact_schema(
    source: _InputFile,
    relative: PurePosixPath,
    case_id: str,
    run_id: str,
) -> str | None:
    relative_path = relative.as_posix()
    expected_schema = REQUIRED_ARTIFACT_SCHEMAS.get(relative_path)
    if source.path.suffix.casefold() != ".json":
        if expected_schema is not None:
            raise BundleError("required run artifact is not JSON")
        return None
    document = _json_object(source, "run artifact")
    schema = document.get("schema")
    if not isinstance(schema, str) or not schema:
        raise BundleError("run artifact SCHEMA binding is absent")
    if expected_schema is not None and schema != expected_schema:
        raise BundleError("run artifact SCHEMA binding mismatch")
    if "run_id" in document and document.get("run_id") != run_id:
        raise BundleError("run artifact identity binding mismatch")
    recovery_plan = relative_path == _RECOVERY_PLAN_ARTIFACT
    if not recovery_plan:
        if "case_id" in document and document.get("case_id") != case_id:
            raise BundleError("run artifact identity binding mismatch")
        if "status" in document and document.get("status") != "PASS":
            expected_provider_fault = (
                relative_path == _SMOKE_COMMAND_DIAGNOSTIC_ARTIFACT
                and case_id in _PROVIDER_FAULT_CASE_IDS
                and schema == _SMOKE_COMMAND_DIAGNOSTIC_SCHEMA
                and document.get("run_id") == run_id
                and document.get("case_id") == case_id
                and document.get("status") == "FAIL"
                and document.get("stage") == "OPENCODE_RUN"
                and document.get("reason_code") == "OPENCODE_TYPED_ERROR"
                and isinstance(document.get("typed_error_count"), int)
                and not isinstance(document.get("typed_error_count"), bool)
                and document.get("typed_error_count") == 1
            )
            if not expected_provider_fault:
                raise BundleError("run artifact status binding mismatch")
    if expected_schema is not None and (
        document.get("run_id") != run_id
        or (
            not recovery_plan
            and (document.get("case_id") != case_id or document.get("status") != "PASS")
        )
    ):
        raise BundleError("required run artifact identity/status binding mismatch")
    return schema


def _bind_artifacts(
    report_sources: Mapping[tuple[str, str], _InputFile],
    explicit_artifacts: Sequence[_InputFile],
) -> tuple[list[_BundleFile], list[_InputFile]]:
    artifact_by_path = {artifact.path: artifact for artifact in explicit_artifacts}
    expected_paths: set[Path] = set()
    bundled: list[_BundleFile] = []
    for (case_id, run_id), report_source in sorted(report_sources.items()):
        report = _json_object(report_source, "report")
        rows = report.get("artifacts")
        if not isinstance(rows, list):
            raise BundleError("report artifact index is absent")
        by_relative: dict[PurePosixPath, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise BundleError("report artifact binding is invalid")
            relative = _artifact_relative_path(row.get("path"))
            if relative in by_relative:
                raise BundleError("duplicate report artifact binding")
            by_relative[relative] = row
        if not set(REQUIRED_ARTIFACT_SCHEMAS).issubset(
            {relative.as_posix() for relative in by_relative}
        ):
            raise BundleError("report required artifact set is incomplete")
        for relative, row in sorted(
            by_relative.items(), key=lambda item: item[0].as_posix()
        ):
            expected_path = Path(
                os.path.normpath(
                    os.fspath(report_source.path.parent / Path(*relative.parts))
                )
            )
            try:
                expected_path.relative_to(report_source.path.parent)
            except ValueError:
                raise BundleError(
                    "report artifact path escapes its report directory"
                ) from None
            if expected_path in expected_paths:
                raise BundleError("artifact path is bound by multiple reports")
            expected_paths.add(expected_path)
            source = artifact_by_path.get(expected_path)
            if source is None:
                raise BundleError("explicit artifact set is incomplete")
            expected_sha = row.get("sha256")
            expected_bytes = row.get("bytes")
            if not _is_sha256(expected_sha) or expected_sha != source.sha256:
                raise BundleError("run artifact SHA256 binding mismatch")
            if (
                not isinstance(expected_bytes, int)
                or isinstance(expected_bytes, bool)
                or expected_bytes != source.size
            ):
                raise BundleError("run artifact BYTES binding mismatch")
            schema = _artifact_schema(source, relative, case_id, run_id)
            bundled.append(
                _BundleFile(
                    logical_path=(f"runs/{case_id}--{run_id}/{relative.as_posix()}"),
                    source=source,
                    source_kind="RUN_ARTIFACT",
                    schema=schema,
                    case_id=case_id,
                    run_id=run_id,
                )
            )
    supplemental = [
        artifact
        for artifact in explicit_artifacts
        if artifact.path not in expected_paths
    ]
    return bundled, supplemental


def _supplemental_schema(source: _InputFile) -> str | None:
    if source.path.suffix.casefold() != ".json":
        return None
    document = _json_object(source, "supplemental artifact")
    schema = document.get("schema")
    if not isinstance(schema, str) or not schema:
        raise BundleError("supplemental JSON artifact schema is absent")
    return schema


def _exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _test_gate_logical_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BundleError("test-gate source path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BundleError("test-gate source path is invalid")
    return path


def _path_has_suffix(path: Path, suffix: PurePosixPath) -> bool:
    suffix_parts = suffix.parts
    return (
        len(path.parts) >= len(suffix_parts)
        and path.parts[-len(suffix_parts) :] == suffix_parts
    )


def _validate_test_gate_receipt(
    document: Mapping[str, Any], supplemental: Sequence[_InputFile]
) -> dict[Path, str]:
    if (
        document.get("schema") != TEST_GATE_RECEIPT_SCHEMA
        or document.get("status") != "PASS"
        or document.get("execution_scope") != _TEST_GATE_EXECUTION_SCOPE
    ):
        raise BundleError("test-gate receipt schema/status/scope is invalid")
    run_id = document.get("run_id")
    if not isinstance(run_id, str) or _SAFE_ID.fullmatch(run_id) is None:
        raise BundleError("test-gate receipt run identity is invalid")
    if not _exact_int(document.get("u1_top_level_file_count"), 26):
        raise BundleError("test-gate top-level file count is invalid")

    commands = document.get("commands")
    if not isinstance(commands, list) or len(commands) != len(_TEST_GATE_SUITES):
        raise BundleError("test-gate suite count is invalid")
    for command, (expected_name, expected_files) in zip(
        commands, _TEST_GATE_SUITES, strict=True
    ):
        if not isinstance(command, Mapping):
            raise BundleError("test-gate suite row is invalid")
        if (
            command.get("name") != expected_name
            or command.get("status") != "PASS"
            or not _exact_int(command.get("file_count"), expected_files)
            or not _exact_int(command.get("attempt"), 1)
            or not _exact_int(command.get("automatic_retries"), 0)
        ):
            raise BundleError("test-gate suite evidence is invalid")

    summary = document.get("summary")
    expected_summary = {
        "commands_planned": 3,
        "commands_executed": 3,
        "commands_passed": 3,
        "commands_failed": 0,
        "commands_not_executed": 0,
        "attempts_per_command_maximum": 1,
        "automatic_retries": 0,
    }
    if not isinstance(summary, Mapping) or any(
        not _exact_int(summary.get(key), expected)
        for key, expected in expected_summary.items()
    ):
        raise BundleError("test-gate suite summary is invalid")
    if (
        document.get("setup_error_reason") is not None
        or document.get("setup_error_type_sha256") is not None
        or document.get("raw_stdout_stderr_persisted") is not False
    ):
        raise BundleError("test-gate receipt failure/raw-output state is invalid")

    temporary = document.get("temporary_storage")
    if (
        not isinstance(temporary, Mapping)
        or temporary.get("kind") != "RUN_OWNED_EPHEMERAL_ROOT"
        or not _is_sha256(temporary.get("path_sha256"))
        or temporary.get("cleanup_status") != "PASS"
        or temporary.get("exists_after_cleanup") is not False
    ):
        raise BundleError("test-gate temporary cleanup evidence is invalid")

    rows = document.get("source_inputs")
    count = document.get("source_input_count")
    if (
        not isinstance(rows, list)
        or not rows
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(rows)
    ):
        raise BundleError("test-gate source input count is invalid")
    expected_inputs_sha = document.get("source_inputs_sha256")
    if (
        not _is_sha256(expected_inputs_sha)
        or hashlib.sha256(_canonical(rows)).hexdigest() != expected_inputs_sha
    ):
        raise BundleError("test-gate source input aggregate SHA256 is invalid")
    source_revalidation = document.get("source_revalidation")
    if (
        not isinstance(source_revalidation, Mapping)
        or source_revalidation.get("status") != "PASS"
        or source_revalidation.get("post_source_inputs_sha256") != expected_inputs_sha
    ):
        raise BundleError("test-gate source revalidation evidence is invalid")

    parsed_rows: list[tuple[PurePosixPath, int, str]] = []
    logical_paths: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"path", "bytes", "sha256"}:
            raise BundleError("test-gate source input row is invalid")
        logical = _test_gate_logical_path(row.get("path"))
        size = row.get("bytes")
        sha256 = row.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not _is_sha256(sha256)
        ):
            raise BundleError("test-gate source input row is invalid")
        logical_paths.append(logical.as_posix())
        parsed_rows.append((logical, size, sha256))
    if logical_paths != sorted(logical_paths) or len(logical_paths) != len(
        set(logical_paths)
    ):
        raise BundleError("test-gate source paths must be unique and sorted")

    closure: dict[Path, str] = {}
    for logical, expected_size, expected_sha in parsed_rows:
        matches = [
            source for source in supplemental if _path_has_suffix(source.path, logical)
        ]
        if len(matches) != 1:
            raise BundleError(
                "test-gate source input must have one explicit supplemental file"
            )
        source = matches[0]
        if source.size != expected_size or source.sha256 != expected_sha:
            raise BundleError("test-gate source input file binding mismatch")
        if source.path in closure:
            raise BundleError("test-gate source input file is bound more than once")
        closure[source.path] = logical.as_posix()
    return closure


def _test_gate_source_closure(
    supplemental: Sequence[_InputFile],
) -> dict[Path, str]:
    candidates: list[dict[str, Any]] = []
    for source in supplemental:
        if source.path.suffix.casefold() != ".json":
            continue
        document = _json_object(source, "supplemental artifact")
        if (
            document.get("schema") == TEST_GATE_RECEIPT_SCHEMA
            or document.get("execution_scope") == _TEST_GATE_EXECUTION_SCOPE
            or {
                "commands",
                "source_inputs",
                "source_inputs_sha256",
                "temporary_storage",
            }.issubset(document)
        ):
            candidates.append(document)
    if not candidates:
        return {}
    if len(candidates) != 1:
        raise BundleError("exactly one supplemental test-gate receipt is allowed")
    return _validate_test_gate_receipt(candidates[0], supplemental)


def _safe_basename(path: Path) -> str:
    name = path.name
    if (
        not name
        or name in {".", ".."}
        or any(ord(character) < 32 for character in name)
    ):
        raise BundleError("supplemental artifact basename is invalid")
    return name


def _write_private(path: Path, raw: bytes) -> None:
    missing: list[Path] = []
    current = path.parent
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    path.chmod(0o600)


def _bundle_paths(
    staging: Path, logical_paths: Sequence[str]
) -> tuple[list[Path], list[Path]]:
    files = [staging / logical_path for logical_path in logical_paths]
    files.append(staging / "manifest.json")
    directories = {staging}
    for path in files:
        current = path.parent
        while current != staging:
            directories.add(current)
            current = current.parent
    return files, sorted(directories, key=lambda path: len(path.parts))


def _seal_bundle(staging: Path, logical_paths: Sequence[str]) -> None:
    files, directories = _bundle_paths(staging, logical_paths)
    for path in files:
        path.chmod(0o444)
    for path in reversed(directories):
        path.chmod(0o555)


def _unseal_bundle(staging: Path, logical_paths: Sequence[str]) -> None:
    files, directories = _bundle_paths(staging, logical_paths)
    for path in directories:
        try:
            path.chmod(0o700)
        except FileNotFoundError:
            pass
    for path in files:
        try:
            path.chmod(0o600)
        except FileNotFoundError:
            pass


def _secure_output_parent(output: Path) -> None:
    _reject_symlink_chain(output.parent, "output parent")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = output.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
        raise BundleError("output parent must be a real directory")
    if stat.S_IMODE(parent.st_mode) & 0o022:
        raise BundleError("output parent must not be group/world writable")


def package_bundle(
    aggregate_path: str | Path,
    report_paths: Sequence[str | Path],
    artifact_paths: Sequence[str | Path],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Validate and atomically publish only the explicitly named review evidence."""
    output = _lexical_absolute(output_dir, "output directory")
    _reject_symlink_chain(output, "output directory")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)

    aggregate_source = _read_explicit(aggregate_path, "aggregate")
    reports = _unique_inputs(report_paths, "report")
    artifacts = _unique_inputs(artifact_paths, "artifact")
    input_paths = [
        aggregate_source.path,
        *(item.path for item in reports),
        *(item.path for item in artifacts),
    ]
    if len(input_paths) != len(set(input_paths)):
        raise BundleError("aggregate, report, and artifact paths must be disjoint")

    aggregate, reports_by_identity = _validate_aggregate(aggregate_source, reports)
    run_artifacts, supplemental = _bind_artifacts(reports_by_identity, artifacts)
    test_gate_sources = _test_gate_source_closure(supplemental)
    files: list[_BundleFile] = [
        _BundleFile(
            "aggregate/aggregate.json",
            aggregate_source,
            "AGGREGATE",
            AGGREGATE_SCHEMA,
        )
    ]
    for (case_id, run_id), report in sorted(reports_by_identity.items()):
        files.append(
            _BundleFile(
                f"reports/{case_id}--{run_id}.json",
                report,
                "RUN_REPORT",
                REPORT_SCHEMA,
                case_id,
                run_id,
            )
        )
    files.extend(run_artifacts)
    for source in sorted(supplemental, key=lambda item: (item.sha256, item.path.name)):
        test_gate_logical_path = test_gate_sources.get(source.path)
        if test_gate_logical_path is not None:
            files.append(
                _BundleFile(
                    f"test-gate-sources/{test_gate_logical_path}",
                    source,
                    "TEST_GATE_SOURCE",
                    None,
                )
            )
            continue
        files.append(
            _BundleFile(
                f"supplemental/{source.sha256[:16]}--{_safe_basename(source.path)}",
                source,
                "SUPPLEMENTAL",
                _supplemental_schema(source),
            )
        )
    logical_paths = [item.logical_path for item in files]
    if len(logical_paths) != len(set(logical_paths)):
        raise BundleError("bundle logical path collision")
    files.sort(key=lambda item: item.logical_path)

    entries = [
        {
            "bytes": item.source.size,
            "case_id": item.case_id,
            "path": item.logical_path,
            "run_id": item.run_id,
            "schema": item.schema,
            "sha256": item.source.sha256,
            "source_kind": item.source_kind,
        }
        for item in files
    ]
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "status": "PASS",
        "release_label": RELEASE_LABEL,
        "release_label_earned": True,
        "input_mode": "EXPLICIT_PATHS_ONLY_NO_DISCOVERY",
        "network_calls": 0,
        "resource_starts": 0,
        "reruns": 0,
        "gates": {name: aggregate["gates"][name]["status"] for name in GATE_NAMES},
        "aggregate_sha256": aggregate_source.sha256,
        "counts": {
            "aggregate": 1,
            "reports": len(reports),
            "run_artifacts": len(run_artifacts),
            "supplemental_artifacts": len(supplemental),
        },
        "files": entries,
        "entries_sha256": hashlib.sha256(_canonical(entries)).hexdigest(),
        "secret_scan": {
            "status": "PASS",
            "files_scanned": len(files),
            "archive_members_scanned": sum(
                item.source.archive_members_scanned for item in files
            ),
            "archive_uncompressed_bytes": sum(
                item.source.archive_uncompressed_bytes for item in files
            ),
            "raw_secret_persisted": False,
        },
    }
    manifest_raw = _canonical(manifest)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()

    _secure_output_parent(output)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    staging.chmod(0o700)
    try:
        for item in files:
            _write_private(staging / item.logical_path, item.source.raw)
        _write_private(staging / "manifest.json", manifest_raw)
        _seal_bundle(staging, logical_paths)
        directory_descriptor = os.open(
            staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        os.rename(staging, output)
        parent_descriptor = os.open(
            output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if staging.exists():
            _unseal_bundle(staging, logical_paths)
            shutil.rmtree(staging)
    return {
        "status": "PASS",
        "manifest_sha256": manifest_sha256,
        "manifest_bytes": len(manifest_raw),
        "file_count": len(files) + 1,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package explicit DG-13U U1 aggregate evidence without rerunning it"
    )
    parser.add_argument("--aggregate", required=True, type=Path)
    parser.add_argument("--report", required=True, action="append", type=Path)
    parser.add_argument("--artifact", required=True, action="append", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = package_bundle(
            args.aggregate,
            args.report,
            args.artifact,
            args.output_dir,
        )
    except (BundleError, FileExistsError, OSError) as exc:
        print(_canonical({"status": "FAIL", "error": str(exc)}).decode(), end="")
        return 2
    print(_canonical(receipt).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
