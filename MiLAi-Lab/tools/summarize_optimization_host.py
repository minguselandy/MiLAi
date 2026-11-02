"""Reconcile declared Host cohorts with actual outputs and separately bound reference reviews."""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from summarize_original_feedback_host import summarize


def summarize_cohort(dispatch: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if dispatch['status'] != 'OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED':
        raise ValueError('Use the explicitly bound optimization cohort dispatch')
    adapted = copy.deepcopy(dispatch)
    study = adapted['study']
    study['positions_per_arm'] = study['positions_per_unique_arm']
    study['exposure'] = study['dispatch_scope']
    result = summarize(adapted, reviews)
    references = {}
    if 'native_reference_review' in study:
        for case in read_json(Path(study['native_reference_review']))['cases']:
            key = case['family'], f"corpus-{case['source_row']}"
            if key in references:
                raise ValueError('Native reference identity repeats a public task')
            references[key] = case['native_reference_answer']
    for row in result['positions']:
        row['reference_relation'] = 'unknown'
        review = row['review']
        if review is None or 'reference_relation' not in review:
            continue
        relation = review['reference_relation']
        grade = relation['grade']
        if grade not in {'compatible', 'incompatible', 'qualified', 'ambiguous', 'unknown'}:
            raise ValueError('Reference relation requires a declared compatibility category')
        key = row['family'], row['request']
        if (key not in references or row['result_path'] is None
                or relation['native_reference_answer'] != references[key]
                or (grade != 'unknown' and not relation['rationale'])):
            raise ValueError(
                'Reference review must bind this actual answer and frozen native reference')
        row['reference_relation'] = grade
    for arm in result['arms']:
        rows = [row for row in result['positions'] if row['arm_id'] == arm['arm_id']]
        arm['reference_relation_counts'] = dict(Counter(row['reference_relation'] for row in rows))
        arm['positions_with_visible_prefetch'] = sum(bool(row['visible_prefetch_receipts'])
                                                     for row in rows)
    result.update(status='OPTIMIZATION_HOST_FIXED_TASKS_AND_BOUND_REVIEWS_RECONCILED',
        execution_id=study['execution_id'], task_conditions=study['task_conditions'],
        cohort_scope=study['dispatch_scope'],
        reference_scope='Reference compatibility is a separately authored judgment, not automatic '
                        'factual truth, source support, Host knowledge, memory attribution or an '
                        'official benchmark score. Unexecuted/unreviewed positions remain unknown.')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dispatch', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reviews', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    reviews = read_json(args.reviews)['reviews'] if args.reviews is not None else []
    result = summarize_cohort(read_json(args.dispatch), reviews)
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
                  model_calls=0, no_sha_validation=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(result['status'], 'fixed positions', result['planned_positions'])


if __name__ == '__main__':
    main()
