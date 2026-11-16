import copy

import pytest
from test_quality_fit_audit import closed_quality_fit, plans_for_adapter

from analyze_feedback_fit import analyze
from analyze_replay_optimized_feedback_fit import optimization_analysis_plan
from milai_lab.harness.artifact_io import read_json, write_json


def study_plans():
    quality, original = plans_for_adapter()
    original['plans'][0]['argv'].extend(['--replay-weight', '.25'])
    for spec in quality['plans']:
        spec['argv'].extend(['--replay-weight', '.25'])
    study = {'base_runtime': quality['base_runtime'],
        'common_initialization': quality['common_initialization'],
        'training_overlay': '/optimization', 'plans': []}
    for intervention in ('full-softce', 'head-softce', 'head-set'):
        spec = copy.deepcopy(quality['plans'][0])
        spec.update(run_id=intervention, arm='answer', intervention=intervention,
                    output='/output/' + intervention, compute_phase=intervention)
        spec['argv'][1] = '/optimization/train_bounded_laya.py'
        spec['argv'][4] = spec['output']
        spec['argv'][spec['argv'].index('--compute-phase') + 1] = spec['compute_phase']
        spec['environment']['PYTHONPATH'] = '/frozen/base/src:/optimization:/frozen/base/tools'
        if intervention.startswith('head-'):
            spec['argv'].append('--freeze-encoder')
        if intervention == 'head-set':
            spec['argv'].extend(['--replay-objective', 'set'])
        study['plans'].append(spec)
    return study, quality, original


def test_optimization_keeps_matched_data_weights_draws_and_original_plans():
    study, quality, original = study_plans()
    before = copy.deepcopy((study, quality, original))
    plan = optimization_analysis_plan(study, quality, original)
    assert len(plan['plans']) == 3
    assert all(p['quality_mode'] == 'quality-direction' for p in plan['plans'])
    assert (study, quality, original) == before


@pytest.mark.parametrize('change', ['weight', 'updates', 'unfreeze', 'objective', 'extra'])
def test_optimization_does_not_hide_an_extra_intervention(change):
    study, quality, original = study_plans()
    argv = study['plans'][2]['argv']
    if change == 'weight':
        argv[argv.index('--replay-weight') + 1] = '1.0'
    elif change == 'updates':
        argv[argv.index('--optimizer-updates') + 1] = '24'
    elif change == 'unfreeze':
        argv.remove('--freeze-encoder')
    elif change == 'objective':
        argv[-1] = 'soft-ce'
    else:
        argv.extend(['--pair-label-smoothing', '.05'])
    with pytest.raises(ValueError):
        optimization_analysis_plan(study, quality, original)


def test_native_set_replay_is_declared_and_bound_to_saved_checkpoint_metadata(tmp_path):
    plan, root = closed_quality_fit(tmp_path, 'quality-direction')
    plan['plans'][0]['argv'].extend(['--replay-objective', 'set'])
    run = read_json(root / 'run.json')
    run['replay_objective'] = 'set'
    write_json(root / 'run.json', run)
    for path in (root / 'checkpoints/update-1/rl_agent_config.json',
                 root / 'checkpoint/rl_agent_config.json'):
        config = read_json(path)
        config['training']['milai_reader']['replay_objective'] = 'set'
        write_json(path, config)
    with pytest.raises(ValueError, match='declared optimization audit'):
        analyze(plan, 'unit', quality_mode='quality-direction')
    result = analyze(plan, 'unit', quality_mode='quality-direction', replay_objective='set')
    assert result['recipe']['replay_objective'] == 'set'
    path = root / 'checkpoints/update-1/rl_agent_config.json'
    config = read_json(path)
    config['training']['milai_reader']['replay_objective'] = 'soft-ce'
    write_json(path, config)
    with pytest.raises(ValueError, match='checkpoint metadata'):
        analyze(plan, 'unit', quality_mode='quality-direction', replay_objective='set')
