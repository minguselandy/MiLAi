from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_single_turn_dev_smoke as single_turn

DATE = "2026-08-21"
CONTRACT_CANDIDATE = "candidate.13"
MODEL_NAME = "Qwen3.6-35B-A3B-FP8-dg10-adapted-prompt"
CHECKER_RELATIVE_PATH = (
    "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_checker.py"
)


class ScoringWorkerError(RuntimeError):
    pass


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoringWorkerError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ScoringWorkerError(f"JSON object required: {path}")
    return value


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ScoringWorkerError("generation ledger row must be an object")
            records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoringWorkerError("invalid generation ledger") from exc
    return records


def _validate_decoded_turns(value: Any) -> list[list[list[str]]]:
    if not isinstance(value, list):
        raise ScoringWorkerError("decoded execution turns must be a list")
    output: list[list[list[str]]] = []
    for turn in value:
        if not isinstance(turn, list):
            raise ScoringWorkerError("decoded turn must be a list")
        output_turn: list[list[str]] = []
        for step in turn:
            if not isinstance(step, list) or any(
                not isinstance(call, str) for call in step
            ):
                raise ScoringWorkerError("decoded step must be a list of strings")
            output_turn.append(list(step))
        output.append(output_turn)
    return output


def totalize_missing_turns(
    decoded_turns: Sequence[Sequence[Sequence[str]]], expected_turn_count: int
) -> tuple[list[list[list[str]]], dict[str, Any]]:
    """Append explicit empty turns only; never delete or rewrite observed turns."""

    if expected_turn_count < 0:
        raise ScoringWorkerError("expected turn count cannot be negative")
    totalized = copy.deepcopy(list(decoded_turns))
    observed = len(totalized)
    missing = max(0, expected_turn_count - observed)
    totalized.extend([] for _ in range(missing))
    return totalized, {
        "policy": "APPEND_EXPLICIT_EMPTY_TURNS_ONLY_NEVER_TRUNCATE_OR_REWRITE",
        "observed_turn_count": observed,
        "expected_turn_count": expected_turn_count,
        "appended_empty_turn_count": missing,
        "extra_observed_turn_count": max(0, observed - expected_turn_count),
        "exact_turn_count_before_adapter": observed == expected_turn_count,
        "turns_truncated": 0,
        "observed_turns_rewritten": 0,
    }


def _safe_result_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    ).encode("utf-8")
    return dev_smoke._sha256_bytes(raw)


def _invoke_checker(name: str, function: Callable[..., Any], *args: Any) -> dict[str, Any]:
    try:
        raw = function(*args)
    except Exception as exc:
        return {
            "name": name,
            "invocation_count": 1,
            "returned": False,
            "valid": False,
            "error_type": f"CHECKER_EXCEPTION:{type(exc).__name__}",
            "result_sha256": dev_smoke._sha256_bytes(
                f"{type(exc).__name__}:{exc}".encode("utf-8", errors="replace")
            ),
        }
    if not isinstance(raw, dict) or not isinstance(raw.get("valid"), bool):
        return {
            "name": name,
            "invocation_count": 1,
            "returned": True,
            "valid": False,
            "error_type": "INVALID_CHECKER_RETURN",
            "result_sha256": _safe_result_hash(raw),
        }
    error_type = None
    if not raw["valid"]:
        candidate = raw.get("error_type")
        error_type = candidate if isinstance(candidate, str) else "UNSPECIFIED"
    return {
        "name": name,
        "invocation_count": 1,
        "returned": True,
        "valid": raw["valid"],
        "error_type": error_type,
        "result_sha256": _safe_result_hash(raw),
    }


def evaluate_case(
    *,
    generation_record: Mapping[str, Any],
    ground_truth: list[list[str]],
    test_entry: Mapping[str, Any],
    category: str,
    accuracy_checker: Callable[..., Any],
    irrelevance_checker: Callable[..., Any],
) -> dict[str, Any]:
    decoded = _validate_decoded_turns(
        generation_record.get("decoded_execution_calls_by_turn")
    )
    totalized, adapter = totalize_missing_turns(decoded, len(ground_truth))
    accuracy = _invoke_checker(
        "multi_turn_checker",
        accuracy_checker,
        totalized,
        ground_truth,
        copy.deepcopy(dict(test_entry)),
        category,
        MODEL_NAME,
    )
    irrelevance = _invoke_checker(
        "multi_turn_irrelevance_checker",
        irrelevance_checker,
        totalized,
        ground_truth,
    )
    generation_success = generation_record.get("generation_success") is True
    evidence_complete = generation_record.get("evidence_complete") is True
    failure_latch = not generation_success or not evidence_complete
    final_valid = bool(
        not failure_latch
        and adapter["exact_turn_count_before_adapter"]
        and accuracy["valid"]
        and irrelevance["valid"]
    )
    return {
        "case_id": generation_record.get("case_id"),
        "source_case_id": generation_record.get("source_case_id"),
        "category": category,
        "generation_success": generation_success,
        "generation_evidence_complete": evidence_complete,
        "generation_failure_code": generation_record.get("failure_code"),
        "generation_failure_latch": failure_latch,
        "turn_adapter": adapter,
        "official_checkers": {
            "multi_turn_checker": accuracy,
            "multi_turn_irrelevance_checker": irrelevance,
        },
        "both_official_checkers_invoked": (
            accuracy["invocation_count"] == 1
            and irrelevance["invocation_count"] == 1
        ),
        "final_valid": final_valid,
        "raw_ground_truth_retained": False,
        "raw_checker_details_retained": False,
    }


