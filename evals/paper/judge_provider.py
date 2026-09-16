"""Frozen independent local evaluator client for paper scoring."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.paper.identity import sha256_file

MODEL_ID = "Qwen3.5-27B-FP8-INDEPENDENT-EVALUATOR"
BASE_URL = "http://127.0.0.1:7870/v1"
MAX_OUTPUT_TOKENS = 512
PROMPT_TOKEN_BUDGET = 8_192
IDENTITY_PATH = (
    Path(__file__).resolve().parents[2]
    / "var/dg11/paper/freeze/evaluator-identity.json"
)
EXPECTED_IDENTITY_SHA256 = (
    "4b1f0e6410e6413f5bab5227040e8da496732f3183fb0362a7db49685528c196"
)
EXPECTED_IDENTITY_ID = (
    "evaluator:ef81425f4ee0e475edf2d3c2d9520030658127850bb9c46df6474ae2a2fc0b4e"
)
SYSTEM_PROMPT = """You are an expert evaluator assessing AI assistant responses. Your task is to answer a YES/NO evaluation question about a given response.

You must provide your answer in the following JSON format:
{
    "answer": "yes" or "no",
    "confidence": 0.0 to 1.0,
    "explanation": "Brief explanation of your reasoning"
}

Be objective and thorough in your evaluation."""
USER_PROMPT_TEMPLATE = """Please evaluate the following AI response against the evaluation question.

AI RESPONSE TO EVALUATE:
{model_response}

EVALUATION QUESTION:
{evaluation_question}
{context_info}

