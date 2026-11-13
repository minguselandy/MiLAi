"""Lossless byte deltas for closed checkpoints, against an explicitly retained base."""
from __future__ import annotations

import gzip
import json
import os
import stat
from pathlib import Path

import numpy as np

CHUNK = 8 * 1024 * 1024


def xor_bytes(left: bytes, right: bytes) -> bytes:
    if len(left) != len(right):
        raise ValueError("Incomplete checkpoint base or delta")
    return np.bitwise_xor(np.frombuffer(left, dtype=np.uint8),
                         np.frombuffer(right, dtype=np.uint8)).tobytes()


def archive_weight(weight: Path, base: Path, destination: Path) -> dict:
    """Verify every reconstructed byte, persist restoration metadata, then remove weight.

    The caller must ensure the model run is closed and retain the immutable base.
    This is an opaque byte transform, never numeric rounding or tensor conversion.
    """
    original, base_stat = weight.stat(), base.stat()
    if original.st_size != base_stat.st_size or original.st_nlink != 1:
        raise ValueError("Require equal-size immutable base and singly linked closed target")
    metadata = destination.with_suffix(".json")
    if metadata.exists() or destination.exists():
        raise FileExistsError("Archive destination already exists")
    with weight.open("rb") as source, base.open("rb") as anchor, gzip.open(
            destination, "xb", compresslevel=6) as output:
        while block := source.read(CHUNK):
            output.write(xor_bytes(block, anchor.read(len(block))))
        if anchor.read(1):
            raise ValueError("Checkpoint base grew during archive creation")
    with destination.open("rb") as archive:
        os.fsync(archive.fileno())
    with weight.open("rb") as source, base.open("rb") as anchor, gzip.open(
            destination, "rb") as delta:
        while block := source.read(CHUNK):
            if xor_bytes(anchor.read(len(block)), delta.read(len(block))) != block:
                raise ValueError("Reconstructed checkpoint differs from original bytes")
        if anchor.read(1) or delta.read(1):
            raise ValueError("Unexpected trailing checkpoint bytes")
    for path, before in ((weight, original), (base, base_stat)):
        after = path.stat()
        if (after.st_ino, after.st_size, after.st_mtime_ns) != (
                before.st_ino, before.st_size, before.st_mtime_ns):
            raise ValueError("Closed checkpoint changed while being archived")
    record = {"schema": "closed_weight_xor_gzip_v1", "original_path": str(weight.resolve()),
        "base": str(base.resolve()), "delta": str(destination.resolve()),
        "logical_bytes": original.st_size, "mode": stat.S_IMODE(original.st_mode),
        "mtime_ns": original.st_mtime_ns, "original_allocated_bytes": original.st_blocks * 512,
        "delta_bytes": destination.stat().st_size,
        "delta_allocated_bytes": destination.stat().st_blocks * 512,
        "verification": "Every reconstructed byte compared directly before original removal",
        "no_sha_validation": True}
    # A crash after removal still leaves both the payload and its restoration record.
    with metadata.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    weight.unlink()
    return {**record, "metadata": str(metadata.resolve())}


def restore_weight(metadata: Path, destination: Path | None = None) -> Path:
    """Restore a fresh file; refuse to replace any existing checkpoint."""
    record = json.loads(metadata.read_text())
    if record["schema"] != "closed_weight_xor_gzip_v1":
        raise ValueError("Unknown checkpoint delta format")
    base, delta_path = Path(record["base"]), Path(record["delta"])
    if base.stat().st_size != record["logical_bytes"]:
        raise ValueError("Retained checkpoint base has wrong size")
    target = destination if destination is not None else Path(record["original_path"])
    temporary = target.with_name(target.name + ".restore-tmp")
    if target.exists() or temporary.exists():
        raise FileExistsError("Refusing to overwrite an existing checkpoint or restore file")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with base.open("rb") as anchor, gzip.open(delta_path, "rb") as delta, temporary.open(
                "xb") as output:
            while block := anchor.read(CHUNK):
                output.write(xor_bytes(block, delta.read(len(block))))
            if delta.read(1):
                raise ValueError("Unexpected trailing checkpoint delta bytes")
        if temporary.stat().st_size != record["logical_bytes"]:
            raise ValueError("Restored checkpoint has wrong size")
        os.chmod(temporary, record["mode"])
        os.utime(temporary, ns=(record["mtime_ns"], record["mtime_ns"]))
        # link is exclusive even if another process created target after the initial check.
        os.link(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
