"""Relaxed spending must still preserve context, request-count and usage settlement."""

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v02_local_provider import accounting, read_events
from v0213_provider import MODEL, Provider, payload


def transport(*, unknown_usage=False, count=20000):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": count})
        assert request.url.path == "/v1/chat/completions"
        value = {"choices": [{"message": {"content": json.dumps({"action": "business"})}}]}
        if not unknown_usage:
            value["usage"] = {"prompt_tokens": count, "completion_tokens": 12,
                              "total_tokens": count + 12}
        return httpx.Response(200, json=value)

    return httpx.MockTransport(handle), calls


def test_more_than_old_cumulative_limit_can_finish_without_extra_calls(tmp_path):
    mock, calls = transport()
    provider = Provider(tmp_path, deadline=time.monotonic() + 30, max_requests=3, transport=mock)
    provider.verify()
    body = payload([{"role": "user", "content": "current task"}], {"type": "object"})
    for _ in range(3):
        provider.generate("task", body)
    state = accounting(read_events(provider.ledger))
    assert state["raw_tokens"] == 60036 and not state["pending"]
    with pytest.raises(ValueError, match="GENERATION_COUNT_LIMIT"):
        provider.generate("task", body)
    assert calls.count("/v1/chat/completions") == 3
    provider.close()


def test_unknown_usage_retains_reservation_and_stops_after_restart(tmp_path):
    mock, calls = transport(unknown_usage=True)
    body = payload([{"role": "user", "content": "task"}], {"type": "object"})
    provider = Provider(tmp_path, deadline=time.monotonic() + 30, max_requests=3, transport=mock)
    provider.verify()
    with pytest.raises(ValueError, match="USAGE_UNKNOWN"):
        provider.generate("task", body)
    provider.close()
    restarted = Provider(tmp_path, deadline=time.monotonic() + 30, max_requests=3, transport=mock)
    with pytest.raises(ValueError, match="UNSETTLED_USAGE"):
        restarted.generate("task", body)
    assert len(accounting(read_events(restarted.ledger))["pending"]) == 1
    assert calls.count("/v1/chat/completions") == 1
    restarted.close()


def test_real_context_limit_never_dispatches_a_generation(tmp_path):
    mock, calls = transport(count=65000)
    provider = Provider(tmp_path, deadline=time.monotonic() + 30, max_requests=3, transport=mock)
    provider.verify()
    with pytest.raises(ValueError, match="MODEL_CONTEXT_LIMIT"):
        provider.generate("task", payload([{"role": "user", "content": "task"}], {}))
    assert "/v1/chat/completions" not in calls
    assert not accounting(read_events(provider.ledger))["pending"]
    provider.close()
