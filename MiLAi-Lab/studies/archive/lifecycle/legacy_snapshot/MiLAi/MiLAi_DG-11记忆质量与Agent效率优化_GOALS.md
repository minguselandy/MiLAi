# MiLAi DG-11 Goals：Memory MCP 功能收敛、质量优化与论文评测

> Goal ID：`DG-11`  
> 文档版本：`0.2.0 ACTIVE — HOLDOUT_FAILED / RECOVERY PLANNED`  
> 更新日期：`2026-08-23`（Asia/Shanghai）  
> 前序目标：`DG-10 CLOSED / ACCEPTED`  
> 当前可用声明：`MILAI_PREFETCH_AGENT_READY`（DG-10 冻结候选）  
> DG-11 当前状态：`HOLDOUT_FAILED`  
> DG-11 目标声明：`MILAI_MEMORY_MCP_FUNCTIONAL_CANDIDATE`；质量成立时再增加
> `MILAI_PREFETCH_AGENT_OPTIMIZED_CANDIDATE`  
> 唯一开发期 answer Provider：`self-hosted vLLM 0.27.1 / Qwen3.6-35B-A3B-FP8`  
> 数据边界：`SYNTHETIC / PUBLIC BENCHMARK / DEIDENTIFIED ONLY`  
> Logical Architecture：`1.0.0 FROZEN`  
> Runtime：`0.1.x CANDIDATE`  
> Schema：`0.1.x EXPERIMENTAL / NO-GO FOR FREEZE`  
> 开发期 AI 审计预算：`0`  
> 论文阶段独立 AI review：`至多一次、只读、非 scorer、非 authority`  
> 默认反馈源：`可执行能力 + 动态结果 + Benchmark delta + Agent task outcome`

---

# 0. Goal 决定

DG-11 尚未完成。权威状态是：

```text
phase = HOLDOUT_FAILED

8 PASS
1 REVERTED
1 HOLDOUT_FAILED
1 NOT_STARTED
```

当前不能通过改文档、补 receipt、重新解释阈值或在已消费 holdout 上重跑来关闭 Goal。后续主线改为：

```text
已消费 v1 holdout 的完整误差分解
→ 在已打开 DEV 数据上完成窄而真实的代码修复
→ 功能、安全、效率回归
→ 冻结可安装候选字节
→ 一次 v2 泛化验证
→ 按真实结果决定 FUNCTIONAL / OPTIMIZED 标签
→ 候选保持不可变
→ 进入独立论文评测平面
→ 官方 baseline + 外部项目 + 消融 + 多 benchmark
→ 结果驱动下一 Goal，而不是结果驱动同一候选继续调参
```

本次修订做出五个关键纠正：

1. 将“功能可用”“质量优化成立”“论文比较完成”拆成三个不同状态；
2. 不再把自定义 `NAIVE_RAG` 称为 benchmark 官方或最强公开 baseline；
3. 开发结束后才冻结论文候选，论文 test 不参与同一候选开发；
4. 引入 LongMemEval 官方 baseline、Mem0、Hindsight、Graphiti、ReMe 和 benchmark-native 方法；
5. 论文评测以动态实验、统计区间和质量—成本曲线为主，不恢复高频 AI 审计。

---

# 1. 当前执行状态与证据

## 1.1 工作包状态

| 工作包 | 状态 | 已成立的实际能力或结论 |
| --- | --- | --- |
| `DG11-00` | `PASS` | DG-10 可复算分层指标、dual scorer、paired/bootstrap 测量 |
| `DG11-01` | `REVERTED` | 初版 turn-window compiler 三次未提高 span survival，已回退 |
| `DG11-02` | `PASS` | turn/window + 128d projection 方案及 Runtime 路径通过 |
| `DG11-03` | `PASS` | temporal/aggregate 确定性 operator 通过 |
| `DG11-04` | `PASS` | compact prompt 与 validated-cache 路径通过 |
| `DG11-05` | `PASS` | persistent OpenWorker 效率路径通过 |
| `DG11-06` | `PASS` | F0/F1、MCP、T2/S1–S10 和安全无回归 |
| `DG11-07` | `PASS` | 20 个 paired Agent tasks，60 次 answer Provider 调用 |
| `DG11-08` | `PASS` | 50-case Combined DEV 达标 |
| `DG11-09` | `HOLDOUT_FAILED` | 100-case v1 sealed holdout 未达到全部泛化门 |
| `DG11-10` | `NOT_STARTED` | 后继 wheel、冻结候选和最终交付尚未完成 |

权威机器状态：[`var/dg11/current-state.json`](./var/dg11/current-state.json)。

## 1.2 DG-10 不可改写基线

| 材料 | 路径 | SHA-256 |
| --- | --- | --- |
| 最终状态 | `var/dg10/current-state.json` | `aadc8ec5476eeab8981af2d007afb5756c0ca723dc908d23f9481f89cc3dda00` |
| 最终报告 | `var/dg10/final/final-report.json` | `6268d17aa9e3f944f09ed1b0c273fd742945aeec6b5fbc477f79efab6df02c07` |
| 受控裁决 | `var/dg10/final/controlled-adjudication.json` | `11915210213bf51dfe92b88b2763b2bf2983a64db693c090e762b982a29f65a3` |
| 候选 inventory | `var/dg10/final/candidate/inventory.json` | `e134807d745bf30e2e464d9a875edb3af571b3651bf3152f3ae43f72d26ecf6a` |
| Freeze manifest | `var/dg10/final/candidate/freeze-manifest.json` | `c64ed9a9b69ac36ba4ea5a91e0be5a9350bfefec8e30316b4be02e7aedb84562` |

`var/dg10/final/candidate` 与 `var/dg10/final/review-workspace` 继续只读。它们既是回滚目标，
也是 DG-11 消融与配对比较的冻结 arm。

## 1.3 已成立的功能与效率结果

```text
F0 MCP native       = 10/10 PASS
F1 Agent            = 5/5 PASS
T2                  = 24/24 PASS
Hardened S1–S10     = PASS
Paired Agent tasks  = 20/20 DG11 task success
Hidden answer calls = 0
Development reviews = 0
```

这些结果证明 MiLAi 已能作为 prefetch Memory MCP 使用，并保持 Scope、OpenIssue、revoke、cache 和
OpenWorker 边界。它们不能证明 DG-11 质量优化已经泛化。

## 1.4 Combined DEV 结果

50-case Combined DEV：

| 指标 | DG-11 | DG-10 | Delta |
| --- | ---: | ---: | ---: |
| Normalized F1 | `0.396679` | `0.283341` | `+0.113338` |
| Exact Match | `0.24` | `0.22` | `+0.02` |
| Answer requests | `50` | 配对复用 | hidden `0` |

