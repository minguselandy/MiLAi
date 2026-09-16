"""Full-page extraction contract without optional PDF package in default test environment."""

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_pdf_layout import full_pdf_text, normalize_horizontal_space


def test_whitespace_only_normalization_preserves_lines_and_values():
    assert normalize_horizontal_space("  Revenue   9.240\n contrary\t9.370 \n") == (
        "Revenue 9.240\n contrary 9.370"
    )


def test_all_pages_same_layout_mode_no_selected_pages(monkeypatch):
    seen = []

    class Page:
        def __init__(self, value):
            self.value = value

        def extract_text(self, **kwargs):
            seen.append(kwargs)
            return self.value

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(
        PdfReader=lambda _: SimpleNamespace(pages=[Page("Old  fact"), Page("Contrary  fact")])
    ))
    assert full_pdf_text(b"fixture", hashlib.sha256(b"fixture").hexdigest()) == [
        "Old fact", "Contrary fact"]
    assert seen == [{"extraction_mode": "layout"}] * 2


def test_wrong_hash_before_parser():
    with pytest.raises(ValueError, match="SOURCE_HASH_CHANGED"):
        full_pdf_text(b"fixture", "wrong")
