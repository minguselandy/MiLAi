from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Mapping
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
from scripts import run_dg10_bfcl_single_turn_dev_smoke as single_turn

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
MODEL_ID = dev_smoke.MODEL_ID
CATEGORIES = ("simple_java", "simple_javascript")
EXPECTED_CASE_COUNT = 14
GENERATION_ACK = "generate-exact-fourteen-java-javascript-dev-no-labels"
SCORING_ACK = "score-sealed-fourteen-java-javascript-dev-no-test"
PLAN = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-{DATE}.json"
)
CONTRACT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-contract-{CANDIDATE}-{DATE}.json"
)
GENERATION_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-generation-{CANDIDATE}-{DATE}.json"
)
SCORING_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-scoring-{CANDIDATE}-{DATE}.json"
)
CAPTURE_DIRECTORY = WORKSPACE_ROOT / "evidence/dg10-bfcl-language-dev"


class LanguageDevError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LanguageDevError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise LanguageDevError(f"JSON object required: {path}")
    return value


def _selected_ids(plan: Mapping[str, Any]) -> list[str]:
    output: list[str] = []
    categories = plan.get("split", {}).get("categories", {})
    for category in CATEGORIES:
        record = categories.get(category)
        if not isinstance(record, dict) or not isinstance(
            record.get("dev_case_ids"), list
        ):
            raise LanguageDevError(f"missing frozen language category: {category}")
        output.extend(record["dev_case_ids"])
    if len(output) != EXPECTED_CASE_COUNT or len(set(output)) != EXPECTED_CASE_COUNT:
        raise LanguageDevError("frozen language dev schedule drift")
    return output


def _category(case_id: str) -> str:
    source_id = case_id.removeprefix("bfcl_v4:")
    for category in CATEGORIES:
        if source_id.startswith(f"{category}_"):
            return category
    raise LanguageDevError("case is outside Java/JavaScript categories")


