"""Frozen blocks preserve semantic-only rows and cannot double-count event versions."""
import copy
import json
import sys

import pytest

import compile_reader_utility_data


def state(event):
    return {"state": {"task": {"request": "Actual public request"}},
        "questions": {"next": {"type": "choice", "instructions": "Choose",
            "criteria": {"read": "READ source {}", "stop": "HANDOFF packet {}"}}},
        "gold": {}, "metadata": {"event_id": event, "family": event.split('/')[0],
            "split": "train", "row": 0, "state_id": 0,
            "action_kinds": {"read": "READ", "stop": "HANDOFF"},
            "action_parameters": {"read": {}, "stop": {}}}}


def block(path, rows, active):
    path.mkdir()
    states = path / "states.jsonl"
    states.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    scores = []
    for row, known in zip(rows, active, strict=True):
        for i, (key, kind, target) in enumerate((('read', 'READ', 'source'),
                                                 ('stop', 'HANDOFF', 'packet'))):
            scores.append({"event_id": row['metadata']['event_id'],
                "family": row['metadata']['family'], "research_split": "train",
                "action": {"id": key, "kind": kind, "target": target, "parameters": {}},
                "score_known": known, "mean_logprob": -1. - i,
                "teacher": "frozen", "template_version": "v1", "reference_set_id": "offline",
                "continuation": {"steps": 2}})
    score_path = path / "scores.jsonl"
    score_path.write_text(''.join(json.dumps(s) + '\n' for s in scores))
    (path / "run.json").write_text(json.dumps({"status": "COMPLETED"}))
    return states, score_path


def test_closed_blocks_keep_semantic_only_support_and_record_inactive(tmp_path, monkeypatch):
    rows = [state('a/q0'), state('b/q0'), state('c/q0')]
    first = block(tmp_path / 'first', rows[:1], [True])
    second = block(tmp_path / 'second', rows[1:], [False, False])
    semantic = copy.deepcopy(rows[1])
    semantic['feedback'] = {'comparisons': [{'left': 'read', 'right': 'stop',
                                            'answer': 'unknown', 'delivery': 'left'}]}
    semantic['metadata']['feedback_semantics'] = 'actual_reviewed_delivery'
    review_path = tmp_path / 'semantic.jsonl'
    review_path.write_text(json.dumps(semantic) + '\n')
    replay = state('replay/q0')
    replay['gold'] = {'next': {'probabilities': {'read': 1.}}}
    replay_path = tmp_path / 'replay.jsonl'
    replay_path.write_text(json.dumps(replay) + '\n')
    output = tmp_path / 'output'
    monkeypatch.setattr(sys, 'argv', ['compile', *map(str, first), str(replay_path), str(output),
        '--additional-block', *map(str, second), '--semantic', str(review_path),
        '--active-main-only'])
    compile_reader_utility_data.main()
    result = [json.loads(line) for line in (output / 'train.jsonl').read_text().splitlines()]
    assert [r['metadata']['event_id'] for r in result] == ['a/q0', 'b/q0', 'replay/q0']
    assert result[1]['feedback'] == semantic['feedback'] and result[1]['gold'] == {}
    assert all(result[i][k] == rows[i][k] for i in (0, 1) for k in ('state', 'questions'))
    report = json.loads((output / 'run.json').read_text())
    assert report['original_opportunity_states'] == 3 and report['main_states'] == 2
    assert report['active_primary_states'] == {'pair': 1, 'utility-kl': 1}
    assert report['inactive_opportunities'] == 1 and report['primary_exposures'] == 6
    assert json.loads((output / 'inactive-opportunities.json').read_text())[0]['event_id'] == 'c/q0'


def test_repeated_state_version_is_not_silently_repeated_as_new_experience(tmp_path, monkeypatch):
    first = block(tmp_path / 'first', [state('a/q0')], [True])
    second = block(tmp_path / 'second', [state('a/q0')], [True])
    monkeypatch.setattr(sys, 'argv', ['compile', *map(str, first), str(tmp_path / 'unused-replay'),
        str(tmp_path / 'output'), '--additional-block', *map(str, second)])
    with pytest.raises(ValueError, match='Repeated event version'):
        compile_reader_utility_data.main()
    assert not (tmp_path / 'output').exists()
