#!/usr/bin/env python3
"""Build the non-self-referential source identity for MiLAi Product."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA = "milai-product-manifest-v1"
SOURCE_LEGACY_HEAD = "651099ba8cffc2675961bb9250ba44c158efccb5"
TREE_PATHS = (
    "VERSION",
    "architecture/v1.0",
    "contracts/agent/v1",
    "runtime/pyproject.toml",
    "runtime/uv.lock",
    "runtime/migrations",
    "runtime/src",
    "integrations/python-client/pyproject.toml",
    "integrations/python-client/uv.lock",
    "integrations/python-client/src",
    "integrations/mcp/pyproject.toml",
    "integrations/mcp/uv.lock",
    "integrations/mcp/src",
    "integrations/openworker-mcp/pyproject.toml",
    "integrations/openworker-mcp/uv.lock",
    "integrations/openworker-mcp/src",
    "integrations/openworker-mcp/openworker",
    "integrations/openworker-mcp/build_dg13u_u1_image.sh",
    "integrations/hooks/pyproject.toml",
    "integrations/hooks/uv.lock",
    "integrations/hooks/src",
    "integrations/langgraph/pyproject.toml",
    "integrations/langgraph/uv.lock",
    "integrations/langgraph/src",
    "integrations/autogen/pyproject.toml",
    "integrations/autogen/uv.lock",
    "integrations/autogen/src",
)
PUBLIC_INTERFACES = {
    "agent-contract-v1": "contracts/agent/v1",
    "context-testkit-v0.1": "runtime/src/milai/testkit",
    "retrieval-trace-testkit-v0.1": "runtime/src/milai/testkit",
    "python-client-v0.1": "integrations/python-client/src",
    "mcp-v0.1": "integrations/mcp/src",
    "openworker-mcp-v0.1": "integrations/openworker-mcp/src",
    "hooks-v0.1": "integrations/hooks/src",
    "langgraph-v0.1": "integrations/langgraph/src",
    "autogen-v0.1": "integrations/autogen/src",
}
IGNORED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "backups",
        "build",
        "dist",
        "logs",
        "var",
        "wheelhouse",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path, relative_paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for relative in relative_paths:
        target = root / relative
        if target.is_file():
            files.append(target)
            continue
        if not target.is_dir():
            raise FileNotFoundError(f"required product path is absent: {relative}")
        for candidate in target.rglob("*"):
            if not candidate.is_file():
                continue
            product_relative = candidate.relative_to(root)
            if any(part in IGNORED_PARTS for part in product_relative.parts):
                continue
            if candidate.suffix in {".pyc", ".pyo"}:
                continue
            files.append(candidate)
    return sorted(set(files), key=lambda item: item.relative_to(root).as_posix())


def _records(root: Path, relative_paths: Sequence[str]) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in _files(root, relative_paths)
    ]


def _digest_records(records: Iterable[dict[str, object]]) -> str:
    identity_records = [
        {"path": record["path"], "sha256": record["sha256"]} for record in records
    ]
    return hashlib.sha256(_canonical(identity_records)).hexdigest()


def build_manifest(root: Path) -> dict[str, object]:
    tree_records = _records(root, TREE_PATHS)
    interfaces = []
    for interface_id, path in sorted(PUBLIC_INTERFACES.items()):
        records = _records(root, (path,))
        interfaces.append(
            {
                "interface_id": interface_id,
                "path": path,
                "file_count": len(records),
                "sha256": _digest_records(records),
            }
        )
    return {
        "schema_version": SCHEMA,
        "product_name": "MiLAi-Product",
        "product_version": (root / "VERSION").read_text(encoding="utf-8").strip(),
        # Migration provenance is part of this Product snapshot, not a runtime
        # dependency on the sibling archive repository.
        "source_legacy_head": SOURCE_LEGACY_HEAD,
        "tree_paths": list(TREE_PATHS),
        "tree_file_count": len(tree_records),
        "tree_sha256": _digest_records(tree_records),
        "public_interfaces": interfaces,
        "manifest_self_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the checked-in manifest instead of rewriting it",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / "product.manifest.json").resolve()
    payload = build_manifest(root)
    if args.check:
        if not output.is_file():
            print(f"manifest is missing: {output}")
            return 1
        checked_in = json.loads(output.read_text(encoding="utf-8"))
        if checked_in != payload:
            print("product.manifest.json is stale; regenerate it with build_product_manifest.py")
            print(json.dumps({"checked_in": checked_in, "expected": payload}, indent=2, sort_keys=True))
            return 1
        print(json.dumps({key: payload[key] for key in ("tree_file_count", "tree_sha256")}))
        return 0
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(json.dumps({key: payload[key] for key in ("tree_file_count", "tree_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
