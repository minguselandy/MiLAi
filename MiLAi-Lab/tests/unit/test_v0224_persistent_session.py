"""Synthetic Host composition only; these receipts are not Product evidence."""

import hashlib
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public
from test_v0220_session import FakeProvider, finish

from v0218_world import World
from v0224_persistent_session import PersistentSession


class SyntheticStore:
    def __init__(self, unknown=False):
        self.rows, self.unknown = [], unknown

    def validate(self):
        pass

    def write(self, content, *, operation_id):
        self.rows.append((content, operation_id))
        if self.unknown:
            raise RuntimeError("SYNTHETIC_LOST_RECEIPT")
        return {
            "status": "PERSISTENT_NOTE_COMMITTED",
            "version_domain": "NOTE",
            "committed": True,
            "business_effect": False,
            "task_outcome": "NOT_EVALUATED",
            "memory_id": str(uuid4()),
            "version": 1,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        }


@pytest.mark.parametrize("arm", ["A", "N0", "N1", "R1"])
def test_same_call_note_save_keeps_business_world_unchanged(tmp_path, arm):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    store = SyntheticStore()
    note = {"content": "Ordinary old text, not authority."} if arm in {"N1", "R1"} else None
    host = PersistentSession(
        world,
        tmp_path / "session",
        episode_id="e",
        arm=arm,
        profile="PERSISTENT_A" if arm == "A" else "PERSISTENT_B",
        note_store=store,
        inherited_note=note,
        validate_binding=lambda: None,
    )
    before = world.snapshot()
    provider = FakeProvider(
        [
            {
                "action": "save_note",
                "arguments": {"note": "Own exact ordinary text."},
                "review": "",
            },
            {**finish(), "review": ""},
        ]
    )
    result = host.run(provider, deadline=time.monotonic() + 30)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert result["note_writes"] == 1 and len(provider.requests) == 2
    assert store.rows == [("Own exact ordinary text.", "e:01")]
    assert world.snapshot() == before and world.ledger() == []
    assert host.rows[0]["response"]["version_domain"] == "NOTE"
    assert host.last_observation["version"] == 0


def test_note_unknown_stops_without_reissuing_write_or_finishing(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    store = SyntheticStore(unknown=True)
    host = PersistentSession(
        world,
        tmp_path / "session",
        episode_id="e",
        arm="A",
        profile="PERSISTENT_A",
        note_store=store,
        validate_binding=lambda: None,
    )
    provider = FakeProvider(
        [
            {"action": "save_note", "arguments": {"note": "Exact text."}, "review": ""},
            {**finish(), "review": ""},
        ]
    )
    result = host.run(provider, deadline=time.monotonic() + 30)
    assert result["status"] == "FAIL_CLOSED"
    assert len(provider.requests) == len(store.rows) == 1
    assert not host.finished and world.ledger() == []


def test_n0_cannot_receive_treatment_note(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "owned", public())
    with pytest.raises(ValueError, match="TREATMENT"):
        PersistentSession(
            world,
            tmp_path / "session",
            episode_id="e",
            arm="N0",
            profile="PERSISTENT_B",
            note_store=SyntheticStore(),
            inherited_note={"content": "not for N0"},
            validate_binding=lambda: None,
        )
    assert not (tmp_path / "session").exists()
