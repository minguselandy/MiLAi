from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

WORKER_CLOSURE = ROOT / (
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.13-2026-08-22.json"
)
ATTEMPT_SCHEMA = ROOT / "docs/contracts/DG-10-attempt-ledger.schema.json"
ATTEMPT_SCHEMA_SHA256 = "9b1b83a4a190dfed6f8d969fec921a3ac8e2ad5639cacd0ed82c517db624f3f2"
ADAPTER_MATERIALS = (
    ROOT / "scripts/dg10_bfcl_loop.py",
    ROOT / "scripts/dg10_bfcl_scoring.py",
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker.py",
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v4.py",
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-bfcl-execution-identity-candidate.4.13-2026-08-22.json"
)


def _reference(path: Path) -> dict[str, Any]:
    lexical = path.absolute()
    if (
        not lexical.is_relative_to(ROOT.absolute())
        or remediation.has_symlink_component(lexical)
        or not lexical.is_file()
    ):
        raise remediation.RemediationError(f"unsafe BFCL execution material: {path}")
    return {
        "path": lexical.relative_to(ROOT.absolute()).as_posix(),
        "sha256": remediation.sha256_file(lexical),
        "size": lexical.stat().st_size,
    }


def _identity(materials: tuple[Path, ...]) -> dict[str, Any]:
    references = [_reference(path) for path in materials]
    return {
        "identity_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"materials": references})
        ),
        "materials": references,
    }


def build_identity() -> dict[str, Any]:
    _reference(WORKER_CLOSURE)
    if remediation.sha256_file(ATTEMPT_SCHEMA) != ATTEMPT_SCHEMA_SHA256:
        raise remediation.RemediationError("BFCL attempt-ledger schema drift")
    closure = json.loads(WORKER_CLOSURE.read_text(encoding="utf-8"))
    bfcl = closure.get("upstream_bfcl") if isinstance(closure, dict) else None
    if (
        not isinstance(bfcl, dict)
        or bfcl.get("git_head") != "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
        or bfcl.get("tracked_file_count") != 192
        or bfcl.get("canonical_entries_sha256")
        != "1e8be069f93b5b910d37f90db6208cca389b5e9d0bcdd03d56ae7037f18b5fb5"
    ):
        raise remediation.RemediationError("BFCL upstream tracked-tree closure drift")
    if closure.get("adapter") != _identity(ADAPTER_MATERIALS):
        raise remediation.RemediationError("BFCL adapter closure differs from exact current bytes")
    return {
        "schema": "milai.dg10.bfcl-execution-identity.v1",
        "candidate_id": remediation.CANDIDATE,
        "frozen_at": datetime.now(UTC).isoformat(),
        "worker_closure": _reference(WORKER_CLOSURE),
        "worker_environment": closure["environment"],
        "adapter": closure["adapter"],
        "upstream_bfcl": {
            "git_head": bfcl["git_head"],
            "tracked_file_count": bfcl["tracked_file_count"],
            "canonical_entries_sha256": bfcl["canonical_entries_sha256"],
        },
        "attempt_ledger": {
            "path": "var/dg10/bfcl-candidate.4/attempts.jsonl",
            "schema": _reference(ATTEMPT_SCHEMA),
            "mode": "0600",
            "append_only": True,
            "expected_case_count": 216,
        },
        "raw_receipt_root": "var/dg10/bfcl-candidate.4/raw-receipts",
        "per_case_identity_fields": [
            "candidate_id",
            "ledger_attempt_ids",
            "worker_environment_sha256",
            "adapter_sha256",
            "ledger_sha256",
        ],
        "result_access_before_freeze_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze candidate.4 BFCL execution identity")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = build_identity()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(
        json.dumps(
            {
                "output": str(output),
                "worker_environment_sha256": value["worker_environment"]["identity_sha256"],
                "adapter_sha256": value["adapter"]["identity_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
