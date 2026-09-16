"""Offline full references and Mock HTTP capacity; no live service/episodes."""

import copy
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

import preflight_v0222_full as preflight_module
from prepare_v0222_full import prepare_p3, prepare_p4, resolve_p4_spec, write_reference
from v0213_provider import ENDPOINT, MODEL, payload
from v0218_world import digest
from v0220_evidence import read
from v0220_provider_hardened import ProviderStop
from v0220_session import SessionContract


def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No real network allowed in full preparation tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def p4_spec():
    return {
        "id": "p4-test",
        "stage": "P4",
        "scope": "new-frozen-scope",
        "root": "synthetic",
        "actions": [put(), put("right", 1)],
        "intent": {"ordered_writes": [put(), put("right", 1)]},
        "initial_state_sha256": "old-derived-not-for-new-scope",
        "cold": 1,
    }


def test_resolution_changes_only_derived_hash_and_not_input():
    spec, data = p4_spec(), public()
    before = copy.deepcopy(spec)
    resolved, diff = resolve_p4_spec(spec, data)
    assert spec == before
    assert {k: v for k, v in resolved.items() if k != "initial_state_sha256"} == {
        k: v for k, v in spec.items() if k != "initial_state_sha256"
    }
    assert diff["scope_unchanged"] and diff["actions_and_intent_unchanged"]
    assert resolved["initial_state_sha256"] == digest(
        {**data, "scope": spec["scope"], "version": 0, "records": {}, "pending": {}, "history": []}
    )


@pytest.mark.parametrize("variant", ["full", "finish"])
def test_full_sources_all_targets_and_reference_value_unchanged(tmp_path, monkeypatch, variant):
    forbid_network(monkeypatch)
    expected = (
        put() if variant == "full" else {"action": "finish", "arguments": {"message": "done"}}
    )
    spec = {
        "id": "p3-test",
        "stage": "P3",
        "scope": "fresh",
        "root": "synthetic",
        "variant": variant,
        "expected": expected,
    }
    rows = prepare_p3(tmp_path / "reference", spec, public(), "D11", lambda: None)
    assert len(rows) == 1
    canonical = read(Path(rows[0]["canonical"]))
    presentation = json.loads(canonical["messages"][-1]["content"])
    assert presentation["authorized_intent"]["authorized_action"] == expected
    assert presentation["inherited_note"] is None
    assert {r["resource"] for r in presentation["observations"]} == {
        "task",
        "policy",
        "current",
        "history",
        "records",
        "pending",
    }
    assert json.loads(read(Path(rows[0]["output"]))["raw"]) == expected
    assert read(tmp_path / "reference/reference-validation.json")["legal_targets"] == [
        "left",
        "right",
    ]
    wire, _ = preflight_module.validate_reference(rows[0], "D11")
    assert wire["messages"][-1] == canonical["messages"][-1]


