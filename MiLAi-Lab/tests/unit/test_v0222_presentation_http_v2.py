"""Identity protocol with MockHTTP and explicit synthetic admission deadlines."""

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_http_v2 as module
from v0213_provider import ENDPOINT, MODEL
from v0220_provider_hardened import ProviderStop


def model_response():
    return {"data": [{"id": MODEL, "max_model_len": 65536}]}


def test_attempt_then_fresh_admission_and_remaining_deadline_each_get(tmp_path, monkeypatch):
    clock, calls, admissions = [100.0], [], []
    monkeypatch.setattr(module.time, "time", lambda: clock[0])

    def admit():
        name = "models" if not admissions else "version"
        assert (tmp_path / "identity" / (name + "-attempt.json")).is_file()
        admissions.append(name)
        return {"deadline": 101.0}

    def handle(request):
        calls.append(request.url.path)
        assert len(calls) == len(admissions)
        assert request.extensions["timeout"]["read"] == (1.0 if len(calls) == 1 else 0.25)
        clock[0] = 100.75
        return httpx.Response(
            200, json=model_response() if len(calls) == 1 else {"version": "mock-version"}
        )

    with httpx.Client(base_url=ENDPOINT, transport=httpx.MockTransport(handle)) as client:
        result = module.identity(
            client, tmp_path / "identity", admit=admit, on_failure=lambda exc: pytest.fail(str(exc))
        )
    assert result == {
        "endpoint": ENDPOINT,
        "model": MODEL,
        "context": 65536,
        "version": "mock-version",
    }
    assert sorted(p.name for p in (tmp_path / "identity").iterdir()) == [
        "models-attempt.json",
        "models.json",
        "version-attempt.json",
        "version.json",
    ]
    for name, route in (("models", "/v1/models"), ("version", "/version")):
        assert json.loads((tmp_path / "identity" / (name + "-attempt.json")).read_bytes()) == {
            "method": "GET",
            "route": route,
        }
        assert set(json.loads((tmp_path / "identity" / (name + ".json")).read_bytes())) == {
            "status_code",
            "body",
            "seconds",
        }


@pytest.mark.parametrize("deadline", [None, True, "100", float("nan"), float("inf"), -1, 99, 100])
def test_invalid_or_expired_deadline_never_sends(tmp_path, monkeypatch, deadline):
    monkeypatch.setattr(module.time, "time", lambda: 100)
    calls, failures = [], []
    with httpx.Client(
        base_url=ENDPOINT,
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    ) as client:
        with pytest.raises(ProviderStop):
            module.identity(
                client,
                tmp_path / "identity",
                admit=lambda: {"deadline": deadline},
                on_failure=failures.append,
            )
    assert not calls and failures


@pytest.mark.parametrize("name", ["models", "version"])
def test_stop_during_attempt_save_is_rechecked_before_get(tmp_path, monkeypatch, name):
    stopped, calls = [], []
    original = module.save

    def save(path, value):
        original(path, value)
        if path.name == name + "-attempt.json":
            stopped.append("STOP_DURING_SAVE")

    def admit():
        if stopped:
            raise ProviderStop(stopped[0])
        return {"deadline": time.time() + 30}

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=model_response())

    monkeypatch.setattr(module, "save", save)
    with httpx.Client(base_url=ENDPOINT, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderStop, match="STOP_DURING_SAVE"):
            module.identity(client, tmp_path / "identity", admit=admit, on_failure=lambda exc: None)
    assert calls == ([] if name == "models" else ["/v1/models"])


@pytest.mark.parametrize("mode", ["201", "float_context", "duplicate", "nonfinite"])
def test_strict_identity_protocol_rejects_bad_receipts(tmp_path, mode):
    calls, failures = [], []

    def handle(request):
        calls.append(request.url.path)
        if mode == "duplicate":
            return httpx.Response(200, text='{"data":[],"data":[]}')
        if mode == "nonfinite":
            return httpx.Response(200, text='{"data":NaN}')
        value = model_response()
        if mode == "float_context":
            value["data"][0]["max_model_len"] = 65536.0
        return httpx.Response(
            201 if mode == "201" else 200,
            json=value if request.url.path == "/v1/models" else {"version": "mock"},
        )

    with httpx.Client(base_url=ENDPOINT, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises((ProviderStop, ValueError)):
            module.identity(
                client,
                tmp_path / "identity",
                admit=lambda: {"deadline": time.time() + 30},
                on_failure=failures.append,
            )
    assert failures and len(calls) <= 2


def test_http_error_locks_before_report_and_preserves_original_on_save_failure(
    tmp_path, monkeypatch
):
    failures, observed = [], []
    original = module.save
    error = httpx.ReadTimeout("mock")

    def handle(request):
        raise error

    def save(path, value):
        if path.name.endswith("-error.json"):
            observed.append(failures[0] is error)
            raise OSError("mock report failure")
        return original(path, value)

    monkeypatch.setattr(module, "save", save)
    with httpx.Client(base_url=ENDPOINT, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.ReadTimeout) as raised:
            module.identity(
                client,
                tmp_path / "identity",
                admit=lambda: {"deadline": time.time() + 30},
                on_failure=failures.append,
            )
    assert raised.value is error and observed == [True]
    assert any("report failed" in note for note in error.__notes__)


def test_attempt_save_failure_stops_without_http(tmp_path, monkeypatch):
    failures, calls = [], []
    error = OSError("mock disk full")

    def fail(*args):
        raise error

    monkeypatch.setattr(module, "save", fail)
    with httpx.Client(
        base_url=ENDPOINT, transport=httpx.MockTransport(lambda req: calls.append(req))
    ) as client:
        with pytest.raises(OSError) as raised:
            module.identity(
                client,
                tmp_path / "identity",
                admit=lambda: {"deadline": time.time() + 30},
                on_failure=failures.append,
            )
    assert raised.value is error and failures == [error] and not calls


def test_actual_wall_timer_bounds_slow_mock_by_remaining_time(tmp_path):
    failures = []

    def slow(request):
        time.sleep(0.08)
        return httpx.Response(200, json=model_response())

    with httpx.Client(base_url=ENDPOINT, transport=httpx.MockTransport(slow)) as client:
        with pytest.raises(httpx.ReadTimeout, match="TOTAL_WALL"):
            module.identity(
                client,
                tmp_path / "identity",
                admit=lambda: {"deadline": time.time() + 0.02},
                on_failure=failures.append,
            )
    assert failures
