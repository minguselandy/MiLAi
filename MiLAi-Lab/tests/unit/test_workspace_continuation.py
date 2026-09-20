"""Real continuation wiring with mock HTTP; not experimental model evidence."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_workspace_task_a import MockCounts, package

import run_workspace_continuation as entry
from milai_lab.methods.workspace_policy import Exchange, Message
from workspace_policy_host import Generation
from workspace_task_provider import Provider

REAL_TOKENIZER_AVAILABLE = all(
    (entry.TOKENIZER / name).is_file()
    for name in ("effective-tokenizer.json", "chat_template.jinja")
)
REAL_RENDERER_AVAILABLE = Path("/cra/qwen36-35B").is_dir()


@pytest.mark.parametrize(
    "failure", [None, "empty", "overlong", "malformed", "truncated", "unknown"]
)
@pytest.mark.skipif(
    not REAL_TOKENIZER_AVAILABLE,
    reason="external V0213 tokenizer evidence is not part of the Git checkout",
)
def test_complete_transition_exact_data_and_failure_paths(tmp_path, monkeypatch, failure):
    sent = []
    original = 'Visible handoff: "quoted"\n范围条件 — unfinished ≠ completed'

    def transport(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": entry.MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        body = json.loads(request.content)
        sent.append(body)
        notice = json.loads(body["messages"][-1]["content"])
        segment, decision = notice["segment"], notice["decision"]
        if segment == "formation":
            text = "" if failure == "empty" else "x" * 3000 if failure == "overlong" else original
            action = {
                "action": "stage_answer",
                "arguments": {"text": text},
                "work_update": {"text": "DO_NOT_CARRY_WORKSPACE", "focus_refs": ["E1"]},
            }
            if decision == 1:
                action.update(action="read", arguments={"ref": "E2"})
            raw = "{" if failure == "malformed" and decision == 2 else json.dumps(action)
        else:
            serialized = json.dumps(body, ensure_ascii=False)
            assert "DO_NOT_CARRY_WORKSPACE" in serialized
            assert all(f"actual-{n}" in serialized for n in (1, 2, 3))
            assert all(p not in serialized for p in json.loads(entry.POLICIES.read_text()).values())
            captures = []
            for message in body["messages"]:
                try:
                    value = json.loads(message["content"])
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("kind") == "HOST_CAPTURED_STAGE_OUTPUT":
                    captures.append(value)
            if failure in (None, "empty", "overlong"):
                assert len(captures) == 1
                expected = (
                    "" if failure == "empty" else "x" * 3000 if failure == "overlong" else original
                )
                assert captures[0]["arguments"]["text"].encode() == expected.encode()
            else:
                assert captures == []
            if decision == 1:
                assert "H1" in serialized
            raw = json.dumps(
                {
                    "action": "read" if decision < 3 else "final",
                    "arguments": {"ref": "E1" if decision == 1 else "H1"}
                    if decision < 3
                    else {"text": "complete synthesis"},
                }
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": raw},
                        "finish_reason": "length"
                        if failure == "truncated" and decision == 2 and segment == "formation"
                        else "stop",
                    }
                ],
                "usage": None
                if failure == "unknown"
                else {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            },
        )

    monkeypatch.setattr(entry, "Counts", MockCounts)
    monkeypatch.setattr(
        entry,
        "Provider",
        lambda root, **kwargs: Provider(root, transport=httpx.MockTransport(transport), **kwargs),
    )
    source = tmp_path / "package"
    entry.dump(source / "visible/task.json", package())
    root = tmp_path / "run"
    result = entry.run(source, root)
    if failure == "unknown":
        assert len(sent) == 1 and result["status"] == "STOPPED_NO_RETRY"
        assert result["accounting"]["pending"] and result["actual_total_raw_tokens"] is None
        return
    assert result["status"] == "THREE_ARMS_FINISHED" and len(sent) == 15
    consumer_systems = []
    for arm in entry.ORDER:
        terminal = result["arms"][arm]
        assert terminal["status"] == "COMPLETE"
        assert (
            terminal["handoff"]["status"]
            == {
                None: "VALID",
                "empty": "EMPTY",
                "overlong": "VALID",
                "malformed": "MISSING",
                "truncated": "MISSING",
            }[failure]
        )
        rows = json.loads((root / arm / "consumption-rows.json").read_text())
        assert rows[0]["workspace_before"]["revision"] >= 1
        assert rows[0]["new_body_refs"][0][0] == "E3"
        assert "actual-1" in json.dumps(rows[0]["result"])
        assert "VISIBLE_ACTION_AND_RECEIPT" in json.dumps(rows[1]["result"])
        assert "actual-2" in json.dumps(rows[1]["result"])
        consumer_systems.append(rows[0]["request"]["messages"][0])
    assert consumer_systems[0] == consumer_systems[1] == consumer_systems[2]


def test_segment_budget_and_lifecycle_do_not_use_semantic_keywords():
    task = entry.ContinuationTask(package(), "test", MockCounts())
    sources = task.begin("formation")
    assert set(task.registry) == {"E1", "E2"} and len(sources) == 2
    task.dispatch({"action": "final", "arguments": {"text": "done correct scope"}})
    assert task.final is None and not task.ended
    task.dispatch({"action": "stage_answer", "arguments": {"text": "wrong resume parked"}})
    assert task.ended and task.handoff["status"] == "VALID"
    task.begin("consumption")
    assert not task.ended
    task.dispatch({"action": "stage_answer", "arguments": {"text": "interim"}})
    assert not task.ended and task.final is None
    task.dispatch({"action": "final", "arguments": {"text": "actual final"}})
    assert task.final == "actual final"


def test_missing_handoff_can_continue_with_equal_source_access():
    task = entry.ContinuationTask(package(), "test", MockCounts())
    task.begin("formation")
    for _ in range(4):
        task.dispatch({"action": "calculate", "arguments": {"op": "add", "left": 1, "right": 2}})
    new = task.begin("consumption")
    host = entry.make_host(task, MockCounts(), "NOTE consumer", entry.capacity_limits(65536))
    assert host.history == [] and host.workspace.text == ""
    assert set(task.registry) == {"E1", "E2", "E3"}
    assert set(task.history_records) == {"H1", "H2", "H3", "H4"}
    host.step(
        new=(*new, Exchange((Message("user", "Continue"),))),
        generate=lambda _: Generation(
            json.dumps({"action": "read", "arguments": {"ref": "E2"}}), "MOCK", True
        ),
        dispatch=task.dispatch,
    )
    assert "actual-2" in json.dumps(host.rows[-1]["result"])
    assert "SECRET_FORMATION_POLICY" not in json.dumps(host.rows[-1]["request"])


def test_natural_history_ignores_k_and_handoff_occurs_once():
    task = entry.ContinuationTask(package(), "test", MockCounts())
    host = entry.make_host(
        task,
        MockCounts(),
        "FORMATION_ONLY",
        replace(entry.capacity_limits(65536), recent_exchanges=1),
    )
    new = task.begin("formation")
    for number in range(4):
        action = {
            "action": "stage_answer" if number == 3 else "suggest_check",
            "arguments": {"text": f"ordinary-progress-{number}"},
        }
        host.step(
            new=new,
            generate=lambda _, action=action: Generation(json.dumps(action), "MOCK", True),
            dispatch=task.dispatch,
        )
        new = ()
    entry.mark_stage_output(host)
    new = task.begin("consumption")
    consumer = entry.continue_host(host, task, MockCounts())
    consumer.step(
        new=new,
        generate=lambda _: Generation(
            json.dumps({"action": "final", "arguments": {"text": "complete"}}), "MOCK", True
        ),
        dispatch=task.dispatch,
    )
    row = consumer.rows[0]
    contents = [message["content"] for message in row["request"]["messages"]]
    assert all(any(f"ordinary-progress-{n}" in text for text in contents) for n in range(4))
    assert sum(text.count("ordinary-progress-3") for text in contents) == 1
    assert sum("HOST_CAPTURED_STAGE_OUTPUT" in text for text in contents) == 1
    assert "FORMATION_ONLY" not in "\n".join(contents)
    assert {ref[0] for ref in row["assembled_body_refs"]} == {"E1", "E2", "E3"}
    assert row["mode"] == "COMMON_CONTEXT"


@pytest.mark.skipif(
    not (REAL_TOKENIZER_AVAILABLE and REAL_RENDERER_AVAILABLE),
    reason="external tokenizer/model materials are not part of the Git checkout",
)
def test_effective_capacity_configuration_and_real_tokenizer_above_old_gates():
    counts = entry.Counts()
    value = package()
    value["batches"][0][0]["value"]["observation"] = " t" * 17000
    task = entry.ContinuationTask(value, "large-input", counts)
    limits = entry.capacity_limits(65536)
    assert limits.input_tokens == 61440 and limits.output_tokens == 4096
    host = entry.make_host(task, counts, "FORMATION_ONLY", limits)
    text = " x" * 600
    assert counts.text(text) > 512
    host.step(
        new=task.begin("formation"),
        generate=lambda _: Generation(
            json.dumps({"action": "stage_answer", "arguments": {"text": text}}), "MOCK", True
        ),
        dispatch=task.dispatch,
    )
    assert task.handoff["status"] == "VALID"
    entry.mark_stage_output(host)
    new = task.begin("consumption")
    consumer = entry.continue_host(host, task, counts)
    consumer.step(
        new=new,
        generate=lambda _: Generation(
            json.dumps({"action": "final", "arguments": {"text": "done"}}), "MOCK", True
        ),
        dispatch=task.dispatch,
    )
    for actual in (host.rows[0], consumer.rows[0]):
        tokens = counts.wire(actual["request"]["messages"])
        assert 16384 < tokens <= 61440 and tokens + actual["request"]["max_tokens"] <= 65536
    assert text in "\n".join(m["content"] for m in consumer.rows[0]["request"]["messages"])
    small = entry.make_host(task, counts, "FORMATION_ONLY", entry.capacity_limits(20000))
    with pytest.raises(entry.WorkspaceError, match="OVER_BUDGET"):
        small.step(
            new=new,
            generate=lambda _: pytest.fail("must stop before generation"),
            dispatch=task.dispatch,
        )
