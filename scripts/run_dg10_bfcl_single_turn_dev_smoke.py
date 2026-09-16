from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
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
SUPPORTED_CATEGORIES = (
    "simple_python",
    "multiple",
    "parallel",
    "parallel_multiple",
    "irrelevance",
)
TYPE_MAPPING = {
    "integer": "integer",
    "number": "number",
    "float": "number",
    "string": "string",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "list": "array",
    "dict": "object",
    "object": "object",
    "tuple": "array",
    "any": "string",
    "byte": "integer",
    "short": "integer",
    "long": "integer",
    "double": "number",
    "char": "string",
    "ArrayList": "array",
    "Array": "array",
    "HashMap": "object",
    "Hashtable": "object",
    "Queue": "array",
    "Stack": "array",
    "Any": "string",
    "String": "string",
    "Bigint": "integer",
}
DEFAULT_DATASET_LOCK = bfcl_contract.DEFAULT_DATASET_LOCK
NATIVE_AUTO_PLAN_CANDIDATE = "candidate.2"
DEFAULT_PLAN = (
    ROOT
    / f"docs/reports/DG-10-bfcl-v4-local-calibration-plan-{NATIVE_AUTO_PLAN_CANDIDATE}-{DATE}.json"
)
DEFAULT_BFCL_ROOT = bfcl_contract.DEFAULT_BFCL_ROOT
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-bfcl-v4-local-dev-smoke-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = WORKSPACE_ROOT / "evidence/dg10-bfcl-v4-local-dev-smoke"
MAX_OUTPUT_TOKENS = 256


class BfclSmokeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BfclCase:
    case_id: str
    source_case_id: str
    category: str
    messages: tuple[Mapping[str, Any], ...]
    functions: tuple[Mapping[str, Any], ...]
    ground_truth: tuple[Mapping[str, Any], ...] | None


@dataclass(frozen=True, slots=True)
class BfclCompletion:
    native_request_id: str
    finish_reason: str
    model_responses: tuple[Mapping[str, str], ...]
    content: str | None
    usage: Mapping[str, int]
    latency_ms: float
    native_receipt_sha256: str
    response_sha256: str


class BfclClient(Protocol):
    tokenizer_requests: int
    max_model_len: int
    identity_evidence: Mapping[str, Any]

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
    ) -> BfclCompletion: ...


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BfclSmokeError(f"{label} must be an object")
    return value


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BfclSmokeError(f"invalid JSON file: {path}") from exc


def _require_locked_file(root: Path, descriptor: Mapping[str, Any], label: str) -> Path:
    relative = descriptor.get("path")
    if not isinstance(relative, str) or not relative:
        raise BfclSmokeError(f"{label} path is invalid")
    path = root / relative
    if (
        not path.is_file()
        or path.stat().st_size != descriptor.get("size")
        or dev_smoke._sha256_file(path) != descriptor.get("sha256")
    ):
        raise BfclSmokeError(f"{label} differs from dataset lock")
    return path


def _load_selected_row(path: Path, source_id: str) -> dict[str, Any]:
    selected: dict[str, Any] | None = None
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, start=1):
            match = bfcl_contract.ID_PREFIX.match(raw)
            if match is None:
                raise BfclSmokeError(f"invalid BFCL id prefix: {path}:{line_no}")
            if match.group(1).decode("ascii") != source_id:
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BfclSmokeError(f"invalid selected BFCL row: {path}") from exc
            selected = _require_object(value, "selected BFCL row")
    if selected is None:
        raise BfclSmokeError(f"selected BFCL ID is absent: {source_id}")
    return selected


def _category_for_case(plan: Mapping[str, Any], case_id: str) -> str:
    split = _require_object(plan.get("split"), "BFCL split")
    if case_id not in split.get("dev_case_ids", []):
        raise BfclSmokeError("requested case must be in the frozen BFCL dev split")
    matches = [
        category
        for category, record in _require_object(
            split.get("categories"), "BFCL category split"
        ).items()
        if case_id in _require_object(record, category).get("dev_case_ids", [])
    ]
    if len(matches) != 1:
        raise BfclSmokeError("selected BFCL case category mapping is invalid")
    return matches[0]


