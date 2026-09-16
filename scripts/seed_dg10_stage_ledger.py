from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation
from scripts import dg10_stage_ledger as stage_ledger

DEFAULT_IDENTITIES = ROOT / (
    "docs/reports/DG-10-authorization-identities-candidate.4.21-2026-08-22.json"
)
DEFAULT_REVIEW_CHECKPOINT = ROOT / (
    "docs/reports/DG-10-r0-r2-stage-ledger-review-checkpoint-candidate.4.17-2026-08-22.json"
)
REVIEW_RECEIPT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.18.json"
)
AUTHOR_RECEIPTS = {
    "DG10-R0": ROOT / "docs/reports/DG-10-remediation-baseline-candidate.4.3-2026-08-22.json",
    "DG10-R1": ROOT
    / "docs/reports/DG-10-remediation-contract-validation-candidate.4.18-2026-08-22.json",
    "DG10-R2": ROOT
    / "docs/reports/DG-10-benchmark-worker-closure-candidate.4.28-2026-08-22.json",
}


class StageSeedError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StageSeedError(reason)


def _source_root(identity_path: Path) -> str:
    identity_path = identity_path.absolute()
    _require(
        identity_path.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(identity_path)
        and identity_path.is_file(),
        "active identity receipt is missing or unsafe",
    )
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    _require(
        isinstance(identity, Mapping)
        and identity.get("schema") == "milai.dg10.authorization-identities.v1"
        and identity.get("candidate_id") == remediation.CANDIDATE,
        "active identity receipt drift",
    )
    reference = identity.get("source_inventory")
    _require(isinstance(reference, Mapping), "active source inventory reference absent")
    relative = reference.get("path")
    _require(isinstance(relative, str) and relative, "active source inventory path absent")
    parsed = PurePosixPath(relative)
    _require(not parsed.is_absolute() and ".." not in parsed.parts, "active source inventory path unsafe")
    source = (ROOT / parsed).absolute()
    _require(
        source.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(source)
        and source.is_file()
        and remediation.sha256_file(source) == reference.get("sha256"),
        "active source inventory reference drift",
    )
    inventory = json.loads(source.read_text(encoding="utf-8"))
    value = inventory.get("canonical_entries_sha256")
    remediation._require_sha256(value, "active source inventory root")
    return str(value)


def _reference(path: Path) -> dict[str, str]:
    lexical = path.absolute()
    _require(
        lexical.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(lexical)
        and lexical.is_file(),
        "stage binding evidence is missing or unsafe",
    )
    return {
        "path": lexical.relative_to(ROOT.absolute()).as_posix(),
        "sha256": remediation.sha256_file(lexical),
    }


def _binding_receipt(
    *, stage: str, state: str, evidence_class: str, source_root: str, evidence: Path
) -> Path:
    kind = "author" if state == "AUTHOR_CANDIDATE" else "review"
    output = ROOT / (
        f"docs/reports/DG-10-{stage.lower()}-stage-{kind}-binding-"
        "candidate.4.17-2026-08-22.json"
    )
    value = {
        "schema": "milai.dg10.stage-state-binding.v1",
        "candidate_id": remediation.CANDIDATE,
        "stage_id": stage,
        "stage_state": state,
        "evidence_class": evidence_class,
        "source_inventory_sha256": source_root,
        "evidence": [_reference(evidence)],
    }
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    return output


def seed(*, identity_path: Path, checkpoint_path: Path) -> dict[str, object]:
    _require(not stage_ledger.ACTIVE_STAGE_LEDGER.exists(), "active stage ledger already exists")
    _require(REVIEW_RECEIPT.is_file() and not REVIEW_RECEIPT.is_symlink(), "review receipt absent")
    source_root = _source_root(identity_path.absolute())
    for stage, receipt in AUTHOR_RECEIPTS.items():
        author_binding = _binding_receipt(
            stage=stage,
            state="AUTHOR_CANDIDATE",
            evidence_class="DETERMINISTIC",
            source_root=source_root,
            evidence=receipt,
        )
        review_binding = _binding_receipt(
            stage=stage,
            state="REVIEW_REQUIRED",
            evidence_class="AUTHOR",
            source_root=source_root,
            evidence=REVIEW_RECEIPT,
        )
        stage_ledger.append_stage_state(
            stage_id=stage,
            stage_state="AUTHOR_CANDIDATE",
            evidence_class="DETERMINISTIC",
            source_inventory_sha256=source_root,
            receipt_path=author_binding,
        )
        stage_ledger.append_stage_state(
            stage_id=stage,
            stage_state="REVIEW_REQUIRED",
            evidence_class="AUTHOR",
            source_inventory_sha256=source_root,
            receipt_path=review_binding,
        )
    return stage_ledger.write_checkpoint(
        checkpoint_path.absolute(),
        required_stages=("DG10-R0", "DG10-R1", "DG10-R2"),
        required_state="REVIEW_REQUIRED",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed candidate.4 R0-R2 append-only stage ledger")
    parser.add_argument("--identities", type=Path, default=DEFAULT_IDENTITIES)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_REVIEW_CHECKPOINT)
    args = parser.parse_args()
    value = seed(identity_path=args.identities, checkpoint_path=args.checkpoint)
    print(json.dumps({"checkpoint": str(args.checkpoint.absolute()), "entry_count": value["entry_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
