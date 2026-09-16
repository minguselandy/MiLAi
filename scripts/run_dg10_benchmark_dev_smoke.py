from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
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
from scripts import run_dg10_benchmark_adapter_contract as adapter_contract

DATE = "2026-08-21"
CANDIDATE = "candidate.4"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
SUPPORTED_ARMS = ("NO_MEMORY", "NAIVE_RAG")
DATA_BOUNDARY_ACK = "dev-benchmark-labels-hashed-only"
IDENTITY_REPORT = ROOT / "docs/reports/DG-10-vllm-local-identity-2026-08-20.json"
IDENTITY_SHA256 = "0463fff90754f54c887ed79e54b5db5593b1860cf593c4a89a66c1828eaa3f0e"
DEFAULT_ADAPTER_REPORT = (
    ROOT / f"docs/reports/DG-10-benchmark-adapter-contract-candidate.4-{DATE}.json"
)
DEFAULT_CALIBRATION_PLAN = (
    ROOT / f"docs/reports/DG-10-benchmark-calibration-plan-candidate.4-{DATE}.json"
)
DEFAULT_LONGMEMEVAL_ROOT = WORKSPACE_ROOT / "benchmarks/LongMemEval"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-dev-smoke-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = WORKSPACE_ROOT / "evidence/dg10-benchmark-dev-smoke"
MAX_MEMORY_CONTEXT_TOKENS = 512
MAX_INITIAL_MEMORY_CHARACTERS = 32_000
MAX_OUTPUT_TOKENS = 256
RETRIEVAL_K = 1
_WORD = re.compile(r"\w+", re.UNICODE)


class DevSmokeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    source_case_id: str
    dataset: str
    category: str
    question: str
    answers: tuple[str, ...]
    sessions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    native_request_id: str
    usage: Mapping[str, int | None]
    latency_ms: float
    native_receipt_sha256: str
    finish_reason: str = "stop"


class CompletionClient(Protocol):
    tokenizer_requests: int
    max_model_len: int
    identity_evidence: Mapping[str, Any]

    def count_tokens(self, messages: Sequence[Mapping[str, Any]]) -> int: ...

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
        expected_prompt_tokens: int,
    ) -> CompletionResult: ...


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DevSmokeError(f"invalid JSON file: {path}") from exc


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DevSmokeError(f"{label} must be an object")
    return value


def _load_contracts(
    adapter_report_path: Path, calibration_plan_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    adapter = _require_object(_load_json(adapter_report_path), "adapter report")
    calibration = _require_object(_load_json(calibration_plan_path), "calibration plan")
    if (
        adapter.get("schema") != "milai.dg10.benchmark-adapter-contract.v1"
        or adapter.get("status") != "ADAPTER_CONTRACT_CANDIDATE_REVIEW_REQUIRED"
        or adapter.get("test_access_authorized") is not False
        or adapter.get("quality_thresholds_frozen") is not False
    ):
        raise DevSmokeError("adapter report boundary mismatch")
    if (
        calibration.get("schema") != "milai.dg10.benchmark-calibration-plan.v1"
        or calibration.get("status") != "CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
        or calibration.get("test_access_authorized") is not False
        or calibration.get("quality_thresholds_frozen") is not False
    ):
        raise DevSmokeError("calibration plan boundary mismatch")
    inputs = _require_object(calibration.get("inputs"), "calibration inputs")
    if inputs.get("adapter_contract_sha256") != _json_sha256(adapter):
        raise DevSmokeError("calibration-to-adapter digest mismatch")
    if adapter.get("generation_contract") != adapter_contract._generation_contract():
        raise DevSmokeError("generation contract drift")
    if adapter.get("prompt_templates_sha256") != _json_sha256(
        adapter_contract._prompt_templates()
    ):
        raise DevSmokeError("prompt template contract drift")
    split = _require_object(calibration.get("dev_split"), "dev split")
    dev_ids = split.get("dev_case_ids")
    if (
        not isinstance(dev_ids, list)
        or not dev_ids
        or any(not isinstance(item, str) for item in dev_ids)
        or dev_ids != sorted(set(dev_ids))
        or split.get("dev_case_count") != len(dev_ids)
        or split.get("dev_case_ids_sha256") != _json_sha256(dev_ids)
        or not isinstance(split.get("dev_fraction"), (int, float))
        or float(split["dev_fraction"]) > 0.10
    ):
        raise DevSmokeError("calibration dev split drift")
    expected_schedule = [
        {"case_id": case_id, "order": list(adapter_contract._latin_square_order(case_id))}
        for case_id in dev_ids
    ]
    schedule = _require_object(calibration.get("schedule"), "calibration schedule")
    if schedule.get("dev_case_arm_schedule_sha256") != _json_sha256(expected_schedule):
        raise DevSmokeError("calibration Latin-square schedule drift")
    return adapter, calibration


def _answer_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value,)
    if isinstance(value, int) and not isinstance(value, bool):
        return (str(value),)
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    ):
        return tuple(value)
    raise DevSmokeError("LongMemEval answer is not a non-empty string/list")


