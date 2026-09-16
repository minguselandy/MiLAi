from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke

DATE = "2026-08-21"
CANDIDATE = "candidate.5"
MODEL_ID = dev_smoke.MODEL_ID
_TEMPERATURE_TOOL = {
    "name": "fetch_temperature",
    "description": "Fetch the temperature for a synthetic city.",
    "parameters": {
        "type": "dict",
        "properties": {
            "city": {"type": "string", "description": "Synthetic city name."},
            "unit": {"type": "string", "description": "Temperature unit."},
        },
        "required": ["city", "unit"],
    },
}
_DISTANCE_TOOL = {
    "name": "convert_distance",
    "description": "Convert a synthetic distance between units.",
    "parameters": {
        "type": "dict",
        "properties": {
            "distance": {"type": "float", "description": "Input distance."},
            "from_unit": {"type": "string", "description": "Input unit."},
            "to_unit": {"type": "string", "description": "Output unit."},
        },
        "required": ["distance", "from_unit", "to_unit"],
    },
}
SYNTHETIC_PROBE_FIXTURES = (
    {
        "id": "select_one_of_two",
        "functions": (_TEMPERATURE_TOOL, _DISTANCE_TOOL),
        "user": "Call the one appropriate function to fetch the temperature for the synthetic city Zephyr-7 in celsius.",
        "expected_steps": (
            ({"fetch_temperature": {"city": "Zephyr-7", "unit": "celsius"}},),
        ),
        "tool_results": (),
    },
    {
        "id": "no_call",
        "functions": (_TEMPERATURE_TOOL, _DISTANCE_TOOL),
        "user": "Say exactly READY. Do not fetch a temperature or convert a distance.",
        "expected_steps": ((),),
        "tool_results": (),
    },
    {
        "id": "parallel_two",
        "functions": (
            {
                "name": "sum_values",
                "description": "Sum a synthetic integer array.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "values": {
                            "type": "array",
                            "description": "Values to sum.",
                            "items": {"type": "integer"},
                        }
                    },
                    "required": ["values"],
                },
            },
            {
                "name": "store_profile",
                "description": "Store a synthetic profile object.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "profile": {
                            "type": "dict",
                            "description": "Synthetic profile.",
                            "properties": {
                                "name": {"type": "string"},
                                "active": {"type": "boolean"},
                            },
                        }
                    },
                    "required": ["profile"],
                },
            },
        ),
        "user": "Call both independent functions: sum values 2, 5, and 8; and store a profile whose name is Probe and active is true.",
        "expected_steps": (
            (
                {"sum_values": {"values": [2, 5, 8]}},
                {"store_profile": {"profile": {"name": "Probe", "active": True}}},
            ),
        ),
        "tool_results": (),
    },
    {
        "id": "multi_turn_tool_result",
        "functions": (
            {
                "name": "inspect_inventory",
                "description": "Inspect synthetic inventory.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "item_id": {"type": "string", "description": "Item ID."}
                    },
                    "required": ["item_id"],
                },
            },
            {
                "name": "reserve_inventory",
                "description": "Reserve synthetic inventory after inspection.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "item_id": {"type": "string", "description": "Item ID."},
                        "quantity": {"type": "integer", "description": "Quantity."},
                        "authorization": {
                            "type": "dict",
                            "description": "Synthetic authorization.",
                            "properties": {"code": {"type": "string"}},
                        },
                    },
                    "required": ["item_id", "quantity", "authorization"],
                },
            },
        ),
        "user": "First call inspect_inventory for widget-syn-9. Wait for the returned inventory before deciding whether to reserve exactly 2 units.",
        "expected_steps": (
            ({"inspect_inventory": {"item_id": "widget-syn-9"}},),
            (
                {
                    "reserve_inventory": {
                        "item_id": "widget-syn-9",
                        "quantity": 2,
                        "authorization": {"code": "AUTH-SYN-7"},
                    }
                },
            ),
        ),
        "tool_results": (
            '{"available":4,"authorization":{"code":"AUTH-SYN-7"}}',
        ),
    },
)
SYNTHETIC_PROBE_CONTRACT = {
    "fixture_version": "dg10-bfcl-prompt-probe-v1",
    "dialogues": [
        {"id": "select_one_of_two", "model_rounds": 1, "oracle": "EXACT_CALL"},
        {"id": "no_call", "model_rounds": 1, "oracle": "NO_CALL"},
        {"id": "parallel_two", "model_rounds": 1, "oracle": "EXACT_CALLS_NO_ORDER"},
        {
            "id": "multi_turn_tool_result",
            "model_rounds": 2,
            "oracle": "EXACT_CALL_PER_STEP",
        },
    ],
    "total_model_rounds": 5,
    "retry_model_calls_max": 0,
    "benchmark_material": False,
    "fixtures_sha256": dev_smoke._json_sha256(SYNTHETIC_PROBE_FIXTURES),
    "covered_parameter_types": [
        "array",
        "boolean",
        "dict",
        "float",
        "integer",
        "string",
    ],
}
LOCAL_NON_LIVE_CATEGORIES = (
    "simple_python",
    "simple_java",
    "simple_javascript",
    "multiple",
    "parallel",
    "parallel_multiple",
    "irrelevance",
    "multi_turn_base",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
    "multi_turn_long_context",
)
ACCIDENTALLY_DISCLOSED_CASE_IDS = (
    "simple_java_43",
    "simple_python_74",
    "simple_python_294",
    "multiple_16",
)
ID_PREFIX = re.compile(rb'^\s*\{"id"\s*:\s*"([^"\\]*)"')
DEFAULT_DATASET_LOCK = (
    ROOT / f"docs/reports/DG-10-benchmark-dataset-lock-candidate.3-{DATE}.json"
)
DEFAULT_FEASIBILITY = (
    ROOT / f"docs/reports/DG-10-benchmark-feasibility-candidate.3-{DATE}.json"
)
DEFAULT_BFCL_ROOT = (
    WORKSPACE_ROOT
    / "benchmarks/gorilla-bfcl/berkeley-function-call-leaderboard"
)
DEFAULT_PROBE_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-prompt-capability-probe-candidate.1-{DATE}.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-{CANDIDATE}-{DATE}.json"
)


