"""Assign unused native source families to new evaluation roles without model outcomes.

Only dev visible pools are exported. Confirmation source/question bodies and all
native answers stay outside the output. Metadata roles do not certify semantic
independence, source sufficiency, or unseen pretraining.
"""
from __future__ import annotations

import argparse
import json
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from audit_confirmation_source_components import components
from audit_source_selection import overlap, panel
from intake_two_wiki_selection import group_sources
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json

Panel = dict[str, set[Any]]


def empty_panel() -> Panel:
    return {k: set() for k in ('pool', 'target', 'pool_titles', 'target_titles', 'questions')}


def merge_panel(destination: Panel, source: Panel) -> None:
    for key in destination:
        destination[key].update(source[key])


def native_panel(rows: list[dict[str, Any]]) -> Panel:
    result = empty_panel()
    for row in rows:
        targets = {fact[0] for fact in row['supporting_facts']}
        pool = {(title, ' '.join(sentences)) for title, sentences in row['context']}
        result['pool'].update(pool)
        result['pool_titles'].update(title for title, _ in pool)
        result['target_titles'].update(targets)
        result['target'].update(item for item in pool if item[0] in targets)
        result['questions'].add(row['question'])
    return result


def boundary_issues(candidate: Panel, protected: dict[str, Panel]) -> list[dict[str, Any]]:
    issues = []
    for name, reference in protected.items():
        shared = overlap(candidate, reference)
        counts = {k: len(v) if isinstance(v, list) else v for k, v in shared.items()}
        if any(v for k, v in counts.items() if k != 'shared_literal_background_or_target'):
            issues.append({'panel': name, 'counts': counts})
    return issues


def public_sources(paths: list[str]) -> tuple[set[str], set[str], int]:
    bodies, titles, families = set(), set(), set()
    for path in paths:
        for history in read_json(Path(path))['histories']:
            families.add(history['source_group'])
            sources = list(history['sources'])
            for request in history['requests']:
                sources.extend(request.get('sources', []))
                sources.extend(request.get('incoming_sources', []))
            for source in sources:
                bodies.add(source['content'])
                if source.get('origin') == 'reference_document':
                    titles.add(source['content'].split('\n', 1)[0])
    return bodies, titles, len(families)


def choose(
    protocol: dict[str, Any], order: dict[str, list[dict[str, Any]]],
    native: list[dict[str, Any]], protected: dict[str, Panel],
    public_bodies: set[str], public_titles: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Panel]]:
    assigned, attempted = set(protocol['old_excluded_families']), set()
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    family_panels: dict[str, Panel] = {}
    earlier = empty_panel()
    for role in protocol['role_order']:
        for stratum in protocol['stratum_order']:
            accepted = 0
            for candidate in order[stratum]:
                if accepted == protocol['quotas'][role][stratum]:
                    break
                family = candidate['family']
                if family in assigned or family in attempted:
                    continue
                attempted.add(family)
                rows = [native[i] for i in candidate['whole_family_rows']]
                own = native_panel(rows)
                issues = boundary_issues(own, {**protected, 'earlier_new_families': earlier})
                seen_targets = sum(title + '\n' + body in public_bodies or body in public_bodies
                                   for title, body in own['target'])
                seen_titles = len(own['target_titles'] & public_titles)
                if seen_targets or seen_titles:
                    issues.append({'panel': 'current_public_sources',
                                   'counts': {'native_targets': seen_targets,
                                              'native_target_titles': seen_titles}})
                entry = {**candidate, 'split': role, 'original_split': 'train',
                         'gradient_training_allowed': False}
                if issues:
                    rejected.append({**entry, 'issues': issues})
                    continue
                selected.append(entry)
                assigned.add(family)
                family_panels[family] = own
                merge_panel(earlier, own)
                accepted += 1
    return selected, rejected, family_panels


def visible_dev(selected: list[dict[str, Any]], native: list[dict[str, Any]]
                ) -> list[dict[str, Any]]:
    views = []
    for entry in selected:
        if entry['split'] != 'dev':
            continue
        index, = entry['source_rows']
        row = native[index]
        if row['_id'] != entry['question_id']:
            raise ValueError('Chosen question identity differs from the native row')
        views.append({'review_id': f'two-wiki-new-dev-row-{index}',
            'family': entry['family'], 'split': 'dev', 'source_row': index,
            'question': row['question'], 'paragraphs': [
                {'idx': i, 'title': title, 'paragraph_text': ' '.join(sentences)}
                for i, (title, sentences) in enumerate(row['context'])]})
    return views


