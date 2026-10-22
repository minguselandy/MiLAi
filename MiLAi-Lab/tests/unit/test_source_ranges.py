"""Literal range retrieval on real Stores; no generated labels or model calls."""
import json

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import build_evidence_packs, open_evidence_packs
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.source_ranges import SourceRangeBudget, source_range_packs


def character_offsets(text):
    return [(i, i + 1) for i in range(len(text))]


def service_at(store, path):
    return MemoryService(store, ("source-ranges", "alice"), "alice", path / "lock",
                         functional_contract="functional_v1")


def test_unicode_offsets_cover_whitespace_and_repeated_character_token_offsets():
    # A multibyte character can have several token positions with the same offsets.
    def byte_offsets(text):
        return [(i, i + 1) for i, c in enumerate(text) for _ in c.encode()]

    text = ' \t中🙂e\u0301\n"\\\u2028 end  '
    budget = SourceRangeBudget(5, lambda t: len(t.encode()), byte_offsets)
    ranges = budget.ranges(text)
    assert ranges[0][0] == 0 and ranges[-1][1] == len(text)
    assert [left for left, _ in ranges[1:]] == [right for _, right in ranges[:-1]]
    assert ''.join(text[left:right] for left, right in ranges) == text
    assert all(len(text[left:right].encode()) <= 5 for left, right in ranges)
    assert budget.ranges('') == [(0, 0)]


def test_fragment_retokenization_is_counted_and_unrepresentable_character_is_explicit():
    budget = SourceRangeBudget(4, len, lambda t: [(0, len(t))])
    text = 'abcdefghijklmnop'
    spans = budget.ranges(text)
    assert ''.join(text[a:b] for a, b in spans) == text
    assert all(b-a <= 4 for a, b in spans)
    with pytest.raises(ValueError, match='one Unicode character'):
        SourceRangeBudget(1, lambda _: 2, character_offsets).ranges('🙂')


def test_partial_pool_ranges_keep_absolute_offsets_and_adjacent_context(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path/'db')) as store:
        service = service_at(store, tmp_path)
        text = 'prefix' + '0123456789' * 5 + 'suffix'
        ref = service.capture_tool('s', 'one', 'observation', text, None)['source_ref']
        material = service.read_source_materials([{'kind': 'original_source', 'id': 'pool',
            'session_id': 's', 'turn_range': [7, 8], 'source_ranges': [{
                'source_ref': ref, 'source_revision': 1, 'start': 6, 'end': 56}]}])[0]
        packs = source_range_packs(material, SourceRangeBudget(10, len, character_offsets))
        assert len(packs) == 5
        assert [p['source_ranges'][0]['start'] for p in packs] == [6, 16, 26, 36, 46]
        middle = open_evidence_packs(service, [packs[2]], expand_context=True)[0]
        turn, = json.loads(middle['text'])
        assert turn['range'] == [16, 46] and turn['content'] == text[16:46]
        assert turn['source_ref'] == ref and turn['source_revision'] == 1
        assert middle['turn_range'] == [7, 8]
        assert service.source(ref)['content'] == text


