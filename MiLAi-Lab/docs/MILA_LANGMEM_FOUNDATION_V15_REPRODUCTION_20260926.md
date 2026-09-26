# v15 LangMem Foundation 复现入口

v15 已结项为 `COMPLETE_WITH_BASELINE_FAILURES`。最终源码映射 `99fba610b55237aa31de8ad7f25312dc65e847d944b44b3bde1cde572b3e5ef9`，foundation lock SHA `e3b98d9ff15030afeb34eb7548edae3571230f1c20db89766ec7b0c5b12c4090`。研究范围仅为已有 12 例诊断及原始 seed-0 arc0。模型服务保持原设置，适配在客户端完成。[结果](MILA_LANGMEM_FOUNDATION_V15_RESULTS_20260926.md)与[终态清单](../data/manifests/langmem-foundation-v15-results.json)可直接查看，无需再次运行模型。

所有命令从 `MiLAi-Lab/` 执行。安装独立组：

```bash
uv sync --frozen --dev --group baseline-langmem --python 3.11
uv run --no-sync pytest -q tests/unit/test_langmem_foundation.py
```

LangMem 为 `uv.lock` 中的精确 Git 提交；默认 Lab core 不自动加载该组。模型保持 Qwen3.6-35B-A3B-FP8、thinking=false、输出 4096、上下文 65536，每条公开消息最多 12 次尝试，真实请求并发为 1。所有请求进入同一连续账本，累计上限为 null；失败和 unknown 不归零。

从 `configs/langmem-baseline-v1.json` 复制本地配置至 ignored 的 `artifacts/langmem-foundation/`。填写实际 Host／embedding endpoint、tokenizer 目录及 SHA、已有模型身份清单，并为每个独立运行设置新的 trace、checkpoint、业务 journal 和消息容量记录路径。跨进程续接必须使用原配置、run／arm／user／episode 与原路径；新实验使用新 run ID 和空 namespace。原运行的两份配置与 prepare 收据散列在[最终冻结清单](../data/manifests/langmem-foundation-v15-final-freeze.json)中，新路径复现会生成新的配置／运行身份，不冒充原始运行。

长期记忆使用上游 PostgresStore 的独立 Lab 数据库及 1024 维 `content` 索引，thread 使用独立 SQLite checkpointer。通过 `MILAI_LANGMEM_POSTGRES_DSN` 环境变量提供连接，不把凭据写入 Git、公开配置或命令日志。本次使用已有隔离实验 pgvector 服务中的专用数据库；不连接 Product 数据库。

vLLM 无需新增 parser 或 auto-tool-choice 参数。`json_action` 适配器把结构化响应转为 LangChain 的 AIMessage／tool calls，再由固定 LangGraph ReAct 和实际 LangMem 工具执行；普通回答直接结束。原始 native HTTP 400 是失败证据，不能把适配器结果写成 native parser 通过。

已有诊断输入可从 `MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_INPUTS_20260926.md` 的唯一 JSON 代码块逐字恢复，保留末尾换行；文件 SHA 必须为 `a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc`。原 rubric 单独保留，SHA 为 `62ab23a2a15f2ef3b81ecb51a715a19e379d24581b90ade2e9b8c12968a0ebcc`，运行器不读取它。以下恢复规则已与原文件逐字核对：

```bash
uv run --no-sync python - <<'PY'
import hashlib
from pathlib import Path

out = Path('artifacts/langmem-foundation/reproduce-inputs')
out.mkdir(parents=True, exist_ok=True)
for part, expected in (
    ('INPUTS', 'a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc'),
    ('RUBRIC', '62ab23a2a15f2ef3b81ecb51a715a19e379d24581b90ade2e9b8c12968a0ebcc'),
):
    source = Path(f'docs/MILA_CONTEXTUAL_USER_MEMORY_V14_DIAGNOSTIC_{part}_20260926.md').read_text()
    raw = (source.split('```json\n', 1)[1].split('\n```', 1)[0] + '\n').encode()
    assert hashlib.sha256(raw).hexdigest() == expected
    (out / f'{part.lower()}.json').write_bytes(raw)
PY
```

