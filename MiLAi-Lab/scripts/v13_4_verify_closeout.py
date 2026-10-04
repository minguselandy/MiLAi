#!/usr/bin/env python3
"""Verify the v13.4 closeout without executing providers or changing evidence.

Default checks Git-carried evidence; --local also verifies the sealed local
artifact inventory. It never restarts run_t0.py or reads/writes the live ledger.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = load(root / "data/manifests/v13-4-n6-closeout.json")
    for relative, expected in manifest["tracked_inputs"].items():
        if digest(root / relative) != expected:
            raise ValueError(f"Tracked evidence changed: {relative}")
    requirements = load(root / "data/manifests/v13-4-requirements.json")
    rows = requirements["requirements"]
    assert len(rows) == len({r["id"] for r in rows}) == 122
    counts = dict(collections.Counter(r["status"] for r in rows))
    assert counts == manifest["requirements_statuses"]
    results = load(root / "data/manifests/v13-4-t0-final-results.json")
    assert results["counts"]["responses"] == 256
    assert results["counts"]["queries"] == 128
    assert results["counts"]["histories"] == 32
    assert sum(results["score_record_counts"].values()) == 256
    assert results["costs"]["v13_4_generation_requests"] == 8 + 64 + 256
    assert results["costs"]["v13_4_known_and_charged_tokens"] == 6012 + 115463 + 563934
    assert results["decision"] == "SIMPLIFY"
    assert results["Product"] == manifest["Product"] == "NO_GO"
    checked = 0
    if args.local:
        ref = manifest["local_inventory"]
        path = root / ref["path"]
        assert digest(path) == ref["sha256"]
        inventory = load(path)
        for relative, expected in inventory["files"].items():
            if digest(root / relative) != expected:
                raise ValueError(f"Local evidence changed: {relative}")
            checked += 1
        assert checked == inventory["count"]
    print(
        json.dumps(
            {
                "status": "PASS",
                "tracked_inputs": len(manifest["tracked_inputs"]),
                "local_files": checked,
                "model_calls": 0,
                "ledger_writes": 0,
                "scope": "Byte integrity and closeout count consistency, not semantic replication",
            }
        )
    )


if __name__ == "__main__":
    main()
