from __future__ import annotations

import copy
import importlib
import json
import socket
import sys
import threading
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
budget = importlib.import_module("v02_responses_budget")
bridge = importlib.import_module("v02_native_bridge")


@pytest.fixture
def config():
    return {"provider_base_url": budget.ENDPOINT, "model": budget.MODEL,
        "paid_model_allocations_authorized": 0, "request_timeout_seconds": 2,
        "model_transport_enabled": True, "new_model_tokens_authorized": 2000,
        "new_model_allocations_authorized": 1, "local_sessions": ["G"],
        "session_token_limit": 2000, "batch_token_limit": 2000, "max_requests_per_session": 2,
        "request_input_token_limit": 1000, "max_output_tokens": 300}


@pytest.fixture
def request_body():
    return {"model": budget.MODEL, "instructions": "A native client instruction",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": " 首\r\n尾 \n"}]}],
        "tools": [{"type": "function", "name": "arbitrary", "parameters": {"type": "object"}}],
        "stream": False, "store": False}


def test_reservation_precedes_dispatch_and_forwarding_only_caps_output(
    tmp_path, config, request_body,
):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/tokenize":
            assert not budget.read_events(tmp_path / "provider-ledger.jsonl")
            return httpx.Response(200, json={"count": 123})
        state = budget.accounting(budget.read_events(tmp_path / "provider-ledger.jsonl"))
        assert len(state["pending"]) == 1 and state["pending"][0]["raw_upper_bound"] == 423
        sent = json.loads(request.content)
        assert sent == {**request_body, "max_output_tokens": 300}
        return httpx.Response(200, json={"id": "r1", "usage": {
            "input_tokens": 123, "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 100}}})

    runner = budget.ResponsesBudget(tmp_path, config, "G", transport=httpx.MockTransport(respond))
    try:
        status, _, _ = runner.forward(request_body)
        assert status == 200 and calls == ["/tokenize", "/v1/responses"]
        state = budget.accounting(budget.read_events(runner.ledger))
        assert state["raw_tokens"] == 143 and state["pending"] == []
    finally:
        runner.close()


@pytest.mark.parametrize("fault", ["disabled", "oversize", "budget", "session"])
def test_rejection_never_sends_generation(tmp_path, config, request_body, fault):
    calls = []
    if fault == "disabled":
        config["model_transport_enabled"] = False
    elif fault == "budget":
        config["new_model_tokens_authorized"] = 100
    elif fault == "session":
        config["local_sessions"] = ["another"]

    def respond(request):
        calls.append(request.url.path)
        assert request.url.path == "/tokenize"
        return httpx.Response(200, json={"count": 1001 if fault == "oversize" else 123})

    runner = budget.ResponsesBudget(tmp_path, config, "G", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(budget.LocalGateError):
            runner.forward(request_body)
        assert "/v1/responses" not in calls and not budget.read_events(runner.ledger)
    finally:
        runner.close()


@pytest.mark.parametrize("fault", ["disconnect", "no_usage", "wrong_input", "excess_output"])
def test_unknown_or_bound_violation_preserves_reservation_and_stops_retry(
    tmp_path, config, request_body, fault,
):
    sent = []

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 123})
        sent.append(request)
        if fault == "disconnect":
            raise httpx.ReadError("response lost")
        if fault == "no_usage":
            return httpx.Response(200, json={"id": "r1", "usage": None})
        return httpx.Response(200, json={"id": "r1", "usage": {
            "input_tokens": 124 if fault == "wrong_input" else 123,
            "output_tokens": 301 if fault == "excess_output" else 1}})

    runner = budget.ResponsesBudget(tmp_path, config, "G", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises((budget.LocalGateError, httpx.ReadError)):
            runner.forward(request_body)
        assert len(budget.accounting(budget.read_events(runner.ledger))["pending"]) == 1
        with pytest.raises(budget.LocalGateError, match="UNRESOLVED"):
            runner.forward(request_body)
        assert len(sent) == 1
    finally:
        runner.close()


def test_stateless_tool_and_namespace_counting_preserves_calls_and_complete_results(request_body):
    result = "  complete result\r\n末尾 \n"
    request_body["tools"] = [{"type": "namespace", "name": "memory",
                              "tools": request_body["tools"]}]
    request_body["input"].extend([
        {"type": "function_call", "namespace": "memory", "name": "arbitrary", "call_id": "c1",
         "arguments": '{"text":"one"}'},
        {"type": "function_call", "namespace": "memory", "name": "arbitrary", "call_id": "c2",
         "arguments": '{"text":"two"}'},
        {"type": "function_call_output", "call_id": "c2", "output": result},
        {"type": "function_call_output", "call_id": "c1", "output": "error: deliberate"}])
    original = copy.deepcopy(request_body)
    rendered = budget.render_input(request_body)
    assert request_body == original
    calls = rendered["messages"][2]["tool_calls"]
    assert [v["id"] for v in calls] == ["c1", "c2"]
    assert rendered["messages"][3] == {"role": "tool", "tool_call_id": "c2", "content": result}
    assert rendered["tools"][0]["function"]["name"] == "memory__arbitrary"
    assert rendered["messages"][1]["content"][0]["text"] == " 首\r\n尾 \n"


def test_socket_bridge_preserves_half_close_and_returned_bytes():
    left_client, left_proxy = socket.socketpair()
    right_proxy, right_server = socket.socketpair()
    sockets = (left_client, left_proxy, right_proxy, right_server)
    for sock in sockets:
        sock.settimeout(2)
    thread = threading.Thread(target=bridge.relay, args=(left_proxy, right_proxy))
    thread.start()
    try:
        left_client.sendall(b"request\r\n")
        left_client.shutdown(socket.SHUT_WR)
        assert right_server.recv(100) == b"request\r\n"
        assert right_server.recv(100) == b""
        right_server.sendall(b"response\x00tail")
        right_server.shutdown(socket.SHUT_WR)
        assert left_client.recv(100) == b"response\x00tail"
        assert left_client.recv(100) == b""
        thread.join(2)
        assert not thread.is_alive()
    finally:
        for sock in sockets:
            sock.close()


def test_new_cold_session_cannot_reset_the_batch_budget(tmp_path, config, request_body):
    config.update(local_sessions=["G", "R"], new_model_allocations_authorized=2,
                  batch_token_limit=500, new_model_tokens_authorized=500)
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        return httpx.Response(200, json={"id": "one", "usage": {
            "input_tokens": 100, "output_tokens": 300}})

    first = budget.ResponsesBudget(tmp_path, config, "G", transport=httpx.MockTransport(respond))
    second = budget.ResponsesBudget(tmp_path, config, "R", transport=httpx.MockTransport(respond))
    try:
        first.forward(request_body)
        with pytest.raises(budget.LocalGateError, match="TOKEN_LIMIT"):
            second.forward(request_body)
        assert paths == ["/tokenize", "/v1/responses"]
        assert budget.accounting(budget.read_events(first.ledger))["raw_tokens"] == 400
    finally:
        first.close()
        second.close()


def test_native_mcp_error_parts_keep_exact_text_and_id_in_counting_and_forwarding(
    tmp_path, config, request_body,
):
    error = " 首\r\nMCP error -32602: Invalid source_type\n尾 \n"
    request_body["input"].append({"type": "function_call_output", "call_id": "failed-call",
        "output": [{"type": "input_text", "text": error}]})
    original = copy.deepcopy(request_body)

    def respond(request):
        sent = json.loads(request.content)
        if request.url.path == "/tokenize":
            assert sent["messages"][-1] == {"role": "tool", "tool_call_id": "failed-call",
                                             "content": error}
            return httpx.Response(200, json={"count": 100})
        assert sent["input"][-1]["output"] == error
        assert sent["input"][-1]["call_id"] == "failed-call"
        return httpx.Response(200, json={"id": "r", "usage": {
            "input_tokens": 100, "output_tokens": 10}})

    runner = budget.ResponsesBudget(tmp_path, config, "G", transport=httpx.MockTransport(respond))
    try:
        runner.forward(request_body)
        assert request_body == original
        assert budget.accounting(budget.read_events(runner.ledger))["raw_tokens"] == 110
    finally:
        runner.close()
