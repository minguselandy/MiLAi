"""Inspect replay loss geometry at existing baseline predictions, without model calls."""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.laya_memory_policy import project_operation_payload


def loss_geometry(logits: dict[str, float], target: dict[str, float]) -> dict[str, Any]:
    keys = list(logits)
    maximum = max(logits.values())
    exp = {key: math.exp(value - maximum) for key, value in logits.items()}
    total = sum(exp.values())
    probability = {key: value / total for key, value in exp.items()}
    accepted = {key for key, value in target.items() if value > 0}
    if not accepted or not accepted <= set(keys):
        raise ValueError('Replay diagnostic needs a nonempty target set inside actual choices')
    positive_max = max(logits[key] for key in accepted)
    positive_sum = sum(math.exp(logits[key] - positive_max) for key in accepted)
    log_z = maximum + math.log(total)
    log_accepted_z = positive_max + math.log(positive_sum)
    ce = sum(value * (log_z - logits[key]) for key, value in target.items() if value)
    ce_gradient = {key: probability[key] * sum(target.values()) - target.get(key, 0)
                   for key in keys}
    set_gradient = {key: probability[key] - (
        math.exp(logits[key] - log_accepted_z) if key in accepted else 0) for key in keys}
    return {'soft_ce': ce, 'set_loss': log_z - log_accepted_z,
        'probabilities': probability, 'accepted_mass': sum(probability[k] for k in accepted),
        'ce_gradient': ce_gradient, 'set_gradient': set_gradient,
        'ce_gradient_l1': sum(map(abs, ce_gradient.values())),
        'set_gradient_l1': sum(map(abs, set_gradient.values())),
        'positive_choices': len(accepted), 'valid_choices': len(keys),
        'positive_targets_uniform': len({target[k] for k in accepted}) == 1}


