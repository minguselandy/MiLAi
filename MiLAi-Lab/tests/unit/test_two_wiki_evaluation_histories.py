import copy

import pytest

from prepare_two_wiki_evaluation_histories import public_histories


def inputs():
    view = {'family': 'dev-family', 'split': 'dev', 'source_row': 7,
            'question': 'What happened?', 'answer': 'private reference',
            'disposition': 'masked', 'paragraphs': [
                {'idx': 4, 'title': 'Literal title', 'paragraph_text': 'Literal\u2028body',
                 'is_supporting': True}]}
    allocation = {'selection': [
        {'family': 'dev-family', 'split': 'dev', 'source_rows': [7], 'question_id': 'q7'},
        {'family': 'confirmation-family', 'split': 'confirmation',
         'source_rows': [8], 'question_id': 'q8'}]}
    return [view], allocation


def test_ordinary_question_and_complete_literal_sources_without_reference_fields():
    views, allocation = inputs()
    before = copy.deepcopy(views)
    fixture, bindings = public_histories(views, allocation)
    assert views == before
    assert len(fixture['histories']) == 1  # Unknown source support does not drop the task.
    request, = fixture['histories'][0]['requests']
    assert request['content'] == views[0]['question']
    assert set(request) == {'id', 'content', 'sources'}
    source, = request['sources']
    assert source['content'] == 'Literal title\nLiteral\u2028body'
    assert set(source) == {'session_id', 'event_key', 'original_event_id', 'role',
                           'origin', 'occurred_at', 'content'}
    assert bindings[0]['paragraphs'] == [{'original_event_id': 'document-0', 'paragraph_index': 4}]
    assert fixture['gradient_training_allowed'] is False


def test_confirmation_or_changed_source_identity_cannot_enter_dev_fixture():
    views, allocation = inputs()
    views[0]['split'] = 'confirmation'
    with pytest.raises(ValueError, match='identity or evaluation role'):
        public_histories(views, allocation)
    views[0].update(split='dev', source_row=8)
    with pytest.raises(ValueError, match='identity or evaluation role'):
        public_histories(views, allocation)
