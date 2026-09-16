from __future__ import annotations

import hashlib
import json
from pathlib import Path

from milai_lab.product_adapter.manifest import (
    digest_paths,
    load_product_lock,
    verify_product_lock,
)


def test_product_manifest_binds_tree_and_public_interface(tmp_path: Path) -> None:
    product = tmp_path / "product"
    interface = product / "public"
    implementation = product / "runtime"
    interface.mkdir(parents=True)
    implementation.mkdir()
    (interface / "schema.json").write_text("{}\n", encoding="utf-8")
    (implementation / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    source_manifest = product / "product.manifest.json"
    source_manifest.write_text(
        json.dumps({"schema_version": "milai-product-manifest-v1"}) + "\n",
        encoding="utf-8",
    )
    tree_paths = ("public", "runtime")
    lock_path = tmp_path / "product.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": {
                    "name": "MiLAi-Product",
                    "version": "0.1.0-candidate",
                    "repository": "product",
                    "git_commit": None,
                    "tree_paths": list(tree_paths),
                    "tree_sha256": digest_paths(product, tree_paths),
                },
                "public_interfaces": [
                    {
                        "interface_id": "schema",
                        "path": "public",
                        "sha256": digest_paths(product, ("public",)),
                    }
                ],
                "source_manifest": {
                    "path": "product.manifest.json",
                    "schema_version": "milai-product-manifest-v1",
                    "sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )

    result = verify_product_lock(load_product_lock(lock_path), product)

    assert result.valid
    (implementation / "service.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert not verify_product_lock(load_product_lock(lock_path), product).valid
