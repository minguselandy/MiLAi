"""Shared standard-library artifact JSON IO and digest; atomic bytes are unchanged."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def configure_runtime_directory(directory: Path) -> Path:
    """Choose temporary storage once, before importing database/model runtimes."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(directory).free == 0:
        raise OSError(errno.ENOSPC, "Runtime temporary directory has no free space", str(directory))
    with tempfile.TemporaryFile(dir=directory) as probe:
        probe.write(b"\0")
        probe.flush()
    os.environ.update(TMPDIR=str(directory), SQLITE_TMPDIR=str(directory))
    tempfile.tempdir = str(directory)
    return directory


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