def _session_text(value: object) -> str:
    if not isinstance(value, list):
        raise DevSmokeError("LongMemEval session must be a message list")
    lines: list[str] = []
    for message in value:
        if not isinstance(message, dict):
            raise DevSmokeError("LongMemEval message must be an object")
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise DevSmokeError("LongMemEval message fields are invalid")
        lines.append(f"{role}: {content}")
    if not lines:
        raise DevSmokeError("LongMemEval session is empty")
    return "\n".join(lines)


def _load_longmemeval_cases(
    root: Path, calibration: Mapping[str, Any], case_limit: int
) -> tuple[list[BenchmarkCase], dict[str, Any]]:
    source = root / "data/longmemeval_s_cleaned.json"
    rows = _load_json(source)
    if not isinstance(rows, list):
        raise DevSmokeError("LongMemEval cleaned dataset must be a list")
    split = _require_object(calibration.get("dev_split"), "dev split")
    planned_dev = [
        item
        for item in split["dev_case_ids"]
        if isinstance(item, str) and item.startswith("longmemeval:")
    ]
    per_dataset = _require_object(split.get("per_dataset"), "per-dataset split")
    lme_split = _require_object(
        per_dataset.get("LONGMEMEVAL_CLEANED_500"), "LongMemEval dev split"
    )
    if (
        lme_split.get("dev") != len(planned_dev)
        or lme_split.get("dev_case_ids_sha256") != _json_sha256(planned_dev)
        or case_limit <= 0
        or case_limit > len(planned_dev)
    ):
        raise DevSmokeError("LongMemEval dev selection boundary mismatch")
    selected = set(planned_dev[:case_limit])
    all_source_ids: list[str] = []
    cases: dict[str, BenchmarkCase] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DevSmokeError(f"LongMemEval row {index} must be an object")
        source_id = row.get("question_id")
        if not isinstance(source_id, str) or not source_id:
            raise DevSmokeError("LongMemEval source case ID is invalid")
        all_source_ids.append(source_id)
        case_id = f"longmemeval:{source_id}"
        if case_id not in selected:
            continue
        question = row.get("question")
        category = row.get("question_type")
        session_ids = row.get("haystack_session_ids")
        sessions = row.get("haystack_sessions")
        if (
            not isinstance(question, str)
            or not question.strip()
            or not isinstance(category, str)
            or not category
            or not isinstance(session_ids, list)
            or not isinstance(sessions, list)
            or len(session_ids) != len(sessions)
            or any(not isinstance(item, str) or not item for item in session_ids)
        ):
            raise DevSmokeError("LongMemEval selected case fields are invalid")
        cases[case_id] = BenchmarkCase(
            case_id=case_id,
            source_case_id=source_id,
            dataset="LONGMEMEVAL_CLEANED_500",
            category=category,
            question=question,
            answers=_answer_values(row.get("answer")),
            sessions=tuple(
                (str(session_id), _session_text(session))
                for session_id, session in zip(session_ids, sessions, strict=True)
            ),
        )
    if len(all_source_ids) != len(set(all_source_ids)):
        raise DevSmokeError("LongMemEval duplicate source case IDs")
    if lme_split.get("total") != len(all_source_ids) or set(cases) != selected:
        raise DevSmokeError("LongMemEval dataset or selected-case coverage drift")
    ordered = [cases[case_id] for case_id in planned_dev[:case_limit]]
    return ordered, {
        "path_class": "REPO_EXTERNAL_PUBLIC_BENCHMARK_INPUT",
        "sha256": _sha256_file(source),
        "size": source.stat().st_size,
        "total_case_count": len(all_source_ids),
        "selected_dev_case_count": len(ordered),
    }


