from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Protocol
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
EVAL_DIRECTORY = ROOT / "evals/agent_efficiency"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EVAL_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(EVAL_DIRECTORY))

from evals.agent_efficiency import vllm_local_ab
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract

DATE = "2026-08-21"
CANDIDATE = "candidate.1"
MODEL_ID = dev_smoke.MODEL_ID
MAX_OUTPUT_TOKENS = 512
EXECUTION_ACK = "synthetic-only-no-benchmark-material-five-rounds-max"
PROBE_PLAN_CANDIDATE = "candidate.4"
DEFAULT_PLAN = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-{PROBE_PLAN_CANDIDATE}-{DATE}.json"
)
DEFAULT_BFCL_ROOT = bfcl_contract.DEFAULT_BFCL_ROOT
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-prompt-capability-probe-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-prompt-capability-probe"
)
SOL_ADVISORY_PROMPT_SHA256 = (
    "73b7edc29a0da277fef9542492acc6d1037bdb2667c402dc78265b079d712c96"
)
SOL_ADVISORY_OUTPUT_SHA256 = (
    "05dbc5f14437e5ef96b0c203aafc6dd37627dc16ae3607bd673d1144f4fa76d2"
)


class PromptProbeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PromptCompletion:
    native_request_id: str
    text: str
    usage: Mapping[str, int | None]
    latency_ms: float
    native_receipt_sha256: str
    response_sha256: str


class PromptClient(Protocol):
    tokenizer_requests: int
    completion_requests: int
    identity_evidence: Mapping[str, Any]

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
    ) -> PromptCompletion: ...


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PromptProbeError(f"{label} must be an object")
    return value


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptProbeError(f"invalid JSON file: {path}") from exc


def _stub_module(name: str, attributes: Mapping[str, Any]) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_official_prompt_utils(root: Path) -> tuple[types.ModuleType, str]:
    utils_path = root / "bfcl_eval/model_handler/utils.py"
    digest = dev_smoke._sha256_file(utils_path)
    root_string = str(root.resolve())
    preserved = {
        name: value
        for name, value in sys.modules.items()
        if name == "bfcl_eval"
        or name.startswith("bfcl_eval.")
        or name == "tenacity"
    }
    inserted_path = root_string not in sys.path
    if inserted_path:
        sys.path.insert(0, root_string)
    parser_stubs = {
        "bfcl_eval.model_handler.parser.java_parser": {
            "parse_java_function_call": lambda value: value
        },
        "bfcl_eval.model_handler.parser.js_parser": {
            "parse_javascript_function_call": lambda value: value
        },
        "bfcl_eval.model_handler.parser.json_parser": {
            "parse_json_function_call": lambda value: value
        },
        "bfcl_eval.model_handler.parser.xml_parser": {
            "parse_concise_xml_function_call": lambda value: value,
            "parse_verbose_xml_function_call": lambda value: value,
        },
    }

    def _decorator(*_args: Any, **_kwargs: Any) -> Any:
        def decorate(function: Any) -> Any:
            return function

        return decorate

    tenacity = _stub_module(
        "tenacity",
        {
            "retry": _decorator,
            "retry_if_exception_message": lambda *_args, **_kwargs: None,
            "retry_if_exception_type": lambda *_args, **_kwargs: None,
            "wait_random_exponential": lambda *_args, **_kwargs: None,
        },
    )
    try:
        for name, attributes in parser_stubs.items():
            sys.modules[name] = _stub_module(name, attributes)
        sys.modules["tenacity"] = tenacity
        spec = importlib.util.spec_from_file_location(
            "dg10_frozen_bfcl_prompt_utils", utils_path
        )
        if spec is None or spec.loader is None:
            raise PromptProbeError("cannot load frozen BFCL prompt utilities")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name in tuple(sys.modules):
            if (
                name == "bfcl_eval"
                or name.startswith("bfcl_eval.")
                or name == "tenacity"
            ):
                sys.modules.pop(name, None)
        sys.modules.update(preserved)
        if inserted_path:
            sys.path.remove(root_string)
    required = (
        "formulate_system_prompt",
        "default_decode_ast_prompting",
        "convert_to_function_call",
        "DEFAULT_SYSTEM_PROMPT_FORMAT",
        "ReturnFormat",
    )
    if any(not hasattr(module, item) for item in required):
        raise PromptProbeError("frozen BFCL prompt utilities are incomplete")
    return module, digest


