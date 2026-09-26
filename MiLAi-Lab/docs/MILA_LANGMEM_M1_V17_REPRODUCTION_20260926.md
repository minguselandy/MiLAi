# v17 M1 复现入口

本入口对应已完成的 [Goal v17](MILA_LANGMEM_M1_GOAL_v17.md)和[最终结果](MILA_LANGMEM_M1_V17_RESULTS_20260926.md)。最终 R2 已完整运行，状态为 COMPLETE_WITH_M1_LIMITATIONS，决定 PIVOT、暂不进入 M2。范围是 task-local Decision Basis、明确采用实际交付证据以及程序 recheck。M2/Attention、新 seeds 和正式 matched comparison 不在本轮。

以下命令从 `MiLAi-Lab/` 执行。v16 原结果在 commit `3676c511f4c4087453d5bbf54cea3514e57fd948`；其 B1/foundation lock 保留原字节。当前共享实现由新 `data/locks/milai-m1-v17.lock.json` 校验，不改旧锁使其通过新源码。

## 环境与检查

沿用原 optional LangMem 依赖，模型和服务参数不改变：

```bash
uv sync --frozen --dev --group baseline-langmem --python 3.11
```

Host 为 Qwen3.6-35B-A3B-FP8，thinking=false，输出 4096、上下文 65536、每公开消息最多 12 次尝试、并发 1；embedding 为 bge-m3／1024 维 content 索引。保持原 vLLM image、command、环境及 HostConfig，不为新 JSON envelope 改 parser 或服务。真实 DSN 只在 run 子进程环境中的 `MILAI_LANGMEM_POSTGRES_DSN` 提供，使用原专用 Lab 数据库，不能指向 Product。

零模型 schema 查看：

```bash
uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py schema \
  --fixture data/fixtures/milai_m1_v17_mechanism.json
```

它不调用模型。已有部署 probe 的 3 个实际回执证明 set+calls、clear+answer、null+answer 可生成，全部为结构／decoder 检查，没有执行工具或提交 Basis。查看或发布结果无需重复 probe。默认运行只用普通 ReAct generation，没有 State/reflection 专用调用。

## 配置与输入

从新 template 生成独立运行配置，三组共用持续账本：

```bash
uv run --no-sync python - <<'PY'
import copy
import json
from pathlib import Path

template = json.loads(Path('configs/milai-m1-v17.json').read_text())
foundation = json.loads(Path('data/locks/langmem-foundation.lock.json').read_text())
for mode in ('mechanism', 'diagnostic', 'merit'):
    root = Path(f'artifacts/langmem-m1-v17/reproduce-{mode}')
    root.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(template)
    config['capacity'] = {**foundation['capacity'], 'tokenizer_path': '/cra/qwen36-35B'}
    config['model_identity'] = foundation['model_identity']
    for key, name in {
        'trace_path': 'trace.jsonl',
        'checkpoint_path': 'checkpoints.sqlite',
        'business_journal_path': 'business-journal.json',
        'message_capacity_path': 'message-capacity.json',
        'sidecar_path': 'instrumentation.sqlite',
        'm1_state_path': 'decision-basis.sqlite',
    }.items():
        config[key] = str(root / name)
    (root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
PY
```

实际 endpoint/tokenizer/模型身份必须与锁匹配。已开始的 run 不重新生成配置或清空账本；续接使用相同 run/arm、数据、checkpoint、B1 sidecar、M1 state 和世界。新实验则整体使用新 scope，不能只更改 run ID 绕过 pending 状态。

[机制 fixture](../data/fixtures/milai_m1_v17_mechanism.json)为新建的单一三消息 development 输入，已在任何模型请求前[冻结](../data/manifests/milai-m1-v17-mechanism-freeze.json)。seed 与同 ID update 由显式 `FIXTURE_CONTROLLED_*` 调用执行，经过原 upstream manage_memory 和公开 Store；不是 Host 自主操作，也不是方法中的自动记忆策略。它不预置 Basis、不强制 adoption，模拟业务函数只记录实际参数。

