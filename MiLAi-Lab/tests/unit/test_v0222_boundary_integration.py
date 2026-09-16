"""Actual new worker/HTTP mock/independent audit, without a network or business host."""

import copy
import json
import os
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_boundary_contract import fixture

import preflight_v0222_boundary as preflight_module
import run_v0222_boundary as runner_module
import v0222_boundary_transport as transport_module
import v0222_boundary_worker as worker_module
from v0213_provider import ENDPOINT, MODEL, payload
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import encoded, fingerprint
from v0222_boundary_audit import audit_episode, validate_preflight, validate_reference
from v0222_boundary_contract import ROOT_ORDER, SOURCE_EPISODES, audit_transform, transform
from v0222_boundary_transport import Transport
from v0222_string_contract import compile_contract


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("REAL_NETWORK_FORBIDDEN_IN_BOUNDARY_INTEGRATION")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


class FixtureBatch:
    """Only coordinator persistence is substituted; real worker/transport/auditor run."""

    def __init__(self, root, specs, references, parent):
        self.root, self.binding_sha = root, "fixture-binding"
        self.plan = {
            "episodes": specs,
            "parent_root": str(parent),
            "http_identity": {
                "endpoint": ENDPOINT,
                "model": MODEL,
                "context": 65536,
                "version": "0.27.1",
            },
        }
        self.auth = {"historical": {"sources": []}}
        self.refs, self.events, self.stopped = references, [], None
        self.gates = {
            "scope_review": {"status": "G_AUTH_SCOPE_REVIEW_PASS"},
            "engineering_checks": {"status": "ENGINEERING_CHECKS_PASS"},
        }
        self.claimed = set()

    def authorize(self, stage):
        assert stage in {"PREP", "R1"}
        return self.auth

    def artifact(self, name):
        return self.gates[name]

    def freeze_artifact(self, name, path, status=None):
        value = read(path)
        assert status is None or value["status"] == status
        assert name not in self.gates
        self.gates[name] = value

    def references(self):
        return self.refs

    @contextmanager
    def transaction(self):
        yield self

    def check_journal(self, _db):
        if self.stopped or not usage_state(self.events)["new_generation_allowed"]:
            raise ProviderStop("FIXTURE_STOPPED_OR_UNKNOWN")

    def http_admit(self, episode, *, inflight=False):
        return self.admit(episode)

    def claim(self, episode):
        assert episode not in self.claimed
        self.claimed.add(episode)

    def admit(self, episode):
        if self.stopped:
            raise ProviderStop("FIXTURE_STOPPED")
        assert episode in self.claimed
        return {"stage": "R1", "pid": os.getpid(), "deadline": time.time() + 300, "cap": 1}

    def record(self, episode, event):
        assert episode in self.claimed
        usage_state([*self.events, event])
        self.events.append(event)

    def stop(self, reason):
        self.stopped = self.stopped or reason

    def snapshot(self):
        return {"stop": self.stopped, "cost": usage_state(self.events)}


def fixture_batch(tmp_path, *, count=1, condition="B1"):
    parent, root = tmp_path / "parent", tmp_path / "new"
    specs, references = [], []
    for i in range(count):
        cold, root_index = i // 8 + 1, (i % 8) // 2
        chosen = (("B0", "B1") if cold == 1 else ("B1", "B0"))[i % 2] if count == 16 else condition
        source_episode = SOURCE_EPISODES[root_index]
        body, expected, schema = fixture()
        original = json.loads(encoded(payload(body["messages"], schema)))
        source = parent / "full-reference/P3" / source_episode / "request-01.canonical.json"
        if not source.exists():
            source.parent.mkdir(parents=True)
            source.write_text(encoded(original))
        spec = {
            "id": f"r1-{i + 1:02d}",
            "stage": "R1",
            "root": ROOT_ORDER[root_index],
            "cold": cold,
            "condition": chosen,
            "source_episode": source_episode,
            "expected": expected,
        }
        canonical = transform(original, chosen)
        compiled = compile_contract(schema, "D11")
        row = {
            "episode": spec["id"],
            "stage": "R1",
            **{k: spec[k] for k in ("root", "cold", "condition", "source_episode")},
            "source_canonical": str(source),
            "source_canonical_sha256": sha(source),
            "schema_pair": compiled.manifest(),
        }
        for kind, value in (
            ("canonical", canonical),
            ("wire", compiled.prepare(canonical)),
            ("output", {"raw": encoded(expected)}),
            ("diff", audit_transform(original, canonical, chosen)),
        ):
            path = root / "references" / (spec["id"] + "." + kind + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded(value))
            row[kind] = str(path)
        row["hashes"] = {k: sha(Path(row[k])) for k in ("canonical", "wire", "output", "diff")}
        specs.append(spec)
        references.append(row)
    return FixtureBatch(root, specs, references, parent)