def prepare(protocol: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frozen = read_json(Path(protocol['candidate_order']))
    groups = read_json(Path(protocol['group_metadata']))
    with zipfile.ZipFile(protocol['archive']) as archive:
        native = json.load(archive.open(protocol['archive_member']))
    if group_sources(native) != groups:
        raise ValueError('Actual native entity/support grouping differs from prior metadata')
    by_family = {g['family']: g for g in groups}
    for stratum, candidates in frozen['order'].items():
        for entry in candidates:
            group = by_family[entry['family']]
            index, = entry['source_rows']
            if (entry['whole_family_rows'] != group['rows'] or index not in group['rows']
                    or native[index]['_id'] != entry['question_id']
                    or len({f[0] for f in native[index]['supporting_facts']}) != int(stratum)):
                raise ValueError('Metadata order or selected native question changed')
    protected = {}
    for entry in protocol['native_protected_panels']:
        wanted = set(entry['rows']) if entry['rows'] is not None else None
        records = [{'metadata': {'row': i}, 'source': json.loads(line)}
                   for i, line in enumerate(Path(entry['source']).open())
                   if wanted is None or i in wanted]
        if wanted is not None and {r['metadata']['row'] for r in records} != wanted:
            raise ValueError('A declared protected source row is missing')
        protected[entry['name']] = panel(records, {})
    for entry in protocol['normalized_protected_panels']:
        records = read_jsonl(Path(entry['records']))
        cases = [case for path in entry['reviews'] for case in read_json(Path(path))['cases']]
        reviews = {case['source_row']: case for case in cases}
        if (len(reviews) != len(cases) or set(reviews) != {r['metadata']['row'] for r in records}
                or any(reviews[r['metadata']['row']]['family'] != r['metadata']['family']
                       for r in records)):
            raise ValueError('Prior reviewed targets do not bind to their original sources')
        protected[entry['name']] = panel(records, reviews)
    bodies, titles, public_groups = public_sources(protocol['public_histories'])
    selected, rejected, family_panels = choose(
        protocol, frozen['order'], native, protected, bodies, titles)
    views = visible_dev(selected, native)
    summary = {}
    for role, quotas in protocol['quotas'].items():
        counts = Counter(str(e['native_support_titles']) for e in selected if e['split'] == role)
        summary[role] = {'families': sum(counts.values()), 'native_support_counts': dict(counts),
                         'shortfall': {k: count - counts[k] for k, count in quotas.items()}}
    selected_panels = {e['family']: native_panel([native[i] for i in e['source_rows']])
                       for e in selected}
    report = {'status': 'NEW_EVALUATION_SOURCE_ROLES_FIXED;REVIEW_AND_EXPOSURE_CHECKS_PENDING',
        'selection': selected, 'rejected': rejected, 'summary': summary,
        'native_rows': len(native), 'native_families': len(groups),
        'old_excluded_families': len(protocol['old_excluded_families']),
        'protected_panels': {name: {k: len(v) for k, v in value.items()}
                             for name, value in protected.items()},
        'current_public_source_groups': public_groups,
        'whole_family_background_components': components(
            {f: p['pool'] for f, p in family_panels.items()}),
        'selected_question_background_components': components(
            {f: p['pool'] for f, p in selected_panels.items()}),
        'dev_visible_pools_exported': len(views), 'confirmation_visible_pools_exported': 0,
        'native_answer_values_used': False, 'source_semantic_labels_generated': False,
        'model_calls': 0, 'old_source_files_or_roles_changed': False,
        'scope': protocol['scope'], 'privacy': protocol['privacy'],
        'interpretation': 'Native support counts are strata, not reviewed proof lengths. '
            'Only declared literal/native-and-reviewed-target boundaries were checked. '
            'Background sharing is reported and does not imply effective sample size. '
            'Final method/settings freeze and complete historical/auxiliary exposure '
            'reconciliation remain required before confirmation inference.'}
    return report, views


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('protocol', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    result, views = prepare(read_json(args.protocol))
    (args.output / 'dev-source-review-inputs.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in views))
    result.update(protocol=str(args.protocol.resolve()), ledger_recorded=False,
                  cpu_seconds_pending=time.process_time() - started, no_sha_validation=True)
    write_json(args.output / 'allocation.json', result)
    print(result['status'], result['summary'], 'rejected', len(result['rejected']))


if __name__ == '__main__':
    main()
