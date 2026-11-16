"""Batching preserves first outcomes, shared weights and the original operational ledger."""
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from test_frozen_host_message import VERSION, capture_root
from test_given_retrieval import source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_json
from milai_lab.runners.functional import frozen, message
from run_frozen_host_messages import run_batch


def collected_cases(tmp_path, monkeypatch, mode):
    root = capture_root(tmp_path, native=False, thinking=True)

    def reply(wire, _ordinal):
        if not wire['chat_template_kwargs']['enable_thinking'] and mode['failure']:
            if mode['failure'] == 'unknown':
                return httpx.ReadTimeout('Outcome unknown')
            mode['failure'] = None
            return {'invalid': 'No answer or call envelope'}
        receipts = [m for m in wire['messages'] if m['role'] == 'tool']
        if not receipts or (not any(json.loads(m['content'])['evidence'] for m in receipts)
                            and len(receipts) == 1):
            return {'calls': [{'name': 'milai_retrieve', 'arguments': {'query': 'Cedar code'}}]}
        return {'answer': '4312' if any(json.loads(m['content'])['evidence'] for m in receipts)
                else 'No evidence'}

    wires = scripted(monkeypatch, reply, native=False)
    cases = []
    for index in range(2):
        snapshots = tmp_path/f'snapshots-{index}'
        actual = message(root, bank=f'bank-{index}', owner='alice', session='host', message_id='q',
            content='Find the Cedar code', incoming_sources=[source()], host_snapshots=snapshots)
        assert actual['status'] == 'COMPLETED'
        captured, = snapshots.iterdir()
        cases.append({'name': f'case-{index}', 'capture': str(captured)})
    return cases, frozen(root)['config']['budget_path'], wires


def test_batch_reuses_one_learned_model_and_shares_actual_message_allowances(tmp_path, monkeypatch):
    cases, budget, wires = collected_cases(tmp_path, monkeypatch, {'failure': None})
    loaded = []

    class Handoff:
        def __init__(self, *args, **kwargs):
            loaded.append(args)
            self.counters = {'forwards': 0}

        def predict(self, payload):
            self.counters['forwards'] += 1
            return {'choice': 'handoff'}

    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr('milai_lab.runners.memory_control.NativeDecision', Handoff)
    from pathlib import Path

    before = read_json(Path(budget))
    output = tmp_path/'batch'
    result = run_batch(cases, output, Path(budget), source_version=VERSION,
        control_policy={'policy': 'laya', 'checkpoint': 'stub'}, host_enable_thinking=False)
    assert result['status'] == 'COMPLETED' and len(result['completed']) == 2
    assert result['model_cache_entries'] == len(loaded) == 1
    assert [r['generation_calls'] for r in result['completed']] == [5, 5]
    after = read_json(Path(budget))
    assert after['generation_requests'] - before['generation_requests'] == 6
    assert after['compute']['dynamic_memory_laya']['forwards'] == 4
    assert after['limits'] == before['limits']
    assert all(not w['chat_template_kwargs']['enable_thinking'] for w in wires[4:])
    count = len(wires)
    with pytest.raises(FileExistsError):
        run_batch(cases, output, Path(budget), source_version=VERSION)
    assert len(wires) == count


@pytest.mark.parametrize('failure', ['known', 'unknown'])
def test_batch_keeps_failed_first_attempt_and_only_continues_known_usage(
    tmp_path, monkeypatch, failure,
):
    from pathlib import Path

    mode = {'failure': None}
    cases, budget, wires = collected_cases(tmp_path, monkeypatch, mode)
    retained = {str(p): p.read_bytes() for c in cases for p in Path(c['capture']).rglob('*')
                if p.is_file()}
    before = read_json(Path(budget))
    mode['failure'] = failure
    output = tmp_path/'batch'
    if failure == 'unknown':
        with pytest.raises(RuntimeError, match='First failed Host branch retained'):
            run_batch(cases, output, Path(budget), source_version=VERSION,
                host_enable_thinking=False, continue_known_failures=True)
        result = read_json(output/'driver.json')
        assert result['status'] == 'FAILED_RETAINED'
        assert len(result['completed']) == 1 and not (output/'case-1').exists()
        assert len(wires) == 5
        assert read_json(Path(budget))['generation']['unknown_usage'] == (
            before['generation']['unknown_usage'] + 1)
    else:
        result = run_batch(cases, output, Path(budget), source_version=VERSION,
            host_enable_thinking=False, continue_known_failures=True)
        assert result['status'] == 'COMPLETED_WITH_FAILURES'
        assert [r['status'] for r in result['completed']] == ['FAILED', 'COMPLETED']
        assert len(wires) == 7  # One failed dispatch, then two calls for the next capture.
        assert read_json(Path(budget))['generation']['unknown_usage'] == (
            before['generation']['unknown_usage'])
    assert {str(p): p.read_bytes() for c in cases for p in Path(c['capture']).rglob('*')
            if p.is_file()} == retained