def handler_for(raw, calls, *, mode="normal", count=150):
    def handler(request):
        route = request.url.path
        calls.append((request.method, route))
        if route == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if route == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if route == "/tokenize":
            body = json.loads(request.content)
            return httpx.Response(200, json={"count": 25 if "prompt" in body else count})
        assert route == "/v1/chat/completions"
        if mode == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if mode == "http500":
            return httpx.Response(500, text="fixture failure")
        envelope = {
            "id": "mock-response",
            "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": count, "completion_tokens": 20, "total_tokens": count + 20},
        }
        if mode == "no_usage":
            envelope.pop("usage")
        return httpx.Response(200, json=envelope)

    return handler


def run_mock(batch, monkeypatch, raw, *, mode="normal"):
    calls = []
    mock = httpx.MockTransport(handler_for(raw, calls, mode=mode))
    monkeypatch.setattr(worker_module, "Batch", lambda *_: batch)
    monkeypatch.setattr(
        transport_module, "historical_usage_boundary", lambda _: batch.auth["historical"]
    )
    monkeypatch.setattr(
        worker_module, "Transport", lambda *a, **k: Transport(*a, **k, transport=mock)
    )
    observation = worker_module.run(batch.root, batch.binding_sha, batch.plan["episodes"][0]["id"])
    return observation, calls


@pytest.mark.parametrize("condition", ["B0", "B1"])
@pytest.mark.parametrize(
    "case",
    ["exact", "wrong_value", "wrong_object", "invalid_json", "schema_rejected", "invalid_unicode"],
)
def test_worker_mock_http_to_independent_raw_audit(tmp_path, monkeypatch, condition, case):
    batch = fixture_batch(tmp_path, condition=condition)
    expected = batch.plan["episodes"][0]["expected"]
    value = copy.deepcopy(expected)
    if case == "wrong_value":
        value["arguments"]["data"]["text"] = "different but legal"
    elif case == "wrong_object":
        value["arguments"]["object_id"] = "different target"
    elif case == "schema_rejected":
        value["arguments"]["data"]["text"] = " \t\n "
    elif case == "invalid_unicode":
        value["arguments"]["data"]["text"] = "\ud800"
    raw = "{invalid" if case == "invalid_json" else json.dumps(value)
    result, calls = run_mock(batch, monkeypatch, raw)
    audited = audit_episode(batch, "r1-01")
    assert audited["exact_fidelity"] is (case == "exact")
    assert result["classification"] == audited["classification"]
    assert audited["cost"]["known_raw_tokens"] == 170
    assert audited["business_dispatches"] == 0 and batch.stopped is None
    assert calls.count(("POST", "/v1/chat/completions")) == 1
    assert not (batch.root / "worlds").exists()
    saved = batch.root / "episodes/r1-01/independent-observation.json"
    save(saved, audited)
    assert fingerprint(audit_episode(batch, "r1-01")) == fingerprint(audited)


@pytest.mark.parametrize("mode", ["http500", "timeout", "no_usage"])
def test_real_transport_failure_is_not_content_observation(tmp_path, monkeypatch, mode):
    batch = fixture_batch(tmp_path)
    with pytest.raises(ProviderStop):
        run_mock(batch, monkeypatch, encoded(batch.plan["episodes"][0]["expected"]), mode=mode)
    assert batch.stopped and len(batch.snapshot()["cost"]["unresolved_reservations"]) == 1
    assert not (batch.root / "episodes/r1-01/observation.json").exists()