def _source_descriptor(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(root.resolve()).as_posix(),
        "sha256": dev_smoke._sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def build_contract(plan_path: Path, bfcl_root: Path) -> dict[str, Any]:
    plan = _load_json(plan_path)
    if (
        plan.get("schema") != "milai.dg10.bfcl-v4-local-calibration-plan.v1"
        or plan.get("candidate") != "candidate.5"
        or plan.get("status")
        != "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
        or plan.get("test_access_authorized") is not False
        or plan.get("quality_thresholds_frozen") is not False
        or plan.get("lane_contract", {}).get("protocol_label")
        != "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD"
    ):
        raise LanguageDevError("BFCL plan boundary mismatch")
    ids = _selected_ids(plan)
    root = bfcl_root.resolve()
    if bfcl_contract._git_head(root) != plan.get("inputs", {}).get("bfcl_git_head"):
        raise LanguageDevError("BFCL git HEAD drift")
    scorer_hashes = plan.get("scorer_contract", {}).get("scorer_file_sha256", {})
    paths = {
        "official_ast_checker": root / "bfcl_eval/eval_checker/ast_eval/ast_checker.py",
        "official_model_handler_utils": root / "bfcl_eval/model_handler/utils.py",
        "official_utils": root / "bfcl_eval/utils.py",
        "official_java_parser": root / "bfcl_eval/model_handler/parser/java_parser.py",
        "official_javascript_parser": root / "bfcl_eval/model_handler/parser/js_parser.py",
        "official_default_prompts": root / "bfcl_eval/constants/default_prompts.py",
    }
    if (
        dev_smoke._sha256_file(paths["official_ast_checker"])
        != scorer_hashes.get("ast_checker")
        or dev_smoke._sha256_file(paths["official_model_handler_utils"])
        != scorer_hashes.get("model_handler_utils")
    ):
        raise LanguageDevError("official BFCL scorer bytes drift")
    label_sources: dict[str, Any] = {}
    source_files: dict[str, Any] = {}
    for category in CATEGORIES:
        record = plan["split"]["categories"][category]
        label_sources[category] = {
            "path": f"bfcl_eval/data/possible_answer/BFCL_v4_{category}.json",
            "sha256": record["possible_answer_file_sha256"],
            "semantic_access_by_contract": False,
        }
        source_files[category] = {
            "path": f"bfcl_eval/data/BFCL_v4_{category}.json",
            "sha256": record["source_file_sha256"],
        }
    return {
        "schema": "milai.dg10.bfcl-language-dev-contract.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_LANGUAGE_DEV_GENERATION_FROZEN_LABELS_NOT_OPENED",
        "quality_outcome": "NOT_RUN",
        "bfcl_dev_generation_inputs_opened": False,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "inputs": {
            "calibration_plan_sha256": dev_smoke._sha256_file(plan_path),
            "bfcl_git_head": bfcl_contract._git_head(root),
        },
        "generation_schedule": {
            "ordered_case_ids": ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(ids),
            "case_count": EXPECTED_CASE_COUNT,
            "category_counts": {"simple_java": 9, "simple_javascript": 5},
            "model_requests_per_case": 1,
            "retry_model_calls": 0,
        },
        "generation_contract": {
            "temperature": 0,
            "seed": 20260821,
            "max_output_tokens": prompt_probe.MAX_OUTPUT_TOKENS,
            "native_tools_field_present": False,
            "tool_choice_field_present": False,
            "prompt_format": "FROZEN_BFCL_DEFAULT_PROMPT_WITH_OFFICIAL_LANGUAGE_HINTS",
            "raw_output_preserved_before_labels": True,
        },
        "scoring_contract": {
            "simple_java": {
                "decoder": "OFFICIAL_AST_PARSE_RETURN_FORMAT_JAVA",
                "checker": "OFFICIAL_AST_CHECKER_LANGUAGE_JAVA",
            },
            "simple_javascript": {
                "decoder": "OFFICIAL_AST_PARSE_RETURN_FORMAT_JAVASCRIPT",
                "checker": "OFFICIAL_AST_CHECKER_LANGUAGE_JAVASCRIPT",
            },
            "decoder_failure_policy": "INVALID_FAIL_CLOSED_NOT_NO_CALL",
            "official_leaderboard_claim": False,
        },
        "source_files": source_files,
        "label_sources": label_sources,
        "byte_closure": {
            "runner": _source_descriptor(Path(__file__), ROOT),
            **{
                key: _source_descriptor(path, root) for key, path in paths.items()
            },
        },
        "gate_results": {
            "language_dev_generation": "AUTHORIZED_BY_EXACT_ACK_NOT_RUN",
            "language_dev_scoring": "NOT_RUN_LABELS_UNOPENED",
            "test_execution": "NOT_AUTHORIZED",
            "BMG-03": "NO_GO_LANGUAGE_DEV_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This lane is adapted prompt mode, non-native, and non-leaderboard-comparable.",
            "The contract does not read answer bytes; only the later scoring phase selects the exact 14 dev answers.",
            "No test IDs, labels, or outputs are authorized.",
        ],
    }


def _load_contract(contract_path: Path, plan_path: Path, bfcl_root: Path) -> dict[str, Any]:
    contract = _load_json(contract_path)
    if (
        contract.get("schema") != "milai.dg10.bfcl-language-dev-contract.v1"
        or contract.get("candidate") != CANDIDATE
        or contract.get("status")
        != "BFCL_LANGUAGE_DEV_GENERATION_FROZEN_LABELS_NOT_OPENED"
        or contract.get("test_access_authorized") is not False
        or contract.get("byte_closure", {}).get("runner", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or contract.get("inputs", {}).get("calibration_plan_sha256")
        != dev_smoke._sha256_file(plan_path)
        or contract.get("inputs", {}).get("bfcl_git_head")
        != bfcl_contract._git_head(bfcl_root)
    ):
        raise LanguageDevError("language dev contract boundary mismatch")
    return contract


def _load_source_cases(
    contract: Mapping[str, Any], bfcl_root: Path
) -> dict[str, dict[str, Any]]:
    if str(bfcl_root) not in sys.path:
        sys.path.insert(0, str(bfcl_root))
    from bfcl_eval.utils import load_dataset_entry

    selected = set(contract["generation_schedule"]["ordered_case_ids"])
    output: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        source = contract["source_files"][category]
        source_path = bfcl_root / source["path"]
        if dev_smoke._sha256_file(source_path) != source["sha256"]:
            raise LanguageDevError("BFCL language source bytes drift")
        for row in load_dataset_entry(category):
            case_id = f"bfcl_v4:{row['id']}"
            if case_id in selected:
                output[case_id] = row
    if set(output) != selected:
        raise LanguageDevError("language source selection drift")
    return output


def _messages(prompt_utils: Any, source: Mapping[str, Any]) -> list[dict[str, Any]]:
    functions = source.get("function")
    questions = source.get("question")
    if (
        not isinstance(functions, list)
        or not isinstance(questions, list)
        or len(questions) != 1
        or not isinstance(questions[0], list)
    ):
        raise LanguageDevError("invalid BFCL language source case")
    system = prompt_utils.formulate_system_prompt(
        prompt_utils.DEFAULT_SYSTEM_PROMPT_FORMAT, copy.deepcopy(functions)
    )
    messages = [copy.deepcopy(dict(item)) for item in questions[0]]
    messages.insert(0, {"role": "system", "content": system})
    return messages


def run_generation(
    *,
    contract_path: Path,
    plan_path: Path,
    bfcl_root: Path,
    client: prompt_probe.PromptClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    contract = _load_contract(contract_path, plan_path, bfcl_root)
    sources = _load_source_cases(contract, bfcl_root)
    prompt_utils, prompt_utils_sha = prompt_probe._load_official_prompt_utils(bfcl_root)
    if prompt_utils_sha != contract["byte_closure"]["official_model_handler_utils"][
        "sha256"
    ]:
        raise LanguageDevError("official prompt utility bytes drift")
    run_id = f"dg10-bfcl-language-generation-{DATE}-{uuid4().hex[:12]}"
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    for case_id in contract["generation_schedule"]["ordered_case_ids"]:
        source = sources[case_id]
        messages = _messages(prompt_utils, source)
        completion = client.complete(
            messages, request_key=f"{run_id}:{case_id}"
        )
        records.append(
            {
                "case_id": case_id,
                "source_case_id": source["id"],
                "category": _category(case_id),
                "native_request_id": completion.native_request_id,
                "native_receipt_sha256": completion.native_receipt_sha256,
                "response_sha256": completion.response_sha256,
                "response_text_sha256": dev_smoke._sha256_bytes(
                    completion.text.encode("utf-8")
                ),
                "request_messages_sha256": dev_smoke._json_sha256(messages),
                "usage": dict(completion.usage),
                "latency_ms": round(completion.latency_ms, 3),
                "development_answer_label_opened": False,
                "test_material_opened": False,
            }
        )
        raw_records.append(
            {
                "case_id": case_id,
                "source_case": source,
                "messages": messages,
                "response_text": completion.text,
            }
        )
    client.post_identity_check()
    native_ids = [record["native_request_id"] for record in records]
    if (
        len(records) != EXPECTED_CASE_COUNT
        or len(set(native_ids)) != EXPECTED_CASE_COUNT
        or client.completion_requests != EXPECTED_CASE_COUNT
        or client.tokenizer_requests != EXPECTED_CASE_COUNT
    ):
        raise LanguageDevError("language generation accounting drift")
    report = {
        "schema": "milai.dg10.bfcl-language-dev-generation.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "BFCL_LANGUAGE_DEV_LABEL_FREE_GENERATION_SEALED",
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "bfcl_dev_generation_inputs_opened": True,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "local_vllm_requests": EXPECTED_CASE_COUNT,
        "local_tokenizer_requests": EXPECTED_CASE_COUNT,
        "unique_native_request_ids": EXPECTED_CASE_COUNT,
        "retry_model_calls": 0,
        "hidden_or_extra_model_calls": 0,
        "inputs": {
            "contract_sha256": dev_smoke._sha256_file(contract_path),
            "plan_sha256": dev_smoke._sha256_file(plan_path),
            "runner_sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
            "bfcl_git_head": bfcl_contract._git_head(bfcl_root),
        },
        "identity_pre": dict(client.identity_evidence),
        "identity_post": dict(client.identity_evidence),
        "records": records,
        "aggregates": {
            "case_count": EXPECTED_CASE_COUNT,
            "input_tokens": sum(int(row["usage"]["input_tokens"]) for row in records),
            "output_tokens": sum(int(row["usage"]["output_tokens"]) for row in records),
            "latency_ms_mean": round(mean(row["latency_ms"] for row in records), 3),
        },
        "repo_external_raw_generation": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "language_dev_generation": "SEALED",
            "language_dev_scoring": "NOT_RUN_LABELS_UNOPENED",
            "test_execution": "NOT_AUTHORIZED",
        },
    }
    sidecar = {
        "schema": "milai.dg10.bfcl-language-dev-generation-raw.v1",
        "run_id": run_id,
        "data_classification": "PUBLIC_BENCHMARK_DEV_PROMPT_SCHEMA_AND_MODEL_OUTPUT_NO_LABELS",
        "records": raw_records,
    }
    return report, sidecar


def _score_one(
    *,
    category: str,
    source: Mapping[str, Any],
    response_text: str,
    ground_truth: list[dict[str, Any]],
    decoder_utils: Any,
    checker: Any,
) -> dict[str, Any]:
    if category == "simple_java":
        return_format = decoder_utils.ReturnFormat.JAVA
        language = checker.Language.JAVA
    elif category == "simple_javascript":
        return_format = decoder_utils.ReturnFormat.JAVASCRIPT
        language = checker.Language.JAVASCRIPT
    else:
        raise LanguageDevError("unsupported language score category")
    try:
        decoded = decoder_utils.ast_parse(
            response_text, language=return_format, has_tool_call_tag=False
        )
        if not isinstance(decoded, list) or any(
            not isinstance(item, dict) for item in decoded
        ):
            raise ValueError("decoder output is not a list of call objects")
    except Exception as exc:
        return {
            "decoder_success": False,
            "decoder_error_type": type(exc).__name__,
            "official_checker_invocations": 0,
            "official_checker_valid": False,
            "tool_selection_correct": False,
            "argument_correctness": False,
            "checker_error_type": "ast_decoder:decoder_failed",
            "decoded_calls_sha256": None,
        }
    result = checker.ast_checker(
        list(source["function"]),
        decoded,
        ground_truth,
        language,
        category,
        MODEL_ID,
    )
    if not isinstance(result, dict) or not isinstance(result.get("valid"), bool):
        raise LanguageDevError("official language AST checker returned invalid result")
    actual_names = sorted(name for item in decoded for name in item)
    expected_names = sorted(name for item in ground_truth for name in item)
    return {
        "decoder_success": True,
        "decoder_error_type": None,
        "official_checker_invocations": 1,
        "official_checker_valid": bool(result["valid"]),
        "tool_selection_correct": actual_names == expected_names,
        "argument_correctness": bool(result["valid"])
        if actual_names == expected_names
        else False,
        "checker_error_type": result.get("error_type"),
        "decoded_calls_sha256": dev_smoke._json_sha256(decoded),
    }


def run_scoring(
    *,
    contract_path: Path,
    generation_report_path: Path,
    raw_generation_path: Path,
    plan_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    contract = _load_contract(contract_path, plan_path, bfcl_root)
    generation = _load_json(generation_report_path)
    raw_generation = _load_json(raw_generation_path)
    if (
        generation.get("schema") != "milai.dg10.bfcl-language-dev-generation.v1"
        or generation.get("status")
        != "BFCL_LANGUAGE_DEV_LABEL_FREE_GENERATION_SEALED"
        or generation.get("bfcl_dev_answer_labels_opened") is not False
        or generation.get("bfcl_test_labels_or_outputs_opened") is not False
        or generation.get("repo_external_raw_generation", {}).get("sha256")
        != dev_smoke._sha256_file(raw_generation_path)
        or raw_generation.get("schema")
        != "milai.dg10.bfcl-language-dev-generation-raw.v1"
        or generation.get("inputs", {}).get("contract_sha256")
        != dev_smoke._sha256_file(contract_path)
    ):
        raise LanguageDevError("sealed language generation boundary mismatch")
    if str(bfcl_root) not in sys.path:
        sys.path.insert(0, str(bfcl_root))
    from bfcl_eval.constants.enums import Language
    from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker
    from bfcl_eval.model_handler import utils as decoder_utils

    checker = type("Checker", (), {"Language": Language, "ast_checker": ast_checker})
    if dev_smoke._sha256_file(Path(decoder_utils.__file__)) != contract[
        "byte_closure"
    ]["official_model_handler_utils"]["sha256"]:
        raise LanguageDevError("official prompt/decoder utility bytes drift")
    sources = _load_source_cases(contract, bfcl_root)
    raw_by_id = {row["case_id"]: row for row in raw_generation["records"]}
    generation_by_id = {row["case_id"]: row for row in generation["records"]}
    records: list[dict[str, Any]] = []
    for case_id in contract["generation_schedule"]["ordered_case_ids"]:
        category = _category(case_id)
        source_id = case_id.removeprefix("bfcl_v4:")
        label_descriptor = contract["label_sources"][category]
        label_path = bfcl_root / label_descriptor["path"]
        if dev_smoke._sha256_file(label_path) != label_descriptor["sha256"]:
            raise LanguageDevError("language dev label bytes drift")
        answer = single_turn._load_selected_row(label_path, source_id)
        ground_truth = answer.get("ground_truth")
        if (
            answer.get("id") != source_id
            or not isinstance(ground_truth, list)
            or any(not isinstance(item, dict) for item in ground_truth)
        ):
            raise LanguageDevError("selected language dev answer is invalid")
        raw = raw_by_id.get(case_id)
        generation_row = generation_by_id.get(case_id)
        if (
            not isinstance(raw, dict)
            or not isinstance(generation_row, dict)
            or dev_smoke._sha256_bytes(raw["response_text"].encode("utf-8"))
            != generation_row["response_text_sha256"]
        ):
            raise LanguageDevError("raw language response binding drift")
        score = _score_one(
            category=category,
            source=sources[case_id],
            response_text=raw["response_text"],
            ground_truth=ground_truth,
            decoder_utils=decoder_utils,
            checker=checker,
        )
        records.append(
            {
                "case_id": case_id,
                "source_case_id": source_id,
                "category": category,
                "ground_truth_sha256": dev_smoke._json_sha256(ground_truth),
                "response_text_sha256": generation_row["response_text_sha256"],
                "raw_ground_truth_retained": False,
                "raw_response_retained_in_repo": False,
                **score,
            }
        )
    if len(records) != EXPECTED_CASE_COUNT:
        raise LanguageDevError("language dev score denominator drift")
    by_category: dict[str, Any] = {}
    for category in CATEGORIES:
        items = [row for row in records if row["category"] == category]
        by_category[category] = {
            "case_count": len(items),
            "official_checker_accuracy": round(
                sum(row["official_checker_valid"] for row in items) / len(items), 6
            ),
            "tool_selection_accuracy": round(
                sum(row["tool_selection_correct"] for row in items) / len(items), 6
            ),
            "decoder_failure_count": sum(
                not row["decoder_success"] for row in items
            ),
            "official_checker_invocations": sum(
                row["official_checker_invocations"] for row in items
            ),
        }
    valid_count = sum(row["official_checker_valid"] for row in records)
    return {
        "schema": "milai.dg10.bfcl-language-dev-scoring.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_LANGUAGE_DEV_SCORING_COMPLETE",
        "quality_outcome": "CHARACTERIZED_ONLY_THRESHOLDS_NOT_FROZEN",
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count_opened": EXPECTED_CASE_COUNT,
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "local_vllm_requests": 0,
        "inputs": {
            "contract_sha256": dev_smoke._sha256_file(contract_path),
            "generation_report_sha256": dev_smoke._sha256_file(
                generation_report_path
            ),
            "raw_generation_sha256": dev_smoke._sha256_file(raw_generation_path),
            "runner_sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
            "bfcl_git_head": bfcl_contract._git_head(bfcl_root),
        },
        "records": records,
        "aggregates": {
            "case_count": EXPECTED_CASE_COUNT,
            "official_checker_valid_count": valid_count,
            "official_checker_accuracy": round(valid_count / EXPECTED_CASE_COUNT, 6),
            "tool_selection_accuracy": round(
                sum(row["tool_selection_correct"] for row in records)
                / EXPECTED_CASE_COUNT,
                6,
            ),
            "decoder_failure_count": sum(
                not row["decoder_success"] for row in records
            ),
            "by_category": by_category,
        },
        "gate_results": {
            "BMG-03": "DEV_LANGUAGE_CHARACTERIZATION_COMPLETE",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "test_execution": "NOT_AUTHORIZED",
        },
        "known_limits": [
            "This is adapted prompt-mode development characterization, not an official leaderboard score.",
            "Decoder failure is always invalid and cannot be treated as a no-call success.",
            "No model or provider call occurs during scoring; test remains closed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze, generate, or score 14 BFCL Java/JavaScript dev cases"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze-generation-contract", action="store_true")
    action.add_argument("--execute-generation", action="store_true")
    action.add_argument("--score-sealed-generation", action="store_true")
    parser.add_argument("--execution-ack")
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--contract", type=Path, default=CONTRACT_OUTPUT)
    parser.add_argument("--generation-report", type=Path, default=GENERATION_OUTPUT)
    parser.add_argument("--raw-generation", type=Path)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--capture-directory", type=Path, default=CAPTURE_DIRECTORY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    root = args.bfcl_root.resolve()
    if args.freeze_generation_contract:
        report = build_contract(plan_path, root)
        output = (args.output or CONTRACT_OUTPUT).resolve()
        raw = dev_smoke._encoded_json(report)
        dev_smoke._write_new(output, raw)
        print(json.dumps({"output": str(output), "output_sha256": dev_smoke._sha256_bytes(raw), "status": report["status"], "labels_opened": False}, sort_keys=True))
        return
    if args.execute_generation:
        if args.execution_ack != GENERATION_ACK:
            raise LanguageDevError("generation requires exact acknowledgement")
        capture = dev_smoke._validate_capture_directory(args.capture_directory)
        client = prompt_probe.LocalPromptClient(
            args.base_url, args.identity_report, args.timeout
        )
        report, sidecar = run_generation(
            contract_path=args.contract.resolve(),
            plan_path=plan_path,
            bfcl_root=root,
            client=client,
        )
        sidecar_raw = dev_smoke._encoded_json(sidecar)
        sidecar_path = capture / f"{report['run_id']}.raw.json"
        dev_smoke._write_new(sidecar_path, sidecar_raw)
        report["repo_external_raw_generation"] = {
            "status": "SEALED_HASH_BOUND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": dev_smoke._sha256_bytes(sidecar_raw),
            "size": len(sidecar_raw),
            "mode": "0600",
        }
        output = (args.output or GENERATION_OUTPUT).resolve()
        report_raw = dev_smoke._encoded_json(report)
        dev_smoke._write_new(output, report_raw)
        print(json.dumps({"output": str(output), "output_sha256": dev_smoke._sha256_bytes(report_raw), "raw_generation": str(sidecar_path), "raw_generation_sha256": dev_smoke._sha256_bytes(sidecar_raw), "status": report["status"], "local_vllm_requests": EXPECTED_CASE_COUNT}, sort_keys=True))
        return
    if args.execution_ack != SCORING_ACK or args.raw_generation is None:
        raise LanguageDevError("scoring requires exact acknowledgement and raw generation")
    report = run_scoring(
        contract_path=args.contract.resolve(),
        generation_report_path=args.generation_report.resolve(),
        raw_generation_path=args.raw_generation.resolve(),
        plan_path=plan_path,
        bfcl_root=root,
    )
    output = (args.output or SCORING_OUTPUT).resolve()
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(output, raw)
    print(json.dumps({"output": str(output), "output_sha256": dev_smoke._sha256_bytes(raw), "status": report["status"], "official_checker_accuracy": report["aggregates"]["official_checker_accuracy"], "provider_requests": 0, "local_vllm_requests": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
