from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from milai.adapters.blob_store import LocalContentAddressedBlobStore
from milai.observability.metrics import OperationTimer, request_operation_timer


@pytest.mark.parametrize("timing", [False, True])
def test_save_syncs_content_before_publication_and_directory_chain_on_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timing: bool
) -> None:
    tenant = uuid4()
    root = tmp_path / "blobs"
    store = LocalContentAddressedBlobStore(root)
    events: list[tuple[str, Path]] = []
    real_sync, real_replace = os.fsync, os.replace

    def sync(fd: int) -> None:
        events.append(("sync", Path(os.readlink(f"/proc/self/fd/{fd}"))))
        real_sync(fd)

    def replace(source: Path, target: Path) -> None:
        events.append(("replace", target))
        real_replace(source, target)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    timer = OperationTimer()
    token = request_operation_timer.set(timer if timing else None)
    try:
        receipt = store.write(tenant, b"first\ncomplete content\nlast")
    finally:
        request_operation_timer.reset(token)
    if timing:
        assert timer.counts == {"blob_write_ms": 1, "blob_lock_wait_ms": 1,
                                "blob_encode_ms": 1, "blob_file_sync_ms": 1,
                                "blob_directory_sync_ms": 4}
        assert timer.duration("blob_write_ms") >= timer.duration("blob_file_sync_ms")
    else:
        assert not timer.counts
    target = root / str(tenant) / receipt.content_hash[:2] / receipt.content_hash
    assert events[0][0] == "sync" and events[0][1].name.startswith(".staging-")
    assert events[1] == ("replace", target)
    directories = [target.parent, target.parent.parent, root, tmp_path]
    assert events[2:] == [("sync", p) for p in directories]
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    events.clear()
    assert store.write(tenant, b"first\ncomplete content\nlast").created is False
    assert events == [("sync", p) for p in [target, *directories]]


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_failed_directory_sync_never_returns_receipt_and_explicit_replay_resyncs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    tenant = uuid4()
    root = tmp_path / "blobs"
    store = LocalContentAddressedBlobStore(root)
    real_sync = os.fsync
    directories = 0

    def sync(fd: int) -> None:
        nonlocal directories
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directories += 1
            if directories == fail_at:
                raise OSError("injected directory sync failure")
        real_sync(fd)

    monkeypatch.setattr(os, "fsync", sync)
    timer = OperationTimer()
    token = request_operation_timer.set(timer)
    try:
        with pytest.raises(OSError, match="injected directory"):
            store.write(tenant, b"retained unconfirmed content")
    finally:
        request_operation_timer.reset(token)
    assert timer.counts["blob_write_ms"] == 1
    assert timer.counts["blob_directory_sync_ms"] == fail_at
    assert not list(root.rglob(".staging-*"))
    receipt = store.write(tenant, b"retained unconfirmed content")
    assert receipt.created is False
    assert directories == fail_at + 4
    assert store.read(tenant, receipt.storage_uri, receipt.content_hash, receipt.byte_length) == (
        b"retained unconfirmed content"
    )
