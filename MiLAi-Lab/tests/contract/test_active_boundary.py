from __future__ import annotations

from pathlib import Path

from milai_lab.boundary import scan_active_source


def test_active_package_has_no_private_product_imports() -> None:
    root = Path(__file__).parents[2] / "src" / "milai_lab"

    assert scan_active_source(root) == ()

