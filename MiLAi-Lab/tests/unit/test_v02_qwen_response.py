from __future__ import annotations

import copy
import importlib
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
codec = importlib.import_module("v02_qwen_response")
budget = importlib.import_module("v02_responses_budget")


def response(text):
    return {"id": "resp_test", "status": "completed", "output": [{"type": "message",
        "id": "msg", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": 100, "output_tokens": 20}}


TOOLS = [{"type": "function", "name": "save", "parameters": {"type": "object",
    "properties": {"text": {"type": "string"}, "version": {"type": "integer"},
                   "payload": {"type": "object"}, "refs": {"type": "array"}}}}]


def test_xml_preserves_string_edges_and_json_fields_without_mutating_source():
    text = '  首\r\n"$HOME" & <tag>\n尾 \n'
    raw = response('<tool_call>\n<function=save>\n<parameter=text>\n' + text
        + '\n</parameter>\n<parameter=version>7</parameter>'
        '<parameter=payload>{"arbitrary": {"首": 1, "尾": false}}</parameter>'
        '<parameter=refs>["abc", "def"]</parameter></function>\n</tool_call>')
    original = copy.deepcopy(raw)
    result = codec.decode_response(raw, TOOLS)
    call = result["output"][0]
    assert json.loads(call["arguments"]) == {"text": text, "version": 7,
        "payload": {"arbitrary": {"首": 1, "尾": False}}, "refs": ["abc", "def"]}
    assert call["name"] == "save" and raw == original and result["usage"] == raw["usage"]


def test_parallel_namespaced_calls_have_distinct_ids_and_preserve_order():
    tools = [{"type": "namespace", "name": "m", "tools": TOOLS}]
    raw = response('before\n<tool_call><function=m__save><parameter=text>first</parameter>'
        '</function></tool_call>\n<tool_call><function=m__save>'
        '<parameter=text>last</parameter></function></tool_call>')
    result = codec.decode_response(raw, tools)
    assert result["output"][0]["content"][0]["text"] == "before\n"
    calls = result["output"][1:]
    assert [json.loads(c["arguments"])["text"] for c in calls] == ["first", "last"]
    assert calls[0]["call_id"] != calls[1]["call_id"]
    assert all(c["namespace"] == "m" and c["name"] == "save" for c in calls)
    events = [json.loads(line[6:]) for line in codec.response_events(result).decode().splitlines()
              if line.startswith("data: ")]
    assert events[-1]["response"] == result


@pytest.mark.parametrize("text", [
    '<tool_call><function=save><parameter=text>missing end',
    '<tool_call><function=save><parameter=text>one</parameter>'
    '<parameter=text>two</parameter></function></tool_call>',
    '<tool_call><function=save><parameter=text>x</parameter></function></tool_call>suffix',
    '<tool_call><function=not_advertised></function></tool_call>',
])
def test_malformed_or_unadvertised_calls_do_not_become_actions(text):
    with pytest.raises(budget.LocalGateError):
        codec.decode_response(response(text), TOOLS)


def test_plain_text_and_already_parsed_calls_are_unchanged():
    raw = response("Complete plain text.\n")
    raw["output"].append({"type": "function_call", "call_id": "existing", "name": "save",
                          "arguments": '{"text":"exact"}'})
    assert codec.decode_response(raw, TOOLS) == raw


def settings():
    return {"provider_base_url": budget.ENDPOINT, "model": budget.MODEL,
        "paid_model_allocations_authorized": 0, "request_timeout_seconds": 2,
        "model_transport_enabled": True, "new_model_tokens_authorized": 2000,
        "new_model_allocations_authorized": 1, "local_sessions": ["probe"],
        "session_token_limit": 2000, "batch_token_limit": 2000, "max_requests_per_session": 2,
        "request_input_token_limit": 1000, "max_output_tokens": 300, "output_codec": "qwen_xml",
        "request_raw_token_limit": 200}


def test_budget_adaptation_settles_raw_usage_and_delivers_only_decoded_output(tmp_path):
    request_body = {"model": budget.MODEL, "input": "task", "tools": TOOLS, "stream": True}

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        assert json.loads(request.content) == {**request_body, "max_output_tokens": 100,
                                              "stream": False}
        return httpx.Response(200, json=response('<tool_call><function=save>'
            '<parameter=text>value</parameter></function></tool_call>'))

    runner = budget.ResponsesBudget(tmp_path, settings(), "probe",
                                   transport=httpx.MockTransport(respond))
    try:
        status, raw, content_type = runner.forward(request_body)
        assert status == 200 and content_type == "text/event-stream"
        assert b'"name": "save"' in raw
        assert budget.accounting(budget.read_events(runner.ledger))["raw_tokens"] == 120
        assert (tmp_path / "probe-001-response.bin").exists()
        assert (tmp_path / "probe-001-delivered.bin").read_bytes() == raw
    finally:
        runner.close()


def test_total_request_deadline_retains_sent_reservation(tmp_path):
    config = settings()
    config["request_timeout_seconds"] = 0.04

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        time.sleep(0.5)
        pytest.fail("deadline must interrupt the in-flight response")

    runner = budget.ResponsesBudget(tmp_path, config, "probe",
                                   transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(budget.DeadlineExpired):
            runner.forward({"model": budget.MODEL, "input": "task"})
        assert len(budget.accounting(budget.read_events(runner.ledger))["pending"]) == 1
    finally:
        runner.close()


def test_expired_session_never_tokenizes(tmp_path):
    def respond(request):
        pytest.fail("expired session cannot send anything")

    runner = budget.ResponsesBudget(tmp_path, settings(), "probe",
        transport=httpx.MockTransport(respond), session_end=time.monotonic() - 1)
    try:
        with pytest.raises(budget.DeadlineExpired):
            runner.forward({"model": budget.MODEL, "input": "task"})
        assert not budget.read_events(runner.ledger)
    finally:
        runner.close()
