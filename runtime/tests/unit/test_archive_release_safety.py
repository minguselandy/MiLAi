from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from milai.operations.release_safety import (
    ArchiveScan,
    scan_archive_bytes,
    scan_paths,
    secret_values,
)


def _tar(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, raw in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
        if symlink is not None:
            member = tarfile.TarInfo(symlink)
            member.type = tarfile.SYMTYPE
            member.linkname = "../outside"
            archive.addfile(member)
    return buffer.getvalue()


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries.items():
            archive.writestr(name, raw)
    return buffer.getvalue()


def test_archive_scanner_opens_compressed_and_nested_secrets() -> None:
    secret = b"archive-secret-value-0123456789"
    nested = _zip({"payload.txt": secret})
    raw = _tar({"safe/nested.zip": nested})
    result = scan_archive_bytes("candidate.tar.gz", "candidate.tar.gz", raw, [secret])
    assert result.matching_members == ["candidate.tar.gz!safe/nested.zip!payload.txt"]
    assert result.unsafe_archives == []


def test_archive_scanner_rejects_env_cache_and_links() -> None:
    raw = _tar(
        {
            "package/.env": b"not-a-real-secret",
            "package/.cache/downloader.lock": b"cache",
        },
        symlink="package/link",
    )
    result = scan_archive_bytes("candidate.tar.gz", "candidate.tar.gz", raw, [])
    assert result.forbidden_members == [
        "candidate.tar.gz!package/.env",
        "candidate.tar.gz!package/.cache/downloader.lock",
    ]
    assert result.unsafe_archives == ["candidate.tar.gz!package/link:link"]


def test_archive_scanner_accepts_minimal_source_archive() -> None:
    result = scan_archive_bytes(
        "candidate.tar.gz",
        "candidate.tar.gz",
        _tar({"package/src/module.py": b"VALUE = 1\n"}),
        [b"archive-secret-value-0123456789"],
    )
    assert result == ArchiveScan(member_count=1, uncompressed_bytes=10)


def test_workspace_scan_uses_exact_configured_secret_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    secret = "configured-secret-value-0123456789"
    env_file.write_text(f"MILAI_AGENT_TOKEN={secret}\n", encoding="utf-8")
    safe = tmp_path / "safe.txt"
    safe.write_text("public", encoding="utf-8")
    leaked = tmp_path / "leaked.txt"
    leaked.write_text(secret, encoding="utf-8")

    values = secret_values(env_file)
    result = scan_paths(tmp_path, [safe, leaked], values)

    assert values == [secret.encode()]
    assert result["status"] == "FAIL"
    assert result["matching_paths"] == ["leaked.txt"]