def _load_case(
    *,
    dataset_lock_path: Path,
    plan_path: Path,
    bfcl_root: Path,
    case_id: str,
    expected_plan_candidate: str = NATIVE_AUTO_PLAN_CANDIDATE,
) -> tuple[BfclCase, dict[str, Any], dict[str, Any]]:
    dataset_lock = _require_object(_load_json(dataset_lock_path), "dataset lock")
    plan = _require_object(_load_json(plan_path), "BFCL plan")
    if (
        dataset_lock.get("schema") != "milai.dg10.benchmark-dataset-lock.v1"
        or dataset_lock.get("status")
        != "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED"
        or plan.get("schema")
        != "milai.dg10.bfcl-v4-local-calibration-plan.v1"
        or plan.get("status")
        != "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
        or plan.get("candidate") != expected_plan_candidate
        or plan.get("test_access_authorized") is not False
        or plan.get("quality_thresholds_frozen") is not False
        or plan.get("inputs", {}).get("dataset_lock_report_sha256")
        != dev_smoke._sha256_file(dataset_lock_path)
    ):
        raise BfclSmokeError("BFCL dataset-lock/plan boundary mismatch")
    category = _category_for_case(plan, case_id)
    if category not in SUPPORTED_CATEGORIES:
        raise BfclSmokeError(
            "this smoke supports Python single-turn and irrelevance categories only"
        )
    if not case_id.startswith("bfcl_v4:"):
        raise BfclSmokeError("BFCL case ID prefix is invalid")
    source_id = case_id.split(":", 1)[1]
    if source_id in plan.get("quarantine", {}).get("case_ids", []):
        raise BfclSmokeError("quarantined BFCL case cannot be executed")
    bfcl_lock = _require_object(
        _require_object(dataset_lock.get("datasets"), "locked datasets").get(
            "bfcl_v4_local_non_live"
        ),
        "BFCL lock",
    )
    descriptor = _require_object(
        _require_object(bfcl_lock.get("categories"), "BFCL categories").get(category),
        f"BFCL {category}",
    )
    root = bfcl_root.resolve()
    try:
        current_git_head = bfcl_contract._git_head(root)
    except bfcl_contract.BfclContractError as exc:
        raise BfclSmokeError(str(exc)) from exc
    if current_git_head != bfcl_lock.get("git_head"):
        raise BfclSmokeError("BFCL git HEAD differs from dataset lock")
    scorer_files = _require_object(
        _require_object(plan.get("scorer_contract"), "BFCL scorer contract").get(
            "scorer_file_sha256"
        ),
        "BFCL scorer file hashes",
    )
    ast_checker_path = root / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
    tool_utils_path = root / "bfcl_eval/model_handler/utils.py"
    if (
        dev_smoke._sha256_file(ast_checker_path) != scorer_files.get("ast_checker")
        or dev_smoke._sha256_file(tool_utils_path)
        != scorer_files.get("model_handler_utils")
    ):
        raise BfclSmokeError("BFCL scorer/tool conversion bytes differ from plan")
    source_path = _require_locked_file(root, descriptor, f"BFCL {category} source")
    prompt = _load_selected_row(source_path, source_id)
    if prompt.get("id") != source_id:
        raise BfclSmokeError("selected BFCL prompt ID drift")
    questions = prompt.get("question")
    functions = prompt.get("function")
    if (
        not isinstance(questions, list)
        or len(questions) != 1
        or not isinstance(questions[0], list)
        or not questions[0]
        or any(not isinstance(message, dict) for message in questions[0])
        or not isinstance(functions, list)
        or any(not isinstance(function, dict) for function in functions)
    ):
        raise BfclSmokeError("selected BFCL prompt is not valid single-turn data")
    possible_descriptor = _require_object(
        descriptor.get("possible_answer"), "possible-answer descriptor"
    )
    ground_truth: tuple[Mapping[str, Any], ...] | None
    if category == "irrelevance":
        if possible_descriptor.get("path") is not None:
            raise BfclSmokeError("irrelevance case unexpectedly has a label file")
        ground_truth = None
    else:
        possible_path = _require_locked_file(
            root, possible_descriptor, f"BFCL {category} labels"
        )
        answer = _load_selected_row(possible_path, source_id)
        value = answer.get("ground_truth")
        if (
            answer.get("id") != source_id
            or not isinstance(value, list)
            or not value
            or any(not isinstance(item, dict) for item in value)
        ):
            raise BfclSmokeError("selected BFCL ground truth is invalid")
        ground_truth = tuple(value)
    case = BfclCase(
        case_id=case_id,
        source_case_id=source_id,
        category=category,
        messages=tuple(questions[0]),
        functions=tuple(functions),
        ground_truth=ground_truth,
    )
    evidence = {
        "dataset_lock_report_sha256": dev_smoke._sha256_file(dataset_lock_path),
        "calibration_plan_sha256": dev_smoke._sha256_file(plan_path),
        "bfcl_git_head": bfcl_lock["git_head"],
        "source_file_sha256": descriptor["sha256"],
        "possible_answer_file_sha256": possible_descriptor.get("sha256"),
        "official_ast_checker_sha256": scorer_files["ast_checker"],
        "tool_conversion_source_sha256": scorer_files["model_handler_utils"],
        "selected_case_id": case_id,
        "selected_case_id_sha256": dev_smoke._sha256_bytes(case_id.encode()),
    }
    return case, plan, evidence


