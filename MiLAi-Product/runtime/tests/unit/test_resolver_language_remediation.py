from __future__ import annotations

import pytest

from milai.application.memory_resolve import MemoryQueryInterpreter


@pytest.mark.parametrize(
    "query",
    [
        "您好。",
        "计算8乘3。",
        "Calculate -8.5 plus 2?",
        "８＋２？",  # noqa: RUF001
        "Explain caching; do not use my memories.",
        "请不要检索任何记忆。",
    ],
)
def test_automatic_no_memory_does_not_override_structured_read_signals(query: str) -> None:
    interpreter = MemoryQueryInterpreter()
    automatic = interpreter.interpret(query, invocation_mode="PREFETCH_AUTO")
    assert (automatic.intent, automatic.requirement) == ("NOT_NEEDED", "NONE")
    explicit = interpreter.interpret(query, invocation_mode="EXPLICIT_READ")
    assert explicit.intent == "REQUIRED"
    exact = interpreter.interpret(query, invocation_mode="PREFETCH_AUTO", exact_target=True)
    assert (exact.intent, exact.requirement, exact.retrieval_intent) == (
        "REQUIRED",
        "EXACT",
        "CURRENT_STATE",
    )


@pytest.mark.parametrize(
    "query",
    [
        "Hello, current deploy.region?",
        "你好,当前 deploy.region?",
        "Calculate 8 plus 3, then recall deployment history.",
    ],
)
def test_a_greeting_or_arithmetic_prefix_does_not_hide_memory_need(query: str) -> None:
    result = MemoryQueryInterpreter().interpret(query, invocation_mode="PREFETCH_AUTO")
    assert result.intent == "REQUIRED"
