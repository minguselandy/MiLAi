import copy
import json

from prepare_two_wiki_evaluation_sources import (
    boundary_issues,
    choose,
    native_panel,
    visible_dev,
)


def row(identity, title, background='shared background'):
    return {'_id': identity, 'question': 'question ' + identity, 'answer': 'ANSWER SENTINEL',
            'context': [[title, ['literal first.', 'literal second.']],
                        [background, ['background text.']]],
            'supporting_facts': [[title, 0]], 'evidences': ['NATIVE EVIDENCE SENTINEL']}


def candidate(family, index, native, members=None):
    return {'family': family, 'source_rows': [index],
            'whole_family_rows': members if members is not None else [index],
            'question_id': native[index]['_id'], 'native_support_titles': 2}


def protocol(excluded=()):
    return {'old_excluded_families': list(excluded), 'role_order': ['dev', 'confirmation'],
            'stratum_order': ['2'], 'quotas': {'dev': {'2': 1}, 'confirmation': {'2': 1}}}


def test_background_reuse_is_not_target_conflict():
    first, second = native_panel([row('a', 'A')]), native_panel([row('b', 'B')])
    assert first['pool'] & second['pool']
    assert boundary_issues(first, {'second': second}) == []
    second['target'].add(('shared background', 'background text.'))
    second['target_titles'].add('shared background')
    issues = boundary_issues(first, {'second': second})
    assert issues[0]['counts']['right_target_in_left_pool'] == 1
    assert 'background text.' not in json.dumps(issues)


def test_unselected_family_member_still_protects_the_boundary():
    native = [row('a', 'A'), row('b', 'OLD'), row('c', 'C')]
    order = {'2': [candidate('first', 0, native, [0, 1]), candidate('second', 2, native)]}
    selected, rejected, _ = choose(
        protocol(), order, native, {'old': native_panel([row('old', 'OLD')])}, set(), set())
    assert [x['family'] for x in selected] == ['second']
    assert rejected[0]['family'] == 'first'
    assert selected[0]['split'] == 'dev'


def test_old_roles_and_new_disjoint_roles_are_preserved():
    native = [row('old', 'OLD'), row('a', 'A'), row('b', 'B')]
    order = {'2': [candidate('old-family', 0, native), candidate('a', 1, native),
                   candidate('b', 2, native)]}
    selected, rejected, _ = choose(protocol(['old-family']), order, native, {}, set(), set())
    assert [(x['family'], x['split']) for x in selected] == [('a', 'dev'), ('b', 'confirmation')]
    assert not rejected
    assert all(not x['gradient_training_allowed'] for x in selected)
    assert all(x['original_split'] == 'train' for x in selected)


def test_later_target_in_earlier_background_is_rejected_without_backfill():
    native = [row('a', 'A', background='B'), row('b', 'B')]
    order = {'2': [candidate('a', 0, native), candidate('b', 1, native)]}
    selected, rejected, _ = choose(protocol(), order, native, {}, set(), set())
    assert len(selected) == 1
    assert selected[0]['split'] == 'dev'
    assert rejected[0]['issues'][0]['panel'] == 'earlier_new_families'


def test_confirmation_and_native_answer_content_never_enter_dev_export():
    native = [row('a', 'A'), row('confirmation-id', 'CONFIRMATION BODY SENTINEL')]
    order = {'2': [candidate('a', 0, native), candidate('b', 1, native)]}
    selected, _, _ = choose(protocol(), order, native, {}, set(), set())
    views = visible_dev(selected, native)
    serialized = json.dumps(views)
    assert len(views) == 1
    assert all(value not in serialized for value in (
        'ANSWER SENTINEL', 'NATIVE EVIDENCE SENTINEL', 'confirmation-id',
        'CONFIRMATION BODY SENTINEL', 'supporting_facts'))
    assert views[0]['paragraphs'][0]['paragraph_text'] == 'literal first. literal second.'


def test_native_answers_do_not_affect_selection_or_public_target_boundary():
    native = [row('a', 'A'), row('b', 'B')]
    order = {'2': [candidate('a', 0, native), candidate('b', 1, native)]}
    before = choose(protocol(), order, native, {}, set(), {'A'})
    changed = copy.deepcopy(native)
    for item in changed:
        item['answer'] = 'DIFFERENT ANSWER'
        item['evidences'] = ['DIFFERENT NATIVE ANSWER RELATION']
    assert choose(protocol(), order, changed, {}, set(), {'A'}) == before
    assert before[1][0]['issues'][0]['panel'] == 'current_public_sources'
