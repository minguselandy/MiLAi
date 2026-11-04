"""Audit paired unit/relative supervision and nominate from a closed full curve."""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from analyze_conditional_scale_fit import validate_applicability_prediction
from analyze_operation_curve import saved_tensor_dtypes, validate_prediction
from conditional_training import conditional_change_targets, conditional_training_groups
from evaluate_bounded_laya import score_applicability_predictions
from milai_lab.datasets.conditional_applicability import score_condition_pairs
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_feedback import score_feedback
from retrieval_mixture import mixture_event_weights, score_mixed_predictions
from train_bounded_laya import state_option_seed, training_microbatches


def family_balanced_accuracy(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Mean each label inside family, then labels, then families; unknown has no vote."""
    values: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for row, prediction in zip(rows, predictions, strict=True):
        target = row['gold'].get('applicability', {}).get('probabilities', {})
        if not target:
            continue
        label = max(target, key=target.__getitem__)
        values[row['metadata']['family']][label].append(int(prediction['choice'] == label))
    if any(set(v) != {'satisfies', 'does_not_satisfy'} for v in values.values()):
        raise ValueError('The declared balanced dev panel requires both labels per family')
    by_family = {family: sum(sum(xs) / len(xs) for xs in labels.values()) / 2
                 for family, labels in values.items()}
    return {'families': len(by_family), 'by_family': by_family,
            'family_macro_balanced_accuracy': sum(by_family.values()) / len(by_family)}


def nominate(points: list[dict[str, Any]], expected_updates: list[int]) -> dict[str, Any] | None:
    """One trained nominee under the predeclared retention gate; update0 stays separate."""
    if [p['update'] for p in points] != expected_updates or expected_updates[0] != 0:
        raise ValueError('Nomination requires the entire declared synchronized curve')
    baseline = points[0]['operation_family_macro_acceptance']
    eligible = [p for p in points if p['update'] > 0
                and p['operation_family_macro_acceptance'] >= baseline - .02]
    if any(not math.isfinite(p[k]) for p in points for k in (
            'operation_family_macro_acceptance', 'family_macro_balanced_accuracy')):
        raise ValueError('Nomination needs finite observed metrics')
    return min(eligible, key=lambda p: (-p['family_macro_balanced_accuracy'], p['update'])) \
        if eligible else None


def relative_exposure_audit(
    rows: list[dict[str, Any]], pairs: list[dict[str, Any]],
    stages: list[Any], records: list[dict[str, Any]], coefficient: float,
) -> dict[str, Any]:
    """Check actual supported pair draws and their separate optimizer-loss scale."""
    conditional_training_groups(rows, pairs, 0)  # Check labels, identity and disjoint support.
    targets = conditional_change_targets(rows, pairs)
    expected: list[dict[str, Any]] = []
    for update, window in enumerate([w for _, windows in stages for w in windows], 1):
        micros = training_microbatches(window, 2)
        count = sum(tuple(i for _, i in micro) in targets for micro in micros)
        for micro in micros:
            indices = tuple(i for _, i in micro)
            if indices in targets:
                direction, weight = targets[indices]
                expected.append({'update': update, 'data_pass': micro[0][0],
                    'events': [rows[i]['metadata']['event_id'] for i in indices],
                    'direction': direction, 'family_weight': weight, 'window_change_pairs': count})
    if len(records) != len(expected):
        raise ValueError('Relative loss did not cover exactly the declared training change draws')
    for actual, wanted in zip(records, expected, strict=True):
        if any(actual[k] != value for k, value in wanted.items()):
            raise ValueError('Relative loss changed pair identity, direction, window or weight')
        loss, contribution = actual['relative_loss'], actual['optimizer_contribution']
        if (not math.isfinite(loss) or loss < 0 or not math.isfinite(contribution)
                or not math.isclose(contribution,
                    coefficient * wanted['family_weight'] * loss / wanted['window_change_pairs'],
                    rel_tol=1e-6, abs_tol=1e-9)):
            raise ValueError('Relative loss contribution does not match its declared normalization')
    return {'change_pairs': len(targets), 'actual_pair_draws': len(records),
        'updates': [r['update'] for r in records],
        'optimizer_contribution_sum': sum(r['optimizer_contribution'] for r in records)}


def point_report(
    root: Path, update: int, dev: list[dict[str, Any]], feedback: list[dict[str, Any]],
    lengths: dict[str, Any], pairs: list[dict[str, Any]], semantic: list[dict[str, Any]],
) -> dict[str, Any]:
    results = {}
    predictions = {}
    for split, rows in [('dev', dev), ('feedback-dev', feedback)]:
        folder = root / split / str(update)
        if sorted(int(p.stem) for p in folder.glob('*.json') if p.stem.isdigit()) != list(
                range(len(rows))):
            raise ValueError('The requested evaluation point is not completely observed')
        outputs = []
        for i, (row, length) in enumerate(zip(rows, lengths[split], strict=True)):
            result = read_json(folder / f'{i}.json')
            validator = (validate_applicability_prediction if 'applicability' in row['questions']
                         else validate_prediction)
            validator(row, result, length)
            outputs.append(result)
        predictions[split] = outputs
        if split == 'dev':
            results[split] = score_mixed_predictions(rows, outputs)
            if results[split] != read_json(folder / 'summary.json'):
                raise ValueError('Mixed development aggregates differ from their actual outputs')
        else:
            results[split] = {t: score_feedback(rows, outputs, t) for t in ('answer', 'delivery')}
            summary = read_json(folder / 'summary.json')
            if any(results[split][t] != summary[t] for t in results[split]):
                raise ValueError('Feedback retention scores differ from their actual outputs')
    selected = [(row, pred) for row, pred in zip(dev, predictions['dev'], strict=True)
                if row['metadata']['task'] == 'instruction_applicability']
    rows, preds = [x[0] for x in selected], [x[1] for x in selected]
    balanced = family_balanced_accuracy(rows, preds)
    supported = [r['pair'] for r in semantic
                 if r['source_author_pair_status'] == 'supported_request_condition_change']
    conflicts = [r['pair'] for r in semantic
                 if r['source_author_pair_status'] != 'supported_request_condition_change']
    if sorted((p['left_event'], p['right_event']) for p in [*supported, *conflicts]) != sorted(
            (p['left_event'], p['right_event']) for p in pairs if p['kind'] == 'change'):
        raise ValueError('Semantic changes must partition the fixed compiled change pairs')
    strata = {'supported_change': supported, 'native_label_conflicts': conflicts,
              'stable_positive': [p for p in pairs if p['kind'] == 'stable' and p['left_label']],
              'stable_negative': [p for p in pairs
                                  if p['kind'] == 'stable' and not p['left_label']],
              'unknown': [p for p in pairs if p['kind'] == 'unknown']}
    by_id = {r['metadata']['event_id']: p for r, p in zip(rows, preds, strict=True)}
    changes = []
    for pair in supported:
        a, z = by_id[pair['left_event']], by_id[pair['right_event']]
        margins = [p['logits']['satisfies'] - p['logits']['does_not_satisfy'] for p in (a, z)]
        correct = [p['choice'] == ('satisfies' if pair[side + '_label'] else 'does_not_satisfy')
                   for p, side in [(a, 'left'), (z, 'right')]]
        changes.append({'pair': pair, 'choices': [a['choice'], z['choice']], 'margins': margins,
            'signed_margin': (1 if pair['left_label'] else -1) * (margins[0] - margins[1]),
            'joint_correct': all(correct)})
    origin = {}
    for status in ('known', 'source_author_reviewed'):
        items = [(r, p) for r, p in selected if r['metadata']['label_status'] == status]
        origin[status] = score_applicability_predictions(
            [r for r, _ in items], [p for _, p in items])
    return {'update': update, **balanced,
        'operation_family_macro_acceptance': results['dev']['by_task']['memory_operation'][
            'family_macro_acceptance'], 'mixed_dev': results['dev'],
        'feedback_dev': results['feedback-dev'], 'label_origin': origin,
        'condition_pairs': {name: score_condition_pairs(rows, ps, preds)
                            for name, ps in strata.items()}, 'supported_change_details': changes,
        'evaluation_input_tokens': {split: sum(p['input_tokens'] for p in ps)
                                    for split, ps in predictions.items()}}


def analyze(plan_path: Path, *, initial_only: bool) -> dict[str, Any]:
    plan = read_json(plan_path)
    root, data = Path(plan['job']['output']), Path(plan['data'])
    run = read_json(root / 'run.json')
    argv = plan['job']['argv']
    condition = {'data': str(data), 'base_checkpoint': plan['initialization'],
        'task': 'mixed_retrieval', 'objective': 'set', 'operation_state': 'shared_actions',
        'max_len': 16384, 'head_max_len': 2048, 'batch_size': 2, 'precision': 'float32',
        'physical_gpus': [2, 3], 'reference_compile': False, 'freeze_encoder': False,
        'encoder_lr': float(argv[argv.index('--encoder-lr') + 1]),
        'head_lr': float(argv[argv.index('--head-lr') + 1]),
        'seed': int(argv[argv.index('--seed') + 1]), 'mixture_loss_scale': 1.25,
        'conditional_loss_weight': plan['cross_condition_loss_weight'],
        'evaluate_initial_dev': True,
        'planned_optimizer_updates': plan['optimizer_updates'],
        'evaluation_points': plan['evaluation_points'][1:]}
    if any(run[k] != value for k, value in condition.items()):
        raise ValueError('Native input, initialization or optimization condition changed')
    history = read_json(root / 'history.json')
    expected = plan['evaluation_points']
    if not initial_only and (run['status'] != 'COMPLETED'
                            or [h['optimizer_updates'] for h in history] != expected):
        raise ValueError('Full analysis requires a completed fit and every fixed evaluation point')
    if not initial_only:
        proc = Path('/proc') / str(run['pid']) / 'cmdline'
        if proc.exists() and str(root).encode() in proc.read_bytes().split(b'\0'):
            raise ValueError('The original trainer has not yet released its output')
    dev = read_jsonl(data / 'dev.jsonl')
    feedback = read_jsonl(Path(run['feedback_dev_source']))
    lengths = read_json(root / 'lengths.json')
    if lengths != read_json(plan_path.parent / 'capacity-records-v1.json'):
        raise ValueError('Native complete-input lengths differ from prelaunch admission')
    base = plan_path.parent.parent
    pair_file = base / 'conditional-dev32-review-v1/reviewed-v1/condition-pairs.jsonl'
    semantic = read_json(base / 'conditional-dev32-review-v1/actual-audit-v1.json')['change_audit']
    points = [point_report(root, u, dev, feedback, lengths, read_jsonl(pair_file), semantic)
              for u in ([0] if initial_only else expected)]
    for point in points:
        update = point['update']
        checkpoint = Path(plan['initialization']) if update == 0 else (
            root / 'checkpoints' / f'update-{update}')
        if update:
            saved = read_json(checkpoint / 'rl_agent_config.json')['training']['milai_reader']
            if (saved['optimizer_updates'] != update
                    or any(saved[k] != value for k, value in condition.items())):
                raise ValueError('Saved checkpoint metadata differs from its declared fit point')
        point['checkpoint'] = str(checkpoint)
        point['saved_tensor_dtypes'] = saved_tensor_dtypes(checkpoint / 'model.safetensors')
    closed_status = ('CLOSED_RELATIVE_CONDITION_CURVE_VERIFIED_SAVED_AND_TASK_SELECTION_PENDING'
                     if plan['cross_condition_loss_weight'] else
                     'CLOSED_ORDINARY_UNIT_CURVE_VERIFIED_SAVED_AND_TASK_SELECTION_PENDING')
    status = 'INITIAL_GPU_POINT_VERIFIED_NO_NOMINATION' if initial_only else closed_status
    report = {'status': status,
              'plan': str(plan_path.resolve()), 'points': points, 'nominee': None,
              'mandatory_update0': plan['initialization'], 'model_calls': 0,
              'ledger_recorded': False, 'no_sha_validation': True,
              'scope': 'Native in-memory auxiliary development metrics, separate from persisted '
                  'CPU decisions, final Reader answers, autonomous Host or confirmation.'}
    if initial_only:
        return report
    train = [r for r in read_jsonl(data / 'train.jsonl') if r['gold']]
    weights = [1.25 * w for w in mixture_event_weights(train, read_json(data / 'mixture.json'))]
    for row, actual, weight in zip(train, read_json(root / 'sampling.json'), weights, strict=True):
        if (actual['event_id'] != row['metadata']['event_id'] or actual['weight'] != weight
                or actual['component'] != row['metadata']['component']):
            raise ValueError('Native sampling lost source identity or component/family weights')
    if read_json(root / 'training-windows.json') != read_json(
            plan_path.parent / 'expected-windows-v1.json'):
        raise ValueError('Native windows differ from the admitted paired exposure')
    options = read_json(root / 'option-orders/1.json')
    for row, order in zip(train, options, strict=True):
        question = next(iter(row['questions'].values()))
        expected_order = list(range(len(question['criteria'])))
        rng = random.Random(state_option_seed(0, 1, row['metadata']['state_id']))  # noqa: S311
        rng.shuffle(expected_order)
        if order != (expected_order if len(expected_order) > 1 else None):
            raise ValueError('Actual option order differs from the fixed source-state shuffle')
    capacity = read_json(plan_path.parent / 'capacity-v1.json')
    if (run['train_sequence_rows'] != plan['known_train_rows']
            or run['optimizer_updates'] != plan['optimizer_updates']
            or run['sampled_component_rows'] != plan['train_components']
            or run['train_input_tokens'] != capacity['panels']['train']['total_input_tokens']):
        raise ValueError('Native training exposure differs from the full declared unit pass')
    compute = read_json(root / 'compute.json')
    for split, rows in [('dev', dev), ('feedback-dev', feedback)]:
        if (compute[split + '_sequence_rows'] != len(rows) * len(points)
                or compute[split + '_input_tokens'] != sum(
                    p['evaluation_input_tokens'][split] for p in points)):
            raise ValueError('Recorded evaluation cost differs from actual complete predictions')
    if plan['cross_condition_loss_weight']:
        loss_records = read_jsonl(root / 'conditional-losses.jsonl')
        relative = relative_exposure_audit(train, read_jsonl(data / 'selected-pairs.jsonl'),
            read_json(root / 'training-windows.json'), loss_records,
            plan['cross_condition_loss_weight'])
        if (run['conditional_change_pairs'] != relative['change_pairs']
                or run['conditional_pair_draws'] != relative['actual_pair_draws']):
            raise ValueError('Native relative-pair counters differ from actual loss records')
        ordinary_plan = read_json(Path(plan['ordinary_control_plan']))
        ordinary = Path(ordinary_plan['job']['output'])
        for filename in ('training-windows.json', 'sampling.json', 'option-orders/1.json'):
            if read_json(root / filename) != read_json(ordinary / filename):
                raise ValueError('The matched relative arm changed data exposure or option order')
        old_compute = read_json(ordinary / 'compute.json')
        fields = [k for k in compute if any(k.endswith(suffix) for suffix in (
            '_rows', '_tokens', '_forwards', '_attempts'))]
        if any(compute[k] != old_compute[k] for k in fields):
            raise ValueError('Relative comparison changed measured rows, tokens or model forwards')
        for point in history[1:]:
            last = max(u for u in expected if u < point['optimizer_updates'])
            contribution = sum(r['optimizer_contribution'] for r in loss_records
                if last < r['update'] <= point['optimizer_updates'])
            if not math.isclose(point['conditional_loss_optimizer_mean'],
                    contribution / (point['optimizer_updates'] - last), rel_tol=1e-6, abs_tol=1e-9):
                raise ValueError('Relative history does not match actual optimizer contributions')
        report['relative_exposure'] = relative
        report['ordinary_matched_model_work_verified'] = fields
    nominee = nominate(points, expected)
    report['nominee'] = ({k: nominee[k] for k in ('update', 'checkpoint',
        'family_macro_balanced_accuracy', 'operation_family_macro_acceptance')}
        if nominee is not None else None)
    report['native_exposure'] = {k: run[k] for k in ('optimizer_updates', 'train_sequence_rows',
        'train_input_tokens', 'sampled_component_rows', 'sampled_component_input_tokens')}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--initial-only', action='store_true')
    args = parser.parse_args()
    start = time.process_time()
    report = analyze(args.plan, initial_only=args.initial_only)
    report['cpu_seconds_nested'] = time.process_time() - start
    write_json(args.output, report)
    print(json.dumps({'status': report['status'], 'nominee': report['nominee'],
        'points': [{k: p[k] for k in ('update', 'family_macro_balanced_accuracy',
                    'operation_family_macro_acceptance')} for p in report['points']]}))


if __name__ == '__main__':
    main()
