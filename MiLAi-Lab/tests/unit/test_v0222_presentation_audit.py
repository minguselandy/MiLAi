"""Independent reconstruction against fresh original Session and Mock HTTP.

FixtureBatch is deliberately not an authorization or frozen production instance.
"""

import copy
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_presentation_provider import (
    FINISH,
    READBACK,
    FixtureBatch,
    environment,
    provider_for,
)

import v0222_presentation_audit as audit
import v0222_presentation_transport as transport_module
from v0218_world import World
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_session import Session
from v0220_wire_contract import encoded
from v0222_presentation_references import prepare_p3, prepare_p4


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("INDEPENDENT_AUDIT_TEST_MUST_NOT_USE_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(
        transport_module, "historical_usage_presentation", lambda _: {"sources": []}
    )


def prepared(tmp_path, monkeypatch, stage="P4", *, variant="full", writes=2):
    batch = FixtureBatch(tmp_path / "batch", stage, variant=variant, writes=writes)
    source = tmp_path / "cases" / batch.value["root"] / "public-initial.json"
    save(source, environment())
    monkeypatch.setattr(audit, "CASES", tmp_path / "cases")
    directory = batch.root / "full-reference" / stage / batch.episode
    if stage == "P3":
        batch.refs = prepare_p3(directory, batch.value, environment(), lambda: None)
    else:
        batch.refs, resolution = prepare_p4(directory, batch.value, environment(), lambda: None)
        batch.value = resolution["spec"]
    batch.plan[stage] = [copy.deepcopy(batch.value)]
    return batch, directory


