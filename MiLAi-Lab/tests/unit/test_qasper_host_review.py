"""Actual provider visibility, not hidden Store content or source identity guesses, feeds review."""
import copy
import json

import pytest

from milai_lab.harness.artifact_io import write_json
from prepare_qasper_host_review import prepare, visible_original_ranges


def inputs():
    source = {'original_event_id': 'paper/paragraph', 'role': 'tool',
              'origin': 'reference_document', 'content': 'The code is 4312.'}
    question = {'id': 'q', 'content': 'What is the code?'}
    history = {'id': 'paper', 'source_group': 'f', 'continuous': False,
               'sources': [source], 'requests': [question]}
    references = {'cases': [{'family': 'f', 'history': 'paper', 'request': question,
                            'native_control': {'native_question_id': 'native-q'}}]}
    return {'histories': [history]}, references, source


def receipt(source):
    return {'role': 'tool', 'name': 'milai_retrieve', 'tool_call_id': 'call',
        'content': json.dumps({'schema': 'milai_retrieval_result_v1', 'ok': True,
            'evidence': [{'kind': 'original_source', 'label': 'e0', 'evidence': [{
                'content': source['content'][4:8], 'range': [4,8],
                'source_characters': len(source['content']), 'role': source['role'],
                'origin': source['origin'], 'source': 's0'}]}]})}


@pytest.mark.parametrize('filename', ['q-result.json', 'q-attempt-0.json'])
def test_only_actual_final_input_support_is_bound_and_duplicate_sources_stay_distinct(
    tmp_path, filename,
):
    fixture, refs, source = inputs()
    fixture['histories'][0]['sources'].append({**source, 'original_event_id': 'paper/duplicate'})
    path = tmp_path / filename
    result = {'status': 'COMPLETED', 'attempt': 0, 'bank': 'paper-q', 'message_id': 'q',
        'content': 'What is the code?', 'final_answer': '4312',
        'messages': [{'type': 'human'}, {'type': 'ai', 'id': 'final', 'content': '4312'}]}
    write_json(path, result)
    wire = [{'role': 'user', 'content': result['content']}, receipt(source)]
    (tmp_path / 'q-trace-0.jsonl').write_text(json.dumps({
        'event': 'vllm_response', 'receipt': {'id': 'final'}, 'request': {'messages': wire}})+'\n')
    report = prepare(fixture, refs, {'f': str(path)})
    r = report['records'][0]
    assert r['quality_labels'] is None and r['answer'] == '4312'
    assert r['material_binding']['visible_original_ranges'][0]['original_source_candidates'] == [
        'paper/paragraph', 'paper/duplicate']
    # Store/source availability does not turn into visible Tool evidence.
    wire.pop()
    (tmp_path / 'q-trace-0.jsonl').write_text(json.dumps({
        'event': 'vllm_response', 'receipt': {'id': 'final'}, 'request': {'messages': wire}})+'\n')
    report = prepare(fixture, refs, {'f': str(path)})
    assert report['records'][0]['material_binding']['visible_original_ranges'] == []


def test_first_attempt_input_does_not_follow_a_later_canonical_result(tmp_path):
    fixture, refs, source = inputs()
    first = {'status': 'COMPLETED', 'attempt': 0, 'bank': 'paper-q', 'message_id': 'q',
        'content': 'What is the code?', 'final_answer': 'first answer',
        'messages': [{'type': 'human'}, {'type': 'ai', 'id': 'first', 'content': 'first answer'}]}
    path = tmp_path / 'q-attempt-0.json'
    write_json(path, first)
    later = {**first, 'attempt': 1, 'final_answer': 'later answer',
             'messages': [{'type': 'human'}, {'type': 'ai', 'id': 'later'}]}
    write_json(tmp_path / 'q-result.json', later)
    first_wire = [{'role': 'user', 'content': first['content']}, receipt(source)]
    for attempt, response, wire in [(0, 'first', first_wire), (1, 'later', [])]:
        (tmp_path / f'q-trace-{attempt}.jsonl').write_text(json.dumps({
            'event': 'vllm_response', 'receipt': {'id': response},
            'request': {'messages': wire}})+'\n')
    actual = prepare(fixture, refs, {'f': str(path)})['records'][0]
    assert actual['answer'] == 'first answer'
    assert actual['actual_final_provider_messages'] == first_wire
    assert actual['final_host_input']['final_message_id'] == 'first'


def test_mismatched_source_fragments_and_tool_errors_are_retained_without_grades():
    _, _, source = inputs()
    item = receipt(source)
    changed = copy.deepcopy(source)
    changed['content'] = 'A different source'
    error = {'role': 'tool', 'name': 'milai_retrieve', 'content': 'Tool failed: invalid query'}
    report = visible_original_ranges([item, error], [changed])
    assert report['unmatched_ranges'] == 1 and report['literal_matched_ranges'] == 0
    assert report['visible_retrieval_receipts'][1]['status'] == 'NON_JSON_TOOL_MESSAGE_RETAINED'


def test_failed_missing_and_wrong_task_results_do_not_invent_final_visibility(tmp_path):
    fixture, refs, _ = inputs()
    report = prepare(fixture, refs, {'f': None})
    assert report['planned_families'] == 1 and report['bound_final_inputs'] == 0
    path = tmp_path / 'q-result.json'
    failed = {'status': 'FAILED', 'bank': 'paper-q', 'message_id': 'q',
              'content': 'What is the code?', 'sources': fixture['histories'][0]['sources']}
    write_json(path, failed)
    report = prepare(fixture, refs, {'f': str(path)})
    assert report['records'][0]['material_binding'] is None
    failed['content'] = 'Another question'
    write_json(path, failed)
    with pytest.raises(ValueError, match='another bank or public task'):
        prepare(fixture, refs, {'f': str(path)})
    with pytest.raises(ValueError, match='every declared source'):
        prepare(fixture, refs, {})
    failed['content'] = 'What is the code?'
    failed['host_request_generated'] = False
    write_json(path, failed)
    with pytest.raises(ValueError, match='not autonomous Host'):
        prepare(fixture, refs, {'f': str(path)})
