"""DG-27 V03 quote-grounded interpretation with trusted local materialization."""

from __future__ import annotations

import http.client
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, tzinfo
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from milai.domain.decision_boundary import (
    EventTimeHypothesisV02,
    GroundedSpanV02,
    SemanticHypothesisV02,
    SemanticInterpretationSetV02,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import EvidenceRequirementV02

DG27_V03_SYSTEM_PROMPT = (
    "You are a fallible semantic interpretation component for already-admitted memory "
    "candidates. You do not admit Evidence, create AcceptedBinding, declare COMPLETE, answer "
    "the query, or mutate memory. Under each exact candidate key required by the response "
    "schema, return zero to three alternative hypotheses grounded only in exact contiguous "
    "quotes copied from that candidate_render. Do not "
    "calculate offsets. Prefer a quote that occurs exactly once in that candidate. Preserve "
    "distinct entity, predicate, value, unit and event-time readings when ambiguity matters. "
    "Judge one candidate against one target requirement as an atomic evidence role, not "
    "against the whole user question. A candidate does not need to contain other operands, "
    "all members of a set, a completeness proof, an operator result, or the final answer. "
    "Put target entity/action anchors explicitly expressed by the quote in "
    "normalized_subjects. SUPPORT or UPDATE means the quote supplies one typed operand, "
    "event member, state value, or other atomic support for the target requirement; "
    "CONTRADICT preserves contrary evidence; CONTEXT_ONLY is topically related but supplies "
    "no target operand/member; IRRELEVANT has no quotes. Do not use CONTEXT_ONLY merely "
    "because a quote cannot answer the whole question. When an interpretable candidate is "
    "irrelevant, "
    "return one explicit IRRELEVANT hypothesis with empty quotes/subjects and null normalized "
    "fields; reserve zero hypotheses for content that cannot be interpreted at all. Use "
    "ambiguity_reasons only when two or more grounded readings of this candidate remain "
    "plausible for the atomic requirement; otherwise return an empty list. "
    "Event-time start/end should be ISO-8601 when "
    "resolvable; do not invent a timezone. Confidence is advisory. Runtime derives offsets, "
    "resolves only deterministic timezone context, and independently validates source, gate, "
    "type, role, entity, predicate, time, unit, deduplication and sufficiency. Return JSON only."
)

_CANDIDATE_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
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
                    "grounded_quotes": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string", "minLength": 1},
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
                    "grounded_quotes",
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
    "required": ["hypotheses", "ambiguity_reasons"],
}

DG27_V03_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
            "required": [],
        }
    },
    "required": ["candidates"],
}


def response_schema_for_candidates(candidate_ids: Sequence[str]) -> dict[str, Any]:
    """Derive a strict request-scoped schema whose keys are the candidate identity."""

    schema = deepcopy(DG27_V03_RESPONSE_SCHEMA)
    candidates_schema = schema["properties"]["candidates"]
    candidates_schema["properties"] = {
        candidate_id: deepcopy(_CANDIDATE_PAYLOAD_SCHEMA)
        for candidate_id in candidate_ids
    }
    candidates_schema["required"] = list(candidate_ids)
    return schema

LocalDispositionV03 = Literal["VALID", "REJECTED_PROTOCOL", "DOWNGRADED_UNRESOLVED"]


