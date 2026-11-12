"""Multiple original requests preserve their own native context and original receipt K."""
import json
import sys
from types import SimpleNamespace

import prepare_public_initial_feedback as preparation
import rollout_public_known_conditions as rollout
from collect_public_reference_states import collect_history
from milai_lab.harness.artifact_io import write_json
from milai_lab.memory.literal_projection import observation_object
from milai_lab.methods.laya_memory_policy import payload_actions
from prepare_musique_operation_sources import export_family


def test_all_requests_reuse_original_k_and_preserve_context(tmp_path, monkeypatch):
    a = {"idx": 0, "title": "Alpha", "paragraph_text": "Alpha leads to Beta.",
         "is_supporting": True}
    b = {"idx": 1, "title": "Beta", "paragraph_text": "HIDDEN_BETA_PREMISE gives Gamma.",
         "is_supporting": True}
    records = [{"metadata": {"row": i}, "source": {"id": f"q-{i}",
        "question": "Where does Alpha lead?", "paragraphs": paragraphs,
        "answerable": answerable, "answer": "Gamma", "answer_aliases": []}}
        for i, (paragraphs, answerable) in enumerate((([a], False), ([a, b], True)))]
    history, controls = export_family("family", records)
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
            choice = (next(a for a in actions if a.kind == 'SEARCH')
                      if before['last_result'] is None else
                      next(a for a in actions if a.kind == 'HANDOFF' and not a.parameters))
            return {'choice': choice.id,
                    'logits': {a.id: float(a.id == choice.id) for a in actions}}

    monkeypatch.setattr(rollout, 'HostCapacity', lambda _: capacity)
    monkeypatch.setattr(rollout, 'NativeDecision', Decision)
    output = tmp_path / 'output'
    monkeypatch.setattr(sys, 'argv', ['rollout', str(collection), str(config), 'unused-model',
                                    str(output), '--families', '1', '--requests-per-family', '0'])
    rollout.main()
    run = json.loads((output / 'run.json').read_text())
    assert run['completed_families'] == 1 and run['closed_requests'] == 4
    assert run['planned_native_requests'] == 2 and len(inputs) == 8
    assert all('HIDDEN_BETA_PREMISE' not in json.dumps(p) for p in inputs[:4])
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
        '--continuation-policy', 'query_once_context', '--include-legal-handoff'])
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
