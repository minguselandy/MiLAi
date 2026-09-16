from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from milai_lab.product_adapter.manifest import digest_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a reviewable MiLAi product lock")
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--repository", default="../MiLAi-Product")
    parser.add_argument("--version")
    parser.add_argument("--tree-path", action="append")
    parser.add_argument(
        "--product-manifest",
        type=Path,
        help="consume the Product-owned manifest instead of duplicating its path list",
    )
    parser.add_argument(
        "--interface",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="public interface identifier and product-relative path",
    )
    parser.add_argument("--output", type=Path, default=Path("product.lock.json"))
    args = parser.parse_args()
    root = args.product_root.resolve()
    source_manifest = None
    if args.product_manifest is not None:
        manifest_path = args.product_manifest.resolve()
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = str(raw_manifest["product_version"])
        tree_paths = [str(value) for value in raw_manifest["tree_paths"]]
        interfaces = list(raw_manifest["public_interfaces"])
        observed_tree = digest_paths(root, tree_paths)
        if observed_tree != raw_manifest["tree_sha256"]:
            parser.error("Product-owned manifest does not match the current product tree")
        source_manifest = {
            "path": manifest_path.relative_to(root).as_posix(),
            "schema_version": str(raw_manifest["schema_version"]),
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }
    else:
        if not args.version or not args.tree_path:
            parser.error("--version and --tree-path are required without --product-manifest")
        version = args.version
        tree_paths = args.tree_path
        interfaces = []
        for value in args.interface:
            interface_id, separator, path = value.partition("=")
            if not separator or not interface_id or not path:
                parser.error(f"invalid interface value: {value}")
            interfaces.append(
                {
                    "interface_id": interface_id,
                    "path": path,
                    "sha256": digest_paths(root, (path,)),
                }
            )
    payload = {
        "schema_version": 1,
        "product": {
            "name": "MiLAi-Product",
            "version": version,
            "repository": args.repository,
            "git_commit": os.environ.get("MILAI_PRODUCT_COMMIT"),
            "tree_paths": tree_paths,
            "tree_sha256": digest_paths(root, tree_paths),
        },
        "public_interfaces": interfaces,
    }
    if source_manifest is not None:
        payload["source_manifest"] = source_manifest
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
