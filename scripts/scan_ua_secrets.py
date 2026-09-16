from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai.operations.release_safety import (
    ArchiveScan as ArchiveScan,
    archive_kind,
    scan_archive_bytes as scan_archive_bytes,
    scan_paths,
    secret_values,
)

from build_ua_inventory import OUTPUT as INVENTORY_OUTPUT
from build_ua_inventory import ROOT, inventory_files

_archive_kind = archive_kind
_secrets = secret_values


def _files(env_file: Path) -> list[Path]:
    result = set(inventory_files())
    if INVENTORY_OUTPUT.is_file():
        result.add(INVENTORY_OUTPUT)
    result.discard(env_file.resolve())
    return sorted(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check current UA bytes and decompressed artifacts for exact local secrets"
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    secrets = secret_values(env_file)
    files = _files(env_file)
    result = scan_paths(ROOT, files, secrets)
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
