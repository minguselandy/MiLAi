"""Real frozen sources/history and coordinator; HTTP receipts are TEST_ONLY mocks.

No production root, historical hash, authorization, or validator is substituted.
The two instance ROOT constants are redirected to pytest's disposable directory.
"""

import copy
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import preflight_v0222_boundary as preflight_module
import prepare_v0222_boundary as prepare_module
import v0222_boundary_batch as batch_module
import v0222_boundary_worker as worker_module
from v0213_provider import MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_boundary_audit import audit_episode, validate_preflight, validate_reference
from v0222_boundary_batch import Batch
from v0222_boundary_contract import ROOT_ORDER, SOURCE_EPISODES, audit_transform, observe
from v0222_boundary_transport import Transport
from v0222_string_contract import compile_contract


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("REAL_NETWORK_FORBIDDEN_IN_PREPARATION_TEST")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def parent_snapshot():
    """Read-only semantic SQL plus durable file hashes; never checkpoint the parent."""
    parent = batch_module.PARENT_ROOT
    connection = sqlite3.connect(f"file:{parent / 'batch.sqlite'}?mode=ro", uri=True)
    try:
        tables = {
            name: connection.execute(  # nosec: table names are the fixed tuple below.
                f'SELECT * FROM "{name}" ORDER BY rowid'  # noqa: S608
            ).fetchall()
            for name in ("meta", "episodes", "events", "artifacts", "launches")
        }
        assert dict(tables["meta"])["stop"] == batch_module.PARENT_STOP
    finally:
        connection.close()
    paths = [
        parent / "batch.sqlite",
        parent / "execution-binding.json",
        parent / "P3-independent-review.json",
        *(Path(path) for path, _ in batch_module.HISTORICAL_SOURCES),
    ]
    # SHM contains reader locks, not durable business data; do not compare it.
    wal = parent / "batch.sqlite-wal"
    if wal.exists():
        paths.append(wal)
    return {"tables": tables, "files": {str(path): sha(path) for path in paths}}


