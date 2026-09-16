"""Acquisition integrity and secret parser tests using synthetic bytes, no network."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from download_v0218_benchmarks import WMA_REVISION, credential
from verify_v0218_benchmarks import git_blob, local_hf


def test_credential_parser_never_executes_env_text(tmp_path):
    secret = tmp_path / "fixture.env"
    secret.write_text("# synthetic only\nexport HF_TOKEN='synthetic-credential'\n")
    assert credential(secret) == "synthetic-credential"
    secret.write_text("WRONG=first\nSECOND=second\n")
    with pytest.raises(ValueError, match="NO_VALUES_LOGGED"):
        credential(secret)


@pytest.mark.parametrize("lfs", [True, False])
def test_upstream_hash_not_just_size_detects_tampering(tmp_path, lfs):
    target = tmp_path / ("WorldMemArena-" + WMA_REVISION)
    target.mkdir()
    asset = target / "fixture.bin"
    asset.write_bytes(b"good")
    catalog = {
        "revision": WMA_REVISION,
        "expected_files": 1,
        "expected_bytes": 4,
        "files": [
            {
                "path": "fixture.bin",
                "bytes": 4,
                "git_blob": git_blob(asset),
                "lfs_sha256": hashlib.sha256(b"good").hexdigest() if lfs else None,
            }
        ],
    }
    (tmp_path / "wma-upstream-files.json").write_text(json.dumps(catalog))
    assert local_hf(tmp_path, True)["status"] == "UPSTREAM_HASH_VERIFIED_COMPLETE"
    asset.write_bytes(b"evil")
    assert local_hf(tmp_path, False)["size_matched_files"] == 1
    invalid = local_hf(tmp_path, True)
    assert invalid["status"] == "IN_PROGRESS" and invalid["verified_files"] == 0
    assert invalid["mismatches"] == ["fixture.bin"]


def test_missing_file_never_complete(tmp_path):
    catalog = {
        "revision": WMA_REVISION,
        "expected_files": 1,
        "expected_bytes": 4,
        "files": [{"path": "missing.bin", "bytes": 4, "git_blob": "unused", "lfs_sha256": None}],
    }
    (tmp_path / "wma-upstream-files.json").write_text(json.dumps(catalog))
    assert local_hf(tmp_path, True)["status"] == "IN_PROGRESS"
