# MiLAi DG-14：LongMemEval MCP 适配与真实对比实验 Goal

> Goal ID：`DG-14`
> 文档版本：`1.0.0 COMPLETE`
> 生效日期：`2026-08-26`（Asia/Shanghai）
> 当前状态：`IMPLEMENTED / TESTED / CHARACTERIZED · RELEASE REVIEW CLOSED`
> 方法标识：`DG14-MILAI-MCP`
> 结果等级上限：`OPENED_DEV_SMOKE / CHARACTERIZATION`
> Runtime / Schema：`0.1.x CANDIDATE / 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

---

# 0. Goal 决定

DG-14 开发当前 DG-13 MiLA，使 LongMemEval opened-development case 通过真实 MCP 服务完成：

```text
LongMemEval history
→ milai-mcp governed Evidence capture / Proposal review
→ MiLA Runtime PostgreSQL persistence and projection
→ milai_memory_resolve
→ MemoryStateView / Context
→ existing vLLM answer provider
```

主实验对象是 MCP-native governed memory service，不是 OpenWorker session memory。OpenWorker 只做
代表性 composition smoke，不构成算法 arm，也不得向模型重放历史消息来冒充 MiLA memory。

# 1. 不可越界项

1. 不依赖或恢复 DG-10 post-R3 authorization；不使用 DG-10 frozen artifact 作为 adapter runtime dependency。
2. 不修改 DG-12 candidate、formal paper harness、frozen holdout、既有正式结果或一次性授权。
3. 不消费正式 holdout label/context/answer；开发输入仅使用
   `var/dg11/paper/runs/pe04-harness-smoke-20260824-002/inputs.json`。
4. 明确禁止 `pe04-harness-smoke-20260824-001`，因为其 session event identity 重复。
5. benchmark adapter、retrieval result、question、answer、label、scorer output 都不能直接写 canonical truth。
6. Evidence、Proposal、StewardDecision、ClaimVersion、Projection、Canonical Gate、Context 的现有边界不变。
7. 不新增 Direct/HTTP memory transport或第二套 memory semantics；benchmark product path 使用本地 stdio MCP。
8. provider 固定为 operator-owned `http://127.0.0.1:7860` / `Qwen3.6-35B-A3B-FP8`；
   DG-14 不重启、不重配、不替换该服务。

# 2. 数据与 label boundary

每个 opened-dev case 使用独立 tenant/principal/scope 或等价的精确测试 namespace。确定性 event identity：

```text
case_id + session_ordinal + original_session_id + turn_ordinal
```

ingest 只接收 history session、role、content、event timestamp 与 label-free metadata。以下字段只能位于
scoring/control plane，永不进入 adapter ingest payload、Evidence content、Proposal patch或 Context：

```text
answer
answer_session_ids
question_type
scorer output
holdout annotations
```

question 只在 query 阶段提供。MiLA provenance 必须无歧义映射回 LongMemEval original session ID，供同一
deterministic retrieval scorer 使用。

M0 冻结身份（2026-08-26）：

| Object | SHA-256 / state |
| --- | --- |
| allowed `pe04-harness-smoke-20260824-002/inputs.json` | `dd1c6fb5c137b16780965b5637562cdfdc8e69ef8d1f1e02e94ce92c754b5a5b` |
| rejected `pe04-harness-smoke-20260824-001/inputs.json` | `8d27d36136e2d4b93b1813c31c50733e9c71be0b9f8eaa3bba85c5ef0d79816a` |
| baseline method config | `ec611f78719c1a6c32878bc543a80e196d0b12f34b26970ccd29e9cf917577de` |
| Qwen tokenizer | `5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42` |
| Qwen chat template | `e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259` |
| opened source IDs vs paper-test holdout | `0/5` overlap |
| DG-14 paper-test/generalization consumption paths | both `ABSENT` at M0 |

# 3. Adapter 合同

`DG14-MILAI-MCP` 必须提供：

```text
reset(case)
ingest(history_event)
finalize/index_readiness
query(question, timestamp, memory_token_budget)
export_context
export_provenance/source_ids
export_stage_trace
cleanup(case_namespace)
```

每次逻辑调用默认 automatic retry `0`。typed failure 必须进入账本，不允许 silent fallback 或宽泛异常吞掉。

# 4. Matched experiment

同一 opened-dev 五 case、同一 answer provider、prompt、seed、generation settings 与 memory budget 对比：

```text
CTRL-NONE
CTRL-CUSTOM-LEX1
LME-BM25-S
LME-BM25-T
DG14-MILAI-MCP
```

