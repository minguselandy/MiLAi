"""Read literal first answers; failures and native reference conflicts remain visible."""
import pytest

from milai_lab.harness.artifact_io import write_json
from score_qasper_readouts import read_answers, read_host_answers


def test_raw_explanatory_answer_is_not_shortened_and_failed_answer_is_not_repaired(tmp_path):
    cases, paths = [], {}
    for index, status in enumerate(("COMPLETED", "FAILED", None)):
        family = f"paper-{index}"
        cases.append({"family": family, "history": family,
            "native_control": {"native_question_id": f"native-{index}"},
            "request": {"id": "q", "content": "Is the claim supported?"}})
        capture = tmp_path / family
        write_json(capture / "call.json", {"bank": family + "-q", "public_message": {
            "message_id": "q", "content": "Is the claim supported?"}})
        readout = capture / "readout.json"
        write_json(readout, {"status": status, "captured_call": str(capture),
                            "answer": "Yes, for this condition only. [Source 1]"})
        paths[family] = str(readout) if status else None
    predictions, receipts = read_answers(cases, paths)
    assert predictions == {"native-0": {"answer": "Yes, for this condition only. [Source 1]",
                                       "evidence": []}}
    assert [r["status"] for r in receipts] == ["COMPLETED", "FAILED", "MISSING_READOUT"]
    with pytest.raises(ValueError, match="every declared"):
        read_answers(cases, {k: v for k, v in paths.items() if k != "paper-2"})


def test_closed_readout_from_another_paper_cannot_be_scored_as_this_question(tmp_path):
    case = {"family": "paper", "history": "paper", "request": {"id": "q", "content": "Same text"},
            "native_control": {"native_question_id": "native"}}
    write_json(tmp_path / "call.json", {"bank": "another-paper-q",
        "public_message": {"message_id": "q", "content": "Same text"}})
    path = tmp_path / "readout.json"
    write_json(path, {"status": "COMPLETED", "captured_call": str(tmp_path), "answer": "Yes"})
    with pytest.raises(ValueError, match="paper question"):
        read_answers([case], {"paper": str(path)})


def test_host_scoring_keeps_literal_first_answer_and_all_failed_or_missing_positions(tmp_path):
    cases, paths = [], {}
    for index, status in enumerate(['COMPLETED', 'FAILED', 'COMPLETED', 'BUDGET_EXHAUSTED', None]):
        family = f'paper-{index}'
        cases.append({'family': family, 'history': family,
            'request': {'id': 'q', 'content': 'Question'},
            'native_control': {'native_question_id': str(index)}})
        path = tmp_path/f'{family}-attempt-0.json'
        result = {'status': status, 'bank': family+'-q', 'message_id': 'q', 'content': 'Question',
                  'final_answer': 'Yes, within this condition. [Source e0]'}
        if index == 2:
            result['failure_delivery'] = {'reason': 'budget_exhausted'}
        write_json(path, result)
        paths[family] = str(path) if status else None
    predictions, receipts = read_host_answers(cases, paths)
    assert predictions == {'0': {
        'answer': 'Yes, within this condition. [Source e0]', 'evidence': []}}
    assert [r['status'] for r in receipts] == [
        'COMPLETED', 'FAILED', 'FAILURE_DELIVERY', 'BUDGET_EXHAUSTED', 'MISSING_HOST_RESULT']
    with pytest.raises(ValueError, match='every declared'):
        read_host_answers(cases, {'paper-0': paths['paper-0']})


def test_host_scoring_rejects_given_conditions_and_wrong_public_task_binding(tmp_path):
    case = {'family': 'paper', 'history': 'paper',
        'request': {'id': 'q', 'content': 'Question'},
        'native_control': {'native_question_id': 'n'}}
    path = tmp_path/'first-attempt-0.json'
    result = {'status': 'COMPLETED', 'bank': 'paper-q', 'message_id': 'q',
        'content': 'Question', 'final_answer': 'Yes', 'host_request_generated': False}
    write_json(path, result)
    with pytest.raises(ValueError, match='not autonomous'):
        read_host_answers([case], {'paper': str(path)})
    result.pop('host_request_generated')
    result['bank'] = 'another-paper-q'
    write_json(path, result)
    with pytest.raises(ValueError, match='paper question'):
        read_host_answers([case], {'paper': str(path)})
