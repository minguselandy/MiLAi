"""Separate prediction/scoring with actual owned accounting and mock HTTP, no real model."""
import copy
import json
import socket

import httpx
import pytest
from test_lme_protocol import UPSTREAM
from test_retrieval_feedback_without_fingerprints import forbid_fingerprints
from test_v13_5_functional_integration import prepared

from milai_lab.datasets.lme_protocol import NativeLmeProtocol
from milai_lab.harness.artifact_io import read_json
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.functional import frozen
from milai_lab.runners.lme_reader import predict_reader, score_reader


def setup(tmp_path, monkeypatch, *, native=True):
    forbid_fingerprints(monkeypatch)
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("REAL_NETWORK_FORBIDDEN"))
    runtime = prepared(tmp_path, native=native)
    capacity = HostCapacity(frozen(runtime)["config"]["capacity"])
    protocol = NativeLmeProtocol(UPSTREAM)
    return runtime, capacity, protocol


def reply(content, *, finish="stop", usage=True):
    value = {"choices": [{"finish_reason": finish,
        "message": {"role": "assistant", "content": content}}]}
    if usage:
        value["usage"] = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
    return httpx.Response(200, json=value)


def predict(runtime, output, protocol, capacity, transport):
    return predict_reader(runtime, output, protocol, capacity, domain="web",
        query="Public synthetic question", query_image=None,
        context=[{"type": "text", "value": "Actual returned synthetic evidence"}],
        source_version="mechanical", transport=transport)


def reference():
    return {"id": "OFFLINE_ID", "question": "Public synthetic question",
            "answer": "REFERENCE_ONLY_FOR_JUDGE", "question_type": "errors-gotchas",
            "eval_function": "llm_gotchas_checker"}


@pytest.mark.parametrize("native", [True, False])
def test_reader_judge_use_same_ledger_and_queue_without_reference_leak(
    tmp_path, monkeypatch, native,
):
    runtime, capacity, protocol = setup(tmp_path, monkeypatch, native=native)
    wires = []

    def respond(request):
        payload = json.loads(request.content)
        wires.append(payload)
        if len(wires) == 1:
            assert "REFERENCE_ONLY_FOR_JUDGE" not in request.content.decode()
            assert "OFFLINE_ID" not in request.content.decode()
            assert "response_format" not in payload
            return reply("Actual answer \\boxed{synthetic insight}")
        assert "REFERENCE_ONLY_FOR_JUDGE" in request.content.decode()
        assert (tmp_path/"reader/prediction.json").exists()
        return reply('{"label": 1, "reason": "synthetic agreement"}')

    prediction = predict(runtime, tmp_path/"reader", protocol, capacity,
                         httpx.MockTransport(respond))
    assert prediction["status"] == "COMPLETED" and prediction["reference_accessed"] is False
    before = (tmp_path/"reader/prediction.json").read_bytes()
    result = score_reader(tmp_path/"reader", tmp_path/"score", reference(), protocol, capacity,
        source_version="mechanical", transport=httpx.MockTransport(respond))
    assert result["status"] == "COMPLETED" and result["score_bool"]
    assert len(wires) == 2 and (tmp_path/"reader/prediction.json").read_bytes() == before
    assert "max_tokens" in wires[0] and "max_completion_tokens" in wires[1]
    assert all("timeout" not in wire and "extra_body" not in wire for wire in wires)
    assert read_json(runtime/"queue-admission.json")["requests"] == 2
    budget = read_json(tmp_path/"isolated-mechanical-budget.json")
    assert budget["generation_requests"] == 2
    assert budget["generation"]["known_tokens"] == budget["generation"]["charged_tokens"] == 24
    assert budget["generation"]["unknown_usage"] == 0
    assert read_json(tmp_path/"reader/reader/call.json")["actual_http_attempts"] == 1
    assert read_json(tmp_path/"score/judge/call.json")["actual_http_attempts"] == 1