def _cast_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(dict(properties))
    for key, value in output.items():
        if not isinstance(value, dict):
            raise BfclSmokeError(f"BFCL parameter schema is invalid: {key}")
        if "type" not in value:
            value["type"] = "string"
        else:
            original_type = value["type"]
            if original_type == "float":
                value["format"] = "float"
                value["description"] += " This is a float type value."
            value["type"] = TYPE_MAPPING.get(str(original_type), "string")
        if value["type"] in {"array", "object"}:
            if "properties" in value:
                value["properties"] = _cast_properties(value["properties"])
            elif "items" in value and isinstance(value["items"], dict):
                items = value["items"]
                items["type"] = TYPE_MAPPING[items["type"]]
                if items["type"] == "array" and "items" in items:
                    items["items"]["type"] = TYPE_MAPPING[items["items"]["type"]]
                elif items["type"] == "object" and "properties" in items:
                    items["properties"] = _cast_properties(items["properties"])
    return output


def _convert_tools(functions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for original in functions:
        function = copy.deepcopy(dict(original))
        name = function.get("name")
        parameters = function.get("parameters")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(parameters, dict)
            or not isinstance(parameters.get("properties"), dict)
        ):
            raise BfclSmokeError("BFCL function schema is invalid")
        function["name"] = re.sub(r"\.", "_", name)
        parameters["type"] = "object"
        parameters["properties"] = _cast_properties(parameters["properties"])
        tools.append({"type": "function", "function": function})
    return tools


