"""CPU differences must be reported without changing the selected GPU checkpoint."""
import copy
from pathlib import Path

import pytest
from test_saved_cuda_protocol import add_cuda_measurement
from test_saved_feedback_fit import emit_job, prediction
from test_saved_quality_fit import quality_fixture

from analyze_saved_feedback_fit import select
from confirm_saved_feedback_cpu import confirm, confirmation_plan
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_feedback import score_feedback


def controls(tmp_path):
    cpu, native = quality_fixture(tmp_path)
    job = cpu['common_base']
    job['argv'] = ['python', 'evaluate_bounded_laya.py', job['data'], job['checkpoint'],
                   job['output'], '--compute-phase', job['phase']]
    gpu = copy.deepcopy(cpu)
    gpu['conditions'].update(device='cuda:0', visible_cuda_devices='2')
    for job in [gpu['common_base'], *gpu['fits'][0]['candidates'][1:],
                *gpu['fits'][0]['conditional_retention_jobs']]:
        job.update(job_id='gpu-' + job['job_id'], phase='gpu-' + job['phase'],
                   output=str(tmp_path / ('gpu-' + Path(job['output']).name)))
        emit_job(gpu, native, job)
        add_cuda_measurement(gpu, job)
    gpu['fits'][0]['candidates'][0]['shared_job'] = gpu['common_base']['job_id']
    return gpu, cpu, native


def replace_choice(job, index, prefer_read):
    root = Path(job['output'])
    previous = read_json(root / 'calls' / str(index) / 'output.json')
    write_json(root / 'calls' / str(index) / 'output.json',
               prediction({'sequence_tokens': previous['input_tokens']}, prefer_read))
    rows = read_jsonl(Path(job['data']))
    predictions = [read_json(root / 'calls' / str(i) / 'output.json') for i in range(len(rows))]
    write_json(root / 'results.json', {t: score_feedback(rows, predictions, t)
                                      for t in ('answer', 'delivery')})


def test_cpu_old_skill_change_is_reported_without_reselection(tmp_path):
    gpu, cpu, native = controls(tmp_path)
    selected = select(gpu, native)
    assert selected['deployment_selection']['answer']['update'] == 2
    output = tmp_path / 'confirmation'
    plan = confirmation_plan(gpu, cpu, selected, output)
    assert plan['job']['argv'][3:5] == [plan['job']['checkpoint'], plan['job']['output']]
    assert not plan['reuse_original_cpu_base']
    emit_job(cpu, native, plan['job'])
    replace_choice(plan['job'], 0, True)
    result = confirm(gpu, cpu, native, selected, plan, output)
    assert result['GPU_selected_point']['update'] == 2
    assert result['old_operation_CPU_minus_GPU'] == 1
    assert result['choice_changes'] == [{'combined_index': 0,
                                        'gpu_choice': 'stop', 'cpu_choice': 'read'}]
    changed = copy.deepcopy(plan)
    changed['job']['checkpoint'] = native['curve'][-1]['checkpoint']
    with pytest.raises(ValueError, match='selected checkpoint or conditions'):
        confirm(gpu, cpu, native, selected, changed, output)


def test_selected_zero_reuses_actual_cpu_base_even_when_cpu_quality_differs(tmp_path):
    gpu, cpu, native = controls(tmp_path)
    replace_choice(gpu['common_base'], 3, False)
    selected = select(gpu, native)
    assert selected['deployment_selection']['answer']['update'] == 0
    output = tmp_path / 'confirmation'
    plan = confirmation_plan(gpu, cpu, selected, output)
    assert plan['reuse_original_cpu_base']
    assert plan['job']['output'] == cpu['common_base']['output']
    assert not output.exists()  # This reuse requires no new model execution.
    result = confirm(gpu, cpu, native, selected, plan, output)
    assert result['GPU_selected_point']['update'] == 0
    assert len(result['choice_changes']) == 1
    assert result['choice_changes'][0]['combined_index'] == 3
    assert result['CPU_quality_partitions'] != result['GPU_quality_partitions']
