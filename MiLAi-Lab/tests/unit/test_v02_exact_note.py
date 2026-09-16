from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
note = importlib.import_module("v02_exact_note")
REF = "11111111-1111-4111-8111-111111111111"


def head() -> dict:
    return {"schema_version": "host-cognitive-state-v1", "status": "ABSENT",
            "state_id": None, "version": 0, "authority": "HOST_WORKING", "scope": "TASK",
            "payload": {}, "warnings": []}


def test_exact_utf8_payload_preserves_old_fields_and_refs(tmp_path: Path) -> None:
    raw = ('  报价 "quoted"\r\n' + REF + '\n\n').encode()
    (tmp_path / "note.md").write_bytes(raw)
    before = head()
    before.update(status="ACTIVE", state_id=str(uuid4()), version=3,
                  payload={"other": {"evidence_refs": [str(uuid4())], "value": "keep"}})
    saved = copy.deepcopy(before)
    status, payload, managed = note.build_payload(tmp_path, "note.md", before, [REF])
    assert status == "WRITE" and managed["text"].encode() == raw
    assert payload["other"] == before["payload"]["other"]
    assert before == saved
    before["payload"] = payload
    assert note.build_payload(tmp_path, "note.md", before, [REF])[0] == "NO_OP"


def test_natural_save_noop(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("Already\nfinished")
    before = head()
    before.update(status="ACTIVE", state_id=str(uuid4()), version=1,
                  payload={"note": "Already\nfinished", "evidence_refs": [REF]})
    assert note.build_payload(tmp_path, "note.md", before, [REF])[0] == "NO_OP_NATURAL_SAVE"


@pytest.mark.parametrize("kind", ["long", "utf8long", "escape", "symlink", "parentlink",
                                  "unknownfield", "unknownref", "norefs", "bootstrap"])
def test_rejection_does_not_truncate_or_write(tmp_path: Path, kind: str) -> None:
    (tmp_path / "note.md").write_text("text")
    before, path, refs = head(), "note.md", [REF]
    if kind == "long":
        (tmp_path / path).write_bytes(b"a" * 4097)
    elif kind == "utf8long":
        (tmp_path / path).write_text("中" * 1366)
    elif kind == "escape":
        path = "../note.md"
    elif kind == "symlink":
        (tmp_path / "link").symlink_to(tmp_path / "note.md")
        path = "link"
    elif kind == "parentlink":
        (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
        path = "link/note.md"
    elif kind == "unknownfield":
        before.update(status="ACTIVE", state_id=str(uuid4()), version=1,
                      payload={note.FIELD: {"owner": "someone-else"}})
    elif kind == "unknownref":
        (tmp_path / path).write_text(str(uuid4()))
    elif kind == "norefs":
        refs = []
    else:
        before.update(status="ACTIVE", state_id=str(uuid4()), version=1,
                      payload={"other": "中" * 4100})
    with pytest.raises(ValueError):
        note.build_payload(tmp_path, path, before, refs)


@pytest.mark.parametrize("status", ["EXPIRED", "TRUNCATED", "DELETED", "ACTIVE"])
def test_incomplete_or_inactive_head_is_not_empty_merge(status: str) -> None:
    before = head()
    before["status"] = status
    with pytest.raises(ValueError):
        note.validate_head(before)


@pytest.mark.parametrize("failure", [None, "STALE_WORKING_STATE", "OPERATION_CONFLICT",
                                     "EVIDENCE_REFERENCE_INVALID", "UNKNOWN", "LOST_REPLY"])
def test_cas_one_write_and_confirmation(tmp_path: Path, failure: str | None) -> None:
    (tmp_path / "note.md").write_text("note")
    state = head()
    state.update(status="ACTIVE", state_id=str(uuid4()), version=4,
                 payload={"other": {"evidence_refs": [REF]}})
    calls = []

    def call(tool: str, args: dict) -> dict:
        calls.append(tool)
        if tool.endswith("get"):
            return copy.deepcopy(state)
        assert args["expected_version"] == 4 and args["state_id"] == state["state_id"]
        assert args["operation_id"] == "stable-op"
        if failure not in (None, "LOST_REPLY"):
            return {"mcp_error": True, "code": failure}
        state.update(version=5, payload=args["payload"])
        if failure == "LOST_REPLY":
            raise TimeoutError()
        return copy.deepcopy(state)

    result = note.checkpoint(call, tmp_path, "note.md", [REF], "stable-op")
    assert calls == ["milai_working_state_get", "milai_working_state_update",
                     "milai_working_state_get"]
    assert result["model_tokens"] == 0 and result["delta_save_seconds"] > 0
    if failure is None:
        assert result["status"] == "SAVED_CONFIRMED"
        again = note.checkpoint(call, tmp_path, "note.md", [REF], "stable-op")
        assert again["status"] == "NO_OP" and state["version"] == 5
    elif failure == "LOST_REPLY":
        assert result["status"] == "SAVED_OBSERVED_AFTER_UNKNOWN"
    elif failure == "UNKNOWN":
        assert result["status"] == "UNCONFIRMED"
    else:
        assert result["status"] == "REJECTED_" + failure
