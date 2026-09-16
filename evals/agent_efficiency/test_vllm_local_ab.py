from __future__ import annotations

from typing import Any

import pytest

from evals.agent_efficiency import vllm_local_ab as local_ab


def test_component_counts_use_full_no_tools_and_no_memory_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[int, int]] = []
    counts = iter((30, 20, 12))

    def fake_tokenize(
        base_url: str,
        messages: Any,
        tools: Any,
        *,
        timeout: float,
    ) -> int:
        del base_url, timeout
        observed.append((len(messages), len(tools)))
        return next(counts)

    monkeypatch.setattr(local_ab, "_tokenize", fake_tokenize)
    messages = [
        {"role": "system", "content": "synthetic"},
        {
            "role": "user",
            "content": (
                "TASK:\nanswer\n\n<MILAI_MEMORY_DATA>\nmemory\n"
                "</MILAI_MEMORY_DATA>"
            ),
        },
    ]
    total, components = local_ab._component_counts(
        "http://127.0.0.1:7860",
        messages,
        ({"type": "function"},),
        "memory",
        timeout=1,
    )
    assert total == 30
    assert components == {"memory_context_tokens": 8, "tool_schema_tokens": 10}
    assert observed == [(2, 1), (2, 0), (2, 0)]


def test_completion_validation_binds_model_usage_and_receipt() -> None:
    response = {
        "id": "chatcmpl-synthetic-0001",
        "model": local_ab.MODEL_ID,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": (
                        '{"answer":"7","abstained":false,"open_issue_ids":[],'
                        '"claim_refs":[],"reason_code":"DIRECT"}'
                    ),
                    "tool_calls": None,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 40,
            "completion_tokens": 20,
            "total_tokens": 60,
        },
    }
    text, usage, request_id, receipt = local_ab._validate_completion(
        response,
        {"x-request-id": "request-header-synthetic"},
        expected_prompt_tokens=40,
        max_output_tokens=160,
    )
    assert text.startswith("{")
    assert usage == {
        "input_tokens": 40,
        "cached_input_tokens": 0,
        "output_tokens": 20,
        "reasoning_tokens": None,
    }
    assert request_id == "chatcmpl-synthetic-0001"
    assert len(receipt) == 64

    response["usage"]["prompt_tokens"] = 39
    response["usage"]["total_tokens"] = 59
    with pytest.raises(local_ab.LocalVllmCaptureError, match="pre-count"):
        local_ab._validate_completion(
            response,
            {},
            expected_prompt_tokens=40,
            max_output_tokens=160,
        )


def test_post_rejects_any_non_allowlisted_endpoint_before_io() -> None:
    with pytest.raises(local_ab.LocalVllmCaptureError, match="allowlisted"):
        local_ab._post_json(
            "http://127.0.0.1:7860",
            "/v1/models",
            {},
            timeout=1,
        )


def test_effective_messages_add_uniform_policy_without_mutating_workload() -> None:
    messages = (
        {"role": "system", "content": "frozen"},
        {"role": "user", "content": "synthetic"},
    )
    effective = local_ab._effective_messages(messages)
    assert messages[0]["content"] == "frozen"
    assert effective[0]["content"].startswith("frozen\n\n")
    assert "CURRENT_AUTHORIZED" in effective[0]["content"]
    assert effective[1] == messages[1]
    assert local_ab.OUTPUT_SCHEMA["additionalProperties"] is False
