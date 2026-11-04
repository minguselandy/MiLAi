"""Deduplicate complete bindings without borrowing same-kind results or dropping failed cases."""
import json
from pathlib import Path

import pytest

from milai_lab.harness.artifact_io import write_json
from prepare_e1_choice_branches import bind_nominees, group_choices, matched_closed_bindings


def test_saved_comparison_binds_the_two_nominees_and_update0(tmp_path):
    nomination = {"mandatory_update0": str(tmp_path / "zero"), "nominees": [
        {"arm": arm, "checkpoint": str(tmp_path / arm)}
        for arm in ("delivery-only", "answer-first-head")]}
    conditions = {name: {"checkpoint": str(tmp_path / checkpoint),
        "task": "memory_operation", "operation_state": "shared_actions", "max_len": 16384,
        "head_max_len": 2048, "device": "cpu", "threads": 4, "loaded_weight_dtype": "torch.float32",
        "reference_compile_override": False, "mha_fastpath_enabled": False}
        for name, checkpoint in (("update0", "zero"), ("delivery-only", "delivery-only"),
                                  ("answer-first-head", "answer-first-head"))}
    bind_nominees(nomination, conditions)
    with pytest.raises(ValueError, match="mandatory update0"):
        bind_nominees(nomination, {k: v for k, v in conditions.items() if k != "update0"})
    conditions["delivery-only"]["checkpoint"] = str(tmp_path / "another-update")
    with pytest.raises(ValueError, match="checkpoint differs"):
        bind_nominees(nomination, conditions)
    conditions["delivery-only"]["checkpoint"] = str(tmp_path / "delivery-only")
    conditions["update0"]["operation_state"] = "compact_actions"
    with pytest.raises(ValueError, match="input condition"):
        bind_nominees(nomination, conditions)


def test_same_binding_reuses_failed_baseline_but_other_read_parameters_stay_separate(tmp_path):
    capture = tmp_path / "capture"
    actions = [{"id": key, "kind": "READ", "target": "same source", "parameters": {"index": i}}
               for key, i in (("read0", 0), ("read0_alias", 0), ("read1", 1))]
    baseline = {"id": "stop", "kind": "HANDOFF", "target": "opened", "parameters": {}}
    actions.append(baseline)
    call = {"initial_actions": actions}
    write_json(capture / "call.json", call)
    panel = {"positions": [{"family": "a", "status": "ACTUAL_PRE_HANDOFF_EXPORTED",
        "capture": str(capture), "evaluation_index": 0, "baseline_action": baseline,
        "baseline_readout": {"status": "FAILED"}},
        {"family": "missing", "status": "NO_REACHED_FINAL_HANDOFF", "evaluation_index": None}]}
    predictions = {name: {str(capture.resolve()): {"call": call, "prediction": {"choice": choice}}}
                   for name, choice in (("zero", "stop"), ("a", "read0"),
                                        ("same", "read0_alias"), ("b", "read1"))}
    result = group_choices(panel, predictions)
    assert len(result["positions"]) == 2 and len(result["jobs"]) == 2
    actual = result["positions"][0]
    assert actual["bindings"][0]["readout"]["status"] == "FAILED"
    assert actual["model_choices"]["zero"]["status"] == "REUSED_CLOSED_RAW_OUTCOME"
    assert actual["model_choices"]["a"]["binding_index"] == actual["model_choices"][
        "same"]["binding_index"]
    assert actual["model_choices"]["b"]["binding_index"] != actual["model_choices"][
        "a"]["binding_index"]
    assert all(r["status"] == "NO_REACHED_STATE"
               for r in result["positions"][1]["model_choices"].values())
    assert all(job["intervention"]["continuation_steps"] == 2 for job in result["jobs"])
    assert all(Path(job["capture"]) == capture for job in result["jobs"])


