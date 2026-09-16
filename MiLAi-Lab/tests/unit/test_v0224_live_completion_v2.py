"""Prospective B/C boundaries; no real HTTP, fixture, or live authorization."""

import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0224_live_completion_v2 as runner
import v0224_live_completion_batch_v2 as live
import v0224_live_http as wire
from v0224_cpu_completion_segment import Batch as CompletionBatch
from v0224_k3_cpu_batch import OfflineBatch


def test_provider_constructor_primary_survives_transport_close_failure(monkeypatch):
    import v0222_presentation_provider_v2 as original

    primary = RuntimeError("primary admission failure")

    def fail(*args, **kwargs):
        raise primary

    class Transport:
        def close(self):
            raise ValueError("secondary close failure")

    class Batch:
        def spec(self, episode):
            return {"stage": "P3"}

    monkeypatch.setattr(original, "FullProvider", fail)
    monkeypatch.setattr(wire, "BoundedLiveHTTP", lambda **kwargs: Transport())
    with pytest.raises(RuntimeError) as raised:
        runner.FullProvider(Path("/synthetic"), batch=Batch(), episode="e1")
    assert raised.value is primary
    assert primary.__notes__ == ["SECONDARY_TRANSPORT_CLOSE_FAILURE: ValueError"]


def test_live_keeps_fresh_operations_and_declared_containment():
    for name in (
        "_operation",
        "_new_scope",
        "authorize",
        "artifact",
        "freeze_artifact",
        "finish",
        "_p3_gate",
        "_read_artifact_row",
    ):
        assert getattr(live.Batch, name) is getattr(OfflineBatch, name)
    for name in ("launch_once", "_check_journal"):
        assert getattr(live.Batch, name) is getattr(OfflineBatch, name)
    for name in ("claim", "_check_claims", "_audit"):
        assert getattr(live.Batch, name) is getattr(CompletionBatch, name)
    auth = live.make_live_authorization(
        live.ROOT,
        issued=1,
        expires=2,
        history={"unresolved_reservations": []},
        gate_a={"path": "/a", "sha256": "0" * 64},
    )
    assert auth["phase_wall_seconds"] == {"P3": 129600, "P4": 129600}
    assert auth["episode_wall_seconds"] == 3600 and auth["http_wall_seconds"] == 60
    assert auth["new_unknown_stops_all"] and not auth["automatic_retry"]
    assert auth["real_http_allowed"] and not auth["device_calls_allowed"]
    assert (
        sum(sum(v.values()) for v in live.AUXILIARY_LIMITS.values())
        == runner.LIMITS["http_requests"]
    )


def test_cpu_root_cannot_be_resumed_as_live():
    from v0224_k3_cpu_batch import CPU_ROOT

    with pytest.raises(live.ProviderStop, match="ONE_FIXED_FRESH_LIVE_ROOT_REQUIRED"):
        live.Batch(
            CPU_ROOT,
            "0" * 64,
            static_authority=None,
            gate_a_path=Path("/gate"),
            gate_a_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    "gate",
    [
        {"status": "CPU_REPLAY_P3_PASS", "blocking_findings": [], "files": {"/x": "0" * 64}},
        {
            "status": live.GATE_A_STATUS,
            "blocking_findings": ["missing P4"],
            "files": {"/x": "0" * 64},
        },
        {"status": live.GATE_A_STATUS, "blocking_findings": [], "files": {}},
    ],
)
def test_incomplete_gate_a_refused_before_history_or_http(gate, monkeypatch):
    batch = object.__new__(live.Batch)
    batch._gate_a = {"path": "/gate", "sha256": "0" * 64}

    class Scope:
        def read_json(self, path, digest):
            assert str(path) == "/gate"
            return gate

    @contextmanager
    def guard(scope):
        yield

    monkeypatch.setattr(live, "_guard", guard)
    with pytest.raises(live.ProviderStop, match="GATE_A"):
        batch._authorize("PREP", Scope())


def test_http_fixed_routes_counts_and_failures_consume_attempt(monkeypatch):
    calls = []

    class Delegate:
        def handle_request(self, request):
            calls.append(request)
            raise httpx.ConnectError("synthetic failure")

        def close(self):
            pass

    monkeypatch.setattr(wire.httpx, "HTTPTransport", lambda **kwargs: Delegate())
    transport = wire.BoundedLiveHTTP(identity_get=1, tokenize_post=0, generation_post=0)
    for url in (
        "http://example.com:7860/v1/models",
        "http://127.0.0.1:7861/v1/models",
        "http://127.0.0.1:7860/v1/models?extra=1",
        "http://127.0.0.1:7860/unknown",
    ):
        with pytest.raises(live.ProviderStop):
            transport.handle_request(httpx.Request("GET", url))
    assert not calls
    request = httpx.Request("GET", "http://127.0.0.1:7860/v1/models")
    with pytest.raises(httpx.ConnectError):
        transport.handle_request(request)
    with pytest.raises(live.ProviderStop, match="COUNT_EXCEEDED"):
        transport.handle_request(request)
    assert len(calls) == 1
    transport.close()
