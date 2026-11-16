"""Compare declared auxiliary model inputs with private native source strings."""
from __future__ import annotations

import argparse
import json
import time
import zipfile
from collections import Counter, defaultdict, deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from audit_source_selection import target_indices
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


class LiteralMatcher:
    """Exact overlapping substring matches, preserving case and whitespace."""

    def __init__(self, patterns: list[str]) -> None:
        self.edges: list[dict[str, int]] = [{}]
        self.failure = [0]
        self.outputs: list[list[int]] = [[]]
        for index, pattern in enumerate(patterns):
            if not pattern:
                raise ValueError('Empty strings are not evidence')
            state = 0
            for char in pattern:
                if char not in self.edges[state]:
                    self.edges[state][char] = len(self.edges)
                    self.edges.append({})
                    self.failure.append(0)
                    self.outputs.append([])
                state = self.edges[state][char]
            self.outputs[state].append(index)
        queue = deque(self.edges[0].values())
        while queue:
            state = queue.popleft()
            for char, child in self.edges[state].items():
                queue.append(child)
                parent = self.failure[state]
                while parent and char not in self.edges[parent]:
                    parent = self.failure[parent]
                self.failure[child] = self.edges[parent].get(char, 0)
                self.outputs[child].extend(self.outputs[self.failure[child]])

    def matches(self, text: str) -> set[int]:
        state = 0
        found = set()
        for char in text:
            while state and char not in self.edges[state]:
                state = self.failure[state]
            state = self.edges[state].get(char, 0)
            found.update(self.outputs[state])
        return found


def strings(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, f'{path}[{index}]')


