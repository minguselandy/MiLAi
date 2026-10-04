"""X1 fixed-proposal reviewer comparison; no business or semantic Store is opened."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import digest, read_json, write_json
from milai_lab.harness.contextual_artifacts import (
    BudgetExceeded,
    RunLimits,
    Trace,
    entry_budget,
    http_budget_scope,
)
from milai_lab.memory.functional_state import FunctionalRejection, FunctionalReviewRejection
from milai_lab.methods.functional_support_review import (
    review_formation_support,
    review_revision_support,
)
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalQueue, FunctionalVLLMClient
from milai_lab.runners.functional import frozen, prepare


def driver_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def totals(budget: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({key: budget[key]
        for key in ('generation_requests', 'generation', 'embedding')})


def prepare_probe(root: Path, config: Path, inputs: Path, labels: Path) -> dict[str, Any]:
    fixture = read_json(inputs)
    if set(fixture) != {'schema', 'cases'} or fixture['schema'] != 'post_r52_x1_inputs_v1':
        raise ValueError('X1_INPUT_SCHEMA_INVALID')
    cases = fixture['cases']
    if len(cases) != 24 or len({row['id'] for row in cases}) != 24:
        raise ValueError('X1_REQUIRES_24_UNIQUE_PROPOSALS')
    for row in cases:
        if set(row) != {'id', 'matter_id', 'stage', 'evidence'} or row['stage'] not in {
                'formation', 'revision'}:
            raise ValueError('X1_MODEL_INPUT_MUST_EXCLUDE_LABELS_AND_REVIEW_REASONS')
        expected = 'functional_' + row['stage'] + '_evidence_v1'
        if (row['evidence'].get('schema') != expected or
                bool(row['evidence'].get('record_id')) != (row['stage'] == 'revision')):
            raise ValueError('X1_STAGE_DOES_NOT_MATCH_ACTUAL_EVIDENCE_SCHEMA')
    matters = {row['matter_id'] for row in cases}
    if len(matters) != 12 or any(sum(r['matter_id'] == m for r in cases) != 2 for m in matters):
        raise ValueError('X1_REQUIRES_12_PAIRED_MATTERS')
    base = prepare(root, config, fixture_path=inputs)
    value = {'schema': 'post_r52_x1_freeze_v1', 'driver_sha256': driver_sha(),
             'fixture_sha256': base['fixture_sha256'],
             'source_labels_file': str(labels.resolve()),
             'source_labels_sha256': hashlib.sha256(labels.read_bytes()).hexdigest(),
             'conditions': ['r52_comparison', 'single_verdict_v1'],
             'order': 'alternate_first_condition_by_proposal_index',
             'proposals': 24, 'evidence_matters': 12, 'review_conditions': 48,
             'business_store_connected': False, 'semantic_store_connected': False,
             'automatic_retry': False, 'same_family_review': True,
             'status': 'FROZEN_NOT_EXECUTED'}
    path = root / 'x1-freeze.json'
    if path.exists() and read_json(path) != value:
        raise ValueError('X1_EXISTING_FREEZE_CHANGED')
    write_json(path, value)
    return value


def run_probe(root: Path) -> list[dict[str, Any]]:
    base, manifest = frozen(root), read_json(root / 'x1-freeze.json')
    if manifest['driver_sha256'] != driver_sha() or manifest['fixture_sha256'] != (
            base['fixture_sha256']):
        raise ValueError('X1_DRIVER_OR_FIXTURE_CHANGED')
    # Labels are hashed to detect drift, never parsed or delivered to either reviewer.
    if hashlib.sha256(Path(manifest['source_labels_file']).read_bytes()).hexdigest() != (
            manifest['source_labels_sha256']):
        raise ValueError('X1_SOURCE_LABELS_CHANGED')
    settings = base['config']
    host = VLLMConfig(**settings['host'])
    limits = RunLimits(**base['budget_before']['limits'])
    results = []
    with http_budget_scope(settings, limits, client_configs=[asdict(host)]):
        budget = entry_budget(limits, Path(settings['budget_path']))
        for index, row in enumerate(base['fixture']['cases']):
            conditions = manifest['conditions'][::1 if index % 2 == 0 else -1]
            for condition in conditions:
                identity = digest([row['id'], condition])
                folder = root / 'reviews' / identity
                folder.mkdir(parents=True, exist_ok=True)
                result_path = folder / 'result.json'
                binding = {'id': row['id'], 'matter_id': row['matter_id'],
                           'condition': condition, 'evidence_sha256': digest(row['evidence'])}
                if result_path.exists():
                    result = read_json(result_path)
                    if result['binding'] != binding:
                        raise ValueError('X1_RESULT_BINDING_CHANGED')
                    results.append(result)
                    continue
                trace = Trace(folder / 'trace.jsonl', 'post_r52_x1_review')
                before = json.loads(json.dumps(totals(budget.state)))
                client = FunctionalVLLMClient(host, emit=trace, budget=budget,
                                             capacity=HostCapacity(settings['capacity']))
                client.declaration_capacity = HostCapacity({
                    **settings['capacity'], 'enable_thinking': False})
                client.declaration_temperature = 0.0
                client.declaration_tool_names = frozenset({
                    'review_formation_support', 'review_revision_support'})
                client.queue = FunctionalQueue(root / 'queue-admission.json',
                                               **settings['queue_limits'])
                model = LangMemRecipeChatModel(client=client, allow_required_tool_choice=True,
                    preserve_tool_reasoning=True, capacity_path=folder / 'admission.json',
                    max_calls_per_message=settings['max_calls_per_message'],
                    generation_admission_profile='durable_shared_v1',
                    tool_schema_communication='shape_feedback_v1')
                model.begin_public_message(identity,
                    admission_phase='resume' if (folder / 'admission.json').exists() else 'start',
                    admission_scope={'owner': 'post-r52-x1-diagnostic',
                        'bank': ['isolated-review', identity], 'session': identity,
                        'request_ref': row['id'], 'request_sha256': binding['evidence_sha256'],
                        'config_sha256': base['config_sha256']})
                status, error_type, error_text = 'review_supported', None, None
                method = review_formation_support if row['stage'] == 'formation' else (
                    review_revision_support)
                terminal_error: Exception | None = None
                with client:
                    try:
                        method(model, folder / 'review-state.json', row['evidence'], trace,
                               comparison=condition == 'r52_comparison',
                               contract='legacy' if condition == 'r52_comparison'
                               else 'single_verdict_v1')
                    except Exception as error:
                        error_type, error_text = type(error).__name__, str(error)
                        status = (error.review_status
                                  if isinstance(error, FunctionalReviewRejection)
                                  else 'review_declined' if isinstance(error, FunctionalRejection)
                                  else 'review_unavailable')
                        if not isinstance(error, (FunctionalRejection, IncompleteChatResponse)):
                            terminal_error = error
                        if isinstance(error, FunctionalReviewRejection) and (
                                error.failure_type == 'BudgetExceeded'):
                            terminal_error = BudgetExceeded(error_text)
                state_path = folder / 'review-state.json'
                review_state = read_json(state_path) if state_path.exists() else None
                if isinstance(review_state, dict) and 'decision' not in review_state:
                    status = 'review_unavailable'
                result = {'binding': binding, 'operational_status': status,
                    'error_type': error_type, 'error': error_text,
                    'review_state': review_state,
                    'budget_before': before, 'budget_after': totals(budget.state),
                    'usage': trace.usage, 'calls_in_condition': model.calls_in_message,
                    'business_store_connected': False, 'semantic_store_connected': False}
                write_json(result_path, result)
                results.append(result)
                print(json.dumps({'id': row['id'], 'condition': condition, 'status': status}),
                      flush=True)
                if terminal_error is not None:
                    raise terminal_error
    write_json(root / 'execution-results.json', results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'run'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--labels', type=Path)
    args = parser.parse_args()
    if args.operation == 'prepare':
        if any(value is None for value in (args.config, args.inputs, args.labels)):
            parser.error('prepare requires --config, --inputs and --labels')
        print(json.dumps(prepare_probe(args.root, args.config, args.inputs, args.labels)))
    else:
        run_probe(args.root)


if __name__ == '__main__':
    main()