至少运行 `512` 与 `2048` memory tokens。先完成单 case 真实纵向测试，再恢复五 case；provider 并发默认
`1`，只有资源稳定后最多 `2`。OpenWorker composition 只跑代表性 smoke，不重复计分。

# 5. 指标与分段账本

Quality：EM、normalized F1、Hit@K、NDCG@K、Evidence Coverage、UNKNOWN/abstention rate、
multi-session success rate。

Efficiency：Evidence ingest、projection/finalize、MCP query p50/p95、Runtime stage、context compilation、
provider、end-to-end latency；memory/prompt tokens、context truncation、MCP/provider logical calls、candidate
count 与 escalation route。不得用总 wall time 掩盖阶段瓶颈。

Correctness 必须分别报告：

```text
wrong-scope acceptance = 0/N
cross-case contamination = 0/N
label leakage = 0/N
stale/revoked evidence acceptance = 0/N
silent fallback = 0/N
```

# 6. Gate

最低 Gate：

1. 五个 opened-dev case 均真实完成 write→persist→retrieve→context→vLLM answer；
2. provider/MCP/Runtime 调用账本完整且可验证；
3. provenance 可被 LongMemEval scorer 识别；
4. 2048-token `DG14-MILAI-MCP` 至少 `3/5` 正确、Evidence Coverage `>=0.80`，以
   `LME-BM25-T` 为非劣目标；
5. 不读取 label、不按 case 硬编码、不改 scorer/answer/baseline；
6. 重复运行不依赖 OpenWorker history；新 MCP 进程或清空 OpenWorker retained context 后仍可查询 PostgreSQL memory；
7. 正式 holdout consumption 保持不存在；目标 tests、ruff、触及模块 strict mypy 通过。

若未达标，逐 case 输出 failure taxonomy 并继续修复真实 retrieval/context 根因；不能降格 Gate 或掩盖失败。

# 7. 有序执行与状态

```text
[x] M0-1 冻结当前 MCP/Runtime、opened-dev、baseline、provider 合同
[x] M0-2 建立 provider 环境账本并完成 spec hash + witness + agent-follows-doc
[x] M1-1 adapter unit、event identity、label-boundary tests
[x] M1-2 fake MCP contract 与 provenance/scorer compatibility tests
[x] M2-1 单 case真实 MiLA MCP write→persist→retrieve→context
[x] M2-2 五 case MiLA-only 真实 smoke
[x] M3-1 512/2048 matched baseline comparison
[x] M3-2 provider/MCP/Runtime ledger 与全指标导出
[x] M4-1 OpenWorker→MCP→MiLA representative smoke
[x] M4-2 触及模块 regression、ruff、strict mypy
[x] R-1 对照逐项 DoD 并运行唯一 release-boundary independent review
```

失败处理严格遵循：停止批次→最小失败 case→单一 stage→根因修复→单项重跑→恢复批量。

# 8. 初始已知基线

`pe04-harness-smoke-20260824-002` 的已知 opened-dev characterization：

| Arm / budget | F1 / EM | Coverage | Truncation |
| --- | --- | --- | --- |
| NONE / 512 | 0.00 | — | — |
| Lexical top-1 / 512 | 0.00 | 0.50 | — |
| Session BM25 / 512 | 0.00 | 0.80 | 1.00 |
| Lexical top-1 / 2048 | 0.20 | — | — |
| Session BM25 / 2048 | 0.00 | 0.80 | 1.00 |
| Turn BM25 / 2048 | 0.60 / 0.60 | 0.80 | 0.00 |

已知失败集中在 multi-session counting、跨 session arithmetic、session packing 和命中内容位于截断后部。

# 9. 最终交付分类

最终报告必须逐项标注：

```text
IMPLEMENTED
TESTED
CHARACTERIZED
BLOCKED
NOT FORMALLY EVALUATED
```

五 case结果永远不得标为 paper result、production result、formal benchmark pass 或创新结论。

# 10. 实现与真实运行状态（2026-08-26）

## IMPLEMENTED

1. `evals/dg14/` 提供当前 DG-13 MCP contract 的 adapter、persistent stdio transport、runner、provider、
   hash-chained ledger、scorer、correctness smoke、OpenWorker composition 和 source-ID-only split builder。
2. 写入路径为 Evidence capture → Proposal → 独立 reviewer GET/APPROVE → worker projection；不依赖 DG-10
   frozen artifact 或 post-R3 authorization。
3. canonical payload 使用确定性 session chunk，Event identity 绑定
   `case_id + session_ordinal + original_session_id + turn_ordinal`。
