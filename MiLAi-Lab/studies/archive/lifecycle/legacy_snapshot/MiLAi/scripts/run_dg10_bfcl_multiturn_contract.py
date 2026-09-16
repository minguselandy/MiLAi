from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import inspect
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_bfcl_multiturn_safety as safety
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract

DATE = "2026-08-21"
CANDIDATE = "candidate.12"
MULTI_TURN_CATEGORIES = (
    "multi_turn_base",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
    "multi_turn_long_context",
)
EXPECTED_SELECTED_CLASS_TO_DOC = {
    "GorillaFileSystem": "gorilla_file_system.json",
    "MathAPI": "math_api.json",
    "MessageAPI": "message_api.json",
    "TwitterAPI": "posting_api.json",
    "TicketAPI": "ticket_api.json",
    "TradingBot": "trading_bot.json",
    "TravelAPI": "travel_booking.json",
    "VehicleControlAPI": "vehicle_control.json",
}
EXPECTED_SELECTED_CLASS_TO_SOURCE = {
    "GorillaFileSystem": "gorilla_file_system.py",
    "MathAPI": "math_api.py",
    "MessageAPI": "message_api.py",
    "TwitterAPI": "posting_api.py",
    "TicketAPI": "ticket_api.py",
    "TradingBot": "trading_bot.py",
    "TravelAPI": "travel_booking.py",
    "VehicleControlAPI": "vehicle_control.py",
}
SAFETY_PROMPT_SUFFIX = (
    "\n\nDG-10 adapted safety contract: Return only one explicit Python list. "
    "Each element must be a bare available function call using keyword arguments "
    "and literal values. Return exactly [] when no function call remains. Never "
    "return prose, markdown fences, a bare call, positional arguments, expressions, "
    "or nested function calls."
)
STRICT_SYNTHETIC_FIXTURES_SHA256 = (
    "7ec8001f37219ddc52da3f2017ccaa92366759b82ed82a1f8259762c9f6b7173"
)
STRICT_SYNTHETIC_CONTRACT_SHA256 = (
    "ce9f86580a8b5aaa540195bfb1e7b59079909d3c6aa0018bf9eebf3f2b71cef3"
)
DEFAULT_PLAN = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-{DATE}.json"
)
DEFAULT_ADVISORY_RECEIPT = (
    ROOT
    / "docs/reviews/"
    f"DG-10-bfcl-multiturn-sol-advisory-receipt-candidate.1-{DATE}.json"
)
DEFAULT_OFFLINE_PROBE = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-safety-probe-candidate.1-{DATE}.json"
)
DEFAULT_LOCAL_MODEL_PROBE = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-local-probe-candidate.1-{DATE}.json"
)
DEFAULT_FAILED_PREFIX_DIAGNOSTIC = (
    ROOT
    / "docs/reports/"
    f"DG-10-bfcl-multiturn-generation-prefix-diagnostic-candidate.1-{DATE}.json"
)
DEFAULT_SECOND_FAILED_PREFIX_DIAGNOSTIC = (
    ROOT
    / "docs/reports/"
    f"DG-10-bfcl-multiturn-generation-prefix-diagnostic-candidate.2-{DATE}.json"
)
DEFAULT_PARTIAL_CANDIDATE_11 = (
    ROOT
    / "docs/reports/"
    f"DG-10-bfcl-multiturn-generation-partial-candidate.11-{DATE}.json"
)
DEFAULT_BFCL_ROOT = bfcl_contract.DEFAULT_BFCL_ROOT
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-safety-contract-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-multiturn-generation-contract"
)


