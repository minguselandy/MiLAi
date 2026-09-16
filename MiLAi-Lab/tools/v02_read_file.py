#!/usr/bin/env python3
"""Read exact UTF-8 file pages within the task workspace, with a bounded JSON response."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

DEFAULT_LIMIT = 4096
MAX_LIMIT = 16384


def encode(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def read_page(root: Path, relative: str, offset: int = 0, limit: int = DEFAULT_LIMIT,
              expected_sha256: str | None = None, *, max_file_bytes: int | None = None) -> dict:
    if not 512 <= limit <= MAX_LIMIT:
        raise ValueError("OUTPUT_LIMIT_RANGE_512_16384")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("WORKSPACE_RELATIVE_PATH_REQUIRED")
    root = root.resolve(strict=True)
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("SYMLINK_NOT_ALLOWED")
    if not current.resolve().is_relative_to(root):
        raise ValueError("PATH_OUTSIDE_WORKSPACE")
    if not current.is_file():
        raise ValueError("FILE_NOT_FOUND_OR_NOT_REGULAR")
    with current.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if max_file_bytes is None:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        else:
            if type(max_file_bytes) is not int or max_file_bytes < 0 \
                    or before.st_size > max_file_bytes:
                raise ValueError("SOURCE_EXCEEDS_FILE_READ_BOUND")
            body = stream.read(max_file_bytes + 1)
            if len(body) > max_file_bytes:
                raise ValueError("SOURCE_EXCEEDS_FILE_READ_BOUND")
            sha = hashlib.sha256(body).hexdigest()
        if expected_sha256 is not None and expected_sha256 != sha:
            raise ValueError("SOURCE_CHANGED")
        if offset < 0 or offset > before.st_size or (offset and not expected_sha256):
            raise ValueError("INVALID_OFFSET_OR_MISSING_SOURCE_HASH")
        stream.seek(offset)
        raw = stream.read(limit)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("SOURCE_CHANGED_DURING_READ")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason != "unexpected end of data" or offset + len(raw) == before.st_size:
            raise ValueError("INVALID_UTF8_OR_OFFSET") from exc
        text = raw[:exc.start].decode("utf-8")
    while True:
        next_offset = offset + len(text.encode())
        more = next_offset < before.st_size
        result = {"schema_version": 1, "status": "MORE" if more else "EOF",
                  "path": path.as_posix(), "source_sha256": sha,
                  "total_bytes": before.st_size, "offset": offset, "text": text,
                  "truncated": more, "max_output_bytes": limit,
                  "next": {"offset": next_offset, "sha256": sha} if more else None}
        if len(encode(result)) <= limit and (text or not more):
            return result
        if not text:
            raise ValueError("OUTPUT_LIMIT_TOO_SMALL_FOR_METADATA")
        text = text[:len(text) // 2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path relative to the task workspace")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--sha256", help="Required when continuing from a nonzero offset")
    args = parser.parse_args()
    try:
        result = read_page(Path(os.environ.get("V02_WORKSPACE", os.getcwd())), args.path,
                           args.offset, args.max_bytes, args.sha256)
    except (OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(encode({"status": "ERROR", "reason": message}).decode(), end="")
        raise SystemExit(2) from None
    print(encode(result).decode(), end="")


if __name__ == "__main__":
    main()