旧 Host 专属的结构字段在 B0 中标 N/A，不凭空新增这些协议；真实消息、业务回执与 Store 内容供人工语义核对。

MERIT 使用 `data/manifests/contextual-memory-v7-e0-selection-final.json` 的固定提交、原生成参数及原 arc／world hash。本地路径变化时制作本地 selection 副本，只调整资源路径并生成新的运行身份。若缺少旧 ignored arc／world，可在固定 MERIT checkout 下，按 manifest 的 `generator_arguments` 调用 `merit.arcs.generate_suite`，只生成已暴露 seed 0 的单 arc；arc 按 `json.dumps(asdict(arc), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()` 保存，world 按 `arc.make_world().dump_json().encode()` 保存。两份 SHA 必须分别为 `32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f` 和 `221f4be1976ff8bc44ddc97b121dea6e15c22d79eff15dfe551a914342569b29`；将本地 selection 的 `external_root`、`private_artifacts.arc`、`private_artifacts.initial_world` 指向实际资源。prepare 会再次核对原源码及这些字节。

禁止换题、读新 seed 或把 gold、checker 参数和未来消息传给模型。旧 contextual runtime 只作 reference，不导入其 Host 或维护循环。

spike 的普通回答示例：

```bash
uv run --no-sync --group baseline-langmem python tools/run_langmem_foundation.py \
  --config artifacts/langmem-foundation/local-config.json \
  --stage spike-s1 --run fresh-spike --user fixture-user --episode plain \
  --message 'What is 2 + 2? Reply in one short sentence.' \
  --result artifacts/langmem-foundation/s1.json
```

中断后使用相同配置和 scope，加 `--resume` 并省略 `--message`，从 checkpoint 继续。已保存的业务结果按原 call 身份交付；pending 且没有结果的动作标 unknown，需原世界查询或原动作幂等能力核对，不能盲目重做，也不宣称通用 exactly-once。

以下生成可用的正式本地配置，沿用锁中的模型／容量身份。`/cra/qwen36-35B` 改成实际相同 tokenizer 所在目录；Host／embedding endpoint 可按所在环境修改。操作前将模型清单、元数据和服务参数与 lock 核对，不能仅凭同名服务认为权重相同。prepare 负责源码／工具／配方／输入校验，不替代部署身份检查。原大权重未变化且已有合法清单时无需重复散列全部权重。

```bash
uv run --no-sync python - <<'PY'
import copy
import json
from pathlib import Path

lock = json.loads(Path('data/locks/langmem-foundation.lock.json').read_text())
template = json.loads(Path('configs/langmem-baseline-v1.json').read_text())
for mode in ('diagnostic', 'merit'):
    root = Path(f'artifacts/langmem-foundation/reproduce-{mode}')
    root.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(template)
    config['capacity'] = {**lock['capacity'], 'tokenizer_path': '/cra/qwen36-35B'}
    config['model_identity'] = lock['model_identity']
    for key, name in {
        'trace_path': 'trace.jsonl',
        'checkpoint_path': 'checkpoints.sqlite',
        'business_journal_path': 'spike-journal.json',
        'message_capacity_path': 'message-capacity.json',
        'spike_world_path': 'spike-world.json',
    }.items():
        config[key] = str(root / name)
    (root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
PY
```

这段仅用于新复现；恢复既有任务时不要重写 config。两组运行使用同一连续 budget_path，旧账本有内容时继续追加，不清零。独立复现环境从自身空账本开始，其计数不替代本次已封存成本。每次新的独立实验同时换目录和下述 run ID，已完成的同一 run 不用于重复取分。

先离线 prepare。以下使用原 selection；如已按上文迁移资源路径，两处都改为同一个本地 selection 副本：

