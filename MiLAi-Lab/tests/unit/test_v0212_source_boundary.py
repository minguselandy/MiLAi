"""Actual Host source boundary: pagination, isolation and existing deadline coexist."""

import hashlib
import json
import signal
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_v0212_horizon import source_call, tool_window
from v02_deadline import Deadline


def test_source_pages_preserve_bytes_and_deny_other_query_and_evaluation(tmp_path: Path) -> None:
    source = tmp_path / "query-a"
    source.mkdir()
    raw = ("角色与时间 remain verbatim.\n" * 500).encode()
    (source / "history.txt").write_bytes(raw)
    (tmp_path / "evaluation.json").write_text('{"correct_letter":"E"}')
    (tmp_path / "query-b.txt").write_text("unrelated writable state")
    frozen = {"history.txt": hashlib.sha256(raw).hexdigest()}
    recovered, offset = bytearray(), 0
    while True:
        page = source_call(source, frozen, "source_read", {"path": "history.txt", "offset": offset})
        recovered.extend(page["text"].encode())
        if page["next"] is None:
            break
        offset = page["next"]["offset"]
    assert recovered == raw
    for forbidden in ("../evaluation.json", "../query-b.txt"):
        with pytest.raises(KeyError):
            source_call(source, frozen, "source_read", {"path": forbidden})
    search = source_call(source, frozen, "source_search", {"queries": ["verbatim"]})
    assert len(json.dumps(search, ensure_ascii=False).encode()) <= 8192
    assert search["next_offset"] == len(search["hits"])
    assert (source / "history.txt").read_bytes() == raw


def test_tool_timeout_window_restores_existing_query_deadline() -> None:
    with Deadline(time.monotonic(), 2) as deadline:
        with tool_window(deadline):
            assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= 2
        assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= 2
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
