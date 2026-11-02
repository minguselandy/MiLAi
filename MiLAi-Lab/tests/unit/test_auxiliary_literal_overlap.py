import json
import zipfile

import pytest

from audit_auxiliary_source_overlap import LiteralMatcher, audit, strings
from milai_lab.harness.artifact_io import read_json, write_json


def test_literal_matcher_retains_overlaps_suffixes_duplicates_and_unicode():
    patterns = ['ab', 'bc', 'abc', 'b', 'ab', '正文', 'AB', 'a b']
    text = 'zabc 正文 ab'
    assert LiteralMatcher(patterns).matches(text) == {
        i for i, pattern in enumerate(patterns) if pattern in text}
    assert LiteralMatcher(patterns).matches('a b') == {3, 7}
    assert LiteralMatcher([]).matches(text) == set()
    with pytest.raises(ValueError, match='Empty'):
        LiteralMatcher([''])


def test_only_model_visible_values_are_scanned_with_exact_paths():
    row = {'state': {'candidate': {'text': 'a\nb', 'title': '-'}, 'values': ['正文', 1]},
           'questions': {'next': {'criteria': {'read': 'READ'}}},
           'metadata': {'private': 'not input'}, 'gold': {'answer': 'not input'}}
    fields = [*strings(row['state'], 'state'), *strings(row['questions'], 'questions')]
    assert fields == [('state.candidate.text', 'a\nb'), ('state.candidate.title', '-'),
                      ('state.values[0]', '正文'), ('questions.next.criteria.read', 'READ')]


def test_private_audit_uses_complete_literals_and_emits_no_source_text(tmp_path):
    sentence = 'A private source sentence is long enough for a literal comparison.'
    source = {'_id': 'q1', 'question': 'Protected question?',
              'context': [['Private title', [sentence, 'Second sentence.']]],
              'supporting_facts': [['Private title', 0]], 'answer': 'secret answer'}
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('train.json', json.dumps([source]))
    groups, cohort, allocation, review = [tmp_path / (n + '.json') for n in
                                          ('groups', 'cohort', 'allocation', 'review')]
    write_json(groups, [{'family': 'native-1', 'rows': [0]}])
    write_json(cohort, {'archive': str(archive), 'archive_member': 'train.json',
                        'group_metadata': str(groups)})
    write_json(allocation, {'selection': [{'family': 'native-1', 'whole_family_rows': [0],
        'source_rows': [0], 'question_id': 'q1', 'split': 'confirmation'}]})
    write_json(review, {'cases': []})
    data = tmp_path / 'aux.jsonl'
    rows = [{'state': {'candidate': {'title': '-', 'text': text}}, 'questions': {},
             'metadata': {'family': 'aux-1', 'hidden': source['question']},
             'gold': {'hidden': source['context'][0][0]}}
            for text in [sentence, sentence[:32] + ' altered suffix']]
    rows[0]['state']['other'] = 'Literal\u2028content\u0085still one JSONL record'
    data.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    protocol = {'cohort_protocol': str(cohort), 'cohort_allocation': str(allocation),
        'source_review': str(review), 'minimum_sentence_or_reverse_containment_characters': 32,
        'interpretation': 'Literal exposure only', 'privacy': 'No source text',
        'panels': [{'name': 'aux', 'role': 'planned_train', 'input_file': str(data),
                    'expected_rows': 2, 'expected_query_families': 1}]}
    result = audit(protocol, tmp_path / 'out')
    panel = result['panels'][0]
    assert panel['matched_input_rows'] == 1
    assert panel['kind_counts'] == {'native_sentence_containment': 1,
                                     'aux_candidate_containment': 1}
    assert panel['source_roles']['confirmation']['native_support_families'] == 1
    assert not panel['declared_model_output_present']
    artifact = read_json(tmp_path / 'out/aux-matches.json')
    encoded = json.dumps({'report': result, 'details': artifact})
    for secret in [sentence, source['question'], source['answer'], 'Private title']:
        assert secret not in encoded