```bash
for mode in diagnostic merit; do
  uv run --no-sync --group baseline-langmem python tools/prepare_langmem_foundation.py \
    --config "artifacts/langmem-foundation/reproduce-${mode}/config.json" \
    --merit-selection data/manifests/contextual-memory-v7-e0-selection-final.json \
    --diagnostic-inputs artifacts/langmem-foundation/reproduce-inputs/inputs.json \
    --diagnostic-freeze data/manifests/contextual-memory-v14-diagnostic-freeze.json \
    --output "artifacts/langmem-foundation/reproduce-${mode}/prepared.json"
done
```

真实模型阶段需要预先在当前进程环境提供 `MILAI_LANGMEM_POSTGRES_DSN`，指向专用 Lab 数据库；不要把秘密粘进命令或文档。按顺序执行，真实请求并发保持 1：

```bash
uv run --no-sync --group baseline-langmem python tools/run_langmem_foundation.py \
  --config artifacts/langmem-foundation/reproduce-diagnostic/config.json \
  --prepared artifacts/langmem-foundation/reproduce-diagnostic/prepared.json \
  --stage v15-reproduce-diagnostic --run v15-reproduce-diagnostic-01 \
  --diagnostic-inputs artifacts/langmem-foundation/reproduce-inputs/inputs.json \
  --diagnostic-freeze data/manifests/contextual-memory-v14-diagnostic-freeze.json \
  --output artifacts/langmem-foundation/reproduce-diagnostic/results

uv run --no-sync --group baseline-langmem python tools/run_langmem_foundation.py \
  --config artifacts/langmem-foundation/reproduce-merit/config.json \
  --prepared artifacts/langmem-foundation/reproduce-merit/prepared.json \
  --stage v15-reproduce-merit --run v15-reproduce-merit-01 \
  --merit-selection data/manifests/contextual-memory-v7-e0-selection-final.json \
  --output artifacts/langmem-foundation/reproduce-merit/results
```

正式运行中断时重用完全相同的命令即可：runner 根据 progress 和 checkpoint 续接待完成消息，不重复插入原用户消息；`--resume` 是上文单消息 spike 的显式入口。identity 改变会在打开状态和请求前拒绝，不能关闭校验继续旧 run。业务 pending 未知仍需原世界核对，不能靠重启绕过。

离线汇总不需要 DSN、模型请求或 Judge：

```bash
for mode in diagnostic merit; do
  uv run --no-sync --group baseline-langmem python tools/summarize_langmem_foundation.py \
    --mode "${mode}" \
    --results "artifacts/langmem-foundation/reproduce-${mode}/results" \
    --trace "artifacts/langmem-foundation/reproduce-${mode}/trace.jsonl" \
    --run "v15-reproduce-${mode}-01" \
    --budget artifacts/langmem-foundation/v15-budget.json \
    --output "artifacts/langmem-foundation/reproduce-${mode}/summary.json"
done
```

汇总器输出执行／中断分母和逐 episode／public message 的 input/output、embedding、unknown 与 Provider 墙钟；诊断是否符合原 rubric 仍需人工核对真实回复、工具回执和 Store，不把 TERMINAL 当语义 PASS。原生 MERIT checker 独立评分。温度 0 也不保证逐字或逐调用重现，不可筛掉新的失败。

本次原运行目录为 `artifacts/langmem-foundation/final-diagnostic-r2/` 与 `final-merit-r2/`，run ID 分别为 `v15-b0-diagnostic-r2`、`v15-b0-merit-r2`；这些目录已有 summary，无需再次跑模型。R1 目录没有 `-r2` 后缀，保留完整诊断和 MERIT 中断，不与 R2 拼接。final-freeze 的 READY 状态是执行前时间点，终态以 results manifest 为准。

数据库、第三方源码、模型、完整请求和运行日志保持 ignored，Git 只保存源码、锁、精简清单及报告。默认依赖隔离、8 项窄测试、静态／边界／打包检查已完成；仅查看或发布这些结果不重复测试和模型调用。
