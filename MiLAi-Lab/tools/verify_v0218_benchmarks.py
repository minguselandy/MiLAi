"""Verify downloaded bytes against pinned upstream metadata without reading task semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from download_v0218_benchmarks import PINS, WMA_REVISION, credential, save, sha_file


def git_blob(path: Path) -> str:
    value = hashlib.sha1(usedforsecurity=False)
    value.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def github(root: Path, previous: Path) -> dict:
    rows = []
    for key, (_repo, revision) in PINS.items():
        status = json.loads((root / f"{key}-status.json").read_text())
        assert status["revision"] == revision
        tree_path = previous / ("wma" if key == "wma-code" else key) / "tree.json"
        tree = json.loads(tree_path.read_text())
        assert tree["sha"] == revision and not tree.get("truncated")
        trees = [path for path in (root / key).iterdir() if path.is_dir()]
        assert len(trees) == 1
        local = trees[0]
        files = [item for item in tree["tree"] if item["type"] == "blob"]
        expected = {item["path"] for item in files}
        actual = {str(p.relative_to(local)) for p in local.rglob("*") if p.is_file()}
        assert expected == actual
        mismatches = [
            item["path"] for item in files if git_blob(local / item["path"]) != item["sha"]
        ]
        rows.append(
            {
                "benchmark": key,
                "revision": revision,
                "files": len(files),
                "bytes": sum((local / item["path"]).stat().st_size for item in files),
                "upstream_tree_sha256": sha_file(tree_path),
                "mismatches": mismatches,
                "status": "VERIFIED_EVERY_UPSTREAM_GIT_BLOB" if not mismatches else "MISMATCH",
            }
        )
    result = {"rows": rows, "task_semantics_reviewed": False, "foreign_code_executed": False}
    save(root / "github-upstream-verification.json", result)
    return result


def metadata(root: Path, secret: Path) -> dict:
    os.environ["HF_HUB_ETAG_TIMEOUT"] = "45"
    from huggingface_hub import HfApi
    from huggingface_hub.hf_api import RepoFile
    from huggingface_hub.utils import logging

    logging.set_verbosity_error()
    target = root / "wma-upstream-files.json"
    if target.exists():
        return json.loads(target.read_text())
    files = []
    for item in HfApi(token=credential(secret)).list_repo_tree(
        "LCZZZZ/WorldMemArena",
        repo_type="dataset",
        revision=WMA_REVISION,
        recursive=True,
    ):
        if isinstance(item, RepoFile):
            files.append(
                {
                    "path": item.path,
                    "bytes": item.size,
                    "git_blob": item.blob_id,
                    "lfs_sha256": item.lfs.sha256 if item.lfs else None,
                }
            )
    result = {
        "revision": WMA_REVISION,
        "files": files,
        "expected_files": len(files),
        "expected_bytes": sum(row["bytes"] for row in files),
    }
    save(target, result)
    return result


def local_hf(root: Path, full: bool) -> dict:
    catalog = json.loads((root / "wma-upstream-files.json").read_text())
    assert catalog["revision"] == WMA_REVISION
    target = root / ("WorldMemArena-" + WMA_REVISION)
    present, mismatches = [], []
    for row in catalog["files"]:
        path = target / row["path"]
        if not path.is_file():
            continue
        if path.stat().st_size != row["bytes"]:
            mismatches.append(row["path"])
            continue
        if full:
            observed = sha_file(path) if row["lfs_sha256"] else git_blob(path)
            if observed != (row["lfs_sha256"] or row["git_blob"]):
                mismatches.append(row["path"])
                continue
        present.append(row)
    complete = len(present) == catalog["expected_files"] and not mismatches
    result = {
        "status": "UPSTREAM_HASH_VERIFIED_COMPLETE" if complete and full else "IN_PROGRESS",
        "hashes_checked": full,
        "revision": WMA_REVISION,
        "expected_files": catalog["expected_files"],
        "expected_bytes": catalog["expected_bytes"],
        "verified_files" if full else "size_matched_files": len(present),
        "verified_bytes" if full else "size_matched_bytes": sum(row["bytes"] for row in present),
        "mismatches": mismatches,
        "observed_at_unix": time.time(),
        "task_semantics_reviewed": False,
    }
    save(
        root / ("wma-upstream-verification.json" if full else "wma-download-progress.json"), result
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--kind", choices=["github", "metadata", "progress", "verify"], required=True
    )
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--secret-file", type=Path)
    args = parser.parse_args()
    try:
        if args.kind == "github":
            result = github(args.root, args.previous)
        elif args.kind == "metadata":
            result = metadata(args.root, args.secret_file)
            result = {key: value for key, value in result.items() if key != "files"}
        else:
            result = local_hf(args.root, args.kind == "verify")
        print(json.dumps(result))
    except Exception as exc:
        print(
            json.dumps({"status": "VERIFICATION_INCOMPLETE", "exception_type": type(exc).__name__})
        )
        raise SystemExit(1) from None