4. query 无 TaskIdentity 也进入 `milai_memory_resolve`；TaskContext 仅允许收窄到当前 case project。
5. Runtime candidate hydration 与最终 Qwen tokenizer context packing 分离；最终导出严格遵守 512/2048
   memory token budget，provenance 映射回 pseudonymized LongMemEval session ID。
6. CLI：`scripts/run_dg14_longmemeval_dev.py` 支持 `run`、`milai-smoke`、`score`、
   `verify-ledger`、`integration-smoke`、`openworker-composition-smoke`、`build-dev-split`。

## TESTED

- 单 case真实链路：514 Evidence、428 governed chunks，512=`PARTIAL`、2048=`HIT`，清理 514/514。
- 五 case MiLA-only：10/10 context 成功；2048 全部 `HIT`，512 全部有 governed context；provider calls=0。
- matched run：50/50 context 与 50/50 vLLM generation；同 case/budget 的五 arm seed 完全一致。
- ledger：14,615 events，最终 root
  `428f7b512d5dab5b2ca7bce0a52ec83b18b3592df56d9cd1b600668c01918be2`，独立 verify=`VERIFIED`；
  其中 50 条 provider response binding 和 1 条 score closure 将 answer/context/prompt/native request、fixture、
  scored records、comparison 与 analysis 纳入同一 append-only hash chain。
- correctness integration：wrong-scope 0/1、cross-case 0/1、revoked evidence 0/1、silent fallback 0/1；
  MCP PID 重启后 provenance 不变，另一个 namespace 不受精确撤销影响。
- OpenWorker：两个全新 `opencode` session；主路径实际执行 OpenWorker tool call → relay/UDS → broker →
  current reader-detail `milai-mcp` → Runtime → 1 provider，history forwarded=0，retained=0；第二 session
  再执行 1 次 MCP、0 次 provider，从同一 Runtime persistence 返回相同 source ID。
- 最终目标检查：DG-14 `32 passed`；Runtime task-free `21 passed`；OpenWorker binding `12 passed`；
  MCP targeted `10 passed`；ruff、strict mypy 与 `git diff --check` 通过。
- 每次真实 Runtime 使用 fresh PostgreSQL database，均记录 `exact_fresh_database_only=true` 并成功 drop。

## CHARACTERIZED

主结果：`dg14-matched-001-20260826`，只属于 `OPENED_DEV_SMOKE / CHARACTERIZATION`。

| Arm | Budget | EM | F1 | Hit@K | NDCG@K | Coverage | Unknown | Context truncation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CTRL-NONE | 512 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 |
| CTRL-NONE | 2048 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 |
| CTRL-CUSTOM-LEX1 | 512 | 0.00 | 0.00 | 0.80 | 0.80 | 0.50 | 0.80 | 0.80 |
| CTRL-CUSTOM-LEX1 | 2048 | 0.20 | 0.20 | 0.80 | 0.80 | 0.50 | 0.60 | 1.00 |
| LME-BM25-S | 512 | 0.00 | 0.00 | 0.80 | 0.80 | 0.80 | 1.00 | 0.80 |
| LME-BM25-S | 2048 | 0.00 | 0.00 | 0.80 | 0.80 | 0.80 | 1.00 | 0.80 |
| LME-BM25-T | 512 | 0.00 | 0.00 | 0.80 | 0.665 | 0.80 | 0.80 | 0.80 |
| LME-BM25-T | 2048 | 0.60 | 0.60 | 0.80 | 0.665 | 0.80 | 0.40 | 0.00 |
| DG14-MILAI-MCP | 512 | 0.20 | 0.358 | 0.80 | 0.80 | 0.50 | 0.40 | 0.20 |
| DG14-MILAI-MCP | 2048 | 0.60 | 0.60 | 0.80 | 0.80 | 0.80 | 0.40 | 0.00 |

DG14/2048 达到最低验收：3/5 correct、Coverage=0.80，并与 LME-BM25-T/2048 的 EM/F1/Coverage
持平。零 margin 非劣 Gate 已机械检查 EM/F1/Coverage，结果全部 `true`。DG14 query p50/p95=77.7/92.3 ms，
provider mean=287.6 ms，E2E mean=381.9 ms；主要成本是 governed finalize mean=109.5 s/case。
每个 budget 的真实 MCP query calls=10；五 case共享的 ingest/finalize/cleanup 生命周期 calls=11,442，
只在 comparison 顶层报告一次，不再冒充 per-budget 调用量。

