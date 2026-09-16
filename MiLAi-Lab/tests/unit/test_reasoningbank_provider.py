import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from reasoningbank_provider import NativeProvider
from v02_local_provider import accounting, read_events


@pytest.mark.parametrize("known_usage", [True, False])
def test_native_tool_calls_preserve_payload_and_settle_or_retain_usage(tmp_path, known_usage):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path == "/tokenize":
            assert body["tools"][0]["function"]["name"] == "flight_search"
            return httpx.Response(200, json={"count": 12})
        result = {
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": []}}]
        }
        if known_usage:
            result["usage"] = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
        return httpx.Response(200, json=result)

    provider = NativeProvider(
        tmp_path,
        max_tokens=5000,
        deadline=time.monotonic() + 30,
        max_requests=3,
        transport=httpx.MockTransport(respond),
    )
    provider.context = 65536
    tools = [{"type": "function", "function": {"name": "flight_search", "parameters": {}}}]
    if known_usage:
        assert (
            provider.generate_message("native", [{"role": "user", "content": "x"}], tools=tools)[
                "content"
            ]
            is None
        )
        assert accounting(read_events(provider.ledger))["raw_tokens"] == 20
    else:
        with pytest.raises(ValueError, match="USAGE_UNKNOWN"):
            provider.generate_message("native", [{"role": "user", "content": "x"}], tools=tools)
        with pytest.raises(ValueError, match="UNSETTLED_USAGE"):
            provider.generate_message("native", [], tools=tools)
        assert len(accounting(read_events(provider.ledger))["pending"]) == 1
    assert len(requests) == 2
    provider.close()


def test_exhausted_task_allowance_does_not_consume_the_next_tasks_allowance(tmp_path):
    sends = []

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 10})
        sends.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    provider = NativeProvider(
        tmp_path, max_tokens=10000, max_requests=4, deadline=time.monotonic() + 30,
        transport=httpx.MockTransport(respond),
    )
    provider.context = 65536
    limits = {"max_tokens": 5000, "max_requests": 1, "wall_seconds": 30}
    provider.begin_unit(limits)
    provider.generate_message("first", [{"role": "user", "content": "x"}])
    with pytest.raises(ValueError, match="UNIT_GENERATION_LIMIT"):
        provider.generate_message("first", [{"role": "user", "content": "x"}])
    provider.begin_unit(limits)
    provider.generate_message("next", [{"role": "user", "content": "x"}])
    assert len(sends) == 2
    state = accounting(read_events(provider.ledger))
    assert state["raw_tokens"] == 30 and not state["pending"]
    provider.close()


def test_template_completion_preserves_prompt_tokens_and_native_tool_argument_types(tmp_path):
    sent = []
    raw = (
        "<tool_call>\n<function=lookup>\n<parameter=city>42</parameter>"
        '<parameter=count>2</parameter><parameter=refs>["card:1"]</parameter>'
        "</function>\n</tool_call>"
    )

    def respond(request):
        value = json.loads(request.content)
        sent.append((request.url.path, value))
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 3, "tokens": [10, 20, 30]})
        assert request.url.path == "/v1/completions"
        assert request.extensions["timeout"]["read"] == 600
        assert value["prompt"] == [10, 20, 30]
        return httpx.Response(
            200,
            json={
                "choices": [{"text": raw}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 20,
                    "total_tokens": 23,
                },
            },
        )

    provider = NativeProvider(
        tmp_path,
        max_tokens=10000,
        tool_transport="template_completion",
        request_timeout_seconds=600,
        deadline=time.monotonic() + 1000,
        max_requests=1,
        transport=httpx.MockTransport(respond),
    )
    provider.context = 65536
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "count": {"type": "integer"},
                        "refs": {"type": "array"},
                    },
                },
            },
        }
    ]
    result = provider.generate_message(
        "native", [{"role": "user", "content": "lookup"}], tools=tools
    )
    assert json.loads(result["tool_calls"][0]["function"]["arguments"]) == {
        "city": "42",
        "count": 2,
        "refs": ["card:1"],
    }
    assert accounting(read_events(provider.ledger))["raw_tokens"] == 23
    assert len(sent) == 2
    provider.close()
