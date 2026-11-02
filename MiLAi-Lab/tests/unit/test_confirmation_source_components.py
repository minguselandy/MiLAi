import json

from audit_confirmation_source_components import audit, components, summarize_components


def test_excluded_bridge_and_reserved_members_stay_in_components():
    graph = components({'a': {'ab'}, 'b': {'ab', 'bc'}, 'c': {'bc'}, 'd': {'d'}})
    metadata = {f: {'question_ids': [f], 'rows': [i],
                   'violations': ['exposed'] if f == 'b' else []}
                for i, f in enumerate('abcd')}
    result = summarize_components(graph, metadata, {'c'})
    assert result['components'] == 2
    assert result['components_without_recorded_conflict_or_prior_reservation'] == 1
    assert result['groups'][0]['families'] == ['a', 'b', 'c']
    assert result['groups'][0]['violations'] == ['exposed']
    assert result['groups'][0]['prior_reserved_families'] == ['c']


def fixture_protocol(tmp_path):
    groups = [{'family': f, 'rows': [i], 'question_ids': [f], 'violations': []}
              for i, f in enumerate(('a', 'b', 'c'))]
    rows = [{'id': f, 'question': 'PRIVATE QUESTION', 'answer': 'PRIVATE ANSWER',
             'paragraphs': [{'title': 'shared page' if f != 'c' else '',
                             'paragraph_text': f'PRIVATE BODY {f}', 'is_supporting': True}]}
            for f in ('a', 'b', 'c')]
    files = {'prior_boundary': {'groups': groups}, 'prior_reservation': {'groups': []},
        'histories': {'histories': [{'id': 'h', 'source_group': 'train-family', 'split': 'train',
            'sources': [], 'requests': [{'sources': [{'origin': 'reference_document',
                'content': 'shared page\nPRIVATE BODY a'}],
                'incoming_sources': [{'content': 'UNRELATED BODY'}]}]}]}}
    for name, value in files.items():
        (tmp_path / f'{name}.json').write_text(json.dumps(value))
    candidate = tmp_path / 'candidate.jsonl'
    candidate.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return {'prior_boundary': str(tmp_path / 'prior_boundary.json'),
            'prior_reservation': str(tmp_path / 'prior_reservation.json'),
            'candidate_source': str(candidate),
            'public_histories': [str(tmp_path / 'histories.json')]}, rows


def test_literal_and_page_dependencies_differ_without_outputting_private_content(tmp_path):
    protocol, _ = fixture_protocol(tmp_path)
    result = audit(protocol)
    assert result['literal_pool']['components'] == 3
    assert result['page_title_pool']['components'] == 2
    assert result['families_overlapping_current_public_bodies'] == 1
    assert result['families_overlapping_current_public_page_titles'] == 2
    assert result['empty_candidate_title_occurrences'] == 1
    assert result['literal_pool']['components_without_recorded_conflict_or_prior_reservation'] == 2
    count_key = 'components_without_recorded_conflict_or_prior_reservation'
    assert result['page_title_pool'][count_key] == 1
    assert all(s not in json.dumps(result) for s in (
        'PRIVATE QUESTION', 'PRIVATE ANSWER', 'PRIVATE BODY', 'UNRELATED BODY'))
    assert 'shared page' not in json.dumps(result)


def test_answers_and_question_text_cannot_affect_component_census(tmp_path):
    protocol, rows = fixture_protocol(tmp_path)
    before = audit(protocol)
    for row in rows:
        row['question'] = 'CHANGED QUESTION'
        row['answer'] = 'CHANGED ANSWER'
    (tmp_path / 'candidate.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    assert audit(protocol) == before


def test_background_link_is_separate_from_native_target_in_another_pool(tmp_path):
    protocol, rows = fixture_protocol(tmp_path)
    rows[1]['paragraphs'] = [dict(rows[0]['paragraphs'][0], is_supporting=False)]
    path = tmp_path / 'candidate.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = audit(protocol)
    assert result['target_to_pool']['components'] == 2
    assert result['literal_pool']['components'] == 2
    rows[0]['paragraphs'][0]['is_supporting'] = False
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = audit(protocol)
    assert result['target_to_pool']['components'] == 3
    assert result['literal_pool']['components'] == 2


def test_public_background_match_is_not_a_native_target_violation(tmp_path):
    protocol, rows = fixture_protocol(tmp_path)
    rows[0]['paragraphs'][0]['is_supporting'] = False
    (tmp_path / 'candidate.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = audit(protocol)
    assert result['families_overlapping_current_public_bodies'] == 1
    assert result['families_with_native_targets_in_current_public_bodies'] == 0
    key = 'components_without_recorded_conflict_or_prior_reservation'
    assert result['target_to_pool'][key] == 3
    assert result['target_to_pool_any_public_overlap_sensitivity'][key] == 2
