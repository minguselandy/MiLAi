from __future__ import annotations

import argparse
import json
import sys
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

from scripts import dg10_bfcl_multiturn_safety as safety
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_contract as contract
from scripts import run_dg10_bfcl_prompt_capability_probe as prior_probe

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
CONTRACT_CANDIDATE = "candidate.8"
EXECUTION_ACK = "strict-synthetic-only-eight-rounds-no-benchmark-material"
DEFAULT_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-safety-contract-{CONTRACT_CANDIDATE}-{DATE}.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-local-probe-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-multiturn-local-probe"
)

_TEMPERATURE_TOOL = {
    "name": "fetch_temperature",
    "description": "Fetch a temperature for a synthetic city.",
    "parameters": {
        "type": "dict",
        "properties": {
            "city": {"type": "string"},
            "unit": {"type": "string"},
        },
        "required": ["city", "unit"],
    },
}
_DISTANCE_TOOL = {
    "name": "convert_distance",
    "description": "Convert a synthetic distance.",
    "parameters": {
        "type": "dict",
        "properties": {
            "distance": {"type": "float"},
            "from_unit": {"type": "string"},
            "to_unit": {"type": "string"},
        },
        "required": ["distance", "from_unit", "to_unit"],
    },
}
STRICT_SYNTHETIC_FIXTURES = (
    {
        "id": "select_then_empty",
        "functions": (_TEMPERATURE_TOOL, _DISTANCE_TOOL),
        "user": (
            "Fetch the temperature for synthetic city Zephyr-8 in celsius, then "
            "finish after the tool result."
        ),
        "expected_raw_steps": (
            "[fetch_temperature(city='Zephyr-8', unit='celsius')]",
            "[]",
        ),
        "tool_results": (("{\"temperature\":19,\"unit\":\"celsius\"}",),),
        "parallel_step_indexes": (),
    },
    {
        "id": "explicit_no_call",
        "functions": (_TEMPERATURE_TOOL, _DISTANCE_TOOL),
        "user": (
            "No available function is applicable. Follow the strict system format "
            "for no call."
        ),
        "expected_raw_steps": ("[]",),
        "tool_results": (),
        "parallel_step_indexes": (),
    },
    {
        "id": "parallel_then_empty",
        "functions": (
            {
                "name": "sum_values",
                "description": "Sum synthetic integer values.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "values": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["values"],
                },
            },
            {
                "name": "store_profile",
                "description": "Store a synthetic profile.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "profile": {
                            "type": "dict",
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
        "user": (
            "Call both independent functions: sum 2, 5, and 8; store profile "
            "Probe with active true; then finish after both results."
        ),
        "expected_raw_steps": (
            (
                "[sum_values(values=[2, 5, 8]), "
                "store_profile(profile={'name': 'Probe', 'active': True})]"
            ),
            "[]",
        ),
        "tool_results": (("15", "{\"stored\":true}"),),
        "parallel_step_indexes": (0,),
    },
    {
        "id": "two_execution_steps_then_empty",
        "functions": (
            {
                "name": "inspect_inventory",
                "description": "Inspect synthetic inventory.",
                "parameters": {
                    "type": "dict",
                    "properties": {"item_id": {"type": "string"}},
                    "required": ["item_id"],
                },
            },
            {
                "name": "reserve_inventory",
                "description": "Reserve synthetic inventory after inspection.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "item_id": {"type": "string"},
                        "quantity": {"type": "integer"},
                        "authorization": {
                            "type": "dict",
                            "properties": {"code": {"type": "string"}},
                        },
                    },
                    "required": ["item_id", "quantity", "authorization"],
                },
            },
        ),
        "user": (
            "Inspect widget-syn-10. If the result permits, reserve exactly 2 with "
            "the returned authorization, then finish."
        ),
        "expected_raw_steps": (
            "[inspect_inventory(item_id='widget-syn-10')]",
            (
                "[reserve_inventory(item_id='widget-syn-10', quantity=2, "
                "authorization={'code': 'AUTH-SYN-8'})]"
            ),
            "[]",
        ),
        "tool_results": (
            ("{\"available\":4,\"authorization\":{\"code\":\"AUTH-SYN-8\"}}",),
            ("{\"reserved\":2}",),
        ),
        "parallel_step_indexes": (),
    },
)
STRICT_SYNTHETIC_CONTRACT = {
    "fixture_version": "dg10-bfcl-multiturn-strict-synthetic-v1",
    "dialogue_count": 4,
    "total_model_rounds": 8,
    "retry_model_calls_max": 0,
    "hidden_or_extra_model_calls_max": 0,
    "benchmark_material": False,
    "strict_explicit_empty_list_required": True,
    "fixtures_sha256": dev_smoke._json_sha256(STRICT_SYNTHETIC_FIXTURES),
}