证据：[`dg11-combined-dev-20260823-005/result.json`](./var/dg11/runs/dg11-combined-dev-20260823-005/result.json)。

该结果只说明优化在开发分布有效，不能替代 holdout。

## 1.5 v1 sealed holdout 结果

100 个案例、四个 arm、400 次 answer 请求均完整执行；同一 arm/case 只有一次 answer call，hidden calls
为零。v1 split 已消费且不可重跑。

| 指标 | DG-11 | DG-10 | 自定义 lexical Top-1 |
| --- | ---: | ---: | ---: |
| F1 | `0.283122` | `0.268533` | `0.208678` |
| EM | `0.23` | `0.22` | `0.15` |
| Prompt tokens mean | `394.21` | `492.47` | `405.92` |

关键配对结果：

```text
DG11 - DG10 F1 mean     = +0.014589
bootstrap 95% CI        = [-0.024459, +0.057533]
wins / losses / ties    = 6 / 7 / 87
DG11 - custom RAG F1    = +0.074444
safety failures         = 0
```

失败的正式门：

```text
paired F1 delta >= +0.04                 FAIL
bootstrap lower95 > 0                    FAIL
delta vs fixed custom baseline >= +0.10  FAIL
single-assistant delta vs custom RAG >=0 FAIL（-0.002778）
```

证据：[`dg11-holdout-20260823-001/result.json`](./var/dg11/runs/dg11-holdout-20260823-001/result.json)。

## 1.6 Holdout 暴露的真实问题

| 类别 | DG-11 F1 | DG-10 F1 | 结论 |
| --- | ---: | ---: | --- |
| knowledge-update | `0.588948` | `0.564706` | 小幅提升 |
| temporal-reasoning | `0.174179` | `0.139457` | 小幅提升，绝对值仍低 |
| preference | `0.088106` | `0` | 有改善，但样本仅 5 个 |
| single-assistant | `0.25` | `0.125` | 对 DG-10 提升，但略低于 custom RAG `0.252778` |
| single-user | `0.603175` | `0.613095` | 轻微回退；custom RAG 更高 |
| multi-session | `0.066667` | `0.10` | 明确回退，是当前首要质量阻断 |

综合诊断：

1. DG-11 把平均 prompt 从 `492.47` 压到 `394.21`，效率收益成立；
2. 更紧凑的 Context 没有形成广泛质量收益，87% 的配对案例完全持平；
3. 多会话任务可能因固定 Top-k、预算分配和跨会话事实覆盖不足而回退；
4. assistant 列表、角色继承、数值单位和指代结构仍会在编译时损失；
5. temporal operator 有正收益，但 route 过宽会误处理普通 duration/金额问题；
6. 50-case DEV 的 `+0.113338` 明显高于 holdout 的 `+0.014589`，存在开发集特化和样本方差；
7. `CUSTOM_LEXICAL_TOP1` 很弱，超过它不能支持“优于官方 RAG/外部系统”的论文 claim。

## 1.7 Holdout 后修复的证据等级

已完成的代码修复覆盖：

```text
did it take 路由误判
last Thursday 金额查询误路由
16GB 数值单位保留
assistant 推荐列表/跨行角色继承
SIAC_GEE 与 SIAC\_GEE 归一化
编号列表代词主体继承
```

已知五个案例能给出 `4 hours`、`$0.75`、`16GB`、`Ruby, Python, or PHP`、`6S`。这些只能标记为：

```text
TARGETED_DEV_EVIDENCE
```

不得据此把 `DG11-01` 或 `DG11-09` 改为 PASS，也不得替代新的泛化实验。

---

# 2. 状态与声明分离

DG-11 不再使用一个总 PASS 混合三个不同问题。

## 2.1 功能候选

```text
MILAI_MEMORY_MCP_FUNCTIONAL_CANDIDATE
```

要求：

- MCP/OpenWorker/Agent 的读取、召回、OpenIssue、Scope、revoke、cache 路径完整；
- F0/F1 和受影响的数据库/安全/E2E 门通过；
- wheel 可 fresh install，可回滚到 DG-10；
- 无 hidden answer call；
- 质量结果可以是正、平或负，但必须如实报告。

## 2.2 优化候选

```text
MILAI_PREFETCH_AGENT_OPTIMIZED_CANDIDATE
```

除功能候选外，还要求新的预注册泛化集达到 DG11-09V2 质量门。未达到时只能声明：

```text
FUNCTIONAL_CANDIDATE / QUALITY_TARGET_NOT_MET
```

## 2.3 论文评测候选

```text
MILAI_PAPER_EVALUATED_CANDIDATE
```

表示同一冻结候选已完成官方 baseline、外部系统、消融、效率与统计评测。它不是
`PRODUCTION_READY`，也不保证所有指标胜出。论文结果必须允许负结果和条件性结论。

---

# 3. 不可破坏的边界

开发和论文实验均必须保持：

```text
PostgreSQL Canonical Core 是唯一正式状态来源
Evidence != Claim
Context/模型输出/外部系统不能制造 canonical truth
OpenIssue 不能被压平成确定事实
ACTION_SAFE 必须通过 Scope + authority + Canonical Gate
revoke 后 stale index/cache/context 必须 fail closed
Agent 和 baseline adapter 不能直接 canonical DML
每个 answer arm/case 默认只有一次 answer model call
任何额外 extraction/rerank/judge call 单独计数，禁止隐藏
```

外部项目仅允许在隔离 Evaluation Plane 中作为 baseline：

```text
Mem0 / Hindsight / Graphiti / ReMe
→ 独立数据库或目录
→ 无 MiLAi canonical 写凭据
→ 不成为 Runtime 启动依赖
→ 不改变 Frozen Logical Architecture
```

这不重开 `ReMe/Hindsight/Graphiti production route`；生产接入继续 `PARKED`。

---

# 4. 开发与实验纪律

## 4.1 代码优先、误差分层

每个失败先归入一个层级：

```text
R0 query/intent parsing
R1 retrieval candidate miss
R2 relevant session 命中但 evidence set 不完整
R3 answer span 在 Context 编译时丢失
R4 span 存在但模型回答错误
R5 temporal/aggregate operator 误路由或 operand 不完整
R6 governance/safety gate 正确拒绝
R7 scorer/label/protocol 问题
```

一次改动只主攻一个层级，并同时记录上游和下游指标。不能只看最终 F1 猜原因。

## 4.2 尝试预算

同一假设族最多三次：

```text
attempt 1 = 最小实现
attempt 2 = 针对主要失败修正
attempt 3 = 最后一个受限变体
```

三次仍无跨 slice 稳定收益则 `REVERT/PARK`。失败只追加一条 experiment ledger，不生成候选链、
receipt 链或重复 review。

## 4.3 单一开发状态

