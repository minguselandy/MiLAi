"""Identity/admission tests; actual CPU-output verification has separate receipt tests."""
import copy
from pathlib import Path

import pytest

import bind_optimization_retention_host as binding
from milai_lab.harness.artifact_io import read_json, write_json
from run_bound_optimization_host import validate_bound_arm


def fixture(tmp_path):
    base = str(tmp_path / 'base')
    conditions = {'device': 'cpu'}
    plans, fits = [], []
    for intervention in ['head-softce', 'head-set', 'full-softce']:
        plans.append({'run_id': intervention, 'intervention': intervention,
                      'output': str(tmp_path / intervention)})
        fits.append({'run_id': intervention, 'intervention': intervention,
            'selection': str(tmp_path / intervention / 'selection.json'),
            'GPU_retention': str(tmp_path / intervention / 'retention.json'),
            'CPU_confirmation': str(tmp_path / intervention / 'confirmation.json')})
    study = {'fits': fits, 'inference': conditions}
    optimization = {'plans': plans, 'common_initialization': base}
    cpu = {'conditions': conditions, 'common_base': {'checkpoint': base}}
    return study, optimization, cpu


def emit_first_method(tmp_path, study, optimization, cpu):
    spec, fit = optimization['plans'][0], study['fits'][0]
    checkpoint = Path(spec['output']) / 'checkpoints/update-12'
    checkpoint.mkdir(parents=True)
    (checkpoint / 'model.safetensors').write_bytes(b'not loaded in these identity tests')
    point = {'update': 12, 'checkpoint': str(checkpoint), 'metric': .75,
             'condition': {'device': 'cuda:0'}}
    selected = {'status': 'SAVED_GPU_QUALITY_SELECTION_VERIFIED', 'run_id': spec['run_id'],
                'deployment_selection': {'answer': point}}
    retained = {**selected, 'status':
                'SAVED_GPU_QUALITY_SELECTION_AND_RETENTION_VERIFIED;HOST_EVALUATION_PENDING'}
    confirmed = {'status': 'GPU_SELECTED_CHECKPOINT_CPU_CONFIRMED;HOST_EVALUATION_PENDING',
                 'run_id': spec['run_id'], 'GPU_selected_point': copy.deepcopy(point),
                 'CPU_conditions': cpu['conditions'], 'states': 4}
    for key, value in [('selection', selected), ('GPU_retention', retained),
                       ('CPU_confirmation', confirmed)]:
        write_json(Path(fit[key]), value)
    write_json(tmp_path / 'native-audits' / spec['run_id'] / 'analysis.json', {})
    write_json(tmp_path / 'cpu-confirmation' / spec['run_id'] / 'plan.json', {})
    return fit, confirmed


def test_missing_confirmations_remain_pending_and_cannot_materialize(tmp_path):
    study, optimization, cpu = fixture(tmp_path)
    result = binding.inspect_bindings(study, optimization, {}, cpu, tmp_path)
    assert result['status'] == 'PENDING' and result['ready_methods'] == 0
    with pytest.raises(ValueError, match='All three'):
        binding.materialize(study, result, tmp_path / 'bound', python='python',
                            attention_wrapper='attention.py')
    assert not (tmp_path / 'bound').exists()


def test_cpu_checkpoint_cannot_replace_the_gpu_selection(tmp_path):
    study, optimization, cpu = fixture(tmp_path)
    fit, confirmed = emit_first_method(tmp_path, study, optimization, cpu)
    confirmed['GPU_selected_point']['update'] = 24
    write_json(Path(fit['CPU_confirmation']), confirmed)
    with pytest.raises(ValueError, match='differs from the actual GPU selection'):
        binding.inspect_bindings(study, optimization, {}, cpu, tmp_path)


def test_ready_status_is_insufficient_when_actual_cpu_reverification_disagrees(
    tmp_path, monkeypatch,
):
    study, optimization, cpu = fixture(tmp_path)
    _, confirmed = emit_first_method(tmp_path, study, optimization, cpu)
    monkeypatch.setattr(binding, 'confirm', lambda *args: {**confirmed, 'states': 3})
    with pytest.raises(ValueError, match='no longer matches the actual confirmed outputs'):
        binding.inspect_bindings(study, optimization, {}, cpu, tmp_path)


def test_shared_zero_checkpoint_keeps_method_aliases_and_fixed_positions(tmp_path):
    study, optimization, _ = fixture(tmp_path)
    base = optimization['common_initialization']
    template = tmp_path / 'template.json'
    write_json(template, {'entrypoints': {'functional': {
        'memory_control': {'policy': 'fixed_context', 'checkpoint': base},
        'config_version': 'fixture', 'host': {'model': 'unchanged'}}}})
    study.update(controls=[{'id': 'fixed_context', 'policy': 'fixed_context', 'checkpoint': None},
        {'id': 'rules', 'policy': 'rules', 'checkpoint': None},
        {'id': 'jev_initialization', 'policy': 'laya', 'checkpoint': base}],
        runtime=str(tmp_path / 'runtime'), source_version='native-version',
        config_template=str(template), histories=str(tmp_path / 'histories.json'),
        inference_wrapper='existing_cpu_wrapper.py', positions_per_unique_arm=16,
        execution_id='ordinary-dev-cohort-v1', dispatch_scope='Ordinary development cohort')
    inspected = []
    for index, fit in enumerate(study['fits']):
        inspected.append({**fit, 'status': 'READY', 'selected_point': {
            'update': 0 if index < 2 else 12,
            'checkpoint': base if index < 2 else str(tmp_path / 'different-checkpoint')}})
    host_site = str(tmp_path / 'host packages')
    result = binding.materialize(study, {'status': 'READY', 'fits': inspected}, tmp_path / 'bound',
                                 python='python', attention_wrapper='attention.py',
                                 host_site_packages=host_site)
    assert result['unique_arms'] == 4 and result['planned_positions'] == 64
    initial, = [arm for arm in result['arms'] if arm['id'] == 'jev_initialization']
    assert [a['intervention'] for a in initial['aliases']] == ['head-softce', 'head-set']
    assert all('--continue-host-history' in arm['argv'] for arm in result['arms'])
    assert all(arm['environment']['CUDA_VISIBLE_DEVICES'] == '' for arm in result['arms'])
    assert result['scope'] == study['dispatch_scope']
    assert result['host_site_packages'] == host_site
    for arm in result['arms']:
        assert validate_bound_arm(result, arm['id']) == arm
        assert arm['argv'][-2:] == ['--host-site-packages', host_site]
        assert host_site not in arm['environment']['PYTHONPATH']
        actual = read_json(Path(arm['config']))['entrypoints']['functional']
        assert actual['config_version'] == 'fixture-ordinary-dev-cohort-v1-' + arm['id']
        assert actual['host'] == {'model': 'unchanged'}