def analyze(replay_file: Path, teacher: Path, initialization: Path) -> dict[str, Any]:
    run = read_json(teacher / 'run.json')
    if (run['status'] != 'COMPLETED' or run['device'] != 'cpu'
            or run['loaded_weight_dtype'] != 'torch.float32'
            or Path(run['checkpoint']).resolve() != initialization.resolve()):
        raise ValueError('Teacher must be the actual closed saved-CPU common initialization')
    teacher_rows = read_jsonl(Path(run['data']))
    by_id = {(r['metadata']['family'], r['metadata']['event_id']): i
             for i, r in enumerate(teacher_rows)}
    if len(by_id) != len(teacher_rows) or run['completed_states'] != len(teacher_rows):
        raise ValueError('Teacher identities or completed coverage differ')
    records = []
    for training_row, row in enumerate(read_jsonl(replay_file)):
        if 'feedback' in row:
            continue
        identity = row['metadata']['family'], row['metadata']['event_id']
        index = by_id[identity]
        original = teacher_rows[index]
        if any(row[k] != original[k] for k in ('state', 'questions', 'gold')):
            raise ValueError('Replay is not the literal original teacher state/target')
        projected = project_operation_payload(row, run['operation_state'])
        expected = {k: projected[k] for k in ('state', 'questions')}
        actual = read_json(teacher / 'calls' / str(index) / 'input.json')
        if json.dumps(actual, ensure_ascii=False) != json.dumps(expected, ensure_ascii=False):
            raise ValueError('Teacher did not receive this exact projected input')
        prediction = read_json(teacher / 'calls' / str(index) / 'output.json')
        if (prediction['truncated'] or prediction['input_tokens'] > run['max_len']
                or set(prediction['logits']) != set(projected['questions']['next']['criteria'])
                or not all(math.isfinite(v) for v in prediction['logits'].values())):
            raise ValueError('Teacher prediction coverage or complete input is invalid')
        target = row['gold']['next']['probabilities']
        geometry = loss_geometry(prediction['logits'], target)
        choice = prediction['choice']
        records.append({'training_row': training_row, 'teacher_index': index,
            'family': identity[0], 'event_id': identity[1], 'actual_choice': choice,
            'actual_choice_accepted': target.get(choice, 0) > 0,
            'positive_choices': geometry['positive_choices'],
            'valid_choices': geometry['valid_choices'],
            'uniform_positive_targets': geometry['positive_targets_uniform'],
            'choice_probability': geometry['probabilities'][choice],
            'choice_target_probability': target.get(choice, 0),
            'accepted_probability_mass': geometry['accepted_mass'],
            'soft_ce': geometry['soft_ce'], 'set_loss': geometry['set_loss'],
            'ce_choice_gradient': geometry['ce_gradient'][choice],
            'set_choice_gradient': geometry['set_gradient'][choice],
            'ce_gradient_l1': geometry['ce_gradient_l1'],
            'set_gradient_l1': geometry['set_gradient_l1'],
            'probability_rounding_difference': max(abs(
                geometry['probabilities'][key] - prediction['probabilities'][key])
                for key in geometry['probabilities'])})
    multi = [r for r in records if r['positive_choices'] > 1]
    correct_multi = [r for r in multi if r['actual_choice_accepted']]
    subsets = {'all_replay': records, 'multi_positive': multi,
               'correct_multi_positive': correct_multi}
    summary = {}
    for name, rows in subsets.items():
        summary[name] = {'rows': len(rows),
            'unique_teacher_states': len({r['teacher_index'] for r in rows}),
            'families': len({r['family'] for r in rows}),
            'actual_choice_accepted': sum(r['actual_choice_accepted'] for r in rows),
            'ce_pushes_chosen_logit_down_gt_1e_minus_6': sum(
                r['ce_choice_gradient'] > 1e-6 for r in rows),
            'mean_ce_chosen_gradient': sum(r['ce_choice_gradient'] for r in rows) / len(rows),
            'mean_set_chosen_gradient': sum(r['set_choice_gradient'] for r in rows) / len(rows),
            'mean_ce_gradient_l1': sum(r['ce_gradient_l1'] for r in rows) / len(rows),
            'mean_set_gradient_l1': sum(r['set_gradient_l1'] for r in rows) / len(rows),
            'mean_soft_ce': sum(r['soft_ce'] for r in rows) / len(rows),
            'mean_set_loss': sum(r['set_loss'] for r in rows) / len(rows)}
    return {'status': 'CACHED_BASELINE_REPLAY_GEOMETRY_MEASURED;NO_NEW_MODEL_GRADIENTS',
        'replay_file': str(replay_file.resolve()), 'teacher': str(teacher.resolve()),
        'initialization': str(initialization.resolve()), 'teacher_conditions': {
            k: run[k] for k in ('device', 'max_len', 'head_max_len', 'loaded_weight_dtype')},
        'positive_set_sizes': dict(Counter(r['positive_choices'] for r in records)),
        'nonuniform_positive_targets': sum(not r['uniform_positive_targets'] for r in records),
        'all_choices_positive_rows': sum(r['positive_choices'] == r['valid_choices']
                                        for r in records),
        'maximum_probability_rounding_difference': max(r['probability_rounding_difference']
                                                       for r in records),
        'summary': summary, 'rows': records,
        'scope': 'Analytical unweighted logit gradients at actual stored baseline CPU scores. '
            'Inputs/targets bind literally to teacher records. This is not observed parameter '
            'gradient conflict or a causal explanation of all forgetting; actual training uses '
            'shuffled options and evolving weights. Set replay matches accepted-set evaluation, '
            'but must be tested for retention and feedback/Host quality. No model weights loaded.',
        'model_calls': 0, 'ledger_recorded': False, 'no_sha_validation': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('replay_file', type=Path)
    parser.add_argument('teacher', type=Path)
    parser.add_argument('initialization', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    result = analyze(args.replay_file, args.teacher, args.initialization)
    result['cpu_seconds_pending'] = time.process_time() - started
    write_json(args.output / 'analysis.json', result)
    print(result['status'], result['summary'])


if __name__ == '__main__':
    main()