开发期只维护：

```text
var/dg11/current-state.json
var/dg11/dev/experiment-ledger.jsonl
var/dg11/dev/latest-result.json
```

冻结阶段才新增：

```text
var/dg11/final/candidate/
var/dg11/final/final-report.json
var/dg11/paper/
```

## 4.4 数据使用原则

- 已打开的 DG-10 DEV/confirmation 和 DG-11 v1 holdout 可用于开发与误差分析；
- 不得把这些数据再次称为 holdout；
- 任何基于已打开案例的修复只产生 DEV evidence；
- 论文 test 开始后，不得修改同一候选；
- 公开 benchmark 标签可获得不等于允许用 test labels 调 prompt、router、retrieval 或阈值。

---

# 5. 数据切分与防止反复追 holdout

本地 LongMemEval cleaned 数据共 `500` 个案例。已独立复算当前使用情况：

```text
DG-10 及 DG-11 v1 前已消费    = 200
DG-11 v1 holdout 已消费         = 100
当前仍未消费                   = 200
```

在任何新开发实验前，必须将剩余 200 个案例一次性、确定性、按类别分层冻结为：

```text
DG11_GENERALIZATION_V2 = 100
DG11_LME_PAPER_TEST_V1 = 100
```

必须同时生成：

```text
source ID manifest
dataset SHA-256
category allocation
label-free inputs
split seed digest
candidate identity placeholder
consumption record path
```

约束：

- 两组互斥，并排除前 300 个已消费案例；
- `PAPER_TEST_V1` 不得用于 v2 修复、adapter 开发或阈值选择；
- v2 只运行一次；
- v2 失败后，本 Goal 禁止创建 LongMemEval v3 继续追门槛；
- 若 v2 失败，只能冻结为 `FUNCTIONAL / QUALITY_TARGET_NOT_MET`，或结束本 Goal 后另立开发 Goal；
- 论文 LongMemEval 结果只能来自已冻结候选对 `PAPER_TEST_V1` 的一次完整运行。

由于 LongMemEval 标签是公开数据，此处是程序性 holdout，不应宣传为第三方私有盲测。跨 benchmark
泛化主要依赖此前未用于 MiLAi 调参的 Memora、LongMemEval-V2、BEAM、HorizonBench/CUPID。

---

# 6. 后续恢复开发工作包

## 6.1 `DG11-R00` 冻结剩余数据与失败矩阵

目标：先保护最后 200 个 LongMemEval 案例，再开发。

实现：

1. 冻结 v2 与 paper 两个互斥 100-case manifest；
2. 对已消费 v1 的 100 个案例生成 R0–R7 误差矩阵；
3. 输出每个类别的 retrieval hit、coverage、answer-span survival、operator route、UNKNOWN、F1/EM；
4. 将当前五个 targeted 修复映射到具体失败类别；
5. 不调用 answer Provider。

完成条件：

```text
remaining split overlap                   = 0
overlap with consumed 300                 = 0
paper label fields in generated DEV inputs = 0
v1 100-case error denominator             = 100
provider answer calls                     = 0
```

## 6.2 `DG11-R01` Stable Compact Compiler 定向增强

不恢复已失败的通用 turn-window 重写。继续以当前稳定 compact compiler 为基线，只加入可单独验证的结构保护：

```text
role-aware user/assistant adjacency
number + unit atomic span
enumerated-list subject inheritance
cross-line role inheritance
escaped identifier normalization
query-hit sentence surrounding window
sentence/token boundary truncation
```

Sidecar 继续保存 UUID、trace 和完整 refs，模型正文不重复。

KEEP 条件：

```text
opened DEV answer-span survival       > current compact baseline
single-assistant F1                   >= DG10 on opened DEV
single-user F1 regression             >= -0.01
mean memory tokens                    <= 320
max memory tokens                     <= 512
OpenIssue/revoke tests                = 0 regression
```

只有该动态结果成立后，才能把旧 `DG11-01 REVERTED` 标记为
`SUPERSEDED_BY_DG11-R01/PASS`；否则保持 REVERTED。

## 6.3 `DG11-R02` 多会话 evidence-set 覆盖优化

这是当前最高优先级质量工作包。目标不是盲目增加 Top-k，而是在固定 token 预算内覆盖回答所需的多个会话。

候选实现按顺序 A/B：

```text
B0 current top-3 fusion
B1 intent-adaptive candidate pool，model-visible budget 不变
B2 query-aware weighted set cover
B3 FTS + 128d vector + cross-encoder rerank
B4 B2 + bounded diversity/MMR
```

要求：

- 先离线运行 retrieval-only A/B；
- reranker 使用本地冻结模型并单独记录调用、耗时和版本；
- multi-session/temporal 可扩大候选池，但最终 Context 仍不超过 512 target tokens；
- set cover 优先新增未覆盖实体、时间、关系和 answer-bearing span，不按 session 平均分预算；
- 单事实问题不得因多会话策略引入无关上下文；
- gold `answer_session_ids` 只能用于 scorer，不得进入 retrieval、rerank 或 compiler。

KEEP 条件：

```text
multi-session relevant coverage       > current DG11
multi-session answer-span survival    > current DG11
multi-session F1 on opened DEV        >= DG10
single-session regression             >= -0.01
memory token ceiling                  unchanged
hidden answer calls                   = 0
```

## 6.4 `DG11-R03` QueryPlan 与 Operator 精度

修复目标：

```text
duration 问句 != calendar distance
weekday 作为事件限定词 != 自动 temporal arithmetic
金额/容量/版本号 != 时间 operand
latest/before/after/count/sum 必须具备完整 typed slots
```

实现：

- operator route 必须通过 intent + slot schema；
- route 置信不足时退回普通 recall 或 structured abstention；
- operand 全部来自 Canonical-Gated Evidence Bundle；
- operator 输出是 derived query result，不写 canonical state；
- 输出保存 route reason、operand refs、inclusive/exclusive 口径。

完成条件：

```text
known false-route regressions        = 0
temporal opened-DEV F1               >= current DG11
wrong-certain operator fixtures      = 0
operator hidden model calls          = 0
```

## 6.5 `DG11-R04` Combined DEV-2

只使用已消费/已打开案例。执行顺序：

```text
retrieval-only
→ compiler-only
→ operator-only
→ one combined run
```

禁止在每个局部变体重跑全部 arm。Combined DEV-2 必须并列报告原 scorer v1、scorer v2 和分层指标。

进入候选冻结的最低条件：

```text
F1 vs DG10 on opened combined DEV       >= +0.05
EM vs DG10                              >= 0
multi-session vs DG10                   >= 0
single-assistant vs custom lexical RAG  >= 0
knowledge-update regression             >= -0.02
mean memory tokens                      <= 320
safety regressions                      = 0
```