class BfclContractError(RuntimeError):
    pass


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BfclContractError(f"{label} must be an object")
    return value


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclContractError(f"invalid JSON file: {path}") from exc


def _load_report(path: Path, schema: str, status: str) -> dict[str, Any]:
    report = _require_object(_load_json(path), "report")
    if (
        report.get("schema") != schema
        or report.get("status") != status
        or report.get("test_access_authorized") is not False
        or report.get("quality_thresholds_frozen") is not False
    ):
        raise BfclContractError(f"report boundary mismatch: {path}")
    return report


def _category_for_source_id(source_id: str) -> str:
    matches = [
        category
        for category in LOCAL_NON_LIVE_CATEGORIES
        if source_id.startswith(f"{category}_")
    ]
    if len(matches) != 1:
        raise BfclContractError(f"cannot map BFCL source ID to category: {source_id}")
    return matches[0]


def _extract_ids_without_opening_payload(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, start=1):
            match = ID_PREFIX.match(raw)
            if match is None:
                raise BfclContractError(
                    f"BFCL row does not begin with a plain id: {path}:{line_no}"
                )
            try:
                source_id = match.group(1).decode("ascii")
            except UnicodeDecodeError as exc:
                raise BfclContractError("BFCL source ID must be ASCII") from exc
            ids.append(source_id)
    if len(ids) != len(set(ids)):
        raise BfclContractError(f"duplicate BFCL IDs in {path}")
    return ids


def _require_locked_file(root: Path, descriptor: Mapping[str, Any], label: str) -> Path:
    relative = descriptor.get("path")
    if not isinstance(relative, str) or not relative:
        raise BfclContractError(f"{label} lock path is invalid")
    path = root / relative
    if (
        not path.is_file()
        or path.stat().st_size != descriptor.get("size")
        or dev_smoke._sha256_file(path) != descriptor.get("sha256")
    ):
        raise BfclContractError(f"{label} differs from the dataset lock")
    return path


def _case_hash(source_id: str, category: str) -> str:
    return hashlib.sha256(
        f"dg10-bfcl-dev-2026-08-21-v1\0{category}\0{source_id}".encode()
    ).hexdigest()


