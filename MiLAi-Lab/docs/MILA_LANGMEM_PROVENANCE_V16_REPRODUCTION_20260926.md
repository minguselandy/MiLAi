# v16 模型不可见追踪复现入口

最终状态为 COMPLETE_WITH_INSTRUMENTED_BASELINE，G0–G6 通过；详见[结果](MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md)及[精简清单](../data/manifests/langmem-b1-v16-results.json)。范围仅 B1 追踪和原 12 例／20 会话、已暴露 arc0／5 集／7 消息；不启动 Basis、recheck 或 Attention，也不修改 vLLM 设置。

所有命令从 `MiLAi-Lab/` 执行。原 v15 foundation lock 保留原字节，其完整复现使用固定提交 `46b8a925385e7b38a7111c7c32283af0eb28467e`；当前共享源码的改变由独立 `data/locks/langmem-b1.lock.json` 约束，不能改旧 lock 让当前代码假扮旧版本。

源码 mapping 为 `ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea`（27 文件），B1 lock SHA `2098f2708081e1ae23341a301356543cb81e3b2be5fe1614ba487647ac8231a7`。原 12 例与 arc0 已在 `artifacts/langmem-provenance/final-diagnostic-r1/`、`final-merit-r1/` 完整执行，run ID 分别为 `v16-b1-diagnostic-r1`、`v16-b1-merit-r1`，arm 为 `b1_instrumented`。下方 reproduce 路径与 ID 是独立新运行示例，查看既有结果不需要重跑。

## 环境与零模型检查

已通过原 foundation＋新增共 18 项窄测试，以及相关静态／boundary／锁检查。重建环境时沿用锁定可选依赖组，无版本升级：

```bash
uv sync --frozen --dev --group baseline-langmem --python 3.11
uv run --no-sync pytest -q tests/unit/test_langmem_foundation.py tests/unit/test_langmem_provenance.py
```

原 v15 trace 仍在同一环境可用时，同输出 parity 的零模型入口是：

```bash
uv run --no-sync --group baseline-langmem python tools/replay_langmem_provenance_v15.py \
  --output artifacts/langmem-provenance/reproduce-v15-parity
```

该入口依赖原保留回执和 pinned MERIT 世界，固定 ID／时钟／向量仅用于 V0；已经通过的 r3 比较 21/21 生成与 5/5 embedding 请求的实际字节。缺少原 trace 时不要把重新采样当作同输出回放。原始 V0 与必要真实后端恢复检查记录在结果清单中。

这只检查受影响合同。既有通过结果的查看和发布无需重跑；历史全套与全量 benchmark 不属于本轮。真实模型仍为 Qwen3.6-35B-A3B-FP8、thinking=false、输出 4096、上下文 65536、每公开消息 12 次实际尝试、并发 1；embedding 仍为 bge-m3／1024 维 content 索引。

长期 Store 使用既有隔离 Lab PostgresStore，thread checkpoint 和 instrumentation 各自为独立本地 SQLite 文件。`MILAI_LANGMEM_POSTGRES_DSN` 只在 run 的进程环境提供，指向专用 Lab 数据库／角色；不把真实连接串放在命令、Git 或公开配置中。所有原服务参数保持不变，不新增 parser 参数或更换服务容器。

## 新配置与原数据

从 `configs/langmem-b1-v16.json` 复制新运行配置；恢复既有 run 时不要重新生成。以下示例复用公开 lock 中的容量／模型清单身份，tokenizer 目录与 endpoint 按实际环境填写。先核对实际部署与这些身份相同，prepare 不替代服务和大权重身份检查。

```bash
uv run --no-sync python - <<'PY'
import copy
import json
from pathlib import Path

template = json.loads(Path('configs/langmem-b1-v16.json').read_text())
foundation = json.loads(Path('data/locks/langmem-foundation.lock.json').read_text())
for mode in ('diagnostic', 'merit'):
    root = Path(f'artifacts/langmem-provenance/reproduce-{mode}')
    root.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(template)
    config['capacity'] = {**foundation['capacity'], 'tokenizer_path': '/cra/qwen36-35B'}
    config['model_identity'] = foundation['model_identity']
    for key, filename in {
        'trace_path': 'trace.jsonl',
        'checkpoint_path': 'checkpoints.sqlite',
        'business_journal_path': 'business-journal.json',
        'message_capacity_path': 'message-capacity.json',
        'sidecar_path': 'instrumentation.sqlite',
    }.items():
        config[key] = str(root / filename)
    (root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
PY
```