原 12 例和原 MERIT arc0 不重新生成或改写。恢复原诊断 JSON 的方法见 [v16 复现入口](MILA_LANGMEM_PROVENANCE_V16_REPRODUCTION_20260926.md)与其 v15 链接；原输入 SHA `a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc`。MERIT 继续使用原 `contextual-memory-v7-e0-selection-final.json` 及其中已暴露的 arc0/world。数据身份见 [v17 exposed freeze](../data/manifests/milai-m1-v17-exposed-freeze.json)。rubric 只由运行后的独立分析读取。

## 最终冻结后的 prepare/run

prepare 要求新 M1 lock 和源码匹配，零模型：

```bash
uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py prepare \
  --mode mechanism --arm m1 --run v17-reproduce-mechanism-01 \
  --config artifacts/langmem-m1-v17/reproduce-mechanism/config.json \
  --fixture data/fixtures/milai_m1_v17_mechanism.json \
  --mechanism-freeze data/manifests/milai-m1-v17-mechanism-freeze.json \
  --output artifacts/langmem-m1-v17/reproduce-mechanism/prepared.json

uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py prepare \
  --mode diagnostic --arm m1 --run v17-reproduce-diagnostic-01 \
  --config artifacts/langmem-m1-v17/reproduce-diagnostic/config.json \
  --diagnostic-inputs artifacts/contextual-user-memory/v14-v1-spec/inputs.json \
  --diagnostic-freeze data/manifests/contextual-memory-v14-diagnostic-freeze.json \
  --output artifacts/langmem-m1-v17/reproduce-diagnostic/prepared.json

uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py prepare \
  --mode merit --arm m1 --run v17-reproduce-merit-01 \
  --config artifacts/langmem-m1-v17/reproduce-merit/config.json \
  --merit-selection data/manifests/contextual-memory-v7-e0-selection-final.json \
  --output artifacts/langmem-m1-v17/reproduce-merit/prepared.json
```

以下产生真实请求。按机制诊断、原 12 例、原 arc0 顺序执行，必须先完成 V0、正式 lock/freeze 与空 namespace 核对：

```bash
uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py run \
  --mode mechanism --arm m1 --run v17-reproduce-mechanism-01 \
  --stage v17-reproduce-mechanism \
  --config artifacts/langmem-m1-v17/reproduce-mechanism/config.json \
  --prepared artifacts/langmem-m1-v17/reproduce-mechanism/prepared.json \
  --fixture data/fixtures/milai_m1_v17_mechanism.json \
  --mechanism-freeze data/manifests/milai-m1-v17-mechanism-freeze.json \
  --output artifacts/langmem-m1-v17/reproduce-mechanism/results

uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py run \
  --mode diagnostic --arm m1 --run v17-reproduce-diagnostic-01 \
  --stage v17-reproduce-diagnostic \
  --config artifacts/langmem-m1-v17/reproduce-diagnostic/config.json \
  --prepared artifacts/langmem-m1-v17/reproduce-diagnostic/prepared.json \
  --diagnostic-inputs artifacts/contextual-user-memory/v14-v1-spec/inputs.json \
  --diagnostic-freeze data/manifests/contextual-memory-v14-diagnostic-freeze.json \
  --output artifacts/langmem-m1-v17/reproduce-diagnostic/results

uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py run \
  --mode merit --arm m1 --run v17-reproduce-merit-01 \
  --stage v17-reproduce-merit \
  --config artifacts/langmem-m1-v17/reproduce-merit/config.json \
  --prepared artifacts/langmem-m1-v17/reproduce-merit/prepared.json \
  --merit-selection data/manifests/contextual-memory-v7-e0-selection-final.json \
  --output artifacts/langmem-m1-v17/reproduce-merit/results
```

