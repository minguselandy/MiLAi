"""Open exactly the next prospectively ordered D source; never resolve reserve source text."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from v0219_inventory import read, save, sha


def open_next(seal: Path, screening: Path) -> dict:
    manifest = read(seal / "seal-A.json")
    for name, expected in manifest["files"].items():
        assert sha(seal / name) == expected
    ordered = read(seal / "assignment.json")["D_order"]
    screening.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous = sorted(screening.glob("[0-9][0-9][0-9]-open.json"))
    for index, path in enumerate(previous):
        assert read(path)["root_id"] == ordered[index]["root_id"]
        assert (screening / f"{index + 1:03d}-decision.json").exists(), "REVIEW_PREVIOUS_ROOT_FIRST"
        decision = read(screening / f"{index + 1:03d}-decision.json")
        assert decision["root_id"] == ordered[index]["root_id"]
        assert decision["status"] in {"ACCEPT_STATIC", "REJECT", "HOLD"}
    index = len(previous)
    assert index < len(ordered), "DEVELOPMENT_POOL_EXHAUSTED"
    row = ordered[index]
    source = next(
        r for r in read(seal / "private-source-map.json")["rows"] if r["root_id"] == row["root_id"]
    )
    neutral = next(
        r for r in read(seal / "neutral-manifest.json")["rows"] if r["root_id"] == row["root_id"]
    )
    path = Path(source["source_path"])
    assert sha(path) == neutral["source_sha256"]
    destination = screening / "opened" / row["root_id"] / "task.py"
    destination.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(path, destination)
    receipt = {
        **row,
        "source_path": str(path),
        "source_sha256": sha(path),
        "opened_copy": str(destination),
        "native_id": source["native_id"],
        "exposure": "TASK_TEXT_OPENED_FOR_STATIC_ADMISSION",
        "seal_sha256": sha(seal / "seal-A.json"),
        "model_requests": 0,
        "status": "REQUIRES_SOURCE_GROUNDED_STATIC_ADMISSION",
    }
    save(screening / f"{index + 1:03d}-open.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--screening", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(open_next(args.seal, args.screening)))
