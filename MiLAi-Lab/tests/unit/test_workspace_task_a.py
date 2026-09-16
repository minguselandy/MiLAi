"""Task schedule and Provider boundary regressions; HTTP mock is never model evidence."""

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_workspace_task_a as entry
from v02_local_provider import accounting, read_events
from v0213_provider import MODEL
from workspace_task_provider import Provider


def package():
    return {
        "task": entry.TASK,
        "field_definitions": entry.FIELDS,
        "batches": [
            [{"handle": f"E{n}", "value": {"batch": n, "observation": f"actual-{n}"}}]
            for n in (1, 2, 3)
        ],
    }


def test_releases_ignore_state_words_and_early_final_does_not_consume_future():
    task = entry.Task(package(), "task")
    task.release(1)
    result = task.dispatch({"action": "final", "arguments": {"text": "DONE resume"}})
    assert "FINAL_NOT_YET_AVAILABLE" in result.messages[0].content
    assert not task.ended and task.final is None
    assert (
        "NOT_PUBLISHED"
        in task.dispatch({"action": "read", "arguments": {"ref": "E3"}}).messages[0].content
    )
    for phase in (1, 2):
        task.release(phase)
        task.dispatch({"action": "stage_answer", "arguments": {"text": "current diagnosis"}})
    task.release(3)
    assert set(task.registry) == {"E1", "E2", "E3"}
    assert (
        "actual-1"
        in task.dispatch({"action": "read", "arguments": {"ref": "E1"}}).messages[0].content
    )
    proposed = task.dispatch({"action": "suggest_check", "arguments": {"text": "collect more"}})
    assert '"executed":false' in proposed.messages[0].content


class MockCounts:
    def text(self, value):
        return len(value) // 4

    def wire(self, value):
        return 100

    def messages(self, value):
        return 100


