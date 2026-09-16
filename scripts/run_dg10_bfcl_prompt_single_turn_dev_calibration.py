from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_prompt_capability_probe as prompt_probe
from scripts import run_dg10_bfcl_prompt_single_turn_dev_smoke as single_smoke

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
SUPPORTED_CATEGORIES = (
    "simple_python",
    "multiple",
    "parallel",
    "parallel_multiple",
    "irrelevance",
)
EXPECTED_CASE_COUNT = 122
EXECUTION_ACK = "open-frozen-bfcl-dev-supported-122-no-test"
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-prompt-single-turn-dev-calibration-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-prompt-single-turn-dev-calibration"
)


class PromptCalibrationError(RuntimeError):
    pass


def _load_plan(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptCalibrationError("invalid BFCL calibration plan") from exc
    if (
        not isinstance(plan, dict)
        or plan.get("schema")
        != "milai.dg10.bfcl-v4-local-calibration-plan.v1"
        or plan.get("candidate") != bfcl_contract.CANDIDATE
        or plan.get("status")
        != "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
        or plan.get("synthetic_capability_probe", {}).get("status") != "PASS_BOUND"
        or plan.get("test_access_authorized") is not False
        or plan.get("quality_thresholds_frozen") is not False
    ):
        raise PromptCalibrationError("BFCL calibration plan boundary mismatch")
    categories = plan.get("split", {}).get("categories")
    if not isinstance(categories, dict):
        raise PromptCalibrationError("BFCL category split is invalid")
    selected: list[str] = []
    for category in SUPPORTED_CATEGORIES:
        record = categories.get(category)
        if not isinstance(record, dict) or not isinstance(
            record.get("dev_case_ids"), list
        ):
            raise PromptCalibrationError(f"BFCL dev category is invalid: {category}")
        selected.extend(record["dev_case_ids"])
    selected = sorted(selected)
    if (
        len(selected) != EXPECTED_CASE_COUNT
        or len(selected) != len(set(selected))
        or any(item not in plan["split"]["dev_case_ids"] for item in selected)
        or any(
            item.removeprefix("bfcl_v4:")
            in plan.get("quarantine", {}).get("case_ids", [])
            for item in selected
        )
    ):
        raise PromptCalibrationError("supported BFCL dev case set drift")
    return plan, selected


def _category_aggregates(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["category"])].append(record)
    output: dict[str, Any] = {}
    for category, items in sorted(grouped.items()):
        answers = [item["answer_record"] for item in items]
        arguments = [
            item["argument_correctness"]
            for item in answers
            if item["argument_correctness"] is not None
        ]
        no_calls = [
            item["no_call_correct"]
            for item in answers
            if item["no_call_correct"] is not None
        ]
        output[category] = {
            "case_count": len(items),
            "official_checker_accuracy": round(
                sum(int(item["official_checker_valid"]) for item in answers)
                / len(items),
                6,
            ),
            "tool_selection_accuracy": round(
                sum(int(item["tool_selection_correct"]) for item in answers)
                / len(items),
                6,
            ),
            "argument_correctness_accuracy": (
                round(sum(int(item) for item in arguments) / len(arguments), 6)
                if arguments
                else None
            ),
            "no_call_accuracy": (
                round(sum(int(item) for item in no_calls) / len(no_calls), 6)
                if no_calls
                else None
            ),
            "invalid_tool_call_rate": round(
                sum(int(item["invalid_tool_call"]) for item in answers) / len(items),
                6,
            ),
            "input_tokens": sum(int(item["usage"]["input_tokens"]) for item in items),
            "output_tokens": sum(
                int(item["usage"]["output_tokens"]) for item in items
            ),
            "latency_ms_mean": round(mean(float(item["latency_ms"]) for item in items), 3),
        }
    return output


