from __future__ import annotations

import hashlib
from pathlib import Path

from milai_lab.product_adapter.manifest import load_product_lock


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_checked_in_product_lock_is_complete() -> None:
    root = Path(__file__).parents[2]
    lock = load_product_lock(root / "product.lock.json")

    assert lock.product_name == "MiLAi-Product"
    assert len(lock.tree_sha256) == 64
    assert len(lock.public_interfaces) == 7
    assert all(len(item.sha256) == 64 for item in lock.public_interfaces)
    assert lock.source_manifest is not None


def test_user_modified_dg13u_files_are_preserved_exactly() -> None:
    root = Path(__file__).parents[2]
    preserved = root / "studies" / "archive" / "dg" / "dg13u_user_preserved"

    assert _sha256(preserved / "scripts" / "dg13u_u1_review.py") == (
        "5b297e995a87240b0bb9161a031aa34170bd0db97c10d954c77a4b9ca8b95bad"
    )
    assert _sha256(preserved / "tests" / "test_dg13u_u1_review.py") == (
        "3404142e970ea68aa6b418a1d38d8408f46f2e8053cf3463afa8e5950fe0fa25"
    )
