"""Synthetic mechanical actions; no benchmark gold or real-model success claims."""

import copy
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0218_world import World, WorldError
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ActionContract, ContractError
from v0220_dispatch_journal import UnresolvedDispatch


def public():
    properties = {
        "text": {"type": "string"},
        "amount": {"type": "number", "minimum": 0},
        "approved": {"type": "boolean"},
        "extra": {
            "type": ["object", "null"],
            "properties": {"items": {"type": "array", "items": {"type": "string"}}},
            "required": ["items"],
            "additionalProperties": False,
        },
    }
    schemas = {
        key: {
            "type": "object",
            "additionalProperties": False,
            "properties": {"object_id": {"const": key}, **copy.deepcopy(properties)},
            "required": ["object_id", *properties],
        }
        for key in ["left", "right"]
    }
    return {
        "task": {"record_schemas": schemas, "request": "Synthetic interface test"},
        "policy": {},
        "current": {"authorized": True},
        "objects": list(schemas),
    }


def put(target="left", version=0):
    return {
        "action": "put_record",
        "arguments": {
            "object_id": target,
            "expected_version": version,
            "data": {
                "text": '中英 "quote"\nline\\path',
                "amount": 12.5,
                "approved": False,
                "extra": {"items": ["甲", "b"]},
            },
        },
    }


@pytest.fixture
def adapter(tmp_path):
    p = public()
    return ActionAdapter(
        World.create(tmp_path / "world.sqlite", "owned", p), ActionContract.from_public(p)
    )


def test_schema_and_validator_share_public_types(adapter):
    contract = adapter.contract
    Draft202012Validator.check_schema(contract.action_schema())
    assert Draft202012Validator(contract.action_schema()).is_valid(put())
    assert contract.decode(json.dumps(put(), ensure_ascii=False)) == put()
    assert "arguments_json" not in json.dumps(contract.documents())
    assert "object_id" not in contract.write_schemas()["left"]["properties"]
    assert "object_id" in contract.read_schemas["left"]["properties"]


def test_actual_two_object_cas_replace_and_replay(adapter):
    first = adapter.execute(put(), operation_id="one")
    assert first["committed"] and first["version"] == 1
    assert adapter.execute(put(), operation_id="one") == first
    second = adapter.execute(put("right", 1), operation_id="two")
    assert second["version"] == 2
    assert adapter.operation_status("one") == first
    observed = adapter.read("records")
    assert observed["version_domain"] == "WORLD" and observed["version"] == 2
    assert observed["content"]["left"] == {"object_id": "left", **put()["arguments"]["data"]}
    replacement = put(version=2)
    replacement["arguments"]["data"]["extra"] = None
    assert adapter.execute(replacement, operation_id="three")["version"] == 3
    assert len(adapter.world.ledger()) == 3


@pytest.mark.parametrize(
    "field", ["object_id", "scope", "version", "tenant", "project", "operation_id"]
)
def test_storage_and_security_metadata_rejected_without_effect(adapter, field):
    action = put()
    action["arguments"]["data"][field] = "DO_NOT_ECHO_SENTINEL"
    before = adapter.world.snapshot()
    receipt = adapter.execute(action, operation_id="host")
    assert receipt["code"] == "READ_ONLY_FIELD" and receipt["committed"] is False
    assert "DO_NOT_ECHO_SENTINEL" not in json.dumps(receipt)
    assert adapter.world.snapshot() == before and adapter.world.ledger() == []


@pytest.mark.parametrize("version", [None, True, "0", -1, 0.0, {}, []])
def test_strict_world_version_type(adapter, version):
    receipt = adapter.execute(put(version=version), operation_id="host")
    assert receipt["code"] == "WORLD_VERSION_INTEGER_REQUIRED"
    assert adapter.world.snapshot()["version"] == 0


@pytest.mark.parametrize("target", ["foreign-scope/right", "missing", {}, [], None])
def test_unauthorized_or_malformed_target(adapter, target):
    receipt = adapter.execute(put(target), operation_id="host")
    assert receipt["code"] == "OBJECT_SCOPE_DENIED"
    assert adapter.world.ledger() == []


