from __future__ import annotations

import hashlib
import json

from build_ua_inventory import ROOT, digest, inventory_files

OUTPUT = ROOT / "docs/reports/OE-current-byte-inventory-2026-08-18.json"


def main() -> None:
    paths = [path for path in inventory_files() if path != OUTPUT]
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "size": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in paths
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    inventory = {
        "format": "milai-oe-current-byte-inventory-v1",
        "snapshot_date": "2026-08-18",
        "excludes_secrets": True,
        "entry_count": len(entries),
        "entries_sha256": hashlib.sha256(canonical).hexdigest(),
        "entries": entries,
    }
    OUTPUT.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
