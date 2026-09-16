"""Pinned benchmark acquisition; secrets read in-process, never logged or persisted."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import time
from pathlib import Path

PINS = {
    "clawmark": ("evolvent-ai/ClawMark", "d1b641b3171e584e69a3763c269069f32a13b574"),
    "wma-code": ("UCSB-AI/WorldMemArena", "15ea25b723d9c4fb35e8062037aec6a5601e4442"),
    "supersede": ("Vrin-cloud/supersede", "677993d3713c265329ac935262d3c08cbfa4cd63"),
}
WMA_REVISION = "e2148757921fc7e2d66d8ed899823b763227c341"


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def credential(path: Path) -> str:
    """Parse a narrow env file without executing shell code or exposing values."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.removeprefix("export ").partition("=")
        if separator:
            values[key.strip()] = value.strip().strip("\"'")
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN",
                "HUGGINGFACE_TOKEN"):
        if values.get(key):
            return values[key]
    candidates = [value for value in values.values() if value.startswith("hf_")]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("HF_CREDENTIAL_NOT_UNAMBIGUOUS_NO_VALUES_LOGGED")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hf_download(root: Path, secret_file: Path, workers: int) -> dict:
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"
    os.environ["HF_HUB_ETAG_TIMEOUT"] = "45"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import logging

    logging.set_verbosity_error()
    target = root / ("WorldMemArena-" + WMA_REVISION)
    snapshot_download("LCZZZZ/WorldMemArena", repo_type="dataset", revision=WMA_REVISION,
                      local_dir=target, token=credential(secret_file), max_workers=workers,
                      etag_timeout=45)
    files = [path for path in target.rglob("*") if path.is_file() and ".cache" not in path.parts]
    manifest = [{"path": str(path.relative_to(target)), "bytes": path.stat().st_size,
                 "sha256": sha_file(path)} for path in sorted(files)]
    save(root / "wma-data-files.json", {"revision": WMA_REVISION, "files": manifest})
    return {"status": "SNAPSHOT_DOWNLOADED_HASHED", "revision": WMA_REVISION,
            "path": str(target), "files": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "credentials_persisted": False, "task_semantics_reviewed": False}


def github_download(root: Path, key: str) -> dict:
    import httpx

    repository, revision = PINS[key]
    archive = root / f"{key}-{revision}.tar.gz"
    if not archive.exists():
        partial = archive.with_suffix(".part")
        with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as client:
            url = f"https://codeload.github.com/{repository}/tar.gz/{revision}"
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with partial.open("wb") as stream:
                    size = 0
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > 3_000_000_000:
                            raise ValueError("ARCHIVE_SIZE_BOUND")
                        stream.write(chunk)
        partial.rename(archive)
    target = root / key
    if not target.exists():
        target.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(target, filter="data")
    files = [path for path in target.rglob("*") if path.is_file()]
    manifest = [{"path": str(path.relative_to(target)), "bytes": path.stat().st_size,
                 "sha256": sha_file(path)} for path in sorted(files)]
    save(root / f"{key}-files.json", {"revision": revision, "files": manifest})
    return {"status": "PINNED_ARCHIVE_DOWNLOADED_HASHED", "repository": repository,
            "revision": revision, "archive_sha256": sha_file(archive), "path": str(target),
            "files": len(files), "bytes": sum(path.stat().st_size for path in files),
            "foreign_code_executed": False, "task_semantics_reviewed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kind", choices=["wma-data", *PINS], required=True)
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 33))
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    print(json.dumps({"status": "DOWNLOAD_STARTED", "kind": args.kind}), flush=True)
    try:
        result = (hf_download(args.root, args.secret_file, args.workers) if args.kind == "wma-data"
                  else github_download(args.root, args.kind))
    except Exception as exc:
        result = {"status": "DOWNLOAD_INCOMPLETE_PRESERVED", "exception_type": type(exc).__name__,
                  "error_details": "Omitted to avoid credentials/signed-URL leakage; "
                      "retry only read-only downloads",
                  "kind": args.kind}
    result["seconds"] = time.time() - started
    with (args.root / "download-attempts.jsonl").open("a") as stream:
        stream.write(json.dumps(result) + "\n")
    save(args.root / f"{args.kind}-status.json", result)
    print(json.dumps(result), flush=True)
    raise SystemExit(1 if result["status"].startswith("DOWNLOAD_INCOMPLETE") else 0)