class MultiTurnLocalProbeError(RuntimeError):
    pass


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MultiTurnLocalProbeError(f"invalid safety contract: {path}") from exc
    if (
        not isinstance(report, dict)
        or report.get("schema") != "milai.dg10.bfcl-multiturn-safety-contract.v1"
        or report.get("candidate") != CONTRACT_CANDIDATE
        or report.get("status")
        != "OFFLINE_SAFETY_PASS_REVISED_LOCAL_MODEL_PROBE_NOT_RUN"
        or report.get("test_access_authorized") is not False
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or report.get("gate_results", {}).get("offline_ast_corpus") != "PASS_BOUND"
        or report.get("gate_results", {}).get("scripted_state_machine")
        != "PASS_BOUND"
        or report.get("gate_results", {}).get("revised_synthetic_local_vllm")
        != "NOT_RUN"
    ):
        raise MultiTurnLocalProbeError("candidate.8 contract boundary mismatch")
    local_closure = report.get("local_harness_byte_closure", {})
    if local_closure.get("revised_local_model_probe", {}).get(
        "sha256"
    ) != dev_smoke._sha256_file(Path(__file__).resolve()):
        raise MultiTurnLocalProbeError("local probe script bytes drifted")
    if report.get("strict_synthetic_local_probe_contract", {}).get(
        "contract_sha256"
    ) != dev_smoke._json_sha256(STRICT_SYNTHETIC_CONTRACT):
        raise MultiTurnLocalProbeError("strict synthetic contract drifted")
    return report


def _canonical_strings(calls: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in calls
    )


def _tool_result_message(calls: Sequence[str], results: Sequence[str]) -> str:
    if len(calls) != len(results):
        raise MultiTurnLocalProbeError("synthetic call/result count mismatch")
    return repr(
        [
            {"role": "tool", "name": call, "content": result}
            for call, result in zip(calls, results, strict=True)
        ]
    )


