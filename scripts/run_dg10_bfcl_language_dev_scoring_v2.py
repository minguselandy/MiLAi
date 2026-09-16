from __future__ import annotations

import argparse
import importlib
import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_language_dev as v1
from scripts import run_dg10_bfcl_single_turn_dev_smoke as single_turn

DATE = "2026-08-21"
CANDIDATE = "candidate.2"
FREEZE_ACK = "freeze-language-scoring-v2-optional-provider-import-isolated"
SCORE_ACK = "score-sealed-fourteen-language-dev-v2-no-test"
CONTRACT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-scoring-contract-{CANDIDATE}-{DATE}.json"
)
SCORING_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-language-dev-scoring-{CANDIDATE}-{DATE}.json"
)


class LanguageScoringV2Error(RuntimeError):
    pass


def _load_checker_and_decoder(
    bfcl_root: Path,
) -> tuple[Any, Any, dict[str, str]]:
    root_string = str(bfcl_root.resolve())
    inserted = root_string not in sys.path
    if inserted:
        sys.path.insert(0, root_string)
    model_config_name = "bfcl_eval.constants.model_config"
    original_model_config = sys.modules.get(model_config_name)
    model_config = types.ModuleType(model_config_name)
    model_config.MODEL_CONFIG_MAPPING = {
        v1.MODEL_ID: types.SimpleNamespace(underscore_to_dot=False)
    }
    sys.modules[model_config_name] = model_config
    try:
        checker = importlib.import_module(
            "bfcl_eval.eval_checker.ast_eval.ast_checker"
        )
        decoder = importlib.import_module("bfcl_eval.model_handler.utils")
    finally:
        if original_model_config is None:
            sys.modules.pop(model_config_name, None)
        else:
            sys.modules[model_config_name] = original_model_config
        if inserted:
            sys.path.remove(root_string)
    hashes = {
        "official_ast_checker": dev_smoke._sha256_file(Path(checker.__file__)),
        "official_model_handler_utils": dev_smoke._sha256_file(
            Path(decoder.__file__)
        ),
        "official_java_converter": dev_smoke._sha256_file(
            bfcl_root
            / "bfcl_eval/eval_checker/ast_eval/type_convertor/java_type_converter.py"
        ),
        "official_javascript_converter": dev_smoke._sha256_file(
            bfcl_root
            / "bfcl_eval/eval_checker/ast_eval/type_convertor/js_type_converter.py"
        ),
    }
    return checker, decoder, hashes


def _synthetic_probe(checker: Any, decoder: Any) -> dict[str, Any]:
    fixtures = (
        {
            "category": "simple_java",
            "response": "[fetch(value=1)]",
            "function": [
                {
                    "name": "fetch",
                    "description": "fixture",
                    "parameters": {
                        "type": "dict",
                        "properties": {
                            "value": {"type": "integer", "description": "fixture"}
                        },
                        "required": ["value"],
                    },
                }
            ],
            "ground_truth": [{"fetch": {"value": [1]}}],
            "return_format": decoder.ReturnFormat.JAVA,
            "language": checker.Language.JAVA,
        },
        {
            "category": "simple_javascript",
            "response": "[fetch(value=true)]",
            "function": [
                {
                    "name": "fetch",
                    "description": "fixture",
                    "parameters": {
                        "type": "dict",
                        "properties": {
                            "value": {"type": "Boolean", "description": "fixture"}
                        },
                        "required": ["value"],
                    },
                }
            ],
            "ground_truth": [{"fetch": {"value": [True]}}],
            "return_format": decoder.ReturnFormat.JAVASCRIPT,
            "language": checker.Language.JAVASCRIPT,
        },
    )
    results: list[dict[str, Any]] = []
    for fixture in fixtures:
        decoded = decoder.ast_parse(
            fixture["response"],
            language=fixture["return_format"],
            has_tool_call_tag=False,
        )
        result = checker.ast_checker(
            fixture["function"],
            decoded,
            fixture["ground_truth"],
            fixture["language"],
            fixture["category"],
            v1.MODEL_ID,
        )
        if not isinstance(result, dict) or result.get("valid") is not True:
            raise LanguageScoringV2Error(
                f"synthetic language checker probe failed: {fixture['category']}"
            )
        results.append(
            {
                "category": fixture["category"],
                "decoded_sha256": dev_smoke._json_sha256(decoded),
                "checker_result_sha256": dev_smoke._json_sha256(result),
                "valid": True,
            }
        )
    return {
        "status": "PASS",
        "fixture_count": 2,
        "results": results,
        "benchmark_labels_opened": False,
        "model_or_provider_calls": 0,
    }


