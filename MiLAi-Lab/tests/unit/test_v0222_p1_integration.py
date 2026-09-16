"""Real P1 coordinator/worker/transport wiring with only synthetic MockTransport I/O."""

import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import test_v0222_batch as batch_fixture

import v0222_p1_worker as worker
from v02_local_provider import read_events
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0218_world import World
from v0220_action_adapter import ActionAdapter
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_session import Session
from v0220_wire_contract import fingerprint
from v0222_batch import Batch
from v0222_diagnostic import FIXTURES, request
from v0222_transport import Transport


def integration_batch(tmp_path, monkeypatch):
    """Reuse synthetic authorization/history, but freeze actual diagnostic requests initially."""
    original_seal, original_freeze = batch_fixture.seal, batch_fixture.freeze

    def seal_with_real_diagnostic(*args, **kwargs):
        contract = kwargs["contract"]
        for spec in contract["P1"]:
            spec["target"] = FIXTURES[spec["fixture"]]
        contract["http_identity"] = {
            "endpoint": ENDPOINT,
            "model": MODEL,
            "context": 65536,
            "version": "0.27.1",
        }
        return original_seal(*args, **kwargs)

    def freeze_with_real_references(batch, name, value):
        if name == "P1_references":
            value = []
            for spec in batch.plan["P1"]:
                canonical, wire = request(spec["fixture"], spec["condition"])
                row = {
                    "episode": spec["id"],
                    "stage": "P1",
                    "fixture": spec["fixture"],
                    "condition": spec["condition"],
                    "target_sha256": fingerprint(spec["target"]),
                    "hashes": {},
                }
                for kind, body in (
                    ("canonical", canonical),
                    ("wire", wire),
                    ("output", {"raw": json.dumps({"text": spec["target"]})}),
                ):
                    path = batch.root / "references" / (spec["id"] + "." + kind + ".json")
                    save(path, body)
                    row[kind] = str(path)
                    row["hashes"][kind] = sha(path)
                value.append(row)
        return original_freeze(batch, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(batch_fixture, "seal", seal_with_real_diagnostic)
        patch.setattr(batch_fixture, "freeze", freeze_with_real_references)
        # The synthetic historical source replacement must outlive fixture construction.
        batch = batch_fixture.fixture(tmp_path, monkeypatch)
    assert type(batch) is Batch
    return batch


def run_worker(batch, monkeypatch, raw):
    calls = []
    _, expected_wire = request("T1", "D00")

    def forbidden(*args, **kwargs):
        raise AssertionError("P1 must not open sockets, Session, World or dispatcher")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for cls in (World, Session, ActionAdapter):
        monkeypatch.setattr(cls, "__init__", forbidden)

    def handle(req):
        calls.append((req.method, req.url.path, req.content))
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if req.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if req.url.path == "/tokenize":
            assert json.loads(req.content) == {key: expected_wire[key] for key in TOKENIZE_KEYS}
            return httpx.Response(200, json={"count": 77})
        assert req.url.path == "/v1/chat/completions"
        assert json.loads(req.content) == expected_wire
        return httpx.Response(
            200,
            json={
                "id": "mock-p1-integration",
                "usage": {
                    "prompt_tokens": 77,
                    "completion_tokens": 5,
                    "total_tokens": 82,
                },
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            },
        )

    def transport(*args, **kwargs):
        return Transport(*args, **kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(worker, "Transport", transport)
    observation = worker.run(batch.root, batch.binding_sha, "p1-01")
    assert [route for _, route, _ in calls] == [
        "/v1/models",
        "/version",
        "/tokenize",
        "/v1/chat/completions",
    ]
    assert not (batch.root / "worlds").exists()
    assert list(batch.root.rglob("*.sqlite")) == [batch.root / "batch.sqlite"]
    return observation, calls


@pytest.mark.parametrize(
    "mode,classification,exact,schema",
    [
        ("exact", "EXACT_COPY", True, True),
        ("short", "CONTENT_DIFFERENCE", False, True),
        ("invalid", "INVALID_STRICT_JSON", False, False),
    ],
)
def test_real_batch_worker_transport_to_parent_observation(
    tmp_path,
    monkeypatch,
    mode,
    classification,
    exact,
    schema,
):
    batch = integration_batch(tmp_path, monkeypatch)
    raw = {
        "exact": json.dumps({"text": FIXTURES["T1"]}),
        "short": '{"text":"x"}',
        "invalid": "not JSON",
    }[mode]
    observation, calls = run_worker(batch, monkeypatch, raw)
    assert observation["business_dispatches"] == 0
    assert observation["automatic_value_repair"] is False
    assert observation["content_class"] == classification
    assert observation["exact_fidelity"] is exact
    assert observation["full_schema"] is schema
    assert batch.snapshot()["episodes"][0]["status"] == "RUNNING"
    batch.freeze_artifact("p1-01_observation", batch.root / "episodes/p1-01/observation.json")
    batch.finish("p1-01", "OBSERVED")
    state = batch.snapshot()
    assert state["stop"] is None
    assert state["episodes"][0]["status"] == "OBSERVED"
    assert state["cost"]["requests"] == 1
    assert state["cost"]["known_raw_tokens"] == 82
    assert state["cost"]["actual_total_raw_tokens"] == 82
    assert state["cost"]["unresolved_reservations"] == []
    provider = batch.root / "episodes/p1-01/provider"
    events = read_events(provider / "provider-ledger-v2.jsonl")
    with batch.transaction() as db:
        assert batch.events(db) == events
        assert batch._observation(db, batch.plan["P1"][0])["exact_fidelity"] is exact
    assert [e["event"] for e in events] == [
        "RESERVED",
        "DISPATCH_STARTED",
        "RESPONSE_RECEIVED",
        "USAGE_KNOWN",
    ]
    key = observation["request_id"]
    assert read(provider / (key + "-visible.json"))["content"] == raw
    assert (provider / (key + "-request.json")).read_bytes() == calls[-1][2]


@pytest.mark.parametrize("tamper", ["raw", "usage"])
@pytest.mark.parametrize("timing", ["before_freeze", "after_freeze"])
def test_parent_rejects_mismatching_http_raw_or_usage(tmp_path, monkeypatch, tamper, timing):
    batch = integration_batch(tmp_path, monkeypatch)
    observation, _ = run_worker(batch, monkeypatch, '{"text":"x"}')
    observation_path = batch.root / "episodes/p1-01/observation.json"
    if timing == "after_freeze":
        batch.freeze_artifact("p1-01_observation", observation_path)
    path = batch.root / "episodes/p1-01/provider" / (observation["request_id"] + "-http.json")
    http = read(path)
    envelope = json.loads(http["body"])
    if tamper == "raw":
        envelope["choices"][0]["message"]["content"] = '{"text":"different"}'
    else:
        envelope["usage"]["completion_tokens"] += 1
        envelope["usage"]["total_tokens"] += 1
    http["body"] = json.dumps(envelope)
    # Deliberate corruption of this test's owned temporary evidence, never an old/live file.
    path.write_text(json.dumps(http))
    if timing == "before_freeze":
        batch.freeze_artifact("p1-01_observation", observation_path)
    reason = "RAW_HTTP_USAGE_AUDIT_FAILED" if timing == "before_freeze" else "RAW_EVIDENCE_DRIFT"
    with pytest.raises(ProviderStop, match=reason):
        batch.finish("p1-01", "OBSERVED")
    with batch.transaction() as db:
        assert db.execute("SELECT status FROM episodes WHERE id='p1-01'").fetchone()[0] == "RUNNING"