def run_probe(
    *,
    contract_path: Path,
    bfcl_root: Path,
    client: prior_probe.PromptClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    frozen_contract = _load_contract(contract_path.resolve())
    prompt_utils, decoder_sha256 = prior_probe._load_official_prompt_utils(
        bfcl_root.resolve()
    )
    expected_decoder_sha256 = frozen_contract["official_upstream_byte_closure"][
        "core"
    ]["prompt_decoder_and_serializer"]["sha256"]
    if decoder_sha256 != expected_decoder_sha256:
        raise MultiTurnLocalProbeError("official prompt decoder bytes drifted")
    decoder = prompt_utils.default_decode_execute_prompting
    run_id = f"dg10-bfcl-multiturn-local-probe-{DATE}-{uuid4().hex[:12]}"
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    completions: list[prior_probe.PromptCompletion] = []
    for fixture in STRICT_SYNTHETIC_FIXTURES:
        functions = list(fixture["functions"])
        function_names = frozenset(str(item["name"]) for item in functions)
        system_prompt = (
            prompt_utils.formulate_system_prompt(
                prompt_utils.DEFAULT_SYSTEM_PROMPT_FORMAT, functions
            )
            + contract.SAFETY_PROMPT_SUFFIX
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fixture["user"]},
        ]
        expected_steps = fixture["expected_raw_steps"]
        expected_attestations = [
            safety.attest_dual_gate(raw, function_names, decoder)
            for raw in expected_steps
        ]
        tool_results = fixture["tool_results"]
        current_executor_step = 0

        def executor(
            calls: Sequence[str], frozen_results: Sequence[Sequence[str]] = tool_results
        ) -> Sequence[str]:
            nonlocal current_executor_step
            results = frozen_results[current_executor_step]
            current_executor_step += 1
            if len(calls) != len(results):
                raise MultiTurnLocalProbeError("fixture executor shape mismatch")
            return results

        machine = safety.SafeTurnStateMachine(function_names, decoder, executor)
        steps: list[dict[str, Any]] = []
        raw_steps: list[dict[str, Any]] = []
        can_continue = True
        for step_index, expected in enumerate(expected_attestations):
            if not can_continue:
                steps.append(
                    {
                        "step_index": step_index,
                        "status": "SKIPPED_PREVIOUS_FAILURE",
                        "oracle_pass": False,
                    }
                )
                continue
            completion = client.complete(
                messages,
                request_key=f"{run_id}:{fixture['id']}:{step_index}",
            )
            completions.append(completion)
            outcome = machine.process_native_step(
                completion.text,
                {
                    "native_request_id": completion.native_request_id,
                    "usage": dict(completion.usage),
                    "latency_ms": round(completion.latency_ms, 3),
                    "native_receipt_sha256": completion.native_receipt_sha256,
                    "response_sha256": completion.response_sha256,
                },
            )
            actual_calls = outcome.get("canonical_calls", [])
            if step_index in fixture["parallel_step_indexes"]:
                oracle_pass = _canonical_strings(actual_calls) == _canonical_strings(
                    expected.canonical_calls
                )
            else:
                oracle_pass = tuple(actual_calls) == expected.canonical_calls
            expected_status = (
                "TURN_COMPLETE_EXPLICIT_EMPTY_LIST"
                if not expected.execution_calls
                else "EXECUTED_ATTESTED_CALLS"
            )
            oracle_pass = oracle_pass and outcome["status"] == expected_status
            step = {
                "step_index": step_index,
                "status": outcome["status"],
                "native_request_id": completion.native_request_id,
                "usage": dict(completion.usage),
                "latency_ms": round(completion.latency_ms, 3),
                "native_receipt_sha256": completion.native_receipt_sha256,
                "response_sha256": completion.response_sha256,
                "request_messages_sha256": dev_smoke._json_sha256(messages),
                "response_text_sha256": dev_smoke._sha256_bytes(
                    completion.text.encode("utf-8")
                ),
                "expected_canonical_calls_sha256": dev_smoke._json_sha256(
                    expected.canonical_calls
                ),
                "actual_canonical_calls_sha256": dev_smoke._json_sha256(
                    actual_calls
                ),
                "execution_permitted": outcome["execution_permitted"],
                "tool_results_emitted": outcome["tool_results_emitted"],
                "oracle_pass": oracle_pass,
            }
            if machine.failure_code is not None:
                step["failure_code"] = machine.failure_code
            steps.append(step)
            raw_steps.append(
                {
                    "step_index": step_index,
                    "messages": list(messages),
                    "response_text": completion.text,
                    "expected_raw": fixture["expected_raw_steps"][step_index],
                    "outcome": outcome,
                    "oracle_pass": oracle_pass,
                }
            )
            if not oracle_pass:
                can_continue = False
                continue
            if outcome["status"] == "EXECUTED_ATTESTED_CALLS":
                messages.append({"role": "assistant", "content": completion.text})
                messages.append(
                    {
                        "role": "user",
                        "content": _tool_result_message(
                            expected.execution_calls, outcome["tool_results"]
                        ),
                    }
                )
        dialogue_pass = (
            len(steps) == len(expected_steps)
            and all(item["oracle_pass"] for item in steps)
            and machine.complete
            and machine.failure_code is None
        )
        records.append(
            {
                "probe_id": fixture["id"],
                "status": "PASS" if dialogue_pass else "FAIL",
                "model_rounds_planned": len(expected_steps),
                "model_rounds_executed": len(raw_steps),
                "oracle_pass": dialogue_pass,
                "system_prompt_sha256": dev_smoke._sha256_bytes(
                    system_prompt.encode("utf-8")
                ),
                "function_docs_sha256": dev_smoke._json_sha256(functions),
                "raw_synthetic_data_in_report": False,
                "steps": steps,
            }
        )
        raw_records.append(
            {
                "probe_id": fixture["id"],
                "functions": functions,
                "user": fixture["user"],
                "system_prompt": system_prompt,
                "steps": raw_steps,
                "oracle_pass": dialogue_pass,
            }
        )
    ended = datetime.now(UTC)
    passed = len(records) == 4 and all(item["oracle_pass"] for item in records)
    native_ids = [item.native_request_id for item in completions]
    if len(native_ids) != len(set(native_ids)):
        raise MultiTurnLocalProbeError("native request IDs are not unique")
    report = {
        "schema": "milai.dg10.bfcl-multiturn-local-probe.v1",
        "candidate": CANDIDATE,
        "date": DATE,
        "run_id": run_id,
        "status": (
            "STRICT_SYNTHETIC_LOCAL_VLLM_PROBE_PASS"
            if passed
            else "STRICT_SYNTHETIC_LOCAL_VLLM_PROBE_FAIL"
        ),
        "quality_outcome": "NOT_APPLICABLE_SYNTHETIC_CAPABILITY_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "SYNTHETIC_ONLY_NO_BENCHMARK_PROMPT_LABEL_OR_OUTPUT",
        "benchmark_material_opened_by_probe": False,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": client.completion_requests,
        "local_tokenizer_requests": client.tokenizer_requests,
        "hidden_or_extra_model_calls": 0,
        "retry_model_calls": 0,
        "unique_native_request_ids": len(native_ids),
        "identity_pre": dict(client.identity_evidence),
        "identity_post": "PENDING_MAIN_POST_CHECK",
        "inputs": {
            "safety_contract_sha256": dev_smoke._sha256_file(
                contract_path.resolve()
            ),
            "strict_synthetic_contract_sha256": dev_smoke._json_sha256(
                STRICT_SYNTHETIC_CONTRACT
            ),
            "strict_synthetic_fixtures_sha256": dev_smoke._json_sha256(
                STRICT_SYNTHETIC_FIXTURES
            ),
            "official_prompt_decoder_sha256": decoder_sha256,
            "local_probe_script_sha256": dev_smoke._sha256_file(
                Path(__file__).resolve()
            ),
        },
        "protocol": {
            "label": "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD",
            "request_api": "OPENAI_COMPATIBLE_CHAT_COMPLETIONS_ORDINARY_TEXT_ONLY",
            "native_tools_field_present": False,
            "tool_choice_field_present": False,
            "strict_safety_prompt_suffix_sha256": dev_smoke._json_sha256(
                contract.SAFETY_PROMPT_SUFFIX
            ),
            "client_side_dual_ast_gate": True,
            "native_function_calling_claim": False,
            "official_leaderboard_claim": False,
            "mcp_transport_claim": False,
            "temperature": 0,
            "seed": 20260821,
            "max_output_tokens": prior_probe.MAX_OUTPUT_TOKENS,
        },
        "records": records,
        "aggregates": {
            "dialogues_planned": 4,
            "dialogues_passed": sum(int(item["oracle_pass"]) for item in records),
            "model_rounds_planned": 8,
            "model_rounds_executed": len(completions),
            "input_tokens": sum(
                int(item.usage["input_tokens"] or 0) for item in completions
            ),
            "output_tokens": sum(
                int(item.usage["output_tokens"] or 0) for item in completions
            ),
            "latency_ms_mean": (
                round(mean(item.latency_ms for item in completions), 3)
                if completions
                else None
            ),
            "safety_failure_dialogues": sum(
                int(
                    any(
                        step.get("failure_code") is not None
                        for step in item["steps"]
                    )
                )
                for item in records
            ),
        },
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "static_no_label_closure": "PASS_BOUND",
            "offline_ast_corpus": "PASS_BOUND",
            "scripted_state_machine": "PASS_BOUND",
            "revised_synthetic_local_vllm": "PASS" if passed else "FAIL",
            "BMG-03": "NO_GO_SYNTHETIC_PROBE_IS_NOT_DEV_CALIBRATION",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This is an eight-round synthetic endpoint probe, not a BFCL benchmark score.",
            "Prompt-mode calls are dual-gated, client-decoded, non-native, adapted, and non-leaderboard-comparable.",
            "A PASS authorizes only the separately predeclared development generation workflow; it does not authorize test access.",
            "No MCP wire, memory-arm, external-provider, quality-threshold, or formal CRG claim is supported.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.bfcl-multiturn-local-probe-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "SYNTHETIC_PUBLIC_NON_BENCHMARK_PROMPTS_AND_OUTPUTS",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the strict eight-round BFCL multi-turn local-vLLM probe"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--synthetic-probe-ack")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_local_vllm or args.synthetic_probe_ack != EXECUTION_ACK:
        raise MultiTurnLocalProbeError(
            "real calls require --execute-local-vllm and exact --synthetic-probe-ack"
        )
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
    except dev_smoke.DevSmokeError as exc:
        raise MultiTurnLocalProbeError(str(exc)) from exc
    client = prior_probe.LocalPromptClient(
        args.base_url, args.identity_report, args.timeout
    )
    report, sidecar = run_probe(
        contract_path=args.contract,
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
                "dialogues_passed": report["aggregates"]["dialogues_passed"],
                "model_rounds_executed": report["aggregates"][
                    "model_rounds_executed"
                ],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
