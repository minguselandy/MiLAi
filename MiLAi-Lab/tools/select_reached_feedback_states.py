"""Select actual initial/post states using recorded decisions, never branch outcomes."""
from __future__ import annotations

import argparse
import random
import time
from pathlib import Path
from typing import Any

from feedback_choices import baseline_choice, captured_decisions
from milai_lab.harness.artifact_io import read_json, write_json
from prepare_e1_choice_branches import binding_equal


def select_states(
    records: list[dict[str, Any]], families: list[str], priority: list[str], seed: int,
) -> dict[str, Any]:
    """One actual step0 and one actual post state; seeded draws are independent per family."""
    if len(set(families)) != len(families) or not set(priority) <= set(families):
        raise ValueError('Fix unique families and a priority subset before collection')
    if any(r['family'] not in families for r in records):
        raise ValueError('Reached states must belong to the declared collection families')
    rng = random.Random(seed)  # noqa: S311 -- declared data-selection seed
    seeds = {family: rng.randrange(2**63) for family in families}
    selected, cells = [], []
    for family in families:
        available = sorted((r for r in records if r['family'] == family),
                           key=lambda r: (r['step'], r['capture']))
        initial = [r for r in available if r['step'] == 0]
        if len(initial) > 1:
            raise ValueError('This one-question-per-family protocol has multiple initial states')
        post = [r for r in available if r['step'] > 0]
        disagreements = [r for r in post if not binding_equal(r['argmax'], r['baseline'])]
        chosen = initial[:]
        reason = 'no_actual_post_state'
        if post:
            if family in priority and disagreements:
                chosen.append(disagreements[0])
                reason = 'earliest_actual_argmax_baseline_disagreement'
            else:
                chosen.append(random.Random(seeds[family]).choice(post))  # noqa: S311
                reason = 'seeded_uniform_actual_post'
        for r in chosen:
            selected.append({'family': family, 'capture': r['capture'], 'step': r['step'],
                'reason': 'actual_initial_step0' if r['step'] == 0 else reason})
        cells.append({'family': family, 'initial_available': len(initial),
            'post_available': len(post), 'post_disagreements': len(disagreements),
            'selected': len(chosen), 'missing_initial': not initial, 'missing_post': not post,
            'post_seed': seeds[family], 'post_reason': reason})
    return {'selected': selected, 'cells': cells, 'seed_per_family': seeds}


def recorded_inventory(collection: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conditions, decisions = captured_decisions(collection)
    rows = []
    for capture, decision in decisions.items():
        call = decision['call']
        actions = {a['id']: a for a in call['initial_actions']}
        rows.append({'family': decision['row']['metadata']['family'], 'capture': capture,
            'step': call.get('control_step', 0),
            'argmax': actions[decision['prediction']['choice']],
            'baseline': actions[baseline_choice(call, 'fixed_prefix', 4)],
            'raw_context': actions[baseline_choice(call, 'raw_context', 4)]})
    return conditions, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('collection', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    start = time.process_time()
    plan = read_json(args.plan)
    histories = read_json(args.collection/'fixture.json')['histories']
    families = [h['source_group'] for h in histories]
    if (any(h['split'] != 'train' or len(h['requests']) != 1 for h in histories)
            or families != [f for f in plan['families'] if f in families]):
        raise ValueError('Keep the declared TRAIN family order and one original question each')
    conditions, records = recorded_inventory(args.collection)
    if (plan['collector_checkpoint'] is None
            or Path(conditions['checkpoint']).resolve()
            != Path(plan['collector_checkpoint']).resolve()
            or conditions['operation_state'] != 'shared_actions'):
        raise ValueError('Selection requires the bound collector and its actual full-menu scores')
    # Keep all56 family seeds fixed even when this is one8/48 segment.
    chosen = select_states(records, plan['families'],
                           plan['disagreement_priority_post_families'], 0)
    chosen['cells'] = [c for c in chosen['cells'] if c['family'] in families]
    write_json(args.output, {'status': 'ACTUAL_REACHED_STATE_SELECTION_NO_OUTCOME_LABELS',
        'plan': str(args.plan.resolve()), 'collection': str(args.collection.resolve()),
        'conditions': conditions, 'families_in_segment': families, **chosen,
        'candidate_inventory': records, 'model_calls': 0, 'new_training_labels': 0,
        'ledger_recorded': False, 'cpu_seconds_nested': time.process_time()-start,
        'no_sha_validation': True,
        'scope': 'At most initial/post per family. Priority families use the earliest actual '
            'complete-binding disagreement; others use the predeclared family seed. Missing '
            'states are not filled, repeated/unknown states are not scored as negatives, and '
            'branch outcomes are never used to choose states.'})
    print('selected', len(chosen['selected']), 'actual states from', len(families), 'families')


if __name__ == '__main__':
    main()
