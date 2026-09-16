"""MockHTTP + fake Batch/source admission; not a live-instance approval.

The production raw-receipt preflight auditor is retained. Only source-reference
reconstruction and Batch's already-separately-tested authorization layer are fake.
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import preflight_v0222_presentation as module
import v0222_presentation_audit as audit
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import save, sha
from v0220_provider_hardened import ProviderStop
from v0222_diagnostic import request


class FakeBatch:
    def __init__(self, root):
        self.root = root
        self.stopped = None
        self.frozen = []
        self.events = []
        self.plan = {
            "http_identity": {
                "endpoint": ENDPOINT,
                "model": MODEL,
                "context": 65536,
                "version": "0.27.1",
            },
            "P3": [{"id": f"p3-{i:02d}"} for i in range(1, 17)],
            "P4": [
                {"id": f"p4-{i:02d}", "actions": [{}] * (2 if i <= 8 else 1)} for i in range(1, 25)
            ],
        }
        self.refs = {
            stage: [
                {"episode": spec["id"], "turn": turn, "hashes": {"mock": "source"}}
                for spec in self.plan[stage]
                for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
            ]
            for stage in ("P3", "P4")
        }

    def authorize(self, stage):
        self.events.append(("authorize", stage))
        if self.stopped:
            raise ProviderStop("BATCH_STOPPED")

    @contextmanager
    def transaction(self):
        yield None

    def check_journal(self, db):
        self.events.append(("journal", None))
        if self.stopped:
            raise ProviderStop("BATCH_STOPPED")

    def artifact(self, name):
        return {
            "status": {
                "scope_review": "G_AUTH_SCOPE_REVIEW_PASS",
                "engineering_checks": "ENGINEERING_CHECKS_PASS",
            }[name]
        }

    def references(self, stage):
        return self.refs[stage]

    def spec(self, episode):
        return next(s for stage in ("P3", "P4") for s in self.plan[stage] if s["id"] == episode)

    def stop(self, reason):
        self.events.append(("stop", reason))
        self.stopped = self.stopped or reason

    def freeze_artifact(self, name, path, status):
        value = json.loads(path.read_text())
        assert value["status"] == status
        audit.validate_preflight(self, value, name[:2])
        self.frozen.append(name)


def setup(tmp_path, monkeypatch, mode="valid"):
    batch = FakeBatch(tmp_path)
    monkeypatch.setattr(module, "Batch", lambda root, binding: batch)
    _, wire = request("T1", "D00")
    raw = '{"完整":"保留 \\n Unicode 世界", "nested": [1, 2, 3]}'

    def reference(*args):
        return {}, {}, wire, raw

    monkeypatch.setattr(module, "validate_reference", reference)
    monkeypatch.setattr(audit, "validate_reference", reference)
    calls, bodies = [], []

    def handle(req):
        assert batch.events[-2][0] == "authorize"
        assert batch.events[-1] == ("journal", None)
        calls.append(req.url.path)
        batch.events.append(("http", req.url.path))
        index = len(calls)
        if mode == "stop_models" and index == 1:
            batch.stop("TEST_STOP")
        if mode == "stop_tokenize" and index == 3:
            batch.stop("TEST_STOP")
        if mode == "stop_final" and index == 36:
            batch.stop("TEST_STOP")
        if req.url.path == "/v1/models":
            return httpx.Response(
                201 if mode == "identity_201" else 200,
                json={
                    "data": [
                        {
                            "id": MODEL,
                            "max_model_len": 65536.0 if mode == "context_float" else 65536,
                        }
                    ]
                },
            )
        if req.url.path == "/version":
            return httpx.Response(
                200, json={"version": "drift" if mode == "version_drift" else "0.27.1"}
            )
        assert req.url.path == "/tokenize", "No generation route may be used"
        body = json.loads(req.content)
        bodies.append(body)
        if "prompt" in body:
            assert body == {"model": MODEL, "prompt": raw, "add_special_tokens": False}
            count = 4096 if mode == "output_overflow" else 100
        else:
            assert body == {key: wire[key] for key in TOKENIZE_KEYS}
            count = 61441 if mode == "input_overflow" else 1000
        count = {"bool": True, "float": 1.0, "negative": -1}.get(mode, count)
        if mode == "duplicate_count":
            return httpx.Response(200, text='{"count":1,"count":2}')
        if mode == "timeout":
            raise httpx.ReadTimeout("mock")
        return httpx.Response(201 if mode == "tokenize_201" else 200, json={"count": count})

    return batch, httpx.MockTransport(handle), calls, bodies


@pytest.mark.parametrize("stage,nrefs,nfiles", [("P3", 16, 104), ("P4", 80, 488)])
def test_complete_capacity_and_real_receipt_audit(tmp_path, monkeypatch, stage, nrefs, nfiles):
    batch, transport, calls, bodies = setup(tmp_path, monkeypatch)
    result = module.preflight(tmp_path, "mock-binding", stage, transport=transport)
    assert result["status"] == "G_PREFLIGHT_PASS"
    assert len(result["rows"]) == nrefs
    assert len(result["files"]) == nfiles
    assert len(bodies) == nrefs * 2
    assert calls.count("/tokenize") == nrefs * 2
    assert calls.count("/v1/models") == calls.count("/version") == 2
    assert batch.frozen == [stage + "_preflight"]
    assert batch.stopped is None
    assert result["preflight_window_seconds"] == {"P3": 1200, "P4": 2400}[stage]
    assert result["model_requests"] == result["direct_device_calls"] == 0
    assert all(sha(Path(path)) == value for path, value in result["files"].items())


@pytest.mark.parametrize(
    "mode,requests",
    [
        ("stop_models", 1),
        ("stop_tokenize", 3),
        ("stop_final", 36),
        ("identity_201", 1),
        ("context_float", 2),
        ("version_drift", 2),
        ("tokenize_201", 3),
        ("bool", 3),
        ("float", 3),
        ("negative", 3),
        ("duplicate_count", 3),
        ("timeout", 3),
        ("input_overflow", 4),
        ("output_overflow", 4),
    ],
)
def test_http_failure_stops_without_more_requests(tmp_path, monkeypatch, mode, requests):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch, mode)
    result = module.preflight(tmp_path, "mock", "P3", transport=transport)
    assert result["status"] == "NOT_MET"
    assert batch.stopped and not batch.frozen
    assert len(calls) == requests


@pytest.mark.parametrize(
    "problem", ["stage", "scope", "engineering", "positions", "count", "stopped", "duplicate"]
)
def test_no_http_before_admission(tmp_path, monkeypatch, problem):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    stage = "P3"
    if problem == "stage":
        stage = "R1"
    elif problem in {"scope", "engineering"}:
        monkeypatch.setattr(batch, "artifact", lambda name: {"status": "NOT_MET"})
    elif problem == "positions":
        batch.refs[stage].reverse()
    elif problem == "count":
        batch.refs[stage].pop()
    elif problem == "stopped":
        batch.stop("PREEXISTING_STOP")
    else:
        (tmp_path / "P3-preflight").mkdir()
        save(tmp_path / "P3-preflight" / "result.json", {"prior": True})
    with pytest.raises((ProviderStop, FileExistsError)):
        module.preflight(tmp_path, "mock", stage, transport=transport)
    assert batch.stopped and not calls
    if problem == "duplicate":
        assert json.loads((tmp_path / "P3-preflight/result.json").read_text()) == {"prior": True}


@pytest.mark.parametrize("suffix", [".request.json", ".attempt.json", ".http.json", "result.json"])
def test_save_failure_stops_before_failure_report(tmp_path, monkeypatch, suffix):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    original = module.save

    def broken(path, value):
        if str(path).endswith(suffix):
            raise OSError("mock persistence failure")
        if path.name == "result.json" and value["status"] == "NOT_MET":
            assert batch.stopped
        original(path, value)

    monkeypatch.setattr(module, "save", broken)
    if suffix == "result.json":
        with pytest.raises(OSError):
            module.preflight(tmp_path, "mock", "P3", transport=transport)
    else:
        assert module.preflight(tmp_path, "mock", "P3", transport=transport)["status"] == "NOT_MET"
    assert batch.stopped and not batch.frozen
    assert len(calls) == (36 if suffix == "result.json" else 3 if suffix == ".http.json" else 2)


def test_stop_after_attempt_save_is_checked_before_send(tmp_path, monkeypatch):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    original = module.save

    def stop_after_save(path, value):
        original(path, value)
        if str(path).endswith(".attempt.json"):
            batch.stop("STOP_DURING_PREPARATION")

    monkeypatch.setattr(module, "save", stop_after_save)
    assert module.preflight(tmp_path, "mock", "P3", transport=transport)["status"] == "NOT_MET"
    assert len(calls) == 2


@pytest.mark.parametrize("moment", ["before", "tokenize", "freeze"])
def test_finite_window_counts_validation_and_freeze(tmp_path, monkeypatch, moment):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    original_authorize = batch.authorize
    original_freeze = batch.freeze_artifact

    def authorize(stage):
        original_authorize(stage)
        if moment == "before" or (moment == "tokenize" and len(calls) == 2):
            clock[0] = 1196

    def freeze(*args):
        original_freeze(*args)
        clock[0] = 1201

    monkeypatch.setattr(batch, "authorize", authorize)
    if moment == "freeze":
        monkeypatch.setattr(batch, "freeze_artifact", freeze)
    if moment in {"before", "freeze"}:
        with pytest.raises(ProviderStop, match="DEADLINE"):
            module.preflight(tmp_path, "mock", "P3", transport=transport)
    else:
        assert module.preflight(tmp_path, "mock", "P3", transport=transport)["status"] == "NOT_MET"
    assert batch.stopped
    assert len(calls) == {"before": 0, "tokenize": 2, "freeze": 36}[moment]


@pytest.mark.parametrize("change", ["extra", "missing", "body", "count", "attempt", "row", "calls"])
def test_real_auditor_rejects_tampering_even_rehashed(tmp_path, monkeypatch, change):
    batch, transport, _, _ = setup(tmp_path, monkeypatch)
    result = module.preflight(tmp_path, "mock", "P3", transport=transport)
    directory = tmp_path / "P3-preflight"
    if change == "extra":
        save(directory / "hidden-attempt.json", {"method": "POST"})
    elif change == "missing":
        result["files"].pop(next(iter(result["files"])))
    elif change in {"body", "count", "attempt"}:
        suffix = {"body": "request", "count": "http", "attempt": "attempt"}[change]
        path = directory / f"p3-01-01-input.{suffix}.json"
        value = json.loads(path.read_text())
        if change == "body":
            value["messages"] = []
        elif change == "count":
            value["body"] = '{"count": 1000.0}'
        else:
            value["turn"] = 2
        # Deliberately corrupt only this synthetic temporary receipt.
        path.write_text(json.dumps(value), encoding="utf-8")
        result["files"][str(path)] = sha(path)
    elif change == "row":
        result["rows"][0]["counts"]["input"] = 42
    else:
        result["tokenize_calls"].reverse()
    with pytest.raises(ProviderStop):
        audit.validate_preflight(batch, result, "P3")


@pytest.mark.parametrize("failure", ["hash", "freeze"])
def test_final_failure_stops_without_retry(tmp_path, monkeypatch, failure):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)

    def broken(*args):
        raise OSError("mock")

    monkeypatch.setattr(
        module if failure == "hash" else batch,
        "sha" if failure == "hash" else "freeze_artifact",
        broken,
    )
    with pytest.raises(OSError):
        module.preflight(tmp_path, "mock", "P3", transport=transport)
    assert len(calls) == 36 and batch.stopped and not batch.frozen


@pytest.mark.parametrize("name,requests", [("models-attempt.json", 0), ("models.json", 1)])
def test_identity_save_failure_stops_before_result(tmp_path, monkeypatch, name, requests):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    original = module.save

    def broken_identity(path, value):
        if path.name == name:
            raise OSError("identity persistence failed")
        original(path, value)

    def save_result(path, value):
        if path.name == "result.json":
            assert batch.stopped and value["status"] == "NOT_MET"
        original(path, value)

    monkeypatch.setattr("v0222_presentation_http.save", broken_identity)
    monkeypatch.setattr(module, "save", save_result)
    result = module.preflight(tmp_path, "mock", "P3", transport=transport)
    assert result["status"] == "NOT_MET" and len(calls) == requests
    assert not batch.frozen


def test_http_timer_excludes_expensive_authorization(tmp_path, monkeypatch):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    clock = [0.0]
    original_authorize = batch.authorize
    original_request = module.bounded_request
    checked = []

    def authorize(stage):
        original_authorize(stage)
        clock[0] += 3

    def bounded(*args, **kwargs):
        assert kwargs["timeout"] == 5
        before = clock[0]
        response = original_request(*args, **kwargs)
        assert clock[0] == before
        checked.append(True)
        return response

    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(batch, "authorize", authorize)
    monkeypatch.setattr(module, "bounded_request", bounded)
    monkeypatch.setattr("v0222_presentation_http.bounded_request", bounded)
    assert (
        module.preflight(tmp_path, "mock", "P3", transport=transport)["status"]
        == "G_PREFLIGHT_PASS"
    )
    assert len(checked) == len(calls) == 36


def test_extra_actual_receipt_blocks_success_freeze(tmp_path, monkeypatch):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)
    original = module.validate_reference

    def extra(*args):
        path = tmp_path / "P3-preflight" / "unexpected-attempt.json"
        if not path.exists():
            save(path, {"method": "POST", "route": "/tokenize"})
        return original(*args)

    monkeypatch.setattr(module, "validate_reference", extra)
    with pytest.raises(ProviderStop, match="EXACT_COMPLETE_PREFLIGHT_RECEIPTS"):
        module.preflight(tmp_path, "mock", "P3", transport=transport)
    assert len(calls) == 36 and batch.stopped and not batch.frozen


@pytest.mark.parametrize(
    "phase,name,expected",
    [
        ("identity-start", "models-attempt.json", 0),
        ("identity-start", "version-attempt.json", 1),
        ("identity-final", "models-attempt.json", 34),
        ("identity-final", "version-attempt.json", 35),
    ],
)
def test_identity_attempt_save_then_stop_never_sends_next_get(
    tmp_path, monkeypatch, phase, name, expected
):
    batch, transport, calls, _ = setup(tmp_path, monkeypatch)

    def persist(path, value):
        save(path, value)
        if path.parent.name == phase and path.name == name:
            batch.stop("STOP_AFTER_IDENTITY_ATTEMPT")

    monkeypatch.setattr("v0222_presentation_http.save", persist)
    result = module.preflight(tmp_path, "mock", "P3", transport=transport)
    assert result["status"] == "NOT_MET" and len(calls) == expected
    assert batch.stopped == "STOP_AFTER_IDENTITY_ATTEMPT" and not batch.frozen


@pytest.mark.parametrize("binding_matches", [True, False])
def test_constructor_failure_only_stops_exact_existing_bound_journal(
    tmp_path, monkeypatch, binding_matches
):
    save(tmp_path / "execution-binding.json", {"TEST_ONLY": True})
    binding = sha(tmp_path / "execution-binding.json")
    with sqlite3.connect(tmp_path / "batch.sqlite") as db:
        db.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE episodes(status TEXT)"
        )
        db.execute("INSERT INTO meta VALUES ('binding',?)", (binding,))
        db.execute("INSERT INTO episodes VALUES ('RUNNING')")

    def broken(*_args):
        raise ProviderStop("FROZEN_SOURCE_DRIFT")

    monkeypatch.setattr(module, "Batch", broken)
    monkeypatch.setattr("v0222_presentation_worker.ROOT", tmp_path)
    with pytest.raises(ProviderStop, match="FROZEN_SOURCE_DRIFT"):
        module.preflight(tmp_path, binding if binding_matches else "wrong", "P3")
    with sqlite3.connect(tmp_path / "batch.sqlite") as db:
        stop = db.execute("SELECT value FROM meta WHERE key='stop'").fetchone()
        state = db.execute("SELECT status FROM episodes").fetchone()[0]
    assert stop == (("FROZEN_SOURCE_DRIFT",) if binding_matches else None)
    assert state == ("FAIL" if binding_matches else "RUNNING")
    assert not (tmp_path / "P3-preflight").exists()