def _load_contract(plan_path: Path, bfcl_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = _require_object(_load_json(plan_path), "BFCL adapted plan")
    if (
        plan.get("schema") != "milai.dg10.bfcl-v4-local-calibration-plan.v1"
        or plan.get("candidate") != PROBE_PLAN_CANDIDATE
        or plan.get("status")
        != "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
        or plan.get("test_access_authorized") is not False
        or plan.get("quality_thresholds_frozen") is not False
        or plan.get("lane_contract", {}).get("protocol_label")
        != "ADAPTED_ENDPOINT_PROTOCOL_BFCL_PROMPT_MODE_NON_LEADERBOARD"
    ):
        raise PromptProbeError("BFCL adapted plan boundary mismatch")
    generation = _require_object(plan.get("generation_contract"), "generation contract")
    if (
        generation.get("native_tools_field_present") is not False
        or generation.get("tool_choice_field_present") is not False
        or generation.get("max_output_tokens") != MAX_OUTPUT_TOKENS
        or generation.get("retry_model_calls_max") != 0
    ):
        raise PromptProbeError("BFCL prompt generation contract mismatch")
    probe = _require_object(
        plan.get("synthetic_capability_probe"), "synthetic probe contract"
    )
    if (
        probe.get("status") != "NOT_RUN"
        or probe.get("fixtures_sha256")
        != dev_smoke._json_sha256(bfcl_contract.SYNTHETIC_PROBE_FIXTURES)
        or probe.get("contract_sha256")
        != dev_smoke._json_sha256(bfcl_contract.SYNTHETIC_PROBE_CONTRACT)
        or probe.get("total_model_rounds") != 5
    ):
        raise PromptProbeError("synthetic probe fixture/contract drift")
    root = bfcl_root.resolve()
    if bfcl_contract._git_head(root) != plan.get("inputs", {}).get("bfcl_git_head"):
        raise PromptProbeError("BFCL git HEAD differs from adapted plan")
    scorer_hashes = _require_object(
        plan.get("scorer_contract", {}).get("scorer_file_sha256"),
        "BFCL scorer hashes",
    )
    paths = {
        "model_handler_utils": root / "bfcl_eval/model_handler/utils.py",
        "default_prompts": root / "bfcl_eval/constants/default_prompts.py",
        "qwen_local_prompt_handler": (
            root / "bfcl_eval/model_handler/local_inference/qwen.py"
        ),
        "base_oss_prompt_handler": (
            root / "bfcl_eval/model_handler/local_inference/base_oss_handler.py"
        ),
        "openai_completion_handler": (
            root / "bfcl_eval/model_handler/api_inference/openai_completion.py"
        ),
    }
    actual_hashes = {name: dev_smoke._sha256_file(path) for name, path in paths.items()}
    if any(scorer_hashes.get(name) != digest for name, digest in actual_hashes.items()):
        raise PromptProbeError("BFCL adapted prompt/parser source bytes drift")
    evidence = {
        "adapted_plan_sha256": dev_smoke._sha256_file(plan_path.resolve()),
        "bfcl_git_head": plan["inputs"]["bfcl_git_head"],
        "probe_contract_sha256": probe["contract_sha256"],
        "probe_fixtures_sha256": probe["fixtures_sha256"],
        "prompt_and_parser_source_sha256": actual_hashes,
    }
    return plan, evidence


class LocalPromptClient:
    def __init__(self, base_url: str, identity_report: Path, timeout: float) -> None:
        try:
            verified = dev_smoke.LocalVllmClient(base_url, identity_report, timeout)
        except dev_smoke.DevSmokeError as exc:
            raise PromptProbeError(str(exc)) from exc
        self.base_url = verified.base_url
        self.timeout = timeout
        self.max_model_len = verified.max_model_len
        self.identity_evidence = dict(verified.identity_evidence)
        self.tokenizer_requests = 0
        self.completion_requests = 0

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
    ) -> PromptCompletion:
        self.tokenizer_requests += 1
        try:
            prompt_tokens = vllm_local_ab._tokenize(
                self.base_url, messages, (), timeout=self.timeout
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise PromptProbeError("synthetic probe tokenizer request failed") from exc
        if prompt_tokens > self.max_model_len:
            raise PromptProbeError("synthetic prompt exceeds frozen max_model_len")
        payload = {
            "model": MODEL_ID,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
            "seed": 20260821,
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "cache_salt": dev_smoke._sha256_bytes(
                f"dg10-bfcl-prompt-probe:{request_key}".encode()
            ),
        }
        if "tools" in payload or "tool_choice" in payload:
            raise PromptProbeError("native tool fields are prohibited in prompt mode")
        self.completion_requests += 1
        started = time.perf_counter()
        try:
            response, headers = vllm_local_ab._post_json(
                self.base_url,
                "/v1/chat/completions",
                payload,
                timeout=self.timeout,
            )
            latency_ms = (time.perf_counter() - started) * 1000
            text, usage, native_id, receipt = vllm_local_ab._validate_completion(
                response,
                headers,
                expected_prompt_tokens=prompt_tokens,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise PromptProbeError("synthetic prompt completion failed") from exc
        return PromptCompletion(
            native_request_id=native_id,
            text=text,
            usage=usage,
            latency_ms=latency_ms,
            native_receipt_sha256=receipt,
            response_sha256=dev_smoke._json_sha256(response),
        )

    def post_identity_check(self) -> Mapping[str, Any]:
        try:
            verified = dev_smoke.LocalVllmClient(
                self.base_url, dev_smoke.IDENTITY_REPORT, self.timeout
            )
        except dev_smoke.DevSmokeError as exc:
            raise PromptProbeError("post-probe vLLM identity check failed") from exc
        post = dict(verified.identity_evidence)
        if post != self.identity_evidence:
            raise PromptProbeError("pre/post vLLM identity evidence drift")
        return post


def _canonical_calls(value: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(dev_smoke._encoded_json(item).decode() for item in value)


def _decode(
    prompt_utils: types.ModuleType, text: str
) -> tuple[tuple[Mapping[str, Any], ...], bool, str | None]:
    try:
        decoded = prompt_utils.default_decode_ast_prompting(
            text,
            language=prompt_utils.ReturnFormat.PYTHON,
            has_tool_call_tag=False,
        )
    # BFCL's official relevance runner intentionally treats any decoder exception
    # as a no-call result; preserve that exact boundary here.
    except Exception as exc:
        return (), False, type(exc).__name__
    if not isinstance(decoded, list) or any(not isinstance(item, dict) for item in decoded):
        raise PromptProbeError("official BFCL decoder returned an invalid envelope")
    return tuple(decoded), True, None


def _oracle_pass(
    probe_id: str,
    expected: Sequence[Mapping[str, Any]],
    decoded: Sequence[Mapping[str, Any]],
    decoder_success: bool,
) -> bool:
    if not expected:
        return not decoder_success or not decoded
    if not decoder_success:
        return False
    if probe_id == "parallel_two":
        return _canonical_calls(expected) == _canonical_calls(decoded)
    return list(expected) == list(decoded)


def _tool_result_message(
    prompt_utils: types.ModuleType,
    decoded: Sequence[Mapping[str, Any]],
    tool_result: str,
) -> str:
    execution_calls = prompt_utils.convert_to_function_call(list(decoded))
    if not isinstance(execution_calls, list) or len(execution_calls) != 1:
        raise PromptProbeError("multi-turn probe expected exactly one executable call")
    return repr(
        [{"role": "tool", "name": execution_calls[0], "content": tool_result}]
    )


def run_probe(
    *,
    plan_path: Path,
    bfcl_root: Path,
    client: PromptClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    plan, input_evidence = _load_contract(plan_path.resolve(), bfcl_root.resolve())
    prompt_utils, utils_sha256 = _load_official_prompt_utils(bfcl_root.resolve())
    if utils_sha256 != input_evidence["prompt_and_parser_source_sha256"][
        "model_handler_utils"
    ]:
        raise PromptProbeError("loaded BFCL prompt utility bytes drift")
    run_id = f"dg10-bfcl-prompt-probe-{DATE}-{uuid4().hex[:12]}"
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    all_completions: list[PromptCompletion] = []
    for fixture in bfcl_contract.SYNTHETIC_PROBE_FIXTURES:
        probe_id = str(fixture["id"])
        functions = list(fixture["functions"])
        system_prompt = prompt_utils.formulate_system_prompt(
            prompt_utils.DEFAULT_SYSTEM_PROMPT_FORMAT, functions
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fixture["user"]},
        ]
        expected_steps = fixture["expected_steps"]
        tool_results = fixture["tool_results"]
        steps: list[dict[str, Any]] = []
        raw_steps: list[dict[str, Any]] = []
        can_continue = True
        for step_index, expected in enumerate(expected_steps):
            if not can_continue:
                steps.append(
                    {
                        "step_index": step_index,
                        "status": "SKIPPED_PREVIOUS_ORACLE_FAILURE",
                        "oracle_pass": False,
                    }
                )
                continue
            completion = client.complete(
                messages,
                request_key=f"{run_id}:{probe_id}:{step_index}",
            )
            all_completions.append(completion)
            decoded, decoder_success, decoder_error_type = _decode(
                prompt_utils, completion.text
            )
            passed = _oracle_pass(
                probe_id, expected, decoded, decoder_success
            )
            step = {
                "step_index": step_index,
                "status": "COMPLETE",
                "native_request_id": completion.native_request_id,
                "usage": dict(completion.usage),
                "latency_ms": round(completion.latency_ms, 3),
                "native_receipt_sha256": completion.native_receipt_sha256,
                "response_sha256": completion.response_sha256,
                "request_messages_sha256": dev_smoke._json_sha256(messages),
                "response_text_sha256": dev_smoke._sha256_bytes(
                    completion.text.encode()
                ),
                "expected_calls_sha256": dev_smoke._json_sha256(expected),
                "decoded_calls_sha256": dev_smoke._json_sha256(decoded),
                "decoder_success": decoder_success,
                "decoder_error_type": decoder_error_type,
                "oracle_pass": passed,
                "native_tools_field_present": False,
                "tool_choice_field_present": False,
            }
            steps.append(step)
            raw_steps.append(
                {
                    "step_index": step_index,
                    "messages": list(messages),
                    "response_text": completion.text,
                    "expected_calls": expected,
                    "decoded_calls": decoded,
                    "oracle_pass": passed,
                }
            )
            if not passed:
                can_continue = False
                continue
            if step_index < len(tool_results):
                messages.append({"role": "assistant", "content": completion.text})
                messages.append(
                    {
                        "role": "user",
                        "content": _tool_result_message(
                            prompt_utils, decoded, str(tool_results[step_index])
                        ),
                    }
                )
        probe_pass = len(steps) == len(expected_steps) and all(
            step["oracle_pass"] for step in steps
        )
        records.append(
            {
                "probe_id": probe_id,
                "status": "PASS" if probe_pass else "FAIL",
                "model_rounds_planned": len(expected_steps),
                "model_rounds_executed": len(raw_steps),
                "oracle_pass": probe_pass,
                "functions_sha256": dev_smoke._json_sha256(functions),
                "system_prompt_sha256": dev_smoke._sha256_bytes(
                    system_prompt.encode()
                ),
                "raw_synthetic_data_in_report": False,
                "steps": steps,
            }
        )
        raw_records.append(
            {
                "probe_id": probe_id,
                "functions": functions,
                "user": fixture["user"],
                "system_prompt": system_prompt,
                "steps": raw_steps,
                "oracle_pass": probe_pass,
            }
        )
    ended = datetime.now(UTC)
    passed = len(records) == 4 and all(item["oracle_pass"] for item in records)
    native_ids = [item.native_request_id for item in all_completions]
    if len(native_ids) != len(set(native_ids)):
        raise PromptProbeError("synthetic probe native request IDs are not unique")
    total_input = sum(int(item.usage["input_tokens"] or 0) for item in all_completions)
    total_output = sum(int(item.usage["output_tokens"] or 0) for item in all_completions)
    report = {
        "schema": "milai.dg10.bfcl-prompt-capability-probe.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": (
            "BFCL_ADAPTED_PROMPT_SYNTHETIC_CAPABILITY_PROBE_PASS"
            if passed
            else "BFCL_ADAPTED_PROMPT_SYNTHETIC_CAPABILITY_PROBE_FAIL"
        ),
        "quality_outcome": "NOT_APPLICABLE_SYNTHETIC_CAPABILITY_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "SYNTHETIC_ONLY_NO_BENCHMARK_PROMPT_LABEL_OR_OUTPUT",
        "benchmark_material_opened_by_probe": False,
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
            **input_evidence,
            "sol_development_advisory_prompt_sha256": SOL_ADVISORY_PROMPT_SHA256,
            "sol_development_advisory_output_sha256": SOL_ADVISORY_OUTPUT_SHA256,
            "sol_advisory_formal_crg_review": False,
            "official_prompt_utils_loaded_sha256": utils_sha256,
        },
        "protocol": {
            "label": plan["lane_contract"]["protocol_label"],
            "request_api": "OPENAI_COMPATIBLE_CHAT_COMPLETIONS_ORDINARY_TEXT_ONLY",
            "native_tools_field_present": False,
            "tool_choice_field_present": False,
            "client_side_decoder": "FROZEN_BFCL_DEFAULT_PYTHON_PROMPT_DECODER",
            "native_function_calling_claim": False,
            "official_leaderboard_claim": False,
            "mcp_transport_claim": False,
            "temperature": 0,
            "seed": 20260821,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "records": records,
        "aggregates": {
            "dialogues_planned": 4,
            "dialogues_passed": sum(int(item["oracle_pass"]) for item in records),
            "model_rounds_planned": 5,
            "model_rounds_executed": len(all_completions),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "latency_ms_mean": (
                round(mean(item.latency_ms for item in all_completions), 3)
                if all_completions
                else None
            ),
        },
        "superseded_native_auto_observation": plan["lane_contract"][
            "native_auto_lane"
        ],
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "synthetic_prompt_capability": "PASS" if passed else "FAIL",
            "BMG-03": "NO_GO_SYNTHETIC_PROBE_IS_NOT_DEV_CALIBRATION",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "contract_ambiguity": "REVIEW_REQUIRED",
        },
        "known_limits": [
            "This is synthetic endpoint capability evidence, not a BFCL benchmark score.",
            "Prompt-mode calls are client-decoded, non-native, adapted, and non-leaderboard-comparable.",
            "A PASS only authorizes the predeclared <=10% dev calibration under the adapted candidate contract.",
            "No MCP wire, memory-arm, external-provider, or every-public-case claim is supported.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.bfcl-prompt-capability-probe-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "SYNTHETIC_PUBLIC_NON_BENCHMARK_PROMPTS_AND_OUTPUTS",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the frozen five-round synthetic BFCL prompt-mode probe"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--synthetic-probe-ack")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--bfcl-root", type=Path, default=DEFAULT_BFCL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_local_vllm or args.synthetic_probe_ack != EXECUTION_ACK:
        raise PromptProbeError(
            "real calls require --execute-local-vllm and exact --synthetic-probe-ack"
        )
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
    except dev_smoke.DevSmokeError as exc:
        raise PromptProbeError(str(exc)) from exc
    client = LocalPromptClient(args.base_url, args.identity_report, args.timeout)
    report, sidecar = run_probe(
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