DEV 阈值只能决定是否停止开发，不能成为论文结果。

## 6.6 `DG11-R05` 功能、Agentic 与效率回归

候选冻结前运行：

```text
fresh exact-role PostgreSQL affected suites
F0 10/10
F1 5/5
affected T2 and hardened S1–S10
20 paired Agent tasks
revoke → stale FTS/vector/cache rejection
OpenIssue preserve/abstain
Scope/authority negative
Runtime restart/degrade
persistent OpenWorker >=100 warm samples/tier
```

性能目标继续使用已经建立的门：

```text
Memory-control warm p95 <= 75 ms
T2 - T1 warm mean       <= 100 ms
T3a - T2 warm mean      <= 100 ms
validated cache p95     <= 12 ms
terminal rate           = 100%
```

## 6.7 `DG11-R06` 候选字节冻结与 wheel

在任何新 holdout answer generation 前完成：

- 构建 runtime、python-client、MCP、OpenWorker 四个 wheel；
- fresh isolated install；
- 从非仓库 cwd 启动；
- 冻结 source、config、prompt、tokenizer、projection、adapter、wheel identity；
- 保留 DG-10 wheel 作为 rollback target；
- 只生成一个 candidate manifest，不建立 candidate.1/.2/.3 审计链。

冻结后，任何源码、prompt、权重、retrieval policy 或配置变化都会创建下一 Goal，而不是修改本候选。

## 6.8 `DG11-09V2` 一次泛化验证

内部泛化 arm：

```text
CTRL_NO_MEMORY
CTRL_CUSTOM_LEXICAL_TOP1
MILAI_DG10_FROZEN
MILAI_DG11_FROZEN
```

注意：`CTRL_CUSTOM_LEXICAL_TOP1` 是 MiLAi 自定义词项重叠 Top-1，不是 LongMemEval 官方 baseline。

精确 denominator：

```text
logical cases          = 100
arms                   = 4
native answer requests = 400
answer calls/arm/case  = 1
hidden answer calls    = 0
```

使用预冻结 Latin-square schedule、同一 answer model、prompt、tokenizer、时间解释、max output 和
512-token Memory ceiling。

预注册门保持不因 v1 失败而降低：

```text
DG11 - DG10 paired F1 mean          >= +0.04
paired bootstrap lower95            > 0
DG11 - DG10 EM                      >= 0
DG11 - custom lexical Top-1 F1      >= +0.10
single-assistant delta vs custom    >= 0
preference delta vs custom          >= 0
temporal delta vs DG10              > 0
prompt-token ratio vs custom        <= 1.20x
safety failures                     = 0
```

决定：

```text
all gates PASS
→ FUNCTIONAL + OPTIMIZED

functional gates PASS, quality gates FAIL
→ FUNCTIONAL / QUALITY_TARGET_NOT_MET

any safety/function gate FAIL
→ REVERT TO DG10
```

禁止 v3。

## 6.9 `DG11-10` 最终功能交付

无论质量标签是 `OPTIMIZED` 还是 `QUALITY_TARGET_NOT_MET`，只要功能安全门通过，都可生成一个如实命名的
功能候选交付：

```text
var/dg11/final/candidate/
var/dg11/final/final-report.json
var/dg11/final/rollback.json
```

最终报告必须分开写：

```text
functional_status
quality_status
efficiency_status
paper_evaluation_status
```

---

# 7. 论文评测为何必须独立于开发

DG-10/DG-11 当前实验主要用于工程决策，存在以下论文局限：

1. MiLAi 已在 LongMemEval 多个 slice 上开发，剩余同分布 test 只能证明有限泛化；
2. 当前 `CUSTOM_LEXICAL_TOP1` 是弱的项目自定义 RAG；
3. DG-10/DG-11 对比同时改变 retrieval、compiler 和 operator，不能识别各组件贡献；
4. 当前主要使用本地 normalized EM/F1，不等同于所有 benchmark 官方 leaderboard protocol；
5. 缺少 Mem0、Hindsight、Graphiti、ReMe 等实际系统的同环境重跑；
6. 缺少跨 benchmark 的遗忘、Agent 轨迹、偏好演化和超长规模证据。

因此论文阶段必须使用冻结候选和独立 harness：

```text
DEVELOPMENT_CLOSED
→ CANDIDATE_FROZEN
→ EVALUATION_HARNESS_FROZEN
→ BASELINE_ADAPTERS_FROZEN
→ PAPER_EVALUATION_RUNNING
→ RESULTS_FROZEN
→ ANALYSIS_ONLY
```

进入 `PAPER_EVALUATION_RUNNING` 后，不允许改被测候选。发现方法缺陷时记录为结果，下一版本另立 Goal。

---

# 8. 统一论文 Evaluation Plane

## 8.1 目录与隔离

目标目录：

```text
evals/paper/
  adapters/
  contracts/
  scorers/
  schedules/
  tests/

var/dg11/paper/
  freeze/
  runs/
  raw/
  reports/
  statistics/
```

Evaluation Plane：

- 使用独立数据库、目录、端口和临时凭据；
- 只能读取 frozen MiLAi package；
- baseline 无 MiLAi Runtime token、Steward 权限或 canonical DML；
- benchmark history 只按时间顺序 ingest；
- query 前禁止访问答案、gold session ID 或 scorer label；
- raw generation、retrieval trace、cost ledger 和 terminal 状态 append-only 保存；
- 不复制真实 `.env`、Blob、日志或私密数据进入归档。

## 8.2 统一 Memory Adapter

所有方法实现同一实验接口：

```python
reset(run_id, case_id)
ingest(event, observed_at, actor, scope)
finalize()
query(question, question_at, token_budget, mode)
revoke(event_id)          # benchmark 支持时
stats()
close()
```

`query()` 只返回：

```text
model-visible memory context
source/evidence IDs
rank/score/trace
declared token count
latency and provider-call ledger
```

统一 answer runner 负责最终模型调用，避免各系统偷偷使用不同 answer prompt 或额外 answer round。

## 8.3 两条公平性赛道

### Controlled Backbone Track

```text
same answer vLLM model
same tokenizer/chat template
same answer prompt/output contract
same max completion tokens
same chronological history
same model-visible memory budget
same schedule and failure denominator
same scorer
```

embedding/reranker 在系统支持替换时使用共同本地模型；不支持时保留原生组件并明确记录。

### Native Open-Source Track

每个系统使用其冻结开源版本的推荐配置。允许内部 extraction、reflection、graph build 不同，但必须完整报告：

```text
ingest model calls/tokens
query model calls/tokens
embedding/rerank calls
index time
query latency
storage
answer calls
```

不得把 vendor managed/proprietary 分数与本地 MiLAi 分数直接并列为同环境结果。