def _load_python_ast_checker(
    root: Path, *, underscore_to_dot: bool = True
) -> tuple[types.ModuleType, str]:
    checker_path = root / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
    checker_sha256 = dev_smoke._sha256_file(checker_path)
    root_string = str(root.resolve())
    model_config_name = "bfcl_eval.constants.model_config"
    java_name = (
        "bfcl_eval.eval_checker.ast_eval.type_convertor.java_type_converter"
    )
    js_name = "bfcl_eval.eval_checker.ast_eval.type_convertor.js_type_converter"
    model_config = types.ModuleType(model_config_name)
    model_config.MODEL_CONFIG_MAPPING = {
        MODEL_ID: types.SimpleNamespace(underscore_to_dot=underscore_to_dot)
    }
    java_module = types.ModuleType(java_name)
    java_module.java_type_converter = lambda value, _expected: value
    js_module = types.ModuleType(js_name)
    js_module.js_type_converter = lambda value, _expected: value
    previous_modules = {
        name: value
        for name, value in sys.modules.items()
        if name == "bfcl_eval" or name.startswith("bfcl_eval.")
    }
    inserted_path = root_string not in sys.path
    if inserted_path:
        sys.path.insert(0, root_string)
    sys.modules[model_config_name] = model_config
    sys.modules[java_name] = java_module
    sys.modules[js_name] = js_module
    try:
        module_name = "dg10_frozen_bfcl_ast_checker"
        spec = importlib.util.spec_from_file_location(module_name, checker_path)
        if spec is None or spec.loader is None:
            raise BfclSmokeError("cannot load BFCL AST checker")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name in tuple(sys.modules):
            if name == "bfcl_eval" or name.startswith("bfcl_eval."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        if inserted_path:
            sys.path.remove(root_string)
    if not callable(getattr(module, "ast_checker", None)):
        raise BfclSmokeError("BFCL AST checker entrypoint is absent")
    return module, checker_sha256


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BfclSmokeError(f"{label} is invalid")
    return value


class LocalBfclClient:
    def __init__(self, base_url: str, identity_report: Path, timeout: float) -> None:
        try:
            verified = dev_smoke.LocalVllmClient(base_url, identity_report, timeout)
        except dev_smoke.DevSmokeError as exc:
            raise BfclSmokeError(str(exc)) from exc
        self.base_url = verified.base_url
        self.timeout = timeout
        self.max_model_len = verified.max_model_len
        self.identity_evidence = dict(verified.identity_evidence)
        self.tokenizer_requests = 0

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
    ) -> BfclCompletion:
        self.tokenizer_requests += 1
        try:
            prompt_tokens = vllm_local_ab._tokenize(
                self.base_url, messages, tools, timeout=self.timeout
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise BfclSmokeError("BFCL tokenizer request failed") from exc
        if prompt_tokens > self.max_model_len:
            raise BfclSmokeError("BFCL request exceeds frozen vLLM max_model_len")
        payload = {
            "model": MODEL_ID,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
            "seed": 20260821,
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "cache_salt": dev_smoke._sha256_bytes(
                f"dg10-bfcl-dev-smoke:{request_key}".encode()
            ),
        }
        started = time.perf_counter()
        try:
            response, headers = vllm_local_ab._post_json(
                self.base_url,
                "/v1/chat/completions",
                payload,
                timeout=self.timeout,
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise BfclSmokeError("BFCL completion request failed") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        native_id = response.get("id")
        choices = response.get("choices")
        usage_value = response.get("usage")
        if (
            not isinstance(native_id, str)
            or vllm_local_ab._NATIVE_ID.fullmatch(native_id) is None
            or response.get("model") != MODEL_ID
            or not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
            or choices[0].get("finish_reason") not in {"stop", "tool_calls"}
            or not isinstance(choices[0].get("message"), dict)
            or not isinstance(usage_value, dict)
        ):
            raise BfclSmokeError("BFCL native completion envelope is invalid")
        choice = choices[0]
        message = choice["message"]
        finish_reason = str(choice["finish_reason"])
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise BfclSmokeError("BFCL native tool_calls is invalid")
        model_responses: list[Mapping[str, str]] = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict) or not isinstance(
                tool_call.get("function"), dict
            ):
                raise BfclSmokeError("BFCL native tool call envelope is invalid")
            function = tool_call["function"]
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, str):
                raise BfclSmokeError("BFCL native tool call fields are invalid")
            model_responses.append({name: arguments})
        if bool(model_responses) != (finish_reason == "tool_calls"):
            raise BfclSmokeError("BFCL finish reason and tool calls disagree")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise BfclSmokeError("BFCL native content is invalid")
        prompt_usage = _nonnegative_int(usage_value.get("prompt_tokens"), "prompt usage")
        output_usage = _nonnegative_int(
            usage_value.get("completion_tokens"), "completion usage"
        )
        total_usage = _nonnegative_int(usage_value.get("total_tokens"), "total usage")
        if (
            prompt_usage != prompt_tokens
            or output_usage > MAX_OUTPUT_TOKENS
            or total_usage != prompt_usage + output_usage
        ):
            raise BfclSmokeError("BFCL tokenizer/native usage mismatch")
        usage = {"input_tokens": prompt_usage, "output_tokens": output_usage}
        receipt = {
            "response_id": native_id,
            "header_request_id": headers.get("x-request-id"),
            "model": MODEL_ID,
            "finish_reason": finish_reason,
            "usage": usage,
            "tool_calls_sha256": dev_smoke._json_sha256(model_responses),
        }
        return BfclCompletion(
            native_request_id=native_id,
            finish_reason=finish_reason,
            model_responses=tuple(model_responses),
            content=content,
            usage=usage,
            latency_ms=latency_ms,
            native_receipt_sha256=dev_smoke._json_sha256(receipt),
            response_sha256=dev_smoke._json_sha256(response),
        )