两组运行共用连续 v16 budget_path；已有账本继续追加，单次恢复不重置费用或消息容量。新独立实验要同时更换下述 run ID、配置目录、checkpoint、world 和 sidecar。`b0_control`／`b1_instrumented` 的 namespace 及世界隔离，不读取另一臂学习到的记忆。

原诊断输入与 rubric 可按 [v15 复现说明](MILA_LANGMEM_FOUNDATION_V15_REPRODUCTION_20260926.md)从公开 Markdown 的唯一 JSON 块逐字恢复到 `artifacts/langmem-foundation/reproduce-inputs/`。输入 SHA 为 `a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc`；rubric SHA 为 `62ab23a2a15f2ef3b81ecb51a715a19e379d24581b90ade2e9b8c12968a0ebcc`，仅用于运行后的独立分析，不交给 observer 或模型。

MERIT 使用 `data/manifests/contextual-memory-v7-e0-selection-final.json` 指向的原固定源码、arc 和 world；资源迁移及缺少原 ignored 文件时的恢复方式也见 v15 入口，只生成原已暴露 seed 0。arc SHA `32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f`，world SHA `221f4be1976ff8bc44ddc97b121dea6e15c22d79eff15dfe551a914342569b29`。如制作只调整本地资源路径的 selection 副本，prepare 与 run 必须共同引用同一副本，并记录新配置身份。不要读取新 seeds 或将 checker/gold 混入运行材料。

## 冻结后的准备与运行

正式入口要求新 B1 lock 为 FROZEN，源码和模型可见合同匹配。先做零模型准备：

```bash
uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py prepare \
  --mode diagnostic --arm b1_instrumented --run v16-reproduce-diagnostic-01 \
  --config artifacts/langmem-provenance/reproduce-diagnostic/config.json \
  --diagnostic-inputs artifacts/langmem-foundation/reproduce-inputs/inputs.json \
  --diagnostic-freeze data/manifests/contextual-memory-v14-diagnostic-freeze.json \
  --output artifacts/langmem-provenance/reproduce-diagnostic/prepared.json

uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py prepare \
  --mode merit --arm b1_instrumented --run v16-reproduce-merit-01 \
  --config artifacts/langmem-provenance/reproduce-merit/config.json \
  --merit-selection data/manifests/contextual-memory-v7-e0-selection-final.json \
  --output artifacts/langmem-provenance/reproduce-merit/prepared.json
```

以下阶段产生真实请求，按先诊断后 arc0 执行。需要前述私有 DSN 环境变量，不能把用于打桩的向量或固定 ID 混入正式运行：

```bash
uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py run \
  --mode diagnostic --arm b1_instrumented --run v16-reproduce-diagnostic-01 \
  --stage v16-reproduce-diagnostic \
  --config artifacts/langmem-provenance/reproduce-diagnostic/config.json \
  --prepared artifacts/langmem-provenance/reproduce-diagnostic/prepared.json \
  --diagnostic-inputs artifacts/langmem-foundation/reproduce-inputs/inputs.json \
  --diagnostic-freeze data/manifests/contextual-memory-v14-diagnostic-freeze.json \
  --output artifacts/langmem-provenance/reproduce-diagnostic/results

uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py run \
  --mode merit --arm b1_instrumented --run v16-reproduce-merit-01 \
  --stage v16-reproduce-merit \
  --config artifacts/langmem-provenance/reproduce-merit/config.json \
  --prepared artifacts/langmem-provenance/reproduce-merit/prepared.json \
  --merit-selection data/manifests/contextual-memory-v7-e0-selection-final.json \
  --output artifacts/langmem-provenance/reproduce-merit/results
```

普通中断后使用原配置、原 run/arm 和同一命令，依赖原 progress/checkpoint 续接，不重复插入用户消息。instrumentation 健康错误必须先核对已有见证：不能删除错误标记、用新 run ID 绕过 pending business，或凭当前正文相同补造已确认 revision。主 Store 与 sidecar 不构成原子事务，真实业务未知也不能盲目重做。

