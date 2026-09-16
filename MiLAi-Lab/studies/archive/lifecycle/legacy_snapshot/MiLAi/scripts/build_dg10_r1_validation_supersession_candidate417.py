from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

PREVIOUS = ROOT / (
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.16-2026-08-22.json"
)
PREVIOUS_SHA256 = "bee35229671dfba2fab8a85f246d73253fc7b19f9e86e54d83fe24b25aae55f0"
ACTIVE = ROOT / (
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.17-2026-08-22.json"
)
ACTIVE_IDENTITIES = ROOT / (
    "docs/reports/DG-10-authorization-identities-candidate.4.20-2026-08-22.json"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-r1-validation-supersession-candidate.4.17-2026-08-22.json"
)


class R1ValidationSupersessionError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise R1ValidationSupersessionError(reason)


def _object(path: Path) -> dict[str, object]:
    _require(
        path.is_file() and not remediation.has_symlink_component(path),
        f"R1 validation artifact is missing or unsafe: {path}",
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"R1 validation artifact is not an object: {path}")
    return value


def build_receipt() -> dict[str, object]:
    _require(
        remediation.sha256_file(PREVIOUS) == PREVIOUS_SHA256,
        "contract-only R1 receipt drift",
    )
    previous = _object(PREVIOUS)
    active = _object(ACTIVE)
    identities = _object(ACTIVE_IDENTITIES)
    _require(
        previous.get("schema") == "milai.dg10.remediation-contract-validation.v1"
        and previous.get("candidate_id") == remediation.CANDIDATE
        and previous.get("scope") == "contracts"
        and "source_inventory" not in previous
        and previous.get("independent_acceptance") is False
        and previous.get("model_run_authorized") is False,
        "contract-only R1 receipt semantics drift",
    )
    source_inventory = active.get("source_inventory")
    identity_reference = identities.get("source_inventory")
    _require(
        active.get("schema") == "milai.dg10.remediation-contract-validation.v1"
        and active.get("candidate_id") == remediation.CANDIDATE
        and active.get("scope") == "all"
        and isinstance(source_inventory, Mapping)
        and active.get("independent_acceptance") is False
        and active.get("model_run_authorized") is False
        and isinstance(identity_reference, Mapping),
        "active full-source R1 receipt semantics drift",
    )
    source_path = identity_reference.get("path")
    _require(
        source_path
        == "docs/reports/DG-10-candidate-source-inventory-candidate.4.20-2026-08-22.json",
        "active R1 source identity path drift",
    )
    identity_source = ROOT / str(source_path)
    _require(
        remediation.sha256_file(identity_source) == identity_reference.get("sha256"),
        "active R1 source identity hash drift",
    )
    identity_source_value = _object(identity_source)
    active_root = source_inventory.get("canonical_entries_sha256")
    remediation._require_sha256(active_root, "active R1 source root")
    _require(
        identity_source_value.get("canonical_entries_sha256") == active_root,
        "active R1 and authorization source roots differ",
    )
    return {
        "schema": "milai.dg10.r1-validation-supersession.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "SUPERSEDED_CONTRACT_ONLY_R1_NO_ACCEPTANCE_EFFECT",
        "superseded": {
            "path": PREVIOUS.relative_to(ROOT).as_posix(),
            "sha256": PREVIOUS_SHA256,
            "scope": "contracts",
            "acceptance_effect": False,
        },
        "active": {
            "path": ACTIVE.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(ACTIVE),
            "scope": "all",
            "source_inventory_sha256": active_root,
        },
        "active_authorization_identities": {
            "path": ACTIVE_IDENTITIES.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(ACTIVE_IDENTITIES),
        },
        "reason_codes": [
            "ACTIVE_R1_REQUIRES_SCOPE_ALL",
            "ACTIVE_R1_REQUIRES_COMPLETE_SOURCE_INVENTORY",
            "R1_SOURCE_ROOT_MUST_EQUAL_STAGE_LEDGER_ROOT",
        ],
        "test_access_before_supersession": False,
        "model_completion_calls_before_supersession": 0,
        "release_authorized_before_supersession": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze contract-only R1 validation supersession"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "SUPERSEDED"}, sort_keys=True))


if __name__ == "__main__":
    main()
