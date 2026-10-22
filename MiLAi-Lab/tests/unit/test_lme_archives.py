"""Closed real-Store cohort archives retain every file, outcome and failed position."""
from pathlib import Path

import httpx
import pytest
from test_lme_evaluation import fixture, response
from test_lme_protocol import UPSTREAM

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.lme_archives import archive_lme_cases, restore_lme_case
from milai_lab.runners.lme_evaluation import predict_cohort, score_cohort


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('failed_reader', [False, True])
def test_complete_file_roundtrip_and_outcomes_for_success_and_failed_tail(
    tmp_path, monkeypatch, failed_reader,
):
    snapshot = fixture(tmp_path, monkeypatch)
    predicted, scored = tmp_path/'predicted', tmp_path/'scored'
    calls = []
    def reader(request):
        calls.append(request)
        return response('\\boxed{blue}', 'length' if failed_reader and len(calls)==2 else 'stop')
    args = (tmp_path/'settings.json', snapshot, UPSTREAM, predicted)
    kwargs = {'source_version': 'mechanical', 'capacity_factory': HostCapacity,
              'transport': httpx.MockTransport(reader)}
    if failed_reader:
        with pytest.raises(IncompleteChatResponse):
            predict_cohort(*args, **kwargs)
    else:
        predict_cohort(*args, **kwargs)
    score_cohort(predicted, scored, source_version='mechanical', transport=httpx.MockTransport(
        lambda _: response('{"label":1,"reason":"synthetic match"}')))
    driver_before, scores_before = (predicted/'driver.json').read_bytes(), files(scored)
    generation = read_json(predicted/'driver.json')
    actual = {c['row']: Path(c['runtime']) for c in generation['cases'] if 'runtime' in c}
    original = {row: files(path) for row, path in actual.items()}
    bases = {pool.name: files(pool/'template') for pool in (predicted/'memory').iterdir()}
    report = archive_lme_cases(predicted, scored, source_version='mechanical')
    assert report['status'] == 'COMPLETED'
    assert report['archived_cases'] == (2 if failed_reader else 3)
    assert report['planned_question_count'] == 3
    assert all(not p.exists() for p in actual.values())
    assert (predicted/'driver.json').read_bytes() == driver_before
    assert files(scored) == scores_before
    assert bases == {pool.name: files(pool/'template') for pool in (predicted/'memory').iterdir()}
    for row, path in actual.items():
        assert restore_lme_case(predicted, row) == path
        assert files(path) == original[row]
        assert (predicted/f'case-archives/case-{row:04d}.tar.gz').is_file()
    assert files(scored) == scores_before
    if failed_reader:
        assert [c['status'] for c in generation['cases']] == [
            'COMPLETED', 'FAILED_READING', 'NOT_RUN']
        assert read_json(scored/'metrics.json')['unscored'] == 2


def test_retrieval_failure_records_its_actual_runtime_for_archival(tmp_path, monkeypatch):
    snapshot = fixture(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic original-source search failure')
    monkeypatch.setattr('milai_lab.memory.service.MemoryService.search_sources', fail)
    predicted, scored = tmp_path/'predicted', tmp_path/'scored'
    transport = httpx.MockTransport(lambda _: pytest.fail('No generation on this failed path'))
    with pytest.raises(RuntimeError, match='First failed retrieval retained'):
        predict_cohort(tmp_path/'settings.json', snapshot, UPSTREAM, predicted,
            source_version='mechanical', capacity_factory=HostCapacity, transport=transport)
    driver = read_json(predicted/'driver.json')
    assert driver['cases'][0]['status'] == 'FAILED_RETRIEVING'
    runtime = Path(driver['cases'][0]['runtime'])
    assert read_json(runtime/'query.json')['status'] == 'FAILED'
    score_cohort(predicted, scored, source_version='mechanical', transport=transport)
    before = files(runtime)
    report = archive_lme_cases(predicted, scored, source_version='mechanical')
    assert report['archived_cases'] == 1 and report['planned_question_count'] == 3
    restore_lme_case(predicted, 0)
    assert files(runtime) == before


@pytest.mark.parametrize('phase', ['prediction', 'scoring'])
def test_running_phase_rejected_before_any_archival(tmp_path, phase):
    predicted, scored = tmp_path/'predicted', tmp_path/'scored'
    write_json(predicted/'driver.json', {
        'status': 'RUNNING' if phase=='prediction' else 'COMPLETED'})
    write_json(scored/'driver.json', {'status': 'RUNNING' if phase=='scoring' else 'COMPLETED'})
    with pytest.raises(ValueError, match='Close prediction and scoring'):
        archive_lme_cases(predicted, scored, source_version='mechanical')
    assert not (predicted/'case-archives').exists()


def test_unlisted_case_prevents_partial_collection_archival(tmp_path):
    predicted, scored = tmp_path/'predicted', tmp_path/'scored'
    (predicted/'memory/pool-0000/cases/0000').mkdir(parents=True)
    write_json(predicted/'driver.json', {'status': 'COMPLETED', 'cases': []})
    write_json(scored/'driver.json', {
        'status': 'COMPLETED', 'predictions': str(predicted), 'cases': []})
    with pytest.raises(ValueError, match='every actual case'):
        archive_lme_cases(predicted, scored, source_version='mechanical')
    assert (predicted/'memory/pool-0000/cases/0000').exists()
    assert not (predicted/'case-archives').exists()


def test_missing_declared_runtime_is_not_a_successful_empty_archive(tmp_path):
    predicted, scored = tmp_path/'predicted', tmp_path/'scored'
    (predicted/'memory/pool-0000/template').mkdir(parents=True)
    case = {'row': 0, 'question_id': 'q', 'status': 'COMPLETED', 'pool': 'pool-0000',
            'runtime': str(predicted/'memory/pool-0000/cases/0000')}
    write_json(predicted/'driver.json', {'status': 'COMPLETED', 'cases': [case]})
    write_json(scored/'driver.json', {'status': 'COMPLETED', 'predictions': str(predicted),
                                    'cases': [{'question_id': 'q', 'status': 'COMPLETED'}]})
    with pytest.raises(FileNotFoundError, match='runtime is missing'):
        archive_lme_cases(predicted, scored, source_version='mechanical')
    assert not (predicted/'case-archives').exists()
