"""Offline new reference layers from the original full 96-request trajectory set."""

import copy
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0220_action_adapter import public, put

from prepare_v0221_http_v2 import W2_SYSTEM
from v0213_provider import payload
from v0218_world import World
from v0220_evidence import read, sha
from v0220_provider_hardened import ProviderStop
from v0220_session import Session
from v0220_wire_contract import encoded
from v0222_presentation_references import (
    KINDS,
    prepare_p3,
    prepare_p4,
    validate_reference,
    write_reference,
)

PARENT = Path("/cra/memory/mx_memory/evidence/v0222/20260911-http-r1")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("PRESENTATION_REFERENCE_TEST_CANNOT_USE_HTTP")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def source_rows():
    return [
        row
        for stage in ("P3", "P4")
        for row in read(PARENT / "full-reference" / (stage + "-reference-index.json"))
    ]


def materialize(tmp_path, source):
    canonical = read(Path(source["canonical"]))
    output = json.loads(read(Path(source["output"]))["raw"])
    spec = {"id": source["episode"], "stage": source["stage"]}
    return write_reference(tmp_path, spec, source["turn"], canonical, output)


def test_all_96_complete_original_reference_layers(tmp_path):
    sources = source_rows()
    assert len(sources) == 96
    seen = []
    for source in sources:
        for kind in ("canonical", "wire", "output"):
            assert sha(Path(source[kind])) == source["hashes"][kind]
        row = materialize(tmp_path / source["stage"] / source["episode"], source)
        original, presented, wire, raw = validate_reference(row)
        assert Path(row["canonical"]).read_bytes() == Path(source["canonical"]).read_bytes()
        assert raw == read(Path(source["output"]))["raw"]
        assert (
            original["response_format"]
            == presented["response_format"]
            == read(Path(source["canonical"]))["response_format"]
        )
        assert row["schema_pair"] == source["schema_pair"]
        assert wire["response_format"] == read(Path(source["wire"]))["response_format"]
        assert wire["messages"][0] == read(Path(source["wire"]))["messages"][0]
        assert len(presented["messages"]) == len(original["messages"]) + 1
        assert set(row["hashes"]) == set(KINDS)
        seen.append((row["stage"], row["episode"], row["turn"]))
    assert len(set(seen)) == 96
    assert sum(stage == "P3" for stage, _, _ in seen) == 16
    assert sum(stage == "P4" for stage, _, _ in seen) == 80
    assert not list(tmp_path.rglob("*.sqlite"))
    assert not list(tmp_path.rglob("provider-ledger*"))


@pytest.mark.parametrize("kind", KINDS)
def test_each_layer_hash_is_required(tmp_path, kind):
    row = materialize(tmp_path, source_rows()[0])
    bad = copy.deepcopy(row)
    bad["hashes"][kind] = "0" * 64
    with pytest.raises(ProviderStop, match="REFERENCE_HASH_DRIFT"):
        validate_reference(bad)


@pytest.mark.parametrize("change", ("wire", "diff", "compiler", "missing_layer", "candidate"))
def test_rehashed_or_metadata_tampering_cannot_pass(tmp_path, change):
    row = materialize(tmp_path, source_rows()[0])
    if change in {"wire", "diff"}:
        kind = "wire" if change == "wire" else "presentation_diff"
        value = read(Path(row[kind]))
        if change == "wire":
            value["messages"][-1]["content"] += "extra instruction"
        else:
            value["unreviewed_added_field"] = True
        # Test-only new file; never overwrite the original frozen source.
        path = tmp_path / "TEST_ONLY_tampered.json"
        path.write_text(encoded(value))
        row[kind] = str(path)
        row["hashes"][kind] = sha(path)
    elif change == "compiler":
        row["schema_pair"]["unreviewed_added_field"] = True
    elif change == "missing_layer":
        del row["hashes"]["presented"]
    else:
        row["selected_condition"] = "B0"
    with pytest.raises(ProviderStop):
        validate_reference(row)


def test_reference_is_append_only(tmp_path):
    source = source_rows()[0]
    materialize(tmp_path, source)
    with pytest.raises(FileExistsError):
        materialize(tmp_path, source)


