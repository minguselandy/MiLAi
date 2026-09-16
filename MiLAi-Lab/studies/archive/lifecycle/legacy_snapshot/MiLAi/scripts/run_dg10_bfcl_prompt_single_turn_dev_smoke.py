from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_prompt_capability_probe as prompt_probe
from scripts import run_dg10_bfcl_single_turn_dev_smoke as native_smoke

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
MODEL_ID = dev_smoke.MODEL_ID
DEFAULT_DATASET_LOCK = bfcl_contract.DEFAULT_DATASET_LOCK
DEFAULT_PLAN = bfcl_contract.DEFAULT_OUTPUT
DEFAULT_BFCL_ROOT = bfcl_contract.DEFAULT_BFCL_ROOT
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-prompt-single-turn-dev-smoke-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-prompt-single-turn-dev-smoke"
)


class PromptDevSmokeError(RuntimeError):
    pass


def _adapted_messages(
    prompt_utils: Any,
    case: native_smoke.BfclCase,
) -> list[dict[str, Any]]:
    system_prompt = prompt_utils.formulate_system_prompt(
        prompt_utils.DEFAULT_SYSTEM_PROMPT_FORMAT, list(case.functions)
    )
    messages = [copy.deepcopy(dict(message)) for message in case.messages]
    if messages and messages[0].get("role") == "system":
        content = messages[0].get("content")
        if not isinstance(content, str):
            raise PromptDevSmokeError("BFCL source system message is invalid")
        messages[0]["content"] = system_prompt + "\n\n" + content
    else:
        messages.insert(0, {"role": "system", "content": system_prompt})
    return messages


def _score_decoded(
    case: native_smoke.BfclCase,
    decoded: Sequence[Mapping[str, Any]],
    checker: Any,
) -> dict[str, Any]:
    encoded_responses: list[dict[str, str]] = []
    for item in decoded:
        if len(item) != 1:
            raise PromptDevSmokeError("decoded BFCL call must contain one function")
        name, arguments = next(iter(item.items()))
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise PromptDevSmokeError("decoded BFCL call fields are invalid")
        encoded_responses.append(
            {name: json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))}
        )
    return native_smoke._score(
        case,
        encoded_responses,
        checker,
        normalize_dots=False,
    )