@pytest.mark.parametrize('selection', [False, True])
def test_actual_tool_history_search_read_delivery_and_read_budget(selection, tmp_path):
    from test_intent_retrieval import context

    with SqliteStore.from_conn_string(str(tmp_path/'db')) as store:
        service = service_at(store, tmp_path)
        for index in range(3):
            service.capture_tool('long-tools', str(index), 'observation', 'irrelevant ' * 120, None)
        body = 'background ' * 100 + 'ZEBRA_PASSCODE_4312' + ' tail' * 40
        ref = service.capture_tool('long-tools', 'target', 'observation', body, None)['source_ref']
        cfg = context(service)
        seen = []

        class Policy:
            def choose(self, state, actions):
                seen.append(state.project())
                if len(seen) == 1:
                    return next(a.id for a in actions if a.kind == 'SEARCH'
                                and a.parameters['limit'] == 8)
                if len(seen) == 2:
                    return 'read_0_observe' if selection else 'read_0'
                return next(a.id for a in actions if a.kind == 'HANDOFF'
                            and (not selection or a.parameters == {'delivery_indices': [0]}))

        memory = IntentRetrievalMemory(service, len, material_limit=2200, read_limit=8,
            evidence_policy='question_pack_v1', source_access='independent_v1',
            source_tokenization='unicode_v1', control_policy=Policy(), control_steps=4,
            control_source_observation_tokens=900, control_delivery_selection=selection,
            control_source_ranges=SourceRangeBudget(80, len, character_offsets))
        before = memory.read_allowance(cfg)['reads_remaining']
        packet = memory.retrieve(cfg, 'ranges', RetrievalRequest(query='ZEBRA_PASSCODE_4312'))
        assert 'ZEBRA_PASSCODE_4312' in json.dumps(packet['evidence'])
        assert 'ZEBRA_PASSCODE_4312' not in json.dumps(seen[0]['new_events'])
        assert packet['usage']['read_operations'] == 1
        assert packet['usage']['operations'] == (3 if selection else 2)
        assert before - memory.read_allowance(cfg)['reads_remaining'] == 2
        assert memory.return_tokens(packet) <= 2200
        delivered = packet['evidence'][0]['evidence'][0]
        left, right = delivered['range']
        assert delivered['content'] == body[left:right]
        assert delivered['source_characters'] == len(body)
        assert right-left <= 80 and service.source(ref)['content'] == body
        assert memory.policy['source_range_tokens'] == 80


def test_normal_runner_applies_declared_range_condition_to_all_tool_history(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted

    from milai_lab.runners.functional import message

    root = prepared(tmp_path, native=True, memory_method='milai_edit_m_v1',
        evidence_policy='question_pack_v1', retrieval_tool='rich', business_tools=[],
        memory_view_mode='staged', additional_reads=6, memory_control={'policy': 'fixed_context',
            'max_control_steps': 6, 'reads': 1, 'source_observation_tokens': 300,
            'source_range_tokens': 64})
    scripted(monkeypatch, lambda *_: pytest.fail('No Host generation in given retrieval'),
             native=True)
    result = message(root, bank='ranges', owner='alice', session='host', message_id='q',
        content='Zebra passcode', given_retrieval_request={'query': 'Zebra passcode'},
        incoming_sources=[{'event_key': 'long', 'session_id': 'history', 'role': 'tool',
            'origin': 'synthetic_observation', 'occurred_at': None,
            'content': 'background text ' * 1200
                + ' Zebra passcode is 4312. ' + ' tail ' * 100}])
    assert result['status'] == 'COMPLETED', result.get('error')
    assert '4312' in json.dumps(result['retrieval_result']['evidence'])
    trace = next(root.glob('banks/*/*-trace-*.jsonl'))
    inputs = [e for line in trace.read_text().splitlines()
              if (e := json.loads(line)).get('phase') == 'decision_input']
    assert any(p.get('source_range_read') for e in inputs for p in e['candidate_materials'])
    assert '4312' not in json.dumps(inputs[0]['before']['new_events'])


def test_default_whole_exchange_and_range_reopen_after_source_revocation(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path/'db')) as store:
        service = service_at(store, tmp_path)
        text = 'private zebra evidence ' * 30
        ref = service.capture_tool('s', 'one', 'observation', text, None)['source_ref']
        service.capture_tool('s', 'two', 'observation', 'second tool result', None)
        originals = service.search_sources('zebra', limit=1)['source_materials']
        original = build_evidence_packs(service, 'zebra', '', originals, [])
        assert len(original) == 1 and len(original[0]['source_ranges']) == 2
        ranged = build_evidence_packs(service, 'zebra', '', originals, [],
            source_range_budget=SourceRangeBudget(80, len, character_offsets), source_range_limit=3)
        assert len(ranged) == 3
        assert all(p['source_ranges'][0]['source_ref'] == ref for p in ranged)
        handle = service.source_fragment_range(ref, 0, len(text))['fragment_handle']
        service.forget('s', 'forget', fragment_handles=[handle])
        reopened = open_evidence_packs(service, ranged)
        assert all(p['body_delivered'] is False and p['text'] == '[]' for p in reopened)
        assert all(p['unavailable_source_ranges'] for p in reopened)
