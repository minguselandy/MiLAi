import copy
from dataclasses import asdict
from pathlib import Path

import pytest
from test_original_feedback_host import bound_fixture, completed_arm

import settle_bound_optimization_host as settlement
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunLimits
from run_bound_optimization_host import local_cpu_accounting


def failed_fixture(tmp_path):
    dispatch = bound_fixture(tmp_path)
    optimization = tmp_path / 'optimization'
    optimization.mkdir()
    dispatch['status'] = 'OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED'
    dispatch['study'].update(positions_per_unique_arm=16, execution_id='test-cohort',
        task_conditions={}, dispatch_scope='Synthetic test',
        optimization_study=str(optimization / 'study.json'))
    arm = dispatch['arms'][0]
    completed_arm(dispatch, arm)
    root = Path(arm['output'])
    before, after = (read_json(root / name) for name in ('budget-before.json', 'budget-after.json'))
    for budget in (before, after):
        budget['limits'] = asdict(RunLimits())
    before['compute'] = {'dynamic_memory_laya': {'cpu_seconds': 7.}}
    after['compute'] = {'dynamic_memory_laya': {'cpu_seconds': 8.5},
                        'dynamic_memory_laya_load': {'cpu_seconds': .5}}
    dispatch_path = tmp_path / 'bound/dispatch.json'
    write_json(dispatch_path, dispatch)
    owner = dispatch_path.parent / 'orchestration' / arm['id']
    for name, budget in [('budget-before.json', before), ('budget-after.json', after)]:
        write_json(root / name, budget)
        write_json(owner / name, budget)
    ledger = Path(read_json(Path(arm['config']))['entrypoints']['functional']['budget_path'])
    write_json(ledger, after)
    driver = {'status': 'FAILED_RETAINED', 'pid': 90000001, 'child_pid': 90000002,
              'dispatch': str(dispatch_path), 'execution_id': 'test-cohort', 'arm_id': arm['id'],
              **{key: arm[key] for key in ('output', 'argv', 'environment')}, 'exit_code': 1,
              **local_cpu_accounting(before, after, 5.25),
              'orchestration_cpu_seconds_pending': .75}
    write_json(owner / 'driver.json', driver)
    offline = tmp_path / 'offline.json'
    write_json(offline, {'cpu_seconds_pending': .5})
    inventory = tmp_path / 'inventory.json'
    write_json(inventory, {'accounting': {
        'pending_disjoint_entries_excluding_this_progress': [
            {'file': str(offline), 'field': 'cpu_seconds_pending'}],
        'progress_processing_cpu_pending': .125}})
    return dispatch_path, arm, owner, ledger, inventory, optimization


def test_failed_attempt_cost_is_settled_once_without_rebilling_native_or_grading_missing(
    tmp_path, monkeypatch,
):
    dispatch, arm, _, ledger, inventory, optimization = failed_fixture(tmp_path)
    monkeypatch.setattr(settlement, 'active_model_owners', lambda: [])
    before = read_json(ledger)
    output = optimization / 'host-test-settlement-v1.json'
    result = settlement.settle(dispatch, arm['id'], inventory, output, 'offline-host')
    after = read_json(ledger)
    assert result['measures']['cpu_seconds'] == pytest.approx(
        4.625 + result['verification_processing_cpu_seconds'])
    assert after['generation'] == before['generation']
    assert after['generation']['unknown_usage'] == 1
    assert after['compute']['dynamic_memory_laya'] == before['compute']['dynamic_memory_laya']
    assert result['verification']['owner_status'] == 'FAILED_RETAINED'
    summary = result['verification']['arm_summary']
    assert summary['planned_positions'] == 16 and summary['confirmed_task_successes'] == 0
    assert summary['semantic_counts'] == {'unknown': 16}
    retained = copy.deepcopy(after)
    with pytest.raises(ValueError, match='ledger changes'):
        settlement.settle(dispatch, arm['id'], inventory,
                          optimization / 'host-second-settlement-v1.json', 'other-phase')
    assert read_json(ledger) == retained


@pytest.mark.parametrize('change', ['residual', 'tasks', 'false_completion', 'paid_inventory'])
def test_unreconciled_or_changed_attempt_never_writes_the_ledger(tmp_path, monkeypatch, change):
    dispatch, arm, owner, ledger, inventory, optimization = failed_fixture(tmp_path)
    monkeypatch.setattr(settlement, 'active_model_owners', lambda: [])
    if change == 'paid_inventory':
        entry = read_json(inventory)['accounting'][
            'pending_disjoint_entries_excluding_this_progress']
        write_json(optimization / 'previous-settlement-v1.json', {'entries': entry})
    elif change == 'tasks':
        path = Path(arm['output']) / 'fixture.json'
        fixture = read_json(path)
        fixture['histories'][0]['requests'][0]['content'] = 'Changed task'
        write_json(path, fixture)
    else:
        driver = read_json(owner / 'driver.json')
        if change == 'residual':
            driver['child_cpu_pending'] += 1
        else:
            driver['status'] = 'COMPLETED'
            driver['exit_code'] = 0
        write_json(owner / 'driver.json', driver)
    before = read_json(ledger)
    output = optimization / 'host-test-settlement-v1.json'
    with pytest.raises(ValueError):
        settlement.settle(dispatch, arm['id'], inventory, output, 'offline-host')
    assert read_json(ledger) == before and not output.exists()


def test_live_model_stops_before_any_receipt_or_ledger_access(tmp_path, monkeypatch):
    monkeypatch.setattr(settlement, 'active_model_owners', lambda: [12345])
    with pytest.raises(ValueError, match='No model may be active'):
        settlement.settle(tmp_path / 'missing-dispatch', 'arm', tmp_path / 'missing-inventory',
                          tmp_path / 'settlement.json', 'offline-host')
    assert not list(tmp_path.iterdir())