def test_actual_frozen_prepare_preflight_and_owned_worker(tmp_path, monkeypatch):
    before = parent_snapshot()
    root = (tmp_path / "TEST_ONLY_boundary_instance").resolve()
    monkeypatch.setattr(prepare_module, "ROOT", root)
    monkeypatch.setattr(batch_module, "ROOT", root)
    result = prepare_module.prepare(root)
    assert result == {
        "status": "PREPARED_NOT_REVIEWED_NOT_LIVE",
        "binding_sha256": sha(root / "execution-binding.json"),
        "positions": 16,
        "source_roots": 4,
        "candidate_count": 1,
        "model_requests": 0,
        "http_requests": 0,
        "business_dispatches": 0,
    }
    batch = Batch(root, result["binding_sha256"])
    history = batch.auth["historical"]
    assert history["sources"] == [
        {"path": path, "sha256": digest} for path, digest in batch_module.HISTORICAL_SOURCES
    ]
    assert len(history["sources"]) == 28
    assert (history["requests"], history["known_raw_tokens"]) == (29, 62874)
    assert history["reserved_raw_upper_bound"] == 28284
    assert len(history["unresolved_reservations"]) == 1
    assert batch.plan["business_execution"] is False
    assert batch.plan["selected_decoder"] == "D11"
    assert batch.plan["parent_binding"] == batch_module.PARENT_BINDING
    assert read(root / "coordinator-created.json") == {"binding_sha256": batch.binding_sha}
    snapshot = batch.snapshot()
    assert snapshot["stop"] is None
    assert snapshot["cost"]["requests"] == 0
    assert len(snapshot["episodes"]) == 16
    assert {row["status"] for row in snapshot["episodes"]} == {"PENDING"}
    with batch.transaction() as db:
        assert batch.check_journal(db)["requests"] == 0
        assert db.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0

    references = batch.references()
    assert len(references) == 16
    assert {row["root"] for row in references} == set(ROOT_ORDER)
    assert {row["source_episode"] for row in references} == set(SOURCE_EPISODES)
    assert [row["condition"] for row in references] == ["B0", "B1"] * 4 + ["B1", "B0"] * 4
    originals, validated = {}, []
    for reference, spec in zip(references, batch.plan["episodes"], strict=True):
        source_path = Path(reference["source_canonical"])
        assert source_path == (
            batch_module.PARENT_ROOT
            / "full-reference/P3"
            / spec["source_episode"]
            / "request-01.canonical.json"
        )
        original = read(source_path)
        canonical, wire, raw = validate_reference(batch, reference, spec)
        schema = original["response_format"]["json_schema"]["schema"]
        compiled = compile_contract(schema, "D11")
        assert reference["schema_pair"] == compiled.manifest()
        assert canonical["response_format"] == original["response_format"]
        assert wire["response_format"]["json_schema"]["schema"] == compiled.wire
        assert wire["messages"][0]["content"] == (
            original["messages"][0]["content"] + "\n\n" + compiled.notice
        )
        assert wire["messages"][1:] == canonical["messages"][1:]
        assert {k: v for k, v in canonical.items() if k != "messages"} == {
            k: v for k, v in original.items() if k != "messages"
        }
        observation = observe(spec["expected"], schema, raw)
        assert observation["full_schema"] and observation["exact_fidelity"]
        diff = audit_transform(original, canonical, spec["condition"])
        assert diff == read(Path(reference["diff"]))
        assert all(diff["checks"].values())
        presentation = json.loads(original["messages"][-1]["content"])
        assert presentation["authorized_intent"]["authorized_action"] == spec["expected"]
        if spec["condition"] == "B0":
            assert Path(reference["canonical"]).read_bytes() == source_path.read_bytes()
        else:
            remainder = json.loads(canonical["messages"][-2]["content"])
            assert remainder == {k: v for k, v in presentation.items() if k != "authorized_intent"}
            assert json.loads(canonical["messages"][-1]["content"]) == {
                "authorized_intent": presentation["authorized_intent"]
            }
        originals[spec["source_episode"]] = spec["expected"]
        validated.append((canonical, wire, raw))
    assert [originals[ep]["arguments"]["object_id"] for ep in SOURCE_EPISODES] == [
        "manager_report",
        "manager_report",
        "placement_plan",
        "triage",
    ]
    assert parent_snapshot() == before

    # These are test harness gates, not a reviewer signature or online authorization.
    for name, status in (
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
    ):
        path = root / ("TEST_ONLY_" + name + ".json")
        save(
            path,
            {
                "status": status,
                "test_only": True,
                "claim": "MOCK_HTTP_ONLY_NOT_A_REAL_SCOPE_APPROVAL_OR_BUSINESS_RESULT",
                "files": {str(root / "manifest.json"): sha(root / "manifest.json")},
            },
        )
        batch.freeze_artifact(name, path, status)
        assert batch.artifact(name)["test_only"] is True

    calls, tokenize_bodies = [], []

    def preflight_http(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        assert (request.method, request.url.path) == ("POST", "/tokenize")
        body = json.loads(request.content)
        tokenize_bodies.append(body)
        return httpx.Response(200, json={"count": 25 if "prompt" in body else 150})

    gate = preflight_module.preflight(
        root, batch.binding_sha, transport=httpx.MockTransport(preflight_http)
    )
    assert gate["status"] == "G_PREFLIGHT_PASS", gate.get("reason")
    assert gate["model_requests"] == 0
    assert len(gate["rows"]) == 16 and len(gate["tokenize_calls"]) == 32
    assert len(calls) == 36 and calls.count(("POST", "/tokenize")) == 32
    assert tokenize_bodies == [
        body
        for _, wire, raw in validated
        for body in (
            {k: wire[k] for k in TOKENIZE_KEYS},
            {"model": MODEL, "prompt": raw, "add_special_tokens": False},
        )
    ]
    assert batch.artifact("preflight") == gate
    validate_preflight(batch, gate)
    assert batch.snapshot()["cost"]["requests"] == 0
    assert parent_snapshot() == before

    # Negative independent receipt audit without changing any frozen artifact.
    altered = copy.deepcopy(gate)
    altered["rows"][0]["counts"]["input"] += 1
    with pytest.raises(ProviderStop, match="PREFLIGHT_COMPLETE_CAPACITY_OR_ROW_DRIFT"):
        validate_preflight(batch, altered)

    worker_calls = []
    _, first_wire, first_raw = validated[0]

    def worker_http(request):
        worker_calls.append((request.method, request.url.path))
        if request.url.path != "/v1/chat/completions":
            return preflight_http(request)
        assert json.loads(request.content) == first_wire
        return httpx.Response(
            200,
            json={
                "id": "TEST_ONLY_frozen_source_completion",
                "choices": [{"message": {"content": first_raw}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 150, "completion_tokens": 20, "total_tokens": 170},
            },
        )

    mock = httpx.MockTransport(worker_http)
    monkeypatch.setattr(
        worker_module, "Transport", lambda *a, **kw: Transport(*a, **kw, transport=mock)
    )
    parent_pid = os.getpid()
    batch.launch_once()
    with monkeypatch.context() as child:
        child.setattr(os, "getpid", lambda: parent_pid + 100000)
        worker_observation = worker_module.run(root, batch.binding_sha, "r1-01")
    assert worker_observation["exact_fidelity"] is True
    finished = batch.finish("r1-01")
    assert finished["exact_fidelity"] is True
    assert fingerprint(audit_episode(batch, "r1-01")) == fingerprint(finished)
    assert batch.artifact("r1-01_observation") == finished
    assert worker_calls.count(("POST", "/v1/chat/completions")) == 1
    snapshot = batch.snapshot()
    assert snapshot["stop"] is None
    assert snapshot["cost"]["requests"] == 1
    assert snapshot["cost"]["known_raw_tokens"] == 170
    assert snapshot["cost"]["unresolved_reservations"] == []
    assert snapshot["episodes"][0]["status"] == "OBSERVED"
    assert all(row["status"] == "PENDING" for row in snapshot["episodes"][1:])
    with batch.transaction() as db:
        assert batch.check_journal(db)["requests"] == 1
    assert finished["business_dispatches"] == 0
    assert not list(root.rglob("world*"))
    assert not list(root.rglob("turn*.json"))
    assert parent_snapshot() == before
