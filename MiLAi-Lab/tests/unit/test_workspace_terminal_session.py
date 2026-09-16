"""Native wiring semantics with deterministic mock generation; no model claims."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from milai_lab.methods.workspace_policy import WorkspaceError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from workspace_policy_host import Generation
from workspace_terminal_session import VIEW_CHARS, TerminalSession


class Counts:
    text = staticmethod(len)

    @staticmethod
    def messages(messages):
        return sum(len(m.content) + 8 for m in messages)


def make_session(tmp_path, terminal=None):
    return TerminalSession(instruction="task", policy="ordinary note", binding="test",
                           root=tmp_path, counts=Counts(), context=65536,
                           terminal=terminal or (lambda command, timeout: {"stdout": command}))


def test_failed_terminal_time_is_counted_without_publishing_completion(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(sys.modules["workspace_terminal_session"], "time",
                        SimpleNamespace(monotonic=lambda: clock[0]))

    def terminal(*_):
        clock[0] = 60.0
        raise RuntimeError("Command timed out")

    session = make_session(tmp_path, terminal)
    with pytest.raises(RuntimeError, match="timed out"):
        session.dispatch({"action": "exec", "arguments": {"command": "owned action"}})
    assert session.tool_seconds == 60.0
    assert not session.raw_receipts


def step(session, name, args, update=None):
    return session.host.step(new=(), dispatch=session.dispatch, generate=lambda request: Generation(
        json.dumps({"action": name, "arguments": args, "work_update": update}), "MOCK", True))


def test_note_and_explicit_selection_change_next_input_and_readback(tmp_path):
    session = make_session(tmp_path)
    step(session, "exec", {"command": "UNIQUE_FIRST_BODY", "timeout_sec": 10})
    step(session, "exec", {"command": "UNIQUE_SECOND_BODY", "timeout_sec": 10})
    step(session, "context", {"mode": "MANAGED_WORKSET", "recent_exchanges": 1},
         {"text": "a" * 600, "focus_refs": ["H001"]})
    step(session, "read", {"ref": "H002", "start": 0, "length": 16000})
    row = session.host.rows[-1]
    request = json.dumps(row["request"])
    assert "a" * 600 in request  # No old 512-token rejection.
    assert "UNIQUE_FIRST_BODY" in request
    assert "UNIQUE_SECOND_BODY" not in request
    assert "UNIQUE_SECOND_BODY" in json.dumps(row["result"])
    assert row["expanded"] == ("H001",)
    step(session, "context", {"mode": "COMMON_CONTEXT", "recent_exchanges": 1})
    step(session, "final", {"text": "done"})
    assert "UNIQUE_FIRST_BODY" in json.dumps(session.host.rows[-1]["request"])
    assert "UNIQUE_SECOND_BODY" in json.dumps(session.host.rows[-1]["request"])


def test_optional_bad_note_never_replays_successful_command(tmp_path):
    effects = []

    def terminal(command, timeout):
        effects.append(command)
        return {"stdout": "changed"}

    session = make_session(tmp_path, terminal)
    step(session, "exec", {"command": "one_effect", "timeout_sec": 10},
         {"text": "bad reference", "focus_refs": ["MISSING"]})
    assert effects == ["one_effect"]
    assert session.host.rows[-1]["dispatch_attempts"] == 1
    assert session.host.workspace.text == ""


def test_optional_timeout_executes_once_and_returns_native_receipt(tmp_path):
    effects = []

    def terminal(command, timeout):
        effects.append((command, timeout))
        return {"stdout": "Python 3.13", "return_code": 0}

    session = make_session(tmp_path, terminal)
    step(session, "exec", {"command": "python3 --version"})
    step(session, "final", {"text": "received"})
    assert effects == [("python3 --version", 30)]
    assert "Python 3.13" in json.dumps(session.host.rows[-1]["request"])


def test_large_receipt_has_exact_readback_and_default_history(tmp_path):
    session = make_session(tmp_path, lambda *_: {"stdout": "x" * VIEW_CHARS + "TAIL"})
    step(session, "exec", {"command": "large", "timeout_sec": 10})
    assert "TAIL" not in session.sources["H001"].text
    start = session.raw_receipts["H001"].index("TAIL")
    step(session, "read", {"ref": "H001", "start": start, "length": 4})
    assert '"text": "TAIL"' in session.raw_receipts["H002"]
    assert session.host.mode == "COMMON_CONTEXT"


def test_unknown_terminal_failure_halts_without_repeat(tmp_path):
    effects = []

    def terminal(*_):
        effects.append(1)
        raise TimeoutError("unknown completion")

    session = make_session(tmp_path, terminal)
    with pytest.raises(TimeoutError):
        step(session, "exec", {"command": "unknown", "timeout_sec": 1})
    with pytest.raises(WorkspaceError, match="HOST_HALTED"):
        step(session, "exec", {"command": "unknown", "timeout_sec": 1})
    assert effects == [1]
