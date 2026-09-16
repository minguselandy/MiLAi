"""MockHTTP + narrow FakeBatch; no real model or production evidence writes."""

import copy
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0222_boundary_transport import Transport
from v0222_diagnostic import request


class FakeBatch:
    def __init__(self, root):
        self.root, self.events, self.stopped = root, [], None
        self.auth = {"historical": {"sources": [{"path": str(root / "history")}]}}
        self.plan = {
            "http_identity": {
                "endpoint": ENDPOINT,
                "model": MODEL,
                "context": 65536,
                "version": "0.27.1",
            }
        }

    def admit(self, episode):
        if self.stopped:
            raise ProviderStop("BATCH_STOPPED")
        assert episode == "r1-01"
        return {"cap": 1, "deadline": time.time() + 300}

    def record(self, episode, event):
        assert episode == "r1-01"
        usage_state([*self.events, event])
        self.events.append(event)

    def http_admit(self, episode, *, inflight=False):
        return self.admit(episode)

    def stop(self, reason):
        self.stopped = self.stopped or reason


def setup(tmp_path, monkeypatch, mode="valid"):
    batch = FakeBatch(tmp_path)
    calls = []
    monkeypatch.setattr(
        "v0222_boundary_transport.historical_usage_boundary", lambda paths: batch.auth["historical"]
    )
    _, body = request("T1", "D00")
    expected_body = copy.deepcopy(body)

    def handle(req):
        calls.append(req.url.path)
        if req.url.path == "/v1/models":
            if mode == "stop_after_models":
                batch.stop("MOCK_STOP_BETWEEN_IDENTITY_GETS")
            return httpx.Response(
                201 if mode == "identity_201" else 200,
                json={
                    "data": [
                        {
                            "id": MODEL,
                            "max_model_len": 65536.0 if mode == "float_context" else 65536,
                        }
                    ]
                },
            )
        if req.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if req.url.path == "/tokenize":
            if mode == "stop_after_tokenize":
                batch.stop("MOCK_STOP_AFTER_TOKENIZE")
            assert json.loads(req.content) == {k: expected_body[k] for k in TOKENIZE_KEYS}
            count = {
                "bool_count": True,
                "float_count": 77.0,
                "too_long": 65536,
                "negative_count": -1,
            }.get(mode, 77)
            if mode == "duplicate_count":
                return httpx.Response(200, text='{"count":77,"count":77}')
            return httpx.Response(201 if mode == "tokenize_201" else 200, json={"count": count})
        assert req.url.path == "/v1/chat/completions"
        assert json.loads(req.content) == expected_body
        if mode == "timeout":
            raise httpx.ReadTimeout("mock", request=req)
        if mode == "500":
            return httpx.Response(500, json={"error": {"message": ""}})
        if mode == "duplicate_usage":
            return httpx.Response(
                200,
                text=(
                    '{"id":"mock","usage":{"prompt_tokens":77,"completion_tokens":400,'
                    '"total_tokens":477},"usage":{"prompt_tokens":77,"completion_tokens":5,'
                    '"total_tokens":82},"choices":[{"message":{"content":"x"}}]}'
                ),
            )
        usage = {"prompt_tokens": 77, "completion_tokens": 5, "total_tokens": 82}
        if mode == "missing_usage":
            usage = None
        elif mode == "bound":
            usage = {"prompt_tokens": 78, "completion_tokens": 5, "total_tokens": 83}
        elif mode == "oversized_completion":
            usage = {"prompt_tokens": 77, "completion_tokens": 4097, "total_tokens": 4174}
        elif mode == "bool_usage":
            usage = {"prompt_tokens": 77, "completion_tokens": True, "total_tokens": 78}
        content = {
            "invalid_json": "not json",
            "deep_json": "[" * 1100 + "0" + "]" * 1100,
            "invalid_unicode": "\ud800",
            "empty": "",
            "wrong_schema": "[]",
        }.get(mode, '{"text":"x"}')
        output = {
            "id": "mock-id",
            "usage": usage,
            "choices": [{"message": {"content": content}}],
        }
        if mode == "missing_id":
            output.pop("id")
        if mode == "invalid_unicode":
            return httpx.Response(200, text=json.dumps(output, ensure_ascii=True))
        return httpx.Response(200, json=output)

    def exact_wire(candidate):
        if fingerprint(candidate) != fingerprint(expected_body):
            raise ProviderStop("UNFROZEN_WIRE")

    provider = Transport(
        tmp_path / "episodes/r1-01/provider",
        batch=batch,
        episode="r1-01",
        preflight=exact_wire,
        transport=httpx.MockTransport(handle),
    )
    return batch, provider, body, calls