中断应保留错误回执、原进度、费用和状态。completed turn 重交付不新写 Basis/业务/memory；主操作已进入而完成结果未知时不得自动再执行。非法 delta 与普通工具参数错误分别记录，不将它们改造成语义 action gate。

## 只读查看与解释

```bash
uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py summary \
  --state artifacts/langmem-m1-v17/reproduce-mechanism/decision-basis.sqlite

uv run --no-sync --group baseline-langmem python tools/run_milai_m1.py query \
  --state artifacts/langmem-m1-v17/reproduce-mechanism/decision-basis.sqlite \
  --table events

uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py summary \
  --sidecar artifacts/langmem-m1-v17/reproduce-mechanism/instrumentation.sqlite
```

M1 state 与 B1 instrumentation 分开，均通过 request/generation/call/准确 ref 连接。短 handle 只在其冻结请求映射内有意义；continued ref 不是重新读取正文。Recheck 表示准确版本发生变化，不表示旧 decision 为假；ack 必须能连到实际新材料和合法 Host delta。

成本从原 Provider usage、完整请求/响应和状态事件独立统计。[评价协议](../data/manifests/milai-m1-v17-evaluation-protocol.json)固定 activation、churn、selectivity、gap 和 token 口径。原状态片段的 tokenizer tokens 与完整 billed tokens 分列；普通 ReAct 请求数可以变化，但没有独立 State/reflection 请求。生成失败、unknown 预留和 decoder probe 都留在 v17 连续账本，不能清零后只报成功运行。

## 已交付身份与离线复核

最终 38 文件 mapping 为 `392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f`；M1 lock SHA `d03779620ab8a15c3da7902765b9e477af0207257f809046826e35ee80fceb02`；final freeze SHA `e263aa177869abf63c1c4faaea55f7a9c00b77960ddf241e304a99f112ffc1df`。真实运行目录为 ignored `artifacts/langmem-m1-v17/final-{mechanism,diagnostic,merit}-r2`，run ID 是 `v17-m1-{mode}-r2`，arm=m1；不是上方示例的 reproduce 命名。

每组保留 config、prepared、process receipt、trace、独立 instrumentation/decision-basis SQLite、checkpoint、业务 journal 和 results。`m1-analysis.json` 保存逐请求候选/采用、Context/delta token 数及准确交付核对；`manual-semantic-review.json` 与根目录 `manual-basis-review.json` 是离线人工评价，不交给 runner。公开汇总在 [results manifest](../data/manifests/milai-m1-v17-results.json)与[cost manifest](../data/manifests/milai-m1-v17-cost-summary.json)。

成本复核遍历两个 decoder 目录及 R1/R2 六份正式 trace 的 vllm_response：chat/completions 共 101、input 92672、output 9138，embeddings 28 次／916 tokens，与持续账本一致。Context 取每个 `m1_decision_context` 的实际 text；delta 取对应原始响应 JSON 的 decision_delta 字段原子片段，以同一固定 tokenizer 编码。事件中 SET 计 semantic revision，CLEARED/NO_STATE_CHANGE/RECHECK_ACKNOWLEDGED 分开；按 user/task 重放 delta 才能统计 null 后仍存在的 Basis。

原 R1 的宽松 schema 允许非法 clear 多字段，引发中断。完整 R1 身份在[失败 manifest](../data/manifests/milai-m1-v17-r1-failure.json)，ignored `r1-frozen-source/`、`r1-lock.json`、`r1-final-freeze.json` 保留原源码。最终 R2 只将生成 shape 对齐严格 reducer；未改提示或服务。不要用当前锁启动原 R1 continuation，也不要把成功片段并入 R2。旧 v16 则使用其固定历史 commit。

窄验证记录分别为 `v0-checks.json`、`r2-schema-checks.json`、`package-checks.json` 和 `v0-supplement.json`：7 项 M1＋1 项 B1 parity，1 项 schema 修复测试，相关静态/边界通过；唯一 build 对应 R1 包含性，后补机械检查发生在 R2 后。查看结果或发布无需重跑。
