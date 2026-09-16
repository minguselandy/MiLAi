"""A separately allocated P3 prefix; reuse the frozen first-wave cold Host unchanged."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from check_v0210_control import LAB, write
from milai_lab.methods.state_control import digest
from run_v0212_horizon import product


def run(root: Path, admission: Path, previous: Path, installed: Path) -> dict:
    allocation_path = LAB / "configs/v0212-horizon-recurrence.json"
    allocation = json.loads(allocation_path.read_text())
    adjudication = previous / "semantic-adjudication.json"
    assert digest(adjudication.read_bytes()) == allocation["trigger_review_sha256"]
    body = (admission / "seal-b.json").read_bytes()
    assert digest(body) == json.loads((admission / "seal-b-sha256.json").read_text())["sha256"]
    seal = json.loads(body)
    start, stop = allocation["accepted_cluster_slice"]
    keys = [
        row["query"]
        for cluster in seal["accepted_clusters"][start:stop]
        for row in seal["accepted_queries"][cluster]
    ]
    assert keys == allocation["query_ids"]
    assert (admission / "a0-profile.json").read_bytes() == (
        previous / "a0-profile.json"
    ).read_bytes()
    old_pins = json.loads((previous / "implementation-pin.json").read_text())
    assert all(digest((LAB / name).read_bytes()) == sha for name, sha in old_pins.items())
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    (root / "a0-profile.json").write_bytes((admission / "a0-profile.json").read_bytes())
    (root / "allocation.json").write_bytes(allocation_path.read_bytes())
    write(
        root / "implementation-pin.json",
        {
            **old_pins,
            str(Path(__file__).resolve().relative_to(LAB)): digest(Path(__file__).read_bytes()),
            str(allocation_path.relative_to(LAB)): digest(allocation_path.read_bytes()),
        },
    )
    results = {}
    started = time.monotonic()
    try:
        with product(root / "product", installed) as owned:
            for key in keys:
                remaining = allocation["max_seconds"] - (time.monotonic() - started)
                if remaining <= 0:
                    break
                subprocess.run(  # noqa: S603 -- identical pinned cold Host, frozen source paths
                    [
                        sys.executable,
                        str(LAB / "tools/run_v0212_horizon.py"),
                        "--root",
                        str(root),
                        "--cold",
                        key,
                        "--source",
                        str(admission / "online" / key),
                        "--owned",
                        str(owned),
                        "--remaining",
                        str(remaining),
                    ],
                    cwd=LAB,
                    check=True,
                    timeout=remaining,
                )
                results[key] = json.loads((root / key / "result.json").read_text())
                if (
                    results[key]["accounting"]["pending"]
                    or results[key]["accounting"]["violations"]
                ):
                    break
    finally:
        for key in keys:
            results.setdefault(key, {"status": "NOT_RUN", "reason": "BATCH_STOP"})
        result = {
            "queries": results,
            "seconds": time.monotonic() - started,
            "actual_generations": sum(
                r.get("accounting", {}).get("requests", 0) for r in results.values()
            ),
            "actual_raw_tokens": sum(
                r.get("accounting", {}).get("raw_tokens", 0) for r in results.values()
            ),
            "scoring": "PENDING_OFFLINE",
        }
        write(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.root.resolve(),
                args.admission.resolve(),
                args.previous.resolve(),
                args.installed.resolve(),
            )
        )
    )