逐 case：`001be529`、`01493427`、`031748ae` 正确；`00ca467f` retrieval miss；`0100672e`
Evidence Coverage=1.0 但 provider 输出 `UNKNOWN`，属于 answer/reasoning abstention。

## BLOCKED

无。最低适配与 opened-dev characterization gate 已满足。

## NOT FORMALLY EVALUATED

未运行新建的 50-case public/deidentified dev split；未消费 paper-test-v1 或 generalization-v2；未运行
DG-12 frozen candidate、正式 paper harness 或任何论文正式实验。两个正式 consumption path 在本轮结束前仍为
`ABSENT`。本节结果不能称为 paper result、production result、formal benchmark pass 或创新结论。

# 11. 交付物与证据

- Matched comparison：`var/dg14/runs/dg14-matched-001-20260826/comparison.json`
- 对比分析：`var/dg14/runs/dg14-matched-001-20260826/analysis.md`
- 逐 cell 结果：`var/dg14/runs/dg14-matched-001-20260826/scored-records.json`
- Provider/MCP/Runtime 账本：`var/dg14/runs/dg14-matched-001-20260826/stage-ledger.jsonl`
- Context / generation / cleanup：同 run 目录的 `contexts.json`、`generations.json`、`cleanup.json`
- Failure taxonomy：同 run 目录的 `failure-taxonomy.json`
- Governance/restart correctness：`var/dg14/runs/dg14-integration-001-20260826/integration-smoke.json`
- OpenWorker authoritative composition：`var/dg14/runs/dg14-openworker-uds-009-20260826/openworker-smoke.json`
- Public/deidentified dev split：`var/dg14/splits/public-deidentified-dev-v1/source-ids.json`
- 五行 opened scoring fixture：`evals/dg14/fixtures/opened-dev-scoring-fixture.json`

# 12. 精确复现命令

以下命令必须使用新的 `run-id`；vLLM 保持现有 7860 服务，不由 DG-14 启停：

```bash
cd /cra/memory/mx_memory/MiLAi

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py milai-smoke \
  --run-id <fresh-milai-run-id>

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py run \
  --run-id <fresh-matched-run-id> --provider-workers 1

# 新 run 在成功退出前自动 seal；以下命令用于迁移/验证尚未 seal 的既有 opened-dev run。
runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py seal-run \
  --run-id <fresh-matched-run-id>

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py score \
  --run-id <fresh-matched-run-id> \
  --scoring-fixture evals/dg14/fixtures/opened-dev-scoring-fixture.json

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py verify-ledger \
  --run-id <fresh-matched-run-id>

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py integration-smoke \
  --run-id <fresh-integration-run-id>

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py openworker-composition-smoke \
  --run-id <fresh-openworker-run-id>

runtime/.venv/bin/python scripts/run_dg14_longmemeval_dev.py build-dev-split
```

# 13. 已知限制与下一阶段建议

1. 五 case 分母极小，只能用于 characterization；50-case dev split 尚未执行。
2. governed chunk 的 Evidence/Proposal/reviewer/worker 流程正确但 finalize 成本高；下一阶段应优先做合法的批量
   capture/review/projection 调度优化，不应跳过治理边界。
3. `00ca467f` 需要真实 multi-session retrieval 改进；`0100672e` 需要在不读 label 的前提下改进
   cross-session arithmetic/answer reasoning。
4. 本轮 local Runtime 使用 deterministic-hash embedding，结果不能外推到 production embedding/provider。
5. OpenWorker smoke 是 composition 验证，不是独立算法 arm，也不进入 50-cell comparison。

# 14. 唯一 release-boundary independent review

按 `codex_sol_xhigh.md` 仅调用一次 `gpt-5.6-sol / xhigh` 只读审查。审查提出的一个阻断、一个高和三个中等级
finding 已分别通过以下事实关闭，未重复调用审查：

1. provider/score 证据闭环：新增 response binding、run seal、score closure 和 scorer 前置闭环验证；
2. OpenWorker 边界：替换 provider-gateway 直调 adapter 的旧 smoke，完成真实 relay/UDS/broker/MCP tool 回合；
3. 非劣 Gate：EM、F1、Coverage 使用明确零 margin 机械判定，并增加 baseline 更优时必须失败的负向测试；
4. 运行身份：tokenizer、chat template、baseline config 三个冻结 SHA 启动时 fail-closed 并写入 manifest；
5. MCP 成本：共享 lifecycle 与 per-budget query calls 分开报告。

---

_Last updated：2026-08-26 · implementation, opened-dev characterization, targeted regression and the single release-boundary review complete · DG-14 formal paper-test/generalization consumption remains absent._