---

# 9. Baseline 与外部项目矩阵

## 9.1 控制组与官方 baseline

| ID | 方法 | 作用 | 发布地位 |
| --- | --- | --- | --- |
| `CTRL-NONE` | No Memory | 测量模型本身与拒答下限 | 必跑 |
| `CTRL-CUSTOM-LEX1` | 当前自定义 lexical session Top-1 | 保持 DG-10/DG-11 连续性 | 必跑，但不得称官方 |
| `CTRL-FULL` | Full history，输入可容纳时 | 长上下文直接输入 | 条件必跑 |
| `CTRL-TRUNC-FULL` | 明确标记的截断 full history | 描述 context-limit 影响 | characterization only |
| `LME-BM25-S` | LongMemEval `flat-bm25` session | 官方稀疏检索 baseline | LongMemEval 必跑 |
| `LME-BM25-T` | LongMemEval `flat-bm25` turn | 官方细粒度稀疏 baseline | LongMemEval 必跑 |
| `LME-DENSE` | `flat-gte`；可扩展 Stella/Contriever | 官方 dense baseline | 至少一项必跑 |
| `LME-ORACLE` | 只给 evidence sessions | 回答上限/检索误差分解 | 上限，不参与普通胜负 |
| `DG10-FROZEN` | MiLAi DG-10 frozen | 旧系统基线 | 必跑 |
| `DG11-FULL` | 当前冻结 MiLAi | 被测方法 | 必跑 |

## 9.2 外部系统

| ID | 本地项目 | 代表能力 | Controlled Track | Native Track |
| --- | --- | --- | --- | --- |
| `MEM0-OSS` | `../mem0` | 事实抽取、多信号、实体和时间检索 | 必做 feasibility | 必跑（可运行时） |
| `HINDSIGHT-OSS` | `../hindsight` | retain/recall/reflect、经验学习 | 必做 feasibility | 必跑（可运行时） |
| `GRAPHITI-OSS` | `../graphiti` | 时序图、实体关系和历史状态 | 必做 feasibility | 必跑（可运行时） |
| `REME-OSS` | `../ReMe` | 文件记忆、BM25、embedding、链接扩展 | 必做 feasibility | 必跑（可运行时） |

当前 checkout 身份起点：

```text
Mem0     001c235229be8795e3834520467bd0d661ed8f34
Graphiti 401c59a65bdeb22a44136901ff30231e6998a7fe
Hindsight  当前目录无 Git metadata，评测前必须生成逐文件 inventory root
ReMe       当前目录无 Git metadata，评测前必须生成逐文件 inventory root
```

正式运行前必须重新冻结 commit/inventory、dependency lock、license、模型配置和 adapter SHA。某系统只有在以下
预注册原因成立时可排除：

```text
license incompatible
无法使用本地 Provider 且会改变 Provider 边界
缺少公开可运行实现
无法完成最小 ingest/query contract
资源需求超过预冻结上限
```

不得因 pilot 分数低或高而选择性排除。排除报告必须在打开 paper test 前完成。

外部系统不支持某项能力时不得在 adapter 中伪造实现。例如系统没有 revoke/forget API 时，应报告
`CAPABILITY_UNSUPPORTED`，并在 Memora/删除表中保留该事实；不能通过直接删库、重建索引或修改 gold history
冒充正常产品删除路径。

## 9.3 Benchmark-native 方法

| Benchmark | Native baseline |
| --- | --- |
| LongMemEval-V2 | `no_retrieval`、`rag_query_to_slice`、`rag_query_to_slice_notes`、AgentRunbook-R/C、Codex baseline（feasibility 后） |
| BEAM | 官方 RAG/long-context baseline 与 LIGHT |
| Memora | 官方 direct/model 与 agent-eval protocol；可运行的公开 memory agent adapter |
| PAHF | no-memory、SQL/FAISS memory、pre/post feedback variants |

`Codex baseline` 是 benchmark 方法时才作为被测 baseline；Codex 的独立 review 不能替代 benchmark scorer。

---

# 10. Benchmark 组合与比较目的

## 10.1 核心论文矩阵（P0）

| Benchmark | 当前本地仓库 | 主要能力 | MiLAi 关键 claim | 最低比较方法 |
| --- | --- | --- | --- | --- |
| LongMemEval cleaned v1 | commit `9e0b455f...043fc` | 提取、多会话、更新、时序、拒答 | 通用长期会话记忆 | 官方 BM25/dense、Oracle、四外部系统、DG10/DG11 |
| Memora | commit `a6493188...a30ff` | remembering、reasoning、recommending、forgetting | revoke/删除/更新后的安全记忆 | no-memory、BM25、Mem0/Hindsight/Graphiti/ReMe、MiLAi |
| LongMemEval-V2 small | commit `2cc8c540...4520` | Web/enterprise Agent 轨迹经验 | Agentic procedure/环境状态记忆 | native RAG、AgentRunbook-R/C、MiLAi；外部系统可行时加入 |

核心论文结论至少需要其中两个 benchmark 完整结束，且必须包含 Memora 或等价 forgetting benchmark；只有
LongMemEval 同分布结果不足以支持广泛泛化 claim。

LongMemEval 同时输出两套不可混淆的结果：

```text
LME-PAPER-HOLDOUT-100
  = 最后 100 个未用于开发的程序性 holdout
  = 主要用于内部泛化与配对效应

LME-FULL-500-CHARACTERIZATION
  = 冻结候选对官方完整 500 cases 的运行
  = 便于与公开协议/方法比较
  = 必须披露其中 300 cases 曾用于 DG-10/DG-11 开发或误差分析
```

不得把 full-500 characterization 描述成完全未见 test。`CTRL-FULL` 因上下文预算不同，也必须放在
long-context characterization 表，而不是 equal-memory Controlled Track 主胜负表。

## 10.2 扩展矩阵（P1）

| Benchmark | 当前本地仓库 | 目的 | 初始规模 |
| --- | --- | --- | --- |
| BEAM | commit `3e120355...be9` | 128K→1M/10M 扩展性、多种记忆能力 | 先 128K；通过资源门再 500K/1M |
| HorizonBench | commit `4b5076b1...ef0b` | 六个月偏好演化、旧偏好 hard negative | sample→full |
| CUPID | commit `a8560cab...1b6c` | 情境化、动态偏好推断与应用 | 预注册 subset→full |
| PAHF | commit `7a112133...f8cf` | feedback 驱动的 Agent 行为学习 | embodied/shopping 各一条完整路线 |

## 10.3 集成与工具调用矩阵（P1，不是记忆质量主指标）

