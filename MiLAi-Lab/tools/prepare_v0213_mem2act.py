"""Fetch fixed released files and expose only structural/lineage metadata initially."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

from replay_v0213_cost import save, sha

LAB = Path(__file__).resolve().parents[1]


def shape(value, depth=0):
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return {"type": "list", "first_item_shape": shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def prepare(root: Path) -> dict:
    start = time.monotonic()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = LAB / "configs/v0213-admission.json"
    config = json.loads(config_path.read_text())
    seal = root / "pre-open-protocol.json"
    if seal.exists():
        assert json.loads(seal.read_text()) == config
    else:
        save(seal, config)
    receipts = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for relative, expected in config["files"].items():
            path = root / "release" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            reused = path.exists()
            if not reused:
                url = (f"https://raw.githubusercontent.com/{config['repo']}/"
                       f"{config['commit']}/{relative}")
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    received = 0
                    with path.open("xb") as stream:
                        for block in response.iter_bytes():
                            received += len(block)
                            if received > expected["bytes"]:
                                raise ValueError("RELEASE_SIZE_EXCEEDED")
                            stream.write(block)
            raw = path.read_bytes()
            assert len(raw) == expected["bytes"]
            blob = hashlib.sha1(  # noqa: S324 -- Git object identity, not a security primitive
                f"blob {len(raw)}\0".encode() + raw).hexdigest()
            assert blob == expected["git_blob"]
            metadata = []
            shapes = {}
            for index, line in enumerate(raw.splitlines()):
                record = json.loads(line)
                structural = shape(record)
                shapes.setdefault(sha(json.dumps(structural, sort_keys=True).encode()), structural)
                keys = ("id", "qa_id", "session_id", "source_conversation_ids",
                        "original_conversation_ids", "memory_chain_id", "chain_id")
                metadata.append({"row": index, **{k: record[k] for k in keys if k in record},
                                 "evolution_source_ids": sorted({
                                     item["source_id"] for item in record.get("evolution_chain", [])
                                     if item.get("source_id")})})
            save(root / (path.stem + "-metadata.json"), metadata)
            receipts.append({"path": relative, "sha256": sha(raw), "git_blob": blob,
                             "bytes": len(raw), "downloaded_bytes": 0 if reused else len(raw),
                             "records": len(metadata), "shapes": list(shapes.values())})
    result = {"status": "RELEASE_VERIFIED_METADATA_ONLY", "files": receipts,
              "pre_open_protocol_sha256": sha(seal.read_bytes()),
              "seconds": time.monotonic() - start, "new_generations": 0}
    save(root / "release-manifest.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.root)
    print(json.dumps({"status": report["status"], "files": [
        {key: value for key, value in row.items() if key != "shapes"}
        for row in report["files"]]}, indent=2))