def test_truncated_reader_is_retained_unscored_and_not_retried(tmp_path, monkeypatch):
    runtime, capacity, protocol = setup(tmp_path, monkeypatch)
    calls = []

    def respond(request):
        calls.append(request)
        return reply("partial reasoning with an apparent answer", finish="length")

    with pytest.raises(IncompleteChatResponse):
        predict(runtime, tmp_path/"reader", protocol, capacity, httpx.MockTransport(respond))
    assert len(calls) == 1
    assert read_json(tmp_path/"reader/prediction.json")["status"] == "FAILED"
    response = read_json(tmp_path/"reader/reader/response.json")
    assert response["choices"][0]["finish_reason"] == "length"
    with pytest.raises(ValueError, match="completed prediction"):
        score_reader(tmp_path/"reader", tmp_path/"score", reference(), protocol, capacity,
            source_version="mechanical", transport=httpx.MockTransport(respond))
    assert len(calls) == 1 and read_json(tmp_path/"score/score.json")["score"] is None
    assert read_json(tmp_path/"isolated-mechanical-budget.json")["generation"]["known_tokens"] == 12


def test_unknown_usage_keeps_reservation_for_valid_unknown_answer(tmp_path, monkeypatch):
    runtime, capacity, protocol = setup(tmp_path, monkeypatch)
    prediction = predict(runtime, tmp_path/"reader", protocol, capacity,
        httpx.MockTransport(lambda _: reply("\\boxed{UNKNOWN}", usage=False)))
    assert prediction["status"] == "COMPLETED" and prediction["is_unknown"]
    budget = read_json(tmp_path/"isolated-mechanical-budget.json")
    assert budget["generation"]["unknown_usage"] == 1
    assert budget["generation"]["known_tokens"] == 0 and budget["generation"]["charged_tokens"] > 0
    question = {**reference(), "eval_function": "norm_phrase_set_match",
                "question_type": "procedure"}
    score = score_reader(tmp_path/"reader", tmp_path/"score", question, protocol, capacity,
        source_version="mechanical",
        transport=httpx.MockTransport(lambda _: pytest.fail("No Judge")))
    assert score["is_unknown"] and score["score"] == 0
    assert not (tmp_path/"score/judge").exists()
    assert read_json(tmp_path/"isolated-mechanical-budget.json") == budget


def test_bad_judge_format_is_unscored_and_calls_stay_billed(tmp_path, monkeypatch):
    runtime, capacity, protocol = setup(tmp_path, monkeypatch)
    predict(runtime, tmp_path/"reader", protocol, capacity,
            httpx.MockTransport(lambda _: reply("\\boxed{synthetic insight}")))
    with pytest.raises(ValueError, match="Could not parse"):
        score_reader(tmp_path/"reader", tmp_path/"score", reference(), protocol, capacity,
            source_version="mechanical",
            transport=httpx.MockTransport(lambda _: reply("unparseable")))
    result = read_json(tmp_path/"score/score.json")
    assert result["score"] is None and result["status"] == "FAILED"
    assert read_json(tmp_path/"score/judge/call.json")["status"] == "COMPLETED"
    assert read_json(tmp_path/"isolated-mechanical-budget.json")["generation_requests"] == 2


def test_reference_question_cannot_be_swapped_after_prediction(tmp_path, monkeypatch):
    runtime, capacity, protocol = setup(tmp_path, monkeypatch)
    predict(runtime, tmp_path/"reader", protocol, capacity,
            httpx.MockTransport(lambda _: reply("answer")))
    wrong = copy.deepcopy(reference())
    wrong["question"] = "A different question"
    with pytest.raises(ValueError, match="exact public question"):
        score_reader(tmp_path/"reader", tmp_path/"score", wrong, protocol, capacity,
            source_version="mechanical",
            transport=httpx.MockTransport(lambda _: pytest.fail("No call")))
    assert read_json(tmp_path/"isolated-mechanical-budget.json")["generation_requests"] == 1