def closed_fixture(tmp_path):
    capture, case = tmp_path / 'capture', tmp_path / 'case'
    action = {'id': 'read0', 'kind': 'READ', 'target': 'candidate0', 'parameters': {'index': 0}}
    other = {**action, 'id': 'observe0', 'parameters': {'index': 0, 'observe_only': True}}
    stop = {'id': 'stop', 'kind': 'HANDOFF', 'target': 'reader', 'parameters': {}}
    call = {'source_version': {'git_commit': 'given-v4'}, 'initial_actions': [action, other, stop]}
    write_json(capture / 'call.json', call)
    replay = {'status': 'COMPLETED', 'captured_call': str(capture), 'source_version': 'given-v4',
        'policy': {'policy': 'fixed_context', 'reads': 4},
        'intervention': {'first_action': action, 'continuation_steps': 2},
        'result': {'frozen_initial_observation_and_actions_equal': True,
                   'frozen_request_and_allowance_equal': True}}
    write_json(case / 'replay.json', replay)
    readout = {'status': 'FAILED', 'captured_call': str(capture), 'source_version': 'given-v4',
               'branch_result': str(case / 'replay.json'),
               'readout_origin': 'actual_same_before_branch', 'error': 'Original failure'}
    path = case / 'host-readout/readout.json'
    write_json(path, readout)
    baseline_path = tmp_path / 'raw/readout.json'
    wire = {'model': 'reader', 'messages': [{'role': 'system', 'content': 'Use evidence'},
        {'role': 'user', 'content': json.dumps({
            'request': 'Question', 'memory': {'evidence': []}})}]}
    write_json(baseline_path.parent / 'request.json', wire)
    write_json(path.parent / 'request.json', wire)
    record = {'capture': str(capture), 'family': 'f', 'case': str(case), 'readout': str(path),
              'status': 'FAILED', 'answer': None, 'first_action': action}
    outcomes = tmp_path / 'outcomes.json'
    write_json(outcomes, {'records': [record]})
    panel = {'positions': [{'family': 'f', 'status': 'ACTUAL_PRE_HANDOFF_EXPORTED',
        'capture': str(capture), 'evaluation_index': 0, 'baseline_action': stop,
        'baseline_readout': {'status': 'COMPLETED', 'result': str(baseline_path)}}]}
    return panel, outcomes, capture, case, call, replay, record


def test_followup_reuses_failed_exact_branch_and_executes_other_parameters_only(tmp_path):
    panel, outcomes, capture, _, call, _, _ = closed_fixture(tmp_path)
    known = matched_closed_bindings(panel, outcomes)
    choices = {name: {str(capture): {'call': call, 'prediction': {'choice': choice}}}
               for name, choice in [('same', 'read0'), ('distinct', 'observe0')]}
    grouped = group_choices(panel, choices, known)
    assert len(grouped['jobs']) == 1
    position = grouped['positions'][0]
    reused = position['model_choices']['same']
    assert reused['status'] == 'REUSED_CLOSED_MATCHED_BRANCH_OUTCOME'
    assert position['bindings'][reused['binding_index']]['readout']['status'] == 'FAILED'
    assert grouped['jobs'][0]['intervention']['first_action']['parameters'] == {
        'index': 0, 'observe_only': True}


@pytest.mark.parametrize('change', [
    'continuation', 'policy', 'before', 'family', 'answer', 'duplicate', 'reader'])
def test_followup_does_not_reuse_unmatched_or_repeated_outcomes(tmp_path, change):
    panel, outcomes, _, case, _, replay, record = closed_fixture(tmp_path)
    if change == 'continuation':
        replay['intervention']['continuation_steps'] = 3
    elif change == 'policy':
        replay['policy']['policy'] = 'fixed'
    elif change == 'before':
        replay['result']['frozen_initial_observation_and_actions_equal'] = False
    elif change == 'family':
        record['family'] = 'other'
    elif change == 'answer':
        record['answer'] = 'Invented answer for a failed response'
    elif change == 'reader':
        write_json(case / 'host-readout/request.json', {'model': 'different-reader',
            'messages': [{'role': 'system', 'content': 'Use evidence'},
                {'role': 'user', 'content': json.dumps({
                    'request': 'Question', 'memory': {'evidence': []}})}]})
    write_json(case / 'replay.json', replay)
    write_json(outcomes, {'records': [record, record] if change == 'duplicate' else [record]})
    with pytest.raises(ValueError):
        matched_closed_bindings(panel, outcomes)
