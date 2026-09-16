"""Download a pinned fixed snapshot and emit only allowed metadata before Seal A."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
from pathlib import Path

import httpx

from check_v0210_control import LAB, write


def download(root: Path, local_snapshot: Path | None = None) -> list[dict]:
    dataset = json.loads((root / "horizon-dataset.json").read_text())
    files = json.loads((root / "horizon-files.json").read_text())
    allocation = json.loads((root / "allocation.json").read_text())
    assert sum(row["size"] for row in files) <= allocation["resources"]["dataset_download_bytes"]
    snapshot = root / "horizon-snapshot"
    snapshot.mkdir(exist_ok=False)

    def fetch(row: dict) -> dict:
        path = snapshot / Path(row["path"]).name
        started = time.monotonic()
        if local_snapshot is not None:
            local = local_snapshot / row["path"]
            if local.is_file() and local.stat().st_size == row["size"]:
                with local.open("rb") as stream:
                    local_sha = hashlib.file_digest(stream, "sha256").hexdigest()
                if local_sha == row["lfs"]["oid"]:
                    path.symlink_to(local.resolve())
                    result = {"file": str(path.relative_to(root)), "revision": dataset["sha"],
                              "bytes": row["size"], "sha256": local_sha,
                              "seconds": time.monotonic() - started, "remote_lfs_match": True,
                              "reused_source": str(local.resolve()), "download_bytes": 0}
                    write(path.with_suffix(".receipt.json"), result)
                    return result
        url = ("https://huggingface.co/datasets/stellalisy/HorizonBench/resolve/"
               + dataset["sha"] + "/" + row["path"] + "?download=true")
        size, sha = 0, hashlib.sha256()
        with httpx.Client(timeout=40, follow_redirects=True) as client:
            with client.stream("GET", url) as response, path.open("xb") as output:
                response.raise_for_status()
                for block in response.iter_bytes(1024 * 1024):
                    size += len(block)
                    if size > row["size"] or time.monotonic() - started > 1200:
                        raise ValueError("FROZEN_DOWNLOAD_LIMIT")
                    output.write(block)
                    sha.update(block)
        assert size == row["size"] and sha.hexdigest() == row["lfs"]["oid"]
        result = {"file": str(path.relative_to(root)), "revision": dataset["sha"],
                  "bytes": size, "sha256": sha.hexdigest(),
                  "seconds": time.monotonic() - started, "remote_lfs_match": True}
        write(path.with_suffix(".receipt.json"), result)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(fetch, files))
    write(root / "horizon-download.json", receipts)
    return receipts


def inventory(root: Path) -> dict:
    import pyarrow.parquet as pq  # isolated uv --with tool dependency, no repo import

    columns = ["id", "generator", "user_id", "has_evolved", "preference_domain"]
    rows = []
    schemas = []
    for path in sorted((root / "horizon-snapshot").glob("*.parquet")):
        file = pq.ParquetFile(path)
        schemas.append({"file": path.name, "schema": str(file.schema_arrow),
                        "row_groups": file.num_row_groups, "rows": file.metadata.num_rows})
        for index, row in enumerate(file.read(columns=columns).to_pylist()):
            rows.append({**row, "file": path.name, "row": index})
    result = {"revision": json.loads((root / "horizon-dataset.json").read_text())["sha"],
              "allowed_columns": columns, "schemas": schemas, "items": rows,
              "decoded_question_history_gold_columns": [],
              "item_count": len(rows), "user_count": len({r["user_id"] for r in rows}),
              "evolved": sum(r["has_evolved"] for r in rows)}
    write(root / "horizon-metadata.json", result)
    return {key: result[key] for key in ("revision", "item_count", "user_count", "evolved")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--local-snapshot", type=Path, default=(
        LAB.parent / "benchmarks/HorizonBench/data/hf"))
    args = parser.parse_args()
    if not args.inventory_only:
        download(args.root.resolve(), args.local_snapshot.resolve())
    print(json.dumps(inventory(args.root.resolve())))