class MultiTurnContractError(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MultiTurnContractError(f"invalid JSON file: {path}") from exc


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MultiTurnContractError(f"{label} must be an object")
    return value


def _relative_descriptor(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": dev_smoke._sha256_file(path),
        "size": path.stat().st_size,
    }


def _load_plan(path: Path, bfcl_root: Path) -> dict[str, Any]:
    plan = _object(_load_json(path), "candidate.5 plan")
    if (
        plan.get("schema") != "milai.dg10.bfcl-v4-local-calibration-plan.v1"
        or plan.get("candidate") != "candidate.5"
        or plan.get("status")
        != "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
        or plan.get("test_access_authorized") is not False
        or plan.get("quality_thresholds_frozen") is not False
        or plan.get("test_labels_or_outputs_opened_by_this_report") is not False
        or plan.get("synthetic_capability_probe", {}).get("status") != "PASS_BOUND"
        or plan.get("lane_contract", {}).get("protocol_label")
        != "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD"
    ):
        raise MultiTurnContractError("candidate.5 plan boundary mismatch")
    if bfcl_contract._git_head(bfcl_root) != plan.get("inputs", {}).get(
        "bfcl_git_head"
    ):
        raise MultiTurnContractError("BFCL git HEAD differs from candidate.5")
    return plan


def _load_advisory_receipt(path: Path) -> dict[str, Any]:
    receipt = _object(_load_json(path), "Sol advisory receipt")
    if (
        receipt.get("schema")
        != "milai.dg10.bfcl-multiturn-sol-development-advisory-receipt.v1"
        or receipt.get("classification", {}).get("development_advisory_only")
        is not True
        or receipt.get("classification", {}).get("formal_crg_review") is not False
        or receipt.get("advisory_result", {}).get("verdict")
        != "PROCEED_WITH_REQUIRED_CHANGES"
        or receipt.get("advisory_result", {}).get("risk") != "CRITICAL"
        or receipt.get("gate_effect", {}).get("prior_raw_ast_only_design")
        != "REJECTED"
        or receipt.get("gate_effect", {}).get(
            "bfcl_multiturn_dev_labels_may_be_opened_now"
        )
        is not False
    ):
        raise MultiTurnContractError("Sol advisory receipt boundary mismatch")
    return receipt


def _load_offline_probe(path: Path) -> dict[str, Any]:
    report = _object(_load_json(path), "offline safety probe")
    aggregates = report.get("aggregates", {})
    if (
        report.get("schema") != "milai.dg10.bfcl-multiturn-safety-probe.v1"
        or report.get("candidate") != "candidate.1"
        or report.get("status") != "OFFLINE_AST_AND_SCRIPTED_STATE_MACHINE_PASS"
        or report.get("provider_requests") != 0
        or report.get("local_vllm_requests") != 0
        or report.get("benchmark_material_opened_by_probe") is not False
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or aggregates.get("offline_corpus_count") != 36
        or aggregates.get("offline_corpus_passed") != 36
        or aggregates.get("scripted_state_machine_count") != 6
        or aggregates.get("scripted_state_machine_passed") != 6
        or report.get("gate_results", {}).get("offline_ast_corpus") != "PASS"
        or report.get("gate_results", {}).get("scripted_state_machine") != "PASS"
    ):
        raise MultiTurnContractError("offline safety probe boundary mismatch")
    return report


def _load_local_model_probe(path: Path) -> dict[str, Any]:
    report = _object(_load_json(path), "strict local-model probe")
    aggregates = report.get("aggregates", {})
    if (
        report.get("schema") != "milai.dg10.bfcl-multiturn-local-probe.v1"
        or report.get("candidate") != "candidate.1"
        or report.get("status") != "STRICT_SYNTHETIC_LOCAL_VLLM_PROBE_PASS"
        or report.get("provider_requests") != 0
        or report.get("local_vllm_requests") != 8
        or report.get("local_tokenizer_requests") != 8
        or report.get("retry_model_calls") != 0
        or report.get("hidden_or_extra_model_calls") != 0
        or report.get("benchmark_material_opened_by_probe") is not False
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or aggregates.get("dialogues_planned") != 4
        or aggregates.get("dialogues_passed") != 4
        or aggregates.get("model_rounds_planned") != 8
        or aggregates.get("model_rounds_executed") != 8
        or aggregates.get("safety_failure_dialogues") != 0
        or report.get("gate_results", {}).get("revised_synthetic_local_vllm")
        != "PASS"
        or report.get("repo_external_sidecar", {}).get("status")
        != "WRITTEN_HASH_BOUND"
    ):
        raise MultiTurnContractError("strict local-model probe boundary mismatch")
    return report


def _load_failed_prefix_diagnostic(path: Path) -> dict[str, Any]:
    report = _object(_load_json(path), "failed prefix diagnostic")
    attempt = report.get("failed_attempt", {})
    if (
        report.get("schema")
        != "milai.dg10.bfcl-multiturn-generation-prefix-diagnostic.v1"
        or report.get("candidate") != "candidate.1"
        or report.get("status")
        != "PREFIX_FAILURE_DIAGNOSED_NEW_CANDIDATE_REQUIRED"
        or report.get("diagnostic_local_model_requests") != 0
        or report.get("diagnostic_local_tokenizer_requests") != 2
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or attempt.get("case_count") != 4
        or attempt.get("recovered_external_journal_validated_native_model_requests")
        != 62
        or attempt.get("retry_model_calls") != 0
        or attempt.get("eligible_to_resume_remaining_76") is not False
        or report.get("gate_results", {}).get("operational_prefix")
        != "FAIL_NEW_CANDIDATE_REQUIRED"
    ):
        raise MultiTurnContractError("failed prefix diagnostic boundary mismatch")
    return report


def _load_second_failed_prefix_diagnostic(path: Path) -> dict[str, Any]:
    report = _object(_load_json(path), "second failed prefix diagnostic")
    attempt = report.get("failed_attempt", {})
    if (
        report.get("schema")
        != "milai.dg10.bfcl-multiturn-generation-prefix-diagnostic.v1"
        or report.get("candidate") != "candidate.2"
        or report.get("status")
        != "PREFIX_EVIDENCE_COMPLETE_EXCEPT_FROZEN_SCHEDULE_SERIALIZATION_BUG_NEW_CANDIDATE_REQUIRED"
        or report.get("diagnostic_local_model_requests") != 0
        or report.get("diagnostic_local_tokenizer_requests") != 0
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or attempt.get("case_count") != 4
        or attempt.get("local_model_requests") != 62
        or attempt.get("validated_native_receipts") != 62
        or attempt.get("local_tokenizer_requests") != 63
        or attempt.get("retry_model_calls") != 0
        or attempt.get("eligible_to_resume_remaining_76") is not False
    ):
        raise MultiTurnContractError(
            "second failed prefix diagnostic boundary mismatch"
        )
    return report


def _load_partial_candidate_11(path: Path) -> dict[str, Any]:
    report = _object(_load_json(path), "candidate.11 partial report")
    ledger = report.get("append_only_ledger_snapshot", {})
    dependency = report.get("dependency_remediation", {})
    cumulative = report.get("cross_attempt_accounting_through_candidate_11", {})
    if (
        report.get("schema")
        != "milai.dg10.bfcl-multiturn-generation-partial.v1"
        or report.get("candidate") != "candidate.11"
        or report.get("status")
        != "PARTIAL_STOPPED_AFTER_GENERIC_OFFICIAL_BACKEND_DEPENDENCY_FAILURE"
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or ledger.get("record_count") != 19
        or ledger.get("eligible_for_scoring") is not False
        or dependency.get("package") != "mpmath"
        or dependency.get("version") != "1.3.0"
        or dependency.get("installed_tree_sha256")
        != "376efeae63abdfd9378ce98ddb38509387ba0237c82e8e70429ddea11089079b"
        or cumulative.get("cumulative_local_model_requests") != 479
        or cumulative.get("cumulative_local_tokenizer_requests") != 485
        or report.get("required_next_action", {}).get("new_candidate") is not True
    ):
        raise MultiTurnContractError("candidate.11 partial boundary mismatch")
    return report


def _runtime_mpmath_closure() -> dict[str, Any]:
    try:
        module = importlib.import_module("mpmath")
    except Exception as exc:
        raise MultiTurnContractError("mpmath is absent from the worker environment") from exc
    if getattr(module, "__version__", None) != "1.3.0":
        raise MultiTurnContractError("mpmath version differs from official BFCL pin")
    package_root = Path(inspect.getfile(module)).resolve().parent
    files = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(package_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    freeze = subprocess.run(
        ["uv", "pip", "freeze", "--python", sys.executable],
        check=False,
        capture_output=True,
    )
    if freeze.returncode != 0:
        raise MultiTurnContractError("cannot freeze worker Python environment")
    freeze_sha256 = hashlib.sha256(freeze.stdout).hexdigest()
    if (
        len(files) != 87
        or digest.hexdigest()
        != "376efeae63abdfd9378ce98ddb38509387ba0237c82e8e70429ddea11089079b"
        or freeze_sha256
        != "e21b21a1df79293faa2dcf1bca352a82d44f5910767f22b5e34d0b847661ec39"
    ):
        raise MultiTurnContractError("worker dependency closure drifted")
    return {
        "package": "mpmath",
        "version": "1.3.0",
        "source": "OFFICIAL_BFCL_PYPROJECT_PIN_OFFLINE_UV_CACHE",
        "package_path_class": "REPOSITORY_RUNTIME_VENV",
        "tree_file_count": len(files),
        "tree_sha256": digest.hexdigest(),
        "worker_environment_freeze_sha256": freeze_sha256,
    }


def _selected_ids(plan: Mapping[str, Any]) -> dict[str, list[str]]:
    categories = _object(plan.get("split", {}).get("categories"), "categories")
    selected: dict[str, list[str]] = {}
    for category in MULTI_TURN_CATEGORIES:
        record = _object(categories.get(category), category)
        prefixed = record.get("dev_case_ids")
        if not isinstance(prefixed, list) or len(prefixed) != 20:
            raise MultiTurnContractError(f"{category} must contain exactly 20 dev IDs")
        ids = []
        for item in prefixed:
            prefix = "bfcl_v4:"
            if not isinstance(item, str) or not item.startswith(prefix):
                raise MultiTurnContractError(f"invalid selected ID in {category}")
            source_id = item[len(prefix) :]
            if not source_id.startswith(f"{category}_"):
                raise MultiTurnContractError(f"selected ID category mismatch: {item}")
            ids.append(source_id)
        if len(ids) != len(set(ids)):
            raise MultiTurnContractError(f"duplicate selected IDs in {category}")
        selected[category] = sorted(ids)
    flattened = [item for values in selected.values() for item in values]
    if len(flattened) != 80 or len(flattened) != len(set(flattened)):
        raise MultiTurnContractError("multi-turn development split must be exact 80")
    return selected


def _load_selected_generation_rows(
    root: Path,
    plan: Mapping[str, Any],
    selected: Mapping[str, list[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    categories = _object(plan.get("split", {}).get("categories"), "categories")
    rows: list[dict[str, Any]] = []
    descriptors: dict[str, Any] = {}
    for category in MULTI_TURN_CATEGORIES:
        path = root / "bfcl_eval/data" / f"BFCL_v4_{category}.json"
        category_record = _object(categories.get(category), category)
        digest = dev_smoke._sha256_file(path)
        if digest != category_record.get("source_file_sha256"):
            raise MultiTurnContractError(f"source bytes drifted for {category}")
        wanted = set(selected[category])
        found: set[str] = set()
        with path.open(encoding="utf-8") as stream:
            for raw in stream:
                prefix_match = bfcl_contract.ID_PREFIX.match(raw.encode("utf-8"))
                if prefix_match is None:
                    raise MultiTurnContractError(f"invalid BFCL row prefix: {path}")
                source_id = prefix_match.group(1).decode("ascii")
                if source_id not in wanted:
                    continue
                entry = _object(json.loads(raw), f"BFCL case {source_id}")
                if entry.get("id") != source_id:
                    raise MultiTurnContractError("BFCL source ID mismatch")
                if "function" in entry:
                    raise MultiTurnContractError("selected case is not pristine")
                rows.append(entry)
                found.add(source_id)
        if found != wanted:
            raise MultiTurnContractError(f"selected source coverage mismatch: {category}")
        descriptors[category] = _relative_descriptor(root, path)
    rows.sort(key=lambda item: item["id"])
    return rows, descriptors


def _load_official_population_api(root: Path) -> dict[str, Any]:
    root_string = str(root)
    inserted = root_string not in sys.path
    if inserted:
        sys.path.insert(0, root_string)
    try:
        utils = importlib.import_module("bfcl_eval.utils")
        prompts = importlib.import_module("bfcl_eval.constants.default_prompts")
        backend = importlib.import_module(
            "bfcl_eval.constants.executable_backend_config"
        )
    except Exception as exc:
        raise MultiTurnContractError("cannot import frozen BFCL population API") from exc
    finally:
        if inserted:
            sys.path.remove(root_string)
    if prompts.MAXIMUM_STEP_LIMIT != 20:
        raise MultiTurnContractError("official maximum step limit drifted")
    if dict(backend.MULTI_TURN_FUNC_DOC_FILE_MAPPING) != {
        **EXPECTED_SELECTED_CLASS_TO_DOC,
        "WebSearchAPI": "web_search.json",
        "MemoryAPI_kv": "memory_kv.json",
        "MemoryAPI_vector": "memory_vector.json",
        "MemoryAPI_rec_sum": "memory_rec_sum.json",
    }:
        raise MultiTurnContractError("official function-doc mapping drifted")
    return {
        "populate": utils.populate_test_cases_with_predefined_functions,
        "additional_prompt": (
            prompts.DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_PROMPTING
        ),
        "maximum_step_limit": prompts.MAXIMUM_STEP_LIMIT,
        "class_source_mapping": dict(backend.CLASS_FILE_PATH_MAPPING),
    }


def _freeze_upstream_closure(
    root: Path,
    involved_classes: set[str],
    class_source_mapping: Mapping[str, str],
) -> dict[str, Any]:
    if involved_classes != set(EXPECTED_SELECTED_CLASS_TO_DOC):
        raise MultiTurnContractError(
            f"unexpected selected function classes: {sorted(involved_classes)}"
        )
    function_docs: dict[str, Any] = {}
    function_sources: dict[str, Any] = {}
    for class_name in sorted(involved_classes):
        doc_path = (
            root
            / "bfcl_eval/data/multi_turn_func_doc"
            / EXPECTED_SELECTED_CLASS_TO_DOC[class_name]
        )
        source_path = (
            root
            / "bfcl_eval/eval_checker/multi_turn_eval/func_source_code"
            / EXPECTED_SELECTED_CLASS_TO_SOURCE[class_name]
        )
        expected_module = class_source_mapping.get(class_name)
        expected_suffix = EXPECTED_SELECTED_CLASS_TO_SOURCE[class_name][:-3]
        if expected_module != (
            "bfcl_eval.eval_checker.multi_turn_eval.func_source_code."
            + expected_suffix
        ):
            raise MultiTurnContractError(f"source mapping drifted for {class_name}")
        function_docs[class_name] = _relative_descriptor(root, doc_path)
        function_sources[class_name] = _relative_descriptor(root, source_path)
    long_context_path = (
        root
        / "bfcl_eval/eval_checker/multi_turn_eval/func_source_code/long_context.py"
    )
    function_sources["_shared_long_context"] = _relative_descriptor(
        root, long_context_path
    )
    core_paths = {
        "base_handler": root / "bfcl_eval/model_handler/base_handler.py",
        "base_oss_prompt_handler": (
            root / "bfcl_eval/model_handler/local_inference/base_oss_handler.py"
        ),
        "prompt_decoder_and_serializer": (
            root / "bfcl_eval/model_handler/utils.py"
        ),
        "default_prompts_and_step_limit": (
            root / "bfcl_eval/constants/default_prompts.py"
        ),
        "executable_backend_config": (
            root / "bfcl_eval/constants/executable_backend_config.py"
        ),
        "population_helper": root / "bfcl_eval/utils.py",
        "multi_turn_executor": (
            root
            / "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_utils.py"
        ),
        "multi_turn_checker_and_irrelevance_checker": (
            root
            / "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_checker.py"
        ),
    }
    return {
        "core": {
            name: _relative_descriptor(root, path)
            for name, path in sorted(core_paths.items())
        },
        "function_docs": function_docs,
        "function_sources": function_sources,
    }


def _forbidden_label_key(value: Any, path: str = "$") -> str | None:
    forbidden = {"answer", "answers", "ground_truth", "possible_answer", "label"}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in forbidden:
                return f"{path}.{key}"
            found = _forbidden_label_key(item, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _forbidden_label_key(item, f"{path}[{index}]")
            if found:
                return found
    return None


def build_contract(
    *,
    plan_path: Path = DEFAULT_PLAN,
    advisory_receipt_path: Path = DEFAULT_ADVISORY_RECEIPT,
    offline_probe_path: Path = DEFAULT_OFFLINE_PROBE,
    local_model_probe_path: Path = DEFAULT_LOCAL_MODEL_PROBE,
    failed_prefix_diagnostic_path: Path = DEFAULT_FAILED_PREFIX_DIAGNOSTIC,
    second_failed_prefix_diagnostic_path: Path = (
        DEFAULT_SECOND_FAILED_PREFIX_DIAGNOSTIC
    ),
    partial_candidate_11_path: Path = DEFAULT_PARTIAL_CANDIDATE_11,
    bfcl_root: Path = DEFAULT_BFCL_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = bfcl_root.resolve()
    plan = _load_plan(plan_path.resolve(), root)
    _load_advisory_receipt(advisory_receipt_path.resolve())
    offline_probe = _load_offline_probe(offline_probe_path.resolve())
    if offline_probe.get("inputs", {}).get("safety_contract_sha256") != (
        "7fd95c76532156837d2afdf46682e46d5db0565719218d0d6f928c2804b2e431"
    ):
        raise MultiTurnContractError("offline probe is not bound to candidate.7")
    local_model_probe = _load_local_model_probe(local_model_probe_path.resolve())
    if local_model_probe.get("inputs", {}).get("safety_contract_sha256") != (
        "5e0ce2b4e0a49704d1296bacc831b20473494317684ca88a06dfdba45e0fa792"
    ):
        raise MultiTurnContractError("local-model probe is not bound to candidate.8")
    _load_failed_prefix_diagnostic(failed_prefix_diagnostic_path.resolve())
    _load_second_failed_prefix_diagnostic(
        second_failed_prefix_diagnostic_path.resolve()
    )
    _load_partial_candidate_11(partial_candidate_11_path.resolve())
    runtime_dependency_closure = _runtime_mpmath_closure()
    selected = _selected_ids(plan)
    ordered_generation_ids = [
        f"bfcl_v4:{selected[category][index]}"
        for index in range(20)
        for category in MULTI_TURN_CATEGORIES
    ]
    pristine_rows, source_descriptors = _load_selected_generation_rows(
        root, plan, selected
    )
    official = _load_official_population_api(root)
    pristine_sha256 = dev_smoke._json_sha256(pristine_rows)
    population_input = copy.deepcopy(pristine_rows)
    populated_rows = official["populate"](population_input)
    if dev_smoke._json_sha256(pristine_rows) != pristine_sha256:
        raise MultiTurnContractError("pristine selected rows were mutated")
    if populated_rows is not population_input or len(populated_rows) != 80:
        raise MultiTurnContractError("official population helper boundary mismatch")
    schedules: dict[str, Any] = {}
    involved_classes: set[str] = set()
    for entry in populated_rows:
        involved = entry.get("involved_classes")
        if not isinstance(involved, list) or any(
            not isinstance(item, str) for item in involved
        ):
            raise MultiTurnContractError("invalid involved_classes")
        involved_classes.update(involved)
        try:
            schedules[entry["id"]] = safety.build_case_turn_schedule(
                entry, official["additional_prompt"]
            )
        except safety.SafetyGateError as exc:
            raise MultiTurnContractError(str(exc)) from exc
    upstream_closure = _freeze_upstream_closure(
        root, involved_classes, official["class_source_mapping"]
    )
    category_counts = Counter(item["id"].rsplit("_", 1)[0] for item in populated_rows)
    turn_counts = Counter(len(item["question"]) for item in populated_rows)
    bundle = {
        "schema": "milai.dg10.bfcl-multiturn-label-free-generation-bundle.v1",
        "candidate": CANDIDATE,
        "date": DATE,
        "data_classification": (
            "PUBLIC_BFCL_DEV_GENERATION_INPUTS_NO_POSSIBLE_ANSWER_OR_GROUND_TRUTH"
        ),
        "test_material_present": False,
        "development_answer_labels_present": False,
        "selected_case_count": 80,
        "selected_case_ids": [f"bfcl_v4:{item['id']}" for item in populated_rows],
        "population": {
            "pristine_deep_copy": True,
            "official_population_helper_invocation_count": 1,
            "pristine_rows_sha256": pristine_sha256,
            "populated_rows_sha256": dev_smoke._json_sha256(populated_rows),
        },
        "safety_prompt_suffix": SAFETY_PROMPT_SUFFIX,
        "records": [
            {
                "case_id": f"bfcl_v4:{entry['id']}",
                "test_entry": entry,
                "turn_schedule": schedules[entry["id"]],
            }
            for entry in populated_rows
        ],
    }
    forbidden_path = _forbidden_label_key(bundle)
    if forbidden_path is not None:
        raise MultiTurnContractError(
            f"label-like key entered generation bundle: {forbidden_path}"
        )
    selected_ids = [item["id"] for item in populated_rows]
    report = {
        "schema": "milai.dg10.bfcl-multiturn-safety-contract.v1",
        "candidate": CANDIDATE,
        "date": DATE,
        "status": "DEPENDENCY_REMEDIATION_FROZEN_FULL_RERUN_NOT_RUN",
        "quality_outcome": "CHARACTERIZED_ONLY_NOT_RUN",
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "bfcl_dev_generation_inputs_opened": True,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "inputs": {
            "candidate_5_plan_sha256": dev_smoke._sha256_file(plan_path.resolve()),
            "sol_development_advisory_receipt_sha256": dev_smoke._sha256_file(
                advisory_receipt_path.resolve()
            ),
            "offline_safety_probe_sha256": dev_smoke._sha256_file(
                offline_probe_path.resolve()
            ),
            "strict_local_model_probe_sha256": dev_smoke._sha256_file(
                local_model_probe_path.resolve()
            ),
            "failed_prefix_diagnostic_sha256": dev_smoke._sha256_file(
                failed_prefix_diagnostic_path.resolve()
            ),
            "second_failed_prefix_diagnostic_sha256": dev_smoke._sha256_file(
                second_failed_prefix_diagnostic_path.resolve()
            ),
            "candidate_11_partial_report_sha256": dev_smoke._sha256_file(
                partial_candidate_11_path.resolve()
            ),
            "bfcl_git_head": bfcl_contract._git_head(root),
            "source_files": source_descriptors,
        },
        "selection": {
            "case_count": 80,
            "case_ids": [f"bfcl_v4:{item}" for item in selected_ids],
            "case_ids_sha256": dev_smoke._json_sha256(selected_ids),
            "category_counts": dict(sorted(category_counts.items())),
            "turn_count_distribution": {
                str(key): value for key, value in sorted(turn_counts.items())
            },
            "exactly_candidate_5_multi_turn_dev_cases": True,
        },
        "official_upstream_byte_closure": upstream_closure,
        "worker_runtime_dependency_closure": runtime_dependency_closure,
        "local_harness_byte_closure": {
            "safety_gate": _relative_descriptor(
                ROOT, ROOT / "scripts/dg10_bfcl_multiturn_safety.py"
            ),
            "contract_builder": _relative_descriptor(ROOT, Path(__file__).resolve()),
            "offline_scripted_probe": _relative_descriptor(
                ROOT, ROOT / "scripts/run_dg10_bfcl_multiturn_safety_probe.py"
            ),
            "revised_local_model_probe": _relative_descriptor(
                ROOT, ROOT / "scripts/run_dg10_bfcl_multiturn_local_probe.py"
            ),
            "generation_worker": _relative_descriptor(
                ROOT,
                ROOT / "scripts/run_dg10_bfcl_multiturn_generation_worker.py",
            ),
            "generation_orchestrator": _relative_descriptor(
                ROOT, ROOT / "scripts/run_dg10_bfcl_multiturn_generation.py"
            ),
        },
        "strict_synthetic_local_probe_contract": {
            "fixture_version": "dg10-bfcl-multiturn-strict-synthetic-v1",
            "dialogue_count": 4,
            "total_model_rounds": 8,
            "retry_model_calls_max": 0,
            "hidden_or_extra_model_calls_max": 0,
            "benchmark_material": False,
            "strict_explicit_empty_list_required": True,
            "fixtures_sha256": STRICT_SYNTHETIC_FIXTURES_SHA256,
            "contract_sha256": STRICT_SYNTHETIC_CONTRACT_SHA256,
            "status": "PASS_BOUND",
            "report_sha256": dev_smoke._sha256_file(
                local_model_probe_path.resolve()
            ),
        },
        "generation_execution_schedule": {
            "selection": (
                "DETERMINISTIC_CATEGORY_ROUND_ROBIN_USING_FROZEN_SORTED_DEV_IDS"
            ),
            "ordered_case_count": len(ordered_generation_ids),
            "ordered_case_ids": ordered_generation_ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(
                ordered_generation_ids
            ),
            "operational_prefix_case_count": 4,
            "operational_prefix_case_ids": ordered_generation_ids[:4],
            "operational_prefix_exactly_one_per_category": True,
            "remaining_case_count": 76,
            "fresh_generation_process_per_case": True,
            "worker_process_retries_max": 0,
            "native_model_call_retries_max": 0,
            "native_step_journal_fsync_before_next_request": True,
            "case_ledger_fsync_before_next_case": True,
            "labels_available_to_generation_process": False,
            "candidate_12_rerun_uses_new_bundle_run_directory_and_ledger": True,
            "cross_attempt_repeated_case_count": 20,
            "prior_attempt_completed_ledger_case_count": 19,
            "prior_attempt_interrupted_case_count": 1,
            "prior_attempt_count": 3,
            "prior_attempt_local_model_requests": 479,
            "prior_attempt_local_tokenizer_requests": 483,
            "diagnostic_local_tokenizer_requests": 2,
            "prior_and_diagnostic_local_model_requests_cumulative": 479,
            "prior_and_diagnostic_local_tokenizer_requests_cumulative": 485,
        },
        "population_contract": {
            "input": "PRISTINE_DEEP_COPY_OF_EXACT_80_SELECTED_SOURCE_CASES",
            "official_helper_invocation_count": 1,
            "mutation_scope": "POPULATION_INPUT_COPY_ONLY",
            "missed_function_docs_removed_then_REVEALED_AT_EXACT_DECLARED_TURN": True,
            "function_exposure": "CUMULATIVE_MONOTONIC_NO_DUPLICATES",
            "additional_function_prompt_sha256": dev_smoke._json_sha256(
                official["additional_prompt"]
            ),
        },
        "dual_ast_gate_contract": {
            "raw_response_gate": "EXPLICIT_TOP_LEVEL_LIST_ONLY",
            "post_official_decoder_execution_string_gate": "REQUIRED",
            "canonical_typed_equivalence": "EXACT_CALL_ORDER_NAME_KEYWORD_AND_LITERAL_TYPE",
            "bare_exposed_function_names_only": True,
            "keyword_arguments_only": True,
            "recursive_bounded_literals_only": True,
            "exact_unary_minus_int_float_only": True,
            "explicit_empty_list_is_only_no_call_representation": True,
            "limits": safety.SAFETY_LIMITS,
            "safety_prompt_suffix": SAFETY_PROMPT_SUFFIX,
            "safety_prompt_suffix_sha256": dev_smoke._json_sha256(
                SAFETY_PROMPT_SUFFIX
            ),
        },
        "state_machine_contract": {
            "maximum_successful_execution_steps_per_turn": official[
                "maximum_step_limit"
            ],
            "boundary_native_response": (
                "PRESERVE_AS_N_PLUS_1_FORCE_QUIT_FAILURE_NEVER_EXECUTE"
            ),
            "gate_or_decode_failure": (
                "PRESERVE_NATIVE_STEP_EXECUTE_NOTHING_EMIT_NO_TOOL_RESULT_"
                "END_TURN_LATCH_CASE_FAILURE"
            ),
            "executor_failure": (
                "EMIT_NO_TOOL_RESULT_END_TURN_LATCH_CASE_FAILURE_FRESH_PROCESS_DISCARD"
            ),
            "case_process_isolation": "ONE_FRESH_GENERATION_PROCESS_PER_CASE",
            "scoring_process_isolation": "SEPARATE_FRESH_PROCESS_PER_CASE",
            "append_native_receipt_before_next_request": True,
        },
        "failure_taxonomy": [
            "RAW_GATE_FAILURE",
            "OFFICIAL_DECODER_FAILURE",
            "DECODED_EXECUTION_GATE_FAILURE",
            "RAW_DECODED_CANONICAL_MISMATCH",
            "STEP_LIMIT_BOUNDARY_FORCE_QUIT",
            "EXECUTOR_EXCEPTION",
            "EXECUTOR_RESULT_SHAPE_FAILURE",
            "GENERATION_PROCESS_FAILURE",
            "SCORING_PROCESS_FAILURE",
            "OFFICIAL_MULTI_TURN_CHECKER_FAILURE",
            "OFFICIAL_MULTI_TURN_IRRELEVANCE_CHECKER_FAILURE",
        ],
        "sealed_ledger_contract": {
            "generation_bundle_is_label_free": True,
            "generation_bundle_exact_case_count": 80,
            "append_case_record_before_next_case": True,
            "development_answers_load_after_generation_ledger_sealed": True,
            "test_answers_load": "PROHIBITED",
            "raw_capture": "REPO_EXTERNAL_EXCLUSIVE_CREATE_MODE_0600",
            "encryption_at_rest": "REVIEW_REQUIRED_NOT_SILENTLY_INVENTED",
        },
        "scoring_and_denominator_contract": {
            "denominator": "ALL_80_PREDECLARED_MULTI_TURN_DEV_CASES",
            "case_pass_requires": [
                "NO_HARNESS_FAILURE_LATCH",
                "UNCHANGED_OFFICIAL_MULTI_TURN_CHECKER_VALID_TRUE",
                "UNCHANGED_OFFICIAL_MULTI_TURN_IRRELEVANCE_CHECKER_VALID_TRUE",
            ],
            "decoder_failure_as_correct_no_call": "PROHIBITED",
            "force_quit_as_correct_no_call": "PROHIBITED",
            "primary_metric": "multi_turn_recovery_accuracy=passing_cases/80",
            "invalid_tool_call_case_rate": "latched_safety_failure_cases/80",
            "native_step_invalid_rate": (
                "latched_safety_failure_native_steps/all_native_model_steps"
            ),
            "numeric_acceptance_threshold": (
                "PENDING_COMPLETE_DEV_CALIBRATION_NO_TEST_AUTHORIZATION"
            ),
        },
        "supersession": {
            "candidate_11_generation_contract": (
                "SUPERSEDED_AFTER_PARTIAL_RUN_FOUND_MISSING_OFFICIAL_MATH_BACKEND_DEPENDENCY"
            ),
            "candidate_11_report_sha256": (
                "ed4b25e28d76cd81c912f8808c41e6af473c6c1c19fa22afd92f2aff8be73bd7"
            ),
            "candidate_11_partial_report_sha256": (
                "11291b806622e46b49c5b90548b485277190f4195dc7fd774a2bbae7abc7884b"
            ),
            "candidate_11_partial_eligible_for_scoring": False,
            "candidate_10_generation_contract": (
                "SUPERSEDED_AFTER_DYNAMIC_REVEAL_SERIALIZATION_ORDER_FAILURE"
            ),
            "candidate_10_report_sha256": (
                "3c66d5f521a307538000a4b988052769bf144822f80c326f143bac54b731c55e"
            ),
            "candidate_10_failed_prefix_report_sha256": (
                "47d0e9441cd4281762794048e865c76b0b84035303448c3a4dabe55efdce733b"
            ),
            "candidate_10_failed_prefix_eligible_for_scoring": False,
            "candidate_9_generation_contract": (
                "SUPERSEDED_AFTER_FAILED_OPERATIONAL_PREFIX_AND_DIAGNOSTIC"
            ),
            "candidate_9_report_sha256": (
                "27741cf2d53b7e77def96d294beb15ed82aa08580a1c68a87b61fffb90263b87"
            ),
            "candidate_9_failed_prefix_report_sha256": (
                "de6b83b3b93bc647b5588a8c8331f853ee832663c9420abeb25b49778fa1c1cd"
            ),
            "candidate_9_failed_prefix_eligible_for_scoring": False,
            "candidate_8_local_probe_contract": (
                "SUPERSEDED_BY_STRICT_LOCAL_PROBE_PASS_BOUND_GENERATION_CONTRACT"
            ),
            "candidate_8_report_sha256": (
                "5e0ce2b4e0a49704d1296bacc831b20473494317684ca88a06dfdba45e0fa792"
            ),
            "candidate_7_static_contract": (
                "SUPERSEDED_BY_OFFLINE_PASS_BOUND_LOCAL_MODEL_PROBE_CONTRACT"
            ),
            "candidate_7_report_sha256": (
                "7fd95c76532156837d2afdf46682e46d5db0565719218d0d6f928c2804b2e431"
            ),
            "candidate_6_static_contract": (
                "SUPERSEDED_AFTER_PRE_PROBE_LAUNCHER_IMPORT_FAILURE_NO_CORPUS_OR_MODEL_RUN"
            ),
            "candidate_6_report_sha256": (
                "3b4fe5f3821b31acc4b320b970eedf36d592a1397deda72596ca85e58c6f57c1"
            ),
            "candidate_5_multi_turn_raw_only_boundary": "REJECTED",
            "candidate_5_synthetic_PASS_BOUND": (
                "INVALIDATED_FOR_MULTI_TURN_PENDING_REVISED_LOCAL_MODEL_PROBE"
            ),
            "single_turn_122_case_calibration": "UNAFFECTED_SEPARATE_LANE",
        },
        "repo_external_generation_bundle": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": dev_smoke._sha256_bytes(dev_smoke._encoded_json(bundle)),
            "size": len(dev_smoke._encoded_json(bundle)),
        },
        "gate_results": {
            "static_no_label_closure": "PASS",
            "offline_ast_corpus": "PASS_BOUND",
            "scripted_state_machine": "PASS_BOUND",
            "revised_synthetic_local_vllm": "PASS_BOUND",
            "operational_prefix": "FAILED_PRIOR_CANDIDATE_RERUN_NOT_RUN",
            "label_free_generation_ledger": "NOT_RUN",
            "BMG-03": "NO_GO_MULTI_TURN_DEV_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This static contract opens only the 80 predeclared public generation inputs and no answer labels.",
            "It makes no native function-calling, official leaderboard, MCP transport, memory-arm, quality, or formal CRG claim.",
            "The revised strict-empty-list local-model probe passed, but this contract alone is not generation or scoring evidence.",
            "Candidates 9 through 11 remain immutable and excluded; candidate.12 must use a new bundle, run directory, and ledger while reporting all cross-attempt calls.",
            "Repo-external bundle encryption remains a review item; mode 0600 and exclusive creation are the current implemented control.",
        ],
    }
    return report, bundle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze the BFCL multi-turn no-label safety contract"
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--advisory-receipt", type=Path, default=DEFAULT_ADVISORY_RECEIPT
    )
    parser.add_argument(
        "--offline-probe", type=Path, default=DEFAULT_OFFLINE_PROBE
    )
    parser.add_argument(
        "--local-model-probe", type=Path, default=DEFAULT_LOCAL_MODEL_PROBE
    )
    parser.add_argument(
        "--failed-prefix-diagnostic",
        type=Path,
        default=DEFAULT_FAILED_PREFIX_DIAGNOSTIC,
    )
    parser.add_argument(
        "--second-failed-prefix-diagnostic",
        type=Path,
        default=DEFAULT_SECOND_FAILED_PREFIX_DIAGNOSTIC,
    )
    parser.add_argument(
        "--partial-candidate-11",
        type=Path,
        default=DEFAULT_PARTIAL_CANDIDATE_11,
    )
    parser.add_argument("--bfcl-root", type=Path, default=DEFAULT_BFCL_ROOT)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report, bundle = build_contract(
        plan_path=args.plan,
        advisory_receipt_path=args.advisory_receipt,
        offline_probe_path=args.offline_probe,
        local_model_probe_path=args.local_model_probe,
        failed_prefix_diagnostic_path=args.failed_prefix_diagnostic,
        second_failed_prefix_diagnostic_path=(
            args.second_failed_prefix_diagnostic
        ),
        partial_candidate_11_path=args.partial_candidate_11,
        bfcl_root=args.bfcl_root,
    )
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
    except dev_smoke.DevSmokeError as exc:
        raise MultiTurnContractError(str(exc)) from exc
    bundle_raw = dev_smoke._encoded_json(bundle)
    bundle_path = capture_directory / (
        f"dg10-bfcl-multiturn-label-free-{DATE}-{uuid4().hex[:12]}.raw.json"
    )
    dev_smoke._write_new(bundle_path, bundle_raw)
    report["repo_external_generation_bundle"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": dev_smoke._sha256_bytes(bundle_raw),
        "size": len(bundle_raw),
        "mode": "0600",
    }
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(report_raw),
                "generation_bundle": str(bundle_path),
                "generation_bundle_sha256": dev_smoke._sha256_bytes(bundle_raw),
                "selected_case_count": report["selection"]["case_count"],
                "status": report["status"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