def run_calibration(
    *,
    dataset_lock_path: Path,
    plan_path: Path,
    bfcl_root: Path,
    client: prompt_probe.PromptClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    plan, case_ids = _load_plan(plan_path.resolve())
    run_id = f"dg10-bfcl-prompt-dev-calibration-{DATE}-{uuid4().hex[:12]}"
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    input_evidence: dict[str, Any] | None = None
    for case_id in case_ids:
        child_report, child_sidecar = single_smoke.run_smoke(
            dataset_lock_path=dataset_lock_path,
            plan_path=plan_path,
            bfcl_root=bfcl_root,
            case_id=case_id,
            client=client,
        )
        if child_report["record"]["case_id"] != case_id:
            raise PromptCalibrationError("BFCL child record case ID drift")
        records.append(child_report["record"])
        raw_records.append(child_sidecar["record"])
        current_input = {
            key: value
            for key, value in child_report["inputs"].items()
            if key
            not in {
                "selected_case_id",
                "selected_case_id_sha256",
                "source_file_sha256",
                "possible_answer_file_sha256",
            }
        }
        if input_evidence is None:
            input_evidence = current_input
        elif current_input != input_evidence:
            raise PromptCalibrationError("BFCL child input evidence drift")
    ended = datetime.now(UTC)
    native_ids = [str(item["native_request_id"]) for item in records]
    if (
        len(records) != EXPECTED_CASE_COUNT
        or len(native_ids) != len(set(native_ids))
        or client.completion_requests != EXPECTED_CASE_COUNT
        or client.tokenizer_requests != EXPECTED_CASE_COUNT
    ):
        raise PromptCalibrationError("BFCL partial calibration accounting drift")
    category_metrics = _category_aggregates(records)
    official_valid = sum(
        int(item["answer_record"]["official_checker_valid"]) for item in records
    )
    report = {
        "schema": "milai.dg10.bfcl-prompt-single-turn-dev-calibration.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "BFCL_ADAPTED_PROMPT_SUPPORTED_SINGLE_TURN_DEV_CALIBRATION_COMPLETE_PARTIAL",
        "quality_outcome": "CHARACTERIZED_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "PUBLIC_DEV_LABELS_OPENED_RAW_CONTENT_REPO_EXTERNAL_HASHED_ONLY",
        "bfcl_dev_labels_opened": True,
        "bfcl_dev_case_count_opened": EXPECTED_CASE_COUNT,
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": EXPECTED_CASE_COUNT,
        "local_tokenizer_requests": EXPECTED_CASE_COUNT,
        "unique_native_request_ids": EXPECTED_CASE_COUNT,
        "hidden_or_extra_model_calls": 0,
        "retry_model_calls": 0,
        "identity_pre": dict(client.identity_evidence),
        "identity_post": "PENDING_MAIN_POST_CHECK",
        "inputs": {
            **(input_evidence or {}),
            "dataset_lock_report_sha256": dev_smoke._sha256_file(
                dataset_lock_path.resolve()
            ),
            "adapted_plan_sha256": dev_smoke._sha256_file(plan_path.resolve()),
            "selected_supported_dev_case_ids_sha256": dev_smoke._json_sha256(
                case_ids
            ),
        },
        "protocol": {
            "label": plan["lane_contract"]["protocol_label"],
            "supported_categories": list(SUPPORTED_CATEGORIES),
            "native_tools_field_present": False,
            "tool_choice_field_present": False,
            "native_function_calling_claim": False,
            "official_leaderboard_claim": False,
            "unqualified_overall_bfcl_score": False,
            "mcp_transport_claim": False,
        },
        "coverage": {
            "frozen_dev_total": plan["split"]["dev_case_count"],
            "executed_supported_single_turn": EXPECTED_CASE_COUNT,
            "not_executed_total": plan["split"]["dev_case_count"]
            - EXPECTED_CASE_COUNT,
            "not_executed_java_javascript": 14,
            "not_executed_multi_turn": 80,
            "coverage_fraction": round(
                EXPECTED_CASE_COUNT / plan["split"]["dev_case_count"], 6
            ),
        },
        "records": records,
        "aggregates": {
            "adapted_supported_subset": {
                "case_count": EXPECTED_CASE_COUNT,
                "official_checker_accuracy": round(
                    official_valid / EXPECTED_CASE_COUNT, 6
                ),
                "input_tokens": sum(
                    int(item["usage"]["input_tokens"]) for item in records
                ),
                "output_tokens": sum(
                    int(item["usage"]["output_tokens"]) for item in records
                ),
                "latency_ms_mean": round(
                    mean(float(item["latency_ms"]) for item in records), 3
                ),
            },
            "per_category": category_metrics,
        },
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-03": "NO_GO_PARTIAL_122_OF_216_DEV_ONLY",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "supported_single_turn_dev_calibration": "COMPLETE",
            "contract_ambiguity": "REVIEW_REQUIRED",
        },
        "known_limits": [
            "This executes 122 supported dev cases; 14 Java/JavaScript and 80 multi-turn cases remain unexecuted.",
            "The adapted supported-subset aggregate is not an unqualified BFCL score and is not leaderboard-comparable.",
            "This report does not freeze thresholds or authorize test access.",
            "No native function-calling, MCP wire, memory-arm, or every-public-case claim is supported.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.bfcl-prompt-single-turn-dev-calibration-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPTS_TOOL_SCHEMAS_LABELS_AND_OUTPUTS",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all 122 supported adapted BFCL single-turn dev cases"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--calibration-ack")
    parser.add_argument(
        "--dataset-lock", type=Path, default=bfcl_contract.DEFAULT_DATASET_LOCK
    )
    parser.add_argument("--plan", type=Path, default=bfcl_contract.DEFAULT_OUTPUT)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if (
        not args.execute_local_vllm
        or args.data_boundary_ack != dev_smoke.DATA_BOUNDARY_ACK
        or args.calibration_ack != EXECUTION_ACK
    ):
        raise PromptCalibrationError("real dev calibration requires all exact acknowledgements")
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
    except dev_smoke.DevSmokeError as exc:
        raise PromptCalibrationError(str(exc)) from exc
    client = prompt_probe.LocalPromptClient(
        args.base_url, args.identity_report, args.timeout
    )
    report, sidecar = run_calibration(
        dataset_lock_path=args.dataset_lock,
        plan_path=args.plan,
        bfcl_root=args.bfcl_root,
        client=client,
    )
    report["identity_post"] = dict(client.post_identity_check())
    sidecar_raw = dev_smoke._encoded_json(sidecar)
    sidecar_path = capture_directory / f"{report['run_id']}.raw.json"
    dev_smoke._write_new(sidecar_path, sidecar_raw)
    report["repo_external_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": dev_smoke._sha256_bytes(sidecar_raw),
        "size": len(sidecar_raw),
        "mode": "0600",
    }
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(report_raw),
                "sidecar": str(sidecar_path),
                "sidecar_sha256": dev_smoke._sha256_bytes(sidecar_raw),
                "status": report["status"],
                "case_count": report["coverage"]["executed_supported_single_turn"],
                "official_checker_accuracy": report["aggregates"][
                    "adapted_supported_subset"
                ]["official_checker_accuracy"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