def build_contract(
    *,
    generation_contract_path: Path,
    generation_report_path: Path,
    raw_generation_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    generation_contract = v1._load_json(generation_contract_path)
    generation_report = v1._load_json(generation_report_path)
    raw_generation = v1._load_json(raw_generation_path)
    if (
        generation_contract.get("schema")
        != "milai.dg10.bfcl-language-dev-contract.v1"
        or generation_contract.get("status")
        != "BFCL_LANGUAGE_DEV_GENERATION_FROZEN_LABELS_NOT_OPENED"
        or generation_report.get("schema")
        != "milai.dg10.bfcl-language-dev-generation.v1"
        or generation_report.get("status")
        != "BFCL_LANGUAGE_DEV_LABEL_FREE_GENERATION_SEALED"
        or generation_report.get("bfcl_dev_answer_labels_opened") is not False
        or generation_report.get("bfcl_test_labels_or_outputs_opened") is not False
        or generation_report.get("repo_external_raw_generation", {}).get("sha256")
        != dev_smoke._sha256_file(raw_generation_path)
        or raw_generation.get("schema")
        != "milai.dg10.bfcl-language-dev-generation-raw.v1"
        or generation_report.get("local_vllm_requests") != 14
        or generation_report.get("retry_model_calls") != 0
        or generation_report.get("hidden_or_extra_model_calls") != 0
    ):
        raise LanguageScoringV2Error("sealed language generation boundary mismatch")
    checker, decoder, hashes = _load_checker_and_decoder(bfcl_root)
    for key in ("official_ast_checker", "official_model_handler_utils"):
        if (
            hashes[key]
            != generation_contract.get("byte_closure", {}).get(key, {}).get(
                "sha256"
            )
        ):
            raise LanguageScoringV2Error(f"official scoring source drift: {key}")
    probe = _synthetic_probe(checker, decoder)
    ids = generation_contract["generation_schedule"]["ordered_case_ids"]
    return {
        "schema": "milai.dg10.bfcl-language-dev-scoring-contract.v2",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_LANGUAGE_DEV_SCORING_V2_FROZEN_LABELS_NOT_OPENED",
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
            "generation_report_sha256": dev_smoke._sha256_file(
                generation_report_path
            ),
            "raw_generation_sha256": dev_smoke._sha256_file(raw_generation_path),
            "bfcl_git_head": bfcl_contract._git_head(bfcl_root),
        },
        "scoring_schedule": {
            "ordered_case_ids": ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(ids),
            "case_count": 14,
        },
        "scoring_policy": {
            "source_function_docs": "OFFICIAL_RAW_NO_LANGUAGE_HINT_TYPE_REWRITE",
            "simple_java_decoder": "OFFICIAL_RETURN_FORMAT_JAVA",
            "simple_javascript_decoder": "OFFICIAL_RETURN_FORMAT_JAVASCRIPT",
            "checker": "OFFICIAL_AST_CHECKER_LANGUAGE_SPECIFIC",
            "decoder_failure": "INVALID_FAIL_CLOSED",
            "optional_provider_import_isolation": (
                "STUB_MODEL_CONFIG_ONLY_REAL_DECODERS_AND_TYPE_CONVERTERS"
            ),
            "model_or_provider_calls": 0,
        },
        "synthetic_real_parser_checker_probe": probe,
        "label_sources": generation_contract["label_sources"],
        "byte_closure": {
            "scoring_runner": {
                "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
                "sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
                "size": Path(__file__).stat().st_size,
            },
            **{
                key: {"sha256": value} for key, value in hashes.items()
            },
        },
        "gate_results": {
            "candidate1_scoring": "FAILED_PRE_LABEL_OPTIONAL_PROVIDER_IMPORT_BOUND",
            "candidate2_loader_probe": "PASS_BOUND",
            "candidate2_scoring": "AUTHORIZED_BY_EXACT_ACK_NOT_RUN",
            "test_execution": "NOT_AUTHORIZED",
            "BMG-03": "NO_GO_LANGUAGE_SCORING_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
    }


def _load_raw_source_cases(
    contract: dict[str, Any], bfcl_root: Path
) -> dict[str, dict[str, Any]]:
    root_string = str(bfcl_root)
    if root_string not in sys.path:
        sys.path.insert(0, root_string)
    from bfcl_eval.utils import load_dataset_entry

    selected = set(contract["scoring_schedule"]["ordered_case_ids"])
    output: dict[str, dict[str, Any]] = {}
    for category in v1.CATEGORIES:
        for row in load_dataset_entry(
            category, include_language_specific_hint=False
        ):
            case_id = f"bfcl_v4:{row['id']}"
            if case_id in selected:
                output[case_id] = row
    if set(output) != selected:
        raise LanguageScoringV2Error("raw scoring source selection drift")
    return output


def run_scoring(
    *,
    contract_path: Path,
    generation_report_path: Path,
    raw_generation_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    contract = v1._load_json(contract_path)
    generation = v1._load_json(generation_report_path)
    raw_generation = v1._load_json(raw_generation_path)
    if (
        contract.get("schema")
        != "milai.dg10.bfcl-language-dev-scoring-contract.v2"
        or contract.get("candidate") != CANDIDATE
        or contract.get("status")
        != "BFCL_LANGUAGE_DEV_SCORING_V2_FROZEN_LABELS_NOT_OPENED"
        or contract.get("byte_closure", {}).get("scoring_runner", {}).get(
            "sha256"
        )
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or contract.get("inputs", {}).get("generation_report_sha256")
        != dev_smoke._sha256_file(generation_report_path)
        or contract.get("inputs", {}).get("raw_generation_sha256")
        != dev_smoke._sha256_file(raw_generation_path)
        or generation.get("status")
        != "BFCL_LANGUAGE_DEV_LABEL_FREE_GENERATION_SEALED"
        or generation.get("repo_external_raw_generation", {}).get("sha256")
        != dev_smoke._sha256_file(raw_generation_path)
        or raw_generation.get("schema")
        != "milai.dg10.bfcl-language-dev-generation-raw.v1"
    ):
        raise LanguageScoringV2Error("candidate.2 scoring boundary mismatch")
    checker, decoder, hashes = _load_checker_and_decoder(bfcl_root)
    if any(
        contract["byte_closure"][key]["sha256"] != value
        for key, value in hashes.items()
    ):
        raise LanguageScoringV2Error("candidate.2 scorer byte closure drift")
    sources = _load_raw_source_cases(contract, bfcl_root)
    raw_by_id = {row["case_id"]: row for row in raw_generation["records"]}
    generation_by_id = {row["case_id"]: row for row in generation["records"]}
    records: list[dict[str, Any]] = []
    for case_id in contract["scoring_schedule"]["ordered_case_ids"]:
        category = v1._category(case_id)
        source_id = case_id.removeprefix("bfcl_v4:")
        descriptor = contract["label_sources"][category]
        label_path = bfcl_root / descriptor["path"]
        if dev_smoke._sha256_file(label_path) != descriptor["sha256"]:
            raise LanguageScoringV2Error("language dev label source drift")
        answer = single_turn._load_selected_row(label_path, source_id)
        ground_truth = answer.get("ground_truth")
        if (
            answer.get("id") != source_id
            or not isinstance(ground_truth, list)
            or any(not isinstance(item, dict) for item in ground_truth)
        ):
            raise LanguageScoringV2Error("selected language answer invalid")
        raw = raw_by_id[case_id]
        generation_row = generation_by_id[case_id]
        if (
            dev_smoke._sha256_bytes(raw["response_text"].encode("utf-8"))
            != generation_row["response_text_sha256"]
        ):
            raise LanguageScoringV2Error("response text binding drift")
        score = v1._score_one(
            category=category,
            source=sources[case_id],
            response_text=raw["response_text"],
            ground_truth=ground_truth,
            decoder_utils=decoder,
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
    if len(records) != 14:
        raise LanguageScoringV2Error("language scoring denominator drift")
    by_category: dict[str, Any] = {}
    for category in v1.CATEGORIES:
        items = [row for row in records if row["category"] == category]
        by_category[category] = {
            "case_count": len(items),
            "official_checker_valid_count": sum(
                row["official_checker_valid"] for row in items
            ),
            "official_checker_accuracy": round(
                sum(row["official_checker_valid"] for row in items) / len(items),
                6,
            ),
            "tool_selection_accuracy": round(
                sum(row["tool_selection_correct"] for row in items) / len(items),
                6,
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
        "schema": "milai.dg10.bfcl-language-dev-scoring.v2",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "BFCL_LANGUAGE_DEV_SCORING_V2_COMPLETE",
        "quality_outcome": "CHARACTERIZED_ONLY_THRESHOLDS_NOT_FROZEN",
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count_opened": 14,
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "local_vllm_requests": 0,
        "inputs": {
            "scoring_contract_sha256": dev_smoke._sha256_file(contract_path),
            "generation_report_sha256": dev_smoke._sha256_file(
                generation_report_path
            ),
            "raw_generation_sha256": dev_smoke._sha256_file(raw_generation_path),
            "scoring_runner_sha256": dev_smoke._sha256_file(Path(__file__).resolve()),
            "bfcl_git_head": bfcl_contract._git_head(bfcl_root),
        },
        "records": records,
        "aggregates": {
            "case_count": 14,
            "official_checker_valid_count": valid_count,
            "official_checker_accuracy": round(valid_count / 14, 6),
            "tool_selection_accuracy": round(
                sum(row["tool_selection_correct"] for row in records) / 14, 6
            ),
            "decoder_failure_count": sum(
                not row["decoder_success"] for row in records
            ),
            "official_checker_invocations": sum(
                row["official_checker_invocations"] for row in records
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
            "Candidate.1 scoring failed before labels because an optional provider SDK was absent; candidate.2 isolates only that import chain.",
            "No model/provider request occurs during scoring; test remains closed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze or run BFCL Java/JavaScript scoring candidate.2"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze-scoring-contract", action="store_true")
    action.add_argument("--score-sealed-generation", action="store_true")
    parser.add_argument("--execution-ack")
    parser.add_argument("--generation-contract", type=Path, default=v1.CONTRACT_OUTPUT)
    parser.add_argument("--generation-report", type=Path, default=v1.GENERATION_OUTPUT)
    parser.add_argument("--raw-generation", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=CONTRACT_OUTPUT)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.bfcl_root.resolve()
    if args.freeze_scoring_contract:
        if args.execution_ack != FREEZE_ACK:
            raise LanguageScoringV2Error("freeze requires exact acknowledgement")
        report = build_contract(
            generation_contract_path=args.generation_contract.resolve(),
            generation_report_path=args.generation_report.resolve(),
            raw_generation_path=args.raw_generation.resolve(),
            bfcl_root=root,
        )
        output = (args.output or CONTRACT_OUTPUT).resolve()
    else:
        if args.execution_ack != SCORE_ACK:
            raise LanguageScoringV2Error("score requires exact acknowledgement")
        report = run_scoring(
            contract_path=args.contract.resolve(),
            generation_report_path=args.generation_report.resolve(),
            raw_generation_path=args.raw_generation.resolve(),
            bfcl_root=root,
        )
        output = (args.output or SCORING_OUTPUT).resolve()
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(output, raw)
    print(
        json.dumps(
            {
                "output": str(output),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": report["status"],
                "labels_opened": report["bfcl_dev_answer_labels_opened"],
                "test_access_authorized": False,
                "provider_requests": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
