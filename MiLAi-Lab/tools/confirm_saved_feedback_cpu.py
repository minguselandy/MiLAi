"""Confirm the GPU-selected feedback checkpoint on CPU without selecting again."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from analyze_feedback_fit import feedback_partitions
from analyze_saved_feedback_fit import inputs_for_fit, select, verify_job, verify_retention
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control_learning import score_operation_predictions
from quality_feedback import score_quality_feedback


def confirmation_plan(
    gpu: dict[str, Any], original_cpu: dict[str, Any], selection: dict[str, Any], output: Path,
) -> dict[str, Any]:
    """Bind one selected checkpoint; update zero reuses the actual original CPU base."""
    if (selection['status'] != 'SAVED_GPU_QUALITY_SELECTION_VERIFIED'
            or set(selection['deployment_selection']) != {'answer'}
            or original_cpu['conditions']['device'] != 'cpu'
            or gpu['inputs'] != original_cpu['inputs']
            or gpu['original_ledger'] != original_cpu['original_ledger']):
        raise ValueError('CPU confirmation requires the declared GPU selection and common inputs')
    point = selection['deployment_selection']['answer']
    job = copy.deepcopy(original_cpu['common_base'])
    job['update'] = point['update']
    reuse = point['update'] == 0
    if reuse:
        if job['checkpoint'] != point['checkpoint']:
            raise ValueError('Selected zero differs from the original common initialization')
    else:
        job.update(job_id=f"{selection['run_id']}/cpu-selected-{point['update']}",
            checkpoint=point['checkpoint'],
            output=str(output / selection['run_id'] / 'evaluation'),
            phase='evidence_gap_training_opt_cpu_confirmation_'
                  + selection['run_id'].replace('-', '_'))
        entry = next(i for i, value in enumerate(job['argv'])
                     if Path(value).name == 'evaluate_bounded_laya.py')
        job['argv'][entry + 2:entry + 4] = [job['checkpoint'], job['output']]
        job['argv'][job['argv'].index('--compute-phase') + 1] = job['phase']
    return {'run_id': selection['run_id'], 'conditions': original_cpu['conditions'],
        'original_ledger': original_cpu['original_ledger'], 'job': job,
        'GPU_selected_point': copy.deepcopy(point), 'reuse_original_cpu_base': reuse,
        'scope': 'One GPU-selected checkpoint on CPU; no best-CPU claim or CPU reselection.'}


def confirm(
    gpu: dict[str, Any], original_cpu: dict[str, Any], native: dict[str, Any],
    selection: dict[str, Any], plan: dict[str, Any], output: Path,
) -> dict[str, Any]:
    """Recheck selection, retention, literal inputs, actual CPU outputs and recorded costs."""
    actual = select(gpu, native)
    if actual['deployment_selection'] != selection['deployment_selection']:
        raise ValueError('GPU selection changed before CPU confirmation')
    verify_retention(gpu, native, actual)
    if plan != confirmation_plan(gpu, original_cpu, actual, output):
        raise ValueError('CPU job differs from the verified selected checkpoint or conditions')
    context = inputs_for_fit(gpu, native)
    old, feedback, lengths = (context[k] for k in ('old', 'feedback', 'lengths'))
    job = plan['job']
    checkpoint = Path(job['checkpoint'])
    cpu_predictions, compute = verify_job(plan, job, [*old, *feedback],
        [*lengths['dev'], *lengths['feedback-dev']], checkpoint)
    update = plan['GPU_selected_point']['update']
    fit = context['fit']
    candidate = (gpu['common_base'] if update == 0 else
                 next(j for j in fit['candidates'] if j['update'] == update))
    combined = update in (0, native['recipe']['planned_optimizer_updates'])
    gpu_predictions, _ = verify_job(gpu, candidate,
        [*old, *feedback] if combined else feedback,
        [*lengths['dev'], *lengths['feedback-dev']] if combined else lengths['feedback-dev'],
        checkpoint)
    if not combined:
        old_job, = [j for j in fit['conditional_retention_jobs'] if j['update'] == update]
        old_predictions, _ = verify_job(gpu, old_job, old, lengths['dev'], checkpoint)
        gpu_predictions = [*old_predictions, *gpu_predictions]
    pairs = zip(gpu_predictions, cpu_predictions, strict=True)
    changes = [{'combined_index': i, 'gpu_choice': before['choice'], 'cpu_choice': after['choice']}
               for i, (before, after) in enumerate(pairs)
               if before['choice'] != after['choice']]
    cpu_old = score_operation_predictions(old, cpu_predictions[:len(old)])
    gpu_old = score_operation_predictions(old, gpu_predictions[:len(old)])
    return {'status': 'GPU_SELECTED_CHECKPOINT_CPU_CONFIRMED;HOST_EVALUATION_PENDING',
        'run_id': native['run_id'], 'GPU_selected_point': plan['GPU_selected_point'],
        'CPU_conditions': plan['conditions'], 'CPU_old_operation': cpu_old,
        'GPU_old_operation': gpu_old,
        'old_operation_CPU_minus_GPU': cpu_old['family_macro_acceptance']
                                      - gpu_old['family_macro_acceptance'],
        'CPU_quality_partitions': feedback_partitions(feedback, cpu_predictions[len(old):],
            context['legacy_ids'], score_quality_feedback),
        'GPU_quality_partitions': feedback_partitions(feedback, gpu_predictions[len(old):],
            context['legacy_ids'], score_quality_feedback),
        'choice_changes': changes, 'states': len(cpu_predictions),
        'reuse_original_cpu_base': plan['reuse_original_cpu_base'],
        'native_compute_already_recorded': compute,
        'scope': 'The GPU-selected checkpoint is unchanged. CPU differences remain observed '
                 'results; no CPU reselection, full-set equivalence or Host benefit is inferred.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'verify'))
    parser.add_argument('gpu_plan', type=Path)
    parser.add_argument('original_cpu_plan', type=Path)
    parser.add_argument('native_analysis', type=Path)
    parser.add_argument('selection', type=Path)
    parser.add_argument('output_root', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    gpu, cpu, native, selection = map(read_json, (
        args.gpu_plan, args.original_cpu_plan, args.native_analysis, args.selection))
    target = args.output_root / native['run_id']
    if args.mode == 'prepare':
        actual = select(gpu, native)
        if actual['deployment_selection'] != selection['deployment_selection']:
            raise ValueError('GPU selection changed before CPU job preparation')
        verify_retention(gpu, native, actual)
        plan = confirmation_plan(gpu, cpu, actual, args.output_root)
        target.mkdir(parents=True, exist_ok=False)
        write_json(target / 'plan.json', plan)
        result = {'status': 'CPU_CONFIRMATION_BOUND_TO_ACTUAL_GPU_SELECTION',
                  'plan': str(target / 'plan.json'),
                  'reuse_original_cpu_base': plan['reuse_original_cpu_base']}
        name = 'preparation.json'
    else:
        result = confirm(gpu, cpu, native, selection, read_json(target / 'plan.json'),
                         args.output_root)
        name = 'confirmation.json'
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
                  model_calls=0, no_sha_validation=True)
    with (target / name).open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(result['status'])


if __name__ == '__main__':
    main()