def _decode_model_responses(
    responses: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for response in responses:
        if len(response) != 1:
            raise BfclSmokeError("BFCL model response must contain one function name")
        name, arguments = next(iter(response.items()))
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise BfclSmokeError("BFCL model arguments are not JSON") from exc
        if not isinstance(value, dict):
            raise BfclSmokeError("BFCL model arguments must decode to an object")
        decoded.append({name: value})
    return decoded


def _score(
    case: BfclCase,
    responses: Sequence[Mapping[str, str]],
    checker: types.ModuleType,
    *,
    normalize_dots: bool = True,
) -> dict[str, Any]:
    decoded = _decode_model_responses(responses)
    actual_names = sorted(name for item in decoded for name in item)
    if case.category == "irrelevance":
        valid = not decoded
        return {
            "official_checker_lane": "BFCL_RELEVANCE_FILE_RUNNER_EQUIVALENT_NO_CALL_BRANCH",
            "official_checker_valid": valid,
            "tool_selection_correct": valid,
            "argument_correctness": None,
            "no_call_correct": valid,
            "invalid_tool_call": bool(decoded),
            "actual_function_names_sha256": dev_smoke._json_sha256(actual_names),
            "expected_function_names_sha256": dev_smoke._json_sha256([]),
            "checker_error_type": None if valid else "irrelevance_error:decoder_success",
        }
    if case.ground_truth is None:
        raise BfclSmokeError("non-irrelevance BFCL case has no ground truth")
    expected_names = sorted(
        (re.sub(r"\.", "_", name) if normalize_dots else name)
        for answer in case.ground_truth
        for name in answer
    )
    result = checker.ast_checker(
        list(case.functions),
        decoded,
        list(case.ground_truth),
        checker.Language.PYTHON,
        case.category,
        MODEL_ID,
    )
    if not isinstance(result, dict) or not isinstance(result.get("valid"), bool):
        raise BfclSmokeError("BFCL AST checker returned an invalid result")
    valid = bool(result["valid"])
    selection_correct = actual_names == expected_names
    return {
        "official_checker_lane": "BFCL_OFFICIAL_AST_CHECKER_PYTHON_PATH",
        "official_checker_valid": valid,
        "tool_selection_correct": selection_correct,
        "argument_correctness": valid if selection_correct else False,
        "no_call_correct": None,
        "invalid_tool_call": any(
            name
            not in (
                {tool["function"]["name"] for tool in _convert_tools(case.functions)}
                if normalize_dots
                else {str(function["name"]) for function in case.functions}
            )
            for name in actual_names
        ),
        "actual_function_names_sha256": dev_smoke._json_sha256(actual_names),
        "expected_function_names_sha256": dev_smoke._json_sha256(expected_names),
        "checker_error_type": result.get("error_type"),
    }


def run_smoke(
    *,
    dataset_lock_path: Path,
    plan_path: Path,
    bfcl_root: Path,
    case_id: str,
    client: BfclClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    case, plan, input_evidence = _load_case(
        dataset_lock_path=dataset_lock_path.resolve(),
        plan_path=plan_path.resolve(),
        bfcl_root=bfcl_root.resolve(),
        case_id=case_id,
    )
    checker, checker_sha256 = _load_python_ast_checker(bfcl_root.resolve())
    if checker_sha256 != input_evidence["official_ast_checker_sha256"]:
        raise BfclSmokeError("loaded BFCL AST checker differs from frozen input")
    tools = _convert_tools(case.functions)
    run_id = f"dg10-bfcl-dev-smoke-{DATE}-{uuid4().hex[:12]}"
    completion = client.complete(
        case.messages,
        tools,
        request_key=f"{run_id}:{case.case_id}",
    )
    score = _score(case, completion.model_responses, checker)
    ended = datetime.now(UTC)
    record = {
        "run_id": run_id,
        "case_id": case.case_id,
        "source_case_id": case.source_case_id,
        "category": case.category,
        "model_id": MODEL_ID,
        "native_calls": [
            {
                "native_request_id": completion.native_request_id,
                "model_id": MODEL_ID,
                "planned_role": "BFCL_FUNCTION_SELECTION",
                "terminal": True,
                "finish_reason": completion.finish_reason,
                "usage": dict(completion.usage),
                "latency_ms": round(completion.latency_ms, 3),
                "native_receipt_sha256": completion.native_receipt_sha256,
            }
        ],
        "status": "TERMINAL_LOCAL_VLLM_BFCL_SINGLE_TURN_DEV_SMOKE",
        "usage": {
            **dict(completion.usage),
            "model_rounds": 1,
            "mcp_rounds": 0,
            "hidden_or_extra_model_calls": 0,
        },
        "latency_ms": round(completion.latency_ms, 3),
        "prompt_sha256": dev_smoke._json_sha256(case.messages),
        "tool_schema_sha256": dev_smoke._json_sha256(tools),
        "trace": {
            "protocol": "LOCAL_VLLM_PROTOCOL_BFCL_OFFICIAL_LOCAL_CHECKERS",
            "native_bfcl_tools_presented": len(tools),
            "native_function_call_count": len(completion.model_responses),
            "mcp_called": False,
            "mcp_transport_claim": False,
            "hidden_or_extra_model_calls": 0,
            "response_sha256": completion.response_sha256,
        },
        "answer_record": {
            "ground_truth_sha256": (
                dev_smoke._json_sha256(case.ground_truth)
                if case.ground_truth is not None
                else None
            ),
            "model_responses_sha256": dev_smoke._json_sha256(
                completion.model_responses
            ),
            "raw_prompt_in_report": False,
            "raw_function_schemas_in_report": False,
            "raw_ground_truth_in_report": False,
            "raw_model_response_in_report": False,
            **score,
        },
    }
    report = {
        "schema": "milai.dg10.bfcl-v4-local-dev-smoke.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "BFCL_LOCAL_NON_LIVE_SINGLE_TURN_DEV_SMOKE_COMPLETE_NOT_CALIBRATION",
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
        "model_id": MODEL_ID,
        "identity": dict(client.identity_evidence),
        "inputs": {
            **input_evidence,
            "bfcl_plan_lane_contract_sha256": dev_smoke._json_sha256(
                plan["lane_contract"]
            ),
        },
        "execution": {
            "selected_dev_case_id": case.case_id,
            "selected_category": case.category,
            "single_turn": True,
            "native_model_rounds": 1,
            "mcp_rounds": 0,
            "retry_model_calls": 0,
            "hidden_or_extra_model_calls": 0,
            "tool_choice": "auto",
            "temperature": 0,
            "seed": 20260821,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "record": record,
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
            "latency_ms_mean": round(mean([completion.latency_ms]), 3),
        },
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-03": "NO_GO_SINGLE_CASE_SMOKE_NOT_216_CASE_DEV_CALIBRATION",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "single_turn_smoke": "COMPLETE",
            "contract_ambiguity": "REVIEW_REQUIRED",
        },
        "known_limits": [
            "This is one BFCL dev case, not the 216-case calibration or release test.",
            "Only Python single-turn and irrelevance/no-call paths are implemented by this smoke runner.",
            "The Python AST checker executes frozen official checker bytes with unused Java/JavaScript converter imports stubbed; no checker logic on the Python path is replaced.",
            "This run does not execute MiLAi memory arms and cannot prove MCP transport behavior.",
            "The broad every-public-case three-arm contract wording remains review-required.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.bfcl-v4-local-dev-smoke-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_TOOL_SCHEMA_LABEL_AND_MODEL_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "record": {
            "case_id": case.case_id,
            "source_case_id": case.source_case_id,
            "category": case.category,
            "messages": list(case.messages),
            "functions": list(case.functions),
            "ground_truth": case.ground_truth,
            "model_responses": list(completion.model_responses),
            "model_content": completion.content,
            "score": score,
        },
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one BFCL V4 local Python single-turn/no-call dev smoke"
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
        raise BfclSmokeError(
            "real model calls require --execute-local-vllm and exact --data-boundary-ack"
        )
    try:
        capture_directory = dev_smoke._validate_capture_directory(
            args.capture_directory
        )
    except dev_smoke.DevSmokeError as exc:
        raise BfclSmokeError(str(exc)) from exc
    client = LocalBfclClient(args.base_url, args.identity_report, args.timeout)
    report, sidecar = run_smoke(
        dataset_lock_path=args.dataset_lock,
        plan_path=args.plan,
        bfcl_root=args.bfcl_root,
        case_id=args.case_id,
        client=client,
    )
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