| 测试 | 作用 | 不允许的 claim |
| --- | --- | --- |
| DG11 paired Agent workload | Memory 是否改善真实 Agent 任务 | 不能替代公开 benchmark |
| OpenWorker hardened S1–S10 | socket/profile/Scope/terminal 安全 | 不能证明模型质量 |
| BFCL | tool selection、arguments、no-call、多轮恢复 | 不能称 MCP transport/protocol benchmark |
| MCP wire suites | initialize/list/call/reconnect/stdio/UDS | 不能称长期记忆质量 benchmark |

## 10.4 LongMemEval-V2 modality feasibility

在打开 small-tier test 前冻结：

```text
required modalities
Qwen 当前模型能力
tool/browser requirement
image/OCR handling
adapter lossiness
official vs adapted protocol
```

若当前 vLLM 模型无法消费必需图像或轨迹字段：

```text
full official protocol = NOT_APPLICABLE
frozen text-only slice = ADAPTED_PROTOCOL
```

不得丢弃模态后继续声称官方 leaderboard 分数。

---

# 11. MiLAi 消融设计

消融使用同一 frozen candidate 的 Evaluation Plane 配置，不修改 Production Runtime 或 canonical 数据。

## 11.1 质量消融

| ID | 变化 | 要回答的问题 |
| --- | --- | --- |
| `ABL-RET-FTS` | 仅 FTS | dense lane 的增益是多少 |
| `ABL-RET-DENSE` | 仅 vector | lexical lane 的增益是多少 |
| `ABL-RET-16D` | 128d→DG10 16d projection | 高维 projection 是否真正贡献 |
| `ABL-NO-WINDOW` | session-only projection | turn/window 粒度贡献 |
| `ABL-NO-RERANK` | 关闭 cross-encoder rerank | reranker 的质量/延迟收益 |
| `ABL-NO-SETCOVER` | 普通 Top-k 替代 evidence set cover | 多会话覆盖策略贡献 |
| `ABL-DG10-COMPILER` | 使用 DG-10 compiler | compact/结构保护贡献 |
| `ABL-NO-TEMPORAL-OP` | 关闭 deterministic operator | temporal operator 贡献 |
| `ABL-FIXED-K3` | 关闭 intent-adaptive pool | adaptive retrieval 贡献 |

## 11.2 安全/治理反事实消融

以下仅在 synthetic 隔离数据库运行，不能进入普通 Agent 或真实数据路径：

| ID | 变化 | 指标 |
| --- | --- | --- |
| `ABL-RAW-NO-CANONICAL-GATE` | 直接使用派生候选 | stale/invalid/authority leak rate |
| `ABL-NO-OPENISSUE-PRESERVE` | 不保护 OpenIssue | false certainty/false closure |
| `ABL-NO-REVOKE-FILTER` | 不执行 revoke gate | deleted/stale evidence leak |
| `ABL-NO-SCOPE-GATE` | 不检查 Scope | cross-scope action rate |

这些结果用于说明治理组件的安全贡献，不能为了分数更高而成为产品配置。

## 11.3 效率消融

| ID | 变化 | 指标 |
| --- | --- | --- |
| `ABL-NO-CACHE` | 关闭 validated cache | cache validation 与 payload reuse 收益 |
| `ABL-NO-PREFETCH` | reactive MCP tool use | prefetch 对 calls/latency/quality 影响 |
| `ABL-SHORTLIVED-WORKER` | 每次启动 Worker | persistent OpenWorker 收益 |
| `ABL-FULL-METADATA` | UUID/trace 进入正文 | sidecar 对 token 的贡献 |

## 11.4 参数曲线

只对最终方法做预注册小规模 sweep：

```text
memory budget = 128 / 256 / 512 / 1024 tokens
visible top-k = 1 / 3 / 5
candidate pool = 10 / 30 / 50
```

输出质量—token—延迟 Pareto 曲线。不得从 paper test 中挑最佳参数再报告同一 test 分数；参数选择只用
development/calibration split。

---

# 12. 评测公平性合同

## 12.1 Answer model 一致性

Controlled Track 固定：

```text
model weights and revision
vLLM version
tokenizer + chat template
temperature/top_p/seed
system and answer prompt
tool schema serialization
max completion tokens
question timestamp interpretation
```

所有 memory 方法只影响 memory context，不得改变答案模型或问题。

## 12.2 Token Truth

三层分开报告：

```text
vLLM native prompt/completion usage       = accounting truth
final serialized prompt tokenizer recount = deterministic verification
MiLAi component attribution              = decomposition only
```

Memory budget包含最终模型可见 memory context。系统内部 metadata、recovered source token 和额外 tool result
也必须计入对应成本，不能只数初始摘要。

## 12.3 Provider calls

分别记录：

```text
ingest extraction calls
reflection/consolidation calls
embedding calls
reranker calls
memory query model calls
answer calls
judge calls
retry/failure calls
```

主表至少报告 end-to-end 总调用和总 token。不能用“每例一次 answer”隐藏昂贵的 ingest/consolidation。

## 12.4 顺序与服务状态

- arm 顺序使用冻结 Latin-square/counterbalanced schedule；
- cold/warm 分开；
- GPU 处于 exclusive 或可量化共享窗口；
- queue depth、并发、失败和 retry 进入 raw log；
- infrastructure failure 不能从 denominator 删除；
- 可恢复中断只能用相同 request/native ID 继续，不得选择性重生成低分答案。

## 12.5 Scorer 与 judge

优先级：

```text
Tier 1  benchmark 官方 deterministic metric / exact / F1 / retrieval metric
Tier 2  blinded human subset 或独立冻结 evaluator
Tier 3  same-vLLM judge，仅作 characterization
```

same-vLLM judge 不能单独决定论文质量结论。Codex `gpt-5.6-sol` 只允许在最终冻结结果后做一次
claim-to-evidence/reproducibility review，不生成样本、不打分、不修改候选、不关闭 finding。

## 12.6 两种结果不可混合

```text
Controlled Track score
Native Track score
published vendor/paper score
```

三者必须分表。只有本工作区同协议重跑的结果可用于直接显著性比较；论文或 vendor 自报分数只作背景。

---

# 13. 指标与统计计划

## 13.1 质量

```text
Exact Match / normalized F1 / official accuracy
retrieval Hit@k / Recall@k / NDCG@k
relevant evidence coverage
answer-span survival after compile
knowledge-update accuracy
temporal accuracy
abstention precision/recall
wrong-certain rate
Memora FAMA
LongMemEval-V2 official LAFS/quality metrics when protocol applies
```

## 13.2 安全与记忆治理

```text
revoked/deleted evidence leak rate
stale-version answer rate
OpenIssue false closure rate
conflict branch preservation
Scope/authority violation
canonical-unavailable false certainty
unsupported claim rate
```

安全失败独立报告，不能被平均质量分数抵消。

## 13.3 效率

