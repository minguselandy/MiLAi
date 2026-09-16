from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
preflight = importlib.import_module("check_v0210_focus")


def _prepared():
    snapshot, protected, focus = preflight._fixture()
    return {
        arm: preflight.prepare_request(snapshot=snapshot, protected=protected, focus=focus,
                                       mode=mode, check_source=lambda _: "ELIGIBLE",
                                       model=preflight.MODEL)
        for arm, mode in (("C1", "FULL"), ("C2", "FOCUS"))
    }


def test_offline_smoke_never_constructs_network_client(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline mode attempted network")

    monkeypatch.setattr(preflight.httpx, "Client", forbidden)
    root = tmp_path / "owned"
    result = preflight.run(root, tokenize_loopback=False)
    assert result["status"] == "P1_MECHANICAL_VERIFIED_E1_NOT_READY"
    assert result["E1_ready"] is False
    assert result["actual_model_generations"] == 0
    assert result["generation_authorization"] == 0
    assert result["http_events"] == []
    for arm in ("C1", "C2"):
        body = (root / f"{arm}-request.json").read_text()
        assert "focus_sufficiency" not in body
        assert "synthetic_coverage_only" not in body
    assert json.loads((root / "result.json").read_text())["focus_origin"] == (
        "FIXED_TEST_DOUBLE_NOT_MODEL"
    )


def test_preflight_never_reuses_an_existing_experiment_directory(tmp_path):
    root = tmp_path / "retained"
    root.mkdir()
    marker = root / "result.json"
    marker.write_text("retained")
    with pytest.raises(FileExistsError):
        preflight.run(root, tokenize_loopback=False)
    assert marker.read_text() == "retained"


def test_only_discovery_and_exact_template_tokenization_are_sent():
    sent = []
    prepared = _prepared()

    def handler(request):
        sent.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 7860
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": preflight.MODEL}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "fixture"})
        assert request.url.path == "/tokenize"
        return httpx.Response(200, json={"count": 100})

    events = []
    observed = preflight.discover_and_tokenize(prepared, events=events,
                                               transport=httpx.MockTransport(handler))
    assert [(request.method, request.url.path) for request in sent] == [
        ("GET", "/v1/models"), ("GET", "/version"),
        ("POST", "/tokenize"), ("POST", "/tokenize"),
    ]
    for request, arm in zip(sent[2:], ("C1", "C2"), strict=True):
        wire = json.loads(prepared[arm].body)
        assert json.loads(request.content) == {key: wire[key] for key in preflight.TOKENIZE_KEYS}
    assert observed["full_E1_batch_cost_frozen"] is False
    assert observed["token_counts_are_not_generation_usage"] is True


@pytest.mark.parametrize("count", [None, True, 0, -1, 8193, "100"])
def test_bad_count_stops_without_completion_or_retry(count):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        value = ({"data": [{"id": preflight.MODEL}]} if request.url.path == "/v1/models"
                 else {"version": "fixture"} if request.url.path == "/version"
                 else {"count": count})
        return httpx.Response(200, json=value)

    events = []
    with pytest.raises(ValueError):
        preflight.discover_and_tokenize(_prepared(), events=events,
                                        transport=httpx.MockTransport(handler))
    assert paths == ["/v1/models", "/version", "/tokenize"]


def test_endpoint_drift_or_redirect_is_not_followed():
    events = []

    def handler(request):
        return httpx.Response(307, headers={"Location": "https://example.com/elsewhere"})

    with pytest.raises(httpx.HTTPStatusError):
        preflight.discover_and_tokenize(_prepared(), events=events,
                                        transport=httpx.MockTransport(handler))
    assert len(events) == 1


def test_model_drift_stops_before_tokenization():
    events = []
    with pytest.raises(ValueError, match="model identity drift"):
        preflight.discover_and_tokenize(
            _prepared(), events=events,
            transport=httpx.MockTransport(lambda _: httpx.Response(
                200, json={"data": [{"id": "not-the-approved-model"}]})),
        )
    assert len(events) == 1
