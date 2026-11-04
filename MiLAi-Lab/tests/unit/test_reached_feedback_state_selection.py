"""State selection depends on actual reached decisions, not future answers or missing-slot fill."""
import copy

import pytest

from select_reached_feedback_states import select_parameter_states, select_states


def row(family, step, *, index=0, alias='read'):
    return {'family': family, 'capture': f'{family}/step-{step}', 'step': step,
        'argmax': {'id': alias, 'kind': 'READ', 'target': 'candidate',
                   'parameters': {'index': index}},
        'baseline': {'id': 'baseline', 'kind': 'READ', 'target': 'candidate',
                     'parameters': {'index': 0}}}


def test_priority_uses_first_full_binding_disagreement_not_a_different_action_id():
    rows = [row('a', 0), row('a', 1, alias='another-id'), row('a', 2, index=1),
            row('a', 3, index=2)]
    actual = select_states(rows, ['a'], ['a'], 0)
    assert [x['step'] for x in actual['selected']] == [0, 2]
    assert actual['cells'][0]['post_disagreements'] == 2
    assert actual['selected'][1]['reason'] == 'earliest_actual_argmax_baseline_disagreement'


def test_missing_initial_or_post_is_retained_without_borrowing_another_slot():
    rows = [row('initial-only', 0), row('post-only', 3)]
    actual = select_states(rows, ['initial-only', 'post-only', 'missing'], [], 0)
    assert [(x['family'], x['step']) for x in actual['selected']] == [
        ('initial-only', 0), ('post-only', 3)]
    assert [x['selected'] for x in actual['cells']] == [1, 1, 0]
    assert actual['cells'][0]['missing_post'] and actual['cells'][1]['missing_initial']


def test_family_draw_does_not_change_with_other_family_availability_or_outcome_fields():
    families = ['a', 'b', 'c']
    rows = [row(f, step) for f in families for step in range(5)]
    full = select_states(rows, families, [], 0)
    subset = [copy.deepcopy(r) for r in reversed(rows) if r['family'] == 'b']
    for r in subset:
        r['future_answer_quality'] = 1 if r['step'] == 4 else 0
    one = select_states(subset, families, [], 0)
    assert one['selected'] == [r for r in full['selected'] if r['family'] == 'b']
    assert one['seed_per_family'] == full['seed_per_family']


def test_two_initial_states_for_one_question_are_not_silently_selected():
    rows = [row('a', 0), {**row('a', 0), 'capture': 'another-call'}]
    with pytest.raises(ValueError, match='multiple initial'):
        select_states(rows, ['a'], [], 0)


def test_parameter_selection_requires_actual_material_and_three_bindings_without_slot_fill():
    rows = [row('a', step, index=1) for step in range(5)] + [row('b', 1, index=1)]
    for item in rows:
        item.update(acquired_materials=1, has_parameter_alternative=True)
    rows[1]['acquired_materials'] = 0
    rows[2]['has_parameter_alternative'] = False
    rows[3]['argmax'] = {**rows[3]['baseline'], 'id': 'different-alias'}
    actual = select_parameter_states(rows, ['a', 'b', 'missing'], 0)
    assert [(x['family'], x['step']) for x in actual['selected']] == [('a', 4), ('b', 1)]
    assert [c['shortfall'] for c in actual['cells']] == [1, 1, 2]
    changed = copy.deepcopy(list(reversed(rows)))
    for item in changed:
        item['future_answer_quality'] = 'opposite'
    assert select_parameter_states(changed, ['a', 'b', 'missing'], 0) == actual
