from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_IGNORED_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "artifacts",
        "build",
        "dist",
        "logs",
        "var",
    }
)
_IGNORED_SUFFIXES = (".pyc", ".pyo")


@dataclass(frozen=True, slots=True)
class PublicInterfacePin:
    interface_id: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceManifestPin:
    path: str
    schema_version: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ProductLock:
    schema_version: int
    product_name: str
    product_version: str
    repository: str
    git_commit: str | None
    tree_paths: tuple[str, ...]
    tree_sha256: str
    public_interfaces: tuple[PublicInterfacePin, ...]
    source_manifest: SourceManifestPin | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "product": {
                "name": self.product_name,
                "version": self.product_version,
                "repository": self.repository,
                "git_commit": self.git_commit,
                "tree_paths": list(self.tree_paths),
                "tree_sha256": self.tree_sha256,
            },
            "public_interfaces": [
                {
                    "interface_id": item.interface_id,
                    "path": item.path,
                    "sha256": item.sha256,
                }
                for item in self.public_interfaces
            ],
        }
        if self.source_manifest is not None:
            result["source_manifest"] = {
                "path": self.source_manifest.path,
                "schema_version": self.source_manifest.schema_version,
                "sha256": self.source_manifest.sha256,
            }
        return result


@dataclass(frozen=True, slots=True)
class ProductVerification:
    valid: bool
    product_root: str
    lock_digest: str
    observed_tree_sha256: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "product_root": self.product_root,
            "lock_digest": self.lock_digest,
            "observed_tree_sha256": self.observed_tree_sha256,
            "errors": list(self.errors),
        }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _included_files(root: Path, relative_paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for relative in relative_paths:
        target = root / relative
        if target.is_file():
            files.append(target)
            continue
        if not target.is_dir():
            continue
        for candidate in target.rglob("*"):
            if not candidate.is_file():
                continue
            relative_candidate = candidate.relative_to(root)
            if any(part in _IGNORED_NAMES for part in relative_candidate.parts):
                continue
            if candidate.name.endswith(_IGNORED_SUFFIXES):
                continue
            files.append(candidate)
    return sorted(set(files), key=lambda item: item.relative_to(root).as_posix())


def digest_paths(root: Path, relative_paths: Sequence[str]) -> str:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
        }
        for path in _included_files(root, relative_paths)
    ]
    return hashlib.sha256(_canonical_json(records)).hexdigest()


def load_product_lock(path: Path) -> ProductLock:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("unsupported product lock schema")
    product = raw.get("product")
    interfaces = raw.get("public_interfaces")
    if not isinstance(product, dict) or not isinstance(interfaces, list):
        raise ValueError("product and public_interfaces are required")
    pins = tuple(
        PublicInterfacePin(
            interface_id=str(item["interface_id"]),
            path=str(item["path"]),
            sha256=str(item["sha256"]),
        )
        for item in interfaces
    )
    if len({item.interface_id for item in pins}) != len(pins):
        raise ValueError("public interface identities must be unique")
    source_manifest_raw = raw.get("source_manifest")
    source_manifest = None
    if source_manifest_raw is not None:
        if not isinstance(source_manifest_raw, dict):
            raise ValueError("source_manifest must be an object")
        source_manifest = SourceManifestPin(
            path=str(source_manifest_raw["path"]),
            schema_version=str(source_manifest_raw["schema_version"]),
            sha256=str(source_manifest_raw["sha256"]),
        )
    tree_paths = tuple(str(item) for item in product["tree_paths"])
    if not tree_paths or not pins:
        raise ValueError("a product lock requires tree paths and public interfaces")
    return ProductLock(
        schema_version=1,
        product_name=str(product["name"]),
        product_version=str(product["version"]),
        repository=str(product["repository"]),
        git_commit=str(product["git_commit"]) if product.get("git_commit") else None,
        tree_paths=tree_paths,
        tree_sha256=str(product["tree_sha256"]),
        public_interfaces=pins,
        source_manifest=source_manifest,
    )


def _git_commit(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    value = head.read_text(encoding="utf-8").strip()
    if value.startswith("ref: "):
        ref = root / ".git" / value.removeprefix("ref: ")
        return ref.read_text(encoding="utf-8").strip() if ref.is_file() else None
    return value or None


def verify_product_lock(lock: ProductLock, product_root: Path) -> ProductVerification:
    root = product_root.resolve()
    errors: list[str] = []
    if not root.is_dir():
        return ProductVerification(
            valid=False,
            product_root=str(root),
            lock_digest=lock.digest,
            observed_tree_sha256=None,
            errors=("product root does not exist",),
        )
    observed_tree = digest_paths(root, lock.tree_paths)
    if observed_tree != lock.tree_sha256:
        errors.append("product tree digest mismatch")
    observed_commit = _git_commit(root)
    if lock.git_commit is not None and observed_commit != lock.git_commit:
        errors.append("product Git commit mismatch")
    if lock.source_manifest is not None:
        manifest_path = root / lock.source_manifest.path
        if not manifest_path.is_file():
            errors.append("missing source product manifest")
        elif _sha256_file(manifest_path) != lock.source_manifest.sha256:
            errors.append("source product manifest digest mismatch")
        else:
            source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if source_manifest.get("schema_version") != lock.source_manifest.schema_version:
                errors.append("source product manifest schema mismatch")
    for pin in lock.public_interfaces:
        target = root / pin.path
        if not target.exists():
            errors.append(f"missing public interface: {pin.interface_id}")
            continue
        observed = digest_paths(root, (pin.path,))
        if observed != pin.sha256:
            errors.append(f"public interface digest mismatch: {pin.interface_id}")
    return ProductVerification(
        valid=not errors,
        product_root=str(root),
        lock_digest=lock.digest,
        observed_tree_sha256=observed_tree,
        errors=tuple(errors),
    )


def _default_product_root(lock_path: Path, lock: ProductLock) -> Path:
    override = os.environ.get("MILAI_PRODUCT_ROOT")
    if override:
        return Path(override)
    return (lock_path.parent / lock.repository).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the pinned MiLAi product tree")
    parser.add_argument("--lock", type=Path, default=Path("product.lock.json"))
    parser.add_argument("--product-root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    lock_path = args.lock.resolve()
    lock = load_product_lock(lock_path)
    product_root = args.product_root or _default_product_root(lock_path, lock)
    result = verify_product_lock(lock, product_root)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    elif result.valid:
        print(f"PASS product pin {result.lock_digest}")
    else:
        print("FAIL product pin: " + "; ".join(result.errors))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
