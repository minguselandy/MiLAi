"""Bind reviewed development source pools to ordinary autonomous Host tasks."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from milai_lab.datasets.intent_training import musique_intent_request
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def public_histories(views: list[dict[str, Any]], allocation: dict[str, Any]
                     ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected = {e['family']: e for e in allocation['selection'] if e['split'] == 'dev'}
    if len(views) != len(selected) or {v['family'] for v in views} != set(selected):
        raise ValueError('Public histories require exactly the fixed development source families')
    histories, bindings = [], []
    for view in views:
        family = view['family']
        if view['split'] != 'dev' or selected[family]['source_rows'] != [view['source_row']]:
            raise ValueError('Development source identity or evaluation role changed')
        # Reuse the established literal Source layout, but retain the native public question.
        # The older collection helper adds a retrieval directive; this evaluation must not.
        request = musique_intent_request(view, view['source_row'])
        request['content'] = view['question']
        history = {'id': family, 'source_group': family, 'split': 'dev',
                   'sources': [], 'requests': [request]}
        histories.append(history)
        bindings.append({'history_id': family, 'request_id': request['id'],
            'source_row': view['source_row'], 'question_id': selected[family]['question_id'],
            'paragraphs': [{'original_event_id': source['original_event_id'],
                            'paragraph_index': paragraph['idx']}
                           for source, paragraph in zip(request['sources'], view['paragraphs'],
                                                        strict=True)]})
    return {'schema': 'two_wiki_reviewed_dev_autonomous_histories_v1',
        'gradient_training_allowed': False, 'histories': histories,
        'scope': 'Native questions and complete source pools only. One independent request per '
                 'bank; no forced retrieval, prefetch or ideal memory. Source availability is '
                 'not Host knowledge. This static task cohort is not a lifecycle experiment.'
    }, bindings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('allocation', type=Path)
    parser.add_argument('source_views', type=Path)
    parser.add_argument('source_review', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    allocation, review = read_json(args.allocation), read_json(args.source_review)
    views = read_jsonl(args.source_views)
    fixture, bindings = public_histories(views, allocation)
    cases = {c['family']: c for c in review['cases']}
    if set(cases) != {v['family'] for v in views}:
        raise ValueError('Offline source review differs from the fixed public development tasks')
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'histories.json', fixture)
    write_json(args.output / 'offline-bindings.json', {'bindings': bindings,
        'source_review': str(args.source_review.resolve()),
        'scope': 'Join actual runtime source-import original_event_id to these paragraphs. '
                 'No action or Host outcome is assigned before execution.'})
    report = {'status': 'DEV_PUBLIC_TASKS_MATERIALIZED;ACTUAL_RUNTIME_AND_HOST_PENDING',
        'allocation': str(args.allocation.resolve()),
        'source_views': str(args.source_views.resolve()),
        'histories': len(fixture['histories']), 'request_positions': len(bindings),
        'source_paragraph_positions': sum(len(b['paragraphs']) for b in bindings),
        'source_unknown_positions_retained': sum(c['disposition'] != 'supported'
                                                for c in cases.values()),
        'public_questions_literal': True, 'source_titles_bodies_and_order_literal': True,
        'forced_retrieval_directive': False, 'reference_labels_in_public_fixture': False,
        'confirmation_histories_materialized': 0, 'gradient_training_allowed': False,
        'model_calls': 0, 'ledger_recorded': False,
        'cpu_seconds_pending': time.process_time() - started, 'no_sha_validation': True}
    write_json(args.output / 'preparation.json', report)
    print(report['status'], report['histories'], report['source_paragraph_positions'])


if __name__ == '__main__':
    main()
