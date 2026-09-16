"""Controlled responses plus a real local dispatcher; no model or HTTP calls."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from milai_lab.methods.workspace_policy import Exchange, Limits, Material, Message, WorkspaceError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from workspace_policy_host import Generation, WorkspaceHost, load_policy


def count_messages(messages):
    return sum(len(message.content) + 8 for message in messages)  # Test-only codepoint counter.


def make_host(arm="REGULATED", mode="MANAGED_WORKSET", enabled=True):
    sources = {
        "E1": Material("E1", "r1", "task", "alpha source original"),
        "E2": Material("E2", "r1", "task", "beta source original"),
    }

    def validate(action):
        if action["action"] != "put" or set(action["arguments"]) != {"expected", "value"}:
            raise ValueError("task contract")

    host = WorkspaceHost(
        binding="task",
        base=(Message("system", "Task authority"), Message("user", "Do work")),
        registry=lambda: sources,
        count_text=len,
        count_messages=count_messages,
        validate_action=validate,
        policy=load_policy(arm),
        enabled=enabled,
        mode=mode,
    )
    return host, sources


def reply(work_update=None, expected=0, value="written", **generation_args):
    return Generation(
        json.dumps(
            {
                "action": "put",
                "arguments": {"expected": expected, "value": value},
                "work_update": work_update,
            }
        ),
        "MOCK",
        True,
        **generation_args,
    )


@pytest.mark.parametrize("arm", ["NOTE", "REVIEW", "REGULATED"])
@pytest.mark.parametrize("mode", ["COMMON_CONTEXT", "MANAGED_WORKSET"])
def test_same_capabilities_one_call_and_actual_next_input_change(arm, mode):
    host, sources = make_host(arm, mode)
    calls, effects = [], []
    world = {"version": 0, "value": None}

    def dispatch(action):
        args = action["arguments"]
        assert args["expected"] == world["version"]
        world.update(version=world["version"] + 1, value=args["value"])
        effects.append(dict(world))
        return Exchange((Message("user", json.dumps({"actual_receipt": dict(world)})),))

    def generate(request):
        calls.append(request)
        content = json.dumps(request)
        if len(calls) == 1:
            return reply({"text": "first optional record", "focus_refs": ["E1"]})
        if len(calls) == 2:
            assert "first optional record" in content and "actual_receipt" in content
            assert "alpha source original" in content
            return reply({"text": "replacement record", "focus_refs": ["E2"]}, expected=1)
        assert "first optional record" not in content  # Not replayed in old response history.
        assert "replacement record" in content and "beta source original" in content
        assert "new external correction" in content
        if mode == "MANAGED_WORKSET":
            assert "alpha source original" not in content
        return reply(None, expected=2)

    host.step(new=(), generate=generate, dispatch=dispatch)
    host.step(new=(), generate=generate, dispatch=dispatch)
    host.step(
        new=(Exchange((Message("user", "new external correction"),)),),
        generate=generate,
        dispatch=dispatch,
    )
    assert len(calls) == len(effects) == 3 and world["version"] == 3
    assert host.workspace.text == "replacement record"
    assert sources["E1"].text == "alpha source original"
    assert "first optional record" in host.rows[0]["raw_response"]
    assert all(row["delivery"] == "MOCK_INPUT_ONLY" for row in host.rows)
    json.dumps(host.rows)  # Existing logger can archive the complete record, no new ledger format.


def test_bad_work_update_does_not_retry_business_and_feedback_occurs_once():
    host, _ = make_host()
    calls, actions = [], []
    replies = iter([reply({"text": "too large" * 100, "focus_refs": []}), reply(), reply()])

    def generate(request):
        calls.append(request)
        return next(replies)

    def dispatch(action):
        actions.append(action)
        return Exchange((Message("user", "committed once"),))

    for _ in range(3):
        host.step(new=(), generate=generate, dispatch=dispatch)
    assert len(actions) == len(calls) == 3
    assert host.rows[0]["work_update_status"] == "REJECTED"
    assert "UPDATE_TEXT_BUDGET" in json.dumps(calls[1])
    assert "UPDATE_TEXT_BUDGET" not in json.dumps(calls[2])
    assert host.workspace.revision == 0


@pytest.mark.parametrize("failure", ["transport", "parse", "dispatch"])
def test_unknown_or_bad_response_halts_without_hidden_retry(failure):
    host, _ = make_host()
    calls, dispatches = [], []

    def generate(request):
        calls.append(request)
        if failure == "transport":
            raise TimeoutError("secret-bearing provider exception must not be recorded")
        if failure == "parse":
            return Generation('{"action":"put",', "MOCK", True)
        return reply({"text": "plan before receipt", "focus_refs": []})

    def dispatch(action):
        dispatches.append(action)
        raise TimeoutError("operation outcome unknown")

    with pytest.raises((TimeoutError, WorkspaceError)):
        host.step(new=(), generate=generate, dispatch=dispatch)
    with pytest.raises(WorkspaceError, match="NO_AUTOMATIC_RETRY"):
        host.step(new=(), generate=generate, dispatch=dispatch)
    assert len(calls) == 1 and len(dispatches) == int(failure == "dispatch")
    assert host.rows[0]["usage"] is None
    assert host.rows[0]["status"] == "STOPPED_NO_RETRY"
    assert "secret-bearing" not in json.dumps(host.rows)


def test_failed_delivery_not_mislabeled_as_presented():
    host, _ = make_host()
    with pytest.raises(WorkspaceError, match="UNCONFIRMED"):
        host.step(
            new=(),
            generate=lambda _: Generation("{}", "MOCK", False),
            dispatch=lambda _: pytest.fail("must not dispatch"),
        )
    assert host.rows[0]["assembled"] and host.rows[0]["delivery"] == "UNKNOWN"


def test_done_text_does_not_finish_task_and_real_result_is_not_rewritten():
    host, _ = make_host()
    returned = Exchange((Message("user", "FAILED: nothing written"),))
    host.step(
        new=(),
        generate=lambda _: reply({"text": "DONE", "focus_refs": []}),
        dispatch=lambda _: returned,
    )
    seen = []

    def generate(request):
        seen.append(json.dumps(request))
        return reply(None)

    host.step(
        new=(Exchange((Message("user", "later task stage"),)),),
        generate=generate,
        dispatch=lambda _: returned,
    )
    assert "FAILED: nothing written" in seen[0] and "later task stage" in seen[0]
    assert host.rows[0]["status"] == "STEP_COMPLETE_NOT_TASK_VERDICT"


def test_disabled_hook_preserves_native_input_and_response_contract():
    host, _ = make_host(enabled=False)
    calls = []

    def generate(request):
        calls.append(request)
        return Generation('{"action":"put","arguments":{"expected":0,"value":"x"}}', "MOCK", True)

    new = Exchange((Message("user", "current observation"),))
    host.step(new=(new,), generate=generate, dispatch=lambda _: Exchange((Message("user", "ok"),)))
    assert calls[0]["messages"] == [message.wire() for message in (*host.base, *new.messages)]
    assert host.workspace.revision == 0 and "work_update" not in json.dumps(calls[0])


def test_revocation_does_not_leak_via_recent_history_or_disabled_fallback():
    host, sources = make_host(mode="COMMON_CONTEXT")
    host.step(
        new=(),
        generate=lambda _: reply({"text": "derived alpha", "focus_refs": []}),
        dispatch=lambda _: Exchange((Message("user", "derived receipt"),)),
    )
    sources["E1"] = replace(sources["E1"], eligible=False)
    for enabled in (True, False):
        host.enabled = enabled
        with pytest.raises(WorkspaceError, match="DISCLOSURE_UNAVAILABLE"):
            host.step(
                new=(),
                generate=lambda _: pytest.fail("must not send withheld input"),
                dispatch=lambda _: pytest.fail("must not dispatch"),
            )


def test_policy_replacement_is_data_configuration_not_a_code_state_machine():
    note, _ = make_host("NOTE")
    regulated, _ = make_host("REGULATED")
    assert note.limits == regulated.limits == Limits()
    assert "unverified clues" in regulated.policy
    assert "conditions" in note.policy
    with pytest.raises(KeyError):
        load_policy("../../untrusted")