def test_fresh_session_unsorted_envelopes_survive_disk_roundtrip(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "TEST_ONLY_fresh", public())
    host = Session(
        world,
        tmp_path / "session",
        episode_id="TEST_ONLY_full",
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent={"authorized_action": put()},
        validate_binding=lambda: None,
    )
    messages = copy.deepcopy(host.messages)
    messages[0] = {"role": "system", "content": W2_SYSTEM}
    assert list(messages[0]) == ["role", "content"]
    canonical = payload(messages, host.contract.action_schema())
    before = copy.deepcopy(canonical)
    row = write_reference(
        tmp_path / "references",
        {"stage": "P3", "id": "TEST_ONLY_full"},
        1,
        canonical,
        put(),
    )
    original, presented, _, _ = validate_reference(row)
    assert canonical == before
    assert original == canonical
    assert list(original["messages"][0]) == ["content", "role"]
    assert len(presented["messages"]) == 3
    assert not world.snapshot()["records"]


@pytest.mark.parametrize("variant", ("full", "finish"))
def test_fresh_complete_calibration_preserves_original_contract(tmp_path, variant):
    expected = (
        put() if variant == "full" else {"action": "finish", "arguments": {"message": "done"}}
    )
    spec = {
        "id": "TEST_ONLY_p3",
        "stage": "P3",
        "scope": "TEST_ONLY_p3_scope",
        "variant": variant,
        "expected": expected,
    }
    rows = prepare_p3(tmp_path / "reference", spec, public(), lambda: None)
    assert len(rows) == 1
    original, presented, wire, raw = validate_reference(rows[0])
    assert json.loads(raw) == expected
    assert json.loads(original["messages"][1]["content"])["authorized_intent"] == {
        "authorized_action": expected
    }
    assert json.loads(presented["messages"][-1]["content"]) == {
        "authorized_intent": {"authorized_action": expected}
    }
    assert len(wire["messages"]) == 3
    assert read(tmp_path / "reference/reference-validation.json")["legal_targets"] == [
        "left",
        "right",
    ]


@pytest.mark.parametrize("writes", (1, 2))
def test_fresh_session_chain_whole_intent_history_readback_and_effects(tmp_path, writes):
    actions = [put(), put("right", 1)][:writes]
    spec = {
        "id": "TEST_ONLY_p4",
        "stage": "P4",
        "scope": "TEST_ONLY_p4_scope",
        "actions": actions,
        "intent": {
            "instruction": "Perform the authorized complete writes in order, read records, finish.",
            "ordered_writes": [
                {"object_id": a["arguments"]["object_id"], "data": a["arguments"]["data"]}
                for a in actions
            ],
        },
        "initial_state_sha256": "TEST_ONLY_old_scope_digest",
    }
    before = copy.deepcopy(spec)
    rows, resolved = prepare_p4(tmp_path / "reference", spec, public(), lambda: None)
    assert spec == before
    assert len(rows) == writes + 2
    assert resolved["spec"]["intent"] == before["intent"]
    assert resolved["spec"]["actions"] == before["actions"]
    assert resolved["derived_hash_diff"]["scope_unchanged"] is True
    assert read(tmp_path / "reference/independent-effects.json")["status"] == "PASS"
    assert read(tmp_path / "reference/final-world.json")["version"] == writes
    assert len(read(tmp_path / "reference/final-ledger.json")) == writes
    previous_history = None
    for row in rows:
        original, presented, _, _ = validate_reference(row)
        assert json.loads(presented["messages"][-1]["content"]) == {
            "authorized_intent": before["intent"]
        }
        assert original["messages"][2:] == presented["messages"][2:-1]
        assert "authorized_intent" not in json.loads(presented["messages"][1]["content"])
        if previous_history is not None:
            assert original["messages"][: len(previous_history)] == previous_history
        # Original Session history excludes its transient final budget user.
        previous_history = original["messages"][:-1]
    last_original = validate_reference(rows[-1])[0]
    branches = last_original["response_format"]["json_schema"]["schema"]["anyOf"]
    assert len(branches) == 1 if writes == 2 else len(branches) > 1


@pytest.mark.parametrize("stage,turn", (("R1", 1), ("P3", 0), ("P4", True)))
def test_stage_and_turn_must_be_explicit(tmp_path, stage, turn):
    with pytest.raises(ProviderStop, match="STAGE_OR_TURN_INVALID"):
        write_reference(tmp_path, {"stage": stage, "id": "test"}, turn, {}, {})
