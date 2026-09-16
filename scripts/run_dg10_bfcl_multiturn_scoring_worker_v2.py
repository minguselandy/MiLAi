from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_scoring_worker as v1

CONTRACT_CANDIDATE = "candidate.14"
CONTRACT_SCHEMA = "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v1"
CONTRACT_STATUS = (
    "BFCL_MULTITURN_SCORING_REMEDIATION_FROZEN_DEV_LABELS_ALREADY_OPENED"
)


def _canonical_hash_value(value: Any) -> Any:
    """Represent mixed-key mappings canonically without changing checker inputs."""

    if isinstance(value, Mapping):
        pairs = [
            [_canonical_hash_value(key), _canonical_hash_value(item)]
            for key, item in value.items()
        ]
        pairs.sort(
            key=lambda pair: json.dumps(
                pair[0],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {"__mapping__": pairs}
    if isinstance(value, (list, tuple)):
        return [_canonical_hash_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_hash_value(item) for item in value]
        items.sort(
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {"__set__": items}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"__type__": type(value).__name__, "__repr__": repr(value)}


def _safe_result_hash(value: Any) -> str:
    raw = json.dumps(
        _canonical_hash_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return dev_smoke._sha256_bytes(raw)


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
        raise v1.ScoringWorkerError("candidate.14 remediation boundary mismatch")
    return contract


def main() -> None:
    # Reuse the frozen checker-input and fail-closed policy implementation. Only
    # result-detail hashing and the immutable remediation contract boundary differ.
    v1.CONTRACT_CANDIDATE = CONTRACT_CANDIDATE
    v1._safe_result_hash = _safe_result_hash
    v1._validate_contract_and_inputs = _validate_remediation_contract_and_inputs
    v1.main()


if __name__ == "__main__":
    main()
