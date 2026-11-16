import copy
from pathlib import Path

import pytest

from run_bound_optimization_host import (
    active_model_owners,
    local_cpu_accounting,
    validate_bound_arm,
)


def test_only_known_local_scorer_cpu_is_subtracted_and_unknown_http_usage_is_retained():
    before = {'limits': {'generation_requests': 10}, 'generation': {'unknown_usage': 0},
              'compute': {'dynamic_memory_laya': {'cpu_seconds': 7.}}}
    after = copy.deepcopy(before)
    after['generation']['unknown_usage'] = 1
    after['compute']['dynamic_memory_laya']['cpu_seconds'] = 8.5
    after['compute']['dynamic_memory_laya_load'] = {'cpu_seconds': .5}
    retained = copy.deepcopy(after)
    result = local_cpu_accounting(before, after, 3.25)
    assert result['child_cpu_pending'] == 1.25
    assert sum(result['known_local_CPU_already_recorded'].values()) == 2
    assert after == retained and after['generation']['unknown_usage'] == 1
    assert local_cpu_accounting(before, before, 3.25)['child_cpu_pending'] == 3.25


@pytest.mark.parametrize('case', ['unowned_phase', 'negative_residual', 'limits'])
def test_unreconciled_cpu_is_never_clamped_or_silently_billed(case):
    before = {'limits': {}, 'compute': {}}
    after = {'limits': {}, 'compute': {'dynamic_memory_laya': {'cpu_seconds': 2.}}}
    if case == 'unowned_phase':
        after['compute'] = {'other_job': {'cpu_seconds': 2.}}
    elif case == 'limits':
        after['limits'] = {'changed': 1}
    with pytest.raises(ValueError):
        local_cpu_accounting(before, after, 1.)


def test_process_admission_distinguishes_real_entrypoints_from_readonly_work(tmp_path):
    for pid, argv in [(70000001, ['python', 'evaluate_bounded_laya.py']),
                      (70000002, ['python', 'audit_source_selection.py']),
                      (70000003, ['python', 'run_host_saved_cpu.py']),
                      (70000004, ['python', '/study/run_query_format_dev32_v1.py']),
                      (70000005, ['python', '/study/prepare.py'])]:
        process = tmp_path / str(pid)
        process.mkdir()
        (process / 'cmdline').write_bytes(('\0'.join(argv) + '\0').encode())
    assert sorted(active_model_owners(tmp_path)) == [70000001, 70000003, 70000004]


def test_binding_does_not_allow_forced_calls_or_a_second_attempt(tmp_path):
    runtime = tmp_path / 'runtime'
    arm = {'id': 'rules', 'policy': 'rules', 'config': 'config.json',
           'output': str(tmp_path / 'run'), 'environment': {'CUDA_VISIBLE_DEVICES': ''}}
    arm['argv'] = ['python', str(runtime / 'tools/run_host_intent_retrieval.py'),
        arm['config'], 'histories.json', arm['output'], '--policies', 'rules',
        '--interfaces', 'rich', '--split', 'dev', '--continue-host-history']
    dispatch = {'status': 'OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED',
        'bindings': {'status': 'READY', 'fits': [{}, {}, {}]}, 'arms': [arm],
        'study': {'runtime': str(runtime), 'histories': 'histories.json'}}
    assert validate_bound_arm(dispatch, 'rules') == arm
    changed = copy.deepcopy(dispatch)
    changed['arms'][0]['argv'].append('--given-requests')
    with pytest.raises(ValueError, match='inference protocol'):
        validate_bound_arm(changed, 'rules')
    Path(arm['output']).mkdir()
    with pytest.raises(ValueError, match='never retries'):
        validate_bound_arm(dispatch, 'rules')
