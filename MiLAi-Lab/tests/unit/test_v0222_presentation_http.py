"""Mock-only identity admission at the actual send, including disk/error boundaries."""

import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_http as module
from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("MOCK_HTTP_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def setup(tmp_path, monkeypatch, *, failure=None, stop_after=None):
    stopped, calls, order = [], [], []

    def stop(exc):
        if not stopped:
            stopped.append(type(exc).__name__)

    def persist(path, value):
        order.append(("save", path.name))
        if failure == path.name:
            if path.name.endswith("-error.json"):
                assert stopped == ["ReadTimeout"]
            raise OSError("MOCK_DISK_FAILURE")
        save(path, value)
        if path.name == stop_after:
            stopped.append("EXTERNAL_STOP")

    def admit():
        order.append(("admit", None))
        if stopped:
            raise ProviderStop("PERMANENT_STOP")

    def handler(request):
        assert order[-1] == ("admit", None) and not stopped
        calls.append(request.url.path)
        if failure == "models-error.json":
            raise httpx.ReadTimeout("MOCK_TIMEOUT")
        return httpx.Response(
            200,
            json={"data": [{"id": MODEL, "max_model_len": 65536}]}
            if request.url.path == "/v1/models"
            else {"version": "0.27.1"},
        )

    monkeypatch.setattr(module, "save", persist)
    client = httpx.Client(base_url=ENDPOINT, transport=httpx.MockTransport(handler))
    return client, admit, stop, stopped, calls, order


def test_identity_has_exact_four_receipts_and_actual_send_order(tmp_path, monkeypatch):
    client, admit, stop, stopped, calls, order = setup(tmp_path, monkeypatch)
    with client:
        result = module.identity(client, tmp_path / "identity", admit=admit, on_failure=stop)
    assert result == {"endpoint": ENDPOINT, "model": MODEL, "context": 65536, "version": "0.27.1"}
    assert calls == ["/v1/models", "/version"] and not stopped
    assert order == [
        ("save", "models-attempt.json"),
        ("admit", None),
        ("save", "models.json"),
        ("save", "version-attempt.json"),
        ("admit", None),
        ("save", "version.json"),
    ]
    assert len(list((tmp_path / "identity").glob("*.json"))) == 4


@pytest.mark.parametrize("name,expected", [("models-attempt.json", 0), ("version-attempt.json", 1)])
def test_stop_after_attempt_persistence_prevents_that_get(tmp_path, monkeypatch, name, expected):
    client, admit, stop, stopped, calls, _ = setup(tmp_path, monkeypatch, stop_after=name)
    with client, pytest.raises(ProviderStop, match="PERMANENT_STOP"):
        module.identity(client, tmp_path / "identity", admit=admit, on_failure=stop)
    assert stopped == ["EXTERNAL_STOP"] and len(calls) == expected


@pytest.mark.parametrize(
    "name,expected", [("models-attempt.json", 0), ("models.json", 1), ("version.json", 2)]
)
def test_identity_disk_failure_locks_before_return(tmp_path, monkeypatch, name, expected):
    client, admit, stop, stopped, calls, _ = setup(tmp_path, monkeypatch, failure=name)
    with client, pytest.raises(OSError):
        module.identity(client, tmp_path / "identity", admit=admit, on_failure=stop)
    assert stopped == ["OSError"] and len(calls) == expected


def test_transport_error_locks_before_failed_error_report_preserving_original(
    tmp_path, monkeypatch
):
    client, admit, stop, stopped, calls, _ = setup(
        tmp_path, monkeypatch, failure="models-error.json"
    )
    with client, pytest.raises(httpx.ReadTimeout):
        module.identity(client, tmp_path / "identity", admit=admit, on_failure=stop)
    assert stopped == ["ReadTimeout"] and len(calls) == 1
