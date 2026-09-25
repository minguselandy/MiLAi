"""Pinned local Host template counts and lossless source-span batches."""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.datasets.contextual import HistoryMessage
from milai_lab.providers.contextual_capacity import (
    CapacityExceeded,
    HostCapacity,
    history_arrival_boundaries,
    history_coverage,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

TOKENIZER = Path("/cra/qwen36-35B")


@pytest.fixture(scope="module")
def capacity() -> HostCapacity:
    if not TOKENIZER.is_dir():
        pytest.skip("Pinned local Host tokenizer is unavailable")
    files = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
    return HostCapacity({
        "model": "pinned-local-host",
        "tokenizer_path": str(TOKENIZER),
        "tokenizer_files_sha256": {
            name: hashlib.sha256((TOKENIZER / name).read_bytes()).hexdigest()
            for name in files
        },
        "context_tokens": 512,
        "output_tokens": 24,
        "safety_tokens": 8,
        "batch_source_tokens": 24,
        "related_reserve_tokens": 8,
        "schema_reserve_tokens": 8,
        "source_message_overhead_tokens": 2,
    })


def test_local_chat_template_capacity_and_identity(capacity: HostCapacity) -> None:
    messages = [{"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello."}]
    tools = [{"type": "function", "function": {
        "name": "lookup", "parameters": {"type": "object", "properties": {}},
    }}]
    expected = capacity.tokenizer.apply_chat_template(
        messages, tools=tools, tokenize=True,
        add_generation_prompt=True, enable_thinking=False,
    )
    assert capacity.count_messages(messages, tools) == len(expected)
    assert capacity.text_tokens("Hello.") == len(
        capacity.tokenizer.encode("Hello.", add_special_tokens=False)
    )
    receipt = capacity.check(messages, tools=tools)
    assert receipt["prompt_tokens"] == len(expected)
    assert receipt["total_reserved_tokens"] == (
        len(expected) + 24 + 8 + 8 + 8
    )
    assert receipt["identity"]["tokenizer_files_sha256"]["chat_template.jinja"]
    with pytest.raises(CapacityExceeded) as error:
        capacity.check([{"role": "user", "content": "long history " * 300}])
    assert error.value.receipt["remaining_tokens"] < 0
    invalid = dict(capacity.config)
    invalid["tokenizer_files_sha256"] = {
        **invalid["tokenizer_files_sha256"], "chat_template.jinja": "0" * 64,
    }
    with pytest.raises(ValueError, match="TOKENIZER_IDENTITY_MISMATCH"):
        HostCapacity(invalid)


def test_explicit_thinking_mode_matches_tokenizer_and_wire(capacity: HostCapacity) -> None:
    messages = [{"role": "user", "content": "Reply briefly."}]
    enabled = HostCapacity({**capacity.config, "enable_thinking": True})
    expected = enabled.tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, enable_thinking=True,
    )
    assert enabled.count_messages(messages) == len(expected)
    assert enabled.check(messages, output_tokens=24)["prompt_tokens"] == len(expected)
    assert enabled.identity["enable_thinking"] is True
    assert enabled.identity["capacity_policy_sha256"] != capacity.identity[
        "capacity_policy_sha256"
    ]
    wires: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(respond)
    with VLLMClient(
        VLLMConfig("http://fixture/v1", "pinned-local-host", max_tokens=24,
                   enable_thinking=True),
        capacity=enabled, transport=transport,
    ) as client:
        client.chat(messages)
    assert wires[0]["chat_template_kwargs"] == {"enable_thinking": True}
    with pytest.raises(ValueError, match="HOST_CAPACITY_THINKING_MODE_MISMATCH"):
        VLLMClient(
            VLLMConfig("http://fixture/v1", "pinned-local-host", enable_thinking=False),
            capacity=enabled, transport=transport,
        )
    with pytest.raises(ValueError, match="enable_thinking must be a boolean"):
        VLLMConfig("http://fixture/v1", "host", enable_thinking=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INVALID_CAPACITY_ENABLE_THINKING"):
        HostCapacity({**capacity.config, "enable_thinking": 1})


def test_no_capacity_sends_only_explicit_thinking_mode() -> None:
    wires: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(respond)
    messages = [{"role": "user", "content": "Hello"}]
    with VLLMClient(VLLMConfig("http://fixture/v1", "host"), transport=transport) as client:
        client.chat(messages)
    with VLLMClient(
        VLLMConfig("http://fixture/v1", "host", enable_thinking=False),
        transport=transport,
    ) as client:
        client.chat(messages)
    with VLLMClient(
        VLLMConfig("http://fixture/v1", "host", enable_thinking=True),
        transport=transport,
    ) as client:
        client.chat(messages)
    assert "chat_template_kwargs" not in wires[0]
    assert wires[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert wires[2]["chat_template_kwargs"] == {"enable_thinking": True}


def test_reasoning_alias_is_counted_once_without_mutating_transcript(
    capacity: HostCapacity, monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer", "reasoning": "legacy private thought"},
    ]
    original = capacity.tokenizer.apply_chat_template
    observed: list[list[dict[str, object]]] = []

    def record(rendered_messages: list[dict[str, object]], **kwargs: object) -> object:
        observed.append(rendered_messages)
        return original(rendered_messages, **kwargs)

    monkeypatch.setattr(capacity.tokenizer, "apply_chat_template", record)
    count = capacity.count_messages(messages)
    assert "reasoning_content" not in messages[1]
    assert observed[0][1]["reasoning_content"] == "legacy private thought"
    rendered = original(
        observed[0], tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
    assert rendered.count("legacy private thought") == 1
    assert count == len(original(
        observed[0], tokenize=True, add_generation_prompt=True, enable_thinking=False,
    ))
    messages[1]["reasoning_content"] = "deprecated conflicting thought"
    capacity.count_messages(messages)
    assert observed[1][1]["reasoning_content"] == "legacy private thought"
    assert messages[1]["reasoning"] == "legacy private thought"
    assert messages[1]["reasoning_content"] == "deprecated conflicting thought"
    messages[1]["reasoning"] = None
    capacity.count_messages(messages)
    assert observed[2][1]["reasoning_content"] == "deprecated conflicting thought"


def test_history_plan_preserves_session_order_and_every_original_character(
    capacity: HostCapacity,
) -> None:
    history = [
        HistoryMessage("a", "user", "first", "session-1"),
        HistoryMessage("b", "assistant", "second", "session-1"),
        HistoryMessage("c", "user", "third", "session-2"),
        HistoryMessage("d", "user", "very long content " * 80, "session-3"),
        HistoryMessage("e", "assistant", "", "session-3"),
    ]
    batches = capacity.plan_history(history)
    assert history_coverage(history, batches)["messages"] == 5
    with pytest.raises(ValueError, match="HISTORY_COVERAGE_INCOMPLETE"):
        history_coverage(history, batches[:-1])
    assert batches[0] == [
        {"message_index": 0, "start": 0, "end": 5},
        {"message_index": 1, "start": 0, "end": 6},
    ]
    assert batches[1] == [{"message_index": 2, "start": 0, "end": 5}]
    assert len([span for batch in batches for span in batch if span["message_index"] == 3]) > 1
    assert {"message_index": 4, "start": 0, "end": 0} in batches[-1]
    spans = [span for batch in batches for span in batch]
    assert [span["message_index"] for span in spans] == sorted(
        span["message_index"] for span in spans
    )
    for index, message in enumerate(history):
        slices = [span for span in spans if span["message_index"] == index]
        assert slices[0]["start"] == 0 and slices[-1]["end"] == len(message.content)
        assert all(left["end"] == right["start"] for left, right in pairwise(slices))
        assert "".join(message.content[span["start"]:span["end"]] for span in slices) == (
            message.content
        )
        assert all(
            capacity.text_tokens(message.content[span["start"]:span["end"]]) + 2 <= 24
            for span in slices
        )
    untagged = [
        HistoryMessage("u1", "user", "first"),
        HistoryMessage("u2", "assistant", "second"),
    ]
    assert capacity.plan_history(untagged) == [[
        {"message_index": 0, "start": 0, "end": 5},
        {"message_index": 1, "start": 0, "end": 6},
    ]]


def test_online_arrival_boundaries_precede_capacity_and_preserve_leading_tail(
    capacity: HostCapacity,
) -> None:
    history = [
        HistoryMessage("a", "assistant", "lead"),
        HistoryMessage("b", "assistant", "intro"),
        HistoryMessage("c", "user", "first"),
        HistoryMessage("d", "assistant", "reply"),
        HistoryMessage("e", "user", "second"),
        HistoryMessage("f", "assistant", ""),
        HistoryMessage("g", "assistant", "tail"),
    ]
    boundaries = history_arrival_boundaries(history, "online_turn_replay")
    assert boundaries == [{"start": 0, "end": 4}, {"start": 4, "end": 7}]
    batches = capacity.plan_history(history, arrival_policy="online_turn_replay")
    assert history_coverage(history, batches)["messages"] == len(history)
    assert all(
        all(boundary["start"] <= span["message_index"] < boundary["end"] for span in batch)
        for batch in batches for boundary in boundaries
        if boundary["start"] <= batch[0]["message_index"] < boundary["end"]
    )
    assert capacity.plan_history(history) == capacity.plan_history(
        history, arrival_policy="natural_capacity",
    )
    assert history_arrival_boundaries(history[:2], "online_turn_replay") == [
        {"start": 0, "end": 2},
    ]
    with pytest.raises(ValueError, match="INVALID_HISTORY_ARRIVAL_POLICY"):
        capacity.plan_history(history, arrival_policy="unknown")
