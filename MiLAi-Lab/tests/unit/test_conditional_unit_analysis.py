"""Nomination follows label/family balance and retention, never a partial lucky point."""
import pytest

from analyze_conditional_unit_fit import family_balanced_accuracy, nominate, relative_exposure_audit


def row(family, label):
    return {'gold': {} if label is None else {'applicability': {'probabilities': {
        'satisfies': float(label), 'does_not_satisfy': float(not label)}}},
        'metadata': {'family': family}}


def test_negative_multiplicity_and_unknowns_do_not_inflate_balanced_metric():
    rows = [row('a', True), *[row('a', False) for _ in range(99)], row('b', True), row('b', False),
            row('a', None)]
    predictions = [{'choice': 'does_not_satisfy'} for _ in rows]
    actual = family_balanced_accuracy(rows, predictions)
    assert actual['family_macro_balanced_accuracy'] == .5
    assert actual['by_family'] == {'a': .5, 'b': .5}
    predictions[0]['choice'] = 'satisfies'
    assert family_balanced_accuracy(rows, predictions)['family_macro_balanced_accuracy'] == .75


def test_missing_label_is_not_imputed_for_a_family():
    with pytest.raises(ValueError, match='both labels'):
        family_balanced_accuracy([row('a', True)], [{'choice': 'satisfies'}])


def point(update, balanced, retained):
    return {'update': update, 'family_macro_balanced_accuracy': balanced,
            'operation_family_macro_acceptance': retained, 'checkpoint': str(update)}


def test_retention_excludes_best_auxiliary_score_and_ties_use_earliest_point():
    points = [point(0, .6, .9), point(1, .99, .85), point(2, .8, .9), point(3, .8, .9)]
    assert nominate(points, [0, 1, 2, 3]) == points[2]
    assert nominate([point(0, .6, .9), point(1, .99, .85)], [0, 1]) is None


def test_partial_curve_and_nonfinite_metrics_cannot_nominate():
    points = [point(0, .6, .9), point(1, .99, .9)]
    with pytest.raises(ValueError, match='entire'):
        nominate(points, [0, 1, 2])
    with pytest.raises(ValueError, match='finite'):
        nominate([point(0, .6, .9), point(1, float('nan'), .9)], [0, 1])


def relative_fixture():
    rows, pairs = [], []
    for i in range(6):
        family = str(i // 2)
        label = i % 2 == 0 or i >= 4
        item = row(family, label)
        item['metadata'].update(event_id=str(i), query_unit=family, split='train')
        item['state'] = {'candidate': family, 'task': {'retrieval_request': {'query': family}}}
        rows.append(item)
    for i in (0, 2, 4):
        pairs.append({'left_event': str(i), 'right_event': str(i + 1), 'family': str(i // 2),
            'query_unit': str(i // 2), 'left_label': True, 'right_label': i == 4,
            'kind': 'stable' if i == 4 else 'change'})
    stages = [[1, [[(1, i) for i in range(6)]]]]
    records = [{'update': 1, 'data_pass': 1, 'events': [str(i), str(i + 1)], 'direction': 1.,
        'family_weight': 1., 'window_change_pairs': 2, 'relative_loss': loss,
        'optimizer_contribution': .25 * loss / 2} for i, loss in [(0, 2.), (2, 4.)]]
    return rows, pairs, stages, records


def test_relative_audit_excludes_stable_pairs_and_uses_pair_count_not_row_count():
    rows, pairs, stages, records = relative_fixture()
    actual = relative_exposure_audit(rows, pairs, stages, records, .25)
    assert actual['change_pairs'] == actual['actual_pair_draws'] == 2
    assert actual['optimizer_contribution_sum'] == .75


@pytest.mark.parametrize('mutation', ['missing', 'stable', 'direction', 'row_denominator', 'nan'])
def test_relative_audit_rejects_changed_exposure_and_wrong_normalization(mutation):
    rows, pairs, stages, records = relative_fixture()
    if mutation == 'missing':
        records.pop()
    elif mutation == 'stable':
        records[0]['events'] = ['4', '5']
    elif mutation == 'direction':
        records[0]['direction'] = -1
    elif mutation == 'row_denominator':
        records[0]['optimizer_contribution'] /= 3
    else:
        records[0]['relative_loss'] = float('nan')
    with pytest.raises(ValueError, match='Relative loss'):
        relative_exposure_audit(rows, pairs, stages, records, .25)