`--arm b0_control` 使用同一实现关闭 observer，另用独立配置和 namespace；默认没有真实 B0 整套重复运行。主要 parity 证据来自同模型响应／固定向量／原工具与世界的零模型执行，对比实际请求与效果。真实运行温度为 0 也不保证输出逐字重现，不能将分数差异直接认作追踪收益或 parity 失败。

## 只读查看

无需 DSN、Provider 或模型即可读取 sidecar：

```bash
uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py summary \
  --sidecar artifacts/langmem-provenance/reproduce-merit/instrumentation.sqlite

uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py query \
  --sidecar artifacts/langmem-provenance/reproduce-merit/instrumentation.sqlite \
  --table revisions --resolve-body

uv run --no-sync --group baseline-langmem python tools/run_langmem_provenance.py query \
  --sidecar artifacts/langmem-provenance/reproduce-merit/instrumentation.sqlite \
  --table requests --resolve-request
```

可用 `--filter column=value` 做准确字段过滤；定位版本时同时指定 namespace_json、memory_id 和 revision。`--latest` 仅在已限定 namespace/ID 后使用，不能把返回旧材料重绑成最新。`--resolve-body` 还原引用正文，`--resolve-request` 验证 trace 路径／byte offset／记录 SHA 后还原实际请求对象。两者均只读，不发请求。

可查询 `observations、bodies、tool_calls、operations、revisions、searches、requests、request_material`。`namespace_json + memory_id + revision` 指向准确版本；正文由该行 `body_ref` 关联 bodies，不能先取 latest 再将旧返回重绑过去。searches 的 returned_json 保存当时的顺序、分数与版本；request_material 关联真正请求所含 ToolMessage，requests 状态区分完成、错误、未知和明确未发送。相同材料进入不同请求是不同交付，不变成新的外部事实。

来源默认 `source_refs=null / UNKNOWN_NOT_DECLARED`。这些只读事实不表示模型采用、正文得到支持或行动金额正确。journal complete 只说明已取得结果，原返回 JSON 仍可能报告业务失败；最终自然语言回答不被解析成业务回执。

运行后费用可用既有 `tools/summarize_langmem_foundation.py` 对应 mode、results、trace 和实际 run ID 离线汇总，再与 v16 连续账本核对。sidecar 的 summary 单列文件字节、事务计数及附加 Store 读取／本地计时，不能与 Provider 墙钟重复相加。模型、完整正文、SQLite、原始 trace 和第三方源码继续保持 ignored，Git 只提交源码、配置、锁、精简清单与结果说明。

## 结果与费用复核

最终实际结果是诊断 7/12、MERIT native 4/5、dependent 1/2；55 个生成请求／40072 known/charged tokens、17 个 embedding 请求／443 tokens，unknown=0、Judge=0。完整 trace 与持续账本已经核对，不为查看报告重新请求模型。例：

```bash
uv run --no-sync --group baseline-langmem python tools/summarize_langmem_foundation.py \
  --mode merit --run v16-b1-merit-r1 \
  --results artifacts/langmem-provenance/final-merit-r1/results \
  --trace artifacts/langmem-provenance/final-merit-r1/trace.jsonl \
  --budget artifacts/langmem-provenance/v16-budget.json \
  --output artifacts/langmem-provenance/final-merit-r1/review-summary.json
```

诊断按同样参数更换 mode、run 与目录。人工语义判断读取完整 session answers/memories/business calls 和冻结 rubric，绝不反向注入运行器。正式 MERIT 已发生一个正常 null 正文 insert，不能用裸 `sha256("null")` 检验它；非字符串内容 hash 使用 `{"type": Python类型名, "value": 值}` 的 canonical JSON，而字符串按原 UTF-8。原请求对象、正文和实际 wire 字节分别核对。

正式 sidecar 的十条 revision 都是 insert@1，UPDATE/DELETE 自然覆盖为 0。保留的 V0 提供旧版本冷读与边界合同；最终冷进程只读核对 10/10 当前对象与正文一致。仪器净增 152 KiB、额外 Store.get 20 次，精确计时／事务口径见最终结果。不要把实际退款成功、完整记录或 unknown 来源解释为金额正确或已采用依据。