@pytest.mark.parametrize(
    "tamper", ["tokenize_request", "tokenize_http", "visible", "worker", "wire", "world"]
)
def test_independent_audit_rejects_tampered_actual_trace(tmp_path, monkeypatch, tamper):
    batch = fixture_batch(tmp_path)
    result, _ = run_mock(batch, monkeypatch, encoded(batch.plan["episodes"][0]["expected"]))
    provider = batch.root / "episodes/r1-01/provider"
    key = result["request_id"]
    if tamper == "world":
        (batch.root / "worlds").mkdir()
    else:
        paths = {
            "tokenize_request": provider / (key + "-tokenize-request.json"),
            "tokenize_http": provider / (key + "-tokenize-http.json"),
            "visible": provider / (key + "-visible.json"),
            "worker": batch.root / "episodes/r1-01/observation.json",
            "wire": provider / (key + "-request.json"),
        }
        path = paths[tamper]
        value = read(path)
        if tamper == "tokenize_request":
            value["messages"] = []
        elif tamper == "tokenize_http":
            value["body"] = '{"count":150.0}'
        elif tamper == "visible":
            value["content"] = "{}"
        elif tamper == "worker":
            value["exact_fidelity"] = False
        else:
            value["messages"] = []
        path.write_text(encoded(value))
    with pytest.raises(ProviderStop):
        audit_episode(batch, "r1-01")


def test_complete_mock_capacity_preflight_is32_tokenizes_and_zero_generations(
    tmp_path, monkeypatch
):
    batch = fixture_batch(tmp_path, count=16)
    monkeypatch.setattr(preflight_module, "Batch", lambda *_: batch)
    calls = []
    result = preflight_module.preflight(
        batch.root,
        batch.binding_sha,
        transport=httpx.MockTransport(handler_for("unused", calls)),
    )
    assert result["status"] == "G_PREFLIGHT_PASS" and len(result["rows"]) == 16
    assert calls.count(("POST", "/tokenize")) == 32
    assert not any(path == "/v1/chat/completions" for _, path in calls)
    assert len([1 for method, _ in calls if method == "GET"]) == 4
    assert batch.gates["preflight"]["status"] == "G_PREFLIGHT_PASS"
    validate_preflight(batch, result)


def test_capacity_failure_keeps_all_sources_and_stops(tmp_path, monkeypatch):
    batch = fixture_batch(tmp_path, count=16)
    monkeypatch.setattr(preflight_module, "Batch", lambda *_: batch)
    calls = []
    result = preflight_module.preflight(
        batch.root,
        batch.binding_sha,
        transport=httpx.MockTransport(handler_for("unused", calls, count=62000)),
    )
    assert result["status"] == "NOT_MET" and batch.stopped
    assert calls.count(("POST", "/tokenize")) == 2
    assert "preflight" not in batch.gates


def test_reference_cannot_substitute_another_authorized_target(tmp_path):
    batch = fixture_batch(tmp_path)
    spec = copy.deepcopy(batch.plan["episodes"][0])
    spec["expected"]["arguments"]["object_id"] = "other"
    with pytest.raises(ProviderStop, match="ORIGINAL_AUTHORIZED"):
        validate_reference(batch, batch.refs[0], spec)


@pytest.mark.parametrize("stop_after", [1, 2, 3, 34, 35, 36])
def test_preflight_checks_stop_before_every_actual_http(tmp_path, monkeypatch, stop_after):
    batch = fixture_batch(tmp_path, count=16)
    monkeypatch.setattr(preflight_module, "Batch", lambda *_: batch)
    calls = []
    base = handler_for("unused", calls)

    def handler(request):
        response = base(request)
        if len(calls) == stop_after:
            batch.stop("EXTERNAL_TEST_STOP")
        return response

    result = preflight_module.preflight(
        batch.root, batch.binding_sha, transport=httpx.MockTransport(handler)
    )
    assert result["status"] == "NOT_MET"
    assert batch.stopped == "EXTERNAL_TEST_STOP"
    assert len(calls) == stop_after
    assert "preflight" not in batch.gates


