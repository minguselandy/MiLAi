from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
search = importlib.import_module("v02_search_files")
state = importlib.import_module("v02_e2e_state")
runner = importlib.import_module("run_v02_local_vllm")


def test_search_reaches_tail_literal_utf8_and_progresses_without_source_mutation(tmp_path):
    raw = ("中文 " + "x" * 10000 + " A+B " * 20 + " FINAL").encode()
    (tmp_path / "history.txt").write_bytes(raw)
    frozen = {"history.txt": hashlib.sha256(raw).hexdigest()}
    first = search.search_files(tmp_path, frozen, ["a+b", "final"])
    assert len(first["hits"]) == 16 and first["status"] == "MORE"
    second = search.search_files(tmp_path, frozen, ["a+b", "final"], first["next_offset"])
    assert len(second["hits"]) == 5 and second["status"] == "EOF"
    hits = [*first["hits"], *second["hits"]]
    assert len({h["match_byte_offset"] for h in hits}) == 21
    assert raw[hits[-1]["match_byte_offset"]:].startswith(b"FINAL")
    assert (tmp_path / "history.txt").read_bytes() == raw
    (tmp_path / "history.txt").write_text("changed")
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        search.search_files(tmp_path, frozen, ["changed"])


def test_search_checks_permissions_before_read_and_again_before_reuse(tmp_path):
    raw = b"private canary"
    (tmp_path / "secret.txt").write_bytes(raw)
    revoked = True

    def metadata(ref):
        return {"evidence_id": ref, "retention_state": "READABLE",
                "revoked_at": "now" if revoked else None,
                "permission_snapshot": {"readable": True, "project_ids": ["p"]}}

    guard = state.FileDisclosure("p", {"secret.txt": ["ref"]}, metadata)
    frozen = {"secret.txt": hashlib.sha256(raw).hexdigest()}
    # Removing the file proves denial happens before any open attempt.
    (tmp_path / "secret.txt").unlink()
    assert search.search_files(tmp_path, frozen, ["canary"], disclosure=guard)["hits"] == []
    (tmp_path / "secret.txt").write_bytes(raw)
    revoked = False
    assert search.search_files(tmp_path, frozen, ["canary"], disclosure=guard)["hits"]
    revoked = True
    with pytest.raises(state.LocalGateError, match="FILE_DISCLOSURE_DENIED"):
        guard.before_request()


def test_search_is_opt_in_and_does_not_mutate_legacy_protocol():
    for mode in ("JSON_STRING", "ARGUMENT_OBJECT"):
        config = {"host_action_format": mode, "file_search_enabled": True}
        system, schema = runner.host_protocol(config)
        assert "search_files" in system
        assert "search_files" in schema["properties"]["tool"]["enum"]
        _, old = runner.host_protocol({"host_action_format": mode})
        assert "search_files" not in old["properties"]["tool"]["enum"]