def test_two_writes_original_session_readback_finish_and_independent_effects(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    rows, resolution = prepare_p4(tmp_path / "reference", p4_spec(), public(), "D11", lambda: None)
    assert len(rows) == 4
    assert resolution["spec"]["scope"] == p4_spec()["scope"]
    assert read(tmp_path / "reference/independent-effects.json")["status"] == "PASS"
    outputs = [json.loads(read(Path(r["output"]))["raw"]) for r in rows]
    assert outputs[:2] == p4_spec()["actions"]
    assert outputs[2] == {"action": "read", "arguments": {"resource": "records"}}
    assert outputs[3]["action"] == "finish"
    assert read(tmp_path / "reference/final-world.json")["version"] == 2
    assert len(read(tmp_path / "reference/final-ledger.json")) == 2


class MockBatch:
    def __init__(self, root, rows, specs=None):
        self.root, self.rows, self.stopped, self.frozen = root, rows, None, {}
        self.specs = specs
        self.plan = {
            "P3": [{"id": r["episode"]} for r in rows],
            "http_identity": {
                "endpoint": ENDPOINT,
                "model": MODEL,
                "context": 65536,
                "version": "0.27.1",
            },
        }

    def authorize(self, stage):
        assert stage in {"P3", "P4"}

    def artifact(self, name):
        return {
            "P1_final_selection": {"status": "STRING_RULE_SIGNAL", "selected_condition": "D11"},
            "P2_gate": {"status": "G_P2_PASS"},
            "P_full_preparation": {"status": "REFERENCE_PREPARATION_PASS"},
            "P4_resolved_specs": {"specs": self.specs},
        }[name]

    def snapshot(self):
        return {"stop": self.stopped, "episodes": [{"stage": "P3", "status": "PENDING"}]}

    def references(self, stage):
        assert stage in {"P3", "P4"}
        return self.rows

    def stop(self, reason):
        self.stopped = reason

    def freeze_artifact(self, name, path, status):
        assert read(path)["status"] == status
        self.frozen[name] = path


def mock_preflight(tmp_path, monkeypatch, mode, stage="P3"):
    forbid_network(monkeypatch)
    root = tmp_path / "mock-full"
    root.mkdir()
    rows = []
    specs = []
    for i in range(16 if stage == "P3" else 24):
        spec = {
            "id": f"{stage.lower()}-{i + 1:02d}",
            "stage": stage,
            "actions": [put()] * (2 if i < 8 else 1),
        }
        specs.append(spec)
        schema = SessionContract.from_public(public()).action_schema(finish_only=True)
        canonical = payload([{"role": "system", "content": "synthetic complete contract"}], schema)
        for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3):
            rows.append(
                write_reference(
                    root / "references" / spec["id"],
                    spec,
                    turn,
                    canonical,
                    {"action": "finish", "arguments": {"message": "done"}},
                    "D11",
                )
            )
    batch = MockBatch(root, rows, specs)
    if mode == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    monkeypatch.setattr(preflight_module, "Batch", lambda *args: batch)
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        assert request.url.path == "/tokenize"
        body = json.loads(request.content)
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if mode == "bool":
            return httpx.Response(200, json={"count": True})
        count = 4096 if mode == "capacity" and "prompt" in body else 100
        return httpx.Response(200, json={"count": count})

    result = preflight_module.preflight(
        root, "mock-binding", stage, transport=httpx.MockTransport(handle)
    )
    return batch, result, calls


def test_complete_exact_wire_mock_capacity_freezes_every_request_and_attempt(tmp_path, monkeypatch):
    batch, result, calls = mock_preflight(tmp_path, monkeypatch, "pass")
    assert result["status"] == "G_PREFLIGHT_PASS"
    assert len(result["rows"]) == 16 and len(result["tokenize_calls"]) == 32
    assert calls.count("/tokenize") == 32 and "/v1/chat/completions" not in calls
    assert result["model_requests"] == 0 and batch.stopped is None
    assert "P3_preflight" in batch.frozen
    assert len([p for p in result["files"] if p.endswith(".attempt.json")]) == 32


@pytest.mark.parametrize("mode,attempts", [("timeout", 1), ("bool", 1), ("capacity", 2)])
def test_first_capacity_or_http_error_preserves_attempt_and_stops(
    tmp_path, monkeypatch, mode, attempts
):
    batch, result, calls = mock_preflight(tmp_path, monkeypatch, mode)
    assert result["status"] == "NOT_MET" and batch.stopped is not None
    assert len(result["tokenize_calls"]) == attempts
    assert calls.count("/tokenize") == attempts and batch.frozen == {}
    assert any(p.endswith(".attempt.json") for p in result["files"])
    if mode == "timeout":
        assert any(p.endswith(".error.json") for p in result["files"])


def test_reference_raw_hash_drift_fails_before_capacity(tmp_path):
    spec = {"id": "synthetic", "stage": "P3"}
    canonical = payload([], SessionContract.from_public(public()).action_schema(finish_only=True))
    row = write_reference(
        tmp_path, spec, 1, canonical, {"action": "finish", "arguments": {"message": "done"}}, "D11"
    )
    Path(row["output"]).write_text('{"raw":"corrupted"}')
    with pytest.raises(ProviderStop, match="FROZEN_REFERENCE_DRIFT"):
        preflight_module.validate_reference(row, "D11")


def test_all_p4_reference_capacity_can_precede_p3_model_launch(tmp_path, monkeypatch):
    batch, result, calls = mock_preflight(tmp_path, monkeypatch, "pass", stage="P4")
    assert result["status"] == "G_PREFLIGHT_PASS"
    assert len(result["rows"]) == 80 and calls.count("/tokenize") == 160
    assert batch.snapshot()["episodes"][0]["status"] == "PENDING"
    assert result["model_requests"] == 0 and "P4_preflight" in batch.frozen


def test_reference_position_reordering_rejected_before_http(tmp_path, monkeypatch):
    with pytest.raises(ProviderStop, match="POSITION_OR_ORDER_DRIFT"):
        mock_preflight(tmp_path, monkeypatch, "reorder")
