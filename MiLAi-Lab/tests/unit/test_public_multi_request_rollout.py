"""Multiple original requests preserve their own native context and original receipt K."""
import json
import sys
from types import SimpleNamespace

import pytest

import prepare_public_initial_feedback as preparation
import rollout_public_known_conditions as rollout
from collect_public_reference_states import collect_history
from milai_lab.harness.artifact_io import write_json
from milai_lab.memory.literal_projection import observation_object
from milai_lab.methods.laya_memory_policy import payload_actions
from prepare_musique_operation_sources import export_family


@pytest.mark.parametrize("split", ["train", "dev"])
def test_all_requests_reuse_original_k_and_preserve_context(tmp_path, monkeypatch, split):
    a = {"idx": 0, "title": "Alpha", "paragraph_text": "Alpha leads to Beta.",
         "is_supporting": True}
    b = {"idx": 1, "title": "Beta", "paragraph_text": "HIDDEN_BETA_PREMISE gives Gamma.",
         "is_supporting": True}
    records = [{"metadata": {"row": i}, "source": {"id": f"q-{i}",
        "question": "Where does Alpha lead?", "paragraphs": paragraphs,
        "answerable": answerable, "answer": "Gamma", "answer_aliases": []}}
        for i, (paragraphs, answerable) in enumerate((([a], False), ([a, b], True)))]
    history, controls = export_family("family", records)
    history['split'] = split
    capacity = SimpleNamespace(text_tokens=len, tokenizer=lambda text, **_: {
        "offset_mapping": [(i, i + 1) for i in range(len(text))]})
    collection = tmp_path / 'collection'
    bank = collection / 'banks' / history['id']
    collect_history(history, {c['request_id']: c for c in controls}, bank, capacity,
                    max_steps=8, material_tokens=8192, known_condition=True, append=lambda _: None)
    write_json(collection / 'run.json', {'status': 'COMPLETED'})
    write_json(collection / 'sources.json', {'histories': [history]})
    config = tmp_path / 'config.json'
    write_json(config, {'entrypoints': {'functional': {'capacity': {},
        'ordinary_material_tokens': 8192, 'host': {'base_url': 'http://localhost', 'model': 'test'},
        'system_prompt': 'Answer using actual evidence'}}})
    inputs = []

    class Decision:
        def __init__(self, *_):
            self.model = SimpleNamespace(encoder=SimpleNamespace(config=SimpleNamespace()))
            self.counters = {}

        def predict(self, payload):
            inputs.append(payload)
            actions = payload_actions(payload)
            before = observation_object(payload['state'])
            last = before['last_result']
            if last is None:
                choice = next(a for a in actions if a.kind == 'SEARCH')
            elif last['action']['kind'] == 'SEARCH':
                choice = next((a for a in actions if a.id.startswith('read_')),
                              next(a for a in actions if a.id == 'handoff'))
            elif last['action']['id'] == 'read_0' and any(a.id == 'read_1' for a in actions):
                choice = next(a for a in actions if a.id == 'read_1')
            else:
                choice = next(a for a in actions if a.kind == 'HANDOFF' and not a.parameters)
            return {'choice': choice.id,
                    'logits': {a.id: float(a.id == choice.id) for a in actions}}

    monkeypatch.setattr(rollout, 'HostCapacity', lambda _: capacity)
    monkeypatch.setattr(rollout, 'NativeDecision', Decision)
    # The decision model is synthetic; record only its runtime-configuration calls.
    runtime_calls = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        set_num_threads=lambda count: runtime_calls.append(("threads", count)),
        backends=SimpleNamespace(mha=SimpleNamespace(
            set_fastpath_enabled=lambda enabled: runtime_calls.append(("fastpath", enabled)),
        )),
    ))
    output = tmp_path / 'output'
    monkeypatch.setattr(sys, 'argv', ['rollout', str(collection), str(config), 'unused-model',
                                    str(output), '--families', '1', '--requests-per-family', '0'])
    rollout.main()
    assert runtime_calls == [("threads", 4), ("fastpath", False)]
    run = json.loads((output / 'run.json').read_text())
    assert run['completed_families'] == 1 and run['closed_requests'] == 4
    assert run['planned_native_requests'] == 2 and len(inputs) > 8
    for condition in ('cold', 'known-first'):
        first = output / 'banks' / history['id'] / (
            history['requests'][0]['id'] + '-' + condition + '-predictions.jsonl')
        assert 'HIDDEN_BETA_PREMISE' not in first.read_text()
    for request in history['requests']:
        known = json.loads((output / 'banks' / history['id'] /
                            f"{request['id']}-known-first-receipt.json").read_text())
        parent = json.loads((bank / f"{request['id']}-cold-receipt.json").read_text())
        assert known['request']['task_context']['known_evidence_refs'] == [
            parent['packet']['evidence'][0]['ref']]
    monkeypatch.setattr(preparation, 'HostCapacity', lambda _: capacity)
    prepared = tmp_path / 'post-state-branches'
    monkeypatch.setattr(sys, 'argv', ['prepare', str(output), str(prepared), '--families', '1',
        '--requests-per-family', '0', '--target-step', '1', '--continuation-steps', '2',
        '--continuation-policy', 'query_once_context', '--include-legal-handoff', '--split', split])
    preparation.main()
    cases = json.loads((prepared / 'cases.json').read_text())
    assert len(cases) == 4 and {c['step'] for c in cases} == {1}
    for case in cases:
        trace = output / 'banks' / history['id'] / (
            case['request_id'] + '-' + case['condition'] + '-operations.jsonl')
        events = [json.loads(line) for line in trace.open()]
        original = next(e for e in events if e.get('phase') == 'decision_output' and e['step'] == 1)
        assert case['before'] == original['before'] and case['actions'] == original['actions']
        assert all(b['actual_before_and_full_menu_equal'] for b in case['branches'])
    terminal = tmp_path / 'terminal-deliveries'
    monkeypatch.setattr(sys, 'argv', ['prepare', str(output), str(terminal), '--families', '1',
        '--requests-per-family', '0', '--terminal-deliveries', '--continuation-steps', '0',
        '--split', split])
    preparation.main()
    cases = json.loads((terminal / 'cases.json').read_text())
    assert len(cases) == 4 and all(c['source_split'] == split for c in cases)
    assert any({'material_a', 'material_b', 'material_a_b'} <= set(c['choices']) for c in cases)
    for case in cases:
        for branch in case['branches']:
            assert branch['action']['kind'] == 'HANDOFF'
            assert branch['actual_before_and_full_menu_equal']
            if case['request_id'] == history['requests'][0]['id']:
                assert 'HIDDEN_BETA_PREMISE' not in json.dumps(branch['packet'])
    rows = [json.loads(line) for line in (terminal / 'states.jsonl').open()]
    assert len(rows) == len(cases)
    assert {r['metadata']['split'] for r in rows} == {split}
    # New saved-model nominations may choose a different legal delivery without
    # inventing a new state or changing this conditional test into acquisition.
    nominations = tmp_path / 'nominations'
    nominations.mkdir()
    for case in cases:
        handoffs = [a for a in case['actions'] if a['kind'] == 'HANDOFF']
        case['choices']['new_saved_delivery'] = handoffs[-1]['id']
    write_json(nominations / 'cases.json', cases)
    selected = tmp_path / 'new-selected-deliveries'
    monkeypatch.setattr(sys, 'argv', ['prepare', str(output), str(selected), '--families', '1',
        '--requests-per-family', '0', '--terminal-deliveries', '--continuation-steps', '0',
        '--split', split, '--nomination-source', str(nominations)])
    preparation.main()
    new_cases = json.loads((selected / 'cases.json').read_text())
    for before, after in zip(cases, new_cases, strict=True):
        assert before['before'] == after['before'] and before['actions'] == after['actions']
        branch = next(b for b in after['branches'] if 'new_saved_delivery' in b['policies'])
        assert branch['action']['id'] == before['choices']['new_saved_delivery']
        assert branch['actual_before_and_full_menu_equal']
