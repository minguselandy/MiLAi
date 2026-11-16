"""Closed weight storage preserves exact bytes and refuses incomplete or overwritten restores."""
import os

import pytest

from milai_lab.harness.weight_delta_archive import archive_weight, restore_weight


def test_delta_roundtrip_preserves_bytes_metadata_and_retained_base(tmp_path):
    base, target = tmp_path / "base", tmp_path / "target"
    anchor = bytes(range(256)) * 600
    expected = b"different header" + anchor[16:-5] + b"tail!"
    base.write_bytes(anchor)
    target.write_bytes(expected)
    target.chmod(0o640)
    os.utime(target, ns=(1234567890000000000, 1234567890000000000))
    report = archive_weight(target, base, tmp_path / "checkpoint.xor.gz")
    assert not target.exists() and base.read_bytes() == anchor
    metadata = tmp_path / "checkpoint.xor.json"
    assert restore_weight(metadata) == target
    assert target.read_bytes() == expected and target.stat().st_mode & 0o777 == 0o640
    assert target.stat().st_mtime_ns == report["mtime_ns"]
    with pytest.raises(FileExistsError):
        restore_weight(metadata)
    assert target.read_bytes() == expected


def test_truncated_delta_cannot_publish_a_partial_checkpoint(tmp_path):
    base, target = tmp_path / "base", tmp_path / "target"
    base.write_bytes(b"a" * 10000)
    target.write_bytes(b"b" * 10000)
    delta = tmp_path / "checkpoint.xor.gz"
    archive_weight(target, base, delta)
    delta.write_bytes(delta.read_bytes()[:-8])
    with pytest.raises((EOFError, ValueError)):
        restore_weight(tmp_path / "checkpoint.xor.json")
    assert not target.exists() and not list(tmp_path.glob("*.restore-tmp"))


def test_wrong_size_or_shared_target_is_not_removed(tmp_path):
    base, target = tmp_path / "base", tmp_path / "target"
    base.write_bytes(b"base")
    target.write_bytes(b"different size")
    with pytest.raises(ValueError):
        archive_weight(target, base, tmp_path / "first.gz")
    target.write_bytes(b"same")
    os.link(target, tmp_path / "alias")
    with pytest.raises(ValueError):
        archive_weight(target, base, tmp_path / "second.gz")
    assert target.read_bytes() == b"same"