def _terms(text: str) -> Counter[str]:
    return Counter(token.casefold() for token in _WORD.findall(text) if len(token) > 1)


def _retrieve(case: BenchmarkCase, k: int = RETRIEVAL_K) -> tuple[str, list[str]]:
    query = _terms(case.question)
    ranked: list[tuple[int, str, str]] = []
    for session_id, text in case.sessions:
        session_terms = _terms(text)
        overlap = sum(min(count, session_terms.get(token, 0)) for token, count in query.items())
        ranked.append((-overlap, session_id, text))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = ranked[:k]
    memory = "\n\n".join(
        f"[session_id={session_id}]\n{text}" for _score, session_id, text in selected
    )
    return memory[:MAX_INITIAL_MEMORY_CHARACTERS], [item[1] for item in selected]


def _messages(case: BenchmarkCase, memory: str) -> list[dict[str, str]]:
    system = adapter_contract._prompt_templates()["system_template"]
    memory_block = memory if memory else "[none supplied]"
    user = (
        f"Dataset: {case.dataset}\nCase: {case.case_id}\nQuestion:\n{case.question}\n\n"
        f"Memory evidence:\n{memory_block}\n\nReturn only the final answer text."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _fit_memory(
    client: CompletionClient, case: BenchmarkCase, memory: str
) -> tuple[str, int]:
    baseline = client.count_tokens(_messages(case, ""))
    if not memory:
        return "", 0
    high = len(memory)
    low = 1
    best = ""
    best_delta = 0
    while low <= high:
        midpoint = (low + high) // 2
        candidate = memory[:midpoint].rstrip()
        count = client.count_tokens(_messages(case, candidate))
        delta = count - baseline
        if delta <= MAX_MEMORY_CONTEXT_TOKENS:
            best = candidate
            best_delta = max(0, delta)
            low = midpoint + 1
        else:
            high = midpoint - 1
    if not best:
        raise DevSmokeError("retrieved memory cannot fit the 512-token standard budget")
    return best, best_delta


def _parse_answer(text: str) -> str:
    stripped = text.strip()
    marker = "\\boxed{"
    start = stripped.rfind(marker)
    if start < 0:
        return stripped
    index = start + len(marker)
    depth = 1
    for position in range(index, len(stripped)):
        character = stripped[position]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return stripped[index:position].strip()
    return stripped


def _normalize_answer(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = "".join(" " if unicodedata.category(char).startswith("P") else char for char in value)
    tokens = [token for token in value.split() if token not in {"a", "an", "the"}]
    return " ".join(tokens)


def _f1(prediction: str, answer: str) -> float:
    prediction_tokens = _normalize_answer(prediction).split()
    answer_tokens = _normalize_answer(answer).split()
    if not prediction_tokens or not answer_tokens:
        return float(prediction_tokens == answer_tokens)
    common = Counter(prediction_tokens) & Counter(answer_tokens)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(prediction_tokens)
    recall = overlap / len(answer_tokens)
    return 2 * precision * recall / (precision + recall)


def _score(prediction: str, answers: Sequence[str]) -> dict[str, float | int | str]:
    exact = max(int(_normalize_answer(prediction) == _normalize_answer(answer)) for answer in answers)
    f1 = max(_f1(prediction, answer) for answer in answers)
    return {
        "scorer": "DG10_LOCAL_DEV_SMOKE_NORMALIZED_EM_F1_V1_NOT_OFFICIAL_SCORE",
        "exact_match": exact,
        "normalized_f1": round(f1, 6),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _aggregates(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["dataset"]), str(record["arm"]))].append(record)
    result: dict[str, Any] = {}
    for (dataset, arm), group in sorted(grouped.items()):
        latencies = [float(item["latency_ms"]) for item in group]
        exact = [int(item["answer_record"]["exact_match"]) for item in group]
        f1 = [float(item["answer_record"]["normalized_f1"]) for item in group]
        truncated = [bool(item["answer_record"]["output_truncated"]) for item in group]
        result[f"{dataset}/{arm}"] = {
            "case_count": len(group),
            "exact_match_mean": round(mean(exact), 6),
            "normalized_f1_mean": round(mean(f1), 6),
            "truncated_output_count": sum(truncated),
            "truncated_output_rate": round(mean(truncated), 6),
            "input_tokens": sum(int(item["usage"]["input_tokens"]) for item in group),
            "output_tokens": sum(int(item["usage"]["output_tokens"]) for item in group),
            "latency_ms": {
                "mean": round(mean(latencies), 3),
                "p50_nearest_rank": _percentile(latencies, 0.50),
                "p95_nearest_rank": _percentile(latencies, 0.95),
            },
        }
    return result


def _validate_benchmark_completion(
    response: Mapping[str, Any],
    headers: Mapping[str, str],
    *,
    expected_prompt_tokens: int,
    max_output_tokens: int,
) -> tuple[str, dict[str, int | None], str, str, str]:
    """Validate a benchmark answer while preserving capped terminal outputs.

    The exact A/B capture remains stop-only. Benchmark quality evaluation also
    needs to retain a terminal ``length`` response and score it as the observed,
    truncated answer instead of losing the request receipt.
    """
    request_id = response.get("id")
    if (
        not isinstance(request_id, str)
        or vllm_local_ab._NATIVE_ID.fullmatch(request_id) is None
    ):
        raise vllm_local_ab.LocalVllmCaptureError(
            "vLLM native request ID is invalid"
        )
    if response.get("model") != MODEL_ID:
        raise vllm_local_ab.LocalVllmCaptureError("vLLM response model drift")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise vllm_local_ab.LocalVllmCaptureError(
            "vLLM response choice count drift"
        )
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") not in {
        "stop",
        "length",
    }:
        raise vllm_local_ab.LocalVllmCaptureError(
            "vLLM benchmark response is not terminal stop or length"
        )
    finish_reason = str(choice["finish_reason"])
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise vllm_local_ab.LocalVllmCaptureError("vLLM response content is absent")
    tool_calls = message.get("tool_calls")
    if tool_calls is not None and tool_calls != []:
        raise vllm_local_ab.LocalVllmCaptureError(
            "vLLM unexpectedly emitted a tool call"
        )
    usage_value = response.get("usage")
    if not isinstance(usage_value, dict):
        raise vllm_local_ab.LocalVllmCaptureError("vLLM usage is absent")
    prompt_tokens = vllm_local_ab._nonnegative_int(
        usage_value.get("prompt_tokens"), "prompt usage"
    )
    completion_tokens = vllm_local_ab._nonnegative_int(
        usage_value.get("completion_tokens"), "completion usage"
    )
    total_tokens = vllm_local_ab._nonnegative_int(
        usage_value.get("total_tokens"), "total usage"
    )
    if prompt_tokens != expected_prompt_tokens:
        raise vllm_local_ab.LocalVllmCaptureError(
            "pre-count differs from vLLM prompt usage"
        )
    if (
        completion_tokens > max_output_tokens
        or total_tokens != prompt_tokens + completion_tokens
        or (finish_reason == "length" and completion_tokens != max_output_tokens)
    ):
        raise vllm_local_ab.LocalVllmCaptureError(
            "vLLM usage arithmetic, output cap, or length termination failed"
        )
    usage: dict[str, int | None] = {
        "input_tokens": prompt_tokens,
        "cached_input_tokens": 0,
        "output_tokens": completion_tokens,
        "reasoning_tokens": None,
    }
    native_receipt = {
        "response_id": request_id,
        "header_request_id": headers.get("x-request-id"),
        "model": MODEL_ID,
        "finish_reason": finish_reason,
        "usage": usage,
    }
    return (
        str(message["content"]),
        usage,
        request_id,
        vllm_local_ab.identity.sha256_bytes(
            vllm_local_ab.identity.canonical_bytes(native_receipt)
        ),
        finish_reason,
    )


