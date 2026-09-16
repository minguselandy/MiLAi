"""Strict loopback adapter for DG-27 N-best grounded interpretation."""

from __future__ import annotations

import http.client
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from milai.domain.decision_boundary import (
    SemanticHypothesisV02,
    SemanticInterpretationSetV02,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import EvidenceRequirementV02

DG27_SYSTEM_PROMPT = (
    "You are a fallible semantic interpretation component for already-admitted memory "
    "candidates. You do not admit Evidence, create AcceptedBinding, declare COMPLETE, answer "
    "the query, or mutate memory. For every candidate_id, return zero to three alternative "
    "hypotheses grounded only in exact contiguous substrings of candidate_render using Python "
    "[start,end) character offsets. Preserve distinct entity, predicate, value, unit and event-"
    "time readings when ambiguity matters. Put every target entity/action anchor explicitly "
    "expressed by the quoted span in normalized_subjects. SUPPORT or UPDATE means the quoted "
    "span may satisfy "
    "the target requirement; CONTRADICT preserves contrary evidence; CONTEXT_ONLY is relevant "
    "but not answer-bearing; IRRELEVANT has no grounded spans. Do not use observed_at/source "
    "time as event time unless candidate text explicitly states the event time. Confidence is "
    "advisory only. Runtime independently validates source identity, exact spans, permissions, "
    "type, role, entity, predicate, time, unit, deduplication and sufficiency. Return JSON only."
)

DG27_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidate_id": {"type": "string", "minLength": 1},
                    "hypotheses": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "relation": {
                                    "type": "string",
                                    "enum": [
                                        "SUPPORT",
                                        "CONTRADICT",
                                        "UPDATE",
                                        "CONTEXT_ONLY",
                                        "IRRELEVANT",
                                    ],
                                },
                                "grounded_spans": {
                                    "type": "array",
                                    "maxItems": 3,
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "start": {"type": "integer", "minimum": 0},
                                            "end": {"type": "integer", "minimum": 1},
                                            "text": {"type": "string", "minLength": 1},
                                        },
                                        "required": ["start", "end", "text"],
                                    },
                                },
                                "normalized_subjects": {
                                    "type": "array",
                                    "maxItems": 16,
                                    "items": {"type": "string", "minLength": 1},
                                },
                                "normalized_predicate": {"type": ["string", "null"]},
                                "normalized_value": {"type": ["string", "null"]},
                                "normalized_unit": {"type": ["string", "null"]},
                                "event_time_hypothesis": {
                                    "anyOf": [
                                        {"type": "null"},
                                        {
                                            "type": "object",
                                            "additionalProperties": False,
                                            "properties": {
                                                "start": {"type": ["string", "null"]},
                                                "end": {"type": ["string", "null"]},
                                                "time_basis": {
                                                    "type": "string",
                                                    "enum": [
                                                        "EXPLICIT_EVENT_TIME",
                                                        "INFERRED_EVENT_TIME",
                                                        "SOURCE_OBSERVED_TIME",
                                                        "UNRESOLVED",
                                                    ],
                                                },
                                                "normalized_from": {
                                                    "type": ["string", "null"]
                                                },
                                            },
                                            "required": [
                                                "start",
                                                "end",
                                                "time_basis",
                                                "normalized_from",
                                            ],
                                        },
                                    ]
                                },
                                "confidence_feature": {"type": ["number", "null"]},
                            },
                            "required": [
                                "relation",
                                "grounded_spans",
                                "normalized_subjects",
                                "normalized_predicate",
                                "normalized_value",
                                "normalized_unit",
                                "event_time_hypothesis",
                                "confidence_feature",
                            ],
                        },
                    },
                    "ambiguity_reasons": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["candidate_id", "hypotheses", "ambiguity_reasons"],
            },
        }
    },
    "required": ["candidates"],
}


class GroundedInterpretationAdapterError(RuntimeError):
    """One non-retryable model boundary failure."""


@dataclass(frozen=True, slots=True)
class GroundedInterpretationExecution:
    interpretation_sets: tuple[SemanticInterpretationSetV02, ...]
    model_id: str
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    automatic_retries: int = 0