def _load_official_checkers(
    bfcl_root: Path, expected_sha256: str
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    checker_path = (bfcl_root / CHECKER_RELATIVE_PATH).resolve()
    if (
        checker_path.is_symlink()
        or dev_smoke._sha256_file(checker_path) != expected_sha256
    ):
        raise ScoringWorkerError("official multi-turn checker bytes drifted")
    if str(bfcl_root) not in sys.path:
        sys.path.insert(0, str(bfcl_root))
    from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_checker import (
        multi_turn_checker,
        multi_turn_irrelevance_checker,
    )

    return multi_turn_checker, multi_turn_irrelevance_checker


def _validate_contract_and_inputs(
    *,
    contract_path: Path,
    ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    contract = _load_json_object(contract_path)
    closure = contract.get("byte_closure", {})
    inputs = contract.get("inputs", {})
    if (
        contract.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scoring-contract.v1"
        or contract.get("candidate") != CONTRACT_CANDIDATE
        or contract.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_FROZEN_LABELS_NOT_OPENED"
        or contract.get("bfcl_dev_answer_labels_opened") is not False
        or contract.get("test_access_authorized") is not False
        or closure.get("scoring_worker", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or inputs.get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(ledger_path)
        or inputs.get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
        or bfcl_contract._git_head(bfcl_root)
        != inputs.get("bfcl_git_head")
    ):
        raise ScoringWorkerError("candidate.13 scoring boundary mismatch")
    return contract


def score_one_case(
    *,
    contract_path: Path,
    ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
    case_id: str,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    contract = _validate_contract_and_inputs(
        contract_path=contract_path,
        ledger_path=ledger_path,
        bundle_path=bundle_path,
        bfcl_root=bfcl_root,
    )
    selected = contract.get("scoring_schedule", {}).get("ordered_case_ids")
    if not isinstance(selected, list) or case_id not in selected:
        raise ScoringWorkerError("case is outside the frozen scoring schedule")
    ledger_matches = [
        row for row in _load_ledger(ledger_path) if row.get("case_id") == case_id
    ]
    bundle = _load_json_object(bundle_path)
    bundle_matches = [
        row for row in bundle.get("records", []) if row.get("case_id") == case_id
    ]
    if len(ledger_matches) != 1 or len(bundle_matches) != 1:
        raise ScoringWorkerError("case is not unique in generation evidence")
    generation_record = ledger_matches[0]
    bundle_record = bundle_matches[0]
    category = generation_record.get("category")
    source_case_id = generation_record.get("source_case_id")
    if not isinstance(category, str) or not isinstance(source_case_id, str):
        raise ScoringWorkerError("generation case identity is invalid")
    label_source = contract.get("label_sources", {}).get(category)
    if not isinstance(label_source, dict):
        raise ScoringWorkerError("category has no frozen development label source")
    label_path = (bfcl_root / str(label_source.get("path"))).resolve()
    try:
        label_path.relative_to(bfcl_root)
    except ValueError as exc:
        raise ScoringWorkerError("label path escapes frozen BFCL root") from exc
    if (
        label_path.is_symlink()
        or dev_smoke._sha256_file(label_path) != label_source.get("sha256")
    ):
        raise ScoringWorkerError("development label source bytes drifted")
    answer = single_turn._load_selected_row(label_path, source_case_id)
    ground_truth = answer.get("ground_truth")
    if (
        answer.get("id") != source_case_id
        or not isinstance(ground_truth, list)
        or any(
            not isinstance(turn, list)
            or any(not isinstance(call, str) for call in turn)
            for turn in ground_truth
        )
    ):
        raise ScoringWorkerError("selected development ground truth is invalid")
    test_entry = bundle_record.get("test_entry")
    if not isinstance(test_entry, dict) or test_entry.get("id") != source_case_id:
        raise ScoringWorkerError("frozen populated test entry is invalid")
    checker_sha = contract["byte_closure"]["official_multi_turn_checker"][
        "sha256"
    ]
    accuracy_checker, irrelevance_checker = _load_official_checkers(
        bfcl_root, checker_sha
    )
    record = evaluate_case(
        generation_record=generation_record,
        ground_truth=ground_truth,
        test_entry=test_entry,
        category=category,
        accuracy_checker=accuracy_checker,
        irrelevance_checker=irrelevance_checker,
    )
    record["ground_truth_sha256"] = dev_smoke._json_sha256(ground_truth)
    record["development_label_selected"] = True
    record["test_label_or_output_selected"] = False
    return {
        "schema": "milai.dg10.bfcl-multiturn-dev-scored-case.v1",
        "date": DATE,
        "candidate": CONTRACT_CANDIDATE,
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "status": "BFCL_MULTITURN_DEV_CASE_SCORED",
        "contract_sha256": dev_smoke._sha256_file(contract_path),
        "label_file_sha256": label_source["sha256"],
        "record": record,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score one sealed BFCL multi-turn development case"
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = score_one_case(
        contract_path=args.contract.resolve(),
        ledger_path=args.ledger.resolve(),
        bundle_path=args.bundle.resolve(),
        bfcl_root=args.bfcl_root.resolve(),
        case_id=args.case_id,
    )
    raw = dev_smoke._encoded_json(result)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "case_id": args.case_id,
                "final_valid": result["record"]["final_valid"],
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