```text
ingest p50/p95 and throughput
query/retrieval p50/p95/p99
MCP/Runtime/control latency
answer E2E p50/p95/p99
prompt/completion/memory tokens
provider calls per episode/query
index/storage bytes
CPU/RAM/GPU/VRAM when measurable
cache validation requests/ms/hit/invalidation rate
```

至少分四层 serving：

```text
T0 raw vLLM
T1 OpenWorker/Gateway → vLLM, no memory
T2 MiLAi integrated, route NONE
T3 OpenWorker → MCP → Runtime → vLLM, memory used
```

## 13.4 Agentic

```text
task success
steps/tool calls/retries
memory-used rate
unnecessary recall
wrong-certain action
stale/revoked action
explicit terminal rate
wall time and provider tokens
```

## 13.5 统计

- 所有主要比较使用 paired case-level 结果；
- 报告 paired mean/median delta 与 bootstrap 95% CI；
- 二元 EM/accuracy 使用 McNemar 或配对 bootstrap；
- 连续 F1/latency 使用配对 permutation/bootstrap；
- 多方法、多 benchmark 比较采用 Holm 校正；
- 报告 wins/losses/ties 和按类别结果，不只报告总体均值；
- 随机方法使用至少 3 个预注册 seed；温度 0 且确定性的 answer 可使用一次；
- 同时报告 effect size、CI 和原始 denominator，不以单一 `p < 0.05` 代替工程意义。

---

# 14. 论文评测工作包

## `DG11-PE00` Claim 与预注册矩阵

创建 machine-readable `claim-matrix.yaml`，将每个 claim 映射到 benchmark、baseline、metric、threshold、
cost 和允许结论。打开 paper test 前冻结。

## `DG11-PE01` Harness 与 adapter contract

完成统一 adapter、answer runner、usage ledger、failure semantics、resume 和 archive scanner。只使用 5–10 个
已打开案例做 smoke，不看 paper labels。

## `DG11-PE02` 官方 baseline

完成 LongMemEval BM25 session/turn、至少一个 dense baseline、full/truncated history 与 Oracle；确认官方代码
commit、依赖和 scorer 可重复。

## `DG11-PE03` 外部项目 feasibility

对 Mem0、Hindsight、Graphiti、ReMe 各完成：

```text
fresh isolated install
local vLLM connectivity
chronological ingest
one query
one deletion/update case where supported
usage/cost capture
cleanup
```

feasibility 结束后一次性冻结 inclusion/exclusion，不按分数选择。

## `DG11-PE04` LongMemEval paper run

先在预留 100-case paper split 上运行核心 arm，再对同一冻结候选运行 full-500 characterization。两套结果分表；
该 run 结束前禁止读取 aggregate 分数并修改候选或 baseline。

## `DG11-PE05` Memora

先运行官方 smoke，随后按官方 period/task split 运行完整或预注册规模。主要报告 FAMA、remember/forget
分解和删除泄漏。

## `DG11-PE06` LongMemEval-V2

先完成 modality feasibility，再运行 official small 或明确的 adapted text-only protocol。主要比较
native RAG、AgentRunbook 与 MiLAi。

## `DG11-PE07` BEAM 扩展性

先跑 128K；只有质量、稳定性与资源预算满足后进入 500K/1M。10M 属于扩展 characterization，不阻塞
核心论文包。

## `DG11-PE08` Preference benchmarks

运行 HorizonBench 和 CUPID 的预注册矩阵，重点分析 static/evolved、consistent/contrastive/changing preference。

## `DG11-PE09` 消融

运行第 11 节预注册的一因素消融；只对最关键交互做有限 2×2，不进行无界组合搜索。

## `DG11-PE10` Agent/MCP/Serving

运行 paired Agent workload、OpenWorker/MCP wire、安全反例和 T0–T3 serving。BFCL 结果单列为 tool-calling
语义，不混入记忆质量主表。

## `DG11-PE11` 统计与 failure taxonomy

生成配对统计、置信区间、质量—成本 Pareto、按类别/长度/方法失败矩阵。此阶段只分析，不改代码。

## `DG11-PE12` 论文结果包

只生成一次：

```text
paper-freeze-manifest.json
method-configs/
raw-generations/
retrieval-traces/
usage-ledgers/
metrics.json
statistics.json
tables/
figures/
limitations.md
reproduction.md
```

若需要独立 review，只在该包冻结后启动一次；review finding 不触发第二轮 AI review，而是通过确定性重现
处理或进入下一 Goal。

---

# 15. 执行顺序与停止条件

## 15.1 立即执行顺序

```text
DG11-R00 freeze remaining splits + v1 error matrix
→ DG11-R01 compiler structural fixes
→ DG11-R02 multi-session evidence-set optimization
→ DG11-R03 operator route precision
→ DG11-R04 one combined DEV-2
→ DG11-R05 functional/agentic/efficiency regression
→ DG11-R06 freeze packages/candidate
→ DG11-09V2 one generalization run
→ DG11-10 truthful functional/quality handoff
→ DEVELOPMENT_CLOSED
→ DG11-PE00..PE12
```

## 15.2 优先级

```text
P0  protect last 200 LongMemEval cases
P0  multi-session coverage regression
P0  functional/security regression and candidate freeze
P1  role/list/numeric compiler preservation
P1  temporal route precision
P1  official baseline and external adapter feasibility
P1  LongMemEval + Memora + LongMemEval-V2 core paper matrix
P2  BEAM/Horizon/CUPID/PAHF extended matrix
P2  final independent review
```

## 15.3 开发停止条件

立即停止最近改动并回滚：

```text
canonical invariant violation
cross-tenant/Scope/profile leakage
OpenIssue/revoke fail-open
stale cache authorizes action
hidden answer model call
gold label enters retrieval/compiler/prompt
secret/private content leakage
```

停止某个优化假设：

```text
three bounded attempts without cross-slice benefit
quality gain is entirely explained by more visible tokens
gain disappears under paired comparison
latency/call cost dominates benefit
safety ablation is required to obtain the gain
```

停止同一候选继续开发：

```text
candidate frozen
or v2 consumed
or first paper answer generated
```

---

# 16. Provider、计算与审计预算

## 16.1 开发期

```text
retrieval-only A/B          = 0 answer calls
targeted compiler/operator  <= 60 answer calls / attempt
combined DEV-2              = one run
v2 holdout                  = exactly 400 answer calls
development AI reviews      = 0
```

## 16.2 论文期

每个 run 在启动前计算：

```text
expected answer calls
expected ingest/query model calls
expected tokens
expected wall time
expected storage
maximum retry terminals
```

先用已打开的 5–10 个案例验证 adapter，再一次性进入完整 run。不得用 paper test 做 smoke。

## 16.3 AI review 硬上限