class LoopbackGroundedInterpretationAdapter:
    """One-call, no-retry OpenAI-compatible structured-output adapter."""

    def __init__(
        self,
        *,
        model_id: str,
        host: str = "127.0.0.1",
        port: int = 7860,
        timeout_seconds: float = 120.0,
        max_completion_tokens: int = 8192,
    ) -> None:
        self._model_id = model_id
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._max_completion_tokens = max_completion_tokens

    def interpret(
        self,
        *,
        query: str,
        requirement: EvidenceRequirementV02,
        candidates: Sequence[Mapping[str, Any]],
    ) -> GroundedInterpretationExecution:
        candidate_ids = [str(item.get("evidence_id", "")) for item in candidates]
        if any(not value for value in candidate_ids) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise GroundedInterpretationAdapterError("DG27_CANDIDATE_IDENTITY_INVALID")
        visible_candidates = []
        for candidate in candidates:
            render = candidate.get("content")
            if not isinstance(render, str) or not render:
                raise GroundedInterpretationAdapterError("DG27_CANDIDATE_RENDER_MISSING")
            visible_candidates.append(
                {
                    "candidate_id": str(candidate["evidence_id"]),
                    "candidate_render": render,
                }
            )
        user_material = {
            "query": query,
            "target_requirement": requirement.model_dump(mode="json"),
            "offset_contract": "Python [start,end) over candidate_render exactly",
            "candidates": visible_candidates,
        }
        request = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": DG27_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_material,
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
                    "name": "milai_dg27_semantic_interpretation_v02",
                    "strict": True,
                    "schema": DG27_RESPONSE_SCHEMA,
                },
            },
        }
        started = perf_counter()
        response = self._post(request)
        elapsed_ms = (perf_counter() - started) * 1_000
        if response.get("model") != self._model_id:
            raise GroundedInterpretationAdapterError("DG27_MODEL_IDENTITY_MISMATCH")
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise GroundedInterpretationAdapterError("DG27_MODEL_CHOICE_COUNT_INVALID")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise GroundedInterpretationAdapterError("DG27_MODEL_CHOICE_INVALID")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise GroundedInterpretationAdapterError("DG27_MODEL_CONTENT_MISSING")
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as error:
            raise GroundedInterpretationAdapterError("DG27_MODEL_JSON_INVALID") from error
        rows = decoded.get("candidates") if isinstance(decoded, Mapping) else None
        if not isinstance(rows, list):
            raise GroundedInterpretationAdapterError("DG27_MODEL_BATCH_INVALID")
        observed_ids = [
            str(item.get("candidate_id", "")) if isinstance(item, Mapping) else ""
            for item in rows
        ]
        if observed_ids != candidate_ids:
            raise GroundedInterpretationAdapterError("DG27_MODEL_BATCH_IDENTITY_DRIFT")
        interpretation_sets = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise GroundedInterpretationAdapterError("DG27_MODEL_ROW_INVALID")
            raw_hypotheses = row.get("hypotheses")
            if not isinstance(raw_hypotheses, list):
                raise GroundedInterpretationAdapterError("DG27_MODEL_HYPOTHESES_INVALID")
            hypotheses = []
            for index, raw in enumerate(raw_hypotheses):
                if not isinstance(raw, Mapping):
                    raise GroundedInterpretationAdapterError(
                        "DG27_MODEL_HYPOTHESIS_INVALID"
                    )
                material = dict(raw)
                material["hypothesis_id"] = canonical_sha256(
                    {
                        "producer": self._model_id,
                        "candidate_id": row["candidate_id"],
                        "requirement_id": requirement.slot_id,
                        "index": index,
                        "hypothesis": raw,
                    }
                )
                try:
                    hypotheses.append(SemanticHypothesisV02.model_validate(material))
                except ValidationError as error:
                    raise GroundedInterpretationAdapterError(
                        "DG27_MODEL_HYPOTHESIS_SCHEMA_INVALID"
                    ) from error
            try:
                interpretation_sets.append(
                    SemanticInterpretationSetV02(
                        candidate_id=str(row["candidate_id"]),
                        hypotheses=hypotheses,
                        ambiguity_reasons=list(row.get("ambiguity_reasons", [])),
                        producer_identity=self._model_id,
                    )
                )
            except ValidationError as error:
                raise GroundedInterpretationAdapterError(
                    "DG27_MODEL_INTERPRETATION_SET_INVALID"
                ) from error
        usage = response.get("usage")
        usage_values = usage if isinstance(usage, Mapping) else {}
        return GroundedInterpretationExecution(
            interpretation_sets=tuple(interpretation_sets),
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
            raise GroundedInterpretationAdapterError("DG27_MODEL_UNAVAILABLE") from error
        finally:
            connection.close()
        if response.status != 200:
            raise GroundedInterpretationAdapterError(
                f"DG27_MODEL_HTTP_{response.status}"
            )
        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise GroundedInterpretationAdapterError("DG27_MODEL_RESPONSE_INVALID") from error
        if not isinstance(decoded, dict):
            raise GroundedInterpretationAdapterError("DG27_MODEL_RESPONSE_NOT_OBJECT")
        return decoded


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


__all__ = [
    "DG27_RESPONSE_SCHEMA",
    "DG27_SYSTEM_PROMPT",
    "GroundedInterpretationAdapterError",
    "GroundedInterpretationExecution",
    "LoopbackGroundedInterpretationAdapter",
]
