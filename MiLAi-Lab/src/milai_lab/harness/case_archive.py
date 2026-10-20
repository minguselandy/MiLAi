"""Lossless closed-case archives using an explicitly retained common base."""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

BLOCK_BYTES = 64 * 1024


def _files(root: Path) -> dict[str, Path]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Case block archives require regular files, not symbolic links")
        if path.is_file():
            files[str(path.relative_to(root))] = path
    return files


def _equal(left: Path, right: Path) -> bool:
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            block = a.read(BLOCK_BYTES)
            if block != b.read(BLOCK_BYTES):
                return False
            if not block:
                return True


def _member(archive: tarfile.TarFile, name: str, stream: IO[bytes], size: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = size
    archive.addfile(info, stream)


def _blocks(
    row: dict[str, Any], base: Path, payload: IO[bytes],
) -> Iterator[bytes]:
    """Reconstruct bytes in order without loading a whole database into memory."""
    source = base / row["path"]
    previous = source.open("rb") if source.exists() else io.BytesIO()
    with previous:
        changed = {block["offset"]: block["size"] for block in row["blocks"]}
        for offset in range(0, row["size"], BLOCK_BYTES):
            size = min(BLOCK_BYTES, row["size"] - offset)
            if offset in changed:
                block = payload.read(changed[offset])
            else:
                previous.seek(offset)
                block = previous.read(size)
            if len(block) != size:
                raise ValueError("Case block archive or required base is incomplete")
            yield block


def archive_case(root: Path, destination: Path, base: Path) -> dict[str, Any]:
    """Store changed fixed-offset blocks; verify every case byte before removal.

    The immutable base is part of the archive collection and must be retained.
    Named positions, lengths and direct byte equality replace no data with a
    content fingerprint. Model results, databases and trace text are unchanged.
    """
    files, base_files = _files(root), _files(base)
    rows: list[dict[str, Any]] = []
    by_size: dict[int, list[str]] = {}
    stored_bytes = 0
    with tarfile.open(destination, "x:gz", compresslevel=6) as archive:
        for number, (name, path) in enumerate(files.items()):
            metadata = path.stat()
            row: dict[str, Any] = {"path": name, "size": metadata.st_size,
                "mode": stat.S_IMODE(metadata.st_mode), "mtime_ns": metadata.st_mtime_ns}
            same = next((other for other in by_size.get(metadata.st_size, [])
                         if _equal(path, files[other])), None)
            if same is not None:
                row["same_as"] = same
                rows.append(row)
                continue
            by_size.setdefault(metadata.st_size, []).append(name)
            row["base_size"] = base_files[name].stat().st_size if name in base_files else None
            row["blocks"] = []
            previous = base_files[name].open("rb") if name in base_files else io.BytesIO()
            with path.open("rb") as current, previous, tempfile.SpooledTemporaryFile(
                max_size=8 * 1024 * 1024,
            ) as payload:
                offset = 0
                while block := current.read(BLOCK_BYTES):
                    if block != previous.read(BLOCK_BYTES):
                        row["blocks"].append({"offset": offset, "size": len(block)})
                        payload.write(block)
                    offset += len(block)
                size = payload.tell()
                if size:
                    row["payload"] = f"blocks/{number}.bin"
                    payload.seek(0)
                    _member(archive, row["payload"], payload, size)
                    stored_bytes += size
            rows.append(row)
        manifest = {"schema": "case_blocks_v1", "block_bytes": BLOCK_BYTES, "files": rows,
            "removed_base_files": sorted(set(base_files) - set(files)),
            "base_requirement": "Retain the unchanged complete base with this collection; "
                                "supply it explicitly on restore. No digest identity is used."}
        encoded = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        _member(archive, "case-blocks.json", io.BytesIO(encoded), len(encoded))

    # The working case remains available if this direct byte check fails.
    with tarfile.open(destination) as archive:
        for row in rows:
            if "same_as" in row:
                if not _equal(files[row["path"]], files[row["same_as"]]):
                    raise ValueError("Closed case changed during archive construction")
                continue
            restored = archive.extractfile(row["payload"]) if "payload" in row else io.BytesIO()
            assert restored is not None
            with restored, files[row["path"]].open("rb") as actual:
                for block in _blocks(row, base, restored):
                    if block != actual.read(len(block)):
                        raise ValueError("Archived case bytes differ from the closed working case")
                if actual.read(1):
                    raise ValueError("Closed case grew during archive construction")
    result = {"archive": str(destination), "base": str(base.resolve()), "format": "case_blocks_v1",
        "files": len(files), "uncompressed_bytes": sum(row["size"] for row in rows),
        "stored_block_bytes": stored_bytes, "archive_bytes": destination.stat().st_size,
        "verification": "Every reconstructed byte compared directly; no SHA/fingerprint",
        "retention": "Full immutable base plus per-case blocks reconstruct all original files."}
    shutil.rmtree(root)
    return result


def restore_case(archive_path: Path, base: Path, destination: Path) -> Path:
    """Restore a fresh independent case; the shared base is never modified."""
    with tarfile.open(archive_path) as archive:
        file = archive.extractfile("case-blocks.json")
        assert file is not None
        with file:
            manifest = json.load(file)
        if manifest["schema"] != "case_blocks_v1" or manifest["block_bytes"] != BLOCK_BYTES:
            raise ValueError("Unsupported case block archive format")
        names = [row["path"] for row in manifest["files"]] + manifest["removed_base_files"]
        names += [row["same_as"] for row in manifest["files"] if "same_as" in row]
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ValueError("Case archive paths must stay inside the restored case")
        _files(base)  # Base symlinks cannot redirect a patch outside this copy.
        shutil.copytree(base, destination)
        for name in manifest["removed_base_files"]:
            (destination / name).unlink()
        for row in manifest["files"]:
            target = destination / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if "same_as" in row:
                shutil.copyfile(destination / row["same_as"], target)
            else:
                source = base / row["path"]
                if row["base_size"] is not None and source.stat().st_size != row["base_size"]:
                    raise ValueError("Required case base has a different file size")
                payload = archive.extractfile(row["payload"]) if "payload" in row else io.BytesIO()
                assert payload is not None
                with payload, target.open("wb") as output:
                    for block in _blocks(row, base, payload):
                        output.write(block)
            os.chmod(target, row["mode"])
            os.utime(target, ns=(row["mtime_ns"], row["mtime_ns"]))
    return destination
