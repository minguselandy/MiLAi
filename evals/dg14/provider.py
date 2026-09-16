"""Matched local-vLLM provider path for DG-14 opened-development runs."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from evals.dg14.ledger import DG14StageEvent, DG14StageLedger
from evals.paper.provider import (
    ANSWER_SCHEMA,
    EXPECTED_PROMPT_CONTRACT_SHA256,
    MAX_OUTPUT_TOKENS,
    MODEL_ID,
    PROMPT_TOKEN_BUDGET,
    PaperProviderError,
    _post_json,
    messages,
    prompt_contract_sha256,
)

_NATIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,255}")


class DG14ProviderError(RuntimeError):
    """Typed failure from the DG-14 common answer provider."""


class ReaderConformanceError(DG14ProviderError):
    """Safe Reader v0.2 failure metadata without response-body retention."""

    def __init__(
        self,
        failure_class: str,
        message: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.metadata = dict(metadata or {})


class JsonPost(Protocol):
    def __call__(
        self,
        base_url: str,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> tuple[dict[str, Any], Mapping[str, str]]: ...


@dataclass(frozen=True, slots=True)
class PromptAccounting:
    prompt_tokens: int
    no_memory_prompt_tokens: int
    memory_tokens: int


@dataclass(frozen=True, slots=True)
class FittedMemory:
    context: str
    accounting: PromptAccounting
    truncated: bool


@dataclass(frozen=True, slots=True)
class ProviderResult:
    answer: str
    answer_sha256: str
    native_request_id: str
    logical_request_id: str
    seed: int
    cache_salt: str
    prompt_sha256: str
    prompt_tokens: int
    no_memory_prompt_tokens: int
    memory_tokens: int
    completion_tokens: int
    finish_reason: str
    context: str
    context_truncated: bool
    tokenizer_calls: int
    tokenize_latency_ms: float
    provider_latency_ms: float
    provider_calls: int = 1
    content_sha256: str = ""
    content_byte_length: int = 0
    response_schema_sha256: str = ""
    sealed_context_tokens: int | None = None
    template_boundary_tokens: int = 0


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def matched_seed(run_id: str, case_id: str, token_budget: int) -> int:
    """Return an arm-independent seed for one matched case/budget cell."""

    if not run_id or not case_id or token_budget <= 0:
        raise ValueError("matched provider seed identity is invalid")
    identity = f"milai-dg14-matched-v1:{run_id}:{case_id}:{token_budget}"
    return int(hashlib.sha256(identity.encode()).hexdigest()[:16], 16) & ((1 << 63) - 1)


def provider_seed(case_id: str, token_budget: int, run_id: str = "dg14-matched") -> int:
    """Convenience alias used by schedule/fairness tests."""

    return matched_seed(run_id, case_id, token_budget)


def logical_request_id(
    run_id: str, case_id: str, method_id: str, token_budget: int
) -> str:
    if not run_id or not case_id or not method_id or token_budget <= 0:
        raise ValueError("provider logical request identity is invalid")
    digest = hashlib.sha256(
        f"{run_id}\0{case_id}\0{method_id}\0{token_budget}".encode()
    ).hexdigest()[:24]
    return f"dg14-{case_id}-{token_budget}-{digest}"


def full_provider_contract(
    *, max_output_tokens: int = MAX_OUTPUT_TOKENS
) -> dict[str, Any]:
    """Bind settings omitted from the older prompt-only contract hash."""

    return {
        "answer_schema": ANSWER_SCHEMA,
        "cache_salt_policy": "sha256(milai-dg14-provider-v1:logical_request_id)",
        "endpoint": "http://127.0.0.1:7860",
        "generation": {
            "chat_template_kwargs": {"enable_thinking": False},
            "include_reasoning": False,
            "max_tokens": max_output_tokens,
            "response_format": "strict-json-schema",
            "stream": False,
            "temperature": 0,
            "top_p": 1,
        },
        "model_id": MODEL_ID,
        "prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
        "prompt_token_budget": PROMPT_TOKEN_BUDGET,
        "seed_policy": "sha256(run_id,case_id,token_budget); method-independent",
    }


def full_provider_contract_sha256(*, max_output_tokens: int = MAX_OUTPUT_TOKENS) -> str:
    return hashlib.sha256(
        _canonical(full_provider_contract(max_output_tokens=max_output_tokens))
    ).hexdigest()


class MatchedVllmProvider:
    """Exact DG-11 prompt/generation contract with corrected matched-arm seeds."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7860",
        *,
        prompt_token_budget: int = PROMPT_TOKEN_BUDGET,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        post_json: JsonPost = _post_json,
    ) -> None:
        normalized = base_url.rstrip("/").removesuffix("/v1")
        if normalized not in {"http://127.0.0.1:7860", "http://localhost:7860"}:
            raise DG14ProviderError("DG-14 provider must be the existing loopback vLLM")
        if not 1 <= prompt_token_budget <= 65_280:
            raise ValueError("prompt token budget exceeds the vLLM context")
        if max_output_tokens not in {256, 500, 512}:
            raise ValueError("Reader output ceiling must be 256, 500, or 512")
        if prompt_contract_sha256() != EXPECTED_PROMPT_CONTRACT_SHA256:
            raise DG14ProviderError("shared answer prompt contract drifted")
        self.base_url = normalized
        self.prompt_token_budget = prompt_token_budget
        self.max_output_tokens = max_output_tokens
        self._post_json = post_json

    def _count_messages(
        self,
        value: Sequence[Mapping[str, Any]],
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        token_budget: int,
        request_id: str,
        ordinal: int,
        ledger: DG14StageLedger | None,
    ) -> tuple[int, float]:
        started = time.perf_counter()
        tokenizer_id = f"{request_id}:tokenize:{ordinal:03d}"
        try:
            response, _headers = self._post_json(
                self.base_url,
                "/tokenize",
                {
                    "model": MODEL_ID,
                    "messages": list(value),
                    "add_generation_prompt": True,
                    "add_special_tokens": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=30,
            )
        except PaperProviderError as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            if ledger is not None:
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                        logical_request_id=tokenizer_id,
                        stage="provider_tokenize",
                        status="FAILED",
                        duration_ms=duration_ms,
                        logical_calls=1,
                        failure_type=type(exc).__name__,
                        failure_code="TOKENIZER_REQUEST_FAILED",
                    )
                )
            raise DG14ProviderError("vLLM tokenizer request failed") from exc
        duration_ms = (time.perf_counter() - started) * 1000
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
            if ledger is not None:
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                        logical_request_id=tokenizer_id,
                        stage="provider_tokenize",
                        status="FAILED",
                        duration_ms=duration_ms,
                        logical_calls=1,
                        failure_type="DG14ProviderError",
                        failure_code="TOKENIZER_RESPONSE_INVALID",
                    )
                )
            raise DG14ProviderError("vLLM tokenizer response is invalid")
        if ledger is not None:
            ledger.append(
                DG14StageEvent(
                    run_id=run_id,
                    case_id=case_id,
                    method_id=method_id,
                    token_budget=token_budget,
                    logical_request_id=tokenizer_id,
                    stage="provider_tokenize",
                    status="SUCCEEDED",
                    duration_ms=duration_ms,
                    logical_calls=1,
                    prompt_tokens=count,
                )
            )
        return count, duration_ms

    def _fit_memory(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        token_budget: int,
        request_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        ledger: DG14StageLedger | None,
        allow_truncation: bool = True,
        sealed_context_tokens: int | None = None,
    ) -> tuple[FittedMemory, int, float]:
        calls = 0
        latency_ms = 0.0

        def count(context: str) -> int:
            nonlocal calls, latency_ms
            calls += 1
            observed, elapsed = self._count_messages(
                messages(question, question_as_of, context),
                run_id=run_id,
                case_id=case_id,
                method_id=method_id,
                token_budget=token_budget,
                request_id=request_id,
                ordinal=calls,
                ledger=ledger,
            )
            latency_ms += elapsed
            return observed

        with_memory = count(memory_context)
        no_memory = count("")
        accounting = PromptAccounting(
            prompt_tokens=with_memory,
            no_memory_prompt_tokens=no_memory,
            memory_tokens=max(0, with_memory - no_memory),
        )
        if sealed_context_tokens is not None:
            boundary_tokens = accounting.memory_tokens - sealed_context_tokens
            if sealed_context_tokens <= token_budget and boundary_tokens in {0, 1}:
                return FittedMemory(memory_context, accounting, False), calls, latency_ms
            raise ReaderConformanceError(
                "TOKEN_ACCOUNTING_MISMATCH",
                "sealed Context tokens or chat-template boundary accounting drifted",
                metadata={
                    "exact_reader_tokens": accounting.memory_tokens,
                    "sealed_context_tokens": sealed_context_tokens,
                    "template_boundary_tokens": boundary_tokens,
                    "budget_ceiling": token_budget,
                    "accounting_delta": max(
                        0, sealed_context_tokens - token_budget
                    ),
                    "send_time_truncation_attempted": False,
                },
            )
        if accounting.memory_tokens <= token_budget:
            return FittedMemory(memory_context, accounting, False), calls, latency_ms
        if not allow_truncation:
            raise ReaderConformanceError(
                "TOKEN_ACCOUNTING_MISMATCH",
                "exact Reader memory exceeds the sealed presentation ceiling",
                metadata={
                    "exact_reader_tokens": accounting.memory_tokens,
                    "budget_ceiling": token_budget,
                    "accounting_delta": accounting.memory_tokens - token_budget,
                    "send_time_truncation_attempted": False,
                },
            )
        low = 0
        high = len(memory_context)
        best = ""
        best_accounting = PromptAccounting(no_memory, no_memory, 0)
        while low <= high:
            midpoint = (low + high) // 2
            candidate = memory_context[:midpoint].rstrip()
            observed = count(candidate)
            candidate_accounting = PromptAccounting(
                prompt_tokens=observed,
                no_memory_prompt_tokens=no_memory,
                memory_tokens=max(0, observed - no_memory),
            )
            if candidate_accounting.memory_tokens <= token_budget:
                best = candidate
                best_accounting = candidate_accounting
                low = midpoint + 1
            else:
                high = midpoint - 1
        if memory_context and not best:
            raise DG14ProviderError(
                "memory context cannot fit the matched token budget"
            )
        return FittedMemory(best, best_accounting, True), calls, latency_ms

    def answer(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        token_budget: int,
        ledger: DG14StageLedger | None = None,
        sampling_seed: int | None = None,
        exact_context: bool = False,
        sealed_context_tokens: int | None = None,
    ) -> ProviderResult:
        """Tokenize and answer one cell without any automatic retry.

        Defaults preserve DG-14. DG-23 supplies an explicit seed and requires
        an exact Context so overflow fails before the completion endpoint.
        """

        if sampling_seed is not None and not 0 <= sampling_seed < 1 << 63:
            raise ValueError("sampling seed must be a non-negative signed 63-bit value")
        if sealed_context_tokens is not None and (
            not exact_context
            or isinstance(sealed_context_tokens, bool)
            or not isinstance(sealed_context_tokens, int)
            or sealed_context_tokens < 0
            or sealed_context_tokens > token_budget
        ):
            raise ReaderConformanceError(
                "TOKEN_ACCOUNTING_MISMATCH",
                "sealed Context token claim is invalid for the exact Reader",
                metadata={
                    "sealed_context_tokens": sealed_context_tokens,
                    "budget_ceiling": token_budget,
                    "send_time_truncation_attempted": False,
                },
            )
        request_id = logical_request_id(run_id, case_id, method_id, token_budget)
        preflight_started = time.perf_counter()
        try:
            fitted, tokenizer_calls, tokenize_latency_ms = self._fit_memory(
                run_id=run_id,
                case_id=case_id,
                method_id=method_id,
                token_budget=token_budget,
                request_id=request_id,
                question=question,
                question_as_of=question_as_of,
                memory_context=memory_context,
                ledger=ledger,
                allow_truncation=not exact_context,
                sealed_context_tokens=sealed_context_tokens,
            )
        except DG14ProviderError as exc:
            if ledger is not None:
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                        logical_request_id=request_id,
                        stage="provider",
                        status="FAILED",
                        duration_ms=(time.perf_counter() - preflight_started) * 1000,
                        failure_type=type(exc).__name__,
                        failure_code="PROVIDER_PREFLIGHT_FAILED",
                    )
                )
            raise
        accounting = fitted.accounting
        if accounting.prompt_tokens > self.prompt_token_budget:
            if ledger is not None:
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                        logical_request_id=request_id,
                        stage="provider",
                        status="FAILED",
                        duration_ms=(time.perf_counter() - preflight_started) * 1000,
                        memory_tokens=accounting.memory_tokens,
                        prompt_tokens=accounting.prompt_tokens,
                        failure_type="DG14ProviderError",
                        failure_code="PROMPT_BUDGET_EXCEEDED",
                    )
                )
            raise DG14ProviderError("serialized prompt exceeds the vLLM prompt budget")
        prompt_messages = messages(question, question_as_of, fitted.context)
        prompt_bytes = _canonical(
            {
                "messages": prompt_messages,
                "prompt_contract_sha256": EXPECTED_PROMPT_CONTRACT_SHA256,
            }
        )
        prompt_sha256 = hashlib.sha256(prompt_bytes).hexdigest()
        seed = (
            sampling_seed
            if sampling_seed is not None
            else matched_seed(run_id, case_id, token_budget)
        )
        cache_salt = hashlib.sha256(
            f"milai-dg14-provider-v1:{request_id}".encode()
        ).hexdigest()
        started = time.perf_counter()
        try:
            response, headers = self._post_json(
                self.base_url,
                "/v1/chat/completions",
                {
                    "model": MODEL_ID,
                    "messages": prompt_messages,
                    "temperature": 0,
                    "top_p": 1,
                    "max_tokens": self.max_output_tokens,
                    "stream": False,
                    "seed": seed,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "milai_dg14_opened_dev_answer",
                            "strict": True,
                            "schema": ANSWER_SCHEMA,
                        },
                    },
                    "chat_template_kwargs": {"enable_thinking": False},
                    "include_reasoning": False,
                    "cache_salt": cache_salt,
                },
                timeout=240,
            )
        except PaperProviderError as exc:
            provider_latency_ms = (time.perf_counter() - started) * 1000
            if ledger is not None:
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                        logical_request_id=request_id,
                        stage="provider",
                        status="FAILED",
                        duration_ms=provider_latency_ms,
                        logical_calls=1,
                        memory_tokens=accounting.memory_tokens,
                        prompt_tokens=accounting.prompt_tokens,
                        failure_type=type(exc).__name__,
                        failure_code="PROVIDER_REQUEST_FAILED",
                    )
                )
            raise DG14ProviderError("vLLM answer request failed") from exc
        provider_latency_ms = (time.perf_counter() - started) * 1000
        try:
            parsed = _parse_completion(
                response,
                headers,
                accounting.prompt_tokens,
                max_output_tokens=self.max_output_tokens,
            )
        except DG14ProviderError as exc:
            if ledger is not None:
                ledger.append(
                    DG14StageEvent(
                        run_id=run_id,
                        case_id=case_id,
                        method_id=method_id,
                        token_budget=token_budget,
                        logical_request_id=request_id,
                        stage="provider",
                        status="FAILED",
                        duration_ms=provider_latency_ms,
                        logical_calls=1,
                        memory_tokens=accounting.memory_tokens,
                        prompt_tokens=accounting.prompt_tokens,
                        failure_type=type(exc).__name__,
                        failure_code="PROVIDER_RESPONSE_INVALID",
                    )
                )
            raise
        answer_sha256 = hashlib.sha256(parsed[0].encode("utf-8")).hexdigest()
        if ledger is not None:
            ledger.append(
                DG14StageEvent(
                    run_id=run_id,
                    case_id=case_id,
                    method_id=method_id,
                    token_budget=token_budget,
                    logical_request_id=request_id,
                    stage="provider",
                    status="SUCCEEDED",
                    duration_ms=provider_latency_ms,
                    logical_calls=1,
                    memory_tokens=accounting.memory_tokens,
                    prompt_tokens=accounting.prompt_tokens,
                    details={
                        "answer_sha256": answer_sha256,
                        "cache_salt_sha256": cache_salt,
                        "completion_tokens": parsed[3],
                        "native_request_id": parsed[1],
                        "prompt_sha256": prompt_sha256,
                        "seed": seed,
                    },
                )
            )
        return ProviderResult(
            answer=parsed[0],
            answer_sha256=hashlib.sha256(parsed[0].encode("utf-8")).hexdigest(),
            native_request_id=parsed[1],
            logical_request_id=request_id,
            seed=seed,
            cache_salt=cache_salt,
            prompt_sha256=prompt_sha256,
            prompt_tokens=accounting.prompt_tokens,
            no_memory_prompt_tokens=accounting.no_memory_prompt_tokens,
            memory_tokens=accounting.memory_tokens,
            completion_tokens=parsed[3],
            finish_reason=parsed[2],
            context=fitted.context,
            context_truncated=fitted.truncated,
            tokenizer_calls=tokenizer_calls,
            tokenize_latency_ms=tokenize_latency_ms,
            provider_latency_ms=provider_latency_ms,
            content_sha256=parsed[4],
            content_byte_length=parsed[5],
            response_schema_sha256=hashlib.sha256(
                _canonical(ANSWER_SCHEMA)
            ).hexdigest(),
            sealed_context_tokens=sealed_context_tokens,
            template_boundary_tokens=(
                accounting.memory_tokens - sealed_context_tokens
                if sealed_context_tokens is not None
                else 0
            ),
        )


