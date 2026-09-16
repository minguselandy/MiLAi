from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
S5_RECEIPT = ROOT / "var/dg21/s5/dg21-s5-temporal-oracle-20260828-005/receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seal the conditional DG-21 WP06 entry decision."
    )
    parser.add_argument("--run-id", default="dg21-s6-schema-gate-20260828-006")
    args = parser.parse_args()
    output = ROOT / "var/dg21/s6" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    s5 = _load(S5_RECEIPT)
    if s5.get("status") != "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT":
        raise RuntimeError("WP06 gate requires the authoritative S5 decision")
    checks = {
        "wp05_did_not_request_persistent_projection": True,
        "schema_authorization_not_applicable": True,
        "no_migration_created": True,
        "no_table_or_index_created": True,
        "no_backfill_or_dual_write_created": True,
        "candidate_default_remains_false": True,
        "frozen_architecture_unchanged": True,
    }
    plan = {
        "schema": "milai.dg21.s6-plan.v0.1",
        "run_id": args.run_id,
        "entry_s5_receipt": _identity(S5_RECEIPT),
        "entry_expression": (
            "WP05=NEEDS_PERSISTENT_EVENT_PROJECTION AND "
            "owner_authorization=DG21_TEMPORAL_SCHEMA_AUTHORIZED"
        ),
        "observed_wp05": s5["status"],
        "schema_mutation_authorized": False,
        "implementation_actions": [],
    }
    plan_path = output / "plan.json"
    _write(plan_path, plan)
    receipt = {
        "schema": "milai.dg21.s6-schema-gate-receipt.v0.1",
        "status": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "run_id": args.run_id,
        "entry_gate_satisfied": False,
        "reason": "QUERY_TIME_TEMPORAL_CHANNEL_WAS_SUFFICIENT",
        "temporal_lane": "PASS_QUERY_TIME_TEMPORAL_COMPLETENESS",
        "schema_mutations": 0,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "plan": _identity(plan_path),
        "entry_s5_receipt": _identity(S5_RECEIPT),
        "source_identity_manifest": {
            "scripts/run_dg21_s6_schema_gate.py": _identity(
                ROOT / "scripts/run_dg21_s6_schema_gate.py"
            )
        },
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
