"""Exact recovery against a shared base, including changed, new, truncated and deleted files."""
import io
import json
import shutil
import tarfile

import pytest

from milai_lab.harness.case_archive import BLOCK_BYTES, archive_case, restore_case


def contents(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_changed_blocks_and_identical_outputs_reconstruct_every_original_byte(tmp_path):
    base, case = tmp_path / "base", tmp_path / "case"
    base.mkdir()
    (base / "memory.sqlite").write_bytes(b"A" * BLOCK_BYTES + b"B" * BLOCK_BYTES
                                        + b"C" * BLOCK_BYTES)
    (base / "unchanged.json").write_bytes(b'{"source":"literal common corpus"}\n')
    (base / "deleted.txt").write_bytes(b"deleted only in this case")
    original_base = contents(base)
    shutil.copytree(base, case)
    (case / "memory.sqlite").write_bytes(b"A" * BLOCK_BYTES + b"Z" * BLOCK_BYTES + b"C" * 11)
    (case / "deleted.txt").unlink()
    output = ("原始输出🙂\n" * 1000).encode()
    (case / "attempt.json").write_bytes(output)
    (case / "result.json").write_bytes(output)
    expected = contents(case)
    destination = tmp_path / "case.tar.gz"
    report = archive_case(case, destination, base)
    assert not case.exists()
    restored = restore_case(destination, base, tmp_path / "restored")
    assert contents(restored) == expected
    assert contents(base) == original_base
    assert report["stored_block_bytes"] == BLOCK_BYTES + 11 + len(output)
    with tarfile.open(destination) as archive:
        manifest = json.load(archive.extractfile("case-blocks.json"))
    result = next(row for row in manifest["files"] if row["path"] == "result.json")
    assert result["same_as"] == "attempt.json"


def test_failed_byte_verification_preserves_the_original_case(tmp_path, monkeypatch):
    import milai_lab.harness.case_archive as module

    base, case = tmp_path / "base", tmp_path / "case"
    base.mkdir()
    case.mkdir()
    (case / "raw-output").write_bytes(b"original raw bytes")
    original = module._member

    def corrupt(archive, name, stream, size):
        if name.startswith("blocks/"):
            body = stream.read()
            stream = io.BytesIO(b"X" + body[1:])
        original(archive, name, stream, size)

    monkeypatch.setattr(module, "_member", corrupt)
    with pytest.raises(ValueError, match="Archived case bytes differ"):
        archive_case(case, tmp_path / "broken.tar.gz", base)
    assert (case / "raw-output").read_bytes() == b"original raw bytes"


def test_restore_requires_the_retained_base_and_a_fresh_destination(tmp_path):
    base, case = tmp_path / "base", tmp_path / "case"
    base.mkdir()
    (base / "unchanged").write_bytes(b"retained base")
    shutil.copytree(base, case)
    archive = tmp_path / "case.tar.gz"
    archive_case(case, archive, base)
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        restore_case(archive, base, destination)
    (base / "unchanged").write_bytes(b"different size")
    with pytest.raises(ValueError, match="base has a different file size"):
        restore_case(archive, base, tmp_path / "wrong-base")
