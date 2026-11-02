"""Bind declared Host cohorts only to verified GPU selections and CPU confirmations."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from confirm_saved_feedback_cpu import confirm
from milai_lab.harness.artifact_io import read_json, write_json


def inspect_bindings(
    study: dict[str, Any], optimization: dict[str, Any], gpu: dict[str, Any],
    original_cpu: dict[str, Any], optimization_root: Path,
) -> dict[str, Any]:
    specifications = {p['run_id']: p for p in optimization['plans']}
    if ({f['run_id'] for f in study['fits']} != set(specifications)
            or {p['intervention'] for p in specifications.values()}
            != {'full-softce', 'head-softce', 'head-set'}
            or study['inference'] != original_cpu['conditions']
            or optimization['common_initialization'] != original_cpu['common_base']['checkpoint']):
        raise ValueError('Retention diagnostic changed its matched controls or CPU condition')
    rows = []
    for fit in study['fits']:
        spec = specifications[fit['run_id']]
        if fit['intervention'] != spec['intervention']:
            raise ValueError('Retention method identity differs from its trained intervention')
        files = {key: Path(fit[key]) for key in ['selection', 'GPU_retention', 'CPU_confirmation']}
        row = {**fit, 'status': 'PENDING_VERIFIED_GPU_AND_CPU',
               'missing': [key for key, path in files.items() if not path.is_file()]}
        if row['missing']:
            rows.append(row)
            continue
        selected, retained, cpu = (read_json(files[key]) for key in
                                   ['selection', 'GPU_retention', 'CPU_confirmation'])
        if (selected['status'] != 'SAVED_GPU_QUALITY_SELECTION_VERIFIED'
                or retained['status'] != 'SAVED_GPU_QUALITY_SELECTION_AND_RETENTION_VERIFIED;'
                                         'HOST_EVALUATION_PENDING'
                or cpu['status'] != 'GPU_SELECTED_CHECKPOINT_CPU_CONFIRMED;HOST_EVALUATION_PENDING'
                or any(value['run_id'] != fit['run_id'] for value in [selected, retained, cpu])
                or set(selected['deployment_selection']) != {'answer'}
                or selected['deployment_selection'] != retained['deployment_selection']
                or cpu['CPU_conditions'] != study['inference']):
            raise ValueError('Retention Host binding requires this method GPU/CPU closure')
        point = selected['deployment_selection']['answer']
        expected = (Path(optimization['common_initialization']) if point['update'] == 0 else
                    Path(spec['output']) / 'checkpoints' / f"update-{point['update']}")
        if (cpu['GPU_selected_point'] != point
                or Path(point['checkpoint']).resolve() != expected.resolve()
                or not (expected / 'model.safetensors').is_file()):
            raise ValueError('CPU confirmation or checkpoint differs from the actual GPU selection')
        # Reconcile actual inputs, predictions and recorded compute through the existing verifier.
        native = read_json(optimization_root / 'native-audits' / fit['run_id'] / 'analysis.json')
        cpu_root = optimization_root / 'cpu-confirmation'
        actual = confirm(gpu, original_cpu, native, selected,
                         read_json(cpu_root / fit['run_id'] / 'plan.json'), cpu_root)
        if any(cpu[key] != value for key, value in actual.items()):
            raise ValueError('CPU receipt no longer matches the actual confirmed outputs')
        row.update(status='READY', selected_point=point,
                   actual_CPU_output_reverification=True, missing=[])
        rows.append(row)
    return {'status': 'READY' if all(r['status'] == 'READY' for r in rows) else 'PENDING',
            'fits': rows, 'ready_methods': sum(r['status'] == 'READY' for r in rows)}


def materialize(
    study: dict[str, Any], inspection: dict[str, Any], output: Path, *,
    python: str, attention_wrapper: str, host_site_packages: str | None = None,
) -> dict[str, Any]:
    if (inspection['status'] != 'READY' or len(inspection['fits']) != 3
            or any(f['status'] != 'READY' for f in inspection['fits'])):
        raise ValueError('All three optimized GPU/CPU confirmations must close before Host binding')
    arms = copy.deepcopy(study['controls'])
    base, = [arm for arm in arms if arm['id'] == 'jev_initialization']
    by_checkpoint = {str(Path(base['checkpoint']).resolve()): base}
    for arm in arms:
        arm['aliases'] = []
    for fit in inspection['fits']:
        point = fit['selected_point']
        key = str(Path(point['checkpoint']).resolve())
        if key not in by_checkpoint:
            arm = {'id': fit['intervention'] + f"-selected-{point['update']}",
                   'policy': 'laya', 'checkpoint': key, 'aliases': []}
            by_checkpoint[key] = arm
            arms.append(arm)
        by_checkpoint[key]['aliases'].append({
            'run_id': fit['run_id'], 'intervention': fit['intervention'],
            'GPU_selection': fit['selection'], 'CPU_confirmation': fit['CPU_confirmation'],
            'selected_update': point['update']})
    output.mkdir(parents=True, exist_ok=False)
    runtime = Path(study['runtime'])
    for arm in arms:
        config = read_json(Path(study['config_template']))
        settings = config['entrypoints']['functional']
        settings['memory_control']['policy'] = arm['policy']
        if arm.get('checkpoint') is not None:
            settings['memory_control']['checkpoint'] = arm['checkpoint']
        settings['config_version'] += '-' + study['execution_id'] + '-' + arm['id']
        config_path = output / 'configs' / (arm['id'] + '.json')
        write_json(config_path, config)
        destination = output / 'runs' / arm['id']
        arm.update(config=str(config_path), output=str(destination), status='NOT_EXECUTED',
            argv=[python, '-u', attention_wrapper, study['inference_wrapper'],
                  str(destination) + '-inference.json',
                  str(runtime / 'tools/run_host_intent_retrieval.py'),
                  str(config_path), study['histories'], str(destination),
                  '--source-version', study['source_version'], '--policies', arm['policy'],
                  '--interfaces', 'rich', '--split', 'dev', '--continue-host-history',
                  '--capture-control-steps'],
            cwd=str(runtime), environment={
                'PYTHONPATH': str(runtime / 'src') + ':' + str(runtime / 'tools'),
                'CUDA_VISIBLE_DEVICES': '', 'TOKENIZERS_PARALLELISM': 'false',
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if host_site_packages is not None:
            arm['argv'].extend(['--host-site-packages', host_site_packages])
    result = {'status': 'OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED', 'study': study,
        'host_site_packages': host_site_packages,
        'bindings': inspection, 'arms': arms, 'unique_arms': len(arms),
        'planned_positions': len(arms) * study['positions_per_unique_arm'],
        'automatic_retry': False, 'model_calls': 0,
        'scope': study['dispatch_scope']}
    write_json(output / 'dispatch.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'bind'))
    parser.add_argument('study', type=Path)
    parser.add_argument('optimization', type=Path)
    parser.add_argument('gpu_plan', type=Path)
    parser.add_argument('original_cpu_plan', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--python')
    parser.add_argument('--attention-wrapper')
    parser.add_argument('--host-site-packages')
    args = parser.parse_args()
    if args.mode == 'bind' and (args.python is None or args.attention_wrapper is None):
        parser.error('Binding requires the declared interpreter and attention wrapper')
    started = time.process_time()
    study = read_json(args.study)
    result = inspect_bindings(study, read_json(args.optimization), read_json(args.gpu_plan),
                              read_json(args.original_cpu_plan), args.optimization.parent)
    if args.mode == 'bind':
        result = materialize(study, result, args.output,
                             python=args.python, attention_wrapper=args.attention_wrapper,
                             host_site_packages=args.host_site_packages)
        destination = args.output / 'binding.json'
    else:
        destination = args.output
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
                  model_calls=0, no_sha_validation=True)
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(result['status'], 'ready methods',
          result.get('ready_methods', len(result.get('arms', []))))


if __name__ == '__main__':
    main()
