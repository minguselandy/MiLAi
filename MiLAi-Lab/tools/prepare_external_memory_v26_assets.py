"""Prepare and verify the pinned offline NLP assets for the Mem0 CI test."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / "data/manifests/milai-external-memory-v26-environment-receipt.json"
CACHE = LAB / "artifacts/external-memory-v26/cache/fastembed"


def _verify_files(root: Path, files: list[dict[str, object]]) -> None:
    for item in files:
        path = root / str(item["path"])
        if (not path.is_file() or path.stat().st_size != item["size_bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]):
            raise ValueError(f"EXTERNAL_V26_ASSET_CHANGED:{path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true",
                        help="Download only the pinned BM25 snapshot if necessary")
    args = parser.parse_args()
    receipt = json.loads(RECEIPT.read_text())
    sparse = receipt["fastembed_sparse_model"]
    revision = sparse["snapshot_revision"]
    snapshot = CACHE / "models--Qdrant--bm25" / "snapshots" / revision
    if args.prepare:
        from huggingface_hub import snapshot_download

        downloaded = Path(snapshot_download(
            repo_id="Qdrant/bm25", revision=revision, cache_dir=CACHE,
        ))
        if downloaded.resolve() != snapshot.resolve():
            raise ValueError("EXTERNAL_V26_BM25_REVISION_CHANGED")
        for name in ("mock.file", "tamil.txt"):
            placeholder = snapshot / name
            if not placeholder.exists():
                placeholder.touch()
        # FastEmbed loads this model without an explicit revision in offline mode.
        ref = snapshot.parents[1] / "refs/main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(revision)
    _verify_files(snapshot, sparse["files"])
    ref = snapshot.parents[1] / "refs/main"
    if ref.read_text().strip() != revision:
        raise ValueError("EXTERNAL_V26_BM25_REF_CHANGED")

    model = importlib.import_module("en_core_web_sm")
    model_path = model.__file__
    if model_path is None:
        raise ValueError("EXTERNAL_V26_SPACY_MODEL_PACKAGE_MISSING")
    model_dir = Path(model_path).resolve().parent / "en_core_web_sm-3.8.0"
    _verify_files(model_dir, receipt["spacy_model"]["files"])
    if model.__version__ != receipt["spacy_model"]["model_version"]:
        raise ValueError("EXTERNAL_V26_SPACY_MODEL_VERSION_CHANGED")
    print(json.dumps({"bm25_revision": revision, "bm25_files": len(sparse["files"]),
                      "spacy_files": len(receipt["spacy_model"]["files"])},
                     sort_keys=True))


if __name__ == "__main__":
    main()
