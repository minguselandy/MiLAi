"""Audit matched Q-direction parameter-scope and accepted-set replay controls."""
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path
from typing import Any

from analyze_feedback_fit import analyze
from analyze_quality_feedback_fit import quality_analysis_plan
from analyze_regularized_feedback_fit import verify_parameter_scope
from milai_lab.harness.artifact_io import read_json, write_json


def optimization_analysis_plan(
    study: dict[str, Any], quality: dict[str, Any], original: dict[str, Any],
) -> dict[str, Any]:
    base = quality_analysis_plan(quality, original)
    baseline, = [p for p in base['plans'] if p['quality_mode'] == 'quality-direction']
    if (study['common_initialization'] != quality['common_initialization']
            or study['base_runtime'] != quality['base_runtime']
            or [p['intervention'] for p in study['plans']]
            != ['full-softce', 'head-softce', 'head-set']):
        raise ValueError('Optimization changed the declared initialization or matched controls')
    plans = []
    for spec in study['plans']:
        argv = list(spec['argv'])
        entry = next(i for i, value in enumerate(argv)
                     if Path(value).name == 'train_bounded_laya.py')
        if (Path(argv[entry]) != Path(study['training_overlay']) / 'train_bounded_laya.py'
                or argv[entry + 3] != spec['output']
                or argv[argv.index('--compute-phase') + 1] != spec['compute_phase']
                or spec['arm'] != 'answer' or spec['source_cohort'] != baseline['source_cohort']
                or spec['cwd'] != baseline['cwd']):
            raise ValueError('Optimization runtime/output binding changed')
        if spec['intervention'].startswith('head-'):
            if argv.count('--freeze-encoder') != 1:
                raise ValueError('Head controls must keep the encoder frozen')
            argv.remove('--freeze-encoder')
        if spec['intervention'] == 'head-set':
            flag = argv.index('--replay-objective')
            if argv.count('--replay-objective') != 1 or argv[flag + 1] != 'set':
                raise ValueError('Set control changed its replay objective')
            del argv[flag:flag + 2]
        argv[entry] = baseline['argv'][entry]
        argv[entry + 3] = baseline['output']
        argv[argv.index('--compute-phase') + 1] = baseline['compute_phase']
        environment = copy.deepcopy(baseline['environment'])
        environment['PYTHONPATH'] = ':'.join((str(Path(study['base_runtime']) / 'src'),
            study['training_overlay'], str(Path(study['base_runtime']) / 'tools')))
        if argv != baseline['argv'] or spec['environment'] != environment:
            raise ValueError('Optimization changed data, supervision, draw budget or loss mass')
        plans.append({**copy.deepcopy(spec), 'quality_mode': 'quality-direction'})
    return {'source_version': base['source_version'] + '+accepted-set-replay-v1',
            'protocol': base['protocol'], 'plans': plans}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', type=Path)
    parser.add_argument('quality_plan', type=Path)
    parser.add_argument('original_plan', type=Path)
    parser.add_argument('run_id')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    study = read_json(args.study)
    plan = optimization_analysis_plan(study, read_json(args.quality_plan),
                                      read_json(args.original_plan))
    spec, = [p for p in plan['plans'] if p['run_id'] == args.run_id]
    result = analyze(plan, args.run_id, quality_mode='quality-direction',
        replay_objective='set' if spec['intervention'] == 'head-set' else None)
    result.update(intervention=spec['intervention'], study=str(args.study.resolve()),
        saved_parameter_scope=verify_parameter_scope(result),
        scope='Matched Q-direction data, draws, family/event weights and initialization. '
              'Full/head comparison changes encoder update scope; head-softce/head-set changes '
              'only replay objective. Native selection remains provisional. Saved inference '
              'device is declared separately in this optimization study; CPU deployment and '
              'Host results cannot be inferred from GPU selection.',
        model_calls=0, ledger_recorded=False, cpu_seconds_pending=time.process_time() - started,
        no_sha_validation=True)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'analysis.json', result)
    print(result['status'], spec['intervention'], result['in_memory_selection'])


if __name__ == '__main__':
    main()