def test_same_capture_cannot_be_executed_twice_inside_one_batch(tmp_path):
    from pathlib import Path

    cases = [{'name': 'a', 'capture': str(tmp_path/'capture')},
             {'name': 'b', 'capture': str(tmp_path/'capture')}]
    with pytest.raises(ValueError, match='distinct captures'):
        run_batch(cases, tmp_path/'out', Path('unused'), source_version=VERSION)
    assert not (tmp_path/'out').exists()


def test_message_cap_failure_is_retained_before_next_distinct_capture(tmp_path, monkeypatch):
    from pathlib import Path

    cases, budget, _ = collected_cases(tmp_path, monkeypatch, {'failure': None})
    retained = {str(p): p.read_bytes() for c in cases for p in Path(c['capture']).rglob('*')
                if p.is_file()}
    before = read_json(Path(budget))

    def repeat_until_cap(wire, ordinal):
        assert wire['chat_template_kwargs']['enable_thinking'] is False
        if ordinal <= 24:
            return {'calls': [{'name': 'milai_retrieve', 'arguments': {'query': 'Cedar code'}}]}
        return {'answer': 'The next distinct case completes.'}

    wires = scripted(monkeypatch, repeat_until_cap, native=False)
    output = tmp_path/'batch'
    result = run_batch(cases, output, Path(budget), source_version=VERSION,
        host_enable_thinking=False, continue_known_failures=True)
    assert result['status'] == 'COMPLETED_WITH_FAILURES'
    assert [r['status'] for r in result['completed']] == ['BUDGET_EXHAUSTED', 'COMPLETED']
    failed, following = result['completed']
    assert failed['error'] == 'PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED'
    assert failed['generation_calls'] == 24 and following['generation_calls'] == 1
    assert read_json(Path(failed['result']))['status'] == 'BUDGET_EXHAUSTED'
    admission, = (output/'case-0/runtime/banks').glob('*/message-admission.json')
    state = read_json(admission)
    assert state['configuration']['cap'] == 24
    assert [row['count'] for row in state['messages'].values()] == [24]
    after = read_json(Path(budget))
    assert after['limits'] == before['limits']
    assert after['generation_requests'] - before['generation_requests'] == len(wires) == 25
    assert after['generation']['unknown_usage'] == before['generation']['unknown_usage']
    assert {str(p): p.read_bytes() for c in cases for p in Path(c['capture']).rglob('*')
            if p.is_file()} == retained


def test_global_budget_failure_still_stops_before_next_case(tmp_path, monkeypatch):
    from pathlib import Path

    from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget

    cases, budget, wires = collected_cases(tmp_path, monkeypatch, {'failure': None})
    count = len(wires)

    def exhausted(*_args, **_kwargs):
        raise BudgetExceeded('generation token budget cannot fit next request reservation')

    monkeypatch.setattr(RunBudget, 'reserve', exhausted)
    output = tmp_path/'batch'
    with pytest.raises(RuntimeError, match='First failed Host branch retained'):
        run_batch(cases, output, Path(budget), source_version=VERSION,
            host_enable_thinking=False, continue_known_failures=True)
    result = read_json(output/'driver.json')
    assert result['status'] == 'FAILED_RETAINED' and len(result['completed']) == 1
    assert result['completed'][0]['error_type'] == 'BudgetExceeded'
    assert not (output/'case-1').exists() and len(wires) == count
