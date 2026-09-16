"""New HTTP transport: raw accounting precedes diagnostic classification."""

import copy
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0213_provider import ENDPOINT, MODEL
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0222_diagnostic import request
from v0222_transport import Transport


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
        assert episode == "p1-01"
        return {"cap": 1, "deadline": time.time() + 300}

    def record(self, episode, event):
        assert episode == "p1-01"
        usage_state([*self.events, event])
        self.events.append(event)

    def stop(self, reason):
        self.stopped = self.stopped or reason


def setup(tmp_path, monkeypatch, mode="valid"):
    batch = FakeBatch(tmp_path)
    calls = []
    monkeypatch.setattr(
        "v0222_transport.historical_usage_v0222", lambda paths: batch.auth["historical"]
    )
    _, body = request("T1", "D00")
    expected_body = copy.deepcopy(body)

    def handle(req):
        calls.append(req.url.path)
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if req.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if req.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 77})
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
        output = {
            "id": "mock-id",
            "usage": usage,
            "choices": [
                {"message": {"content": "not json" if mode == "invalid_json" else '{"text":"x"}'}}
            ],
        }
        if mode == "missing_id":
            output.pop("id")
        return httpx.Response(200, json=output)

    def exact_wire(candidate):
        if fingerprint(candidate) != fingerprint(expected_body):
            raise ProviderStop("UNFROZEN_WIRE")

    provider = Transport(
        tmp_path / "episodes/p1-01/provider",
        batch=batch,
        episode="p1-01",
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
        output = provider.generate("p1-01", body)
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
            provider.generate("p1-01", body)
        assert batch.stopped and calls.count("/v1/chat/completions") == 1
        cost = usage_state(batch.events)
        assert cost["requests"] == 1
        assert (cost["actual_total_raw_tokens"] is None) == (
            mode in {"500", "timeout", "missing_usage", "duplicate_usage"}
        )
        with pytest.raises(ProviderStop):
            provider.generate("p1-01", body)
        assert calls.count("/v1/chat/completions") == 1
    finally:
        provider.close()


def test_wire_drift_stops_before_tokenize_or_generation(tmp_path, monkeypatch):
    batch, provider, body, calls = setup(tmp_path, monkeypatch)
    try:
        provider.verify()
        body["temperature"] = 0.5
        with pytest.raises(ProviderStop, match="UNFROZEN_WIRE"):
            provider.generate("p1-01", body)
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

        monkeypatch.setattr("v0222_transport.http_identity", failed_identity)
        with pytest.raises(httpx.HTTPStatusError):
            provider.verify()
        assert batch.stopped and provider.context is None
        with pytest.raises(ProviderStop):
            provider.generate("p1-01", body)
        assert "/v1/chat/completions" not in calls
    finally:
        provider.close()