@pytest.mark.parametrize("mode", ["valid", "invalid_json"])
def test_legal_or_illegal_content_returned_raw_and_settled_for_diagnostic(
    tmp_path, monkeypatch, mode
):
    batch, provider, body, calls = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        output = provider.generate("r1-01", body)
        assert output == ("not json" if mode == "invalid_json" else '{"text":"x"}')
        assert usage_state(batch.events)["actual_total_raw_tokens"] == 82
        assert batch.stopped is None and calls.count("/v1/chat/completions") == 1
        assert len(list(provider.root.glob("*-http.json"))) == 2
    finally:
        provider.close()


@pytest.mark.parametrize(
    "mode", ["500", "timeout", "missing_usage", "bound", "missing_id", "duplicate_usage"]
)
def test_fatal_errors_stop_whole_batch_keep_known_or_unknown_cost(tmp_path, monkeypatch, mode):
    batch, provider, body, calls = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        with pytest.raises(ProviderStop):
            provider.generate("r1-01", body)
        assert batch.stopped and calls.count("/v1/chat/completions") == 1
        cost = usage_state(batch.events)
        assert cost["requests"] == 1
        assert (cost["actual_total_raw_tokens"] is None) == (
            mode in {"500", "timeout", "missing_usage", "duplicate_usage"}
        )
        with pytest.raises(ProviderStop):
            provider.generate("r1-01", body)
        assert calls.count("/v1/chat/completions") == 1
    finally:
        provider.close()


def test_wire_drift_stops_before_tokenize_or_generation(tmp_path, monkeypatch):
    batch, provider, body, calls = setup(tmp_path, monkeypatch)
    try:
        provider.verify()
        body["temperature"] = 0.5
        with pytest.raises(ProviderStop, match="UNFROZEN_WIRE"):
            provider.generate("r1-01", body)
        assert batch.stopped and "/tokenize" not in calls and not batch.events
    finally:
        provider.close()


def test_identity_failure_clears_context_and_prevents_any_later_generation(tmp_path, monkeypatch):
    batch, provider, body, calls = setup(tmp_path, monkeypatch)
    try:
        provider.verify()
        assert provider.context == 65536

        def failed_identity(*args):
            raise httpx.HTTPStatusError(
                "mock identity failure",
                request=httpx.Request("GET", ENDPOINT),
                response=httpx.Response(503),
            )

        monkeypatch.setattr("v0222_boundary_transport.boundary_identity", failed_identity)
        with pytest.raises(httpx.HTTPStatusError):
            provider.verify()
        assert batch.stopped and provider.context is None
        with pytest.raises(ProviderStop):
            provider.generate("r1-01", body)
        assert "/v1/chat/completions" not in calls
    finally:
        provider.close()


@pytest.mark.parametrize(
    "mode",
    [
        "bool_count",
        "float_count",
        "negative_count",
        "too_long",
        "duplicate_count",
        "tokenize_201",
        "identity_201",
        "float_context",
    ],
)
def test_strict_tokenize_and_identity_fail_before_model_dispatch(tmp_path, monkeypatch, mode):
    batch, provider, body, calls = setup(tmp_path, monkeypatch, mode)
    try:
        with pytest.raises((ValueError, ProviderStop)):
            provider.verify()
            provider.generate("r1-01", body)
        assert batch.stopped and not batch.events
        assert "/v1/chat/completions" not in calls
    finally:
        provider.close()


