"""Census protected MuSiQue source dependencies without emitting text or answers.

This extends existing metadata, not old splits or experimental admission. Literal
paragraph and page-title components are reported separately from seed/target
families. Full-population links are retained before any eligibility filtering.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def components(groups: dict[str, set[Any]]) -> list[list[str]]:
    """Connect literal keys, preserving links through excluded/reserved families."""
    parent = {family: family for family in groups}

    def find(family: str) -> str:
        while family != parent[family]:
            parent[family] = parent[parent[family]]
            family = parent[family]
        return family

    owners: dict[Any, str] = {}
    for family, keys in sorted(groups.items()):
        for key in keys:
            if key in owners:
                parent[find(family)] = find(owners[key])
            else:
                owners[key] = family
    result: dict[str, list[str]] = defaultdict(list)
    for family in sorted(groups):
        result[find(family)].append(family)
    return sorted(result.values())


def summarize_components(
    connected: list[list[str]], metadata: dict[str, dict[str, Any]], reserved: set[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for families in connected:
        flags = sorted({flag for family in families for flag in metadata[family]['violations']})
        reserved_members = sorted(reserved.intersection(families))
        rows.append({'families': families, 'family_count': len(families),
            'native_questions': sum(len(metadata[f]['question_ids']) for f in families),
            'source_rows': sum(len(metadata[f]['rows']) for f in families),
            'violations': flags, 'prior_reserved_families': reserved_members,
            'no_recorded_conflict_or_prior_reservation': not flags and not reserved_members})
    return {'components': len(rows),
        'largest_component_families': max(row['family_count'] for row in rows),
        'component_size_counts': dict(Counter(row['family_count'] for row in rows)),
        'components_without_recorded_conflict_or_prior_reservation': sum(
            row['no_recorded_conflict_or_prior_reservation'] for row in rows),
        'groups': rows}


def audit(protocol: dict[str, Any]) -> dict[str, Any]:
    prior = read_json(Path(protocol['prior_boundary']))
    metadata = {g['family']: {**g, 'violations': list(g['violations'])} for g in prior['groups']}
    reserved = {g['family'] for g in read_json(Path(protocol['prior_reservation']))['groups']}
    row_owner = {i: family for family, group in metadata.items() for i in group['rows']}
    if len(row_owner) != sum(len(g['rows']) for g in metadata.values()):
        raise ValueError('Prior candidate families assign a native row more than once')
    public_bodies: set[str] = set()
    public_pages: set[str] = set()
    histories, family_roles, public_positions = set(), defaultdict(set), 0
    for path in protocol['public_histories']:
        for history in read_json(Path(path))['histories']:
            if history['id'] in histories:
                raise ValueError('Public source fixtures repeat a history')
            histories.add(history['id'])
            family_roles[history['source_group']].add(history['split'])
            sources = list(history['sources'])
            for request in history['requests']:
                sources.extend(request.get('sources', []))
                sources.extend(request.get('incoming_sources', []))
            for source in sources:
                public_positions += 1
                public_bodies.add(source['content'])
                if source.get('origin') == 'reference_document':
                    public_pages.add(source['content'].split('\n', 1)[0])
    literal: dict[str, set[Any]] = {f: set() for f in metadata}
    targets: set[tuple[str, str]] = set()
    pages: dict[str, set[Any]] = {f: set() for f in metadata}
    read_rows, observed_ids, public_overlap, title_overlap = set(), defaultdict(set), set(), set()
    public_target_overlap: set[str] = set()
    empty_titles = 0
    with Path(protocol['candidate_source']).open(encoding='utf-8') as stream:
        for index, line in enumerate(stream):
            source = json.loads(line)
            family = row_owner[index]
            read_rows.add(index)
            observed_ids[family].add(source['id'])
            # Native support flags are used only for boundary connectivity, never scores.
            # No answer, decomposition text or question text is used.
            for paragraph in source['paragraphs']:
                title, body = paragraph['title'], paragraph['paragraph_text']
                literal[family].add((title, body))
                if paragraph['is_supporting']:
                    targets.add((title, body))
                if title:
                    pages[family].add(title)
                else:
                    empty_titles += 1
                if title + '\n' + body in public_bodies or body in public_bodies:
                    public_overlap.add(family)
                    if paragraph['is_supporting']:
                        public_target_overlap.add(family)
                if title and title in public_pages:
                    title_overlap.add(family)
    if read_rows != set(row_owner) or any(
        observed_ids[f] != set(g['question_ids']) for f, g in metadata.items()
    ):
        raise ValueError('Actual candidate source differs from prior row/ID membership')
    for family in public_target_overlap:
        metadata[family]['violations'].append('native_target_in_current_public_sources')
    literal_result = summarize_components(components(literal), metadata, reserved)
    target_components = components({family: keys & targets for family, keys in literal.items()})
    target_result = summarize_components(target_components, metadata, reserved)
    any_public_metadata = {f: {**g, 'violations': [*g['violations'], *(
        ['any_literal_paragraph_in_current_public_sources'] if f in public_overlap else [])]}
        for f, g in metadata.items()}
    page_metadata = {f: {**g, 'violations': [*g['violations'], *(
        ['page_title_in_current_public_sources'] if f in title_overlap else [])]}
        for f, g in metadata.items()}
    page_result = summarize_components(components(pages), page_metadata, reserved)
    return {'status': 'PRIVATE_SOURCE_COMPONENT_CENSUS;NOT_NEW_SPLIT_OR_MODEL_ADMISSION',
        'source_rows': len(read_rows),
        'native_questions': sum(len(v) for v in observed_ids.values()),
        'prior_seed_target_families': len(metadata), 'prior_reserved_families': len(reserved),
        'public_histories': len(histories), 'public_source_groups': len(family_roles),
        'public_source_positions': public_positions, 'distinct_public_bodies': len(public_bodies),
        'public_reference_page_titles': len(public_pages),
        'empty_candidate_title_occurrences': empty_titles,
        'families_overlapping_current_public_bodies': len(public_overlap),
        'families_with_native_targets_in_current_public_bodies': len(public_target_overlap),
        'families_overlapping_current_public_page_titles': len(title_overlap),
        'prior_boundary_clean_families': sum(not g['violations'] for g in prior['groups']),
        'seed_target': summarize_components([[f] for f in sorted(metadata)], metadata, reserved),
        'target_to_pool': target_result,
        'target_to_pool_any_public_overlap_sensitivity': summarize_components(
            target_components, any_public_metadata, reserved),
        'literal_pool': literal_result, 'page_title_pool': page_result,
        'distinct_literal_candidate_paragraphs': len(set().union(*literal.values())),
        'distinct_native_support_paragraphs': len(targets),
        'selection_based_on_model_outcomes': False, 'old_splits_and_reservations_changed': False,
        'questions_answers_or_source_bodies_emitted': False, 'model_calls': 0,
        'scope': 'Full candidate graph, including excluded and previously reserved nodes. '
            'Current public fixtures cover registered operation Sources, not every historical '
            'artifact or auxiliary corpus. A component with no recorded conflict is not proven '
            'unseen or semantically independent. Equal page titles diagnose shared source pages; '
            'they do not assert identical versions or paragraphs. Prior groups stay reserved. '
            'Graph connectivity is not an effective sample-size estimate or an automatic '
            'exclusion rule. Native support flags only separate boundary mechanisms. '
            'Current background-only matches are reported separately from native-target '
            'matches; only the explicit any-overlap sensitivity treats both alike. '
            'No new dev/confirmation identities are assigned; no native labels are exported.',
        'remaining': ['Reconcile all historical and auxiliary exposure before final admission.',
            'Freeze final methods and settings before protected inference or semantic review.',
            'Source quality, pretraining exposure and semantic independence remain unproven.']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('protocol', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    result = audit(read_json(args.protocol))
    result.update(protocol=str(args.protocol.resolve()), ledger_recorded=False,
                  cpu_seconds_pending=time.process_time() - started, no_sha_validation=True)
    write_json(args.output / 'audit.json', result)
    print(json.dumps({k: result[k] for k in (
        'status', 'source_rows', 'native_questions', 'prior_seed_target_families',
        'public_source_groups', 'families_overlapping_current_public_bodies')}))
    for name in ('seed_target', 'target_to_pool',
                 'target_to_pool_any_public_overlap_sensitivity',
                 'literal_pool', 'page_title_pool'):
        print(name, {k: v for k, v in result[name].items() if k != 'groups'})


if __name__ == '__main__':
    main()
