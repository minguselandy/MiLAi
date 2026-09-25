# v14 ordinary 的最小复现入口

[本轮结果](CONTEXTUAL_USER_MEMORY_V14_RESULTS_20260926.md)为 IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES。下列命令复现有限开发场景，不承诺通过；不要因失败换题或覆盖旧运行。所有命令在 MiLAi-Lab 下执行，使用现有锁文件的 Python 环境。

## 1. 准备原生环境与身份

需要本地 Qwen3.6-35B-A3B-FP8、bge-m3、tokenizer，以及可用的 vLLM Host／embedding 服务。本轮 Host 为 vLLM 0.27.1／xgrammar 0.2.3、thinking=false、prefix caching=false。使用 MERIT 官方提交 `293933d96b1d1849e1f20d1bb324def5de9ed33f`；已提交选择固定 base_seed=0 的原 arc0。这是暴露回归，不是新测试样本。

```bash
export MILAI_MERIT_ROOT=/path/to/pinned/MERIT
export MILAI_HOST_DIR=/path/to/Qwen3.6-35B-A3B-FP8
export MILAI_EMBED_DIR=/path/to/bge-m3

.venv/bin/python tools/prepare_contextual_v9.py \
  --template configs/contextual-memory-v14-notes-template.json \
  --output-dir artifacts/contextual-user-memory/v14-reproduce \
  --merit-root "$MILAI_MERIT_ROOT" \
  --host-dir "$MILAI_HOST_DIR" \
  --embedding-dir "$MILAI_EMBED_DIR" \
  --embedding-tokenizer "$MILAI_EMBED_DIR/tokenizer.json" \
  --host-url http://127.0.0.1:7860/v1/ \
  --embedding-url http://127.0.0.1:7861/v1/ \
  --budget-path artifacts/contextual-user-memory/v14-reproduce-budget.json
```

准备器不调用生成模型；散列源码、配置、模型及 tokenizer，重建并核对原始 arc/world。路径改变会产生新的配置字节身份，不能冒充报告中的旧运行。现有开发继续使用原连续账本；上例的新账本只供独立复现，不能用于抹掉本轮 80 次请求的历史。

## 2. 原样提取诊断输入并冻结

公开输入与 rubric 各只有一个 JSON 代码块，下面原样恢复字节，并要求当前运行源码匹配最终映射。rubric 只交给事后评审者，runner 不读取它。

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path
from milai_lab.harness.contextual_artifacts import digest, write_json

base = Path('artifacts/contextual-user-memory/v14-reproduce')
spec = base / 'diagnostic-spec'
spec.mkdir()
for name, filename in (
    ('inputs', 'MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_INPUTS_20260926.md'),
    ('rubric', 'MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_RUBRIC_20260926.md'),
):
    text = (Path('docs') / filename).read_text()
    payload = text.split('```json\n', 1)[1].split('```', 1)[0]
    (spec / f'{name}.json').write_bytes(payload.encode())

final = json.loads(Path('data/manifests/contextual-memory-v14-final-freeze.json').read_text())
original = json.loads(Path('data/manifests/contextual-memory-v14-diagnostic-freeze.json').read_text())
prepared = json.loads((base / 'freeze.json').read_text())
config = json.loads((base / 'config.json').read_text())
assert prepared['source_mapping_sha256'] == final['source_mapping_sha256']
for name in ('inputs', 'rubric'):
    actual = hashlib.sha256((spec / f'{name}.json').read_bytes()).hexdigest()
    assert actual == original[f'{name}_file_sha256']
write_json(spec / 'freeze.json', {
    'inputs_file_sha256': original['inputs_file_sha256'],
    'config_digest': digest(config),
    'source_sha256': prepared['source_sha256'],
    'runner_sha256': prepared['source_sha256']['tools/run_contextual_semantic_v14.py'],
})
PY

.venv/bin/python tools/run_contextual_semantic_v14.py \
  --inputs artifacts/contextual-user-memory/v14-reproduce/diagnostic-spec/inputs.json \
  --config artifacts/contextual-user-memory/v14-reproduce/config.json \
  --freeze artifacts/contextual-user-memory/v14-reproduce/diagnostic-spec/freeze.json \
  --output artifacts/contextual-user-memory/v14-reproduce/v1-d11 \
  --case d11
```

加 `--prepare-only` 可只核对身份；省略 `--case` 会执行全部 12 个实例，应只在有明确完整复核目的时使用。本轮最终源码实际仅复核 d11，其他 V1 结果来自已声明的历史源码轮次。每例从空库开始，两会话按正式边界关闭并重开；无强制持久化标签，工具是明确的本地虚构样例。

## 3. 完整原始 arc0

```bash
.venv/bin/python tools/run_contextual_merit.py \
  --selection artifacts/contextual-user-memory/v14-reproduce/selection.json \
  --config artifacts/contextual-user-memory/v14-reproduce/config.json \
  --freeze artifacts/contextual-user-memory/v14-reproduce/freeze.json \
  --output artifacts/contextual-user-memory/v14-reproduce/v2-arc0
```

加 `--prepare-only` 不调用模型；正式命令从原始世界和空记忆运行完整五集七条消息。保持单控制器、并发 1。输出逐集快照、原始回答、真实业务回执、维护处置及连续费用。已有 run data 的目录不能直接重跑；中断须先检查真实进程与已保存 intent/result，使用同身份 RuntimeStore 恢复，不重复已发生业务。

人工评审依照隔离 rubric 和 Goal G1–G4，核对首次边界实际卡／来源、后续读取、真实 answer、业务日志及当前正文。Host complete 和 native success 均不能代替这些检查。本轮预期可重现的是方法与输入身份，不保证随机后端生成逐字一致；任何新结果及费用另行保留。

V3 当前不得作为通过证据运行：V1/V2 门槛未满足。[exposure 规则](../data/manifests/contextual-memory-v14-exposure-rule.json)保留已暴露 seeds 0/1/2 和未来选样规则，没有生成 seeds 3/4。

## 4. 窄的离线检查入口

仅当对应实现变更需要核验时运行，不为发布重复执行：

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_contextual_turn_maintenance.py::test_frontier_requires_explicit_disposition_and_actual_action_receipt \
  tests/unit/test_contextual_turn_maintenance.py::test_task_write_does_not_settle_future_use_of_its_source \
  tests/unit/test_contextual_runtime_recovery.py::test_v5_prior_success_requires_current_explicit_source_delivery \
  tests/unit/test_contextual_host_adapter.py::test_v5_requires_grounded_literal_use_for_issued_handle_in_durable_prose \
  tests/unit/test_contextual_host_adapter.py::test_v5_host_checks_new_revision_prose_without_rejecting_inherited_text
```

这些 scripted Host 检查只证明确定性合同，不是模型语义成绩。完整检查范围、部署语法探针、分轮源码和全部费用见结果报告及清单。原始 trace、数据库、模型和语料继续 ignored；复现无需 Product 更改。
