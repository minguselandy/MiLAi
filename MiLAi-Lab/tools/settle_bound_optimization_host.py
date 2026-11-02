"""Reverify one closed Host arm and settle only explicit disjoint local CPU."""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from run_bound_optimization_host import active_model_owners, local_cpu_accounting
from summarize_optimization_host import summarize_cohort


def verify_closed_arm(dispatch_path: Path, arm_id: str) -> dict[str, Any]:
    dispatch = read_json(dispatch_path)
    arm, = [a for a in dispatch['arms'] if a['id'] == arm_id]
    owner = dispatch_path.parent / 'orchestration' / arm_id
    driver = read_json(owner / 'driver.json')
    if (driver['status'] not in {'COMPLETED', 'COMPLETED_WITH_NATIVE_FAILURES_RETAINED',
                                'FAILED_RETAINED'}
            or Path(driver['dispatch']).resolve() != dispatch_path.resolve()
            or driver['execution_id'] != dispatch['study']['execution_id']
            or driver['arm_id'] != arm_id
            or any(driver[key] != arm[key] for key in ('output', 'argv', 'environment'))
            or any(Path('/proc', str(driver[key])).exists() for key in ('pid', 'child_pid'))):
        raise ValueError('Host owner must be closed and bound to this actual arm')
    before, after = (read_json(owner / name)
                     for name in ('budget-before.json', 'budget-after.json'))
    actual = local_cpu_accounting(before, after, driver['whole_child_cpu_seconds'])
    if any(driver[key] != value for key, value in actual.items() if key != 'scope'):
        raise ValueError('Recorded Host residual differs from its actual cost boundaries')
    config = read_json(Path(arm['config']))
    ledger = Path(config['entrypoints']['functional']['budget_path'])
    if read_json(ledger) != after:
        raise ValueError('Settle this arm before subsequent ledger changes')
    root = Path(arm['output'])
    if (root / 'driver.json').exists() and any(
            read_json(root / name) != value
            for name, value in [('budget-before.json', before), ('budget-after.json', after)]):
        raise ValueError('Native Host budget boundaries differ from its coordinator')
    summary = summarize_cohort(dispatch, [])
    summarized, = [a for a in summary['arms'] if a['arm_id'] == arm_id]
    if driver['status'] != 'FAILED_RETAINED':
        native = read_json(root / 'driver.json')
        expected = ('COMPLETED' if driver['status'] == 'COMPLETED'
                    else 'COMPLETED_WITH_FAILURES')
        if (driver['exit_code'] != 0 or native['status'] != expected
                or len(native['completed']) != dispatch['study']['positions_per_unique_arm']
                or summarized['inference_condition_status'] not in {
                    'VERIFIED_LOADED_SCORERS', 'NO_SCORER_LOADED'}):
            raise ValueError('Completed owner lacks its full native and inference closure')
    return {'driver': str(owner / 'driver.json'), 'ledger': str(ledger), 'ledger_after': after,
            'owner_status': driver['status'], 'reconciled_local_cpu': actual,
            'summary_status': summary['status'], 'arm_summary': summarized,
            'scope': 'Actual tasks, runtime, output and cost boundaries rechecked. Failed attempts '
                     'and unknown quality remain retained; this is not a semantic review.'}


def settle(
    dispatch_path: Path, arm_id: str, inventory_path: Path, output: Path, phase: str,
) -> dict[str, Any]:
    started = time.process_time()
    if active_model_owners():
        raise ValueError('No model may be active during offline Host settlement')
    if output.exists():
        raise ValueError('Existing settlement is retained; never settle it twice')
    verified = verify_closed_arm(dispatch_path, arm_id)
    inventory = read_json(inventory_path)
    entries = copy.deepcopy(
        inventory['accounting']['pending_disjoint_entries_excluding_this_progress'])
    entries.extend([{'file': str(inventory_path.resolve()),
                     'field': 'accounting.progress_processing_cpu_pending'},
                    {'file': verified['driver'], 'field': 'child_cpu_pending'},
                    {'file': verified['driver'], 'field': 'orchestration_cpu_seconds_pending'}])
    optimization = Path(read_json(dispatch_path)['study']['optimization_study']).parent
    if output.parent.resolve() != optimization.resolve() or 'settlement' not in output.name:
        raise ValueError('Keep settlement receipts in the existing optimization settlement index')
    records = [*optimization.parent.glob('original-feedback-v2-*settlement*.json'),
               *optimization.glob('*settlement*.json'),
               *(optimization.parent / 'continued-controls-dev-v2').glob('*settlement*.json')]
    prior = {(str(Path(e['file']).resolve()), e['field'])
             for record in records for e in read_json(record).get('entries', [])}
    keys = [(str(Path(e['file']).resolve()), e['field']) for e in entries]
    if len(keys) != len(set(keys)) or prior.intersection(keys):
        raise ValueError('Repeated or previously settled CPU field')
    for entry in entries:
        value = read_json(Path(entry['file']))
        for key in entry['field'].split('.'):
            value = value[int(key)] if isinstance(value, list) else value[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Every CPU charge needs an explicit finite nonnegative measurement')
        entry['cpu_seconds'] = value
    ledger_before = verified.pop('ledger_after')
    if phase in ledger_before.get('compute', {}):
        raise ValueError('Settlement phase already exists in the original ledger')
    cpu = time.process_time() - started
    entries.append({'file': str(output.resolve()), 'field': 'verification_processing_cpu_seconds',
                    'cpu_seconds': cpu})
    measures = {'cpu_seconds': sum(e['cpu_seconds'] for e in entries),
                'measured_phases': len(entries), 'runs': 1}
    expected = copy.deepcopy(ledger_before)
    expected.setdefault('compute', {})[phase] = measures
    ledger = Path(verified['ledger'])
    # Recheck immediately before the one write; the verified native delta is not charged again.
    if active_model_owners() or read_json(ledger) != ledger_before:
        raise ValueError('Model activity or ledger boundary changed before settlement')
    RunBudget(RunLimits(**ledger_before['limits']), ledger).record_compute(phase, measures)
    if read_json(ledger) != expected:
        raise ValueError('Settlement changed more than the declared CPU phase')
    report = {'status': 'CLOSED_HOST_ARM_CPU_SETTLED_ONCE',
              'dispatch': str(dispatch_path.resolve()),
              'arm_id': arm_id, 'phase': phase, 'verification': verified, 'entries': entries,
              'measures': measures, 'verification_processing_cpu_seconds': cpu,
              'only_expected_compute_delta': True, 'model_calls': 0, 'no_sha_validation': True,
              'scope': 'Native HTTP/local-scorer costs and nested driver/message/wrapper CPU '
                       'are not rebilled. Explicit inventory plus residual/coordinator and this '
                       'verification CPU are counted once. Unmeasured overhead remains unknown.'}
    with output.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dispatch', type=Path)
    parser.add_argument('arm_id')
    parser.add_argument('inventory', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('phase')
    args = parser.parse_args()
    result = settle(args.dispatch, args.arm_id, args.inventory, args.output, args.phase)
    print(result['status'], result['arm_id'], result['measures'])


if __name__ == '__main__':
    main()
