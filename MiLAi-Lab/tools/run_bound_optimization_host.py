"""Own one verified Host arm, preserving failures and measured disjoint local CPU."""
from __future__ import annotations

import argparse
import math
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from bind_optimization_retention_host import inspect_bindings
from milai_lab.harness.artifact_io import read_json, write_json

MODEL_ENTRIES = {
    'train_bounded_laya.py', 'evaluate_bounded_laya.py', 'run_frozen_retrieval_calls.py',
    'run_view_feedback_branches.py', 'run_host_intent_retrieval.py', 'run_retrieval_factorial.py',
    'run_frozen_host_message.py', 'run_known_budget_request.py', 'run_host_saved_cpu.py',
    'run_lme_predictions.py', 'score_lme_predictions.py', 'run_bound_optimization_host.py',
}


def active_model_owners(proc_root: Path = Path('/proc')) -> list[int]:
    active = []
    for process in proc_root.iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().decode().split('\0')
        except (FileNotFoundError, ProcessLookupError):
            continue
        if argv and 'python' in Path(argv[0]).name and any(
                Path(value).name in MODEL_ENTRIES for value in argv[1:]):
            active.append(int(process.name))
    return active


def local_cpu_accounting(
    before: dict[str, Any], after: dict[str, Any], whole_child_cpu: float,
) -> dict[str, Any]:
    """The frozen runtime records only local Laya load/predict CPU for these arms."""
    if before['limits'] != after['limits']:
        raise ValueError('Host execution changed the original budget limits')
    phases = {'dynamic_memory_laya_load', 'dynamic_memory_laya'}
    recorded = {}
    for name in before.get('compute', {}).keys() | after.get('compute', {}).keys():
        a = before.get('compute', {}).get(name, {}).get('cpu_seconds', 0)
        z = after.get('compute', {}).get(name, {}).get('cpu_seconds', 0)
        change = z - a
        if not math.isfinite(change) or change < 0 or (change and name not in phases):
            raise ValueError('Unexpected CPU ledger delta needs reconciliation before settlement')
        if change:
            recorded[name] = change
    pending = whole_child_cpu - sum(recorded.values())
    if not math.isfinite(pending) or pending < 0:
        raise ValueError('Recorded local CPU exceeds the measured whole child; do not clamp it')
    return {'known_local_CPU_already_recorded': recorded,
            'whole_child_cpu_seconds': whole_child_cpu, 'child_cpu_pending': pending,
            'scope': 'Known local scorer load/predict CPU is deducted once from the whole client '
                     'process CPU. HTTP token/unknown-usage accounting remains in the original '
                     'ledger. Remote hardware CPU is not measured here. Missing historic counters '
                     'do not establish zero historical cost.'}


