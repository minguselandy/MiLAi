"""Feed exact reached-state selections into the existing current-decision branch preparer."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from feedback_choices import baseline_choice, coverage_alternative, parameter_stratum
from milai_lab.harness.artifact_io import read_json, write_json
from prepare_e1_choice_branches import binding_equal


def declared_alternative(record: dict[str, Any], mode: str, *,
                         coverage: Counter[str] | None = None,
                         seed: int = 0) -> tuple[dict[str, Any] | None, str]:
    """A real acquired-material delivery choice, otherwise the original context alternative."""
    if mode not in {'fixed_context', 'acquired_raw_delivery', 'parameter_coverage'}:
        raise ValueError('Unknown declared reached-state alternative protocol')
    first_two = (record['argmax'], record['baseline'])
    if mode == 'parameter_coverage':
        call = read_json(Path(record['capture'])/'call.json')
        action = coverage_alternative(call, first_two, coverage or Counter(), seed)
        return action, 'Seeded undercovered legal READ/HANDOFF parameters; outcomes not consulted'
    if mode == 'acquired_raw_delivery':
        call = read_json(Path(record['capture'])/'call.json')
        state = call['initial_observation']
        if state['visible_evidence'] or state.get('observed_evidence'):
            selected = baseline_choice(call, 'raw_delivery', 4)
            action, = [a for a in call['initial_actions'] if a['id'] == selected]
            parameters = action['parameters']
            delivered = (state['visible_evidence'] if not parameters else
                         parameters.get('delivery_indices') or
                         parameters.get('retrieved_scope_indices'))
            if delivered and not any(binding_equal(action, prior) for prior in first_two):
                return action, 'Existing raw-delivery HANDOFF from actually acquired material'
    action = record['raw_context']
    if not any(binding_equal(action, prior) for prior in first_two):
        return action, 'Declared existing fixed_context4 alternative, distinct full binding'
    return None, 'No distinct meaningful declared alternative; do not pad the action pool'


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    start=time.process_time()
    selection=read_json(args.selection)
    if selection['status']!='ACTUAL_REACHED_STATE_SELECTION_NO_OUTCOME_LABELS':
        raise ValueError('Use a selection bound to actual recorded full-menu decisions')
    plan=read_json(Path(selection['plan']))
    alternative_mode=plan.get('branch_alternative','fixed_context')
    collection=Path(selection['collection'])
    inventory={r['capture']:r for r in selection['candidate_inventory']}
    if args.output.exists():
        raise FileExistsError(args.output)
    inputs=args.output.with_name(args.output.name+'-inputs')
    inputs.mkdir(parents=True,exist_ok=False)
    includes=[]
    bindings={}
    coverage=Counter(plan.get('branch_parameter_coverage', {}))
    for index, chosen in enumerate(selection['selected']):
        record=inventory[chosen['capture']]
        name='--'.join(Path(chosen['capture']).relative_to(
            collection/'frozen-retrieval-calls').parts)
        includes.append(name)
        for action in (record['argmax'], record['baseline']):
            coverage[parameter_stratum(action)] += 1
        alternate,reason=declared_alternative(record,alternative_mode,
                                             coverage=coverage, seed=index)
        if alternate is not None:
            coverage[parameter_stratum(alternate)] += 1
            bindings[name]={'actions':[alternate['id']],
                'reason':reason}
    write_json(inputs/'bindings.json',bindings)
    argv=[sys.executable,str(Path(__file__).with_name('prepare_view_feedback_branches.py')),
        str(collection),'--groups',*selection['families_in_segment'],
        '--split','train','--seed','0','--include-control-steps',
        '--branch-sampling','current-decision',
        '--decision-collection',str(collection),'--decision-baseline','fixed_prefix',
        '--decision-baseline-reads','4','--continuation-steps','2',
        '--bindings',str(inputs/'bindings.json'),'--output',str(args.output)]
    if selection.get('state_selection') == 'acquired_parameter_support':
        argv.extend(['--exact-nominations', '--per-group', '2'])
    else:
        argv.extend(['--state-quotas', plan['state_quotas']])
    for name in includes:
        argv.extend(['--include',name])
    with (inputs/'preparation.log').open('x') as log:
        subprocess.run(argv,check=True,stdout=log,stderr=subprocess.STDOUT)  # noqa: S603
    result=read_json(args.output/'selection.json')
    expected={r['capture'] for r in selection['selected']}
    actual={str(Path(r['path']).resolve()) for r in result['selected']}
    if expected!=actual:
        raise ValueError('Branch preparation changed the exact selected actual states')
    nominations={r['capture']:r for r in result['decision_nominations']}
    policies=read_json(args.output/'policies.json')
    comparable=[p for p in policies if nominations[p['capture']]['has_comparison']]
    write_json(args.output/'comparison-policies.json',comparable)
    write_json(args.output/'comparison-execution-plan.json',{
        'status':'REACHED_STATE_COMPARISONS_PREPARED_NOT_EXECUTED',
        'source_selection':str(args.selection.resolve()),'preparer_argv':argv,
        'branch_alternative_protocol':alternative_mode,
        'nominated_parameter_coverage':dict(coverage),
        'selected_actual_states':len(expected),'all_nominated_bindings':len(policies),
        'comparison_bindings':len(comparable),
        'comparison_states':sum(r['has_comparison'] for r in nominations.values()),
        'singleton_states':[r for r in result['decision_nominations'] if not r['has_comparison']],
        'missing_cells':[c for c in selection['cells']
                         if c['missing_initial'] or c['missing_post']],
        'scope':'All selected state coverage remains. Execute only states with an actual '
            'current-policy/baseline/declared-context comparison; singleton outcomes are not '
            'invented ties and distant final answers are not borrowed for early states.',
        'model_calls':0,'new_training_labels':0,'ledger_recorded':False,
        'cpu_seconds_nested':time.process_time()-start,'no_sha_validation':True})
    print('states',len(expected),'comparison bindings',len(comparable))


if __name__=='__main__':
    main()