@pytest.mark.parametrize("mode", ["COMMON_CONTEXT", "MANAGED_WORKSET"])
@pytest.mark.parametrize("failure", [None, "unknown_usage", "truncated"])
def test_full_run_logs_real_dispatch_and_stops_unknown_or_truncated(
    tmp_path,
    monkeypatch,
    failure,
    mode,
):
    sent = []

    def transport(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        body = json.loads(request.content)
        sent.append(body)
        notices = [
            json.loads(m["content"])
            for m in body["messages"]
            if m["role"] == "user" and m["content"].startswith('{"batch":')
        ]
        phase = notices[-1]["batch"]
        content = json.dumps(
            {
                "action": "final" if phase == 3 else "stage_answer",
                "arguments": {"text": f"Diagnosis from phase {phase}"},
                "work_update": {"text": f"Observation {phase}", "focus_refs": [f"E{phase}"]},
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "length" if failure == "truncated" else "stop",
                    }
                ],
                "usage": None
                if failure == "unknown_usage"
                else {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            },
        )

    def provider(root, **kwargs):
        return Provider(root, transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(entry, "Provider", provider)
    monkeypatch.setattr(entry, "Counts", MockCounts)
    # Snapshot hashes still point to actual source/tokenizer files, no network needed.
    package_root = tmp_path / "package"
    entry.dump(package_root / "visible/task.json", package())
    root = tmp_path / "run"
    result = entry.run(
        package_root, root, mode=mode, recent_exchanges=1, phase_opportunities=(2, 2, 4)
    )
    assert result["allocated_requests"] == 24
    if failure:
        assert len(sent) == 1
        assert result["status"] == "STOPPED_NO_RETRY"
        assert not result["arms"]["NOTE"]["actions"]
        assert (result["actual_total_raw_tokens"] is None) == (failure == "unknown_usage")
    else:
        assert result["status"] == "THREE_ARMS_FINISHED"
        assert len(sent) == 9 and result["actual_total_raw_tokens"] == 1260
        for arm in entry.ORDER:
            assert result["arms"][arm]["status"] == "COMPLETE"
            rows = json.loads((root / arm / "rows.json").read_text())
            assert rows[0]["workspace_before"]["text"] == ""
            assert "Observation 1" in json.dumps(rows[1]["request"])
            for phase, row in enumerate(rows, 1):
                assert f"actual-{phase}" in json.dumps(row["request"])
                assert any(ref[0] == f"E{phase}" for ref in row["new_body_refs"])
            third = rows[2]
            if mode == "MANAGED_WORKSET":
                assert "actual-1" not in json.dumps(third["request"])
                assert "E1" in json.dumps(third["request"])  # Readable catalog remains.
                assert any(ref[0] == "E1" for ref in third["published_not_in_body"])
            else:
                assert "actual-1" in json.dumps(third["request"])
            events = read_events(root / arm / "events.jsonl")
            assert sum(e["event"] == "ACTION_RESULT" for e in events) == 3
        assert all(b["max_tokens"] == 2048 for b in sent)


def test_tokenizer_mismatch_stops_before_generation_and_pending_stops_next_call(tmp_path):
    generations = []

    def transport(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        generations.append(request)
        raise httpx.ReadTimeout("mock interrupted", request=request)

    provider = Provider(
        tmp_path,
        deadline=time.monotonic() + 60,
        max_requests=3,
        output_cap=2048,
        transport=httpx.MockTransport(transport),
    )
    provider.context = 65536
    body = {
        "model": MODEL,
        "max_tokens": 2048,
        "messages": [],
        "chat_template_kwargs": {},
        "add_generation_prompt": True,
        "add_special_tokens": False,
    }
    with pytest.raises(ValueError, match="TOKENIZER_DISAGREEMENT"):
        provider.generate("NOTE", body, expected_prompt_tokens=101)
    assert not generations
    with pytest.raises(httpx.ReadTimeout):
        provider.generate("NOTE", body, expected_prompt_tokens=100)
    with pytest.raises(ValueError, match="UNSETTLED_USAGE"):
        provider.generate("REVIEW", body, expected_prompt_tokens=100)
    assert len(generations) == 1 and accounting(read_events(provider.ledger))["pending"]
    provider.close()


def test_managed_focus_retains_old_body_and_new_observation_overrides_old_focus():
    from milai_lab.methods.workspace_policy import Exchange, Limits, Message
    from workspace_policy_host import Generation, WorkspaceHost, load_policy

    task = entry.Task(package(), "test")
    host = WorkspaceHost(
        binding=task.binding,
        enabled=True,
        policy=load_policy("NOTE"),
        base=(Message("system", "Task authority"), Message("user", entry.TASK)),
        registry=lambda: task.registry,
        count_text=lambda text: len(text) // 4,
        count_messages=lambda messages: 100,
        validate_action=task.validate,
        mode="MANAGED_WORKSET",
        limits=Limits(recent_exchanges=1),
    )

    def generate(request):
        return Generation(
            json.dumps(
                {
                    "action": "stage_answer",
                    "arguments": {"text": "stage"},
                    "work_update": {"text": "keep old uncertainty", "focus_refs": ["E1"]},
                }
            ),
            "MOCK",
            True,
        )

    for phase in (1, 2, 3):
        host.step(new=task.release(phase), generate=generate, dispatch=task.dispatch)
    third = host.rows[2]
    assert third["expanded"] == ("E1",)
    assert all(f"actual-{phase}" in json.dumps(third["request"]) for phase in (1, 2, 3))
    assert "keep old uncertainty" in json.dumps(third["request"])

    # Clearing focus removes the old body next call, with a still-usable original read action.
    def clear(request):
        return Generation(
            json.dumps(
                {
                    "action": "calculate",
                    "arguments": {"op": "add", "left": 1, "right": 2},
                    "work_update": {"text": "", "focus_refs": []},
                }
            ),
            "MOCK",
            True,
        )

    host.step(new=(), generate=clear, dispatch=task.dispatch)

    def read(request):
        assert "actual-1" not in json.dumps(request)
        return Generation(json.dumps({"action": "read", "arguments": {"ref": "E1"}}), "MOCK", True)

    returned = host.step(
        new=(Exchange((Message("user", "Continue"),)),), generate=read, dispatch=task.dispatch
    )
    assert "actual-1" in returned.messages[0].content


def test_last_phase_stage_answer_preserves_remaining_final_opportunities():
    task = entry.Task(package(), "task")
    task.release(3)
    receipt = task.dispatch({"action": "stage_answer", "arguments": {"text": "preliminary"}})
    assert "FINAL_STILL_REQUIRED" in receipt.messages[0].content
    assert not task.ended and task.final is None
    task.dispatch({"action": "read", "arguments": {"ref": "E3"}})
    task.dispatch({"action": "final", "arguments": {"text": "final synthesis"}})
    assert task.ended and task.final == "final synthesis"
    assert [a["action"]["action"] for a in task.actions] == ["stage_answer", "read", "final"]
