"""Scoped public LiteLLM completion bridge for the unmodified MERIT tool loop."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from openai.types.chat import ChatCompletion

from milai_lab.providers.contextual_vllm import VLLMClient

MODULE_ATTRIBUTES = ("completion", "register_model", "num_retries", "drop_params",
                     "request_timeout")
TRANSPORT_CONTRACT = {
    "runner": "official merit.runner.run_episode; real model name",
    "transport": "scoped public litellm.completion -> VLLMClient",
    "hidden_retries": 0,
    "upstream_num_retries": "upstream assigns 5; bridge performs exactly one HTTP attempt",
    "pricing_registration": "irrelevant upstream Claude registration suppressed in scope",
    "module_restoration": list(MODULE_ATTRIBUTES),
}


def completion(client: VLLMClient, **kwargs: Any) -> ChatCompletion:
    """Return a real public OpenAI response object, preserving actual usage and call IDs."""
    if (kwargs.get("model") != client.config.model
            or kwargs.get("temperature") != client.config.temperature
            or set(kwargs) - {"model", "messages", "tools", "temperature", "api_base"}
            or client.config.tool_mode != "native"):
        raise ValueError("MERIT_TRANSPORT_PARAMETERS_CHANGED")
    receipt = client.chat(kwargs["messages"], kwargs.get("tools"), tool_choice="auto")
    response = ChatCompletion.model_validate(receipt)
    if len(response.choices) != 1:
        raise ValueError("MERIT_RESPONSE_CHOICES_INVALID")
    choice = response.choices[0]
    if choice.finish_reason not in {"stop", "tool_calls"}:
        raise ValueError("MERIT_RESPONSE_INCOMPLETE")
    calls = choice.message.tool_calls or []
    ids = [call.id for call in calls]
    if any(not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("MERIT_RESPONSE_TOOL_IDS_INVALID")
    for call in calls:
        if call.type != "function" or not isinstance(json.loads(call.function.arguments), dict):
            raise ValueError("MERIT_RESPONSE_ARGUMENTS_INVALID")
    if not calls and (not isinstance(choice.message.content, str)
                      or not choice.message.content.strip()):
        raise ValueError("MERIT_RESPONSE_FINAL_MISSING")
    if response.usage is None:
        raise ValueError("MERIT_RESPONSE_USAGE_MISSING")
    return response


@contextmanager
def metered_litellm(client: VLLMClient) -> Iterator[list[dict[str, Any]]]:
    """No replacement module, no SDK network path, and no process-wide residue after use.

    The caller must serialize benchmark execution. This temporary public-module binding
    is intentionally not a concurrent global-provider registration mechanism.
    """
    sdk: Any = importlib.import_module("litellm")
    missing = object()
    saved = {key: getattr(sdk, key, missing)
             for key in MODULE_ATTRIBUTES}
    calls: list[dict[str, Any]] = []

    def metered(**kwargs: Any) -> ChatCompletion:
        result = completion(client, **kwargs)
        message = result.choices[0].message
        assert result.usage is not None  # completion validates the real usage above.
        calls.append({"generation_id": result.id,
            "public_index": sum(row["role"] == "user" for row in kwargs["messages"]) - 1,
            "tool_call_ids": [call.id for call in message.tool_calls or []],
            "final_reply": not bool(message.tool_calls), "usage": result.usage.model_dump()})
        return result

    try:
        sdk.completion = metered
        sdk.register_model = lambda *_args, **_kwargs: None
        yield calls
    finally:
        for key, value in saved.items():
            if value is missing:
                if hasattr(sdk, key):
                    delattr(sdk, key)
            else:
                setattr(sdk, key, value)