def audit(protocol: dict[str, Any], output: Path) -> dict[str, Any]:
    cohort = read_json(Path(protocol['cohort_protocol']))
    allocation = read_json(Path(protocol['cohort_allocation']))
    review = read_json(Path(protocol['source_review']))
    cases = {case['source_row']: case for case in review['cases']}
    groups = {g['family']: g for g in read_json(Path(cohort['group_metadata']))}
    minimum = protocol['minimum_sentence_or_reverse_containment_characters']
    with zipfile.ZipFile(cohort['archive']) as archive:
        native = json.load(archive.open(cohort['archive_member']))
    exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    contained: dict[str, list[dict[str, Any]]] = defaultdict(list)
    paragraphs: list[tuple[str, dict[str, Any]]] = []
    source_rows = set()
    for entry in allocation['selection']:
        family = entry['family']
        if entry['whole_family_rows'] != groups[family]['rows']:
            raise ValueError('The fixed whole-family source boundary changed')
        for index in entry['whole_family_rows']:
            row = native[index]
            source_rows.add(index)
            selected = index in entry['source_rows']
            if selected and row['_id'] != entry['question_id']:
                raise ValueError('Selected question no longer binds to its source row')
            base = {'family': family, 'split': entry['split'], 'source_row': index,
                    'selected_question': selected}
            exact[row['question']].append({**base, 'kind': 'exact_query'})
            supported_titles = {fact[0] for fact in row['supporting_facts']}
            reviewed = target_indices(cases[index]) if index in cases else set()
            for paragraph_index, (title, sentences) in enumerate(row['context']):
                body = ' '.join(sentences)
                reference = {**base, 'paragraph_index': paragraph_index,
                    'native_support': title in supported_titles,
                    'source_reviewed_target': paragraph_index in reviewed}
                exact[title].append({**reference, 'kind': 'exact_title',
                                     'short_title_le_2_characters': len(title) <= 2})
                if body:
                    exact[body].append({**reference, 'kind': 'exact_paragraph'})
                    contained[body].append({**reference, 'kind': 'native_paragraph_containment'})
                    paragraphs.append((body, reference))
                for sentence_index, sentence in enumerate(sentences):
                    if len(sentence) >= minimum:
                        contained[sentence].append({**reference,
                            'kind': 'native_sentence_containment',
                            'sentence_index': sentence_index})
    del native
    patterns = list(contained)
    matcher = LiteralMatcher(patterns)
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for panel in protocol['panels']:
        rows = read_jsonl(Path(panel['input_file']))
        if (('expected_rows' in panel and len(rows) != panel['expected_rows'])
                or len({r['metadata']['family'] for r in rows})
                != panel['expected_query_families']):
            raise ValueError('Auxiliary panel size or query-family identity changed')
        reverse: dict[str, list[dict[str, Any]]] = defaultdict(list)
        hits, scanned_fields, scanned_characters = [], 0, 0
        for row_index, row in enumerate(rows):
            aux = {'aux_row': row_index, 'aux_family': row['metadata']['family']}
            for field, value in [*strings(row['state'], 'state'),
                                 *strings(row['questions'], 'questions')]:
                scanned_fields += 1
                scanned_characters += len(value)
                for reference in exact.get(value, []):
                    hits.append({**reference, **aux, 'input_field': field,
                                 'literal_characters': len(value)})
                for match in matcher.matches(value):
                    for reference in contained[patterns[match]]:
                        hits.append({**reference, **aux, 'input_field': field,
                                     'literal_characters': len(patterns[match])})
                if field == 'state.candidate.text' and len(value) >= minimum:
                    reverse[value].append({**aux, 'input_field': field})
        # Prefixes bound the index size; a hit still requires the complete literal body.
        anchors: dict[str, list[str]] = defaultdict(list)
        for value in reverse:
            anchors[value[:minimum]].append(value)
        reverse_patterns = list(anchors)
        reverse_matcher = LiteralMatcher(reverse_patterns)
        for body, reference in paragraphs:
            for match in reverse_matcher.matches(body):
                for value in anchors[reverse_patterns[match]]:
                    if value in body:
                        for aux in reverse[value]:
                            hits.append({**reference, **aux, 'kind': 'aux_candidate_containment',
                                         'literal_characters': len(value)})
        counts = Counter(hit['kind'] for hit in hits)
        role_summary = {}
        for role in ('dev', 'confirmation'):
            own = [h for h in hits if h['split'] == role]
            bodies = [h for h in own if h['kind'] not in {'exact_title', 'exact_query'}]
            role_summary[role] = {
                'matched_families': len({h['family'] for h in own}),
                'selected_question_families': len({h['family'] for h in own
                                                   if h['selected_question']}),
                'native_support_families': len({h['family'] for h in own
                                                if h.get('native_support')}),
                'source_reviewed_target_families': len({h['family'] for h in own
                                                        if h.get('source_reviewed_target')}),
                'exact_query_families': len({h['family'] for h in own
                                             if h['kind'] == 'exact_query'}),
                'body_overlap_families': len({h['family'] for h in bodies}),
                'selected_question_body_overlap_families': len({h['family'] for h in bodies
                                                                if h['selected_question']}),
                'native_support_body_overlap_families': len({h['family'] for h in bodies
                                                             if h['native_support']}),
                'reviewed_target_body_overlap_families': len({h['family'] for h in bodies
                                                             if h['source_reviewed_target']}),
                'kind_counts': dict(Counter(h['kind'] for h in own))}
        run_file = (Path(panel['declared_output']) / 'run.json'
                    if 'declared_output' in panel else None)
        run = read_json(run_file) if run_file is not None and run_file.exists() else None
        summary = {'panel': panel['name'], 'role': panel['role'], 'input_file': panel['input_file'],
            'rows': len(rows), 'families': len({r['metadata']['family'] for r in rows}),
            'scanned_fields': scanned_fields, 'scanned_characters': scanned_characters,
            'matched_input_rows': len({h['aux_row'] for h in hits}), 'kind_counts': dict(counts),
            'source_roles': role_summary, 'declared_model_output_present': run is not None,
            'declared_model_status': run['status'] if run is not None else None,
            'matches_file': str(output / (panel['name'] + '-matches.json'))}
        write_json(Path(summary['matches_file']), {'matches': hits,
            'scope': 'Identifiers, field paths, counts and lengths only; overlapping kinds '
                     'are not independent observations. No source/question/body text or answers.'})
        summaries.append(summary)
    return {'status': 'PRIVATE_AUXILIARY_LITERAL_INPUT_COMPARISON_COMPLETE',
        'native_whole_family_rows': len(source_rows),
        'native_families': len(allocation['selection']),
        'panels': summaries, 'native_answer_values_used_or_emitted': False,
        'confirmation_bodies_or_questions_emitted': False, 'query_reserved64_bodies_opened': False,
        'source_roles_or_training_inputs_changed': False, 'model_calls': 0,
        'scope': protocol['interpretation'], 'privacy': protocol['privacy'],
        'limits': 'Literal title equality is not entity identity. Short title matches are '
                  'flagged. Zero matches do not exclude changed, paraphrased, subspan or '
                  'pretraining exposure. Planned rows are not evidence of executed training.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('protocol', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    result = audit(read_json(args.protocol), args.output)
    result.update(protocol=str(args.protocol.resolve()), cpu_seconds_pending=time.process_time()
                  - started, ledger_recorded=False, no_sha_validation=True)
    write_json(args.output / 'analysis.json', result)
    print(result['status'])
    for panel in result['panels']:
        print(panel['panel'], 'matched rows', panel['matched_input_rows'],
              'dev families', panel['source_roles']['dev']['matched_families'],
              'confirmation families', panel['source_roles']['confirmation']['matched_families'])


if __name__ == '__main__':
    main()