@pytest.mark.parametrize("mode", ["deep_json", "invalid_unicode", "empty", "wrong_schema"])
def test_known_content_edge_cases_are_preserved_not_repaired(tmp_path, monkeypatch, mode):
    batch, provider, body, calls = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        raw = provider.generate("r1-01", body)
        saved = json.loads(next(provider.root.glob("*-visible.json")).read_text())
        assert saved["content"] == raw
        assert batch.stopped is None
        assert usage_state(batch.events)["known_raw_tokens"] == 82
        assert calls.count("/v1/chat/completions") == 1
        with pytest.raises(ProviderStop, match="EXHAUSTED"):
            provider.generate("r1-01", body)
        assert calls.count("/v1/chat/completions") == 1
    finally:
        provider.close()


@pytest.mark.parametrize("mode,known", [("oversized_completion", 4174), ("bool_usage", 0)])
def test_abnormal_usage_is_never_released_or_forgiven(tmp_path, monkeypatch, mode, known):
    batch, provider, body, calls = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        with pytest.raises(ProviderStop):
            provider.generate("r1-01", body)
        assert batch.stopped
        assert usage_state(batch.events)["known_raw_tokens"] == known
        assert not list(provider.root.glob("*-visible.json"))
        assert calls.count("/v1/chat/completions") == 1
    finally:
        provider.close()


def test_history_drift_stops_without_tokenize(tmp_path, monkeypatch):
    batch, provider, body, calls = setup(tmp_path, monkeypatch)
    try:
        provider.verify()
        monkeypatch.setattr("v0222_boundary_transport.historical_usage_boundary", lambda paths: {})
        with pytest.raises(ProviderStop, match="HISTORICAL_LINEAGE_DRIFT"):
            provider.generate("r1-01", body)
        assert batch.stopped and "/tokenize" not in calls and not batch.events
    finally:
        provider.close()


@pytest.mark.parametrize("mode", ["stop_after_models", "stop_after_tokenize"])
def test_fresh_stop_between_http_calls_prevents_next_send(tmp_path, monkeypatch, mode):
    batch, provider, body, calls = setup(tmp_path, monkeypatch, mode)
    try:
        with pytest.raises(ProviderStop):
            provider.verify()
            provider.generate("r1-01", body)
        assert batch.stopped and "/v1/chat/completions" not in calls
        if mode == "stop_after_models":
            assert calls == ["/v1/models"]
    finally:
        provider.close()


def test_stop_after_dispatch_intent_before_send_keeps_unknown_and_does_not_send(
    tmp_path, monkeypatch
):
    batch, provider, body, calls = setup(tmp_path, monkeypatch)
    original = batch.record

    def record(episode, event):
        original(episode, event)
        if event["event"] == "DISPATCH_STARTED":
            batch.stop("MOCK_STOP_JUST_BEFORE_HTTP")

    monkeypatch.setattr(batch, "record", record)
    try:
        provider.verify()
        with pytest.raises(ProviderStop):
            provider.generate("r1-01", body)
        assert batch.stopped and "/v1/chat/completions" not in calls
        cost = usage_state(batch.events)
        assert cost["requests"] == 1 and cost["actual_total_raw_tokens"] is None
    finally:
        provider.close()


def test_stop_during_wire_preflight_prevents_tokenize(tmp_path, monkeypatch):
    batch, provider, body, calls = setup(tmp_path, monkeypatch)
    original = provider.preflight

    def preflight(candidate):
        original(candidate)
        batch.stop("MOCK_STOP_BEFORE_TOKENIZE")

    monkeypatch.setattr(provider, "preflight", preflight)
    try:
        provider.verify()
        with pytest.raises(ProviderStop):
            provider.generate("r1-01", body)
        assert batch.stopped and "/tokenize" not in calls and not batch.events
    finally:
        provider.close()
