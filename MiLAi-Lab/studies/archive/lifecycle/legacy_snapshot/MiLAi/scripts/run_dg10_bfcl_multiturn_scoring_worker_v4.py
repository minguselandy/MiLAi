from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_scoring_worker as v1

CONTRACT_CANDIDATE = "candidate.16"
CONTRACT_SCHEMA = "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v3"
CONTRACT_STATUS = (
    "BFCL_MULTITURN_SCORING_REMEDIATION_V3_FROZEN_DEV_LABELS_ALREADY_OPENED"
)
HASH_ALGORITHM = "DG10_TYPED_CANONICAL_CHECKER_RESULT_SHA256_V1"
FINAL_VALID_FORMULA = "DG10_BFCL_MULTITURN_FINAL_VALID_V1"
_V1_SCORE_ONE_CASE = v1.score_one_case


class _LabelBoundaryReached(RuntimeError):
    pass


def _typed_canonical(value: Any) -> Any:
    if value is None:
        return ["none"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite float is not canonicalizable")
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, Mapping):
        pairs = [
            [_typed_canonical(key), _typed_canonical(item)]
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
        return ["mapping", pairs]
    if isinstance(value, list):
        return ["list", [_typed_canonical(item) for item in value]]
    if isinstance(value, tuple):
        return ["tuple", [_typed_canonical(item) for item in value]]
    if isinstance(value, (set, frozenset)):
        items = [_typed_canonical(item) for item in value]
        items.sort(
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return ["set" if isinstance(value, set) else "frozenset", items]
    raise TypeError(
        f"unsupported checker-result type: {type(value).__module__}."
        f"{type(value).__qualname__}"
    )


def _safe_result_hash(value: Any) -> str:
    canonical = _typed_canonical(value)
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return dev_smoke._sha256_bytes(raw)


def _validate_contract_and_inputs(
    *,
    contract_path: Path,
    ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    contract = v1._load_json_object(contract_path)
    closure = contract.get("byte_closure", {})
    inputs = contract.get("inputs", {})
    scoring_ids = contract.get("scoring_schedule", {}).get("ordered_case_ids")
    remediation_ids = contract.get("remediation_schedule", {}).get(
        "ordered_case_ids"
    )
    if (
        contract.get("schema") != CONTRACT_SCHEMA
        or contract.get("candidate") != CONTRACT_CANDIDATE
        or contract.get("status") != CONTRACT_STATUS
        or contract.get("bfcl_dev_answer_labels_opened") is not True
        or contract.get("bfcl_test_labels_or_outputs_opened") is not False
        or contract.get("test_access_authorized") is not False
        or not isinstance(scoring_ids, list)
        or not isinstance(remediation_ids, list)
        or scoring_ids != remediation_ids
        or len(scoring_ids) != 5
        or len(set(scoring_ids)) != 5
        or contract.get("hash_contract", {}).get("algorithm") != HASH_ALGORITHM
        or contract.get("scoring_policy", {}).get("final_valid_formula_id")
        != FINAL_VALID_FORMULA
        or closure.get("scoring_worker", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or inputs.get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(ledger_path)
        or inputs.get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
        or bfcl_contract._git_head(bfcl_root) != inputs.get("bfcl_git_head")
    ):
        raise v1.ScoringWorkerError("candidate.16 remediation boundary mismatch")
    return contract


def _score_one_case_with_provenance(**kwargs: Any) -> dict[str, Any]:
    result = _V1_SCORE_ONE_CASE(**kwargs)
    record = result.get("record")
    if not isinstance(record, dict):
        raise v1.ScoringWorkerError("scored record is absent")
    record["checker_result_hash_algorithm"] = HASH_ALGORITHM
    record["final_valid_formula_id"] = FINAL_VALID_FORMULA
    record["scoring_worker_candidate"] = CONTRACT_CANDIDATE
    return result


def _schedule_probe(contract_path: Path, case_id: str) -> tuple[int, dict[str, Any]]:
    contract = v1._load_json_object(contract_path)
    original_validate = v1._validate_contract_and_inputs
    original_load_ledger = v1._load_ledger

    def validate(**_kwargs: Any) -> dict[str, Any]:
        return contract

    def label_boundary(_path: Path) -> list[dict[str, Any]]:
        raise _LabelBoundaryReached

    v1._validate_contract_and_inputs = validate
    v1._load_ledger = label_boundary
    try:
        try:
            _V1_SCORE_ONE_CASE(
                contract_path=contract_path,
                ledger_path=Path("PROBE_GENERATION_LEDGER_NOT_OPENED"),
                bundle_path=Path("PROBE_BUNDLE_NOT_OPENED"),
                bfcl_root=Path("PROBE_BFCL_ROOT_NOT_OPENED"),
                case_id=case_id,
            )
        except _LabelBoundaryReached:
            status = "WOULD_ENTER_LABEL_BOUNDARY"
            exit_code = 0
        except v1.ScoringWorkerError as exc:
            if str(exc) != "case is outside the frozen scoring schedule":
                raise
            status = "REJECTED_AT_FROZEN_SCHEDULE"
            exit_code = 3
        else:
            raise v1.ScoringWorkerError("schedule probe did not stop at boundary")
    finally:
        v1._validate_contract_and_inputs = original_validate
        v1._load_ledger = original_load_ledger
    return exit_code, {
        "schema": "milai.dg10.bfcl-scoring-schedule-probe.v1",
        "status": status,
        "case_id": case_id,
        "label_loader_reached": status == "WOULD_ENTER_LABEL_BOUNDARY",
        "real_label_bytes_opened": False,
        "official_checker_loaded": False,
        "model_or_provider_calls": 0,
        "worker_path": str(Path(__file__).resolve()),
        "worker_sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
        "v1_worker_path": str(Path(v1.__file__).resolve()),
        "v1_worker_sha256": dev_smoke._sha256_file(Path(v1.__file__).resolve()),
    }


def _canonicalizer_probe() -> dict[str, Any]:
    left = {
        "state": {
            1: "integer-one",
            "1": "string-one",
            ("nested", 2): [{3: "three", "3": "string-three"}],
            "set": {"x", 4},
        }
    }
    right = {
        "state": {
            "set": {4, "x"},
            ("nested", 2): [{"3": "string-three", 3: "three"}],
            "1": "string-one",
            1: "integer-one",
        }
    }
    before = repr(left)
    left_hash = _safe_result_hash(left)
    right_hash = _safe_result_hash(right)
    distinct_type_hash = _safe_result_hash({1: "x"}) != _safe_result_hash(
        {"1": "x"}
    )
    unsupported_rejected = False
    try:
        _safe_result_hash({object(): "unsupported"})
    except TypeError:
        unsupported_rejected = True
    if (
        left_hash != right_hash
        or not distinct_type_hash
        or not unsupported_rejected
        or repr(left) != before
    ):
        raise v1.ScoringWorkerError("typed canonicalizer probe failed")
    synthetic_row = {
        "algorithm": HASH_ALGORITHM,
        "checker_result_sha256": left_hash,
        "details": left,
    }
    encoded = json.dumps(
        _typed_canonical(synthetic_row),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": "milai.dg10.bfcl-checker-result-hash-probe.v1",
        "status": "PASS",
        "algorithm": HASH_ALGORITHM,
        "golden_hash": left_hash,
        "insertion_order_independent": True,
        "typed_keys_distinct": True,
        "nested_mixed_keys_supported": True,
        "set_order_independent": True,
        "unsupported_types_fail_closed": True,
        "input_not_mutated": True,
        "synthetic_row_canonical_sha256": dev_smoke._sha256_bytes(encoded),
        "model_or_provider_calls": 0,
        "label_access": False,
    }


def main() -> None:
    if "--schedule-probe" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--schedule-probe", action="store_true")
        parser.add_argument("--contract", type=Path, required=True)
        parser.add_argument("--case-id", required=True)
        args = parser.parse_args()
        exit_code, result = _schedule_probe(args.contract.resolve(), args.case_id)
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(exit_code)
    if "--canonicalizer-probe" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--canonicalizer-probe", action="store_true")
        parser.parse_args()
        print(json.dumps(_canonicalizer_probe(), sort_keys=True))
        return
    v1.CONTRACT_CANDIDATE = CONTRACT_CANDIDATE
    v1._safe_result_hash = _safe_result_hash
    v1._validate_contract_and_inputs = _validate_contract_and_inputs
    v1.score_one_case = _score_one_case_with_provenance
    v1.main()


if __name__ == "__main__":
    main()
