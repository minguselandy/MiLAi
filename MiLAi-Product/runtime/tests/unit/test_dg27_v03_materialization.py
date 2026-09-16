from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from milai.adapters.grounded_interpretation_v03 import (
    DG27_V03_SYSTEM_PROMPT,
    GroundedInterpretationV03Error,
    LoopbackGroundedInterpretationAdapterV03,
    materialize_hypothesis_v03,
    response_schema_for_candidates,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import EvidenceRequirementV02


def _raw(
    quote: str,
    *,
    event_time: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "relation": "SUPPORT",
        "grounded_quotes": [quote],
        "normalized_subjects": ["espresso machine"],
        "normalized_predicate": "buy",
        "normalized_value": "espresso machine",
        "normalized_unit": None,
        "event_time_hypothesis": event_time,
        "confidence_feature": 0.8,
    }


def _requirement() -> EvidenceRequirementV02:
    request = RetrievalRequest(
        route="L1",
        consistency="CANONICAL_REQUIRED",
        query="What did I buy?",
        as_of=datetime(2026, 8, 30, tzinfo=UTC),
        reference_time=datetime(2026, 8, 30, tzinfo=UTC),
        system_as_of=datetime(2026, 8, 30, tzinfo=UTC),
    )
    query_ir = QueryPlanner().plan(request).memory_query_ir
    assert query_ir is not None
    return next(item for item in query_ir.requirements if item.required)


def test_unique_unicode_quote_derives_python_offsets() -> None:
    content = "用户说\uff1aI bought an espresso machine on February 26th ☕"
    quote = "I bought an espresso machine on February 26th"

    hypothesis, disposition = materialize_hypothesis_v03(
        candidate_id="candidate-1",
        requirement_id="TARGET_EVENT",
        hypothesis_index=0,
        hypothesis_id="a" * 64,
        raw=_raw(quote),
        content=content,
        source_observed_at="2024-03-01T00:00:00+00:00",
    )

    assert hypothesis is not None
    assert disposition.disposition == "VALID"
    [span] = hypothesis.grounded_spans
    assert content[span.start : span.end] == quote
    assert span.end - span.start == len(quote)


def test_non_unique_quote_rejects_only_that_hypothesis() -> None:
    hypothesis, disposition = materialize_hypothesis_v03(
        candidate_id="candidate-1",
        requirement_id="TARGET_EVENT",
        hypothesis_index=0,
        hypothesis_id="b" * 64,
        raw=_raw("espresso machine"),
        content="espresso machine and another espresso machine",
        source_observed_at="2024-03-01T00:00:00+00:00",
    )

    assert hypothesis is None
    assert disposition.disposition == "REJECTED_PROTOCOL"
    assert disposition.reason_codes == ["GROUNDED_QUOTE_NON_UNIQUE"]


def test_explicit_irrelevant_is_a_legal_local_disposition() -> None:
    raw = _raw("")
    raw.update(
        {
            "relation": "IRRELEVANT",
            "grounded_quotes": [],
            "normalized_subjects": [],
            "normalized_predicate": None,
            "normalized_value": None,
            "confidence_feature": None,
        }
    )

    hypothesis, disposition = materialize_hypothesis_v03(
        candidate_id="candidate-1",
        requirement_id="TARGET_EVENT",
        hypothesis_index=0,
        hypothesis_id="e" * 64,
        raw=raw,
        content="Unrelated but interpretable content.",
        source_observed_at="2024-03-01T00:00:00+00:00",
    )

    assert hypothesis is not None
    assert hypothesis.relation == "IRRELEVANT"
    assert disposition.disposition == "VALID"


def test_naive_event_time_uses_only_source_timezone_context() -> None:
    raw = _raw(
        "I bought an espresso machine on February 26th",
        event_time={
            "start": "2024-02-26",
            "end": "2024-02-26",
            "time_basis": "EXPLICIT_EVENT_TIME",
            "normalized_from": "February 26th",
        },
    )

    hypothesis, disposition = materialize_hypothesis_v03(
        candidate_id="candidate-1",
        requirement_id="TARGET_EVENT",
        hypothesis_index=0,
        hypothesis_id="c" * 64,
        raw=raw,
        content="I bought an espresso machine on February 26th",
        source_observed_at="2024-03-01T10:00:00+08:00",
    )

    assert hypothesis is not None
    assert disposition.disposition == "VALID"
    assert disposition.timezone_resolution_provenance == (
        "SOURCE_OBSERVED_TIMEZONE_ONLY"
    )
    assert hypothesis.event_time_hypothesis is not None
    assert hypothesis.event_time_hypothesis.start == datetime(
        2024, 2, 26, tzinfo=datetime.fromisoformat("2024-01-01T00:00:00+08:00").tzinfo
    )


def test_naive_event_time_without_timezone_is_downgraded_not_aborted() -> None:
    raw = _raw(
        "I bought an espresso machine on February 26th",
        event_time={
            "start": "2024-02-26",
            "end": None,
            "time_basis": "EXPLICIT_EVENT_TIME",
            "normalized_from": "February 26th",
        },
    )

    hypothesis, disposition = materialize_hypothesis_v03(
        candidate_id="candidate-1",
        requirement_id="TARGET_EVENT",
        hypothesis_index=0,
        hypothesis_id="d" * 64,
        raw=raw,
        content="I bought an espresso machine on February 26th",
        source_observed_at="2024-03-01T10:00:00",
    )

    assert hypothesis is not None
    assert disposition.disposition == "DOWNGRADED_UNRESOLVED"
    assert disposition.reason_codes == ["EVENT_TIME_UNRESOLVED"]
    assert hypothesis.event_time_hypothesis is not None
    assert hypothesis.event_time_hypothesis.time_basis == "UNRESOLVED"


class _FixtureAdapter(LoopbackGroundedInterpretationAdapterV03):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(model_id="fixture-model")
        self._rows = rows

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
        del payload
        return {
            "id": "fixture-response",
            "model": "fixture-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "candidates": {
                                    str(row["candidate_id"]): {
                                        key: value
                                        for key, value in row.items()
                                        if key != "candidate_id"
                                    }
                                    for row in self._rows
                                }
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def test_prompt_defines_atomic_support_not_whole_query_answering() -> None:
    assert "atomic evidence role" in DG27_V03_SYSTEM_PROMPT
    assert "does not need to contain other operands" in DG27_V03_SYSTEM_PROMPT
    assert "Do not use CONTEXT_ONLY merely" in DG27_V03_SYSTEM_PROMPT


def test_bad_hypothesis_does_not_abort_unrelated_valid_hypothesis() -> None:
    candidate_id = "candidate-1"
    rows = [
        {
            "candidate_id": candidate_id,
            "hypotheses": [
                _raw("quote that is absent"),
                _raw("I bought an espresso machine"),
            ],
            "ambiguity_reasons": [],
        }
    ]
    adapter = _FixtureAdapter(rows)
    content = "I bought an espresso machine yesterday."

    execution = adapter.interpret(
        query="What did I buy?",
        requirement=_requirement(),
        candidates=[
            {
                "evidence_id": candidate_id,
                "content": content,
                "content_hash": canonical_sha256(content),
                "observed_at": "2026-08-29T00:00:00+00:00",
            }
        ],
    )

    assert [item.disposition for item in execution.materializations] == [
        "REJECTED_PROTOCOL",
        "VALID",
    ]
    assert len(execution.interpretation_sets[0].hypotheses) == 1


def test_irrelevance_explanation_does_not_become_semantic_ambiguity() -> None:
    raw = _raw("")
    raw.update(
        {
            "relation": "IRRELEVANT",
            "grounded_quotes": [],
            "normalized_subjects": [],
            "normalized_predicate": None,
            "normalized_value": None,
            "confidence_feature": None,
        }
    )
    adapter = _FixtureAdapter(
        [
            {
                "candidate_id": "candidate-1",
                "hypotheses": [raw],
                "ambiguity_reasons": ["This candidate discusses another topic."],
            }
        ]
    )

    execution = adapter.interpret(
        query="What did I buy?",
        requirement=_requirement(),
        candidates=[
            {
                "evidence_id": "candidate-1",
                "content": "I discussed mortgage rates.",
                "observed_at": "2026-08-29T00:00:00+00:00",
            }
        ],
    )

    [interpretation_set] = execution.interpretation_sets
    assert interpretation_set.ambiguity_reasons == []


def test_candidate_identity_drift_remains_batch_fatal() -> None:
    adapter = _FixtureAdapter(
        [
            {
                "candidate_id": "foreign-candidate",
                "hypotheses": [],
                "ambiguity_reasons": [],
            }
        ]
    )

    with pytest.raises(
        GroundedInterpretationV03Error,
        match="DG27_V03_MODEL_BATCH_IDENTITY_DRIFT",
    ):
        adapter.interpret(
            query="What did I buy?",
            requirement=_requirement(),
            candidates=[
                {
                    "evidence_id": "candidate-1",
                    "content": "I bought an espresso machine.",
                    "observed_at": "2026-08-29T00:00:00+00:00",
                }
            ],
        )


def test_exact_candidate_bijection_may_be_returned_in_different_order() -> None:
    adapter = _FixtureAdapter(
        [
            {
                "candidate_id": "candidate-2",
                "hypotheses": [],
                "ambiguity_reasons": [],
            },
            {
                "candidate_id": "candidate-1",
                "hypotheses": [],
                "ambiguity_reasons": [],
            },
        ]
    )

    execution = adapter.interpret(
        query="What did I buy?",
        requirement=_requirement(),
        candidates=[
            {
                "evidence_id": "candidate-1",
                "content": "I bought an espresso machine.",
                "observed_at": "2026-08-29T00:00:00+00:00",
            },
            {
                "evidence_id": "candidate-2",
                "content": "I bought a grill.",
                "observed_at": "2026-08-29T00:00:00+00:00",
            },
        ],
    )

    assert [item.candidate_id for item in execution.interpretation_sets] == [
        "candidate-1",
        "candidate-2",
    ]


def test_request_scoped_schema_requires_exact_candidate_keys() -> None:
    schema = response_schema_for_candidates(["candidate-1", "candidate-2"])
    candidates = schema["properties"]["candidates"]

    assert candidates["additionalProperties"] is False
    assert candidates["required"] == ["candidate-1", "candidate-2"]
    assert set(candidates["properties"]) == {"candidate-1", "candidate-2"}


@pytest.mark.parametrize(
    "rows",
    [
        [
            {
                "candidate_id": "candidate-1",
                "hypotheses": [],
                "ambiguity_reasons": [],
            }
        ],
        [
            {
                "candidate_id": "candidate-1",
                "hypotheses": [],
                "ambiguity_reasons": [],
            },
            {
                "candidate_id": "candidate-1",
                "hypotheses": [],
                "ambiguity_reasons": [],
            },
        ],
    ],
    ids=["missing", "duplicate"],
)
def test_non_bijective_candidate_identity_remains_batch_fatal(
    rows: list[dict[str, Any]],
) -> None:
    adapter = _FixtureAdapter(rows)

    with pytest.raises(
        GroundedInterpretationV03Error,
        match="DG27_V03_MODEL_BATCH_IDENTITY_DRIFT",
    ):
        adapter.interpret(
            query="What did I buy?",
            requirement=_requirement(),
            candidates=[
                {
                    "evidence_id": "candidate-1",
                    "content": "I bought an espresso machine.",
                    "observed_at": "2026-08-29T00:00:00+00:00",
                },
                {
                    "evidence_id": "candidate-2",
                    "content": "I bought a grill.",
                    "observed_at": "2026-08-29T00:00:00+00:00",
                },
            ],
        )