```text
development reviews             = 0
paper final reviews              <= 1
review bundle                    = frozen/redacted/inventory-bound
review model token budget        <= 120,000
iterative AI re-review chain     = 0
```

AI review 只能检查 claim/evidence/reproducibility；不能替代代码、benchmark、统计或人类论文决定。

---

# 17. 状态机与完成矩阵

## 17.1 当前权威状态

```text
DG11-00 PASS
DG11-01 REVERTED
DG11-02 PASS
DG11-03 PASS
DG11-04 PASS
DG11-05 PASS
DG11-06 PASS
DG11-07 PASS
DG11-08 PASS
DG11-09 HOLDOUT_FAILED
DG11-10 NOT_STARTED
```

文档更新不自动修改 `current-state.json`。只有对应动态证据完成后才写入新状态。

## 17.2 后续状态机

```text
HOLDOUT_FAILED
→ RECOVERY_DATA_FROZEN
→ RECOVERY_DEV_PASS
→ FUNCTIONAL_REGRESSION_PASS
→ CANDIDATE_FROZEN
→ V2_CONSUMED
→ FUNCTIONAL_CANDIDATE
   ├─ QUALITY_TARGET_MET
   └─ QUALITY_TARGET_NOT_MET
→ PAPER_HARNESS_FROZEN
→ PAPER_RESULTS_FROZEN
→ ANALYSIS_COMPLETE
```

## 17.3 后续矩阵

| ID | 当前状态 | 输出 |
| --- | --- | --- |
| `DG11-R00` | `NOT_STARTED` | 剩余 200 分割 + v1 failure matrix |
| `DG11-R01` | `PARTIAL` | 已有 5-case targeted evidence；缺完整 compiler regression |
| `DG11-R02` | `NOT_STARTED` | 多会话 evidence-set 优化 |
| `DG11-R03` | `PARTIAL` | 已修已知误路由；缺完整 route regression |
| `DG11-R04` | `NOT_STARTED` | Combined DEV-2 |
| `DG11-R05` | `NOT_STARTED` | 功能、安全、Agent、效率回归 |
| `DG11-R06` | `NOT_STARTED` | frozen candidate + wheels |
| `DG11-09V2` | `NOT_STARTED` | 一次 100-case 泛化结果 |
| `DG11-10` | `NOT_STARTED` | 如实命名的最终功能交付 |
| `DG11-PE00..03` | `NOT_STARTED` | paper contract/harness/baselines |
| `DG11-PE04..10` | `NOT_STARTED` | benchmark/ablation/serving raw results |
| `DG11-PE11..12` | `NOT_STARTED` | statistics + paper result package |

---

# 18. Definition of Done

## 18.1 DG-11 功能完成

同时满足：

1. 冻结 DG-10 rollback target；
2. 当前源码、prompt、projection 和四个 wheel 有唯一 candidate identity；
3. F0/F1、受影响 T2/S1–S10、OpenIssue、Scope、revoke、cache 无回归；
4. 20 个 paired Agent tasks 达到任务与安全门；
5. persistent OpenWorker 与 T0–T3 效率可复算；
6. fresh isolated install 与非仓库 cwd 启动通过；
7. v2 只运行一次并如实记录；
8. 无论质量是否达标，报告不隐藏负结果；
9. Runtime 仍为 CANDIDATE，Schema 仍为 EXPERIMENTAL/NO-GO。

## 18.2 优化声明完成

除功能 DoD 外，`DG11-09V2` 全部质量门通过，才允许：

```text
MILAI_PREFETCH_AGENT_OPTIMIZED_CANDIDATE
```

否则只能：

```text
MILAI_MEMORY_MCP_FUNCTIONAL_CANDIDATE
QUALITY_TARGET_NOT_MET
```

## 18.3 论文评测完成

同时满足：

1. 被测 MiLAi 候选在所有 paper runs 前冻结；
2. official BM25/dense/full/oracle baseline 身份与协议冻结；
3. Mem0、Hindsight、Graphiti、ReMe 均完成或有预注册技术排除理由；
4. LongMemEval、Memora、LongMemEval-V2 核心矩阵至少完成两个，且包含 forgetting/agentic 之一；
5. 关键质量消融、安全反事实和效率消融完成；
6. Controlled 与 Native Track 分表；
7. raw generation、retrieval、usage、failure denominator 可复算；
8. paired CI、effect size、category、cost/Pareto 完整；
9. same-vLLM judge 不作为唯一结论来源；
10. 论文结果没有反向驱动同一候选改代码；
11. 只生成一个 final paper result package；
12. 独立 AI review 至多一次且不成为 authority。

## 18.4 仍然禁止的声明

```text
PRODUCTION_READY
SCHEMA_FROZEN
DYNAMIC_TOOL_AGENT_READY
EXTERNAL_PROVIDER_BILLING_VERIFIED
REAL_PRIVATE_DATA_APPROVED
GENERAL_MULTI_AGENT_MEMORY_PLATFORM
OUTPERFORMS_LONGMEMEVAL_BASELINES   # 在官方同协议实验完成前
STATE_OF_THE_ART                    # 在可复算公开比较完成前
```

---

# 19. 下一执行清单

```text
[ ] 1. 不运行 Provider，冻结剩余 200 个 LongMemEval 案例为 v2/paper 两组
[ ] 2. 对 v1 100 个案例生成 R0–R7 全量失败矩阵
[ ] 3. 将当前 5-case 修复扩展为 compiler/operator 回归测试
[ ] 4. 离线运行多会话 B0–B4 retrieval/set-cover/rerank A/B
[ ] 5. KEEP 一个多会话方案并运行最窄 answer DEV
[ ] 6. 运行一次 Combined DEV-2，KEEP 或 REVERT
[ ] 7. 运行 F0/F1/受影响安全/20 Agent/serving 回归
[ ] 8. 构建并冻结唯一 DG-11 候选与四个 wheel
[ ] 9. 对 v2 执行一次 400-request 四臂泛化验证
[ ] 10. 生成 FUNCTIONAL/OPTIMIZED 或 QUALITY_TARGET_NOT_MET 的如实交付
[ ] 11. 冻结 paper claim matrix、adapter contract 和 baseline inclusion
[ ] 12. 完成官方 BM25/dense/oracle 与四个外部系统 smoke
[ ] 13. 运行 LongMemEval paper test、Memora、LongMemEval-V2 核心矩阵
[ ] 14. 运行预注册消融、Agent/MCP/serving 和统计分析
[ ] 15. 只生成一次 paper result package；必要时一次只读独立 review
```

当前第一个执行动作是：

```text
DG11-R00：保护最后 200 个 LongMemEval 案例并建立完整失败矩阵
```

不是继续针对 v1 holdout 调参，不是启动新审计，也不是先构建论文结论。
