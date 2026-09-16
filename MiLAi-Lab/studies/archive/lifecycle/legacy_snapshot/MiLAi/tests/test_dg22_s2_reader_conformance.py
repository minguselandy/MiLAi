from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from evals.dg14.provider import ReaderConformanceError, _parse_completion
from evals.dg22.reader_conformance import (
    conformance_matrix,
    diagnosis_matrix,
    materialize_cell,
    successor_ceiling_authorized,
)


def test_dg22_reader_parser_classifies_exact_output_limit_evidence() -> None:
    content = '{"answer":"unfinished'
    response = {
        "id": "request-12345678",
        "choices": [{"message": {"content": content}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 256},
    }
    with pytest.raises(ReaderConformanceError) as caught:
        _parse_completion(response, {}, 10)

    assert caught.value.failure_class == "OUTPUT_LIMIT_TRUNCATED"
    assert caught.value.metadata == {
        "native_request_id": "request-12345678",
        "finish_reason": "length",
        "completion_tokens": 256,
        "content_byte_length": len(content.encode()),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "truncated_json_prefix": True,
    }


def test_dg22_reader_parser_never_salvages_schema_or_json_failures() -> None:
    base: dict[str, Any] = {
        "id": "request-12345678",
        "choices": [{"message": {"content": "not-json"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }
    with pytest.raises(ReaderConformanceError) as caught:
        _parse_completion(base, {}, 10)
    assert caught.value.failure_class == "CONTENT_NOT_JSON"

    base["choices"][0]["message"]["content"] = json.dumps({"wrong": "field"})
    with pytest.raises(ReaderConformanceError) as caught:
        _parse_completion(base, {}, 10)
    assert caught.value.failure_class == "SCHEMA_VIOLATION"


def test_dg22_s2_matrix_covers_required_axes_and_has_unique_identities() -> None:
    diagnosis = diagnosis_matrix()
    conformance = conformance_matrix()

    assert len(diagnosis) == 8
    assert len(conformance) == 32
    assert len({row["cell_id"] for row in diagnosis + conformance}) == 40
    assert {row["token_budget"] for row in conformance} == {512, 2048}
    assert {row["answer_shape"] for row in conformance} == {
        "lookup",
        "count",
        "date",
        "list",
        "UNKNOWN",
    }
    assert {row["context_size"] for row in conformance} == {"short", "near_budget"}
    assert {row["unicode"] for row in conformance} == {
        "ASCII",
        "CJK",
        "punctuation-heavy",
    }
    assert {row["expected_answer_length"] for row in conformance} == {
        "short",
        "bounded-long",
    }
    assert all(all(materialize_cell(row)) for row in diagnosis + conformance)


def test_dg22_successor_requires_all_three_observed_conditions() -> None:
    valid = [
        {
            "status": "FAILED",
            "failure_class": "OUTPUT_LIMIT_TRUNCATED",
            "finish_reason": "length",
            "completion_tokens": 256,
            "truncated_json_prefix": True,
        }
    ]
    assert successor_ceiling_authorized(valid)
    for key in ("finish_reason", "completion_tokens", "truncated_json_prefix"):
        mutated = [dict(valid[0])]
        mutated[0][key] = None
        assert not successor_ceiling_authorized(mutated)
