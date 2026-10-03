"""Mechanical replay privacy probes with real Store/Saver and scripted wire replies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_v13_5_functional_integration import materials, prepared, scripted, tool

from milai_lab.runners import functional

SECRET = "MECHANICAL_PRIVATE_REPLAY"


def invoke(root: Path, message_id: str, content: str, **kwargs: Any) -> dict[str, Any]:
    return functional.message(root, bank="mechanical-bank", owner="alice", session="session",
                              message_id=message_id, content=content, **kwargs)


def retained_public_artifacts(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.glob("banks/*/*")
            if path.name.endswith("-result.json") or "-attempt-" in path.name
            or path.name == "checkpoints.sqlite"}


@pytest.mark.parametrize("path", ["cached", "completed_resume", "pending_resume"])
def test_revoked_archived_response_never_reenters_default_or_resume_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> Any:
        if ordinal == 1:
            return tool("save_memory", content="marker " + SECRET, fragment_handles=[
                row["fragment_handle"] for row in materials(wire)["items"]
                if row["type"] == "fragment"])
        if ordinal == 2:
            return {"answer": "Saved."}
        if ordinal == 3:
            assert SECRET in json.dumps(materials(wire))
            if path == "pending_resume":
                return httpx.ReadTimeout("mechanical recall response lost")
            return {"answer": "The marker is " + SECRET}
        if ordinal == 4:
            record = next(row for row in materials(wire)["items"] if row["type"] == "record")
            return tool("forget_memory", read_handle=record["read_handle"])
        assert ordinal == 5
        return {"answer": "Forgotten."}

    wires = scripted(monkeypatch, reply)
    assert invoke(root, "save", "Remember marker " + SECRET)["status"] == "COMPLETED"
    original = invoke(root, "recall", "What marker did I store?")
    assert original["status"] == ("PROVIDER_ERROR" if path == "pending_resume" else "COMPLETED")
    if path != "pending_resume":
        assert SECRET in original["final_answer"]
    forgotten = invoke(root, "forget", "Forget the saved marker.")
    assert forgotten["status"] == "COMPLETED", forgotten
    assert len(wires) == 5
    retained = retained_public_artifacts(root)
    budget_path = tmp_path / "isolated-mechanical-budget.json"
    budget = budget_path.read_bytes()
    replay = invoke(root, "recall", "What marker did I store?", resume=path != "cached")
    assert replay["status"] == "VISIBILITY_REVOKED", replay
    assert replay["final_answer"] is None
    assert replay["messages"] == replay["records"] == replay["sources"] == []
    assert replay["historical_artifact_retained"] is True
    assert SECRET not in json.dumps(replay)
    assert len(wires) == 5
    assert retained_public_artifacts(root) == retained
    assert budget_path.read_bytes() == budget


def test_unrevoked_completed_response_keeps_normal_replay_without_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = prepared(tmp_path)

    def reply(wire: dict[str, Any], ordinal: int) -> dict[str, Any]:
        if ordinal == 1:
            return tool("save_memory", content="marker " + SECRET, fragment_handles=[
                row["fragment_handle"] for row in materials(wire)["items"]
                if row["type"] == "fragment"])
        assert ordinal == 2
        return {"answer": "Saved marker " + SECRET}

    wires = scripted(monkeypatch, reply)
    original = invoke(root, "save", "Remember marker " + SECRET)
    assert original["status"] == "COMPLETED"
    cached = invoke(root, "save", "Remember marker " + SECRET)
    assert cached == original
    resumed = invoke(root, "save", "Remember marker " + SECRET, resume=True)
    assert resumed["status"] == "COMPLETED"
    assert resumed["final_answer"] == original["final_answer"]
    assert len(wires) == 2
