from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract

DATE = "2026-08-21"
CANDIDATE = "candidate.13"
FREEZE_ACK = "freeze-bfcl-multiturn-dev-scoring-before-label-access"
MULTI_TURN_CATEGORIES = (
    "multi_turn_base",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
    "multi_turn_long_context",
)
GENERATION_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-safety-contract-candidate.12-{DATE}.json"
)
GENERATION_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-generation-ledger-candidate.1-{DATE}.json"
)
CALIBRATION_PLAN = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-{DATE}.json"
)
SCORING_WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker.py"
SCORING_ORCHESTRATOR = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring.py"
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-contract-{CANDIDATE}-{DATE}.json"
)


class ScoringContractError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoringContractError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ScoringContractError(f"JSON object required: {path}")
    return value


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ScoringContractError("generation ledger must be non-symlink mode 0600")
    records: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ScoringContractError("generation ledger row must be an object")
            records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoringContractError("invalid generation ledger") from exc
    return records


def _source_descriptor(path: Path, relative_to: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(relative_to.resolve()).as_posix(),
        "sha256": dev_smoke._sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def build_contract(
    *,
    generation_ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
    generation_contract_path: Path = GENERATION_CONTRACT,
    generation_report_path: Path = GENERATION_REPORT,
    calibration_plan_path: Path = CALIBRATION_PLAN,
) -> dict[str, Any]:
    generation_contract = _load_json(generation_contract_path)
    generation_report = _load_json(generation_report_path)
    plan = _load_json(calibration_plan_path)
    if (
        generation_contract.get("schema")
        != "milai.dg10.bfcl-multiturn-safety-contract.v1"
        or generation_contract.get("candidate") != "candidate.12"
        or generation_contract.get("status")
        != "DEPENDENCY_REMEDIATION_FROZEN_FULL_RERUN_NOT_RUN"
        or generation_contract.get("bfcl_dev_answer_labels_opened") is not False
        or generation_contract.get("bfcl_test_labels_or_outputs_opened") is not False
        or generation_report.get("schema")
        != "milai.dg10.bfcl-multiturn-generation-ledger-report.v1"
        or generation_report.get("status") != "LABEL_FREE_GENERATION_LEDGER_SEALED"
        or generation_report.get("bfcl_dev_answer_labels_opened") is not False
        or generation_report.get("bfcl_test_labels_or_outputs_opened") is not False
        or plan.get("schema")
        != "milai.dg10.bfcl-v4-local-calibration-plan.v1"
        or plan.get("candidate") != "candidate.5"
        or plan.get("test_access_authorized") is not False
        or plan.get("quality_thresholds_frozen") is not False
    ):
        raise ScoringContractError("pre-scoring contract boundary mismatch")
    if (
        generation_report.get("inputs", {}).get("generation_contract_sha256")
        != dev_smoke._sha256_file(generation_contract_path)
        or generation_report.get("inputs", {}).get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
        or generation_report.get("repo_external_append_only_ledger", {}).get(
            "sha256"
        )
        != dev_smoke._sha256_file(generation_ledger_path)
    ):
        raise ScoringContractError("sealed generation hash binding mismatch")
    rows = _load_ledger(generation_ledger_path)
    schedule = generation_contract.get("generation_execution_schedule", {}).get(
        "ordered_case_ids"
    )
    ids = [row.get("case_id") for row in rows]
    if (
        not isinstance(schedule, list)
        or len(schedule) != 80
        or ids != schedule
        or len(set(ids)) != 80
        or any(row.get("evidence_complete") is not True for row in rows)
        or sum(int(row.get("native_model_requests", -1)) for row in rows) != 1649
        or sum(int(row.get("validated_native_receipts", -1)) for row in rows)
        != 1649
        or sum(int(row.get("unique_native_request_ids", -1)) for row in rows)
        != 1649
        or sum(int(row.get("retry_model_calls", -1)) for row in rows) != 0
        or sum(int(row.get("hidden_or_extra_model_calls", -1)) for row in rows)
        != 0
        or any(row.get("development_answer_labels_opened") is not False for row in rows)
        or any(row.get("test_material_opened") is not False for row in rows)
    ):
        raise ScoringContractError("sealed generation ledger invariants failed")
    plan_categories = plan.get("split", {}).get("categories", {})
    frozen_dev_ids: list[str] = []
    label_sources: dict[str, dict[str, Any]] = {}
    for category in MULTI_TURN_CATEGORIES:
        record = plan_categories.get(category)
        if not isinstance(record, dict):
            raise ScoringContractError(f"missing frozen dev category: {category}")
        category_ids = record.get("dev_case_ids")
        label_sha = record.get("possible_answer_file_sha256")
        if (
            not isinstance(category_ids, list)
            or len(category_ids) != 20
            or not isinstance(label_sha, str)
            or len(label_sha) != 64
            or record.get("labels_semantically_opened_by_plan") is not False
        ):
            raise ScoringContractError(f"invalid frozen dev category: {category}")
        frozen_dev_ids.extend(category_ids)
        label_sources[category] = {
            "path": f"bfcl_eval/data/possible_answer/BFCL_v4_{category}.json",
            "sha256": label_sha,
            "selected_dev_case_count": 20,
            "semantic_access_before_this_contract": False,
            "contract_builder_reads_label_bytes": False,
        }
    if set(frozen_dev_ids) != set(ids) or len(frozen_dev_ids) != 80:
        raise ScoringContractError("generation schedule differs from frozen dev split")
    root = bfcl_root.resolve()
    if bfcl_contract._git_head(root) != plan.get("inputs", {}).get("bfcl_git_head"):
        raise ScoringContractError("BFCL git HEAD differs from frozen plan")
    checker = (
        root
        / "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_checker.py"
    )
    upstream_closure = generation_contract.get("official_upstream_byte_closure", {})
    checker_expected = upstream_closure.get("core", {}).get(
        "multi_turn_checker_and_irrelevance_checker", {}
    ).get("sha256")
    if dev_smoke._sha256_file(checker) != checker_expected:
        raise ScoringContractError("official multi-turn checker bytes drifted")
    official_sources = {
        "official_multi_turn_checker": _source_descriptor(checker, root),
        "official_multi_turn_utils": _source_descriptor(
            root
            / "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_utils.py",
            root,
        ),
        "official_executable_backend_config": _source_descriptor(
            root / "bfcl_eval/constants/executable_backend_config.py", root
        ),
    }
    for name, value in upstream_closure.get("function_sources", {}).items():
        key = f"function_source_{name}"
        source_path = root / str(value["path"])
        descriptor = _source_descriptor(source_path, root)
        if descriptor["sha256"] != value.get("sha256"):
            raise ScoringContractError(f"official function source drifted: {key}")
        official_sources[key] = descriptor
    byte_closure = {
        "scoring_contract_builder": _source_descriptor(Path(__file__), ROOT),
        "scoring_worker": _source_descriptor(SCORING_WORKER, ROOT),
        "scoring_orchestrator": _source_descriptor(SCORING_ORCHESTRATOR, ROOT),
        **official_sources,
    }
    return {
        "schema": "milai.dg10.bfcl-multiturn-dev-scoring-contract.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_MULTITURN_DEV_SCORING_FROZEN_LABELS_NOT_OPENED",
        "quality_outcome": "NOT_SCORED",
        "bfcl_dev_generation_inputs_opened": True,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "inputs": {
            "generation_contract_sha256": dev_smoke._sha256_file(
                generation_contract_path
            ),
            "sealed_generation_report_sha256": dev_smoke._sha256_file(
                generation_report_path
            ),
            "sealed_generation_ledger_sha256": dev_smoke._sha256_file(
                generation_ledger_path
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(bundle_path),
            "calibration_plan_sha256": dev_smoke._sha256_file(
                calibration_plan_path
            ),
            "bfcl_git_head": bfcl_contract._git_head(root),
        },
        "sealed_generation_summary": {
            "case_count": 80,
            "generation_success_case_count": sum(
                row["generation_success"] is True for row in rows
            ),
            "generation_failure_case_count": sum(
                row["generation_success"] is not True for row in rows
            ),
            "native_model_requests": 1649,
            "validated_native_receipts": 1649,
            "unique_native_request_ids": 1649,
            "tokenizer_requests": sum(row["tokenizer_requests"] for row in rows),
            "retry_model_calls": 0,
            "hidden_or_extra_model_calls": 0,
        },
        "scoring_schedule": {
            "ordered_case_ids": ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(ids),
            "case_count": 80,
            "category_case_count": 20,
            "fresh_process_per_case": True,
            "worker_process_retries": 0,
        },
        "label_sources": label_sources,
        "scoring_policy": {
            "official_checker_invocations_per_case": {
                "multi_turn_checker": 1,
                "multi_turn_irrelevance_checker": 1,
            },
            "missing_turn_adapter": (
                "APPEND_EXPLICIT_EMPTY_TURNS_ONLY_NEVER_TRUNCATE_OR_REWRITE"
            ),
            "extra_turn_policy": "RETAIN_AND_FAIL_EXACT_TURN_COUNT",
            "generation_failure_latch_dominates": True,
            "checker_exception_policy": "INVALID_FAIL_CLOSED_INVOKE_OTHER_CHECKER",
            "decoder_or_gate_failure_can_count_as_no_call": False,
            "final_valid": (
                "generation_success AND evidence_complete AND exact_turn_count "
                "AND multi_turn_checker.valid AND "
                "multi_turn_irrelevance_checker.valid"
            ),
            "raw_ground_truth_repo_retention": "PROHIBITED",
            "raw_checker_details_repo_retention": "PROHIBITED",
            "model_or_provider_calls_during_scoring": 0,
        },
        "byte_closure": byte_closure,
        "gate_results": {
            "sealed_label_free_generation": "PASS_BOUND",
            "scoring_bytes": "FROZEN",
            "development_scoring": "AUTHORIZED_BY_EXACT_ACK_NOT_RUN",
            "test_execution": "NOT_AUTHORIZED",
            "BMG-03": "NO_GO_SCORING_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "The contract builder does not read development answer bytes; it binds the pre-existing dataset-lock hashes and exact selected IDs.",
            "The subsequent scoring workers may select exactly the 80 frozen dev answers and no test IDs.",
            "Adapted prompt mode remains non-native and non-leaderboard-comparable.",
            "This contract does not freeze a quality threshold or authorize test execution.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze BFCL multi-turn development scoring bytes before labels"
    )
    parser.add_argument("--freeze-scoring-contract", action="store_true")
    parser.add_argument("--freeze-ack")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.freeze_scoring_contract or args.freeze_ack != FREEZE_ACK:
        raise ScoringContractError(
            "contract freeze requires the flag and exact acknowledgement"
        )
    report = build_contract(
        generation_ledger_path=args.ledger.resolve(),
        bundle_path=args.bundle.resolve(),
        bfcl_root=args.bfcl_root.resolve(),
    )
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": report["status"],
                "bfcl_dev_answer_labels_opened": False,
                "test_access_authorized": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
