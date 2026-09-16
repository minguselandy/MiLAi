from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_scoring_worker as v1
from scripts import run_dg10_bfcl_multiturn_scoring_worker_v2 as v2

CONTRACT_CANDIDATE = "candidate.15"
CONTRACT_SCHEMA = "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v2"
CONTRACT_STATUS = (
    "BFCL_MULTITURN_SCORING_REMEDIATION_V2_FROZEN_DEV_LABELS_ALREADY_OPENED"
)


def _validate_remediation_contract_and_inputs(
    *,
    contract_path: Path,
    ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    contract = v1._load_json_object(contract_path)
    closure = contract.get("byte_closure", {})
    inputs = contract.get("inputs", {})
    if (
        contract.get("schema") != CONTRACT_SCHEMA
        or contract.get("candidate") != CONTRACT_CANDIDATE
        or contract.get("status") != CONTRACT_STATUS
        or contract.get("bfcl_dev_answer_labels_opened") is not True
        or contract.get("bfcl_test_labels_or_outputs_opened") is not False
        or contract.get("test_access_authorized") is not False
        or closure.get("scoring_worker", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or inputs.get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(ledger_path)
        or inputs.get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
        or bfcl_contract._git_head(bfcl_root) != inputs.get("bfcl_git_head")
    ):
        raise v1.ScoringWorkerError("candidate.15 remediation boundary mismatch")
    return contract


def main() -> None:
    v1.CONTRACT_CANDIDATE = CONTRACT_CANDIDATE
    v1._safe_result_hash = v2._safe_result_hash
    v1._validate_contract_and_inputs = _validate_remediation_contract_and_inputs
    v1.main()


if __name__ == "__main__":
    main()
