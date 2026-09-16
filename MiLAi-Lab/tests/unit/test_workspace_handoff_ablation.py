"""Mechanical counterfactuals; mock generations are not experimental outcomes."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_workspace_task_a import MockCounts, package

import run_workspace_handoff_ablation as entry
from workspace_policy_host import Generation
from workspace_task_provider import Provider


def formed():
    counts = MockCounts()
    task = entry.base.ContinuationTask(package(), "test", counts)
    host = entry.base.make_host(task, counts, "FORMATION_ONLY", entry.base.capacity_limits(65536))
    host.step(
        new=task.begin("formation"),
        generate=lambda _: Generation(
            json.dumps(
                {
                    "action": "stage_answer",
                    "arguments": {"text": "unique old handoff"},
                    "work_update": {"text": "optional separate channel", "focus_refs": ["E1"]},
                }
            ),
            "MOCK",
            True,
        ),
        dispatch=task.dispatch,
    )
    entry.base.mark_stage_output(host)
    return counts, task, host


def test_forks_preserve_sources_workspace_receipts_and_isolate_actions():
    counts, original, host = formed()
    full, full_host, new_full = entry.fork_consumer(host, original, counts, "FULL")
    lesioned, drop_host, new_drop = entry.fork_consumer(host, original, counts, "NO_HANDOFF")
    assert new_full == new_drop
    assert full.registry == lesioned.registry and set(full.registry) == {"E1", "E2", "E3"}
    assert full_host.workspace == drop_host.workspace == host.workspace
    full_messages = [m for g in full_host.history for m in g.messages]
    drop_messages = [m for g in drop_host.history for m in g.messages]
    assert [entry.lesion_message(m) for m in full_messages] == drop_messages
    assert sum(a != b for a, b in zip(full_messages, drop_messages, strict=True)) == 1
    assert all(f"actual-{n}" in " ".join(m.content for m in drop_messages) for n in (1, 2))
    assert "unique old handoff" in full.history_records["H1"]
    assert "unique old handoff" not in lesioned.history_records["H1"]
    receipt = lesioned.dispatch({"action": "read", "arguments": {"ref": "H1"}})
    assert entry.WITHHELD in receipt.messages[0].content
    assert "unique old handoff" not in receipt.messages[0].content
    lesioned.dispatch({"action": "final", "arguments": {"text": "one branch only"}})
    assert full.final is None and original.final is None
    assert len(full.actions) == len(original.actions) == 1
    assert full_host.base == drop_host.base and full_host.policy == drop_host.policy
    assert "FORMATION_ONLY" not in full_host.policy


@pytest.mark.parametrize("failure", [None, "unknown", "malformed", "empty", "truncated"])
def test_real_entry_with_mock_http_preserves_accounting_and_full_schedule(
    tmp_path, monkeypatch, failure
):
    sent = []

    def transport(request):
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"data": [{"id": entry.base.MODEL, "max_model_len": 65536}]}
            )
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        body = json.loads(request.content)
        sent.append(body)
        stage = json.loads(body["messages"][-1]["content"])["segment"]
        text = "" if failure == "empty" else "unique old handoff"
        value = {
            "action": "stage_answer" if stage == "formation" else "final",
            "arguments": {"text": text},
        }
        raw = "{" if failure == "malformed" else json.dumps(value)
        if stage == "consumption":
            serialized = json.dumps(body)
            assert all(f"actual-{n}" in serialized for n in (1, 2, 3))
            assert sum("HOST_CAPTURED_STAGE_OUTPUT" in m["content"] for m in body["messages"]) == 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": raw},
                        "finish_reason": "length" if failure == "truncated" else "stop",
                    }
                ],
                "usage": None
                if failure == "unknown"
                else {
                    "prompt_tokens": 100,
                    "completion_tokens": 40,
                    "total_tokens": 140,
                },
            },
        )

    monkeypatch.setattr(entry, "Counts", MockCounts)
    monkeypatch.setattr(
        entry,
        "Provider",
        lambda root, **kw: Provider(
            root,
            transport=httpx.MockTransport(transport),
            **kw,
        ),
    )
    entry.dump(tmp_path / "package/visible/task.json", package())
    result = entry.run(tmp_path / "package", tmp_path / "run")
    if failure == "unknown":
        assert len(sent) == 1 and result["status"] == "STOPPED_NO_RETRY"
        assert result["accounting"]["pending"] and result["actual_total_raw_tokens"] is None
    else:
        count = 12 if failure is None else 4
        assert len(sent) == count and result["status"] == "SCHEDULE_FINISHED"
        assert result["actual_total_raw_tokens"] == count * 140
        assert not result["accounting"]["pending"]
        if failure is not None:
            assert all(g["status"] == "NO_VALID_HANDOFF" for g in result["groups"].values())
        else:
            assert list(result["groups"]) == ["W1-R", "W1-EXPLAIN", "W2-EXPLAIN", "W2-R"]
            for group in result["groups"].values():
                assert set(group["consumers"]) == {"FULL", "NO_HANDOFF"}