def test_preflight_final_receipt_write_error_permanently_stops(tmp_path, monkeypatch):
    batch = fixture_batch(tmp_path, count=16)
    monkeypatch.setattr(preflight_module, "Batch", lambda *_: batch)
    calls = []

    def fail_result(path, value):
        if path.name == "result.json":
            raise OSError("FINAL_RESULT_STORAGE_FAILED")
        save(path, value)

    monkeypatch.setattr(preflight_module, "save", fail_result)
    with pytest.raises(OSError):
        preflight_module.preflight(
            batch.root,
            batch.binding_sha,
            transport=httpx.MockTransport(handler_for("unused", calls)),
        )
    assert len(calls) == 36 and batch.stopped == "OSError"
    assert "preflight" not in batch.gates


@pytest.mark.parametrize("mode", ["tokenize201", "tokenize_float", "identity201", "context_float"])
def test_preflight_requires200_and_strict_integer_receipts(tmp_path, monkeypatch, mode):
    batch = fixture_batch(tmp_path, count=16)
    monkeypatch.setattr(preflight_module, "Batch", lambda *_: batch)
    calls = []
    base = handler_for("unused", calls)

    def handler(request):
        response = base(request)
        if mode == "tokenize201" and request.url.path == "/tokenize":
            return httpx.Response(201, json={"count": 150})
        if mode == "tokenize_float" and request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 150.0})
        if mode == "identity201" and request.url.path == "/v1/models":
            return httpx.Response(201, json=response.json())
        if mode == "context_float" and request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536.0}]})
        return response

    result = preflight_module.preflight(
        batch.root, batch.binding_sha, transport=httpx.MockTransport(handler)
    )
    assert result["status"] == "NOT_MET" and batch.stopped
    assert "preflight" not in batch.gates


def test_label_and_rehashed_bad_count_cannot_forge_preflight_gate(tmp_path, monkeypatch):
    batch = fixture_batch(tmp_path, count=16)
    monkeypatch.setattr(preflight_module, "Batch", lambda *_: batch)
    result = preflight_module.preflight(
        batch.root, batch.binding_sha, transport=httpx.MockTransport(handler_for("unused", []))
    )
    path = batch.root / "preflight/r1-01-input.http.json"
    bad = read(path)
    bad["body"] = '{"count":150.0}'
    path.write_text(encoded(bad))
    result["files"][str(path)] = sha(path)
    with pytest.raises(ProviderStop, match="STRICT_INTEGER"):
        validate_preflight(batch, result)


def test_runner_final_result_storage_error_sets_stop(tmp_path, monkeypatch):
    batch = fixture_batch(tmp_path, count=16)
    batch.launch_once = lambda: None
    batch.decision = lambda final=False: {
        "status": "NO_DIFFERENTIAL_SIGNAL",
        "repeat_required": False,
    }
    batch.set_decision = lambda *_, **__: None
    batch.finish = lambda episode: {"id": episode, "pid": os.getpid() + 1, "exact_fidelity": False}
    batch.snapshot = lambda: {
        "stop": batch.stopped,
        "cost": {"known_raw_tokens": 0},
        "episodes": [{**s, "status": "PENDING"} for s in batch.plan["episodes"]],
    }
    monkeypatch.setattr(runner_module, "Batch", lambda *_: batch)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda *a, **k: runner_module.subprocess.CompletedProcess(a[0], 0, "", ""),
    )

    def fail_result(path, value):
        if path.name == "result.json":
            raise OSError("FINAL_RESULT_STORAGE_FAILED")
        save(path, value)

    monkeypatch.setattr(runner_module, "save", fail_result)
    with pytest.raises(OSError):
        runner_module.run(batch.root, batch.binding_sha)
    assert batch.stopped == "OSError"
