import copy
import json
from pathlib import Path

import pytest
from test_original_feedback_host import bound_fixture, completed_arm

from milai_lab.harness.artifact_io import read_json, write_json
from summarize_optimization_host import summarize_cohort
from summarize_original_feedback_host import rendered_task, summarize


def source_review(arm, path, result, request='first'):
    return {'arm_id': arm['id'], 'history': 'family-0', 'request': request,
            'result_path': str(path), 'answer': result['final_answer'], 'grade': 'correct',
            'rationale': 'Mechanical fixture with an exact source binding.',
            'source_refs': [['source', 'fact-0', 'user']]}


def test_independent_bank_and_per_request_sources_are_bound_without_prefix_leakage(tmp_path):
    dispatch = bound_fixture(tmp_path)
    fixture_path = Path(dispatch['study']['histories'])
    fixture = read_json(fixture_path)
    history = fixture['histories'][0]
    history['continuous'] = False
    history['requests'][0]['sources'] = [{'session_id': 'doc', 'event_key': 'd',
        'role': 'tool', 'origin': 'reference_document', 'content': 'The value is 0.'}]
    write_json(fixture_path, fixture)
    arm = dispatch['arms'][0]
    path = completed_arm(dispatch, arm)
    result = read_json(path)
    result['bank'] = 'family-0-first'
    write_json(path, result)
    review = source_review(arm, path, result)
    review['source_refs'] = [['doc', 'd', 'tool']]
    summary = summarize(dispatch, [review])
    assert summary['positions'][0]['bank'] == 'family-0-first'
    assert summary['positions'][0]['confirmed_task_success']
    later = path.parent.parent / 'later-bank/later-result.json'
    later_result = {**result, 'bank': 'family-0-later', 'message_id': 'later'}
    write_json(later, later_result)
    stale = source_review(arm, later, later_result, 'later')
    with pytest.raises(ValueError, match='available at this prefix'):
        summarize(dispatch, [review, stale])


def test_prefetch_support_requires_literal_final_provider_input_and_unicode_records(tmp_path):
    dispatch = bound_fixture(tmp_path)
    fixture_path = Path(dispatch['study']['histories'])
    fixture = read_json(fixture_path)
    request = fixture['histories'][0]['requests'][0]
    request['provide_prefetch'] = True
    write_json(fixture_path, fixture)
    arm = dispatch['arms'][0]
    path = completed_arm(dispatch, arm)
    setup = {'prefetch': {'ok': True, 'evidence': [{'text': 'The value is 0.\u2028Literal text.'}]}}
    write_json(path.parent / 'retrieval-setup.json', setup)
    result = read_json(path)
    result.update(content=rendered_task(request, setup), attempt=0)
    result['messages'][0]['content'] = result['content']
    result['messages'][-1]['id'] = 'final'
    write_json(path, result)
    event = {'event': 'vllm_response', 'receipt': {'id': 'final'},
             'request': {'messages': [{'role': 'user', 'content': result['content']}]}}
    trace = path.with_name('first-trace-0.jsonl')
    trace.write_text(json.dumps(event, ensure_ascii=False) + '\n')
    review = source_review(arm, path, result)
    review['delivery'] = {'grade': 'sufficient',
                          'rationale': 'Actual declared prefetch is visible.',
                          'visible_tool_receipts': []}
    with pytest.raises(ValueError, match='prefetch receipts'):
        summarize(dispatch, [review])
    visible = [{'request': 'first', 'receipt': setup['prefetch']}]
    review['delivery']['visible_prefetch_receipts'] = visible
    row = summarize(dispatch, [review])['positions'][0]
    assert row['visible_prefetch_receipts'] == visible and row['tool_attempts'] == 0
    event['request']['messages'][0]['content'] = request['content']
    trace.write_text(json.dumps(event, ensure_ascii=False) + '\n')
    with pytest.raises(ValueError, match='prefetch receipts'):
        summarize(dispatch, [review])


def test_reference_compatibility_does_not_promote_unknown_semantic_quality(tmp_path):
    dispatch = bound_fixture(tmp_path)
    fixture_path = Path(dispatch['study']['histories'])
    fixture = read_json(fixture_path)
    fixture['histories'][0]['requests'][0]['id'] = 'corpus-7'
    write_json(fixture_path, fixture)
    arm = dispatch['arms'][0]
    path = completed_arm(dispatch, arm)
    driver_path = Path(arm['output']) / 'driver.json'
    driver = read_json(driver_path)
    driver['completed'][0]['request'] = 'corpus-7'
    write_json(driver_path, driver)
    result = read_json(path)
    result['message_id'] = 'corpus-7'
    write_json(path, result)
    references = tmp_path / 'references.json'
    write_json(references, {'cases': [{'family': 'family-0', 'source_row': 7,
                                      'native_reference_answer': '0'}]})
    dispatch['status'] = 'OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED'
    dispatch['study'].update(positions_per_unique_arm=16, execution_id='ordinary-dev',
        dispatch_scope='Ordinary development questions', task_conditions={'prefetch': False},
        native_reference_review=str(references))
    review = source_review(arm, path, result, 'corpus-7')
    review.update(grade='unknown', source_refs=[], reference_relation={
        'grade': 'compatible', 'native_reference_answer': '0',
        'rationale': 'Conclusion agrees with reference; provenance remains unresolved.'})
    row = summarize_cohort(dispatch, [review])['positions'][0]
    assert row['reference_relation'] == 'compatible' and row['semantic_grade'] == 'unknown'
    assert not row['confirmed_task_success']
    changed = copy.deepcopy(review)
    changed['reference_relation']['native_reference_answer'] = '1'
    with pytest.raises(ValueError, match='frozen native reference'):
        summarize_cohort(dispatch, [changed])