@pytest.mark.parametrize(
    "change",
    [
        "unknown_argument",
        "unknown_data",
        "missing",
        "wrong_type",
        "nonfinite",
        "private_key",
        "nested_unknown",
        "readonly_payload",
    ],
)
def test_public_field_rejections_no_silent_repair(adapter, change):
    action = put()
    args = action["arguments"]
    if change == "unknown_argument":
        args["scope"] = "CANARY"
    elif change == "unknown_data":
        args["data"]["CANARY"] = "CANARY"
    elif change == "missing":
        del args["data"]["text"]
    elif change == "wrong_type":
        args["data"]["amount"] = True
    elif change == "nonfinite":
        args["data"]["amount"] = float("nan")
    elif change == "private_key":
        args["data"]["gold_answer"] = "CANARY"
    elif change == "nested_unknown":
        args["data"]["extra"]["CANARY"] = "CANARY"
    else:
        args["data"]["object_id"] = "left"
    before = adapter.world.snapshot()
    receipt = adapter.execute(action, operation_id="host")
    assert receipt["committed"] is False and "CANARY" not in json.dumps(receipt)
    assert adapter.world.snapshot() == before and adapter.world.ledger() == []


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"read","action":"finish","arguments":{}}',
        '{"action":"read","arguments":{"resource":"records",',
        '{"action":"read","arguments_json":"{}"}',
    ],
)
def test_malformed_and_duplicate_json_not_repaired(adapter, raw):
    with pytest.raises(ContractError):
        adapter.contract.decode(raw)
    assert adapter.world.ledger() == []


def test_stale_version_read_revalidation_and_semantic_condition_change(adapter):
    adapter.world.publish(event_id="unrelated", current={"authorized": True, "tick": 1})
    rejected = adapter.execute(put(), operation_id="first")
    assert rejected["code"] == "VERSION_CONFLICT" and not rejected["committed"]
    assert rejected["expected_version"] == 0 and rejected["current_version"] == 1
    assert rejected["retry_requires"] == "READ_AND_REVALIDATE"
    assert adapter.read("current")["content"]["authorized"] is True
    assert adapter.execute(put(version=1), operation_id="revalidated")["committed"]
    adapter.world.publish(event_id="changed", current={"authorized": False})
    stale = adapter.execute(put("right", 2), operation_id="old-intent")
    assert stale["code"] == "VERSION_CONFLICT"
    assert not adapter.read("current")["content"]["authorized"]
    question = {
        "action": "request_clarification",
        "arguments": {
            "object_id": "right",
            "expected_version": 3,
            "data": {"question": "Authorization changed; reauthorize?"},
        },
    }
    assert adapter.execute(question, operation_id="ask")["committed"]
    assert "right" not in adapter.read("records")["content"]
    assert "right" in adapter.read("pending")["content"]


def test_clarification_does_not_cancel_prior_record(adapter):
    adapter.execute(put(), operation_id="created")
    action = {
        "action": "request_clarification",
        "arguments": {
            "object_id": "left",
            "expected_version": 1,
            "data": {"question": "Please confirm."},
        },
    }
    adapter.execute(action, operation_id="question")
    assert "left" in adapter.read("records")["content"]
    assert "left" in adapter.read("pending")["content"]
    adapter.execute(put(version=2), operation_id="replace")
    assert adapter.read("pending")["content"] == {}


def test_same_operation_different_valid_payload_rejected(adapter):
    first = adapter.execute(put(), operation_id="same")
    changed = put()
    changed["arguments"]["data"]["text"] = "different"
    before = adapter.world.snapshot()
    assert adapter.execute(changed, operation_id="same")["code"] == "OPERATION_ID_REUSE_CONFLICT"
    assert adapter.operation_status("same") == first and adapter.world.snapshot() == before