def run_smoke(
    *,
    dataset_lock_path: Path,
    plan_path: Path,
    bfcl_root: Path,
    case_id: str,
    client: prompt_probe.PromptClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    case, plan, input_evidence = native_smoke._load_case(
        dataset_lock_path=dataset_lock_path.resolve(),
        plan_path=plan_path.resolve(),
        bfcl_root=bfcl_root.resolve(),
        case_id=case_id,
        expected_plan_candidate=bfcl_contract.CANDIDATE,
    )
    if (
        plan.get("lane_contract", {}).get("protocol_label")
        != "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD"
        or plan.get("synthetic_capability_probe", {}).get("status") != "PASS_BOUND"
        or plan.get("generation_contract", {}).get("native_tools_field_present")
        is not False
        or plan.get("generation_contract", {}).get("tool_choice_field_present")
        is not False
    ):
        raise PromptDevSmokeError("adapted BFCL prompt plan is not executable")
    prompt_utils, prompt_utils_sha256 = prompt_probe._load_official_prompt_utils(
        bfcl_root.resolve()
    )
    if prompt_utils_sha256 != input_evidence["tool_conversion_source_sha256"]:
        raise PromptDevSmokeError("BFCL prompt utility source differs from plan")
    checker, checker_sha256 = native_smoke._load_python_ast_checker(
        bfcl_root.resolve(), underscore_to_dot=False
    )
    if checker_sha256 != input_evidence["official_ast_checker_sha256"]:
        raise PromptDevSmokeError("BFCL AST checker source differs from plan")
    messages = _adapted_messages(prompt_utils, case)
    run_id = f"dg10-bfcl-prompt-dev-smoke-{DATE}-{uuid4().hex[:12]}"
    completion = client.complete(
        messages,
        request_key=f"{run_id}:{case.case_id}",
    )
    decoded, decoder_success, decoder_error_type = prompt_probe._decode(
        prompt_utils, completion.text
    )
    score = _score_decoded(case, decoded, checker)
    ended = datetime.now(UTC)
    report = {
        "schema": "milai.dg10.bfcl-prompt-single-turn-dev-smoke.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "BFCL_ADAPTED_PROMPT_SINGLE_TURN_DEV_SMOKE_COMPLETE_NOT_CALIBRATION",
        "quality_outcome": "CHARACTERIZED_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "PUBLIC_DEV_LABEL_OPENED_RAW_CONTENT_REPO_EXTERNAL_HASHED_ONLY",
        "bfcl_dev_labels_opened": True,
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": 1,
        "local_tokenizer_requests": client.tokenizer_requests,
        "unique_native_request_ids": 1,
        "hidden_or_extra_model_calls": 0,
        "retry_model_calls": 0,
        "model_id": MODEL_ID,
        "identity": dict(client.identity_evidence),
        "inputs": {
            **input_evidence,
            "adapted_plan_sha256": dev_smoke._sha256_file(plan_path.resolve()),
            "synthetic_capability_probe_report_sha256": plan["inputs"][
                "synthetic_capability_probe_report_sha256"
            ],
            "official_prompt_utils_loaded_sha256": prompt_utils_sha256,
            "official_ast_checker_loaded_sha256": checker_sha256,
        },
        "protocol": {
            "label": plan["lane_contract"]["protocol_label"],
            "native_tools_field_present": False,
            "tool_choice_field_present": False,
            "native_function_calling_claim": False,
            "official_leaderboard_claim": False,
            "mcp_transport_claim": False,
            "client_side_decoder": "FROZEN_BFCL_DEFAULT_PYTHON_PROMPT_DECODER",
            "temperature": 0,
            "seed": 20260821,
            "max_output_tokens": prompt_probe.MAX_OUTPUT_TOKENS,
        },
        "record": {
            "case_id": case.case_id,
            "source_case_id": case.source_case_id,
            "category": case.category,
            "status": "TERMINAL_LOCAL_VLLM_ADAPTED_BFCL_PROMPT_DEV_SMOKE",
            "native_request_id": completion.native_request_id,
            "usage": {
                **dict(completion.usage),
                "model_rounds": 1,
                "mcp_rounds": 0,
                "hidden_or_extra_model_calls": 0,
            },
            "latency_ms": round(completion.latency_ms, 3),
            "native_receipt_sha256": completion.native_receipt_sha256,
            "response_sha256": completion.response_sha256,
            "request_messages_sha256": dev_smoke._json_sha256(messages),
            "answer_record": {
                "ground_truth_sha256": (
                    dev_smoke._json_sha256(case.ground_truth)
                    if case.ground_truth is not None
                    else None
                ),
                "response_text_sha256": dev_smoke._sha256_bytes(
                    completion.text.encode()
                ),
                "decoded_calls_sha256": dev_smoke._json_sha256(decoded),
                "decoder_success": decoder_success,
                "decoder_error_type": decoder_error_type,
                "raw_prompt_in_report": False,
                "raw_function_schemas_in_report": False,
                "raw_ground_truth_in_report": False,
                "raw_model_response_in_report": False,
                **score,
            },
        },
        "aggregates": {
            "case_count": 1,
            "official_checker_accuracy": int(score["official_checker_valid"]),
            "tool_selection_accuracy": int(score["tool_selection_correct"]),
            "argument_correctness_accuracy": (
                int(score["argument_correctness"])
                if score["argument_correctness"] is not None
                else None
            ),
            "no_call_accuracy": (
                int(score["no_call_correct"])
                if score["no_call_correct"] is not None
                else None
            ),
            "invalid_tool_call_rate": int(score["invalid_tool_call"]),
            "input_tokens": completion.usage["input_tokens"],
            "output_tokens": completion.usage["output_tokens"],
            "latency_ms": round(completion.latency_ms, 3),
        },
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-03": "NO_GO_SINGLE_CASE_SMOKE_NOT_216_CASE_DEV_CALIBRATION",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "adapted_prompt_smoke": "COMPLETE",
            "contract_ambiguity": "REVIEW_REQUIRED",
        },
        "known_limits": [
            "This is one BFCL dev case, not the 216-case calibration or release test.",
            "The result is adapted prompt mode, client-decoded, non-native, and non-leaderboard-comparable.",
            "Only Python single-turn and irrelevance paths are implemented by this smoke runner.",
            "No MCP wire, memory-arm, or every-public-case claim is supported.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.bfcl-prompt-single-turn-dev-smoke-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_TOOL_SCHEMA_LABEL_AND_MODEL_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "record": {
            "case_id": case.case_id,
            "source_case_id": case.source_case_id,
            "category": case.category,
            "messages": messages,
            "functions": case.functions,
            "ground_truth": case.ground_truth,
            "response_text": completion.text,
            "decoded_calls": decoded,
            "score": score,
        },
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one adapted BFCL prompt-mode Python/no-call dev smoke"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--dataset-lock", type=Path, default=DEFAULT_DATASET_LOCK)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--bfcl-root", type=Path, default=DEFAULT_BFCL_ROOT)
    parser.add_argument("--case-id", required=True)
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
    ):
        raise PromptDevSmokeError(
            "real calls require --execute-local-vllm and exact --data-boundary-ack"
        )
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
    except dev_smoke.DevSmokeError as exc:
        raise PromptDevSmokeError(str(exc)) from exc
    client = prompt_probe.LocalPromptClient(
        args.base_url, args.identity_report, args.timeout
    )
    report, sidecar = run_smoke(
        dataset_lock_path=args.dataset_lock,
        plan_path=args.plan,
        bfcl_root=args.bfcl_root,
        case_id=args.case_id,
        client=client,
    )
    client.post_identity_check()
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
                "official_checker_valid": report["record"]["answer_record"][
                    "official_checker_valid"
                ],
                "local_vllm_requests": 1,
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
