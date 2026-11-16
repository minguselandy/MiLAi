import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_saved_feedback_fit import emit_job, fixture
from test_saved_quality_fit import quality_fixture

import evaluate_bounded_laya
from analyze_saved_feedback_fit import select, verify_retention
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


@pytest.mark.parametrize('failure', [False, True])
def test_cuda_evaluator_records_device_wall_without_claiming_active_kernel_time(
    tmp_path, monkeypatch, failure,
):
    torch = pytest.importorskip('torch')
    events = []
    for name in ('set_device', 'set_per_process_memory_fraction',
                 'reset_peak_memory_stats', 'synchronize'):
        monkeypatch.setattr(torch.cuda, name, lambda *args, name=name: events.append((name, args)))
    monkeypatch.setattr(torch.cuda, 'max_memory_allocated', lambda _: 1024)
    monkeypatch.setattr(torch.cuda, 'max_memory_reserved', lambda _: 2048)
    monkeypatch.setattr(torch.backends.cuda.matmul, 'allow_tf32', True)
    monkeypatch.setattr(torch.backends.cudnn, 'allow_tf32', True)
    row = {'state': {'task': {'retrieval_request': {'query': 'q'}}},
           'questions': {'next': {'type': 'choice', 'criteria': {'a': 'READ'}}},
           'gold': {'next': {'probabilities': {'a': 1.}}},
           'metadata': {'family': 'f', 'label_status': 'reviewed', 'action_kinds': {'a': 'READ'}}}
    data, budget, output = tmp_path / 'data.jsonl', tmp_path / 'budget.json', tmp_path / 'out'
    data.write_text(json.dumps(row) + '\n')
    budget.write_text(json.dumps(RunBudget(RunLimits(), budget).state))

    class StubDecision:
        def __init__(self, checkpoint, max_len, head_max_len, device):
            assert device == 'cuda:0'
            self.model = SimpleNamespace(
                parameters=lambda: iter([SimpleNamespace(dtype=torch.float32)]),
                encoder=SimpleNamespace(config=SimpleNamespace(reference_compile=True)))
            self.counters = {'forwards': 0, 'sequence_rows': 0, 'input_tokens': 0}

        def predict(self, payload):
            assert not self.model.encoder.config.reference_compile
            if failure:
                raise RuntimeError('original prediction failure')
            self.counters.update(forwards=1, sequence_rows=1, input_tokens=10)
            return {'choice': 'a', 'input_tokens': 10}

    monkeypatch.setattr(evaluate_bounded_laya, 'NativeDecision', StubDecision)
    monkeypatch.setattr(sys, 'argv', ['evaluate', str(data), str(tmp_path / 'checkpoint'),
        str(output), '--budget', str(budget), '--task', 'memory_operation', '--device', 'cuda:0',
        '--disable-reference-compile', '--operation-state', 'shared',
        '--compute-phase', 'test_gpu'])
    if failure:
        with pytest.raises(RuntimeError, match='original prediction failure'):
            evaluate_bounded_laya.main()
    else:
        evaluate_bounded_laya.main()
    run = json.loads((output / 'run.json').read_text())
    compute = json.loads((output / 'compute.json').read_text())
    recorded = json.loads(budget.read_text())['compute']['test_gpu']
    assert run['status'] == ('FAILED' if failure else 'COMPLETED')
    assert 0 <= compute['cuda_job_wall_seconds'] <= compute['wall_seconds']
    assert recorded['cuda_job_wall_seconds'] == compute['cuda_job_wall_seconds']
    assert compute['peak_cuda_allocated_bytes'] == 1024
    assert 'peak_cuda_allocated_bytes' not in recorded
    assert 'not active-kernel time' in run['cuda_time_scope']
    assert run.get('cuda_synchronized_completion', False) is (not failure)
    assert any(name == 'synchronize' for name, _ in events) is (not failure)
    assert not torch.cuda.is_initialized()  # All CUDA functions above are stubs.


def gpu_fixture(tmp_path):
    plan, native = fixture(tmp_path)
    plan['conditions'].update(device='cuda:0', visible_cuda_devices='2')
    for job in [plan['common_base'], *plan['fits'][0]['candidates'][1:]]:
        emit_job(plan, native, job)
        add_cuda_measurement(plan, job)
    return plan, native


def add_cuda_measurement(plan, job):
    root = Path(job['output'])
    run = json.loads((root / 'run.json').read_text())
    run['cuda_synchronized_completion'] = True
    (root / 'run.json').write_text(json.dumps(run))
    compute = json.loads((root / 'compute.json').read_text())
    compute.update(cuda_job_wall_seconds=.9, peak_cuda_allocated_bytes=1024,
                   peak_cuda_reserved_bytes=2048)
    (root / 'compute.json').write_text(json.dumps(compute))
    ledger = json.loads(Path(plan['original_ledger']).read_text())
    ledger['compute'][job['phase']]['cuda_job_wall_seconds'] = .9
    Path(plan['original_ledger']).write_text(json.dumps(ledger))


def test_gpu_selection_and_retention_are_explicitly_gpu_not_cpu(tmp_path):
    plan, native = gpu_fixture(tmp_path)
    selected = select(plan, native)
    assert selected['status'] == 'SAVED_GPU_FEEDBACK_SELECTION_VERIFIED'
    assert selected['conditions']['device'] == 'cuda:0'
    assert 'in_memory_gpu_vs_saved_gpu_choice_changes' in selected['curve'][1]
    job = plan['fits'][0]['conditional_retention_jobs'][0]
    emit_job(plan, native, job)
    add_cuda_measurement(plan, job)
    closed = verify_retention(plan, native, selected)
    assert closed['status'].startswith('SAVED_GPU_SELECTION_AND_RETENTION_VERIFIED')
    assert closed['deployment_selection'] == selected['deployment_selection']


def test_gpu_quality_selection_preserves_the_quality_rule_and_replay_identity(tmp_path):
    plan, native = quality_fixture(tmp_path)
    plan['conditions'].update(device='cuda:0', visible_cuda_devices='2')
    fit = plan['fits'][0]
    native['recipe']['replay_objective'] = fit['replay_objective'] = 'set'
    path = Path(native['recipe']['output']) / 'run.json'
    run = json.loads(path.read_text())
    run['replay_objective'] = 'set'
    path.write_text(json.dumps(run))
    for job in [plan['common_base'], *fit['candidates'][1:]]:
        emit_job(plan, native, job)
        add_cuda_measurement(plan, job)
    selected = select(plan, native)
    assert selected['status'] == 'SAVED_GPU_QUALITY_SELECTION_VERIFIED'
    assert selected['deployment_selection']['answer']['update'] == 2
    assert selected['replay_objective'] == 'set'
    fit['replay_objective'] = 'soft-ce'
    with pytest.raises(ValueError, match='replay objective'):
        select(plan, native)


@pytest.mark.parametrize('broken', ['synchronization', 'timing', 'ledger'])
def test_gpu_protocol_rejects_missing_actual_device_accounting(tmp_path, broken):
    plan, native = gpu_fixture(tmp_path)
    job = plan['fits'][0]['candidates'][1]
    if broken == 'synchronization':
        path, key = Path(job['output']) / 'run.json', 'cuda_synchronized_completion'
        value = json.loads(path.read_text())
        del value[key]
    elif broken == 'timing':
        path = Path(job['output']) / 'compute.json'
        value = json.loads(path.read_text())
        del value['cuda_job_wall_seconds']
    else:
        path = Path(plan['original_ledger'])
        value = json.loads(path.read_text())
        value['compute'][job['phase']]['cuda_job_wall_seconds'] += 1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        select(plan, native)