def test_lost_response_durable_query_and_exact_replay(adapter, monkeypatch):
    original = adapter.world.act

    def lost(**kwargs):
        original(**kwargs)
        raise OSError("response lost after commit")

    monkeypatch.setattr(adapter.world, "act", lost)
    unknown = adapter.execute(put(), operation_id="lost")
    assert unknown["committed"] is None and unknown["status"] == "COMMIT_UNKNOWN"
    assert unknown["stop_new_logical_writes"]
    receipt = adapter.operation_status("lost")
    assert receipt["committed"] and receipt["version"] == 1
    monkeypatch.setattr(adapter.world, "act", original)
    assert adapter.execute(put(), operation_id="lost") == receipt
    assert len(adapter.world.ledger()) == 1
    assert adapter.operation_status("absent")["committed"] is None


def test_cold_process_readback_and_clone_isolation(adapter, tmp_path):
    adapter.execute(put(), operation_id="one")
    code = (
        "import json,sys;sys.path.insert(0,sys.argv[1]);"
        "from v0218_world import World;"
        "print(json.dumps(World(__import__('pathlib').Path(sys.argv[2]),'owned').read('records')))"
    )
    child = subprocess.run(  # noqa: S603 - fixed source and test-owned paths, no shell
        [
            sys.executable,
            "-c",
            code,
            str(Path(__file__).resolve().parents[2] / "tools"),
            str(adapter.world.path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(child.stdout)["content"] == adapter.read("records")["content"]
    clone = adapter.clone(tmp_path / "clone.sqlite", "clone")
    assert clone.operation_status("one")["committed"] is None
    clone.execute(put("right", 1), operation_id="one")
    assert "right" not in adapter.read("records")["content"]
    with pytest.raises(WorldError, match="SCOPE_DENIED"):
        ActionAdapter(World(adapter.world.path, "foreign"), adapter.contract)


def test_contract_drift_fails_closed(adapter):
    with sqlite3.connect(adapter.world.path) as db:
        state = adapter.world.snapshot()
        state["task"]["record_schemas"]["left"]["properties"]["amount"]["minimum"] = 1
        db.execute("UPDATE state SET body=?", (json.dumps(state),))
    receipt = adapter.execute(put(), operation_id="one")
    assert receipt["code"] == "PUBLIC_CONTRACT_DRIFT"
    assert adapter.world.ledger() == []


def test_business_wrong_but_structurally_legal_is_not_tool_gold_routed(adapter):
    action = put()
    action["arguments"]["data"]["approved"] = True
    assert adapter.execute(action, operation_id="wrong-semantic")["committed"]
    assert adapter.read("records")["content"]["left"]["approved"] is True


def test_finish_and_note_cannot_be_business_commits(adapter):
    finish = {"action": "finish", "arguments": {"message": "DONE"}}
    assert adapter.contract.validate(finish) == finish
    assert not adapter.execute(finish, operation_id="finish")["committed"]
    note = {"action": "save_note", "arguments": {"note": "DONE"}}
    with pytest.raises(ContractError, match="ACTION_NOT_AVAILABLE"):
        adapter.contract.validate(note)
    enabled = ActionContract.from_public(public(), enable_note=True)
    assert enabled.validate(note) == note
    assert adapter.world.ledger() == []


@pytest.mark.parametrize("commit_first", [True, False])
def test_unknown_dispatch_fence_survives_adapter_restart(adapter, monkeypatch, commit_first):
    original = adapter.world.act

    def interrupted(**kwargs):
        if commit_first:
            original(**kwargs)
        raise OSError("unknown transport completion")

    monkeypatch.setattr(adapter.world, "act", interrupted)
    assert adapter.execute(put(), operation_id="uncertain")["committed"] is None
    resumed = ActionAdapter(World(adapter.world.path, "owned"), adapter.contract)
    before = resumed.world.snapshot()
    blocked = resumed.execute(put("right", before["version"]), operation_id="different")
    assert blocked["code"] == "UNRESOLVED_PRIOR_OPERATION"
    assert blocked["dispatch_performed"] is False and resumed.world.snapshot() == before
    with pytest.raises(UnresolvedDispatch, match="CANNOT_CLONE"):
        resumed.clone(adapter.world.path.parent / "unsafe-clone.sqlite", "unsafe")
    if commit_first:
        assert resumed.acknowledge_committed_operation("uncertain")["committed"]
    else:
        assert resumed.acknowledge_committed_operation("uncertain")["committed"] is None
        assert resumed.journal.unresolved() == ["uncertain"]
        assert resumed.execute(put(), operation_id="uncertain")["committed"]
    assert resumed.journal.unresolved() == []
    assert resumed.execute(put("right", 1), operation_id="different")["committed"]
    assert len(resumed.world.ledger()) == 2


def test_journal_failure_after_commit_never_reported_uncommitted(adapter, monkeypatch):
    def broken_settle(*args):
        raise ContractError("DISPATCH_RECEIPT_CONFLICT")

    monkeypatch.setattr(adapter.journal, "settle", broken_settle)
    receipt = adapter.execute(put(), operation_id="one")
    assert receipt["committed"] is None and receipt["status"] == "COMMIT_UNKNOWN"
    assert adapter.operation_status("one")["committed"] is True
    assert len(adapter.world.ledger()) == 1


def test_known_rejection_replays_without_new_business_attempt(adapter):
    adapter.world.publish(event_id="v1", current={"authorized": True})
    first = adapter.execute(put(), operation_id="stale")
    assert first["code"] == "VERSION_CONFLICT"
    assert adapter.operation_status("stale") == first
    assert adapter.execute(put(), operation_id="stale") == first
    changed = put(version=1)
    assert adapter.execute(changed, operation_id="stale")["code"] == "OPERATION_ID_REUSE_CONFLICT"
    assert adapter.execute(changed, operation_id="new-logical")["committed"]


@pytest.mark.parametrize(
    "mutation",
    [
        "false_commit",
        "note_domain",
        "unknown_field",
        "bad_hash",
        "wrong_version_type",
        "scope_target",
    ],
)
def test_typed_receipts_reject_malformed_outcomes(adapter, mutation):
    receipt = adapter.execute(put(), operation_id="one")
    if mutation == "false_commit":
        receipt["committed"] = False
    elif mutation == "note_domain":
        receipt["version_domain"] = "NOTE"
    elif mutation == "unknown_field":
        receipt["CANARY"] = "CANARY"
    elif mutation == "bad_hash":
        receipt["after_sha256"] = "success"
    elif mutation == "wrong_version_type":
        receipt["version"] = "1"
    else:
        receipt["object_id"] = "foreign"
    with pytest.raises(ContractError, match="INVALID_PUBLIC_RESPONSE"):
        adapter.contract.validate_response(receipt)


def test_public_read_model_types_and_content_hash(adapter):
    schema = adapter.contract.response_schema()
    Draft202012Validator.check_schema(schema)
    for resource in ["task", "policy", "current", "records", "pending", "history"]:
        receipt = adapter.read(resource)
        assert Draft202012Validator(schema).is_valid(receipt)
        receipt["content_sha256"] = "0" * 64
        with pytest.raises(ContractError, match="HASH_MISMATCH"):
            adapter.contract.validate_response(receipt)


def test_version_conflict_receipt_needs_actual_domains_and_reload(adapter):
    adapter.world.publish(event_id="v1", current={"authorized": True})
    receipt = adapter.execute(put(), operation_id="stale")
    assert receipt["retry_requires"] == "READ_AND_REVALIDATE"
    del receipt["current_version"]
    with pytest.raises(ContractError, match="INVALID_PUBLIC_RESPONSE"):
        adapter.contract.validate_response(receipt)


def test_type_error_explains_public_expected_type_without_instance(adapter):
    action = put()
    action["arguments"]["data"]["amount"] = "PRIVATE_LITERAL_CANARY"
    receipt = adapter.execute(action, operation_id="wrong")
    assert receipt["rule"] == 'type="number"'
    assert receipt["path"] == ["arguments", "data", "amount"]
    assert "PRIVATE_LITERAL_CANARY" not in json.dumps(receipt)
