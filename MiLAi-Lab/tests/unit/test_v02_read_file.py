from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
reader = importlib.import_module("v02_read_file")


@pytest.mark.parametrize("content", ["", " \r\n\t", "中文🙂\n\r\n\t" * 400,
                                     json.dumps({"empty": "", "null": None, "sessions": []}),
                                     "\x00\x01\"\\" * 3000])
def test_pages_recover_exact_bytes_and_never_exceed_wire_limit(
    tmp_path: Path, content: str,
) -> None:
    raw = content.encode()
    (tmp_path / "source.txt").write_bytes(raw)
    offset, sha, recovered = 0, None, b""
    while True:
        result = reader.read_page(tmp_path, "source.txt", offset, 512, sha)
        assert len(reader.encode(result)) <= 512
        assert result["offset"] == len(recovered)
        recovered += result["text"].encode()
        if not result["truncated"]:
            assert result["status"] == "EOF" and result["next"] is None
            break
        assert result["next"]["offset"] > offset
        offset, sha = result["next"]["offset"], result["next"]["sha256"]
    assert recovered == raw


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("keep_optional_edges", [False, True])
def test_field_order_and_optional_edge_removal_preserve_all_remaining_content(
    tmp_path: Path, position: int, keep_optional_edges: bool,
) -> None:
    fields = [("padding_a", "填充🙂\n" * 200), ("padding_b", "x" * 2000)]
    fields.insert(position, ("content", {"text": "有效正文\n", "empty": "", "null": None}))
    if keep_optional_edges:
        fields = [("optional_header", "任意头部"), *fields, ("optional_footer", "任意尾部")]
    expected = dict(fields)
    raw = ("\n" + json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode()
    (tmp_path / "input.json").write_bytes(raw)
    recovered = b""
    offset, sha = 0, None
    while True:
        page = reader.read_page(tmp_path, "input.json", offset, 512, sha)
        assert len(reader.encode(page)) <= 512
        recovered += page["text"].encode()
        if page["next"] is None:
            break
        assert page["next"]["offset"] > offset
        offset, sha = page["next"]["offset"], page["next"]["sha256"]
    assert recovered == raw
    assert json.loads(recovered) == expected
    assert list(json.loads(recovered)) == list(expected)
    assert (tmp_path / "input.json").read_bytes() == raw


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "missing", "."])
def test_paths_fail_explicitly(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        reader.read_page(tmp_path, path)


def test_symlinks_and_changed_source_cannot_cross_page_boundary(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("a" * 5000)
    (tmp_path / "link").symlink_to(source)
    with pytest.raises(ValueError, match="SYMLINK"):
        reader.read_page(tmp_path, "link")
    result = reader.read_page(tmp_path, "source.txt")
    source.write_text("changed")
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        reader.read_page(tmp_path, "source.txt", result["next"]["offset"],
                         expected_sha256=result["source_sha256"])


def test_bad_cursor_encoding_and_limits_are_errors(tmp_path: Path) -> None:
    (tmp_path / "text").write_text("中文")
    first = reader.read_page(tmp_path, "text")
    for kwargs in ({"offset": 1}, {"offset": -1}, {"limit": 511}, {"limit": 16385},
                   {"offset": 1, "expected_sha256": first["source_sha256"]}):
        with pytest.raises(ValueError):
            reader.read_page(tmp_path, "text", **kwargs)
    (tmp_path / "binary").write_bytes(b"\xff")
    with pytest.raises(ValueError, match="UTF8"):
        reader.read_page(tmp_path, "binary")