def validate_bound_arm(dispatch: dict[str, Any], arm_id: str) -> dict[str, Any]:
    if (dispatch['status'] != 'OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED'
            or dispatch['bindings']['status'] != 'READY'
            or len(dispatch['bindings']['fits']) != 3):
        raise ValueError('Only a fully bound three-method optimization Host study may dispatch')
    arm, = [arm for arm in dispatch['arms'] if arm['id'] == arm_id]
    study = dispatch['study']
    argv = arm['argv']
    expected_entry = Path(study['runtime']) / 'tools/run_host_intent_retrieval.py'
    entry = argv.index(str(expected_entry))
    if (argv[entry + 1:entry + 4] != [arm['config'], study['histories'], arm['output']]
            or argv[argv.index('--policies') + 1] != arm['policy']
            or argv[argv.index('--interfaces') + 1] != 'rich'
            or argv[argv.index('--split') + 1] != 'dev'
            or '--continue-host-history' not in argv
            or any(flag in argv for flag in ['--given-requests', '--native-probe'])
            or arm['environment']['CUDA_VISIBLE_DEVICES'] != ''):
        raise ValueError('Bound Host command changed its task, policy or inference protocol')
    if Path(arm['output']).exists() or Path(arm['output'] + '-inference.json').exists():
        raise ValueError('Existing Host attempts are retained; this dispatcher never retries')
    return cast(dict[str, Any], arm)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dispatch', type=Path)
    parser.add_argument('arm_id')
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    started, cpu_started = time.perf_counter(), time.process_time()
    active = active_model_owners()
    if active:
        raise ValueError(f'Another model job is still alive: {active}')
    dispatch = read_json(args.dispatch)
    if 'continuation' in dispatch:
        from prepare_optimization_host_continuation import validate_continuation

        validate_continuation(args.dispatch, for_launch=True)
    arm = validate_bound_arm(dispatch, args.arm_id)
    study = dispatch['study']
    optimization_file = Path(study['optimization_study'])
    verified = inspect_bindings(study, read_json(optimization_file),
        read_json(Path(study['gpu_plan'])), read_json(Path(study['original_cpu_plan'])),
        optimization_file.parent)
    if verified != dispatch['bindings']:
        raise ValueError('Actual GPU/CPU bindings changed after Host configuration was frozen')
    config = read_json(Path(arm['config']))
    ledger = Path(config['entrypoints']['functional']['budget_path'])
    before = read_json(ledger)
    args.receipt.mkdir(parents=True, exist_ok=False)
    write_json(args.receipt / 'budget-before.json', before)
    driver_path = args.receipt / 'driver.json'
    report = {'status': 'LAUNCHING', 'pid': os.getpid(), 'dispatch': str(args.dispatch.resolve()),
        'execution_id': study['execution_id'], 'arm_id': args.arm_id, 'output': arm['output'],
        'argv': arm['argv'], 'environment': arm['environment'], 'automatic_retry': False,
        'planned_positions': study['positions_per_unique_arm'], 'ledger_recorded': False}
    write_json(driver_path, report)
    usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        with (args.receipt / 'host.log').open('x') as stream:
            child = subprocess.Popen(  # noqa: S603 -- verified frozen local interpreter/entry/args
                arm['argv'], cwd=arm['cwd'], env={**os.environ, **arm['environment']},
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            report.update(status='RUNNING', child_pid=child.pid, started_epoch=time.time())
            write_json(driver_path, report)
            print('STARTED', study['execution_id'], args.arm_id, os.getpid(), child.pid, flush=True)
            code = child.wait()
        report['exit_code'] = code
        after = read_json(ledger)
        write_json(args.receipt / 'budget-after.json', after)
        usage1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        whole = usage1.ru_utime + usage1.ru_stime - usage0.ru_utime - usage0.ru_stime
        report['whole_child_cpu_seconds'] = whole
        report.update(local_cpu_accounting(before, after, whole))
        native_path = Path(arm['output']) / 'driver.json'
        native = read_json(native_path) if native_path.exists() else None
        inference_path = Path(arm['output'] + '-inference.json')
        inference = read_json(inference_path) if inference_path.exists() else None
        report.update(native_status=native['status'] if native is not None else None,
                      inference_status=inference['status'] if inference is not None else None)
        if code == 0:
            if (native is None or inference is None
                    or native['status'] not in {'COMPLETED', 'COMPLETED_WITH_FAILURES'}
                    or inference['status'] != 'COMPLETED'
                    or len(native['completed']) != study['positions_per_unique_arm']
                    or read_json(Path(arm['output']) / 'budget-before.json') != before
                    or read_json(Path(arm['output']) / 'budget-after.json') != after):
                raise ValueError('Host closure or native cost boundaries do not match its owner')
            report['status'] = ('COMPLETED' if native['status'] == 'COMPLETED'
                                else 'COMPLETED_WITH_NATIVE_FAILURES_RETAINED')
        else:
            report['status'] = 'FAILED_RETAINED'
        print(report['status'], study['execution_id'], args.arm_id, flush=True)
    except BaseException as error:
        report.update(status='FAILED_RETAINED', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
                      orchestration_cpu_seconds_pending=time.process_time() - cpu_started,
                      scope='One actual Host arm only. Native worker owns model costs; this '
                            'coordinator never settles the ledger or launches another arm. '
                            'Whole-driver, message and inference-wrapper CPU are nested, not '
                            'additional charges. Actual semantic reviews remain separate.')
        write_json(driver_path, report)


if __name__ == '__main__':
    main()
