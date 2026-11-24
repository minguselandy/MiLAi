"""Restore missing V13 local model and data aliases from the durable experiment manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def restore(root):
    staging = root / "staging"
    assets = json.loads((root / "persistent-assets.json").read_text())
    links = {Path(item["source"]): Path(destination) for destination, item in assets.items()}
    bindings = json.loads((root / "gte/s1/checkpoint-storage.json").read_text())
    links[Path(bindings["live_output"])] = Path(bindings["persistent_output"])
    links[staging / "round-models"] = root / "weights/round-models"
    qr = json.loads((root / "qr-11/persistent-storage.json").read_text())
    links[Path(qr["runtime_weights"])] = Path(qr["formal_weights"])
    links[Path(qr["runtime_receipts"])] = Path(qr["formal_receipts"])

    result = {}
    for source, destination in links.items():
        if not (source.is_relative_to(root) and destination.is_relative_to(root)):
            raise ValueError(f"Path outside this experiment: {source}")
        if not destination.exists():
            raise FileNotFoundError(destination)
        if source.exists():
            # A live job may use its original downloaded assets on a separate mount.
            result[str(source)] = "already_bound" if source.samefile(destination) else "existing"
            continue
        if source.is_symlink():
            raise FileNotFoundError(f"Broken existing alias {source} -> {source.readlink()}")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.symlink_to(destination, target_is_directory=destination.is_dir())
        result[str(source)] = "restored"
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(restore(args.root.resolve()), indent=2))
