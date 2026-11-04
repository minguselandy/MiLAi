"""Real pre-Host Store/Saver forks with scripted model decisions, never model-quality claims."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_frozen_retrieval import native_request
from test_given_retrieval import prepared_given, source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_host_message import replay_host_message
from milai_lab.runners.functional import frozen, message, prepare
from milai_lab.runners.host_evidence_presentation import INDEX_PREFIX, PRESENTATION

VERSION = "mechanical-pre-host-v1"


def capture_root(tmp_path, *, native=True, thinking=None):
    original = prepared_given(tmp_path, native=native, host_source_arrivals=True, policy={
        "policy": "fixed_context", "max_control_steps": 6, "delivery_selection": True})
    config = tmp_path / "host-capture-config.json"
    settings = frozen(original)["config"]
    if thinking is not None:
        settings['host']['enable_thinking'] = thinking
        settings['capacity']['enable_thinking'] = thinking
        for client in settings['http_ownership_domain']['clients']:
            client['enable_thinking'] = thinking
    write_json(config, settings)
    root = tmp_path / "source"
    prepare(root, config, source_version=VERSION, run_id=frozen(original)["run_id"])
    return root


@pytest.mark.parametrize('native', [True, False])
@pytest.mark.parametrize('original_thinking', [True, False])
def test_host_thinking_factor_changes_only_wire_flag_and_capacity_identity(
    tmp_path, monkeypatch, native, original_thinking,
):
    root = capture_root(tmp_path, native=native, thinking=original_thinking)

    def reply(wire, _ordinal):
        if not any(m['role']=='tool' for m in wire['messages']):
            return (native_request({'query':'Cedar code'}, 'first') if native else
                    {'calls':[{'name':'milai_retrieve','arguments':{'query':'Cedar code'}}]})
        return ({'role':'assistant','content':'4312'} if native else {'answer':'4312'})

    wires = scripted(monkeypatch, reply, native=native)
    snapshots = tmp_path/'snapshots'
    original = message(root, bank='bank', owner='alice', session='host', message_id='q',
        content='Find the Cedar code', incoming_sources=[source()], host_snapshots=snapshots)
    assert original['status']=='COMPLETED'
    captured, = snapshots.iterdir()
    before = {str(p.relative_to(captured)):p.read_bytes()
              for p in captured.rglob('*') if p.is_file()}
    branch = replay_host_message(captured,tmp_path/'changed','current',source_version=VERSION,
                                 host_enable_thinking=not original_thinking)
    assert branch['status']=='COMPLETED', branch.get('error')
    assert branch['final_answer']=='4312' and branch['generation_calls']==2
    assert branch['host_enable_thinking_override'] is not original_thinking
    assert all(branch[k] for k in ('frozen_pre_host_state_equal',
        'frozen_host_baseline_context_equal','frozen_host_tool_catalog_equal'))
    first,changed = copy.deepcopy(wires[0]),copy.deepcopy(wires[2])
    assert first['chat_template_kwargs'].pop('enable_thinking') is original_thinking
    assert changed['chat_template_kwargs'].pop('enable_thinking') is not original_thinking
    assert first==changed
    traces = (tmp_path/'changed/runtime').glob('banks/*/*-trace-*.jsonl')
    events = [json.loads(line) for path in traces
              for line in path.read_text().splitlines()]
    provider = [e for e in events if e.get('event')=='vllm_response']
    assert len(provider)==2
    assert all(e['capacity']['identity']['enable_thinking'] is not original_thinking
               for e in provider)
    assert branch['budget_before']['limits']==branch['budget_after']['limits']
    assert branch['budget_before']['generation_requests']==original['budget_after'][
        'generation_requests']
    assert branch['budget_after']['generation_requests']-branch['budget_before'][
        'generation_requests']==2
    assert {str(p.relative_to(captured)):p.read_bytes()
            for p in captured.rglob('*') if p.is_file()}==before
    replay = read_json(tmp_path/'changed/replay.json')
    assert replay['host_enable_thinking_override'] is not original_thinking
    assert replay['prefix_model_or_tool_operations_reexecuted']==0


def test_thinking_override_requires_the_actual_frozen_host_boundary(tmp_path,monkeypatch):
    root = capture_root(tmp_path)
    wires = scripted(monkeypatch,lambda *_:{'role':'assistant','content':'Done.'},native=True)
    with pytest.raises(ValueError,match='PRE_HOST_SNAPSHOT_AND_BOOL'):
        message(root,bank='bank',owner='alice',session='host',message_id='q',content='Acknowledge',
                host_enable_thinking_override=False)
    assert not wires


@pytest.mark.parametrize('native', [True, False])
def test_method_branch_changes_controller_and_keeps_full_autonomous_host_loop(
    tmp_path, monkeypatch, native,
):
    root = capture_root(tmp_path, native=native)

    def ask(query, call_id):
        return (native_request({'query': query}, call_id) if native else
                {'calls': [{'name': 'milai_retrieve', 'arguments': {'query': query}}]})

    def answer(content):
        return {'role': 'assistant', 'content': content} if native else {'answer': content}

    def reply(wire, _ordinal):
        receipts = [m for m in wire['messages'] if m['role'] == 'tool']
        if not receipts:
            return ask('Cedar code', 'first')
        if any(json.loads(m['content'])['evidence'] for m in receipts):
            return answer('4312')
        if len(receipts) == 1:
            return ask('Cedar code again', 'second')
        return answer('No evidence delivered.')

    wires = scripted(monkeypatch, reply, native=native)
    snapshots = tmp_path / 'snapshots'
    original = message(root, bank='bank', owner='alice', session='host', message_id='q',
        content='Find the Cedar code', incoming_sources=[source()], host_snapshots=snapshots)
    assert original['status'] == 'COMPLETED' and original['generation_calls'] == 2
    captured, = snapshots.iterdir()
    before = {str(p.relative_to(captured)): p.read_bytes()
              for p in captured.rglob('*') if p.is_file()}

    class Handoff:
        def __init__(self, *args, **kwargs):
            self.counters = {'forwards': 0}

        def predict(self, payload):
            self.counters['forwards'] += 1
            return {'choice': 'handoff'}

    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr('milai_lab.runners.memory_control.NativeDecision', Handoff)
    branch = replay_host_message(captured, tmp_path / 'learned', 'current',
        source_version=VERSION, control_policy={'policy': 'laya', 'checkpoint': 'stub'})
    assert branch['status'] == 'COMPLETED', branch.get('error')
    assert branch['final_answer'] == 'No evidence delivered.'
    # The shared native allowance includes two local policy decisions as well as three HTTP calls.
    assert branch['generation_calls'] == 5
    assert (branch['budget_after']['generation_requests']
            - branch['budget_before']['generation_requests']) == 3
    assert all(branch[k] for k in ('frozen_pre_host_state_equal',
        'frozen_host_baseline_context_equal', 'frozen_host_tool_catalog_equal'))
    assert wires[0] == wires[2]  # Same first Host request before either policy runs.
    assert branch['budget_after']['compute']['dynamic_memory_laya']['forwards'] == 2
    assert {str(p.relative_to(captured)): p.read_bytes()
            for p in captured.rglob('*') if p.is_file()} == before
    assert read_json(tmp_path / 'learned/replay.json')['control_policy_override'][
        'max_control_steps'] == frozen(root)['config']['memory_control']['max_control_steps']


@pytest.mark.parametrize('override', [
    {'policy': 'fixed', 'max_control_steps': 99}, {'policy': 'fixed', 'reads': 99},
    {'policy': 'laya'}, {'policy': 'generative'}])
def test_method_branch_cannot_change_limits_or_leave_learned_weights_unbound(
    tmp_path, monkeypatch, override,
):
    root = capture_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: {'role': 'assistant', 'content': 'Done.'}, native=True)
    snapshots = tmp_path / 'snapshots'
    result = message(root, bank='bank', owner='alice', session='host', message_id='q',
        content='Acknowledge.', incoming_sources=[source()], host_snapshots=snapshots)
    assert result['status'] == 'COMPLETED'
    captured, = snapshots.iterdir()
    with pytest.raises(ValueError):
        replay_host_message(captured, tmp_path / 'changed', 'current', source_version=VERSION,
                            control_policy=override)
    assert len(wires) == 1


@pytest.mark.parametrize("prior_receipt", [False, True])
def test_complete_branch_restores_pre_host_state_arrivals_and_allowance_without_future_leak(
    tmp_path, monkeypatch, prior_receipt,
):
    root = capture_root(tmp_path)
    calls = {"bank": "bank", "owner": "alice", "session": "host"}
    target_inputs = []

    def reply(wire, _ordinal):
        last = max(i for i, m in enumerate(wire["messages"]) if m["role"] == "user")
        question = wire["messages"][last]["content"]
        if question.startswith("Target question"):
            assert "COLLECTOR_FUTURE_ANSWER" not in json.dumps(wire)
            target_inputs.append(copy.deepcopy(wire))
            if INDEX_PREFIX in question:
                return {"role": "assistant", "content": "Branch direct answer."}
        if not any(m["role"] == "tool" for m in wire["messages"][last + 1:]):
            return native_request({"query": "Cedar code"}, call_id=f"retrieval-{_ordinal}")
        return {"role": "assistant", "content": "4312" if question == "Prior question"
                else "COLLECTOR_FUTURE_ANSWER"}

    wires = scripted(monkeypatch, reply, native=True)
    if prior_receipt:
        prior = message(root, **calls, message_id="prior", content="Prior question",
                        incoming_sources=[source()])
        assert prior["status"] == "COMPLETED", prior.get("error")
    snapshots = tmp_path / "snapshots"
    kwargs = {"previous_host_message": "prior"} if prior_receipt else {}
    incoming = [{**source(), "event_key": "unrelated", "content": "UNOPENED_UNRELATED_SOURCE"}]
    if not prior_receipt:
        incoming = [source()]
    original = message(root, **calls, message_id="target", content="Target question",
        incoming_sources=incoming, host_snapshots=snapshots, **kwargs)
    assert original["status"] == "COMPLETED", original.get("error")
    captured, = snapshots.iterdir()
    row = read_json(captured / "host.json")
    assert row["status"] == "CAPTURED_PRE_HOST"
    assert row["ready_state"]["generation_calls_before"] == 0
    assert row["initial_baseline_context"] and row["initial_tool_catalog"]
    assert row["ready_state"]["incoming_source_receipts"][0]["newly_captured"] is True
    assert len([m for m in row["ready_state"]["initial_messages"]
                if m["type"] == "tool"]) == int(prior_receipt)
    saved = {p.relative_to(captured): p.read_bytes() for p in captured.rglob("*") if p.is_file()}
    before_count = len(wires)
    branch = replay_host_message(captured, tmp_path / "index", PRESENTATION, source_version=VERSION)
    assert branch["status"] == "COMPLETED", branch.get("error")
    assert branch["frozen_pre_host_state_equal"]
    assert branch["frozen_host_baseline_context_equal"]
    assert branch["frozen_host_tool_catalog_equal"]
    assert branch["final_answer"] == "Branch direct answer."
    assert len(wires) == before_count + 1
    assert branch["generation_calls"] == 1
    assert read_json(tmp_path / "index/replay.json")[
        "prefix_model_or_tool_operations_reexecuted"] == 0
    index = json.loads(target_inputs[-1]["messages"][
        max(i for i, m in enumerate(target_inputs[-1]["messages"]) if m["role"] == "user")][
            "content"].split(INDEX_PREFIX)[1])
    assert index["source_arrivals_as_shown"]["new_visible_sources"] == 1
    assert len(index["visible_retrieval_receipt_metadata"]) == int(prior_receipt)
    assert {p.relative_to(captured): p.read_bytes()
            for p in captured.rglob("*") if p.is_file()} == saved
    assert branch["budget_before"]["generation_requests"] == original["budget_after"][
        "generation_requests"]
    assert branch["budget_after"]["generation_requests"] == branch["budget_before"][
        "generation_requests"] + 1

    plain = replay_host_message(captured, tmp_path / "plain", "current", source_version=VERSION)
    assert plain["status"] == "COMPLETED", plain.get("error")
    assert plain["generation_calls"] == 2  # Its new retrieval really executes.
    assert plain["frozen_host_baseline_context_equal"]
    assert target_inputs[0] == target_inputs[-2]  # Complete initial model wire, before tool result.


def test_changed_ready_state_or_catalog_is_rejected_before_new_provider_request(
    tmp_path, monkeypatch,
):
    root = capture_root(tmp_path)
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "Done."}, native=True)
    snapshots = tmp_path / "snapshots"
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Acknowledge.", incoming_sources=[source()], host_snapshots=snapshots)
    assert result["status"] == "COMPLETED", result.get("error")
    captured, = snapshots.iterdir()
    original = read_json(captured / "host.json")
    changed = copy.deepcopy(original)
    changed["ready_state"]["read_allowance"]["reads_remaining"] += 1
    write_json(captured / "host.json", changed)
    failed = replay_host_message(captured, tmp_path / "changed", PRESENTATION,
                                 source_version=VERSION)
    assert failed["status"] == "FAILED" and failed["error"] == "FROZEN_PRE_HOST_STATE_CHANGED"
    assert len(wires) == 1
    changed = copy.deepcopy(original)
    changed["initial_tool_catalog"][0]["function"]["description"] = "different catalog"
    write_json(captured / "host.json", changed)
    failed = replay_host_message(captured, tmp_path / "changed-catalog", "current",
                                 source_version=VERSION)
    assert failed["status"] == "FAILED"
    assert failed["error"] == "FROZEN_HOST_INITIAL_TOOL_CATALOG_CHANGED"
    assert len(wires) == 1
    changed = copy.deepcopy(original)
    changed["initial_baseline_context"][0]["content"] += "Changed common context"
    write_json(captured / "host.json", changed)
    failed = replay_host_message(captured, tmp_path / "changed-context", PRESENTATION,
                                 source_version=VERSION)
    assert failed["status"] == "FAILED" and failed["error"] == "FROZEN_HOST_INITIAL_CONTEXT_CHANGED"
    assert len(wires) == 1
    with pytest.raises(ValueError, match="captured implementation"):
        replay_host_message(captured, tmp_path / "wrong-version", "current", source_version="other")


def test_original_unknown_provider_usage_remains_charged_when_new_arm_runs(tmp_path, monkeypatch):
    root = capture_root(tmp_path)
    fail = True

    def reply(*_):
        if fail:
            return httpx.ReadTimeout("Original response outcome unknown")
        return {"role": "assistant", "content": "New arm answer."}

    wires = scripted(monkeypatch, reply, native=True)
    snapshots = tmp_path / "snapshots"
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Acknowledge.", incoming_sources=[source()], host_snapshots=snapshots)
    assert original["status"] == "PROVIDER_ERROR"
    assert original["budget_after"]["generation"]["unknown_usage"] == 1
    captured, = snapshots.iterdir()
    metadata = read_json(captured / "host.json")
    original_result = root / metadata["host_result_path"]
    retained = original_result.read_bytes()
    fail = False
    result = replay_host_message(captured, tmp_path / "new-arm", PRESENTATION,
                                 source_version=VERSION)
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["budget_before"]["generation"]["unknown_usage"] == 1
    assert result["budget_after"]["generation"]["unknown_usage"] == 1
    assert len(wires) == 2 and original_result.read_bytes() == retained
    replay = read_json(tmp_path / "new-arm/replay.json")
    assert replay["original_message_status"] == "PROVIDER_ERROR"


def test_collection_and_single_branch_cli_use_the_same_pre_host_protocol(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import run_frozen_host_message
    import run_host_intent_retrieval

    original = capture_root(tmp_path)
    config = tmp_path / "cli-config.json"
    settings = copy.deepcopy(frozen(original)["config"])
    settings["config_version"] = frozen(original)["config_version"]
    write_json(config, {"entrypoints": {"functional": settings}})
    fixture = tmp_path / "fixture.json"
    write_json(fixture, {"histories": [{"id": "one", "source_group": "one-family", "split": "dev",
        "sources": [source()], "requests": [{"id": "q", "content": "Acknowledge."}]}]})
    wires = scripted(monkeypatch, lambda *_: {"role": "assistant", "content": "Done."}, native=True)
    output = tmp_path / "collected"
    monkeypatch.setattr(sys, "argv", ["collect", str(config), str(fixture), str(output),
        "--source-version", VERSION, "--policies", "fixed_context", "--interfaces", "rich",
        "--capture-host-messages"])
    run_host_intent_retrieval.main()
    driver = read_json(output / "driver.json")
    assert driver["status"] == "COMPLETED" and driver["capture_host_messages"]
    captured, = (output / "frozen-host-messages").iterdir()
    monkeypatch.setattr(sys, "argv", ["branch", str(captured), str(tmp_path / "branch"),
        "--presentation", PRESENTATION, "--source-version", VERSION])
    run_frozen_host_message.main()
    assert read_json(tmp_path / "branch/replay.json")["status"] == "COMPLETED"
    assert len(wires) == 2
