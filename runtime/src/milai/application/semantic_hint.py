"""Strict shadow-only boundary for one-call SemanticQueryHint generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from milai.domain.semantic_query import (
    SemanticHintReceipt,
    SemanticHintTiming,
    SemanticQueryHint,
    validate_query_hint_spans,
)

MAX_HINT_COMPLETION_TOKENS = 96
MAX_PREVIEW_COUNT = 12
MAX_PREVIEW_CHARS = 600
_SUPPORTED_FAMILIES = (
    "LOOKUP",
    "TEMPORAL_FILTER",
    "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE",
    "COUNT",
    "SUM",
    "AVERAGE",
    "DIVIDE",
    "COMPARE",
    "MULTI_JOIN",
    "WHY_CHANGE",
)


class SemanticHintError(RuntimeError):
    """Typed failure: no caller may silently accept or repair this result."""

    def __init__(
        self,
        code: str,
        *,
        transport_mode: Literal["non-streaming", "streaming"] | None = None,
        http_status: int | None = None,
        stream_finish_state: str | None = None,
        sse_error_type: str | None = None,
        sse_error_code: int | str | None = None,
        finish_reason: str | None = None,
        completion_tokens: int | None = None,
        latency_ms: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.transport_mode = transport_mode
        self.http_status = http_status
        self.stream_finish_state = stream_finish_state
        self.sse_error_type = sse_error_type
        self.sse_error_code = sse_error_code
        self.finish_reason = finish_reason
        self.completion_tokens = completion_tokens
        self.latency_ms = latency_ms


@dataclass(frozen=True, slots=True)
class SemanticHintCompletion:
    content: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    tokenizer_latency_ms: float
    queue_ms: float
    ttft_ms: float
    decode_ms: float
    total_ms: float
    provider_calls: int = 1
    automatic_retry_count: int = 0
    finish_reason: str = "stop"
    transport_mode: Literal["non-streaming", "streaming", "synthetic"] = "synthetic"
    http_status: int = 200
    stream_finish_state: str = "not_applicable"
    sse_error_observed: bool = False


class StructuredSemanticProvider(Protocol):
    def complete_structured(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        schema_name: str,
        schema: Mapping[str, Any],
        max_completion_tokens: int,
        seed: int,
    ) -> SemanticHintCompletion: ...


class SemanticHintShadowService:
    """Generate an untrusted hint receipt without changing a product QueryPlan."""

    def __init__(self, provider: StructuredSemanticProvider) -> None:
        self._provider = provider

    def generate(
        self,
        *,
        run_id: str,
        case_id: str,
        query: str,
        reference_time: datetime,
        missing_requirement_ids: Sequence[str] = (),
        evidence_previews: Sequence[str] = (),
    ) -> SemanticHintReceipt:
        if not run_id or not case_id or not query:
            raise ValueError("semantic hint identity/query is required")
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("semantic hint reference_time must include timezone")
        if len(evidence_previews) > MAX_PREVIEW_COUNT or any(
            len(preview) > MAX_PREVIEW_CHARS for preview in evidence_previews
        ):
            raise ValueError("semantic hint EvidenceSpan preview budget exceeded")
        messages = _messages(
            query=query,
            reference_time=reference_time,
            missing_requirement_ids=missing_requirement_ids,
            evidence_previews=evidence_previews,
        )
        schema = SemanticQueryHint.model_json_schema()
        seed = _seed(run_id, case_id)
        completion = self._provider.complete_structured(
            messages=messages,
            schema_name="semantic_query_hint_v01",
            schema=schema,
            max_completion_tokens=MAX_HINT_COMPLETION_TOKENS,
            seed=seed,
        )
        if completion.provider_calls != 1 or completion.automatic_retry_count != 0:
            raise SemanticHintError("SEMANTIC_HINT_CALL_CEILING_VIOLATED")
        if not 0 <= completion.completion_tokens <= MAX_HINT_COMPLETION_TOKENS:
            raise SemanticHintError("SEMANTIC_HINT_COMPLETION_BUDGET_VIOLATED")
        if completion.finish_reason == "length":
            raise SemanticHintError("SEMANTIC_HINT_OUTPUT_TRUNCATED")
        try:
            decoded = json.loads(completion.content)
            hint = SemanticQueryHint.model_validate(decoded)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise SemanticHintError("SEMANTIC_HINT_SCHEMA_INVALID") from exc
        try:
            validate_query_hint_spans(query, hint)
        except ValueError as exc:
            raise SemanticHintError("SEMANTIC_HINT_CUE_SPAN_INVALID") from exc
        return SemanticHintReceipt(
            hint=hint,
            provider=completion.provider,
            model=completion.model,
            prompt_digest=_digest(messages),
            schema_digest=_digest(schema),
            seed=seed,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            tokenizer_latency_ms=completion.tokenizer_latency_ms,
            timing=SemanticHintTiming(
                queue_ms=completion.queue_ms,
                ttft_ms=completion.ttft_ms,
                decode_ms=completion.decode_ms,
                total_ms=completion.total_ms,
            ),
            automatic_retry_count=0,
            auxiliary_model_calls=1,
        )


def _messages(
    *,
    query: str,
    reference_time: datetime,
    missing_requirement_ids: Sequence[str],
    evidence_previews: Sequence[str],
) -> list[dict[str, str]]:
    system = (
        "Classify one memory query into the supplied strict JSON schema. Return "
        "one compact JSON line without formatting whitespace. Only route and "
        "operator_family are required; omit schema_version and optional fields "
        "unless they are essential. For this route/operator shadow, omit "
        "cue_spans and temporal_spans instead of estimating character offsets. "
        "This is a non-executable hint: never answer the query, never declare "
        "evidence complete, and never make authority/currentness decisions. "
        "Every cue_spans/temporal_spans item must copy an exact query substring "
        "and use Python-style [start,end) character offsets. Route STATE only for "
        "an exact current authoritative-state address. Route EVIDENCE only with "
        "LOOKUP. Route COMPOSE with every supported operator family other than "
        "LOOKUP, including temporal filtering/order/distance, counting, "
        "arithmetic, comparison, or multi-evidence joins. Use AMBIGUOUS "
        "for exhaustive/global requests, unsupported languages, or when no safe "
        "operator applies. Operator definitions: LOOKUP=one fact; "
        "TEMPORAL_FILTER=event constrained by a time expression; "
        "TEMPORAL_ORDER=which event came first; TEMPORAL_DISTANCE=elapsed time "
        "between two events; COUNT=number of matching events; SUM/AVERAGE/DIVIDE="
        "the named arithmetic; COMPARE=value comparison; MULTI_JOIN=combine "
        "multiple evidence items; WHY_CHANGE=explain a change. Supported operator "
        "families: "
        + ", ".join(_SUPPORTED_FAMILIES)
        + "."
    )
    payload = {
        "query": query,
        "reference_time": reference_time.isoformat(),
        "missing_requirement_ids": list(missing_requirement_ids),
        "evidence_span_previews": list(evidence_previews),
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    ]


def _seed(run_id: str, case_id: str) -> int:
    digest = hashlib.sha256(
        f"milai-dg17-semantic-hint-v01\0{run_id}\0{case_id}".encode()
    ).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _digest(value: object) -> str:
    material = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


__all__ = [
    "MAX_HINT_COMPLETION_TOKENS",
    "MAX_PREVIEW_CHARS",
    "MAX_PREVIEW_COUNT",
    "SemanticHintCompletion",
    "SemanticHintError",
    "SemanticHintShadowService",
    "StructuredSemanticProvider",
]
