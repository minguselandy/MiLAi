from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from milai_openworker_mcp.reader_session import (
    ReaderModelProfile,
    ReaderProviderRound,
    ReaderSessionError,
    ReaderSessionInput,
    VllmEvidenceReaderSession,
    calculate,
)


def _request() -> ReaderSessionInput:
    return ReaderSessionInput(
        question="How many items are there?",
        reader_visible_context="[E1] There is one hat.\n[E2] There are two shirts.",
        visible_evidence_aliases=("E1", "E2"),
        source_identity_digest="a" * 64,
        model_profile=ReaderModelProfile(model_id="Qwen3.6-35B-A3B-FP8"),
    )


def _base_payload() -> dict[str, Any]:
    return {
        "model": "Qwen3.6-35B-A3B-FP8",
        "messages": [
            {
                "role": "system",
                "content": "MILAI_CONTEXT_BEGIN\n[E1] one hat\n[E2] two shirts\nMILAI_CONTEXT_END",
            },
            {"role": "user", "content": "How many items are there?"},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "tools": [{"type": "function", "function": {"name": "read"}}],
        "tool_choice": "auto",
        "seed": 7,
    }


def _round(content: Mapping[str, object], ordinal: int) -> ReaderProviderRound:
    return ReaderProviderRound(
        logical_request_id=f"logical-reader-{ordinal}",
        native_request_id=f"native-reader-{ordinal}",
        content=json.dumps(content),
        finish_reason="stop",
        prompt_tokens=20,
        completion_tokens=10,
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", "7"),
        ("(50000 / 500000) * 100", "10"),
        ("1 / 8", "0.125"),
        ("-2 + +5", "3"),
    ],
)
def test_calculator_accepts_only_bounded_decimal_arithmetic(
    expression: str,
    expected: str,
) -> None:
    assert calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/tmp/x')",
        "x + 1",
        "2 ** 8",
        "1 // 2",
        "1 / 0",
        "[1][0]",
        "1" * 257,
    ],
)
def test_calculator_rejects_code_io_and_unbounded_or_unsupported_syntax(
    expression: str,
) -> None:
    with pytest.raises(ReaderSessionError):
        calculate(expression)


def test_reader_can_answer_directly_without_requiring_citations() -> None:
    observed: list[Mapping[str, Any]] = []

    def invoke(payload: Mapping[str, Any], ordinal: int) -> ReaderProviderRound:
        observed.append(payload)
        return _round(
            {
                "action": "ANSWER",
                "answer_text": "There are three items.",
                "evidence_aliases": [],
                "expressions": [],
            },
            ordinal,
        )

    result = VllmEvidenceReaderSession(_request()).run(_base_payload(), invoke)

    assert result.answer_text == "There are three items."
    assert result.valid_cited_aliases == ()
    assert result.citation_supplied is False
    assert result.tool_calls == ()
    assert result.stop_reason == "ANSWER"
    assert result.provider_usage == {
        "rounds": 1,
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }
    assert len(observed) == 1
    assert observed[0]["stream"] is False
    assert "stream_options" not in observed[0]
    assert "tools" not in observed[0]
    assert "tool_choice" not in observed[0]
    assert "seed" not in observed[0]
    assert observed[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert observed[0]["response_format"]["json_schema"]["name"] == "ReaderActionV01"


def test_reader_executes_multiple_calculations_and_reinjects_standard_tool_results() -> None:
    observed: list[Mapping[str, Any]] = []

    def invoke(payload: Mapping[str, Any], ordinal: int) -> ReaderProviderRound:
        observed.append(payload)
        if ordinal == 1:
            return _round(
                {
                    "action": "CALCULATE",
                    "answer_text": "",
                    "evidence_aliases": ["E1"],
                    "expressions": ["1 + 2", "50000 / 500000 * 100"],
                },
                ordinal,
            )
        return _round(
            {
                "answer_text": "There are 3 items, and the percentage is 10%.",
                "evidence_aliases": ["[E1]", "E2", "E99", "E2"],
            },
            ordinal,
        )

    result = VllmEvidenceReaderSession(_request()).run(_base_payload(), invoke)

    assert result.answer_text == "There are 3 items, and the percentage is 10%."
    assert result.valid_cited_aliases == ("E1", "E2")
    assert result.citation_supplied is True
    assert result.invalid_citation_count == 1
    assert [item.value for item in result.tool_calls] == ["3", "10"]
    assert result.stop_reason == "CALCULATOR_ANSWER"
    assert result.provider_usage["rounds"] == 2
    assert len(observed) == 2
    final_messages = observed[1]["messages"]
    assistant = final_messages[-3]
    assert assistant["role"] == "assistant"
    assert [call["function"]["name"] for call in assistant["tool_calls"]] == [
        "calculator",
        "calculator",
    ]
    assert [json.loads(message["content"])["value"] for message in final_messages[-2:]] == [
        "3",
        "10",
    ]
    assert all(message["role"] == "tool" for message in final_messages[-2:])
    assert observed[1]["response_format"]["json_schema"]["name"] == (
        "ReaderFinalAnswerV01"
    )


@pytest.mark.parametrize(
    "first",
    [
        {"action": "ANSWER", "answer_text": "", "evidence_aliases": [], "expressions": []},
        {
            "action": "ANSWER",
            "answer_text": "answer",
            "evidence_aliases": [],
            "expressions": ["1+1"],
        },
        {
            "action": "CALCULATE",
            "answer_text": "",
            "evidence_aliases": [],
            "expressions": [],
        },
        {
            "action": "CALCULATE",
            "answer_text": "",
            "evidence_aliases": [],
            "expressions": ["open('/tmp/x')"],
        },
    ],
)
def test_reader_rejects_invalid_action_or_tool_arguments_without_an_open_loop(
    first: Mapping[str, object],
) -> None:
    calls = 0

    def invoke(payload: Mapping[str, Any], ordinal: int) -> ReaderProviderRound:
        nonlocal calls
        del payload
        calls += 1
        return _round(first, ordinal)

    with pytest.raises(ReaderSessionError) as captured:
        VllmEvidenceReaderSession(_request()).run(_base_payload(), invoke)

    assert calls == 1
    assert len(captured.value.rounds) == 1


def test_reader_rejects_incomplete_final_response_after_exactly_two_rounds() -> None:
    calls = 0

    def invoke(payload: Mapping[str, Any], ordinal: int) -> ReaderProviderRound:
        nonlocal calls
        del payload
        calls += 1
        if ordinal == 1:
            return _round(
                {
                    "action": "CALCULATE",
                    "answer_text": "",
                    "evidence_aliases": [],
                    "expressions": ["1 + 2"],
                },
                ordinal,
            )
        response = _round({"answer_text": "3", "evidence_aliases": []}, ordinal)
        return ReaderProviderRound(
            logical_request_id=response.logical_request_id,
            native_request_id=response.native_request_id,
            content=response.content,
            finish_reason="length",
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    with pytest.raises(ReaderSessionError) as captured:
        VllmEvidenceReaderSession(_request()).run(_base_payload(), invoke)

    assert calls == 2
    assert len(captured.value.rounds) == 2
    assert len(captured.value.tool_calls) == 1
    assert captured.value.reason_code == "READER_RESPONSE_INCOMPLETE"
