"""Structured vLLM adapter for residual Formation event proposals."""

from __future__ import annotations

import http.client
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from milai.application.evidence_semantics import (
    direct_event_time_expression_count,
    project_evidence_spans,
    resolve_direct_event_time,
)
from milai.domain.formation_artifact import FormationModelEventProposalV01

MF03_V01_SYSTEM_PROMPT = (
    "You are a fallible, non-authoritative memory Formation extractor. Extract only "
    "event occurrences asserted, negated, experienced, or concretely planned by the user "
    "in target_evidence_ids; ignore advice, examples, and hypothetical suggestions. Copy "
    "grounded_quote exactly from its target source. Emit one event per distinct primary "
    "subject/object occurrence; twins or multiple children require separate events. Use "
    "primary_subject for the event-defining person/object and context_participants for "
    "others. event_identity_hint is semantic, never an opaque source ID. Do not calculate "
    "timestamps. Direct dates are normalized by Runtime. Propose temporal_relation only "
    "when the target quote explicitly contains AFTER, BEFORE, or SAME_TIME language and "
    "another supplied source has an exact anchor_quote that grounds it. normalized_from "
    "must be an exact substring of the target grounded_quote. Select temporal anchors only "
    "from runtime_temporal_anchors; their source identity and exact quote are constrained by "
    "the output schema. Model output is only a proposal: Runtime validates quotes, "
    "identities, relation, time, and governance. Return JSON only."
)

_TEMPORAL_CLAUSE_BREAK = re.compile(
    r"\s*(?:;|,\s*(?:and|but|so|then)\b)\s*",
    re.IGNORECASE,
)


class FormationExtractionAdapterError(RuntimeError):
    """The local model transport or structured response was invalid."""


@dataclass(frozen=True, slots=True)
class FormationExtractionExecutionV01:
    proposals: tuple[FormationModelEventProposalV01, ...]
    model_id: str
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    automatic_retries: int = 0


class LoopbackFormationExtractionAdapterV01:
    """One-call, zero-retry adapter over an already-running local vLLM endpoint."""

    def __init__(
        self,
        *,
        model_id: str,
        host: str = "127.0.0.1",
        port: int = 7860,
        timeout_seconds: float = 120.0,
        max_completion_tokens: int = 2048,
    ) -> None:
        self._model_id = model_id
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._max_completion_tokens = max_completion_tokens

    def extract(
        self,
        *,
        sources: Sequence[Mapping[str, Any]],
        target_evidence_ids: Sequence[str],
    ) -> FormationExtractionExecutionV01:
        source_rows = [_visible_source(item) for item in sources]
        source_ids = [str(item["evidence_id"]) for item in source_rows]
        target_ids = [str(value) for value in target_evidence_ids]
        if (
            len(source_ids) != len(set(source_ids))
            or not target_ids
            or len(target_ids) != len(set(target_ids))
            or not set(target_ids).issubset(source_ids)
        ):
            raise FormationExtractionAdapterError("MF03_SOURCE_OR_TARGET_IDENTITY_INVALID")
        temporal_anchors = _temporal_anchor_pairs(sources, target_ids)
        schema = _response_schema(target_ids, temporal_anchors)
        request = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": MF03_V01_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "target_evidence_ids": target_ids,
                            "sources": source_rows,
                            "runtime_temporal_anchors": [
                                {"evidence_id": evidence_id, "quote": quote}
                                for evidence_id, quote in temporal_anchors
                            ],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": self._max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "milai_mf03_formation_events_v01",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        started = perf_counter()
        response = self._post(request)
        elapsed_ms = (perf_counter() - started) * 1_000
        if response.get("model") != self._model_id:
            raise FormationExtractionAdapterError("MF03_MODEL_IDENTITY_MISMATCH")
        raw_events = _response_events(response)
        try:
            proposals = tuple(
                FormationModelEventProposalV01.model_validate(item)
                for item in raw_events
            )
        except ValidationError as error:
            raise FormationExtractionAdapterError(
                "MF03_MODEL_EVENT_SCHEMA_INVALID"
            ) from error
        if any(item.evidence_id not in target_ids for item in proposals):
            raise FormationExtractionAdapterError("MF03_NON_TARGET_EVENT_EMITTED")
        usage = response.get("usage")
        usage_values = usage if isinstance(usage, Mapping) else {}
        return FormationExtractionExecutionV01(
            proposals=proposals,
            model_id=self._model_id,
            response_id=str(response.get("id", "")),
            prompt_tokens=_nonnegative_int(usage_values.get("prompt_tokens")),
            completion_tokens=_nonnegative_int(usage_values.get("completion_tokens")),
            latency_ms=elapsed_ms,
        )

    def _post(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        connection = http.client.HTTPConnection(
            self._host,
            self._port,
            timeout=self._timeout_seconds,
        )
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            response_body = response.read()
        except (OSError, TimeoutError) as error:
            raise FormationExtractionAdapterError("MF03_MODEL_UNAVAILABLE") from error
        finally:
            connection.close()
        if response.status != 200:
            raise FormationExtractionAdapterError(f"MF03_MODEL_HTTP_{response.status}")
        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise FormationExtractionAdapterError("MF03_MODEL_RESPONSE_INVALID") from error
        if not isinstance(decoded, dict):
            raise FormationExtractionAdapterError("MF03_MODEL_RESPONSE_NOT_OBJECT")
        return decoded


def _response_schema(
    target_ids: Sequence[str],
    temporal_anchors: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    relation_variants: list[dict[str, Any]] = [{"type": "null"}]
    for evidence_id, quote in temporal_anchors:
        relation_variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "relation": {
                        "type": "string",
                        "enum": ["AFTER", "BEFORE", "SAME_TIME"],
                    },
                    "amount": {"type": "integer", "minimum": 0, "maximum": 366},
                    "unit": {
                        "type": "string",
                        "enum": ["DAY", "WEEK", "MONTH"],
                    },
                    "anchor_evidence_id": {
                        "type": "string",
                        "enum": [evidence_id],
                    },
                    "anchor_quote": {"type": "string", "enum": [quote]},
                    "normalized_from": {"type": "string", "minLength": 1},
                },
                "required": [
                    "relation",
                    "amount",
                    "unit",
                    "anchor_evidence_id",
                    "anchor_quote",
                    "normalized_from",
                ],
            }
        )
    relation = {"anyOf": relation_variants}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "events": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "evidence_id": {"type": "string", "enum": list(target_ids)},
                        "grounded_quote": {"type": "string", "minLength": 1},
                        "event_type": {"type": "string", "minLength": 1},
                        "primary_subject": {"type": ["string", "null"]},
                        "context_participants": {
                            "type": "array",
                            "maxItems": 32,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "event_identity_hint": {"type": "string", "minLength": 1},
                        "temporal_relation": relation,
                        "negated": {"type": "boolean"},
                        "confidence_feature": {"type": ["number", "null"]},
                    },
                    "required": [
                        "evidence_id",
                        "grounded_quote",
                        "event_type",
                        "primary_subject",
                        "context_participants",
                        "event_identity_hint",
                        "temporal_relation",
                        "negated",
                        "confidence_feature",
                    ],
                },
            }
        },
        "required": ["events"],
    }