def _select_dev(eligible: Sequence[str], category: str) -> list[str]:
    count = len(eligible) // 10
    if count <= 0:
        raise BfclContractError(f"BFCL category too small for <=10% dev split: {category}")
    selected = sorted(
        eligible, key=lambda source_id: (_case_hash(source_id, category), source_id)
    )[:count]
    return sorted(selected)


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BfclContractError("cannot resolve BFCL git HEAD")
    return result.stdout.strip()


def build_report(
    *,
    dataset_lock_path: Path = DEFAULT_DATASET_LOCK,
    feasibility_path: Path = DEFAULT_FEASIBILITY,
    bfcl_root: Path = DEFAULT_BFCL_ROOT,
    probe_report_path: Path = DEFAULT_PROBE_REPORT,
    disclosed_case_ids: Sequence[str] = ACCIDENTALLY_DISCLOSED_CASE_IDS,
) -> dict[str, Any]:
    dataset_lock = _load_report(
        dataset_lock_path.resolve(),
        "milai.dg10.benchmark-dataset-lock.v1",
        "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
    )
    feasibility = _load_report(
        feasibility_path.resolve(),
        "milai.dg10.benchmark-feasibility.v1",
        "FEASIBILITY_CANDIDATE_REVIEW_REQUIRED",
    )
    probe_report = _require_object(_load_json(probe_report_path.resolve()), "probe report")
    if (
        probe_report.get("schema")
        != "milai.dg10.bfcl-prompt-capability-probe.v1"
        or probe_report.get("candidate") != "candidate.1"
        or probe_report.get("status")
        != "BFCL_ADAPTED_PROMPT_SYNTHETIC_CAPABILITY_PROBE_PASS"
        or probe_report.get("benchmark_material_opened_by_probe") is not False
        or probe_report.get("test_access_authorized") is not False
        or probe_report.get("quality_thresholds_frozen") is not False
        or probe_report.get("local_vllm_requests") != 5
        or probe_report.get("retry_model_calls") != 0
        or probe_report.get("hidden_or_extra_model_calls") != 0
        or probe_report.get("provider_requests") != 0
        or probe_report.get("external_provider_requests") != 0
        or probe_report.get("aggregates", {}).get("dialogues_passed") != 4
        or probe_report.get("aggregates", {}).get("model_rounds_executed") != 5
        or probe_report.get("gate_results", {}).get("synthetic_prompt_capability")
        != "PASS"
        or probe_report.get("repo_external_sidecar", {}).get("status")
        != "WRITTEN_HASH_BOUND"
    ):
        raise BfclContractError("BFCL synthetic capability probe boundary mismatch")
    bfcl_feasibility = _require_object(
        _require_object(feasibility.get("datasets"), "feasibility datasets").get(
            "bfcl_v4_local_non_live"
        ),
        "BFCL feasibility",
    )
    if (
        bfcl_feasibility.get("decision")
        != "LOCAL_NON_LIVE_CASE_LIST_CANDIDATE_NOT_RUN"
        or feasibility.get("gate_results", {}).get("BMG-03")
        != "CANDIDATE_LOCKED_NOT_RUN"
    ):
        raise BfclContractError("BFCL feasibility boundary mismatch")
    bfcl_lock = _require_object(
        _require_object(dataset_lock.get("datasets"), "datasets").get(
            "bfcl_v4_local_non_live"
        ),
        "BFCL dataset lock",
    )
    root = bfcl_root.resolve()
    if _git_head(root) != bfcl_lock.get("git_head"):
        raise BfclContractError("BFCL git HEAD differs from dataset lock")
    locked_categories = _require_object(bfcl_lock.get("categories"), "BFCL categories")
    disclosed = set(disclosed_case_ids)
    all_ids: list[str] = []
    eligible_ids: list[str] = []
    dev_ids: list[str] = []
    category_records: dict[str, Any] = {}
    for category in LOCAL_NON_LIVE_CATEGORIES:
        descriptor = _require_object(locked_categories.get(category), category)
        source_path = _require_locked_file(root, descriptor, f"BFCL {category}")
        source_ids = _extract_ids_without_opening_payload(source_path)
        if (
            len(source_ids) != descriptor.get("case_count")
            or dev_smoke._json_sha256(sorted(source_ids))
            != descriptor.get("case_ids_sha256")
        ):
            raise BfclContractError(f"BFCL {category} ID coverage drift")
        possible_answer = _require_object(
            descriptor.get("possible_answer"), f"{category} possible-answer lock"
        )
        possible_path = possible_answer.get("path")
        if category == "irrelevance":
            if possible_path is not None:
                raise BfclContractError("BFCL irrelevance unexpectedly has labels")
        else:
            _require_locked_file(root, possible_answer, f"BFCL {category} labels")
        category_disclosed = sorted(set(source_ids) & disclosed)
        category_eligible = sorted(set(source_ids) - disclosed)
        category_dev = _select_dev(category_eligible, category)
        all_ids.extend(source_ids)
        eligible_ids.extend(category_eligible)
        dev_ids.extend(category_dev)
        category_records[category] = {
            "locked_case_count": len(source_ids),
            "eligible_case_count": len(category_eligible),
            "quarantined_case_count": len(category_disclosed),
            "quarantined_case_ids": category_disclosed,
            "dev_case_count": len(category_dev),
            "dev_case_ids": [f"bfcl_v4:{item}" for item in category_dev],
            "dev_case_ids_sha256": dev_smoke._json_sha256(category_dev),
            "test_case_count": len(category_eligible) - len(category_dev),
            "test_case_ids_sha256": dev_smoke._json_sha256(
                sorted(set(category_eligible) - set(category_dev))
            ),
            "source_file_sha256": descriptor["sha256"],
            "possible_answer_file_sha256": possible_answer.get("sha256"),
            "labels_semantically_opened_by_plan": False,
        }
    missing_disclosed = disclosed - set(all_ids)
    if missing_disclosed:
        raise BfclContractError(
            f"disclosed BFCL quarantine IDs are absent: {sorted(missing_disclosed)}"
        )
    all_ids = sorted(all_ids)
    eligible_ids = sorted(eligible_ids)
    dev_ids = sorted(dev_ids)
    test_ids = sorted(set(eligible_ids) - set(dev_ids))
    local_non_live = _require_object(
        bfcl_lock.get("local_non_live"), "BFCL local/non-live lock"
    )
    if (
        len(all_ids) != local_non_live.get("case_count")
        or dev_smoke._json_sha256(all_ids) != local_non_live.get("case_ids_sha256")
        or bfcl_feasibility.get("compatible_case_count") != len(all_ids)
        or bfcl_feasibility.get("compatible_case_ids_sha256")
        != local_non_live.get("case_ids_sha256")
        or len(dev_ids) / len(eligible_ids) > 0.10
    ):
        raise BfclContractError("BFCL aggregate split boundary mismatch")
    scorer_files = {
        "eval_runner": bfcl_lock["eval_runner"]["sha256"],
        "ast_checker": dev_smoke._sha256_file(
            root / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
        ),
        "multi_turn_checker": dev_smoke._sha256_file(
            root
            / "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_checker.py"
        ),
        "openai_completion_handler": dev_smoke._sha256_file(
            root
            / "bfcl_eval/model_handler/api_inference/openai_completion.py"
        ),
        "model_handler_utils": dev_smoke._sha256_file(
            root / "bfcl_eval/model_handler/utils.py"
        ),
        "default_prompts": dev_smoke._sha256_file(
            root / "bfcl_eval/constants/default_prompts.py"
        ),
        "qwen_local_prompt_handler": dev_smoke._sha256_file(
            root / "bfcl_eval/model_handler/local_inference/qwen.py"
        ),
        "base_oss_prompt_handler": dev_smoke._sha256_file(
            root
            / "bfcl_eval/model_handler/local_inference/base_oss_handler.py"
        ),
    }
    return {
        "schema": "milai.dg10.bfcl-v4-local-calibration-plan.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN",
        "quality_outcome": "CHARACTERIZED_ONLY",
        "data_boundary": "PUBLIC_BENCHMARK_METADATA_ONLY_LABEL_PAYLOAD_NOT_SEMANTICALLY_OPENED",
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "test_labels_or_outputs_opened_by_this_report": False,
        "inputs": {
            "dataset_lock_report_sha256": dev_smoke._sha256_file(
                dataset_lock_path.resolve()
            ),
            "feasibility_report_sha256": dev_smoke._sha256_file(
                feasibility_path.resolve()
            ),
            "bfcl_git_head": bfcl_lock["git_head"],
            "compatible_case_ids_sha256": local_non_live["case_ids_sha256"],
            "synthetic_capability_probe_report_sha256": dev_smoke._sha256_file(
                probe_report_path.resolve()
            ),
        },
        "lane_contract": {
            "name": "BMG03_ADAPTED_ENDPOINT_PROMPT_MODE_CANDIDATE",
            "normative_clarification_status": "REVIEW_REQUIRED_BROAD_EVERY_CASE_THREE_ARM_TEXT_UNRESOLVED",
            "memory_three_arm_gate_owner": "BMG-02",
            "bfcl_gate_owner": "BMG-03",
            "bfcl_memory_arms_executed": False,
            "same_vllm_required": True,
            "mcp_transport_claim": False,
            "native_function_calling_claim": False,
            "official_leaderboard_claim": False,
            "protocol_label": "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD",
            "native_auto_lane": {
                "status": "NOT_APPLICABLE_ENDPOINT_PROTOCOL_UNSUPPORTED",
                "http_status": 400,
                "successful_benchmark_model_rounds": 0,
                "vllm_error_body_sha256": "fa6b090e84a07959eee49f5e28e8211cd517844f3ecec0b9209cb1f68c57c69e",
                "reason": "FROZEN_ENDPOINT_HAS_NEITHER_ENABLE_AUTO_TOOL_CHOICE_NOR_TOOL_CALL_PARSER",
            },
        },
        "quarantine": {
            "reason": "PRECALIBRATION_ACCIDENTAL_LABEL_DISCLOSURE_EXCLUDED_FROM_ALL_RELEASE_DENOMINATORS",
            "case_count": len(disclosed),
            "case_ids": sorted(disclosed),
            "raw_label_payload_in_report": False,
            "eligible_for_dev": False,
            "eligible_for_test": False,
            "eligible_for_quality_thresholds": False,
        },
        "split": {
            "locked_case_count": len(all_ids),
            "eligible_case_count": len(eligible_ids),
            "eligible_case_ids_sha256": dev_smoke._json_sha256(eligible_ids),
            "dev_case_count": len(dev_ids),
            "dev_fraction": round(len(dev_ids) / len(eligible_ids), 6),
            "dev_case_ids": [f"bfcl_v4:{item}" for item in dev_ids],
            "dev_case_ids_sha256": dev_smoke._json_sha256(dev_ids),
            "test_case_count": len(test_ids),
            "test_case_ids_sha256": dev_smoke._json_sha256(test_ids),
            "selection": "DETERMINISTIC_SHA256_LOWEST_PER_CATEGORY_AFTER_PREDECLARED_QUARANTINE",
            "salt_version": "dg10-bfcl-dev-2026-08-21-v1",
            "max_dev_fraction": 0.10,
            "categories": category_records,
        },
        "generation_contract": {
            "model": MODEL_ID,
            "temperature": 0,
            "seed": 20260821,
            "max_output_tokens": 512,
            "request_api": "OPENAI_COMPATIBLE_CHAT_COMPLETIONS_ORDINARY_TEXT_ONLY",
            "native_tools_field_present": False,
            "tool_choice_field_present": False,
            "bfcl_function_schemas_serialized_in_system_prompt": True,
            "prompt_format": "ret_fmt=python&tool_call_tag=False&func_doc_fmt=json&prompt_fmt=plaintext&style=classic",
            "client_side_decode": "FROZEN_BFCL_DEFAULT_PYTHON_PROMPT_DECODER",
            "single_turn_model_calls_per_case": 1,
            "multi_turn_model_calls": "PER_DECLARED_TURN_AND_EXECUTION_STEP_CAPTURED_NOT_FIXED_1_OR_2",
            "retry_model_calls_max": 0,
            "hidden_or_extra_model_calls_max": 0,
            "same_frozen_vllm_identity": True,
        },
        "synthetic_capability_probe": {
            **SYNTHETIC_PROBE_CONTRACT,
            "contract_sha256": dev_smoke._json_sha256(SYNTHETIC_PROBE_CONTRACT),
            "gate": "ALL_APPLICABLE_DIALOGUES_AND_STEPS_MUST_PASS",
            "status": "PASS_BOUND",
            "report_sha256": dev_smoke._sha256_file(probe_report_path.resolve()),
            "model_or_threshold_selection_use": "PROHIBITED",
            "dev_or_test_denominator": False,
        },
        "loss_map": {
            "native_openai_tool_calls": "NOT_PRESERVED_TEXT_OUTPUT_ONLY",
            "function_name_and_typed_arguments": "PRESERVED_WHEN_DEFAULT_PYTHON_DECODER_SUCCEEDS",
            "parallel_call_order": "TRANSFORMED_SCORED_ORDER_INSENSITIVE_WHERE_OFFICIAL_CHECKER_DOES_SO",
            "no_call": "TRANSFORMED_TO_OFFICIAL_DECODER_FAILURE_OR_EMPTY_CALL_SET",
            "tool_result_transport": "TRANSFORMED_TO_BFCL_OPENAI_PROMPT_MODE_USER_MESSAGE_REPR",
            "java_and_javascript": "NOT_APPLICABLE_UNTIL_LANGUAGE_DECODER_DEPENDENCIES_ARE_FROZEN",
            "unsupported_schema_construct": "FAIL_CLOSED_NOT_APPLICABLE_NOT_SILENTLY_DROPPED",
        },
        "scorer_contract": {
            "selection_and_arguments": "BFCL_OFFICIAL_AST_CHECKER",
            "irrelevance_no_call": "BFCL_OFFICIAL_RELEVANCE_FILE_RUNNER",
            "multi_turn": "BFCL_OFFICIAL_MULTI_TURN_CHECKER_AND_LOCAL_FUNCTION_SOURCE_BACKENDS",
            "external_judge": False,
            "scorer_file_sha256": scorer_files,
            "dev_partial_evaluation_label": "CALIBRATION_ONLY_NOT_OFFICIAL_LEADERBOARD",
        },
        "metrics_to_freeze_after_dev": [
            "tool_selection_accuracy",
            "argument_correctness_accuracy",
            "relevance_no_call_accuracy",
            "multi_turn_recovery_accuracy",
            "invalid_tool_call_rate",
            "input_output_tokens_per_native_step",
            "native_rounds_per_case",
            "latency_per_native_step_and_case",
        ],
        "gate_results": {
            "BMG-03": "NO_GO_CALIBRATION_PLAN_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "contract_ambiguity": "REVIEW_REQUIRED",
        },
        "known_limits": [
            "This report freezes a <=10% BFCL dev split but does not open dev labels or execute model calls.",
            "Four accidentally disclosed label cases are quarantined from dev, test, thresholds, and release denominators.",
            "The broad DG-10 every-public-case three-arm sentence is unresolved; this separate BMG-03 lane is a candidate interpretation, not accepted clarification.",
            "BFCL characterizes agent tool-selection semantics and cannot prove MCP transport, relay, broker, UDS, or JSON-RPC behavior.",
            "Multi-turn cases require a per-step model-call schema; the LongMemEval 1/1/2 per-case schema must not be reused.",
            "The frozen endpoint rejects native tools with tool_choice=auto; candidate.3 supersedes that infeasible candidate.2 generation contract without changing the service.",
            "Prompt-mode results are adapted, client-decoded, non-native, and non-leaderboard-comparable; no unqualified overall BFCL score is permitted.",
        ],
    }


def _write_new(path: Path, report: Mapping[str, Any]) -> None:
    dev_smoke._write_new(path, dev_smoke._encoded_json(report))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze a BFCL V4 local/non-live <=10% dev calibration split"
    )
    parser.add_argument("--dataset-lock", type=Path, default=DEFAULT_DATASET_LOCK)
    parser.add_argument("--feasibility", type=Path, default=DEFAULT_FEASIBILITY)
    parser.add_argument("--bfcl-root", type=Path, default=DEFAULT_BFCL_ROOT)
    parser.add_argument("--probe-report", type=Path, default=DEFAULT_PROBE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(
        dataset_lock_path=args.dataset_lock,
        feasibility_path=args.feasibility,
        bfcl_root=args.bfcl_root,
        probe_report_path=args.probe_report,
    )
    _write_new(args.output.resolve(), report)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_file(args.output.resolve()),
                "eligible_case_count": report["split"]["eligible_case_count"],
                "dev_case_count": report["split"]["dev_case_count"],
                "dev_fraction": report["split"]["dev_fraction"],
                "quarantined_case_count": report["quarantine"]["case_count"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
