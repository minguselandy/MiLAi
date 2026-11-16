"""Known pre-HTTP View capacity rejection versus unknown transport outcomes."""
import json
from pathlib import Path

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.query_structure import build_query_structure
from milai_lab.runners.functional import frozen, message
from milai_lab.runners.retrieval_histories import prepare_history_bank


def setup(tmp_path, monkeypatch, *, prior_view=False):
    from test_v13_5_functional_integration import prepared

    root = prepared(tmp_path, native=True, memory_method='milai_edit_m_v1',
        evidence_policy='question_pack_v1', retrieval_tool='rich', business_tools=[],
        stage_enable_thinking={'query_structure': False},
        memory_view_mode='staged', additional_reads=5, memory_control={'policy': 'fixed_context',
            'max_control_steps': 5, 'source_observation_tokens': 300, 'source_range_tokens': 64})
    history = prepare_history_bank(root, bank='ranges', owner='alice', history={
        'source_group': 'synthetic-only', 'sources': [{'session_id': 'prior', 'event_key': 'small',
            'original_event_id': 'prior/small', 'role': 'tool', 'origin': 'synthetic_observation',
            'occurred_at': None, 'content': 'Prior mechanical observation.'}]})
    saved = None
    if prior_view:
        db = next(root.glob('banks/*/memory.sqlite'))
        with SqliteStore.from_conn_string(str(db)) as store:
            service = MemoryService(store,
                ('functional', frozen(root)['run_id'], 'ranges', 'alice'),
                'alice', db.parent/'memory.lock', functional_contract='functional_v1')
            ref = history['sources'][0]['receipt']['source_ref']
            def interpret(messages, schema):
                source = json.loads(messages[-1]['content'])['sources'][0]['id']
                return {'scope': 'Prior synthetic scope', 'nodes': [{'id': 'n0', 'kind': 'reported',
                    'text': 'Prior mechanical observation.', 'evidence': [source]}],
                    'rules': [], 'remove': [], 'remove_rules': [], 'unresolved': []}
            saved, _ = build_query_structure(service, 'prior scope', '', [ref],
                policy='incremental', call=interpret)
    states = []
    class Policy:
        def choose(self, state, actions):
            states.append(state.project())
            if len(states) == 1:
                return next(a.id for a in actions if a.kind == 'REFRESH_VIEW')
            if len(states) == 2:
                assert state.last_result['status'] == 'view_rejected'
                assert state.last_result['effect'] == 'none'
                return next(a.id for a in actions if a.kind == 'SEARCH'
                            and a.parameters['limit'] == 8)
            if len(states) == 3:
                return 'read_0'
            return 'handoff'
    monkeypatch.setattr('milai_lab.runners.memory_control.memory_policy', lambda *a, **k: Policy())
    return root, states, saved


def run(root, body):
    return message(root, bank='ranges', owner='alice', session='host', message_id='query',
        content='Zebra passcode', given_retrieval_request={'query': 'Zebra passcode'},
        incoming_sources=[{'event_key': 'long', 'session_id': 'current', 'role': 'tool',
            'origin': 'synthetic_observation', 'occurred_at': None, 'content': body}])


@pytest.mark.parametrize('prior_view', [False, True])
def test_capacity_rejection_preserves_view_and_consumed_attempt_then_original_read(
    tmp_path, monkeypatch, prior_view,
):
    from test_v13_5_functional_integration import scripted

    root, states, prior = setup(tmp_path, monkeypatch, prior_view=prior_view)
    wires = scripted(monkeypatch, lambda *_: pytest.fail('Capacity rejection must precede HTTP'),
                     native=True)
    result = run(root, 'background ' * 35000 + ' Zebra passcode is 4312. ')
    assert result['status'] == 'COMPLETED', result.get('error')
    assert not wires and len(states) == 4
    rejected = states[1]['last_result']
    prefix, detail = rejected['reason'].split(':', 1)
    assert prefix == 'QUERY_STRUCTURE_INPUT_CAPACITY_EXCEEDED'
    measured = json.loads(detail)
    assert measured['total_reserved_tokens'] > measured['context_tokens']
    assert result['retrieval_result']['usage']['operations'] == 3
    assert result['retrieval_result']['usage']['read_operations'] == 1
    assert '4312' in json.dumps(result['retrieval_result']['evidence'])
    bank = next(root.glob('banks/*'))
    admission, = read_json(bank/'message-admission.json')['messages'].values()
    assert admission['count'] == 1  # The pre-HTTP attempt is not refunded or retried.
    budget = read_json(Path(frozen(root)['config']['budget_path']))
    assert budget['generation_requests'] == 0
    assert budget['generation']['charged_tokens'] == 0
    with SqliteStore.from_conn_string(str(bank/'memory.sqlite')) as store:
        service = MemoryService(store, ('functional', frozen(root)['run_id'], 'ranges', 'alice'),
            'alice', bank/'memory.lock', functional_contract='functional_v1')
        cached = service.store.get((*service.namespace, 'query_structure_v1'), 'current')
        assert (cached.value if cached else None) == prior
    events = [json.loads(line) for path in bank.glob('*-trace-*.jsonl')
              for line in path.read_text().splitlines()]
    assert sum(e['event'] == 'vllm_capacity_rejected' for e in events) == 1
    assert not any(e['event'] == 'vllm_request' for e in events)


def test_dispatched_transport_timeout_is_not_converted_to_definite_view_rejection(
    tmp_path, monkeypatch,
):
    from test_v13_5_functional_integration import scripted

    root, states, _ = setup(tmp_path, monkeypatch)
    def timeout(*_):
        raise httpx.ReadTimeout('Synthetic dispatched request has unknown outcome')
    wires = scripted(monkeypatch, timeout, native=True)
    result = run(root, 'Zebra passcode is 4312.')
    assert result['status'] != 'COMPLETED'
    assert len(wires) == 1 and len(states) == 1
    budget = read_json(Path(frozen(root)['config']['budget_path']))
    assert budget['generation_requests'] == 1
    assert budget['generation']['unknown_usage'] == 1
    assert budget['generation']['charged_tokens'] > 0


def test_controller_generation_overflow_still_raises_capacity_failure(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted

    root = prepared(tmp_path, native=True, memory_method='milai_edit_m_v1',
        evidence_policy='question_pack_v1', retrieval_tool='rich', business_tools=[],
        memory_view_mode='staged', memory_control={'policy': 'generative',
            'state_projection': 'shared_actions', 'max_control_steps': 3,
            'source_observation_tokens': 300})
    wires = scripted(monkeypatch, lambda *_: pytest.fail('Oversized input must not be sent'),
                     native=True)
    result = message(root, bank='ranges', owner='alice', session='host', message_id='query',
        content='A mechanical input-capacity probe.',
        given_retrieval_request={'query': 'large query ' * 35000})
    assert result['status'] != 'COMPLETED' and not wires
    assert result['error_type'] == 'CapacityExceeded'