def _parse_completion(
    response: Mapping[str, Any],
    headers: Mapping[str, str],
    expected_prompt_tokens: int,
    *,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> tuple[str, str, str, int, str, int]:
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
        raise ReaderConformanceError(
            "TRANSPORT_ENVELOPE_INVALID", "vLLM completion envelope is invalid"
        )
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
    ):
        raise ReaderConformanceError(
            "TRANSPORT_ENVELOPE_INVALID", "vLLM completion fields are invalid"
        )
    if prompt_tokens != expected_prompt_tokens:
        raise ReaderConformanceError(
            "TOKEN_ACCOUNTING_MISMATCH",
            "provider prompt usage differs from tokenizer preflight",
            metadata={
                "expected_prompt_tokens": expected_prompt_tokens,
                "observed_prompt_tokens": prompt_tokens,
            },
        )
    content_bytes = content.encode("utf-8")
    safe_metadata = {
        "native_request_id": native_id,
        "finish_reason": finish_reason,
        "completion_tokens": completion_tokens,
        "content_byte_length": len(content_bytes),
        "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
    }
    try:
        answer = json.loads(content)
    except json.JSONDecodeError as exc:
        truncated_prefix = _is_truncated_json_prefix(content)
        if (
            finish_reason == "length"
            and completion_tokens == max_output_tokens
            and truncated_prefix
        ):
            failure_class = "OUTPUT_LIMIT_TRUNCATED"
        elif truncated_prefix:
            failure_class = "STRUCTURED_DECODING_FAILED"
        else:
            failure_class = "CONTENT_NOT_JSON"
        raise ReaderConformanceError(
            failure_class,
            "strict answer content is not JSON",
            metadata={**safe_metadata, "truncated_json_prefix": truncated_prefix},
        ) from exc
    if (
        not isinstance(answer, dict)
        or set(answer) != {"answer"}
        or not isinstance(answer["answer"], str)
    ):
        raise ReaderConformanceError(
            "SCHEMA_VIOLATION",
            "strict answer content violates the schema",
            metadata=safe_metadata,
        )
    return (
        answer["answer"],
        native_id,
        finish_reason,
        completion_tokens,
        str(safe_metadata["content_sha256"]),
        len(content_bytes),
    )


def _is_truncated_json_prefix(content: str) -> bool:
    """Recognize an unfinished envelope; never repair or accept it."""
    stripped = content.lstrip()
    if not stripped.startswith("{") or '"answer"' not in stripped:
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError as exc:
        return exc.pos >= max(0, len(stripped) - 2) or stripped.count('"') % 2 == 1
    return False
