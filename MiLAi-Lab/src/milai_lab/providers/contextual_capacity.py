"""Pinned local Host token capacity and lossless history-span planning."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer


class CapacityExceeded(ValueError):
    def __init__(self, receipt: dict[str, Any]) -> None:
        super().__init__("HOST_CONTEXT_CAPACITY_EXCEEDED")
        self.receipt = receipt


def _field(message: Any, key: str) -> str:
    value = message[key] if isinstance(message, Mapping) else getattr(message, key)
    if not isinstance(value, str):
        raise ValueError(f"INVALID_HISTORY_{key.upper()}")
    return value


def history_arrival_boundaries(
    history: Sequence[Any],
    policy: str = "natural_capacity",
) -> list[dict[str, int]]:
    """Freeze message-index arrival units before tokenizer-based batching."""
    if policy not in {"natural_capacity", "online_turn_replay"}:
        raise ValueError("INVALID_HISTORY_ARRIVAL_POLICY")
    if not history:
        return []
    if policy == "natural_capacity":
        return [{"start": 0, "end": len(history)}]
    user_starts = [
        index for index, message in enumerate(history) if _field(message, "role") == "user"
    ]
    if not user_starts:
        return [{"start": 0, "end": len(history)}]
    starts = [0, *user_starts[1:]]
    return [
        {"start": start, "end": end}
        for start, end in zip(starts, [*starts[1:], len(history)], strict=True)
    ]


class HostCapacity:
    """Count the local vLLM Host template; final wire requests still require `check`."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self.enable_thinking = config.get("enable_thinking", False)
        if type(self.enable_thinking) is not bool:
            raise ValueError("INVALID_CAPACITY_ENABLE_THINKING")
        path = Path(config["tokenizer_path"])
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("TOKENIZER_PATH_MUST_BE_LOCAL_DIRECTORY")
        self.tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            str(path),
            local_files_only=True,
        )
        self.context_tokens = self._positive("context_tokens")
        self.output_tokens = self._positive("output_tokens")
        self.safety_tokens = self._nonnegative("safety_tokens")
        self.batch_source_tokens = self._positive("batch_source_tokens")
        self.related_reserve_tokens = self._nonnegative("related_reserve_tokens")
        self.schema_reserve_tokens = self._nonnegative("schema_reserve_tokens")
        self.source_message_overhead_tokens = self._nonnegative("source_message_overhead_tokens")
        if (
            self.batch_source_tokens
            + self.output_tokens
            + self.safety_tokens
            + self.related_reserve_tokens
            + self.schema_reserve_tokens
            > self.context_tokens
        ):
            raise ValueError("BATCH_RESERVATION_EXCEEDS_CONTEXT")
        self.identity = {
            "model": config["model"],
            "enable_thinking": self.enable_thinking,
            "tokenizer_path": str(path),
            "capacity_version": config.get("capacity_version", "loaded-local-v1"),
            "chat_template": self.tokenizer.chat_template,
        }

    def _positive(self, name: str) -> int:
        value = self.config[name]
        if type(value) is not int or value <= 0:
            raise ValueError(f"INVALID_CAPACITY_{name.upper()}")
        return value

    def _nonnegative(self, name: str) -> int:
        value = self.config.get(name, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f"INVALID_CAPACITY_{name.upper()}")
        return value

    def text_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("TEXT_TOKENS_REQUIRES_STRING")
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def count_messages(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        enable_thinking: bool | None = None,
    ) -> int:
        thinking = self.enable_thinking if enable_thinking is None else enable_thinking
        if type(thinking) is not bool:
            raise ValueError("INVALID_CAPACITY_ENABLE_THINKING")
        rendered_messages = []
        for message in messages:
            normalized = deepcopy(dict(message))
            if normalized.get("role") == "assistant":
                reasoning = normalized.get("reasoning")
                if reasoning is not None:
                    normalized["reasoning_content"] = reasoning
                elif normalized.get("reasoning_content") is not None:
                    normalized["reasoning"] = normalized["reasoning_content"]
                # OpenAI wire arguments are JSON strings; vLLM decodes them
                # before applying the HF template. Do the same only in this copy.
                for call in normalized.get("tool_calls") or ():
                    if isinstance(call, Mapping):
                        function = call.get("function")
                        if isinstance(function, dict):
                            if arguments := function.get("arguments"):
                                if not isinstance(arguments, (dict, list)):
                                    parsed = json.loads(arguments)
                                    function["arguments"] = parsed if parsed is not None else {}
                            else:
                                function["arguments"] = {}
            rendered_messages.append(normalized)
        rendered = self.tokenizer.apply_chat_template(
            rendered_messages,
            tools=list(tools) if tools else None,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=thinking,
        )
        return len(rendered)

    def check(
        self,
        messages: Sequence[Mapping[str, Any]],
        output_tokens: int | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        reserve = self.output_tokens if output_tokens is None else output_tokens
        if type(reserve) is not int or reserve <= 0:
            raise ValueError("INVALID_OUTPUT_RESERVATION")
        prompt = self.count_messages(
            messages, tools,
            **({"enable_thinking": enable_thinking} if enable_thinking is not None else {}),
        )
        total = (
            prompt
            + reserve
            + self.safety_tokens
            + self.related_reserve_tokens
            + self.schema_reserve_tokens
        )
        receipt = {
            "prompt_tokens": prompt,
            "output_reserve_tokens": reserve,
            "safety_tokens": self.safety_tokens,
            "related_reserve_tokens": self.related_reserve_tokens,
            "schema_reserve_tokens": self.schema_reserve_tokens,
            "context_tokens": self.context_tokens,
            "total_reserved_tokens": total,
            "remaining_tokens": self.context_tokens - total,
            "identity": self.identity if enable_thinking is None else {
                **self.identity, "enable_thinking": enable_thinking,
            },
        }
        if total > self.context_tokens:
            raise CapacityExceeded(receipt)
        return receipt

    def _source_tokens(self, content: str) -> int:
        return self.text_tokens(content) + self.source_message_overhead_tokens

    def _split_oversized(self, index: int, content: str) -> list[dict[str, int]]:
        if not content:
            if self._source_tokens(content) > self.batch_source_tokens:
                raise ValueError("EMPTY_MESSAGE_OVERHEAD_EXCEEDS_SOURCE_TARGET")
            return [{"message_index": index, "start": 0, "end": 0}]
        spans = []
        start = 0
        while start < len(content):
            low, high = start + 1, len(content)
            best = start
            while low <= high:
                end = (low + high) // 2
                if self._source_tokens(content[start:end]) <= self.batch_source_tokens:
                    best = end
                    low = end + 1
                else:
                    high = end - 1
            if best == start:
                raise ValueError("SINGLE_CHARACTER_EXCEEDS_SOURCE_TARGET")
            spans.append({"message_index": index, "start": start, "end": best})
            start = best
        return spans

    def plan_history(
        self,
        history: Sequence[Any],
        *,
        arrival_policy: str = "natural_capacity",
    ) -> list[list[dict[str, int]]]:
        """Honor arrival units, then real sessions, messages and exact character spans."""
        batches: list[list[dict[str, int]]] = []
        for arrival in history_arrival_boundaries(history, arrival_policy):
            position = arrival["start"]
            while position < arrival["end"]:
                session = _field(history[position], "session_id")
                end = position + 1
                while end < arrival["end"] and _field(history[end], "session_id") == session:
                    end += 1
                current: list[dict[str, int]] = []
                used = 0
                for index in range(position, end):
                    content = _field(history[index], "content")
                    size = self._source_tokens(content)
                    if size > self.batch_source_tokens:
                        if current:
                            batches.append(current)
                            current, used = [], 0
                        for span in self._split_oversized(index, content):
                            batches.append([span])
                        continue
                    if current and used + size > self.batch_source_tokens:
                        batches.append(current)
                        current, used = [], 0
                    current.append({"message_index": index, "start": 0, "end": len(content)})
                    used += size
                if current:
                    batches.append(current)
                position = end
        return batches


def history_coverage(
    history: Sequence[Any],
    batches: Sequence[Sequence[dict[str, int]]],
) -> dict[str, Any]:
    """Prove chronological, non-overlapping, complete coverage of immutable input."""
    index, offset, characters = 0, 0, 0
    for batch in batches:
        for span in batch:
            if index >= len(history):
                raise ValueError("HISTORY_COVERAGE_EXTRA_RANGE")
            content = _field(history[index], "content")
            if (
                span["message_index"] != index
                or span["start"] != offset
                or not offset <= span["end"] <= len(content)
                or (span["end"] == offset and content)
            ):
                raise ValueError("HISTORY_COVERAGE_GAP_OR_OVERLAP")
            characters += span["end"] - offset
            offset = span["end"]
            if offset == len(content):
                index, offset = index + 1, 0
    if index != len(history) or offset:
        raise ValueError("HISTORY_COVERAGE_INCOMPLETE")
    return {
        "complete": True,
        "messages": index,
        "characters": characters,
        "ranges": sum(len(batch) for batch in batches),
    }
