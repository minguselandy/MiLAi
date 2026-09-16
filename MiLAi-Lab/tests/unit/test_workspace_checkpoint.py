"""Public adapter contract, including CAS races and lost acknowledgement handling."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from workspace_checkpoint import CheckpointError, WorkingStateCheckpoint

BINDING = {
    "principal_binding_digest": "a" * 64,
    "project_id": "project",
    "scope_type": "TASK",
    "scope_ref": "task",
}


class Rejected(RuntimeError):
    code = "STALE_WORKING_STATE"


class PublicClient:
    def __init__(self):
        self.head = {
            "status": "ABSENT",
            "authority": "HOST_WORKING",
            "scope": "TASK",
            "state_id": None,
            "version": 0,
            "payload": {},
            "warnings": [],
            "payload_withheld": False,
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        self.writes = []
        self.mode = None

    def get_working_state(self, binding):
        assert binding == BINDING
        return copy.deepcopy(self.head)

    def update_working_state(self, payload, *, operation_id):
        self.writes.append((copy.deepcopy(payload), operation_id))
        if self.mode == "race":
            raise Rejected("changed head")
        if self.mode == "unknown_before_commit":
            raise TimeoutError("unknown send outcome")
        assert payload["expected_version"] == self.head["version"]
        self.head.update(
            status="ACTIVE",
            state_id="state",
            version=self.head["version"] + 1,
            payload=copy.deepcopy(payload["payload"]),
        )
        if self.mode == "lost_ack":
            raise TimeoutError("committed but acknowledgement lost")
        return copy.deepcopy(self.head)


def port(tmp_path, client=None, **kwargs):
    client = client or PublicClient()
    return WorkingStateCheckpoint(
        client, binding=BINDING, journal=tmp_path / "pending.json", **kwargs
    ), client


def test_public_archive_preserves_bytes_other_namespace_and_declared_dependencies(tmp_path):
    p, client = port(tmp_path, evidence_refs=["00000000-0000-0000-0000-000000000001"])
    client.head["payload"] = {"other_host": {"text": "Keep whitespace \n", "version": 7}}
    artifact = {"receipts": {"H001": "原始字节\r\n  code  " * 20000}, "pending": [1]}
    saved = p.save(artifact, operation_id="save-1")
    assert saved["payload"]["other_host"] == client.head["payload"]["other_host"]
    assert saved["payload"]["milai_rwc"]["evidence_refs"] == p.evidence_refs
    fresh = WorkingStateCheckpoint(client, binding=BINDING, journal=tmp_path / "fresh.json")
    assert fresh.load() == artifact
    assert len(client.writes) == 1


@pytest.mark.parametrize("damage", ["withheld", "warning", "expired", "status", "authority"])
def test_unreadable_or_expired_head_is_never_overwritten_as_empty(tmp_path, damage):
    p, client = port(tmp_path)
    p.save({"record": "private"}, operation_id="seed")
    if damage == "withheld":
        client.head.update(payload={}, payload_withheld=True)
    elif damage == "warning":
        client.head["warnings"] = [{"code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE"}]
    elif damage == "expired":
        client.head["expires_at"] = "2000-01-01T00:00:00+00:00"
    elif damage == "status":
        client.head["status"] = "EXPIRED"
    else:
        client.head["authority"] = "CANONICAL"
    with pytest.raises(CheckpointError):
        p.load()
    with pytest.raises(CheckpointError):
        p.save({"record": "new"}, operation_id="forbidden")
    assert len(client.writes) == 1


def test_cas_conflict_is_not_merged_or_retried(tmp_path):
    p, client = port(tmp_path)
    client.mode = "race"
    with pytest.raises(Rejected):
        p.save({"record": "mine"}, operation_id="once")
    assert len(client.writes) == 1
    assert json.loads(p.journal.read_text())["status"] == "REJECTED"


@pytest.mark.parametrize("mode", ["lost_ack", "unknown_before_commit"])
def test_unknown_update_survives_new_adapter_and_only_matching_head_settles(tmp_path, mode):
    p, client = port(tmp_path)
    client.mode = mode
    with pytest.raises(TimeoutError):
        p.save({"unmaintained_observation": "real result"}, operation_id="uncertain")
    fresh, _ = port(tmp_path, client)
    with pytest.raises(CheckpointError, match="RECONCILIATION"):
        fresh.save({"record": "do not retry"}, operation_id="replacement")
    if mode == "lost_ack":
        assert fresh.reconcile()["status"] == "COMMITTED_VISIBLE_HEAD"
        assert fresh.load() == {"unmaintained_observation": "real result"}
    else:
        with pytest.raises(CheckpointError, match="STILL_UNKNOWN"):
            fresh.reconcile()
    assert len(client.writes) == 1


@pytest.mark.parametrize("damage", ["digest", "size", "encoding", "bytes"])
def test_corrupt_archive_is_not_restored(tmp_path, damage):
    p, client = port(tmp_path)
    p.save({"record": "faithful"}, operation_id="seed")
    archive = client.head["payload"]["milai_rwc"]
    key, value = {
        "digest": ("sha256", "wrong"),
        "size": ("raw_bytes", 10**10),
        "encoding": ("encoding", "unsafe"),
        "bytes": ("archive", "%%%%"),
    }[damage]
    archive[key] = value
    with pytest.raises(ValueError):
        p.load()


def test_oversized_other_namespace_is_preserved_and_blocks_send(tmp_path):
    p, client = port(tmp_path)
    client.head["payload"] = {"other_host": "x" * 65536}
    with pytest.raises(CheckpointError, match="CAPACITY"):
        p.save({"small": "workspace"}, operation_id="oversized")
    assert not client.writes and not p.journal.exists()


def test_followup_save_preserves_declared_dependencies_when_caller_omits_them(tmp_path):
    p, client = port(tmp_path, evidence_refs=["dependency"])
    p.save({"record": "derived"}, operation_id="first")
    fresh = WorkingStateCheckpoint(client, binding=BINDING, journal=tmp_path / "new.json")
    fresh.save(fresh.load(), operation_id="second")
    assert client.head["payload"]["milai_rwc"]["evidence_refs"] == ["dependency"]


def test_settled_journal_cannot_be_reused_with_another_binding(tmp_path):
    p, client = port(tmp_path)
    p.save({"record": "bound"}, operation_id="first")
    wrong = WorkingStateCheckpoint(
        client, binding={**BINDING, "scope_ref": "foreign"}, journal=p.journal
    )
    with pytest.raises(CheckpointError, match="JOURNAL_BINDING_MISMATCH"):
        wrong.load()
    assert len(client.writes) == 1
