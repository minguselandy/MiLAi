from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the filtered legacy copy manifest")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("studies/archive/lifecycle/legacy_snapshot/manifest.json"),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="also verify that the legacy source still has the recorded bytes",
    )
    args = parser.parse_args()
    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors: list[str] = []
    for record in raw["files"]:
        target = args.manifest.parent / record["destination"]
        if not target.is_file():
            errors.append(f"missing {record['destination']}")
        elif _sha256(target) != record["sha256"]:
            errors.append(f"digest mismatch {record['destination']}")
        if args.source_root is not None:
            source = args.source_root / record["source"]
            if not source.is_file():
                errors.append(f"missing source {record['source']}")
            elif _sha256(source) != record["sha256"]:
                errors.append(f"source changed {record['source']}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"PASS {len(raw['files'])} archived files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