@pytest.mark.parametrize(
    "stage,variant,writes",
    [("P3", "full", 1), ("P3", "finish", 1), ("P4", "full", 1), ("P4", "full", 2)],
)
def test_reference_rebuilt_from_source_and_actual_offline_sql(
    tmp_path, monkeypatch, stage, variant, writes
):
    batch, directory = prepared(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    before = sha(directory / "world.sqlite")
    for reference in batch.refs:
        original, _, _, raw = audit.validate_reference(batch, reference, batch.value)
        assert original == read(Path(reference["canonical"]))
        assert json.loads(raw)
    assert sha(directory / "world.sqlite") == before


@pytest.mark.parametrize("change", ["source", "intent", "raw", "position", "sql_receipt"])
def test_reference_self_consistency_does_not_replace_source_authority(
    tmp_path, monkeypatch, change
):
    batch, directory = prepared(tmp_path, monkeypatch)
    reference = copy.deepcopy(batch.refs[0])
    if change == "source":
        source = audit.CASES / batch.value["root"] / "public-initial.json"
        value = read(source)
        value["current"]["unapproved_source"] = "not in frozen request"
        source.write_text(encoded(value))
    elif change == "intent":
        batch.value["intent"]["ordered_writes"][0]["object_id"] = "right"
    elif change == "raw":
        path = directory / "session" / "turn-01.json"
        value = read(path)
        value["raw"] = encoded(FINISH)
        path.write_text(encoded(value))
    elif change == "position":
        reference["episode"] = "different-authority"
    else:
        with sqlite3.connect(directory / "world.sqlite") as db:
            db.execute("UPDATE v0220_dispatch SET receipt=NULL")
    with pytest.raises(ProviderStop):
        audit.validate_reference(batch, reference, batch.value)


def execute_mock(batch, *, legal_finish=False, outputs=None):
    directory = batch.root / "episodes" / batch.episode
    if batch.value["stage"] == "P3":
        output = FINISH if legal_finish else batch.value["expected"]
        provider = provider_for(batch, None, [output], [])
        provider.verify()
        raw = provider.generate(batch.episode, read(Path(batch.refs[0]["canonical"])))
        provider.close()
        result = {"status": "VALIDATE_ONLY_PASS", "raw": raw, "business_dispatches": 0}
    else:
        world = World.create(
            batch.root / "worlds" / (batch.episode + ".sqlite"), batch.value["scope"], environment()
        )
        host = Session(
            world,
            directory,
            episode_id=batch.episode,
            profile="INTENT_ORACLE",
            arm="ORACLE",
            intent=batch.value["intent"],
            validate_binding=lambda: None,
        )
        save(directory / "initial-world.json", world.snapshot())
        provider = provider_for(
            batch, world, outputs or [*batch.value["actions"], READBACK, FINISH], []
        )
        result = host.run(provider, deadline=provider.provider.deadline)
        save(directory / "final-world.json", world.snapshot())
        save(directory / "final-ledger.json", world.ledger())
        result["unresolved_operations"] = host.adapter.journal.unresolved()
    save(directory / "worker-result.json", {**result, "pid": os.getpid()})
    return directory


@pytest.mark.parametrize(
    "stage,variant,writes",
    [("P3", "full", 1), ("P3", "finish", 1), ("P4", "full", 1), ("P4", "full", 2)],
)
def test_mock_http_original_session_independent_audit(
    tmp_path, monkeypatch, stage, variant, writes
):
    batch, _ = prepared(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    execute_mock(batch, legal_finish=variant == "finish")
    result = audit.audit_episode(batch, batch.episode)
    assert result["status"] == "PASS", result["checks"]
    assert result["cost"]["known_raw_tokens"] == 120 * (1 if stage == "P3" else writes + 2)
    assert result["files"]


@pytest.mark.parametrize(
    "change",
    [
        "http_hash",
        "visible",
        "binding",
        "tokenize_float",
        "final_snapshot",
        "sql_receipt",
        "turn_raw",
    ],
)
def test_runtime_audit_rejects_self_reported_pass_after_raw_or_sql_drift(
    tmp_path, monkeypatch, change
):
    batch, _ = prepared(tmp_path, monkeypatch, writes=1)
    directory = execute_mock(batch)
    provider = directory / "provider"
    if change == "sql_receipt":
        with sqlite3.connect(batch.root / "worlds" / (batch.episode + ".sqlite")) as db:
            db.execute("UPDATE v0220_dispatch SET receipt=NULL")
    else:
        if change == "http_hash":
            path = next(p for p in provider.glob("*-http.json") if "tokenize" not in p.name)
            value = read(path)
            value["request_wire_sha256"] = "0" * 64
        elif change == "visible":
            path = next(provider.glob("*-visible.json"))
            value = read(path)
            value["content"] = encoded(FINISH)
        elif change == "binding":
            path = next(provider.glob("contract-*-binding.json"))
            value = read(path)
            value["original_request_sha256"] = "0" * 64
        elif change == "tokenize_float":
            path = next(provider.glob("*-tokenize-http.json"))
            value = read(path)
            value["body"] = '{"count":100.0}'
        elif change == "final_snapshot":
            path = directory / "final-world.json"
            value = read(path)
            value["version"] += 1
        else:
            path = directory / "turn-01.json"
            value = read(path)
            value["raw"] = encoded(FINISH)
        path.write_text(encoded(value))
    try:
        result = audit.audit_episode(batch, batch.episode)
    except ProviderStop:
        return
    assert result["status"] == "FAIL", result


@pytest.mark.parametrize(
    "change", ["orphan_http", "saved_float", "reservation_cap", "lineage", "validation"]
)
def test_independent_review_accounting_counterexamples(tmp_path, monkeypatch, change):
    batch, _ = prepared(tmp_path, monkeypatch, "P3")
    directory = execute_mock(batch)
    provider = directory / "provider"
    if change == "orphan_http":
        path = next(p for p in provider.glob("*-http.json") if "tokenize" not in p.name)
        save(provider / "ORPHAN-http.json", read(path))
    elif change == "reservation_cap":
        path = provider / "provider-ledger-v2.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        for event in events:
            if event["event"] == "RESERVED":
                event.update(output_cap=100, raw_upper_bound=200, cumulative_raw_cap=123456)
        path.write_text("".join(encoded(e) + "\n" for e in events))
    else:
        pattern = {
            "saved_float": "*-tokenize.json",
            "lineage": "*-lineage.json",
            "validation": "contract-*-validation.json",
        }[change]
        path = next(provider.glob(pattern))
        value = read(path)
        if change == "saved_float":
            value["count"] = 100.0
        elif change == "lineage":
            value["sources"] = ["UNAUTHORIZED_HISTORY"]
        else:
            value["released_to_host"] = False
        path.write_text(encoded(value))
    with pytest.raises(ProviderStop):
        audit.audit_episode(batch, batch.episode)


@pytest.mark.parametrize("extra", ["read", "operation_status"])
def test_actual_fourth_turn_is_allowed_when_reference_path_has_three(tmp_path, monkeypatch, extra):
    batch, _ = prepared(tmp_path, monkeypatch, writes=1)
    intermediate = (
        {"action": "read", "arguments": {"resource": "policy"}}
        if extra == "read"
        else {"action": "operation_status", "arguments": {"operation_id": batch.episode + ":01"}}
    )
    execute_mock(batch, outputs=[*batch.value["actions"], intermediate, READBACK, FINISH])
    assert len(batch.refs) == 3
    result = audit.audit_episode(batch, batch.episode)
    assert result["status"] == "PASS", result["checks"]
    assert result["cost"]["requests"] == 4


@pytest.mark.parametrize(
    "change", ["read_content", "finish_response", "before_hash", "dispatch_attempted"]
)
def test_every_public_reply_is_rebuilt_from_real_committed_prefix(tmp_path, monkeypatch, change):
    batch, _ = prepared(tmp_path, monkeypatch, writes=1)
    directory = execute_mock(batch)
    turns = [read(p) for p in sorted(directory.glob("turn-*.json"))]
    initial, ledger = read(directory / "initial-world.json"), read(directory / "final-ledger.json")
    assert audit.public_trajectory(initial, ledger, turns)
    if change == "read_content":
        turns[1]["response"]["content"] = {}
    elif change == "finish_response":
        turns[-1]["response"]["task_outcome"] = "UNSUPPORTED_TASK_PASS"
    elif change == "before_hash":
        turns[0]["before_sha256"] = "0" * 64
    else:
        turns[0]["dispatch_attempted"] = False
    assert not audit.public_trajectory(initial, ledger, turns)


@pytest.mark.parametrize("bad_turn", [True, 1.0])
def test_turn_protocol_requires_strict_integer(tmp_path, monkeypatch, bad_turn):
    batch, _ = prepared(tmp_path, monkeypatch, writes=1)
    directory = execute_mock(batch)
    path = directory / "turn-01.json"
    value = read(path)
    value["turn"] = bad_turn
    path.write_text(encoded(value))
    with pytest.raises(ProviderStop, match="EXACT_CONTIGUOUS_SESSION_TURNS_REQUIRED"):
        audit.audit_episode(batch, batch.episode)
