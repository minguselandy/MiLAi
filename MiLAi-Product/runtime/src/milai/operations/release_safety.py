from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

EXCLUDED_PARTS = {
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}
FORBIDDEN_ARCHIVE_PARTS = EXCLUDED_PARTS | {
    ".env",
    "backups",
    "dist",
    "models-cache",
    "var",
}
MAX_ARCHIVE_DEPTH = 3
MAX_ARCHIVE_MEMBERS = 10_000
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


@dataclass
class ArchiveScan:
    matching_members: list[str] = field(default_factory=list)
    forbidden_members: list[str] = field(default_factory=list)
    unsafe_archives: list[str] = field(default_factory=list)
    member_count: int = 0
    uncompressed_bytes: int = 0


def secret_values(env_file: Path) -> list[bytes]:
    values: list[bytes] = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if (
            any(
                marker in name
                for marker in ("TOKEN", "PASSWORD", "SECRET", "KEK_B64", "DATABASE_URL")
            )
            and len(value) >= 16
        ):
            values.append(value.encode())
    return sorted(set(values))


def archive_kind(name: str) -> str | None:
    lowered = name.lower()
    if lowered.endswith((".whl", ".zip")):
        return "zip"
    if lowered.endswith((".tar.gz", ".tgz", ".tar")):
        return "tar"
    return None


def _safe_member_path(name: str) -> PurePosixPath | None:
    if "\\" in name:
        return None
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return None
    return path


def _forbidden_member(path: PurePosixPath) -> bool:
    return bool(FORBIDDEN_ARCHIVE_PARTS.intersection(path.parts)) or path.name.endswith(".log")


def _record_member(
    state: ArchiveScan,
    label: str,
    member_name: str,
    raw: bytes,
    secrets: list[bytes],
    depth: int,
) -> None:
    member_label = f"{label}!{member_name}"
    path = _safe_member_path(member_name)
    if path is None:
        state.unsafe_archives.append(f"{member_label}:unsafe-path")
        return
    state.member_count += 1
    state.uncompressed_bytes += len(raw)
    if state.member_count > MAX_ARCHIVE_MEMBERS:
        state.unsafe_archives.append(f"{label}:member-limit-exceeded")
        return
    if len(raw) > MAX_MEMBER_BYTES:
        state.unsafe_archives.append(f"{member_label}:member-size-limit-exceeded")
        return
    if state.uncompressed_bytes > MAX_TOTAL_UNCOMPRESSED_BYTES:
        state.unsafe_archives.append(f"{label}:uncompressed-size-limit-exceeded")
        return
    if _forbidden_member(path):
        state.forbidden_members.append(member_label)
    if any(secret in raw for secret in secrets):
        state.matching_members.append(member_label)
    nested_kind = archive_kind(path.name)
    if nested_kind is not None:
        if depth >= MAX_ARCHIVE_DEPTH:
            state.unsafe_archives.append(f"{member_label}:archive-depth-limit-exceeded")
        else:
            scan_archive_bytes(
                member_label,
                path.name,
                raw,
                secrets,
                state=state,
                depth=depth + 1,
            )


def _scan_zip(
    label: str,
    raw: bytes,
    secrets: list[bytes],
    state: ArchiveScan,
    depth: int,
) -> None:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_label = f"{label}!{member.filename}"
            file_type = (member.external_attr >> 16) & 0o170000
            if file_type == stat.S_IFLNK:
                state.unsafe_archives.append(f"{member_label}:symlink")
                continue
            if member.flag_bits & 0x1:
                state.unsafe_archives.append(f"{member_label}:encrypted")
                continue
            if member.file_size > MAX_MEMBER_BYTES:
                state.unsafe_archives.append(f"{member_label}:member-size-limit-exceeded")
                continue
            _record_member(
                state,
                label,
                member.filename,
                archive.read(member),
                secrets,
                depth,
            )


def _scan_tar(
    label: str,
    raw: bytes,
    secrets: list[bytes],
    state: ArchiveScan,
    depth: int,
) -> None:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        for member in archive.getmembers():
            member_label = f"{label}!{member.name}"
            if member.issym() or member.islnk():
                state.unsafe_archives.append(f"{member_label}:link")
                continue
            if not member.isfile():
                continue
            if member.size > MAX_MEMBER_BYTES:
                state.unsafe_archives.append(f"{member_label}:member-size-limit-exceeded")
                continue
            handle = archive.extractfile(member)
            if handle is None:
                state.unsafe_archives.append(f"{member_label}:unreadable")
                continue
            _record_member(
                state,
                label,
                member.name,
                handle.read(MAX_MEMBER_BYTES + 1),
                secrets,
                depth,
            )


def scan_archive_bytes(
    label: str,
    name: str,
    raw: bytes,
    secrets: list[bytes],
    *,
    state: ArchiveScan | None = None,
    depth: int = 0,
) -> ArchiveScan:
    result = state or ArchiveScan()
    kind = archive_kind(name)
    if kind is None:
        return result
    try:
        if kind == "zip":
            _scan_zip(label, raw, secrets, result, depth)
        else:
            _scan_tar(label, raw, secrets, result, depth)
    except (OSError, tarfile.TarError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        result.unsafe_archives.append(f"{label}:invalid-archive:{type(exc).__name__}")
    return result


def scan_paths(root: Path, files: list[Path], secrets: list[bytes]) -> dict[str, object]:
    matches: list[str] = []
    scanned_bytes = 0
    archive_scan = ArchiveScan()
    for path in files:
        raw = path.read_bytes()
        scanned_bytes += len(raw)
        relative = path.relative_to(root).as_posix()
        if any(secret in raw for secret in secrets):
            matches.append(relative)
        if archive_kind(path.name) is not None:
            scan_archive_bytes(relative, path.name, raw, secrets, state=archive_scan)
    failures = bool(
        matches
        or archive_scan.matching_members
        or archive_scan.forbidden_members
        or archive_scan.unsafe_archives
    )
    return {
        "schema": "milai.archive-aware-secret-scan.v1",
        "status": "FAIL" if failures else "PASS",
        "secret_value_count": len(secrets),
        "file_count": len(files),
        "scanned_bytes": scanned_bytes,
        "matching_paths": matches,
        "archive_member_count": archive_scan.member_count,
        "archive_uncompressed_bytes": archive_scan.uncompressed_bytes,
        "matching_archive_members": archive_scan.matching_members,
        "forbidden_archive_members": archive_scan.forbidden_members,
        "unsafe_archives": archive_scan.unsafe_archives,
    }
