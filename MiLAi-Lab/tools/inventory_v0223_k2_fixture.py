"""K0 inventory of one new fixture's actual admission, without timing verdict.

Metadata is copied only at the scope close boundary before its original method
clears the entries. No reader/validator is replaced; close still executes its
fresh second observation and all exceptions propagate.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _inventory():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["MILA_V0223_INSTANCE"] = args.instance
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0220_evidence import save, sha
    from v0222_admission_read_scope import AdmissionReadScope
    from v0223_k2_cpu_batch import OfflineBatch, selected_root

    root = selected_root()
    rows = []
    original = AdmissionReadScope._close

    def close(scope, body_error=None):
        entries = [
            {
                "path": str(path),
                "sha256": entry.expected,
                "bytes": len(entry.data) if entry.data is not None else None,
                "identity": entry.identity,
                "json_parsed": entry.parsed_ready,
            }
            for path, entry in scope._entries.items()
        ]
        try:
            return original(scope, body_error)
        finally:
            rows.append({"files": entries, "stats": scope.stats, "status": scope.status})

    AdmissionReadScope._close = close
    try:
        binding = sha(root / "execution-binding.json")
        batch = OfflineBatch(root, binding)
        with batch._operation("PREP") as (db, _scope, state):
            tables = [
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            queries = {
                "meta": "SELECT * FROM meta ORDER BY key",
                "episodes": "SELECT * FROM episodes ORDER BY stage,ordinal",
                "events": "SELECT * FROM events ORDER BY seq",
                "artifacts": "SELECT * FROM artifacts ORDER BY name",
                "launches": "SELECT * FROM launches ORDER BY stage",
                "claims": "SELECT * FROM claims ORDER BY episode",
            }
            if sorted(queries) != tables:
                raise ValueError("FIXED_COORDINATOR_TABLES_REQUIRED")
            snapshot = {
                name: [dict(row) for row in db.execute(query)] for name, query in queries.items()
            }
    finally:
        AdmissionReadScope._close = original
    # Constructor and complete PREP operation each own one full closed scope.
    if len(rows) != 2 or any(row["status"] != "CLOSED_VERIFIED_TWO_OBSERVATIONS" for row in rows):
        raise ValueError("TWO_COMPLETE_ACTUAL_ADMISSION_SCOPES_REQUIRED")
    result = {
        "status": "K0_ACTUAL_CONSTRUCTOR_AND_PREP_INVENTORY_NOT_TIMING",
        "root": str(root),
        "binding_sha256": binding,
        "scope_rows": rows,
        "dynamic_snapshot": snapshot,
        "accounting_state": state,
        "model_requests": 0,
        "http_requests": 0,
    }
    save(args.output, result)
    print(json.dumps({"status": result["status"], "scope_files": [len(r["files"]) for r in rows]}))


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0223_transaction_primary_fix import installed_transaction_fix

    with installed_transaction_fix():
        return _inventory()


if __name__ == "__main__":
    main()