def _visible_source(source: Mapping[str, Any]) -> dict[str, str]:
    evidence_id = source.get("evidence_id")
    observed_at = source.get("observed_at")
    content = source.get("content")
    if not all(
        isinstance(value, str) and value
        for value in (evidence_id, observed_at, content)
    ):
        raise FormationExtractionAdapterError("MF03_VISIBLE_SOURCE_INVALID")
    return {
        "evidence_id": str(evidence_id),
        "observed_at": str(observed_at),
        "content": str(content),
    }


def _temporal_anchor_pairs(
    sources: Sequence[Mapping[str, Any]],
    target_evidence_ids: Sequence[str],
) -> list[tuple[str, str]]:
    """Return only source-exact, Runtime-resolvable non-target temporal anchors."""

    targets = set(target_evidence_ids)
    content_by_id = {
        str(source["evidence_id"]): str(source["content"])
        for source in sources
        if isinstance(source.get("evidence_id"), str)
        and isinstance(source.get("content"), str)
    }
    pairs: set[tuple[str, str]] = set()
    for span in project_evidence_spans(sources):
        if span.source_evidence_id in targets:
            continue
        content = content_by_id.get(span.source_evidence_id, "")
        for quote in _unambiguous_temporal_fragments(span.text, span.source_timestamp):
            if content.count(quote) == 1:
                pairs.add((span.source_evidence_id, quote))
    return sorted(pairs)[:32]


def _unambiguous_temporal_fragments(
    text: str,
    source_timestamp: datetime | None,
) -> list[str]:
    """Expose exact clause anchors, never a span containing multiple dates."""

    if direct_event_time_expression_count(text) <= 1:
        return [text] if resolve_direct_event_time(text, source_timestamp) is not None else []
    fragments = [
        value
        for value in (
            part.strip(" \t\r\n,;.!?")
            for part in _TEMPORAL_CLAUSE_BREAK.split(text)
        )
        if value
        and direct_event_time_expression_count(value) == 1
        and resolve_direct_event_time(value, source_timestamp) is not None
    ]
    return sorted(set(fragments), key=lambda value: (text.index(value), value))


def _response_events(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise FormationExtractionAdapterError("MF03_MODEL_CHOICE_COUNT_INVALID")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise FormationExtractionAdapterError("MF03_MODEL_CONTENT_MISSING")
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as error:
        raise FormationExtractionAdapterError("MF03_MODEL_JSON_INVALID") from error
    events = decoded.get("events") if isinstance(decoded, Mapping) else None
    if not isinstance(events, list) or any(not isinstance(item, Mapping) for item in events):
        raise FormationExtractionAdapterError("MF03_MODEL_EVENT_COLLECTION_INVALID")
    return [item for item in events if isinstance(item, Mapping)]


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = [
    "MF03_V01_SYSTEM_PROMPT",
    "FormationExtractionAdapterError",
    "FormationExtractionExecutionV01",
    "LoopbackFormationExtractionAdapterV01",
]
