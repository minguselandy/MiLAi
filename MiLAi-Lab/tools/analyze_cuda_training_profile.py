"""Compare actual matched P0 fits, FP32 evaluations and saved-weight reloads."""
from __future__ import annotations

import argparse
import math
import statistics
import time
from collections import Counter
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from retrieval_mixture import project_mixed_row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    started = time.process_time()
    root = args.root
    data = read_jsonl(root / 'p0-data/train.jsonl')
    plan = read_json(root / 'p0-plan.json')
    report = {'source_commit': plan['source_commit'], 'rows_each': len(data), 'arms': {},
              'profile_only': True, 'no_sha_validation': True}
    initial, final = {}, {}
    from safetensors import safe_open

    for precision in ('float32', 'bf16'):
        fit, reload = root / f'p0-{precision}', root / f'p0-{precision}-reloaded'
        run, replay = read_json(fit / 'run.json'), read_json(reload / 'run.json')
        assert run['status'] == replay['status'] == 'COMPLETED'
        assert run['optimizer_updates'] == 32 and run['train_sequence_rows'] == 512
        assert run['train_device_forwards'] == run['train_batch_forwards'] == 256
        assert replay['completed_states'] == 512 and run['parallel_mode'] == 'single'
        assert set(run['parameter_dtypes']) == {'torch.float32'}
        lengths = read_json(fit / 'lengths.json')
        assert all(r['state_tokens_dropped'] == r['head_tokens_dropped'] == 0
                   for records in lengths.values() for r in records)
        initial[precision] = [read_json(fit / 'train/0' / f'{i}.json') for i in range(512)]
        final[precision] = [read_json(fit / 'train/32' / f'{i}.json') for i in range(512)]
        reloaded = [read_json(reload / 'calls' / str(i) / 'output.json') for i in range(512)]
        for i, row in enumerate(data):
            projected = project_mixed_row(row, run['operation_state'])
            assert read_json(reload / 'calls' / str(i) / 'input.json') == {
                k: projected[k] for k in ('state', 'questions')}
        for outputs in (initial[precision], final[precision], reloaded):
            assert all(math.isfinite(v) for p in outputs for v in p['logits'].values())
        margin_drift = []
        flips = []
        for i, (before, after) in enumerate(zip(final[precision], reloaded, strict=True)):
            assert before['input_tokens'] == after['input_tokens']
            ordered = sorted(before['logits'], key=before['logits'].__getitem__, reverse=True)
            left, right = ordered[:2]
            margin = before['logits'][left] - before['logits'][right]
            after_margin = after['logits'][left] - after['logits'][right]
            margin_drift.append(abs(after_margin - margin))
            if before['choice'] != after['choice']:
                flips.append({'index': i, 'before_margin': margin,
                              'before': before['choice'], 'after': after['choice']})
        profile = read_jsonl(fit / 'update-profile.jsonl')
        steady = profile[4:]
        compute = read_json(fit / 'compute.json')
        weights_path = str(fit / 'checkpoint/model.safetensors')
        with safe_open(weights_path, framework='pt', device='cpu') as f:
            export_dtypes = dict(Counter(f.get_slice(k).get_dtype() for k in f.keys()))
        report['arms'][precision] = {
            'fit': str(fit.resolve()), 'reload': str(reload.resolve()),
            'compute': compute, 'steady_updates': len(steady),
            'steady_mean_update_seconds': statistics.mean(r['wall_seconds'] for r in steady),
            'steady_tokens_per_second': (sum(r['input_tokens'] for r in steady)
                                         / sum(r['wall_seconds'] for r in steady)),
            'padding_ratio': (run['train_padded_input_tokens'] / run['train_input_tokens']),
            'reload_argmax_flips': flips,
            'reload_max_margin_difference': max(margin_drift),
            'reload_median_margin_difference': statistics.median(margin_drift),
            'actual_export_weight_dtypes': export_dtypes,
            'loaded_weight_dtype': replay['loaded_weight_dtype'],
            'max_observed_train_tokens': max(r['sequence_tokens'] for r in lengths['train']),
            'encoder_config_position_limit': run['encoder_max_position_embeddings'],
            'precision': precision, 'loss_parameter_dtype': run['parameter_precision'],
            'tf32_matmul': run['tf32_matmul'], 'tf32_cudnn': run['tf32_cudnn'],
            'attention_backend': run['attention_backend'],
            'history': read_json(fit / 'history.json'),
        }
    for file in ('training-windows.json', 'option-orders/1.json'):
        assert read_json(root / 'p0-float32' / file) == read_json(root / 'p0-bf16' / file)
    assert all(a['choice'] == b['choice'] for a, b in zip(
        initial['float32'], initial['bf16'], strict=True))
    report.update(
        initial_argmax_agreement=512,
        final_argmax_agreement=sum(a['choice'] == b['choice'] for a, b in zip(
            final['float32'], final['bf16'], strict=True)),
        training_speed_ratio_fp32_over_bf16=(
            report['arms']['float32']['steady_mean_update_seconds'] /
            report['arms']['bf16']['steady_mean_update_seconds']),
        scope='One representative TRAIN profile, including observed inputs beyond8192. '
              'Successful execution does not validate effective12k context or task benefit. '
              'Export rounds FP32 parameters to FP16. Reserved memory includes allocated. '
              'The first4 updates remain in total cost but are excluded from steady throughput.',
        cpu_seconds_pending=time.process_time() - started,
    )
    write_json(root / 'p0-analysis.json', report)
    print('P0 matched32 and both512-row reloads verified; speed ratio',
          report['training_speed_ratio_fp32_over_bf16'])


if __name__ == '__main__':
    main()