class HypothesisMaterializationV03(BaseModel):
    """Non-authoritative local disposition for one raw model hypothesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    hypothesis_index: int = Field(ge=0, le=2)
    hypothesis_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: LocalDispositionV03
    reason_codes: list[str] = Field(default_factory=list)
    timezone_resolution_provenance: str | None = None
    accepted_binding_authority: Literal[False] = False
    canonical_mutation: Literal[False] = False


class GroundedInterpretationV03Error(RuntimeError):
    """A batch-fatal transport, top-level schema, identity, or source failure."""


@dataclass(frozen=True, slots=True)
class GroundedInterpretationExecutionV03:
    interpretation_sets: tuple[SemanticInterpretationSetV02, ...]
    materializations: tuple[HypothesisMaterializationV03, ...]
    model_id: str
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    automatic_retries: int = 0
    raw_response: dict[str, Any] | None = None


class LoopbackGroundedInterpretationAdapterV03:
    """One-call adapter that isolates hypothesis-local protocol failures."""

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
        include_raw_response: bool = False,
    ) -> GroundedInterpretationExecutionV03:
        candidate_ids = [str(item.get("evidence_id", "")) for item in candidates]
        if any(not value for value in candidate_ids) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise GroundedInterpretationV03Error("DG27_V03_CANDIDATE_IDENTITY_INVALID")
        candidate_by_id: dict[str, Mapping[str, Any]] = {}
        visible_candidates = []
        for candidate in candidates:
            candidate_id = str(candidate["evidence_id"])
            render = candidate.get("content")
            if not isinstance(render, str) or not render:
                raise GroundedInterpretationV03Error("DG27_V03_CANDIDATE_RENDER_MISSING")
            candidate_by_id[candidate_id] = candidate
            visible_candidates.append(
                {"candidate_id": candidate_id, "candidate_render": render}
            )
        user_material = {
            "query": query,
            "target_requirement": requirement.model_dump(mode="json"),
            "atomic_evidence_contract": {
                "unit": "ONE_CANDIDATE_TO_ONE_REQUIREMENT",
                "support_may_supply": "ONE_TYPED_OPERAND_OR_SET_MEMBER",
                "not_required": [
                    "OTHER_REQUIREMENTS",
                    "WHOLE_QUERY_ANSWER",
                    "SET_COMPLETENESS_PROOF",
                    "OPERATOR_RESULT",
                ],
            },
            "grounding_contract": "copy exact quotes; Runtime derives Python offsets",
            "candidates": visible_candidates,
        }
        request = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": DG27_V03_SYSTEM_PROMPT},
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
                    "name": "milai_dg27_v03_semantic_interpretation",
                    "strict": True,
                    "schema": response_schema_for_candidates(candidate_ids),
                },
            },
        }
        started = perf_counter()
        response = self._post(request)
        elapsed_ms = (perf_counter() - started) * 1_000
        if response.get("model") != self._model_id:
            raise GroundedInterpretationV03Error("DG27_V03_MODEL_IDENTITY_MISMATCH")
        rows = _response_rows(response)
        observed_ids = [str(item.get("candidate_id", "")) for item in rows]
        if (
            any(not value for value in observed_ids)
            or len(observed_ids) != len(set(observed_ids))
            or set(observed_ids) != set(candidate_ids)
        ):
            raise GroundedInterpretationV03Error("DG27_V03_MODEL_BATCH_IDENTITY_DRIFT")
        row_by_id = {str(item["candidate_id"]): item for item in rows}

        interpretation_sets: list[SemanticInterpretationSetV02] = []
        materializations: list[HypothesisMaterializationV03] = []
        for candidate_id in candidate_ids:
            row = row_by_id[candidate_id]
            source = candidate_by_id[candidate_id]
            content = str(source["content"])
            raw_hypotheses = row.get("hypotheses")
            if not isinstance(raw_hypotheses, list) or len(raw_hypotheses) > 3:
                raise GroundedInterpretationV03Error(
                    "DG27_V03_MODEL_HYPOTHESIS_COLLECTION_INVALID"
                )
            valid_hypotheses: list[SemanticHypothesisV02] = []
            local_ambiguity = [str(value) for value in row.get("ambiguity_reasons", [])]
            candidate_protocol_rejected = False
            for index, raw_hypothesis in enumerate(raw_hypotheses):
                raw = _mapping(raw_hypothesis, "raw hypothesis")
                hypothesis_id = canonical_sha256(
                    {
                        "producer": self._model_id,
                        "candidate_id": candidate_id,
                        "requirement_id": requirement.slot_id,
                        "index": index,
                        "hypothesis": raw,
                    }
                )
                hypothesis, disposition = materialize_hypothesis_v03(
                    candidate_id=candidate_id,
                    requirement_id=requirement.slot_id,
                    hypothesis_index=index,
                    hypothesis_id=hypothesis_id,
                    raw=raw,
                    content=content,
                    source_observed_at=source.get("observed_at"),
                )
                materializations.append(disposition)
                if hypothesis is not None:
                    valid_hypotheses.append(hypothesis)
                else:
                    candidate_protocol_rejected = True
                    local_ambiguity.extend(disposition.reason_codes)
            if (
                valid_hypotheses
                and all(item.relation == "IRRELEVANT" for item in valid_hypotheses)
                and not candidate_protocol_rejected
            ):
                # Models sometimes place a prose explanation of irrelevance in
                # ``ambiguity_reasons``.  A clear irrelevant disposition is not
                # an unresolved semantic alternative and must stay irrelevant.
                local_ambiguity = []
            try:
                interpretation_sets.append(
                    SemanticInterpretationSetV02(
                        candidate_id=candidate_id,
                        hypotheses=valid_hypotheses,
                        ambiguity_reasons=sorted(set(local_ambiguity))[:8],
                        producer_identity=f"{self._model_id}:dg27-v03",
                    )
                )
            except ValidationError as error:
                raise GroundedInterpretationV03Error(
                    "DG27_V03_INTERPRETATION_SET_INVALID"
                ) from error
        usage = response.get("usage")
        usage_values = usage if isinstance(usage, Mapping) else {}
        return GroundedInterpretationExecutionV03(
            interpretation_sets=tuple(interpretation_sets),
            materializations=tuple(materializations),
            model_id=self._model_id,
            response_id=str(response.get("id", "")),
            prompt_tokens=_nonnegative_int(usage_values.get("prompt_tokens")),
            completion_tokens=_nonnegative_int(usage_values.get("completion_tokens")),
            latency_ms=elapsed_ms,
            raw_response=dict(response) if include_raw_response else None,
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
            raise GroundedInterpretationV03Error("DG27_V03_MODEL_UNAVAILABLE") from error
        finally:
            connection.close()
        if response.status != 200:
            raise GroundedInterpretationV03Error(
                f"DG27_V03_MODEL_HTTP_{response.status}"
            )
        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise GroundedInterpretationV03Error(
                "DG27_V03_MODEL_RESPONSE_INVALID"
            ) from error
        if not isinstance(decoded, dict):
            raise GroundedInterpretationV03Error("DG27_V03_MODEL_RESPONSE_NOT_OBJECT")
        return decoded


def materialize_hypothesis_v03(
    *,
    candidate_id: str,
    requirement_id: str,
    hypothesis_index: int,
    hypothesis_id: str,
    raw: Mapping[str, Any],
    content: str,
    source_observed_at: object,
) -> tuple[SemanticHypothesisV02 | None, HypothesisMaterializationV03]:
    """Materialize one hypothesis without aborting its candidate or batch."""

    reasons: list[str] = []
    raw_quotes = raw.get("grounded_quotes")
    quotes = (
        [str(value) for value in raw_quotes]
        if isinstance(raw_quotes, list)
        else []
    )
    relation = str(raw.get("relation", ""))
    if len(quotes) != len(set(quotes)):
        reasons.append("DUPLICATE_GROUNDED_QUOTE")
    if relation == "IRRELEVANT" and quotes:
        reasons.append("IRRELEVANT_WITH_GROUNDED_QUOTE")
    if relation != "IRRELEVANT" and not quotes:
        reasons.append("SEMANTIC_RELATION_WITHOUT_GROUNDED_QUOTE")
    spans: list[GroundedSpanV02] = []
    for quote in quotes:
        occurrences = content.count(quote)
        if occurrences == 0:
            reasons.append("GROUNDED_QUOTE_ABSENT")
        elif occurrences > 1:
            reasons.append("GROUNDED_QUOTE_NON_UNIQUE")
        else:
            start = content.index(quote)
            spans.append(GroundedSpanV02(start=start, end=start + len(quote), text=quote))
    if reasons:
        disposition = HypothesisMaterializationV03(
            candidate_id=candidate_id,
            requirement_id=requirement_id,
            hypothesis_index=hypothesis_index,
            hypothesis_id=hypothesis_id,
            disposition="REJECTED_PROTOCOL",
            reason_codes=sorted(set(reasons)),
        )
        return None, disposition

    event_time, time_reasons, provenance = _materialize_event_time(
        raw.get("event_time_hypothesis"),
        source_observed_at,
    )
    disposition_name: LocalDispositionV03 = (
        "DOWNGRADED_UNRESOLVED" if time_reasons else "VALID"
    )
    try:
        hypothesis = SemanticHypothesisV02(
            hypothesis_id=hypothesis_id,
            relation=relation,  # type: ignore[arg-type]
            grounded_spans=spans,
            normalized_subjects=[str(value) for value in raw.get("normalized_subjects", [])],
            normalized_predicate=_optional_string(raw.get("normalized_predicate")),
            normalized_value=_optional_string(raw.get("normalized_value")),
            normalized_unit=_optional_string(raw.get("normalized_unit")),
            event_time_hypothesis=event_time,
            confidence_feature=_optional_float(raw.get("confidence_feature")),
        )
    except (TypeError, ValueError, ValidationError):
        disposition = HypothesisMaterializationV03(
            candidate_id=candidate_id,
            requirement_id=requirement_id,
            hypothesis_index=hypothesis_index,
            hypothesis_id=hypothesis_id,
            disposition="REJECTED_PROTOCOL",
            reason_codes=["HYPOTHESIS_SEMANTIC_SHAPE_INVALID"],
        )
        return None, disposition
    disposition = HypothesisMaterializationV03(
        candidate_id=candidate_id,
        requirement_id=requirement_id,
        hypothesis_index=hypothesis_index,
        hypothesis_id=hypothesis_id,
        disposition=disposition_name,
        reason_codes=time_reasons,
        timezone_resolution_provenance=provenance,
    )
    return hypothesis, disposition


def _materialize_event_time(
    raw_value: object,
    source_observed_at: object,
) -> tuple[EventTimeHypothesisV02 | None, list[str], str | None]:
    if raw_value is None:
        return None, [], None
    if not isinstance(raw_value, Mapping):
        return (
            EventTimeHypothesisV02(time_basis="UNRESOLVED"),
            ["EVENT_TIME_SHAPE_INVALID"],
            None,
        )
    basis = str(raw_value.get("time_basis", "UNRESOLVED"))
    normalized_from = _optional_string(raw_value.get("normalized_from"))
    if basis == "UNRESOLVED":
        return (
            EventTimeHypothesisV02(
                time_basis="UNRESOLVED",
                normalized_from=normalized_from,
            ),
            [],
            None,
        )
    source_zone = _source_timezone(source_observed_at)
    start, start_resolved = _parse_datetime(raw_value.get("start"), source_zone)
    end, end_resolved = _parse_datetime(
        raw_value.get("end"),
        start.tzinfo if start is not None else source_zone,
    )
    if start is None or (raw_value.get("end") is not None and end is None):
        return (
            EventTimeHypothesisV02(
                time_basis="UNRESOLVED",
                normalized_from=normalized_from,
            ),
            ["EVENT_TIME_UNRESOLVED"],
            None,
        )
    resolved = start_resolved or end_resolved
    provenance = "SOURCE_OBSERVED_TIMEZONE_ONLY" if resolved else "MODEL_EXPLICIT_OFFSET"
    try:
        event_time = EventTimeHypothesisV02(
            start=start,
            end=end,
            time_basis=basis,  # type: ignore[arg-type]
            normalized_from=normalized_from,
        )
    except ValidationError:
        return (
            EventTimeHypothesisV02(
                time_basis="UNRESOLVED",
                normalized_from=normalized_from,
            ),
            ["EVENT_TIME_UNRESOLVED"],
            None,
        )
    return event_time, [], provenance


def _parse_datetime(
    value: object,
    fallback_zone: tzinfo | None,
) -> tuple[datetime | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str) or not value.strip():
        return None, False
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None, False
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed, False
    if fallback_zone is None:
        return None, False
    return parsed.replace(tzinfo=fallback_zone), True


def _source_timezone(value: object) -> tzinfo | None:
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tzinfo


def _response_rows(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise GroundedInterpretationV03Error("DG27_V03_MODEL_CHOICE_COUNT_INVALID")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise GroundedInterpretationV03Error("DG27_V03_MODEL_CHOICE_INVALID")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise GroundedInterpretationV03Error("DG27_V03_MODEL_CONTENT_MISSING")
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as error:
        raise GroundedInterpretationV03Error("DG27_V03_MODEL_JSON_INVALID") from error
    candidates = decoded.get("candidates") if isinstance(decoded, Mapping) else None
    if not isinstance(candidates, Mapping) or any(
        not isinstance(candidate_id, str) or not isinstance(row, Mapping)
        for candidate_id, row in candidates.items()
    ):
        raise GroundedInterpretationV03Error("DG27_V03_MODEL_BATCH_INVALID")
    return [
        {"candidate_id": candidate_id, **row}
        for candidate_id, raw_row in candidates.items()
        for row in [raw_row if isinstance(raw_row, Mapping) else {}]
    ]


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GroundedInterpretationV03Error(f"DG27_V03_MAPPING_REQUIRED:{source}")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


__all__ = [
    "DG27_V03_RESPONSE_SCHEMA",
    "DG27_V03_SYSTEM_PROMPT",
    "GroundedInterpretationExecutionV03",
    "GroundedInterpretationV03Error",
    "HypothesisMaterializationV03",
    "LocalDispositionV03",
    "LoopbackGroundedInterpretationAdapterV03",
    "materialize_hypothesis_v03",
    "response_schema_for_candidates",
]
