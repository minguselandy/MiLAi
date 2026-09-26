---
version: v18.0
date: 2026-09-26
status: STOPPED_M1_RECHECK_NOT_JUSTIFIED
scope: MiLAi-Lab
---

# v18 复现与证据入口

先读[结果](MILA_LANGMEM_M1_PIVOT_V18_RESULTS_20260926.md)与[开发记录](MILA_LANGMEM_M1_PIVOT_V18_DEVELOPMENT_20260926.md)。本轮实现与指定小规模执行已完成，三个最终实例均中断；后续12/20与arc0未获机制gate，不是已完成benchmark。发布不再运行模型、测试或build。

## 源码与依赖

- 工作目录：`MiLAi/MiLAi-Lab`；使用仓库`uv.lock`，依赖组`baseline-langmem`。
- LangMem固定commit `9d033b47d9ce53e37e92c92241b0496c0278932e`；其余精确版本见原foundation lock与uv.lock。
- 最终41文件mapping：`657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e`。
- v18 lock SHA：`200e8119ee09b1b8cbb5085e51f21c2b11c76755f5c5b335f3a09f1c48d54c11`。
- 最终freeze SHA：`20407ea9ec505e7361dee8fdc8b5e33577bed9fb1d095982747254cf708dd9c2`。
- 原v17恢复点：Git `9438d1349b5f7988ca86f491ad489eefa87becd3`，其原锁及结果保留；旧状态用旧源码读取，不自动迁移到v18。

源码通过原ReAct adapter接入；`tools/run_milai_m1_v18.py`是共享CLI薄入口，`tools/inspect_milai_m1_v18.py`是只读SQLite入口。没有第二Agent loop。

## 无模型核对

```bash
uv sync --frozen --group baseline-langmem --group dev
uv run --no-sync python tools/run_milai_m1_v18.py schema --fixture data/fixtures/milai_m1_v18_recheck_changed.json
uv run --no-sync python tools/inspect_milai_m1_v18.py --state artifacts/langmem-m1-v18/final-changed-r2/decision-basis.sqlite
uv run --no-sync python tools/inspect_milai_m1_v18.py --state artifacts/langmem-m1-v18/final-changed-r2/decision-basis.sqlite --table events
```

必要测试入口为`tests/unit/test_milai_m1_v18.py`；本轮8项与修复相关增补已通过，无需为发布重跑。旧`test_milai_m1.py`跟随v17代码保留在Git历史，当前CI收集新合同。旧B1的工具与业务合同保持；默认core环境的optional依赖由importorskip处理。

[验证清单](../data/manifests/milai-m1-v18-verification.json)明确区分R1完整V0、R2 schema窄修复、唯一R1打包检查。已产出的R1 sdist不是最终R2源码包，当前交付以Git源码和最终lock为准。

## 原服务与独立持久状态

保持原Host `http://127.0.0.1:7860/v1/`、Qwen3.6-35B-A3B-FP8、temperature0、thinking=false、每消息12次尝试、4096输出、65536上下文；embedding仍为`http://127.0.0.1:7861/v1/`的bge-m3／1024维。Tokenizer路径为`/cra/qwen36-35B`，精确文件hash由config固定。

不修改或重启vLLM，不增加tool parser或服务参数。已有隔离Lab PostgreSQL通过进程变量`MILAI_LANGMEM_POSTGRES_DSN`提供DSN；不要把DSN写入Git、命令回显或结果。原私密连接信息在ignored `artifacts/langmem-foundation/private/postgres.json`；不访问Product。

新的人工复现应复制`configs/milai-m1-v18.json`到独立ignored目录，填本地tokenizer路径，为trace/checkpoint/business journal/capacity/sidecar/Decision SQLite设独立路径，沿用连续账本并使用新run ID。先用public Store query=null确认新namespace为空，再执行prepare；不能覆盖本轮已消费namespace或账本来伪造干净重跑。

## 本轮实际入口与身份

| 组 | 最终run ID | fixture | 实际结果 |
| --- | --- | --- | --- |
| changed | v18-m1-changed-r2 | milai_m1_v18_recheck_changed.json | 第2消息协议拒绝 |
| retained | v18-m1-retained-r2 | milai_m1_v18_recheck_retained.json | 第2消息协议拒绝 |
| irrelevant | v18-m1-irrelevant-r2 | milai_m1_v18_irrelevant_revision.json | 第2消息截断 |

每组私有目录为`artifacts/langmem-m1-v18/final-<组>-r2/`，内含config、prepared、trace、checkpoint、instrumentation、decision-basis、process receipt和run/interruption。三个fixture/freeze与离线评分在首个请求前冻结。Runner只读公开fixture/freeze，不读rubric；seed/update通过原LangMem工具，origin显式为FIXTURE。

以本轮changed为例，原正式入口如下（已有结果保留，仅用于说明复现参数）：

```bash
uv run --no-sync python tools/run_milai_m1_v18.py prepare   --config artifacts/langmem-m1-v18/final-changed-r2/config.json   --mode mechanism --arm m1 --run v18-m1-changed-r2   --fixture data/fixtures/milai_m1_v18_recheck_changed.json   --mechanism-freeze data/manifests/milai-m1-v18-changed-freeze.json   --output artifacts/langmem-m1-v18/final-changed-r2/prepared.json
uv run --no-sync python tools/run_milai_m1_v18.py run   --config artifacts/langmem-m1-v18/final-changed-r2/config.json   --mode mechanism --arm m1 --run v18-m1-changed-r2   --fixture data/fixtures/milai_m1_v18_recheck_changed.json   --mechanism-freeze data/manifests/milai-m1-v18-changed-freeze.json   --prepared artifacts/langmem-m1-v18/final-changed-r2/prepared.json   --stage v18-changed-r2   --output artifacts/langmem-m1-v18/final-changed-r2/run
```

R1原失败源码/锁/冻结在ignored `r1-frozen-source/`、`r1-lock.json`、`r1-final-freeze.json`；它的实例是`final-changed-r1/`。不得拿最终R2锁解释R1轨迹。R1/R2 probe原文在`decoder-probe-r1/`及`decoder-probe-r2/`，只做结构可表达性，不执行工具。

原12/20输入、评分与arc0/world的准确hash在[条件数据冻结](../data/manifests/milai-m1-v18-exposed-freeze.json)。本轮只完成其零模型prepare，从未执行；R2新run ID列于最终freeze，替代历史规划中的r1名字，样本内容未变。

## 结果与费用复核

公开依据：[reference](../data/manifests/milai-m1-v18-reference.json)、[final freeze](../data/manifests/milai-m1-v18-final-freeze.json)、[R1失败](../data/manifests/milai-m1-v18-r1-failure.json)、[结果](../data/manifests/milai-m1-v18-results.json)、[机制](../data/manifests/milai-m1-v18-mechanism-results.json)、[连续成本](../data/manifests/milai-m1-v18-cost-summary.json)。私有原文hash对应这些清单，raw trace与DB没有加入Git。

原Provider用量合计16 generations／19237 tokens／267 embedding tokens，unknown0、Judge0、截断1。Context按精确交付片段计288tokens；可解析delta340，拒绝的completion字段19；另一个4096token截断响应完整计费，不能把它漏出成本或假装完成delta。3份DecisionSQLite共135168bytes、8次应用写事务。只读统计不改变状态。

再次核对vLLM container/image/command/environment/HostConfig一致；原计划、旧锁/结果/账本、所有41个最终源码及验证文件hash应保持。后续机制研究必须承认本轮未建立采用和重核前提，不能称M1有效或M2 ready。