class LocalVllmClient:
    def __init__(self, base_url: str, identity_report: Path, timeout: float) -> None:
        self.timeout = timeout
        try:
            self.base_url = vllm_local_ab.identity.strict_base_url(base_url)
            identity = vllm_local_ab._load_identity(identity_report.resolve(), IDENTITY_SHA256)
            binding = _require_object(identity.get("binding"), "vLLM identity binding")
            service = _require_object(binding.get("service"), "vLLM service binding")
            if service.get("base_url") != self.base_url or service.get("served_model_id") != MODEL_ID:
                raise DevSmokeError("requested endpoint differs from frozen vLLM identity")
            vllm_local_ab._live_check(binding)
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise DevSmokeError("frozen local vLLM identity check failed") from exc
        self.max_model_len = int(service["max_model_len"])
        self.tokenizer_requests = 0
        self.identity_evidence = {
            "identity_report_sha256": IDENTITY_SHA256,
            "binding_sha256": identity["binding_sha256"],
            "base_url_class": "LOOPBACK_LOCAL_VLLM",
            "served_model_id": MODEL_ID,
            "vllm_version": service["vllm_version"],
            "max_model_len": self.max_model_len,
            "vllm_lifecycle_mutated": False,
        }

    def count_tokens(self, messages: Sequence[Mapping[str, Any]]) -> int:
        self.tokenizer_requests += 1
        try:
            return vllm_local_ab._tokenize(
                self.base_url, messages, [], timeout=self.timeout
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise DevSmokeError("local vLLM tokenizer request failed") from exc

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        request_key: str,
        expected_prompt_tokens: int,
    ) -> CompletionResult:
        payload = {
            "model": MODEL_ID,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
            "seed": 20260821,
            "tool_choice": "none",
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "cache_salt": _sha256_bytes(f"dg10-dev-smoke:{request_key}".encode()),
        }
        started = time.perf_counter()
        try:
            response, headers = vllm_local_ab._post_json(
                self.base_url,
                "/v1/chat/completions",
                payload,
                timeout=self.timeout,
            )
            latency_ms = (time.perf_counter() - started) * 1000
            text, usage, native_id, receipt_sha256, finish_reason = (
                _validate_benchmark_completion(
                response,
                headers,
                expected_prompt_tokens=expected_prompt_tokens,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
            )
        except vllm_local_ab.LocalVllmCaptureError as exc:
            raise DevSmokeError("local vLLM completion failed") from exc
        return CompletionResult(
            text=text,
            native_request_id=native_id,
            usage=usage,
            latency_ms=latency_ms,
            native_receipt_sha256=receipt_sha256,
            finish_reason=finish_reason,
        )


def run_smoke(
    *,
    adapter_report_path: Path,
    calibration_plan_path: Path,
    longmemeval_root: Path,
    case_limit: int,
    arms: Sequence[str],
    client: CompletionClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    requested_arms = tuple(arms)
    if (
        not requested_arms
        or len(set(requested_arms)) != len(requested_arms)
        or any(arm not in (*SUPPORTED_ARMS, "MILAI_MCP") for arm in requested_arms)
    ):
        raise DevSmokeError("requested smoke arms are invalid")
    if "MILAI_MCP" in requested_arms:
        raise DevSmokeError("MILAI_MCP is not implemented by the partial dev-smoke runner")
    adapter, calibration = _load_contracts(
        adapter_report_path.resolve(), calibration_plan_path.resolve()
    )
    cases, dataset_evidence = _load_longmemeval_cases(
        longmemeval_root.resolve(), calibration, case_limit
    )
    run_id = f"dg10-dev-smoke-{DATE}-{uuid4().hex[:12]}"
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    native_ids: set[str] = set()
    for case in cases:
        scheduled = adapter_contract._latin_square_order(case.case_id)
        for arm in (item for item in scheduled if item in requested_arms):
            if arm == "NAIVE_RAG":
                raw_memory, evidence_ids = _retrieve(case)
                memory, memory_tokens = _fit_memory(client, case, raw_memory)
            else:
                memory = ""
                memory_tokens = 0
                evidence_ids = []
            messages = _messages(case, memory)
            prompt_tokens = client.count_tokens(messages)
            if prompt_tokens > client.max_model_len:
                raise DevSmokeError("smoke prompt exceeds frozen vLLM max_model_len")
            request_key = f"{run_id}:{case.case_id}:{arm}"
            completion = client.complete(
                messages,
                request_key=request_key,
                expected_prompt_tokens=prompt_tokens,
            )
            if completion.native_request_id in native_ids:
                raise DevSmokeError("duplicate native vLLM request ID")
            native_ids.add(completion.native_request_id)
            parsed = _parse_answer(completion.text)
            score = _score(parsed, case.answers)
            usage = {
                "input_tokens": int(completion.usage["input_tokens"] or 0),
                "output_tokens": int(completion.usage["output_tokens"] or 0),
                "model_rounds": 1,
                "mcp_rounds": 0,
                "hidden_or_extra_model_calls": 0,
            }
            records.append(
                {
                    "run_id": run_id,
                    "case_id": case.case_id,
                    "source_case_id": case.source_case_id,
                    "dataset": case.dataset,
                    "category": case.category,
                    "arm": arm,
                    "model_id": MODEL_ID,
                    "planned_model_rounds": adapter_contract.PLANNED_MODEL_ROUNDS[arm],
                    "planned_mcp_calls": adapter_contract.PLANNED_MCP_CALLS[arm],
                    "native_calls": [
                        {
                            "native_request_id": completion.native_request_id,
                            "model_id": MODEL_ID,
                            "planned_role": "ANSWER",
                            "terminal": True,
                            "finish_reason": completion.finish_reason,
                            "usage": {
                                "input_tokens": int(completion.usage["input_tokens"] or 0),
                                "output_tokens": int(completion.usage["output_tokens"] or 0),
                            },
                            "latency_ms": round(completion.latency_ms, 3),
                            "native_receipt_sha256": completion.native_receipt_sha256,
                        }
                    ],
                    "status": (
                        "TERMINAL_LOCAL_VLLM_OUTPUT_TRUNCATED"
                        if completion.finish_reason == "length"
                        else "TERMINAL_LOCAL_VLLM_SMOKE"
                    ),
                    "usage": usage,
                    "latency_ms": round(completion.latency_ms, 3),
                    "prompt_sha256": _json_sha256(messages),
                    "trace": {
                        "latin_square_order": list(scheduled),
                        "retrieval": "NONE" if arm == "NO_MEMORY" else "LOCAL_LEXICAL_V1",
                        "retrieval_k": 0 if arm == "NO_MEMORY" else RETRIEVAL_K,
                        "retrieved_evidence_ids": evidence_ids,
                        "retrieved_evidence_ids_sha256": _json_sha256(evidence_ids),
                        "memory_context_sha256": _sha256_bytes(memory.encode()),
                        "memory_context_tokens_attribution": memory_tokens,
                        "mcp_called": False,
                        "hidden_or_extra_model_calls": 0,
                    },
                    "answer_record": {
                        "gold_answers_sha256": _json_sha256(case.answers),
                        "raw_model_output_sha256": _sha256_bytes(completion.text.encode()),
                        "parsed_answer_sha256": _sha256_bytes(parsed.encode()),
                        "raw_question_in_report": False,
                        "raw_gold_answer_in_report": False,
                        "raw_model_output_in_report": False,
                        "output_truncated": completion.finish_reason == "length",
                        **score,
                    },
                }
            )
            raw_records.append(
                {
                    "case_id": case.case_id,
                    "source_case_id": case.source_case_id,
                    "dataset": case.dataset,
                    "category": case.category,
                    "arm": arm,
                    "question": case.question,
                    "gold_answers": list(case.answers),
                    "memory_context": memory,
                    "retrieved_evidence_ids": evidence_ids,
                    "messages": messages,
                    "raw_model_output": completion.text,
                    "parsed_answer": parsed,
                }
            )
    ended = datetime.now(UTC)
    expected_records = len(cases) * len(requested_arms)
    if len(records) != expected_records or len(native_ids) != expected_records:
        raise DevSmokeError("partial smoke denominator or native-ID coverage failed")
    report = {
        "schema": "milai.dg10.benchmark-dev-smoke.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "DEV_SMOKE_PARTIAL_NOT_CALIBRATION",
        "quality_outcome": "CHARACTERIZED_ONLY",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "data_boundary": "PUBLIC_DEV_LABELS_OPENED_RAW_CONTENT_REPO_EXTERNAL_HASHED_ONLY",
        "calibration_dev_labels_opened": True,
        "test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": len(records),
        "local_tokenizer_requests": client.tokenizer_requests,
        "unique_native_request_ids": len(native_ids),
        "hidden_or_extra_model_calls": 0,
        "model_id": MODEL_ID,
        "identity": dict(client.identity_evidence),
        "inputs": {
            "adapter_report_sha256": _sha256_file(adapter_report_path.resolve()),
            "adapter_contract_canonical_sha256": _json_sha256(adapter),
            "calibration_plan_sha256": _sha256_file(calibration_plan_path.resolve()),
            "dataset": dataset_evidence,
        },
        "execution": {
            "selected_dev_case_count": len(cases),
            "selected_dev_case_ids": [case.case_id for case in cases],
            "selected_dev_case_ids_sha256": _json_sha256([case.case_id for case in cases]),
            "arms_executed": list(requested_arms),
            "records": len(records),
            "records_per_case": len(requested_arms),
            "planned_model_rounds_by_executed_arm": {
                arm: adapter_contract.PLANNED_MODEL_ROUNDS[arm]
                for arm in requested_arms
            },
            "planned_mcp_calls_by_executed_arm": {
                arm: adapter_contract.PLANNED_MCP_CALLS[arm]
                for arm in requested_arms
            },
            "retrieval_k_smoke_candidate": RETRIEVAL_K,
            "memory_context_tokens_max": MAX_MEMORY_CONTEXT_TOKENS,
            "generation_contract_sha256": adapter["generation_contract_sha256"],
            "prompt_templates_sha256": adapter["prompt_templates_sha256"],
            "latin_square_dev_schedule_sha256": calibration["schedule"][
                "dev_case_arm_schedule_sha256"
            ],
        },
        "records": records,
        "aggregates": _aggregates(records),
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-02": "NO_GO_PARTIAL_DEV_SMOKE_NOT_THREE_ARM_CALIBRATION",
            "BMG-03": adapter["gate_results"]["BMG-03"],
            "BMG-05": "NO_GO_THRESHOLDS_NOT_FROZEN",
            "dev_smoke": "PARTIAL_TWO_ARM_LOCAL_VLLM_COMPLETE",
        },
        "known_limits": [
            "This is a two-arm, bounded LongMemEval dev smoke; it is not the <=10% three-arm calibration.",
            "MILAI_MCP and LongMemEval-V2 execution are not implemented by this runner.",
            "The local EM/F1 smoke scorer is not the official LongMemEval LLM judge and is not a leaderboard score.",
            "No threshold, retrieval k, test authorization, BMG-02, or BMG-05 gate is frozen or accepted.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.benchmark-dev-smoke-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_MEMORY_LABEL_AND_MODEL_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def _encoded_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise DevSmokeError(f"refusing to overwrite existing evidence: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _validate_capture_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise DevSmokeError("raw capture directory must be outside the MiLAi repository")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a bounded two-arm DG-10 LongMemEval dev smoke against frozen local vLLM"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--adapter-report", type=Path, default=DEFAULT_ADAPTER_REPORT)
    parser.add_argument("--calibration-plan", type=Path, default=DEFAULT_CALIBRATION_PLAN)
    parser.add_argument("--longmemeval-root", type=Path, default=DEFAULT_LONGMEMEVAL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--case-limit", type=int, default=1)
    parser.add_argument("--arms", nargs="+", default=list(SUPPORTED_ARMS))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_local_vllm or args.data_boundary_ack != DATA_BOUNDARY_ACK:
        raise DevSmokeError(
            "real model calls require --execute-local-vllm and exact --data-boundary-ack"
        )
    capture_directory = _validate_capture_directory(args.capture_directory)
    client = LocalVllmClient(args.base_url, args.identity_report, args.timeout)
    report, sidecar = run_smoke(
        adapter_report_path=args.adapter_report,
        calibration_plan_path=args.calibration_plan,
        longmemeval_root=args.longmemeval_root,
        case_limit=args.case_limit,
        arms=args.arms,
        client=client,
    )
    sidecar_raw = _encoded_json(sidecar)
    sidecar_path = capture_directory / f"{report['run_id']}.raw.json"
    _write_new(sidecar_path, sidecar_raw)
    report["repo_external_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": _sha256_bytes(sidecar_raw),
        "size": len(sidecar_raw),
        "mode": "0600",
    }
    report_raw = _encoded_json(report)
    _write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": _sha256_bytes(report_raw),
                "sidecar": str(sidecar_path),
                "sidecar_sha256": _sha256_bytes(sidecar_raw),
                "status": report["status"],
                "local_vllm_requests": report["local_vllm_requests"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