Provide your evaluation in JSON format with answer (yes/no), confidence (0.0-1.0), and explanation."""
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": ["yes", "no"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "explanation": {"type": "string"},
    },
    "required": ["answer", "confidence", "explanation"],
    "additionalProperties": False,
}
_NATIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,255}")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class JudgeProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedJudge:
    ordinal: int
    logical_request_id: str
    case_id: str
    method_id: str
    criterion_id: str
    evaluation_type: str
    expected_answer: str
    prompt: str
    prompt_tokens: int


@dataclass(frozen=True)
class JudgeCompletion:
    judge_answer: str
    confidence: float
    explanation_sha256: str
    native_request_id: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def prompt_contract() -> dict[str, Any]:
    return {
        "generation": {
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
            "temperature": 0,
            "top_p": 1,
        },
        "judge_schema": JUDGE_SCHEMA,
        "model_id": MODEL_ID,
        "official_memora_system_prompt": SYSTEM_PROMPT,
        "official_memora_user_prompt_template": USER_PROMPT_TEMPLATE,
    }


def prompt_contract_sha256() -> str:
    return hashlib.sha256(_canonical(prompt_contract())).hexdigest()


def stable_seed(logical_request_id: str) -> int:
    return int(hashlib.sha256(logical_request_id.encode()).hexdigest()[:16], 16) & (
        (1 << 63) - 1
    )


def messages(
    *,
    model_response: str,
    evaluation_question: str,
    evaluation_type: str,
    target_item: object | None = None,
) -> list[dict[str, str]]:
    if not model_response or not evaluation_question:
        raise ValueError("judge response and evaluation question are required")
    if evaluation_type not in {"memory_presence", "forgetting_absence"}:
        raise ValueError("unknown Memora evaluation type")
    context_info = ""
    if target_item is not None:
        context_info += f"\nTarget item being evaluated: {target_item}"
    context_info += f"\nEvaluation type: {evaluation_type}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                context_info=context_info,
                evaluation_question=evaluation_question,
                model_response=model_response,
            ),
        },
    ]


def _strict_base_url(value: str) -> str:
    normalized = value.rstrip("/").removesuffix("/v1")
    if normalized not in {"http://127.0.0.1:7870", "http://localhost:7870"}:
        raise JudgeProviderError(
            "paper evaluator must use the frozen independent loopback endpoint"
        )
    return normalized


def _post_json(
    base_url: str,
    path: str,
    payload: Mapping[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], Mapping[str, str]]:
    if path not in {"/tokenize", "/v1/chat/completions"}:
        raise JudgeProviderError("evaluator path is not allowlisted")
    request = urllib.request.Request(
        _strict_base_url(base_url) + path,
        data=_canonical(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
            headers = {key.casefold(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096)
        raise JudgeProviderError(
            f"evaluator HTTP {exc.code}; body_sha256={hashlib.sha256(detail).hexdigest()}"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise JudgeProviderError("independent evaluator request failed") from exc
    if status != 200 or len(raw) > _MAX_RESPONSE_BYTES:
        raise JudgeProviderError("evaluator returned non-200 or oversized response")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeProviderError("evaluator response is not JSON") from exc
    if not isinstance(value, dict):
        raise JudgeProviderError("evaluator response is not an object")
    return value, headers


class FrozenJudgeClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        prompt_token_budget: int = PROMPT_TOKEN_BUDGET,
        identity_path: Path = IDENTITY_PATH,
    ) -> None:
        self.base_url = _strict_base_url(base_url)
        if not 1 <= prompt_token_budget <= 261_632:
            raise ValueError("evaluator prompt token budget is invalid")
        self.prompt_token_budget = prompt_token_budget
        if sha256_file(identity_path) != EXPECTED_IDENTITY_SHA256:
            raise JudgeProviderError("independent evaluator identity artifact drifted")
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JudgeProviderError(
                "independent evaluator identity is invalid"
            ) from exc
        if (
            not isinstance(identity, dict)
            or identity.get("identity_id") != EXPECTED_IDENTITY_ID
            or identity.get("model_id") != MODEL_ID
            or identity.get("planned_endpoint") != BASE_URL
            or identity.get("status") != "FROZEN_PRE_TEST"
        ):
            raise JudgeProviderError("independent evaluator identity drifted")

    def count_messages(self, value: Sequence[Mapping[str, Any]]) -> int:
        response, _headers = _post_json(
            self.base_url,
            "/tokenize",
            {
                "add_generation_prompt": True,
                "add_special_tokens": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": list(value),
                "model": MODEL_ID,
            },
            timeout=30,
        )
        count = response.get("count")
        tokens = response.get("tokens")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
            or not isinstance(tokens, list)
            or len(tokens) != count
            or any(not isinstance(token, int) for token in tokens)
        ):
            raise JudgeProviderError("evaluator tokenizer response is invalid")
        return count

    def prepare(
        self,
        *,
        ordinal: int,
        logical_request_id: str,
        case_id: str,
        method_id: str,
        criterion_id: str,
        evaluation_type: str,
        expected_answer: str,
        model_response: str,
        evaluation_question: str,
    ) -> PreparedJudge:
        prompt_messages = messages(
            model_response=model_response,
            evaluation_question=evaluation_question,
            evaluation_type=evaluation_type,
        )
        prompt_tokens = self.count_messages(prompt_messages)
        if prompt_tokens > self.prompt_token_budget:
            raise JudgeProviderError("evaluator prompt exceeds frozen token budget")
        prompt = _canonical(
            {
                "messages": prompt_messages,
                "prompt_contract_sha256": prompt_contract_sha256(),
            }
        ).decode()
        return PreparedJudge(
            ordinal=ordinal,
            logical_request_id=logical_request_id,
            case_id=case_id,
            method_id=method_id,
            criterion_id=criterion_id,
            evaluation_type=evaluation_type,
            expected_answer=expected_answer,
            prompt=prompt,
            prompt_tokens=prompt_tokens,
        )

    def complete(self, prepared: PreparedJudge) -> JudgeCompletion:
        try:
            envelope = json.loads(prepared.prompt)
        except json.JSONDecodeError as exc:
            raise JudgeProviderError("prepared evaluator prompt is invalid") from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("prompt_contract_sha256") != prompt_contract_sha256()
            or not isinstance(envelope.get("messages"), list)
        ):
            raise JudgeProviderError("prepared evaluator prompt identity drifted")
        response, headers = _post_json(
            self.base_url,
            "/v1/chat/completions",
            {
                "cache_salt": hashlib.sha256(
                    f"milai-dg11-paper-judge:{prepared.logical_request_id}".encode()
                ).hexdigest(),
                "chat_template_kwargs": {"enable_thinking": False},
                "include_reasoning": False,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "messages": envelope["messages"],
                "model": MODEL_ID,
                "response_format": {
                    "json_schema": {
                        "name": "milai_dg11_memora_judgment",
                        "schema": JUDGE_SCHEMA,
                        "strict": True,
                    },
                    "type": "json_schema",
                },
                "seed": stable_seed(prepared.logical_request_id),
                "stream": False,
                "temperature": 0,
                "top_p": 1,
            },
            timeout=240,
        )
        choices = response.get("choices")
        usage = response.get("usage")
        native_id = response.get("id") or headers.get("x-request-id")
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
            or not isinstance(usage, dict)
            or not isinstance(native_id, str)
            or _NATIVE_ID.fullmatch(native_id) is None
        ):
            raise JudgeProviderError("evaluator completion envelope is invalid")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        finish_reason = choices[0].get("finish_reason")
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if (
            not isinstance(content, str)
            or not isinstance(finish_reason, str)
            or not isinstance(prompt_tokens, int)
            or isinstance(prompt_tokens, bool)
            or not isinstance(completion_tokens, int)
            or isinstance(completion_tokens, bool)
            or prompt_tokens != prepared.prompt_tokens
            or completion_tokens <= 0
        ):
            raise JudgeProviderError("evaluator completion usage drifted")
        try:
            judgment = json.loads(content)
        except json.JSONDecodeError as exc:
            raise JudgeProviderError("evaluator content is not strict JSON") from exc
        if (
            not isinstance(judgment, dict)
            or set(judgment) != {"answer", "confidence", "explanation"}
            or judgment.get("answer") not in {"yes", "no"}
            or not isinstance(judgment.get("confidence"), int | float)
            or isinstance(judgment.get("confidence"), bool)
            or not 0 <= float(judgment["confidence"]) <= 1
            or not isinstance(judgment.get("explanation"), str)
        ):
            raise JudgeProviderError("evaluator judgment contract drifted")
        return JudgeCompletion(
            judge_answer=str(judgment["answer"]),
            confidence=float(judgment["confidence"]),
            explanation_sha256=hashlib.sha256(
                str(judgment["explanation"]).encode()
            ).hexdigest(),
            native_request_id=native_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )
