# MiLAi DG-12 Goals：本体优先开发、高效 Benchmark 与论文证据

> Goal ID：`DG-12`  
> 文档版本：`0.9.1 ACTIVE — PRE_LABEL_PARALLEL_EXECUTION`  
> 生效日期：`2026-08-24`（Asia/Shanghai）  
> 接管范围：DG11 冻结功能候选之后的 MiLAi 本体开发、通用性能优化、薄评测适配、创新发现与论文实验  
> 前序状态：`DG-11 DEVELOPMENT_CLOSED / FUNCTIONAL PASS / QUALITY_TARGET_NOT_MET`  
> 当前执行动作：v3 one-way manifest 与无标签 `PE01/PE02` gate 均已 PASS；为唯一一次正式 `PE02` 建立资源计划并预检  
> Answer Provider：`self-hosted vLLM 0.27.1 / Qwen3.6-35B-A3B-FP8`  
> 数据边界：`SYNTHETIC / PUBLIC BENCHMARK / DEIDENTIFIED ONLY`  
> 开发期 AI review：`0`  
> 最终独立 AI review：`至多 1 次；只读；非 scorer；非 authority`  
> 创新发现模式：`AFTER_PRODUCT_READY / RIVAL_HYPOTHESIS / DISCOVERY ≠ CONFIRMATION`  
> Skill 策略：`LOCAL_FIRST / SELECTIVE / NO_AUTOMATIC_REVIEW_AGENT`  
> 开发原则：`PRODUCT CORE FIRST / EXPERIMENTS ARE CONSUMERS / NO GOAL-NAMED PRODUCT CODE`  
> 主产品接口：`MCP`  
> 首要 Agent Host：`OpenWorker`  
> Task Resolver：`DETERMINISTIC_ONLY / NO TRAINING / NO MODEL CALLS`  
> Learned Task Resolver：`PARKED_UNTIL_POST_E2E_SUCCESSOR_GOAL`  
> 新模型训练：`DISABLED FOR CURRENT DG-12 CANDIDATE`  
> 正式实验并发：`8-way stateless/provider + 4 isolated stateful + 2 isolated dense / fixed before labels`  
> Logical Architecture：`1.0.0 FROZEN`  
> Runtime：`0.1.x CANDIDATE`  
> Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

---

# 0. Goal 决定

DG-12 接管旧 DG-11 Goal 中尚未完成的后续开发与论文实验。旧文档
`MiLAi_DG-11记忆质量与Agent效率优化_GOALS.md` 保留为 DG11 历史、失败与恢复证据，不再作为当前任务板。

当前不是重新证明 MiLAi 有没有基本功能。已经成立的起点是：

```text
MiLAi can operate as a governed Memory MCP for the supported local OpenWorker path.

DG11 functional_status       = PASS
DG11 quality_status          = QUALITY_TARGET_NOT_MET
DG11 paper_evaluation_status = NOT_STARTED
DG12 BHE00 stage_profile      = PASS
DG12 BHE01 current prototype  = STOPPED_FOR_PRODUCT_BOUNDARY_REDESIGN
DG12 CORE00/01/02             = PASS
DG12 PD00/01                  = PASS
DG12 EH00/01/02/03            = PASS
DG12 ND00                     = PASS
DG12 ND01                     = PASS
DG12 PD02                     = TERMINAL_TARGET_MISS
DG12 PD02 FP1                 = PASS_FP1_DETERMINISTIC_TASK_BINDING
DG12 EH04                     = PASS
DG12 ND02                     = PASS_DEV_SIGNAL
DG12 ND03                     = PASS_MECHANISM_DISTINGUISHED
DG12 ND04                     = PASS_METHOD_OVERLAP_EMPIRICAL_BOUNDARY_OPTION
DG12 ND05                     = PASS_SELECTED_BOUNDARY_PACKAGE
DG12 PE00                     = PASS_DOCUMENT_FREEZE_EXECUTION_GAPS_DISCOVERED_PE02
DG12 PE00V3                   = IN_PROGRESS_AUTHORIZED_PRE_LABEL_SUCCESSOR
DG12 PE01                     = PASS; successor identity must be reconfirmed
DG12 PE02                     = BLOCKED_PRE_LABEL_PROTOCOL_AND_HARNESS_GAPS
DG12 product 5x objective     = MISS (1.463x)
DG12 evaluation reuse         = PASS (19.815x vs frozen reference; build_calls=0)
```

DG-12 的目标是依次完成：

```text
已完成真实阶段计时、本体整理、产品纵向验证、薄 Benchmark Harness 与 focal/rival hypothesis freeze
→ 先测量并贯通 OpenWorker task continuity、Need/StateKey、NONE/CACHE/L0 route 与 CurrentStateRead
→ 再分离 governed ingest、fragment derivation、embedding、projection write/index 与 deep-query 成本
→ 用 strongest-simple-replacement 分别关闭在线 Fast Path Reachability 与 cold materialization 的真实瓶颈
→ retained product bytes 经 OpenWorker→MCP→Runtime 复验并重新冻结 harness
→ 从失败分层和机制探针继续生成候选假设
→ 用对照、消融和反事实实验区分候选机制
→ 只对出现可重复实验信号的候选做一次有边界的查新
→ 冻结唯一实验协议与方法身份
→ 官方 baseline + 外部项目 + MiLAi 消融
→ 多 benchmark 正式实验
→ 质量、正确性、延迟、token、调用和存储联合分析
→ 用实验结果形成下一轮工程决定
→ 只有 E2E/core benchmark 跑通且 deterministic Task Binding 残差 materially limiting，才提出后继模型训练 Goal
→ 至多一次最终证据审阅
```

本 Goal 纠正四种错误工作方式：

1. 不再把每个 benchmark case 当作一次完整产品部署；
2. 不再用 receipt、hash 数量或反复 AI 审计代替实际代码能力和动态结果；
3. 不再因当前不能宣称质量胜出而停止开发效率、正确性和可用性；
4. 不再使用已经打开或消费的数据反复调参并冒充泛化。

并增加一条高于所有 DG-12 工作包的工程约束：

> **实验不能拥有 MiLAi 产品能力。任何希望 Agent、MCP 或真实部署复用的能力，必须先进入本体的语义接口、
> 正常配置、测试和 wheel；实验代码只能解析数据集、编排调用、平衡顺序、计分和导出结果。**

这同时意味着“本体化”不能采用整目录搬运：`evals/` 中的 Runtime 生命周期、连接复用、context policy、
embedding/projection、治理摄取或观测能力必须重新落到正确的产品 owner；dataset DTO、benchmark loader、
scorer、split、schedule、label boundary 和结果导出仍留在 `evals/`。同一能力不得在本体与实验层各保留一份
可独立演进的实现。

`CORE00～CORE02`、`PD00～02`、`EH00～04` 与 `ND00～05` 均已有 terminal。`PD02` 的功能等价性已经通过，
但 online、deep、cold 三类性能目标均未达到，因此不得补发产品 speed claim。现行阻断已转移到正式论文执行
identity，而不是继续改产品或训练模型：

```text
FP1 deterministic execution-aware Task Binding 已通过
→ Task identity、Need、CACHE authorization 仍保持分离

当前 DG-12 Task Resolver 仅允许 deterministic execution anchors + lexicographic transition rules
→ 禁止训练/微调 LightGBM、XGBoost、Qwen 或其他 learned resolver
→ 禁止为 task identity 调用 LLM、embedding、retrieval 或外部 Provider

完整 OpenWorker→MCP→Runtime 端到端 benchmark 尚未按 §7A.2.6 terminal
→ learned resolver 只能保持 PARKED，不能创建训练集、训练代码、模型 artifact 或新执行工作包

PE00 v2 文档协议已完成，但 PE02 的零调用 preflight 暴露 runner、schedule、producer、annotation 与 clean-source
identity 缺口；正式 labels、contexts、answers、scores 仍为 0

用户已授权 PE00V3 pre-label successor；两份独立盲法 annotation 已完成，v3 runner/producer 正在绑定
→ 在 one-way manifest seal 前允许修正物理并发与资源计划
→ 不允许改变方法、阈值、样本、逻辑调用数、失败分母或产品 candidate

当前机器为 16 物理核、约 215 GiB 可用内存、4×A100；vLLM 占 GPU0/1，GPU2/3 可供隔离检索 baseline
→ 固定 <=2 的旧实验上限停止使用
→ 采用 §19 的 8-way stateless/provider lane 与 4 个独立 stateful process

完成 v3 seal 后只允许：
1. 对新 identity 重跑无标签 PE01/PE02 gate；
2. gate 全部 PASS 后才打开一次正式 label/answer/scoring 链；
3. 不因提高物理并发增加 retry、hidden call 或 method/case 逻辑 attempt
```

本文中的“本体”指 MiLAi product core（Runtime、domain/application/persistence/worker/operations、Python Client、
MCP/OpenWorker integration 和正式 contracts），不是为论文额外建立一套知识本体。

论文创新点不在本 Goal 开始时预设为事实。DG-12 允许从 DG11 失败、分层 benchmark、机制消融和效率—质量
Pareto 中发现三种不同贡献候选：`METHOD`、`SYSTEMS`、`EMPIRICAL_FINDING`。候选必须先经过可证伪的实验，
再经过有边界的 prior-work 检索，最后才进入 paper claim；“工程复杂”“审计严格”或“别人没这么命名”都不
构成创新。

DG-12 完成不要求 MiLAi 在每个 benchmark 上获胜。负结果只要协议公平、数据完整、失败分母真实、统计可复算，
同样可以关闭实验 Goal。质量未胜出时，结论必须是 `QUALITY_NOT_PROVEN` 或 `METHOD_LIMITATION_FOUND`，
而不是继续改同一冻结候选直到分数变好。

---

# 1. 规范层级与接管边界

## 1.1 文档优先级

1. `architecture/v1.0/` frozen Logical Architecture；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` 中的 frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. 本 DG-12 Goal；
5. `MiLAi_Agent执行效率与Token优化设计开发文档_v1.md` §22；
6. 冻结后的 DG12 paper protocol、claim matrix 和 method configs；
7. 实验性 runner、脚本与报告。

出现冲突时不能用 runner 的便利性覆盖 Evidence、Proposal、Decision、OpenIssue、Canonical Gate、Scope、
revoke、Outbox 或权限语义。

## 1.2 状态事实源

当前 DG11 事实仍由以下文件决定：

```text
var/dg11/current-state.json
var/dg11/final/final-report.json
var/dg11/final/candidate/inventory.json
```

DG-12 实施后建立一个精简状态文件：

```text
var/dg12/current-state.json
```

它只保存工作包状态、当前 candidate、当前 protocol、允许的下一动作和最终 artifact 指针。Markdown 不能
自动晋级状态，run report 也不能自动产生 `PASS`。

## 1.3 对旧 DG11 的处理

以下事实继承且不重做：

- `DG11-R00～R06 = PASS`；
- `DG11-10 = PASS`；
- DG11 candidate 已冻结；
- v1 holdout 已消费且失败；
- v2 因基础设施故障、0 native request、labels 未打开而不可再重跑；
- DG11 功能声明可以保留，质量优化声明不能补发。

旧 DG11 Goal 的“当前状态”“下一执行清单”和 `DG11-PE00～12` 未来状态由本 Goal supersede；其原始结果、
失败和设计讨论不删除、不覆盖。

## 1.4 不重开 Logical Architecture

本 Goal 不改变：

```text
PostgreSQL Canonical Core single writer
Evidence != accepted belief
Proposal != canonical state
ClaimVersion append-only
ClaimHead exact-head CAS
OpenIssue cannot be summarized away
secondary index result is candidate only
Canonical Gate before action-safe context
revoke fails closed before asynchronous purge
Agent/MCP/model/benchmark/reviewer has no canonical authority
```

如果效率实现需要改变对象身份、权限、删除或事务语义，停止当前工作包并提交单独 ADR；不能把它隐藏在
benchmark-only helper 中。

## 1.5 主产品形态：OpenWorker 的 MiLAi MCP Memory Tool

MiLAi 的首要使用方式不是让业务 Agent 直接 import Runtime，也不是把 Python Client 当作最终产品接口；它是
由 OpenWorker 托管和调用的 profile-scoped MCP memory tool。权威主链为：

```text
OpenWorker task host
→ host-owned memory_mode / task policy
→ credential-free stdio relay
→ profile-specific UDS capability
→ trusted broker
→ milai-mcp
→ milai-client internal loopback transport
→ milai-runtime
→ PostgreSQL Canonical Core + embedding/reranker workers
```

模型回答链与记忆链分开：

```text
memory path: OpenWorker → MCP → Runtime → governed context/tool result
answer path: OpenWorker → vLLM Gateway with the returned governed context
```

因此本 Goal 的优先级固定为：

1. OpenWorker/MCP wire、profile、broker、Runtime 和 canonical semantics；
2. MCP 会话复用、context 注入、token/latency 和故障恢复；
3. Python Client 作为 MCP server 与可信 host integration 的内部 SDK；
4. LangGraph、AutoGen、Generic direct-client 仅作可移植性/回归 smoke，不与 OpenWorker 主链同权，也不阻断
   `OPENWORKER_MCP_READY`。

强制边界：

- 普通 OpenWorker 只获得 `reader-lite` UDS capability；
- host-only context preparation 不进入模型可见 tool catalog；
- 写入必须经显式 handoff 到独立 submitter profile；operator profile 不提供给普通 Agent；
- OpenWorker 不直接调用 Runtime HTTP、repository 或 canonical procedure，所有 memory operation 经 MCP；
- `milai-client` 可以被 `milai-mcp` 内部使用，但不能成为 OpenWorker 绕过 MCP 的旁路；
- UDS socket 本身是 authorization capability，必须 profile-specific、可撤销、有并发/速率/消息大小/超时上限；
- OpenWorker root 仅指受限 Worker 容器内 root，不等于 host、broker、Runtime 或数据库 authority。

后续 benchmark 中的 MiLAi 主方法也必须复用这条 OpenWorker/MCP 产品路径。直接 Client/API 路径可以作为
诊断分解或下界对照，但不得替代正式 MiLAi arm。

本定位不重开已经完成的 `CORE00` 资产枚举和 owner 分类；它是 `CORE01/CORE02` 的新增主路径验收约束。
若整理矩阵中的宽泛 “public client/MCP” 表述可被实现为 OpenWorker 直连 Runtime，则以本节为准并在
`CORE01` 实现中收紧为 MCP-only memory transport。

---

# 2. 当前起点与已知问题

## 2.1 冻结候选

```text
candidate_id
= 712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51

candidate_inventory_sha256
= b754b9cfed729192b02c9493c5cb3ff93a7961c72f440e5ddb358ef7785055bb
```

该 candidate 是后续所有等价性对照和回滚 arm。DG-12 不原地修改其 wheel 或 inventory。

## 2.2 功能状态

已经成立：

```text
F0 MCP native       10/10 PASS
F1 Agent             5/5 PASS
T2                  24/24 PASS
Hardened S1–S10           PASS
Paired Agent tasks  20/20 PASS
Hidden answer calls       0
```

仍保留的发布边界：

```text
Runtime CANDIDATE
Schema EXPERIMENTAL / NO-GO FOR FREEZE
no dynamic-tool profile claim
no external-provider billing claim
no real-private-data approval
```

## 2.3 质量状态

DG11 v1 sealed holdout 的主要事实：

```text
DG11 F1                         0.283122
DG10 F1                         0.268533
DG11 - DG10                     +0.014589
bootstrap lower 95%             -0.024459
DG11 - fixed custom RAG         +0.074444
quality status                  QUALITY_TARGET_NOT_MET
```

Combined DEV 的较大收益没有泛化；多会话、single-user、assistant list、数值/单位、角色继承和 temporal
route 仍是需要通过公开实验解释的失败类别。DG-12 不重新运行已消费 holdout，也不把后续定向修复当作其
替代证据。

## 2.4 Paper smoke 状态

当前正式 paper evaluation 尚未开始，但已有以下无标签 smoke/reference：

| 工作 | 当前证据 | 解释 |
| --- | --- | --- |
| PE01 adapter/harness | 最新 smoke `PASS` | 只证明合同可运行 |
| PE02 controlled baselines | smoke `PASS` | 不等于正式 baseline 结果 |
| PE03 external feasibility | `PASS` | inclusion/exclusion 仍须在 protocol v2 冻结 |
| PE04 LongMemEval | answer/MiLAi smoke `PASS` | paper split 未正式生成答案 |
| PE05 Memora | all-method smoke `PASS` | formal 60-question run 未开始 |
| PE06 LongMemEval-V2 | MiLAi/RAG/controller smoke `PASS` | official small 未开始 |
| PE07 BEAM | smoke/resource estimate `PASS_WITH_LIGHT_EXCLUDED` | 128K formal 未开始 |
| PE08 Horizon/CUPID | context smoke `PASS` | 正式 answer/judge 调用为 0 |
| PE09～12 | `NOT_STARTED` | 消融、统计与最终包未执行 |

## 2.5 EH02 最新效率事实

当前权威性能结果来自同一冻结 10-case Horizon slice：

| 路径 | case | session / turn | wall | 解释 |
| --- | ---: | ---: | ---: | --- |
| DG11 frozen reference-faithful | 10 | 943 / 24,383 | `1344.500 s` | 历史完整部署/构建参考 |
| PD01 persistent product first phase | 10 | 943 / 24,383 | `912.494 s` | 同一产品 deployment 内逐 workload 首次构建与查询 |
| PD01 persistent product total | 10 | 943 / 24,383 | `918.847 s` | 含一次 `5.410 s` startup |
| 其中 governed history build | 10 | 943 / 24,383 | `842.921 s` | first phase 的 `92.376%` |
| 其中首次 outer retrieval | 10 | — | `64.575 s` | build 之外的读取成本 |
| same-lease immutable reuse | 10 | already built | `67.852 s` | `build_calls=0`；只允许作为 evaluation amortization |

当前 `embed_many(batch_size=32)` 已通过真实 ONNX tensor batch：90 logical items 从 `1.916 s` 降至
`1.048 s`，`1.828x`，scalar/batch vector byte difference 为 0。它证明 batch embedding 有效，但没有证明
整个 cold build 已批量化。

速度口径必须显式写出分母：

```text
reference-faithful / immutable reuse = 1344.500 / 67.852 = 19.815x
PD01 first phase / immutable reuse    =  912.494 / 67.852 = 13.448x
build component / reuse whole phase  =  842.921 / 67.852 = 12.423  # 不称 E2E speedup
```

Horizon 正式 120 case 包含 11,822 session、314,080 turn，当前估计约 622,905 logical embedding items。
`logical items`、`unique items`、`inference batches` 和 `provider calls` 必须分别报告；batch 后不得继续把
logical fragment 数写成底层 inference invocation 数。Answer/judge 调用在上述 profiling 中仍为 0。

## 2.6 历史构建根因：Governed History Materialization Lifecycle

当前首要瓶颈定义为：

> **相同或新的大规模 history 必须经历 governed ingest → canonical commit → fragment derivation → embedding →
> projection write/index → watermark ready；evaluation 的 fresh resource、跨 arm 和跨 run 生命周期会进一步放大
> 这项成本。**

必须区分：

```text
Evaluation rematerialization
  = 相同 workload 因 fresh DB / process / arm 被重复构建

Product cold materialization throughput
  = 真正新增、恢复、迁移或重建 canonical content 的首次物化能力

Product online Agent latency
  = NONE/CACHE/L0/L1 route mix × per-route OpenWorker MCP latency

Product deep recovery latency
  = canonical/projection 已 ready 后真实进入 L1 的 query
```

当前 same-lease exact fingerprint reuse 已实现，但 receipt 仍是进程内状态。以下状态不得混写：

```text
same live lease exact reuse          = PASS
process-restart reuse                = NOT_IMPLEMENTED
fresh-database projection restore    = NOT_IMPLEMENTED
cross-arm/cross-run durable reuse    = NOT_IMPLEMENTED
partial-content CAS reuse            = NOT_IMPLEMENTED
```

十个首次 workload 是十个不同 history。现有结果证明“去掉 build 会显著提速”，但尚未证明正式矩阵中的大部分
fragment 是重复内容。开始 CAS/segment 前必须统计 within-history、within-arm、cross-arm 和 cross-run 的
normalized fragment digest 重复率。

## 2.7 Cold build 内部仍未完成的归因

`842.921 s` 目前至少混合：

```text
943 × Evidence capture
943 × Proposal create
943 × Steward review
fragment derivation
batch embedding
per-fragment FTS/vector projection write
index maintenance
Outbox lease/drain/watermark wait
```

现有 Evaluation Harness 对每个 session 顺序执行 `Evidence → Proposal → Review`。Runtime 虽已按 event 调用
`embed_many()`，但 `ProjectionRepository.apply_window_search()` 仍在一个 transaction 中逐 fragment 调用
`apply_window_search_projection`；这不是 set-based batch projection write。因 build receipt 没有暴露同一
workload 的治理、推理、写入和索引非重叠分项，当前不得宣称 embedding 或 projection write 是唯一主因。

10 个 case 上 `build_elapsed_ms` 与 history item 数的描述性相关约为 `R²=0.99`，平均约
`35.3 ms/history item`。该结果只说明 build 随 workload 规模增长；单次 aggregate run、case/order/host 状态
和 session/fragment/text bytes 共线使其不能成为论文因果结论。

## 2.8 在线首要根因：Fast Path Reachability

DG-12 对在线性能采用以下正式判断：

> **不是 L1 本身绝对太慢，而是已有 `NONE / CACHE / L0` 能力没有在
> `OpenWorker → MCP → Runtime` 主链形成稳定、可寻址、可复用且可观测的快路径。**

MiLAi 已有 `EffectiveClaimState`、L0 exact/current、host deterministic router 和 snapshot/issue-revision cache
validation；本工作包不得以性能名义创建第二套 Current State 数据库或新的 canonical projection。当前实现缺口是：

```text
OpenWorker adapter:
  active_goal 由当前 question 派生
  → 普通 follow-up 容易被误判成新 task
  → MemorySlot/goal continuity 很难跨轮复用

Host Router:
  可产生 NONE/CACHE/L0/L1
  → 当前主链主要只对 NONE 生效
  → L0/L1 decision 未成为 composite Runtime 的强执行合同

Evaluation writer:
  subject=session_id
  predicate=memory.session
  claim_type=SESSION_MEMORY
  → 形成 governed session archive
  → 不等价于可按 project/subject/predicate 直接读取的 current state
```

因此在线快路径受两个独立量控制：

```text
StateAddressability
  = write side 是否形成可直接寻址的 current-state Claim

FastPathExecutionCoverage
  = host 是否把可快读的 Need 真正执行为 NONE/CACHE/L0
```

对 memory-dependent current-state turn，L0 命中必须使用条件链而不是互相独立的无条件概率乘积：

```text
P(L0Hit)
= P(NeedResolved)
× P(StateKeyResolved | NeedResolved)
× P(RouteValidatedAndPropagated | NeedResolved, StateKeyResolved)
× P(StateAvailable | NeedResolved, StateKeyResolved, RouteValidatedAndPropagated)
```

全体 Agent turn 的快路径资格与成功定义为：

```text
FastEligible
= NoMemoryNeed
  OR CacheReusable
  OR CurrentStateKeyResolved

FastSuccess
= FastEligible
  AND terminal_route IN {NONE, CACHE, L0}
  AND canonical/safety semantics preserved
```

这一定义只用于分解因果和计算覆盖率；不得通过删除难例、错误复用 CACHE 或把 L1 静默记作 L0 提高数字。

截至 `2026-08-24 21:34:45 +08:00`，FP0 已由
`var/dg12/runs/dg12-pd02-fp0-route-shadow-20260824-004/terminal.json` 正式终结：

| FP0 指标 | 结果 | 解释 |
| --- | ---: | --- |
| `StateAddressabilityRate` | `0.916667` | 11/12 current-state need 已有正确 canonical key；当前首要问题不是缺 key |
| `FastEligibilityRate` | `0.900000` | 18/20 turn 独立标注为可走快路径 |
| `FastPathExecutionCoverage` | `0.055556` | 只有 1/18 个 eligible turn 被正确执行为快路径；主因是 reachability/propagation |
| `RouteExecutionFidelity` | `1.000000` | 已请求的 route 被如实执行；不代表 requested route 本身足够聪明或够快 |
| `ACTION_SAFE_false_fast` | `1` | baseline 的预期安全失败；任何 retained candidate 必须降为 0 |
| query embedding / vector / reranker calls | `2 / 2 / 2` | 仅为 20-turn shadow baseline 调用计数，不是正式质量实验 |

因此当前证据更支持：

```text
high StateAddressability + very low FastPathExecutionCoverage
→ 先修 Host task continuity 与 route propagation
→ 暂不把 write-side Identification/Derivation 或复杂 retrieval 优化升级为 P0
```

FP1 后续已由
`var/dg12/runs/dg12-pd02-fp1-task-binding-20260824-005/terminal.json` 正式终结为
`PASS_FP1_DETERMINISTIC_TASK_BINDING`。早期 `001～003` 仍只保留为失败/诊断历史，不自动升级为正式证据；FP1
PASS 只覆盖 deterministic task binding correctness，不覆盖 L0 命中率、整体 quality non-inferiority 或产品 speed。
PD02 最终状态由 `var/dg12/performance/optimization-terminal.json` 裁决为 `TERMINAL_TARGET_MISS`。

## 2.9 已测 L1/Warm Deep Path 热点

完全复用 history 后，10 个 outer retrieval 仍需 `63.097 s`，平均 `6.310 s/case`；内部
`query_total_ms` 合计 `51.590 s`：

| warm internal stage | 10-case 合计 | internal query 占比 | 当前判断 |
| --- | ---: | ---: | --- |
| `recent_canonical_ms` | `23.152 s` | `44.9%` | 第一 SQL 热点；仅 7 case 启用，启用时均值约 `3.307 s` |
| `reranker_ms` | `18.011 s` | `34.9%` | 固定候选规模下的 CPU 热点 |
| `fts_ms` | `9.352 s` | `18.1%` | 随 scope/history 增长 |
| `vector_ms` | `0.444 s` | `0.9%` | 当前不是主要性能瓶颈 |
| `query_embedding_ms` | `0.299 s` | `0.6%` | 当前不是主要性能瓶颈 |

outer retrieval 与 internal query 尚有约 `11.507 s` 差值，必须作为 MCP/adapter/wrapper 未分解开销继续计时，
不能直接归因给网络或模型。

这些数字测量的是当前 L1-heavy Horizon 路径，不能推断真实 OpenWorker workload 的所有 turn 都必须承担同样
成本。正式产品必须先报告 NONE/CACHE/L0/L1 实际分布，再解释每档 latency。因此存在三条不同优化目标：

```text
formal benchmark throughput → cold governed materialization
real OpenWorker Agent latency → fast-path reachability × per-route latency
deep recovery latency        → recent_canonical + reranker + FTS + outer overhead
```

不得用 cold build 的巨大占比掩盖 warm MCP 仍为多秒，也不得用小 synthetic E2E 的 `64–241 ms` 代表 Horizon
规模的在线延迟。

## 2.10 代码归属整改与当前证据边界

`BHE00` 的旧 profile 和 `BHE01` 的 product-boundary failure 保留为历史依据；`CORE00～CORE02`、`PD00～01`
与 `EH00～03` 已完成本体 owner、semantic identity、OpenWorker/MCP 主链、batch embedding、长生命周期和薄
harness 整理。当前继续保持：

```text
one product behavior → one product owner → one public contract → one test owner
one benchmark peculiarity → one eval adapter/scorer/config
frozen historical evidence → immutable and inactive
```

EH02 性能数据只有每个正式 arm 一次 aggregate execution，没有 repeated-run interval。当前结论属于
`EVIDENCE_BOUNDED engineering characterization`；DG12-PD02 必须使用 matched repeated blocks 和 payload-free
stage deltas，才能决定 KEEP/REVERT/PARK，不得从一个总时长直接跳到完整 projection paging 架构。

---

# 3. Goal 范围、非目标与允许声明

## 3.1 必须完成

1. 冻结本体、integration、evaluation、dataset adapter 的依赖方向和代码所有权；
2. 清理 Goal/benchmark 名称驱动的产品 identity，并保留受控 legacy read compatibility；
3. 在本体实现通用 stage observability、batch embedding、长生命周期 Runtime/MCP/broker 能力，并如实区分
   已完成的 tensor batch 与尚未完成的 set-based projection write；
4. 若需要 bulk ingest，只通过正式 Evidence→Proposal→Decision 语义实现可复用应用服务；
5. 每项本体能力优先通过 OpenWorker/MCP 使用场景、真实 PostgreSQL、clean wheel install 和 non-repo cwd；
6. MiLAi 正式实验 arm 只通过 OpenWorker/MCP public product path 使用这些能力，不导入 Runtime 私有函数、
   不直连 Runtime HTTP，也不复制业务逻辑；
7. 建立跨 benchmark 复用的薄 Evaluation Harness，dataset-specific 文件只做 schema mapping/scoring；
8. 完成全阶段计时、调用核算、同 history reuse 和公平性能 A/B；
9. 建立 host-owned、execution-aware 的 deterministic Task Binding：分离 TaskIdentity 与 TaskMemoryBinding，维护
   Registry/Graph、generation、invocation-time tool-result binding 和独立的 MemoryNeed/StateKey/route trace；
10. 将 `NONE/CACHE/L0/L1` 从 Host 决策贯通到 MCP/Runtime 实际执行，禁止静默路线替换；
11. 以现有 `ClaimHead + EffectiveClaimState + live OpenIssue` 实现 `CurrentStateReadService`，不得建立第二真相源；
12. 用结构化 Need/Coverage 与 broker-bound Runtime validation proof 验证 CACHE，错误或不可判断时 fail closed；
13. 在连续 OpenWorker workload 上分开测量 StateAddressability、FastEligibility、FastPathExecutionCoverage、
    Route Execution Fidelity、per-route latency 与 expensive-memory rate；
14. 只有 FP1～FP4 纵向快路径闭环后，才对未被其覆盖的 L1 执行 FTS→vector→reranker progressive escalation；
15. 在正式 benchmark 前完成 governed ingest、projection drain、embedding、write/index、watermark 与 deep query
   的非重叠归因，解释至少 95% wall time；
16. 用 strongest-simple-replacement 顺序裁决 batch write、governed ingest pipeline、CAS、projection image、
    stable+delta 与 lazy materialization，禁止一次性实现全部机制；
17. 分开关闭 online fast-path reachability、deep recovery latency 与 cold materialization throughput；
18. 若 product bytes 改变，重新完成产品 E2E、reference equivalence、safety、rollback 和唯一 harness refreeze；
19. 冻结唯一 paper protocol v2、claim matrix、method configs 与 thresholds；
20. 建立 observation → rival hypothesis → discriminating experiment → novelty candidate 的发现闭环；
21. 运行预注册 baseline、外部方法、benchmark 和消融；
22. 同时分析质量、治理正确性、token、调用、延迟、吞吐、存储；
23. 将方法创新、系统创新和经验发现分开裁决，并形成 KEEP/REVERT/REDESIGN/PARK 决定；
24. 只生成一次最终结果包，必要时只做一次独立 AI review；
25. 在不引入新 canonical backend 的前提下，吸收 OpenViking 的 address-first、progressive content load、
    server-side context assembly、cross-turn exposure dedup 与 async derived processing 访问模式；
26. 将 OpenViking 作为隔离 Native/Systems baseline 做 `URI direct / find / context-search` 三档比较，或在正式
    score 打开前给出预冻结技术排除；不得把其接入产品写链或借其结果替代 MiLAi governance 实验。

## 3.2 非目标

- 不重做 DG10/DG11 历史审计；
- 不引入新的生产 canonical memory backend；
- 不把 Mem0/Hindsight/Graphiti/ReMe 变成 MiLAi 正式写者；
- 不把 OpenViking 变成 MiLAi 生产 backend、canonical store、authority source 或 Runtime 依赖；
- 不做公网、多 tenant、真实私人数据或 Schema freeze；
- 不为论文分数削弱 Scope、OpenIssue、revoke、authority 或 Canonical Gate；
- 不在正式 test 后修改同一候选并重跑；
- 不以 same-vLLM judge 单独决定质量；
- 不宣称所有 benchmark `SOTA`；
- 不把 BFCL 称为 MCP transport/protocol benchmark。
- 不在 `runtime/` 或 `integrations/` 新增 `dg10_*`、`dg11_*`、`dg12_*`、benchmark 名称或 paper-work-package
  命名的模块、类、配置开关和默认 identity；
- 不把 benchmark database reset、label visibility、scorer、case schedule 或 frozen wheel path 做成产品 API；
- 不创建异步 authoritative CurrentState store、current-state vector truth 或由 Host hint 决定 canonical 状态；
- 不把 `active_goal_summary`、`canonical_position_seen`、known claim/state/issue hint 当作 Runtime authority；
- 不用 embedding similarity 代替 CACHE 的确定性 `NeedCovered` 判定；
- 不把“内容已经发送过”的 `ExposureLedger` 当成 Need 已覆盖、CACHE 合法或 canonical truth；
- 不把 OpenViking 的 Abstract/Overview/Detail 内容层级与 MiLAi 的 L0/L1/L2 求知复杂度层级混为一谈；
- 不把 Horizon/session archive 的低 L0 覆盖率直接外推为真实 OpenWorker writer 的产品缺陷；
- 不在 FP1 或当前 DG-12 candidate 中训练、微调、蒸馏或部署 LightGBM、XGBoost、Qwen3-4B、35B 或其他
  learned Task Resolver；
- 不训练或微调当前 DG-12 的 answer、router、retriever、reranker、compiler、value estimator 或其他 MiLAi
  control model；允许使用冻结 pretrained dependency/native baseline，但必须核算其调用且不得改变其权重；
- 不让 Task Resolver 调用 LLM、embedding、semantic retrieval 或利用 retrieval result 建立/升级 task identity；
- 不在端到端 benchmark terminal 前创建 task-relation training dataset、feature pipeline、checkpoint、model registry
  或 goal-specific trainer；deterministic trace 只作为运行证据，不自动转为训练授权；
- 不在 `scripts/` 继续增加“一次 run 一个 Python 文件”的执行链；新入口必须是已有 package 的稳定 CLI
  subcommand 或 data-driven config。

## 3.3 分级允许声明

| 状态 | 允许声明 |
| --- | --- |
| `FUNCTIONAL_BASELINE_INHERITED` | DG11 frozen candidate 可作为 governed Memory MCP 使用 |
| `CORE_INVENTORY_COMPLETE` | 既有代码、symbol、entrypoint、owner 与迁移处置已完整冻结 |
| `CORE_NORMALIZED` | 既有通用能力已进入唯一产品 owner，重复活跃实现和跨层私有依赖已消除 |
| `CORE_BASELINE_E2E_PASS` | 整理后的产品 wheels 已通过无 benchmark 的 OpenWorker/MCP 主路径纵向验证 |
| `PRODUCT_DEVELOPMENT_TERMINAL` | 通用效率候选均 KEEP/REVERT/SKIP，retained set 已通过产品 E2E |
| `FAST_HARNESS_EQUIVALENT` | 快速 Evaluation Plane 与 faithful 输出等价 |
| `DETERMINISTIC_TASK_BINDING_PASS` | 仅说明 FP1 Host binding/Registry/generation/delayed-result hard gates 通过；不说明 Route、CACHE、E2E 或 learned model 已完成 |
| `ONLINE_FAST_PATH_TERMINAL` | task continuity、route fidelity、CurrentStateRead、CACHE coverage 和连续 workload 已完成或明确 terminal miss |
| `BATCH_RUNTIME_EQUIVALENT` | 新 batch Runtime 保持检索和治理语义等价 |
| `DEV_SIGNAL` | 仅说明 disjoint DEV 上出现可重复实验信号，不等于 paper claim |
| `SEARCH_BOUNDED_PAPER_CANDIDATE` | 候选已有机制实验和有边界 prior-work 检索，仍待 formal confirmation |
| `PAPER_PROTOCOL_FROZEN` | 正式实验协议、方法、阈值和输入已冻结 |
| `PAPER_RESULTS_COMPLETE` | 所有预注册结果与失败分母已报告 |
| `FORMAL_CONTRIBUTION_SUPPORTED` | 仅在冻结 scope 内支持对应 method/systems/finding claim |
| `QUALITY_ADVANTAGE_SUPPORTED` | 仅在对应 benchmark/track/statistic 达门时使用 |
| `QUALITY_NOT_PROVEN` | 实验完整但主要质量 claim 未成立 |

任何局部 `PASS` 都不能自动升级为 Production、Schema Frozen、External Provider Verified 或 SOTA。

---

# 4. 执行纪律：代码和实验优先

## 4.1 汇报顺序

每次进度首先回答：

```text
新增了什么真实代码能力？
验证了哪条动态纵向路径？
性能/质量/正确性结果是什么？
还剩哪个真实阻断？
```

hash、inventory、receipt 只在身份冻结或最终交付时报告，不作为日常进度主体。

## 4.2 审计预算

```text
development AI reviews          = 0
intermediate AI rereviews        = 0
final independent AI reviews    <= 1
final review input tokens        <= 120,000
failure-derived review versions = 0
```

安全边界冲突、规范歧义和最终验收可以触发一次必要审查；普通性能失败通过 profiler、测试和 A/B 解决。

## 4.3 尝试预算

一个工程假设最多执行三次有实质差异的动态尝试：

```text
attempt 1 → measure
attempt 2 → repair identified cause
attempt 3 → bounded alternative
```

三次仍无收益则 `REVERT` 或 `PARK`，记录一次 terminal；不为失败继续创建 candidate.1、candidate.2、receipt、
supersession 和多层审计链。

## 4.4 单一状态机

所有开发状态写入 `var/dg12/current-state.json`。同一工作包不再以多个 Markdown 文件表示状态；动态原始结果
进入一个 run directory 和 append-only ledger。

## 4.5 Skill 使用边界

Skill 是执行方法库，不是新的状态机、依赖层、scorer、reviewer 或 authority。适用规则：

1. 只有工作包满足 §9A 的 trigger 时才使用对应 Skill；不得为了“再看一遍”重复调用；
2. 本 Goal 的单一状态与 artifact 规则优先于 Skill 的通用 timestamp、`MANIFEST.md` 或目录模板；
3. Skill 产物必须进入现有 `var/dg12/` 闭集，不创建 candidate/receipt/rereview 版本链；
4. 默认只使用本地、确定性脚本；不得自动启动子代理、外部 reviewer、外部 judge 或图像生成 API；
5. `hypothesis-generation` 只生成候选与区分实验，不能自动排名或宣布 winner；
6. `novelty-check` 只在有重复实验信号后运行一次有边界的文献检索，不能用“未搜到”直接宣布 novel；
7. 任一 Skill 不得读取 `.env`、真实私人数据或 raw secret，不得绕过 candidate/protocol freeze；
8. Skill 输出与代码冲突时，以实际动态结果和本 Goal 的冻结合同为准。

采用 Skill 造成的 instrumentation、配置或脚本变更必须列入对应 run 的 `changes.json`；实验完成后 KEEP、
REVERT 或并入正式实现，不能留下不明 profiling patch。

## 4.6 本体优先的强制开发顺序

任何新能力必须按下面的顺序交付：

```text
product use case independent of any benchmark
→ semantic domain/application contract
→ Runtime/MCP/OpenWorker host implementation
→ unit + real PostgreSQL + OpenWorker/MCP E2E
→ build wheel and clean non-repo install
→ thin evaluation adapter calls the installed public API
→ benchmark measures behavior
```

如果一个改动只能由 `evals/dg12`、某个 benchmark fixture 或 Goal 状态触发，它不是本体能力。处理方式只有：

```text
generalize into product core
or
keep as thin reusable evaluation adapter
or
delete/reject the prototype
```

不得让实验 prototype 先成为事实标准，再倒逼 Runtime 去兼容它。

---

# 4A. MiLAi 本体与实验层代码所有权

## 4A.1 允许的依赖方向

```text
milai.domain
    ↓
milai.application
    ↓
milai.persistence / milai.adapters / milai.workers / milai.operations
    ↓
milai_client / milai_mcp / framework integrations
    ↓
evals.harness public-product adapter
    ↓
dataset adapters / schedules / scorers / paper reports
```

强制规则：

- `runtime/` 和 `integrations/` 不得 import `evals`、`scripts`、`var` 或任何 benchmark package；
- generic evaluation harness 只能 import 已安装 wheel 的 public API，不能 import `_private` helper；
- dataset adapter 不得操作 canonical tables、Outbox、projection repository 或 Runtime process internals；
- `scripts/` 只能是稳定 CLI 的薄入口，不得成为 domain/application 逻辑所有者；
- `var/dg*` 只保存状态和结果，任何运行时能力不得读取它来决定产品语义。

## 4A.2 代码归属矩阵

| 能力 | 唯一允许的 owner | 实验层允许做什么 |
| --- | --- | --- |
| Evidence/Proposal/Decision/Claim/OpenIssue | `milai.domain` + `milai.application` | 构造合法 public request；不能复制状态机 |
| canonical/query/context preparation | `milai.application` | 调用 API/MCP，记录返回值 |
| repository/transaction/outbox/watermark | `milai.persistence` + `milai.workers` | 只观察公开 health/trace/metrics |
| embedding/reranker batch/warmup | `milai.adapters` + `milai.workers` | 提交通用 batch；记录 logical item/inference batch |
| Runtime start/ready/stop/adopt | `milai.operations` | 获取一个 Runtime lease；不能重写 supervisor |
| HTTP connection/lifecycle/cache validation | `milai_client` | 复用 client 实例并测量 |
| MCP session/profile/capability | `milai_mcp` / OpenWorker integration | initialize、tools/call、reconnect；不能造 benchmark MCP |
| TaskIdentity/Registry/relation/transition | OpenWorker host integration + typed client contract | 传递 deterministic binding/trace；不能用 retrieval、模型或 eval label 决定 identity |
| memory need / route request | OpenWorker host integration + typed client contract | 消费 binding 并传递 hint；不能宣称 canonical truth 或授权 CACHE |
| CurrentStateRead / route validation / slot validation | `milai.application` + `milai_client` typed boundary | 调用并记录结果；不能在 eval 重写 ECS、NeedCovered 或 fallback |
| stage metrics/usage | `milai.observability` + integration metrics | 加 run/case/method correlation metadata |
| history/question schema mapping | `evals/.../datasets` | 唯一允许的 dataset-specific mapping |
| method schedule/baseline/scorer | `evals.harness` / `evals.paper` | 冻结顺序、调用、计分和导出 |
| isolated DB/template/reset | `evals.harness` provisioner | 只管理明确标记的临时 evaluation resource，不成为产品删除 API |

## 4A.3 本体公共能力候选

DG-12 当前只允许从 profile 需求中提炼以下通用产品能力；名称可在 `CORE00` 收敛，但语义不得包含 Goal 或
benchmark：

```text
StageMetrics / OperationTimer
EmbeddingProvider.embed_many()
ProjectionBatchProcessor
GovernedIngestBatchService
LocalRuntimeSupervisor ready/warm/adopt lifecycle
persistent MilaiClient / AsyncMilaiClient connection lifecycle
persistent MCP session with bounded reconnect
semantic RepresentationPolicy / CompilerIdentity
host-owned TaskMemoryState transport contract
deterministic TaskRegistry / TaskRelationDecision / TaskBindingTransition / ExecutionBindingToken
MemoryNeedSignature / MemorySlotCoverage
CurrentStateReadService over ClaimHead + EffectiveClaimState
RecallExecutionTrace / validated route propagation
```

`BenchmarkRuntimeSlot`、`CohortRuntimeSlot`、CUPID/Horizon/Memora/BEAM loader 不属于产品对象。实验层如需资源
租约，只能定义极薄的 `EvaluationRuntimeLease`：基础设施启停调用 `LocalRuntimeSupervisor`，MiLAi memory
method 调用必须走 OpenWorker/MCP；Client 只允许作为 MCP 内部 transport 或显式诊断对照。

## 4A.4 产品通用性验收

每个新本体能力必须同时通过：

1. 文档能用不含 `DG-*` 和 benchmark 名称的一句话说明真实用户价值；
2. 类型、配置、identity 和错误码使用 semantic naming；
3. 至少一个 OpenWorker/MCP 示例在没有 `evals/`、`scripts/`、`var/dg*` 时可运行；
4. Runtime exact-role PostgreSQL 测试覆盖正常、retry、partial failure 和 rollback；
5. Scope、authority、OpenIssue、revoke、idempotency、order 和 watermark 不变；
6. 能从 wheel fresh install，在 `/tmp` 等 non-repo cwd 使用；
7. evaluation adapter 只消费 public API，删除 adapter 不影响产品能力；
8. 配置默认值不以论文 split、case count 或 benchmark 资源预算决定。

任何一项不满足，都不能写 `CORE_NORMALIZED` 或 `CORE_BASELINE_E2E_PASS`。

## 4A.5 Goal 命名债务迁移

不得直接改动参与持久 hash/identity 的旧字符串。`CORE01` 必须冻结：

```text
legacy identity → semantic identity compatibility table
read old / write new rule
cache and projection invalidation rule
mixed-version detection
rollback behavior
deprecation window
```

新写入只能使用 semantic version，例如 `grouped-compact/v3`、`turn-window/v1`、`signed-projection/v2`；旧
`DG10_*`/`DG11_*` 只作为显式 legacy alias 读取，不再控制新默认行为。

---

# 4B. 既有代码整理、本体化迁移与规范结构

## 4B.1 整理先于新增能力

`DG12-CORE00～CORE02` 是所有后续开发和实验的硬前置门。整理范围不是只看 DG12 新文件，而是检查当前
活跃 import graph、package entrypoint、配置默认值和测试 owner，覆盖：

```text
runtime/src/milai/**
integrations/*/src/**
evals/benchmark/**
evals/agent_efficiency/**
evals/paper/runners/**
evals/dg12/**
scripts/**
runtime/tests/**
integrations/*/tests/**
tests/**
```

每个源文件和具有产品语义的主要 symbol 必须被归为且只归为一类：

```text
KEEP_PRODUCT
MOVE_TO_PRODUCT
SPLIT_PRODUCT_AND_EVAL
KEEP_EVAL_GENERIC
KEEP_EVAL_DATASET_SPECIFIC
FROZEN_LEGACY_REFERENCE
DELETE_AFTER_DEPENDENCY_CHECK
```

不能使用 `KEEP_FOR_DG12`、`MAYBE_USEFUL`、`TEMPORARY` 作为最终分类。整理矩阵直接维护在一个
`core-refactor-matrix.json` 中，不为每次移动生成 candidate、receipt 或 review 文档。

## 4B.2 规范化目标结构

沿用现有包，不新造与 MiLAi 并列的“实验产品包”。目标结构如下；具体文件可在重构中合并，但 owner 和
依赖方向不能改变：

```text
runtime/src/milai/
├─ domain/          # 纯对象、值类型、不变量；不访问网络/数据库/evals
├─ application/     # use case、canonical/query/context service、批处理语义
├─ persistence/     # repository、transaction、outbox、watermark
├─ adapters/        # Runtime server-side blob/embedding/reranker adapter
├─ workers/         # projection/outbox/background execution
├─ operations/      # install/migrate/start/ready/warm/drain/stop/doctor
├─ observability/   # payload-free metrics、stage timing、usage correlation
├─ api/             # HTTP transport only
└─ config/          # semantic product settings

integrations/python-client/src/milai_client/
├─ contracts/models
├─ sync/async transport
├─ Agent lifecycle/task memory
├─ context compilation/cache policy
└─ token/usage accounting

integrations/mcp/src/milai_mcp/
├─ profile-scoped server
└─ stable MCP contracts

integrations/openworker-mcp/src/milai_openworker_mcp/
├─ host policy/controller
├─ UDS transport/broker/relay
├─ provider execution boundary
└─ explicit write handoff

evals/
├─ harness/         # 通用 workload、lease、method adapter、run accounting
├─ datasets/        # CUPID/Horizon/BEAM/Memora/LongMemEval schema mapping
├─ adapters/        # MiLAi 与外部 baseline 的薄适配
├─ scorers/         # deterministic/judge protocol
├─ protocols/       # split、schedule、threshold、method config
└─ legacy/          # 仅限可移动且未被 frozen identity 锁定的历史参考
```

包依赖必须收敛为：

```text
milai-runtime                         # 不依赖 integrations/evals
milai-client                          # MCP 内部 SDK；不依赖 milai-runtime/evals
milai-mcp         → milai-client
openworker-mcp    → public MCP wire/contracts; no Runtime HTTP bypass
framework adapters → milai-client    # secondary portability only
evals main MiLAi arm → OpenWorker/MCP clean-installed product path
```

`milai-openworker-mcp` 不得继续 import `milai.adapters.*`，也不得以 `milai-client` 直接发 Runtime HTTP 请求
绕过 MCP。若共享类型确属 MCP 公共合同，放入 `milai-mcp` public contract；若只服务 OpenWorker，归
OpenWorker package 自己所有。`milai-client` 保持 MCP server 的内部 Runtime transport SDK。

## 4B.3 初始迁移矩阵

下表是 `CORE00` 的强制起点，不是最终实现通过声明：

| 当前资产 | 已确认内容 | 目标处置 |
| --- | --- | --- |
| `runtime/src/milai/{domain,application,persistence}` | canonical 与 retrieval 主体 | `KEEP_PRODUCT`；禁止 Goal/eval 依赖 |
| `runtime/src/milai/adapters/agent_prefetch.py` | Agent context compiler、grouped compact、turn window | `MOVE/SPLIT` 到 `milai-client` 的语义 context policy；Runtime 不保留只供 OpenWorker 调用的 adapter |
| `runtime/src/milai/adapters/mcp_unix.py` | OpenWorker UDS MCP client | 移入 OpenWorker/MCP public transport owner |
| `runtime/src/milai/adapters/provider_execution.py` | Host provider execution boundary | 移入 OpenWorker integration；不属于 memory Runtime |
| `runtime/src/milai/adapters/embedding.py` | embedding/projection identity | `KEEP_PRODUCT`；增加 semantic identity，后续 batch API 仍由 Runtime owner |
| `runtime/src/milai/adapters/reranker.py` | 产品 reranker | `KEEP_PRODUCT`；实验 scorer/judge 不得混入 |
| `runtime/src/milai/workers/main.py` | Outbox/projection worker | `KEEP_PRODUCT`；通用 batching 可拆分，但 CLI 只保留稳定入口 |
| `runtime/src/milai/operations/local_runtime.py` | 本地产品启停与迁移 | `KEEP_PRODUCT` 并收敛公共 lifecycle；不复制 DG12 Slot 状态机 |
| `runtime/src/milai/observability/logging.py` | 日志与脱敏 | `KEEP_PRODUCT`；通用 stage metrics 在同层扩展 |
| `integrations/python-client/.../optimization.py` | token、cache、context policy、usage | `KEEP/SPLIT_PRODUCT`；按语义职责拆分，移除 `dg11-*` 默认 identity |
| `integrations/openworker-mcp/.../adapter.py` | 首要 OpenWorker host integration | `KEEP_PRODUCT_INTEGRATION`；所有 memory call 经 MCP，消除 Runtime internals/HTTP bypass |
| `evals/dg12/runtime_slot.py` | lifecycle 与四 benchmark loader 混合 | `SPLIT`；workload DTO/loader 留 evals，产品 lifecycle 概念由 `milai.operations` 实现，文件最终退出活跃路径 |
| `evals/dg12/stage_profile.py` | monkey-patch profiler + StageRecorder | 旧 profile 保留；通用 timer/metrics 迁入 observability，monkey-patch 诊断不进入产品 |
| `evals/paper/runners/memora_milai_contexts.py::_CohortRuntime` | 建库、迁移、摄取、Worker、query | 产品生命周期改用公共 operations/client；Memora mapping/run/scoring 留 evals |
| `evals/benchmark/lme_product_smoke.py::_runtime_context` | LongMemEval 产品部署 helper | 替换为通用 eval lease + OpenWorker/MCP 产品路径；dataset/scoring 留 evals |
| `evals/benchmark/dg11_retrieval.py` | 研究算法、指标和 winner 混合 | 已进入产品的逻辑只保留一份产品实现；实验 variant/metric 留 evals，历史冻结行为显式标记 legacy |
| `evals/benchmark/dg11_measurement.py`、holdout/schedule | scorer、split、统计 | `KEEP_EVAL`；永不进入 Runtime |
| `evals/agent_efficiency/provider_ab.py` 等 | provider/sandbox/evidence runner | `KEEP_EVAL`；不得成为产品 Runtime 生命周期 |
| `scripts/*dg10*`、`scripts/*dg11*` | 大量历史 run/review/candidate builder | 先检查 frozen/source locks；锁定者原位只读，不锁定且无调用者者归档或删除；可复用逻辑并入单一 data-driven CLI |

## 4B.4 迁移方法：提取，不复制

每一项 `MOVE_TO_PRODUCT` 或 `SPLIT_PRODUCT_AND_EVAL` 必须按同一纵向顺序完成：

```text
1. characterize current accepted behavior with focused tests
2. define semantic public contract and target owner
3. implement once in the target product package
4. run old-vs-new equivalence where old behavior is valid
5. switch ordinary product/integration callers
6. switch eval adapter to the installed public API
7. remove active imports and duplicate implementation
8. archive/delete only after frozen-lock and reverse-dependency checks
```

禁止通过长期 compatibility wrapper 让两份实现继续演进。必要 shim 必须有唯一 owner、deprecation condition
和删除测试；它不能包含业务逻辑。

## 4B.5 历史文件与 frozen evidence

目录规范化不能破坏历史可复算性：

- 已进入 DG10/DG11 frozen manifest、review bundle 或 source lock 的文件保持 byte/path 不变；
- 它们从 active CLI、import graph、文档入口和默认配置退出，但不因“清理”而覆盖；
- 未锁定文件在删除前用 `rg`、import graph、entrypoint 和测试证明无调用者；
- 历史 migration（包括 `0028_dg11_window_projection`）不重命名，后续 semantic identity 通过新兼容合同处理；
- 新产品测试不得继续以 `test_dg11_*` 作为能力名称；历史精确回归测试可在 allowlist 中保留。

## 4B.6 本体整理完成门

`CORE_NORMALIZED` 只有同时满足以下条件才能成立：

1. 活跃代码和主要 symbol 100% 进入整理矩阵且无未决 owner；
2. product package 对 `evals/`、`scripts/`、`var/dg*` 和 benchmark package import 为 0；
3. OpenWorker integration 不 import Runtime 私有 module、不直连 Runtime HTTP；framework adapter 仅为次级 smoke；
4. 每个被采用的 context/retrieval/lifecycle 行为只有一个活跃实现；
5. 产品 public API、CLI、配置、错误码和新写 identity 使用 semantic naming；
6. 旧 identity 完成 read-old/write-new、mixed-version、cache/projection invalidation 和 rollback 测试；
7. 单元、真实 PostgreSQL、Client、MCP、OpenWorker 测试随 owner 迁移，不靠 eval fixture 才能通过；
8. clean wheels 从 non-repo cwd 完成无 benchmark 的 OpenWorker→MCP→Runtime E2E；
9. 临时移除 `evals/` 和非锁定历史 scripts 后，产品 build/test/E2E 仍通过；
10. BHE01、`_CohortRuntime` 和 `_runtime_context` 不再是活跃产品执行依赖。

未通过本门时只能继续整理本体，不能开始 `PD00`、`EH00`、`ND*` 或 `PE*`。

---

# 5. 三种 Benchmark 执行模式

## 5.1 Reference Faithful

```text
empty database
→ complete migrations
→ complete governed ingest
→ complete projections
→ MCP query
→ cleanup
```

用途：少量代表案例验证安装、迁移、治理、删除和完整 cold E2E。它不是正式批量 runner，也不是在线 p95。

## 5.2 Evaluation Fast

```text
BenchmarkCoordinator
→ at most two isolated Evaluation Runtime Leases
→ each lease adopts one installed long-lived product deployment
→ migrate/warm each deployment once
→ ingest one exact history once
→ run all questions for that history
→ release and recreate only the marked temporary resource
→ next history
```

用途：正式 context/quality 实验。Harness 不实现 Runtime；只复用产品 supervisor/client/MCP。进入 paper run 前
必须通过 §10 的等价性门。

## 5.3 Online Latency

```text
data ready
projection watermark ready
API/MCP/embedding/reranker warm
→ continuous OpenWorker turns
   ├─ NONE
   ├─ CACHE validation
   ├─ L0 CurrentStateRead
   └─ L1 progressive deep recovery
```

用途：Agent 实际使用 MiLAi 的 route mix、per-route p50/p95/p99 和 task-level E2E。不得混入 Migration、历史摄取
或恢复成本，也不得只运行 L1-heavy query 后把结果外推为全部 Agent turn。首次正式表必须同时报告：

```text
NONE/CACHE/L0/L1 rate
FTS-only/vector/reranker escalation rate
query embeddings per all turns
memory-control latency per route and overall
task success / false-fast / stale-cache rejection
```

## 5.4 成本分解

```text
T_run_total
= T_run_setup
 + Σ T_unique_history_ingest
 + Σ T_projection_build
 + Σ T_question_query
 + Σ T_answer
 + Σ T_judge
 + T_cleanup

T_amortized_per_question
= T_run_total / terminal_question_count

T_online_expected
= Σ_route P(terminal_route = route) × T_route

ExpensiveMemoryRate
= (VectorTurns + RerankerTurns) / AllAgentTurns
```

BM25、dense 和外部方法也必须将 index build 与 query 分开；不能用 BM25 in-memory warm query 对比 MiLAi
full cold deployment。

---

# 6. Product Runtime 与薄 Evaluation Lease

## 6.1 两个对象模型必须分开

产品对象：

```text
LocalRuntimeSupervisor
├─ PostgreSQL adoption/migration readiness
├─ API / Worker lifecycle
├─ embedding / reranker warmup readiness
├─ health / metrics / graceful drain
└─ stop without benchmark semantics

MilaiClient / AsyncMilaiClient
└─ persistent HTTP pool + bounded retry + request identity

MiLAi MCP Server/Session
└─ initialize + profile capability + tools/call + bounded reconnect

OpenWorker MCP Host Integration
├─ memory_mode + relay/UDS/broker + reader/submitter separation + vLLM handoff
├─ host-owned TaskMemoryState + turn query separation
└─ requested route / validated route / fallback propagation

CurrentStateReadService
└─ ClaimHead + EffectiveClaimState + live OpenIssue in one canonical snapshot
```

实验对象：

```text
BenchmarkCoordinator
├─ EvaluationRuntimeLease-0..N
├─ WorkloadPlanner
├─ DatasetAdapter
├─ MethodSchedule
├─ ResultSink
└─ temporary resource provisioner
```

`EvaluationRuntimeLease` 只组合产品启动能力、OpenWorker/MCP 调用和临时资源；不能拥有 retrieval、ingest、
projection、context compiler、MCP server 或 Runtime lifecycle 的替代实现。

## 6.2 生命周期分离

产品生命周期：

```text
STOPPED → STARTING → MIGRATING/ADOPTING → READY → DRAINING → STOPPED
                         └ failure → DEGRADED/FAILED
```

Evaluation resource 生命周期：

```text
ALLOCATED → CLEAN → WORKLOAD_BOUND → QUERYING → VERIFYING → RELEASED
    └ unverified failure → QUARANTINED → DESTROYED
```

dataset/cohort 名称只能出现在第二条状态机。产品 lifecycle 不得出现 `LOADING_COHORT`、benchmark loader kind
或 paper partition。

## 6.3 Process 与复用边界

```text
max evaluation leases       = 2
Runtime processes per lease = one configured product deployment
case-level shared mutation  = PROHIBITED
```

Runtime 持久化、client connection pool、MCP session、broker/relay 和 embedding/reranker warmup 都先作为产品
能力实现。实验只决定租用几个独立部署并记录 CPU affinity、OMP/ORT threads、DB pool、semaphore 和
service window；正式 MiLAi arm 仍从 OpenWorker/MCP 入口调用。

## 6.4 临时资源 reset 不进入产品 API

Evaluation provisioner 可以重建明确标记的临时数据库和 blob root，但必须：

1. 验证随机 evaluation DB 名、run marker 和临时 root；
2. 通过产品 graceful drain 停止新请求并等待在途调用；
3. 关闭 lease 后 drop/recreate 临时资源，不对一般 canonical database 暴露 bulk reset；
4. 验证连接、文件和进程均释放；失败则 quarantine/destroy；
5. 不使用 `runtime/.env` 的未验证目标执行 destructive reset。

产品对数据生命周期仍只提供既有 revoke/purge/deletion 语义；不能为了 benchmark 快速清空而增加绕过治理的
管理接口。

## 6.5 History fingerprint 只属于实验调度

Evaluation Harness 可以对 public/de-identified immutable workload 计算 exact fingerprint 以避免重复构建：

```text
SHA256(
  ordered source bytes
  + installed product identity
  + public ingest/config identity
  + embedding/projection identity
  + scope/authority profile
)
```

该 fingerprint 只决定“是否可复用一个已隔离的 evaluation artifact”，不得成为 canonical identity、产品
cache validator 或跳过 Evidence/Proposal/Decision 的依据。产品自己的 idempotency/cache identity 必须使用
正式 domain key。Prefix reuse 默认关闭，除非 as-of、future leakage 和逐字节前缀等价已证明。

## 6.6 持久连接与模型属于本体

- `LocalRuntimeSupervisor` 暴露 ready/warm 状态，不由 benchmark monkey-patch 私有启动函数；
- `MilaiClient`/`AsyncMilaiClient` 使用持久连接池、有界 timeout 和显式 close；
- MCP session 通过正式 integration initialize，一次连接执行多个 `tools/call`；
- OpenWorker task 间可复用受控 broker/MCP deployment，但每个 task 的 profile、Scope、memory_mode 和
  request identity 必须重新绑定；
- embedding 与 reranker 由 provider/worker 维护 lazy-load、warmup、并发和故障状态；
- reconnect 绑定原 request/idempotency identity，不增加隐藏业务调用；
- warmup 失败只能 degraded/fail closed，不能降低 authority 或 consistency gate。

---

# 7. Projection 与 Embedding 优化

## 7.1 当前事实与复杂度

对于未长文本分块的 `n` 个 turn：

```text
n turn fragments + (n - 1) adjacent windows = 2n - 1 embedding items
```

逻辑 embedding item 数和底层 inference invocation 数必须分别报告。当前状态为：

| 能力 | 状态 | 允许声明 |
| --- | --- | --- |
| `EmbeddingProvider.embed_many()` | `PASS` | 真实 tensor batch、byte-equivalent |
| event 内 exact text dedupe | `PASS` | 只限同一 event 的完全相同正文 |
| cross-event embedding CAS | `NOT_IMPLEMENTED` | 不得声明 cache reuse |
| set-based projection write | `NOT_IMPLEMENTED` | 当前仍逐 fragment SQL procedure |
| governed bulk ingest/pipeline | `NOT_IMPLEMENTED` | 当前每 session 顺序 Evidence/Proposal/Review |
| same-lease exact workload reuse | `PASS` | Evaluation amortization only |
| process/fresh-DB restore | `NOT_IMPLEMENTED` | 不得声明 persistent projection image |
| immutable segments / delta / compaction | `DESIGN_CANDIDATE` | 未经 PD02 不进入产品 |

`embed_many` 已把 inference invocation 从“近似 logical item 数”降为 bounded batches；当前首要未知已转为
governance round-trip、projection write/index 与 remaining embedding 的贡献，而不是继续假设 scalar embedding
仍是唯一瓶颈。

## 7.2 薄 Evaluation cache

只有本体 batch/warm lifecycle 已完成后，才允许在通用 `evals.harness` 建立独立身份的
content-addressed artifact cache：

```text
cache_key = HMAC_or_SHA256(
  privacy_domain
  + candidate_id
  + exact normalized fragment bytes
  + weights_digest
  + tokenizer_digest
  + pooling_strategy
  + normalization_policy
  + precision_and_dimensions
  + compiler_and_fragmenter_identity
  + projection_schema_version
)
```

约束：

- 只保存向量、identity、维度和 hash，不保存未脱敏正文；
- public/de-identified 与个人数据 namespace 分离；真实私有数据只能在同一 tenant/security/retention domain
  内 dedupe，优先使用 domain key HMAC，禁止裸 content digest 形成跨 tenant existence side channel；
- cold build、warm hit、batch 数、logical items 全量报告；
- 只能加速 context/quality generation；
- 不能作为 frozen Runtime 产品 latency/throughput 证据；
- 必须通过 projection、Top-K 和 Context 等价性；
- 不得实现第二套 embedding、projection writer、canonical gate 或 context compiler；
- cache 文件和 key 不得包含 `DG12` 或具体 benchmark 名称，dataset identity 作为数据字段传入。
- 用户删除、retention expiry 与 shared blob reference 必须分开记录；cache membership 永远 tenant/scope specific。

## 7.3 原生 Runtime batch

已完成部分与下一候选必须分开：

```text
EmbeddingProvider.embed_many(texts, batch_size)
→ exact fragment dedupe                     # PASS
→ batch ONNX inference                      # PASS

bounded ordered Outbox event set
→ derive fragments
→ embed_many / exact cache lookup
→ set-based batch projection write          # PD02 candidate
→ per-Outbox completion/watermark/error attribution
```

必须保持：

```text
same aggregate order
same idempotency
same dead-letter gap behavior
same projection version identity
same revoke/purge priority
same canonical candidate resolution
```

该能力属于 MiLAi Runtime product candidate，不属于“DG12 专用 Runtime”。不能覆盖 DG11 wheel；必须能被
普通 ingest、Agent/MCP 路径和任意合法 workload 使用。set-based writer 可以使用 array/unnest、staging table、
COPY 或等价 PostgreSQL 机制，但必须保持每个 Outbox event 的 identity、顺序、错误归因与 durable watermark。
若三次有实质差异的实现仍无法保持输出等价，则回滚；不得用 evaluation cache 假装产品 batch write 已成立。

## 7.4 Cold materialization 判别实验

在实现 CAS、snapshot 或 segment 前，必须先完成同一 installed product、同一 workload、matched repeated block
的阶段拆分：

| Cell | 合法执行 | 主要识别量 |
| --- | --- | --- |
| `M0 LIFECYCLE_ONLY` | ready/warm，无 history | 固定 deployment/host 成本 |
| `M1 GOVERNANCE_ONLY` | 完整 Evidence→Proposal→Decision，暂缓 projection worker | canonical governance 成本 |
| `M2 PROJECTION_DRAIN_REAL` | 对 M1 canonical state 启动真实 compiler/embedding/scalar writer 至 watermark | 当前 projection drain |
| `M3 PROJECTION_DRAIN_VECTOR_HIT` | 相同 fragments，预计算等价 vectors，保持当前 scalar writer | projection write/index 成本 |
| `M4 PROJECTION_DRAIN_BULK_WRITE` | 真实 embedding，set-based writer | batch write 的独立收益 |
| `M5 FRESH_DB_IMAGE_RESTORE` | fresh DB 恢复合法 canonical/projection artifact 后 attach/gate | projection image 的独立收益 |

上述 cell 只在 Evaluation Plane 控制 worker timing；任何 canonical state 都必须由正式治理路径创建或由正式
backup/restore 合同恢复。不得用直接 DML 构造更快的“产品 arm”。

M1 结束后必须从同一 canonical checkpoint 分别 clone/restore 出独立 M2、M3、M4 输入；不能先执行 M2 再在已
物化的同一数据库上运行 M3/M4。run order 使用冻结 counterbalance，host/service state 匹配，避免把 cache warm、
filesystem cache 或执行顺序误当机制收益。

每个 cell 至少输出：

```text
governance_capture/proposal/review ms
fragment derivation ms
embedding logical/unique items, batches, ms
projection write/index ms
outbox drain/watermark ms
database bytes and peak RSS
Top-K/context/safety equivalence
matched repetition interval
```

现有 reference、PD01 cold 和 same-lease reuse 作为 anchor，不当作上述内部阶段的独立 replicate。

与原五臂决策问题的对应关系固定为：

```text
A current fresh rebuild            = M0 + M1 + M2
B same-DB/same-lease reuse         = EH02 warm anchor
C fresh-DB projection image        = M5
D embedding CAS only               = M3 simulation → evidence-triggered product CAS
E cold batch, no reuse             = M4
```

M0 是额外 lifecycle calibration，不增加一个可宣称更优的方法 arm。这样既保留 A～E 的产品选择问题，又能在
A 内继续区分治理与 projection drain，避免再次只得到一个无法行动的总时长。

## 7.5 ProjectionMaterializationStore 设计候选

只有 `M0～M4` 证明 restore/reuse 仍是主要剩余成本，才允许实现通用产品候选：

> **Content-Addressed Immutable Projection Segments**，或 **Persistent Projection Image + Delta Overlay**。

产品结构必须保持：

```text
Canonical Core
→ deterministic Projection Compiler
→ content-addressed derived blobs
→ immutable stable segments + bounded delta segments
→ Projection Manifest
→ query merge / dedupe
→ Canonical Gate
→ Context Compiler
```

Projection 与 Manifest 只负责 candidate generation 和 coverage，不保存 canonical truth。Manifest 最少包含：

```yaml
privacy_domain:
scope_hash:
compiler_identity:
projection_schema_version:
embedding_identity:
fts_identity:
stable_segments: []
delta_segments: []
coverage_from:
coverage_through:
source_set_digest:
issue_revision_digest:
```

完整性条件使用 coverage frontier：

```text
Coverage(stable segments ∪ delta segments) >= required canonical position
AND no coverage gap
AND identities compatible
```

禁止要求 `manifest watermark == current watermark` 后整包失效；合法 stable+delta 可以共同覆盖当前位置。反之，
coverage gap、identity mismatch 或不可判断状态必须对 `CANONICAL_REQUIRED` fail closed。

## 7.6 Invalidation、OpenIssue 与 lazy fault

必须保持：

```text
lazy physical invalidation = MAY
lazy logical invalidation  = MUST NOT
```

Evidence revoke、permission/retention 失效或 GroundingBlock 必须同步对 Canonical Gate 可见；旧 segment/vector
物理存在时仍必须被拒绝，随后才异步 purge/compact。Projection 可以索引 OpenIssue 文本和 branch keyword，
但 `status/revision/discharge` 必须在 query 阶段由 canonical StateView 决定，Manifest 不得宣称 issue resolved。

Page 粒度不得等于单 fragment：

```text
fragment → content-addressed blob
hundreds/thousands of blobs → immutable segment
segments → manifest
```

若未来启用 lazy materialization，必须有 single-flight、bounded segment/page、bounded worker queue、timeout 和
background prefetch，并明确：

```text
FAULT_SYNC_SMALL
FAULT_ASYNC_WITH_CANONICAL_OR_FTS_FALLBACK
FAULT_UNAVAILABLE
```

大 segment miss 不得在 query thread 同步计算数千 embedding。Action-safe 请求不得因 page fault 静默降低
correctness。segment-local ANN 必须 per-segment overfetch + global rerank，并通过 exact/scoped recall 对照；未经
该门不得把多个 segment top-k 合并声称等价于 global ANN。

## 7.7 Strongest-simple-replacement 与停止条件

按以下顺序裁决，不允许并行一次性实现：

```text
same-lease / persistent evaluation reuse
→ set-based projection write
→ governed ingest pipeline/batch
→ privacy-domain embedding CAS
→ fresh-DB projection image restore
→ stable + delta + compaction
→ lazy materialization
```

选择规则：

- `M3` 接近 warm floor：优先 CAS + existing writer，不造 segment engine；
- `M4` 接近 warm floor：优先 batch write，不造 CAS/snapshot；
- 只有 `M5` 显著优于 M3/M4 且存在 restart/replica/migration/restore 产品 use case，才保留 projection image；
- 增量更新仍昂贵才引入 stable+delta；真实 page miss 成为 p95/p99 主因才引入 lazy fault；
- duplicate digest rate 低、restore benefit 小、存储/复杂度超过收益或三次有界尝试不获益时 `PARK`；
- 上述机制默认是 systems engineering，不作为算法 novelty；只有 governance-preserving minimal recomputation
  产生独立、可复算 separation 时才可进入 systems contribution 候选。

## 7.8 Window 表示消融

以下只作为实验，不直接成为默认产品：

```text
A  turn + adjacent-window vectors（current）
B  turn vectors + window FTS
C  turn vectors + deterministic adjacent-vector composition
D  turn-only retrieval
```

只有在公开 DEV 上同时满足质量、更新、OpenIssue、revoke 和效率门，才可形成后续 candidate；正式 paper
test 后不得再修改本 Goal 的 evaluated candidate。

---

# 7A. Online Fast Path Reachability

## 7A.1 正式读取原则与路由状态机

DG-12 将以下原则写成产品合同：

> **Current state is read; history is retrieved.**  
> **当前状态应直接读取，历史记忆才需要检索。**

正常在线链路必须是：

```text
OpenWorker user/tool event + persistent TaskMemoryState
→ deterministic TaskRelationDecision + validated TaskBindingTransition
→ TaskBindingContext
→ deterministic MemoryNeed resolution
→ route validation
   ├─ NONE  : 当前 turn 不需要 memory
   ├─ CACHE : Runtime 验证 slot token、policy 和 Need coverage 后复用
   ├─ L0    : CurrentStateReadService exact/current canonical read
   └─ L1    : history/semantic recovery with progressive escalation
→ Canonical Gate / compact Context
→ OpenWorker answer path
```

`NONE/CACHE/L0` 不是对 L1 的近似替代，而是具有不同前置条件的合法路径。L0 miss 不得被记录成 L0 hit；Runtime
可显式建议或执行 L1 fallback，但必须留痕。L2/DCEP 不承担“要不要搜 memory”的普通 routing 工作。

## 7A.2 Deterministic Execution-aware Task Binding

FP1 的正式问题定义为：

> **在不依赖 memory retrieval result 自证的前提下，由 OpenWorker Host 维护当前 turn、tool event 与持久 task 的
> execution relation，并输出可供后续 Need/Route 使用、但不能授权 CACHE 或 canonical truth 的 typed binding。**

FP1 只完成确定性基础能力。现有 `TaskMemoryState` 继续作为 Host→MCP public envelope，但在语义上拆成两个互不
反向依赖的部分，不再创建第三套 `TaskState` 或 Runtime canonical object。

### 7A.2.1 `TaskIdentityState` 与 `TaskMemoryBinding`

```yaml
TaskIdentityState:
  task_id:
  parent_task_id: null
  status: ACTIVE | SUSPENDED | COMPLETED
  task_generation:
  binding_generation:
  project_scope:
  profile_identity:
  active_goal_id:
  active_goal_version:
  active_goal_summary:
  execution_lane_id:
  plan_node_id: null
  unresolved_operation_ids: []
  workspace_ref: null
  artifact_refs: []
  created_epoch:
  last_active_epoch:

TaskMemoryBinding:
  task_id:
  known_claim_ids: []
  known_state_keys: []
  relevant_open_issue_ids: []
  canonical_position_seen:
  slot_id: null
  slot_validation_handle: null
  slot_coverage: null
```

依赖方向只能是：

```text
Host execution evidence
→ TaskIdentityState
→ TaskMemoryBinding
→ MemoryNeed / Retrieval / CACHE validation
```

禁止：

```text
RetrievalResult / retrieved Claim / model-generated entity
→ establish or upgrade TaskIdentity
```

`known_claim_ids/state_keys/open_issue_ids` 只是 MemoryBinding locator hint，不能成为 identity feature。Runtime 每次
重新校验 tenant、Scope、permission、authority、retention、GroundingBlock、Claim head、revoke 和 issue revision。
`active_goal_summary` 是受限描述，不是 task ID、Scope grant 或 authority。

OpenWorker 使用 Registry/Graph，而不是 LIFO stack：

```yaml
TaskRegistry:
  registry_revision:
  tasks: {}
  active_by_execution_lane: {}
  parent_child_edges: []
  suspended_task_ids: []
```

一个 execution lane 最多一个 active task；不同 lane 可并行。RETURN 可选择任意合法 suspended task，不要求返回
最近一次 push。Task Registry 属于 Host control state，不进入 MiLAi Canonical Core，也不由 Worker/模型直接写入。

### 7A.2.2 Relation、Decision、Transition 与确定性优先级

FP1 只支持五类 relation：

```text
CONTINUE   same persistent task
SUBTASK    new child under a compatible parent objective
SWITCH     create/activate a different task
RETURN     reactivate a suspended task
AMBIGUOUS  evidence insufficient for safe binding
```

Resolver 只能提出 decision，不能直接 mutation：

```yaml
TaskRelationDecision:
  source_task_id:
  candidate_target_task_id: null
  relation:
  confidence_tier: HARD | STRUCTURED | AMBIGUOUS
  reason_codes: []
  scope_compatible:
  profile_compatible:
  binding_constraints:
    cache_reuse: PROHIBITED | ELIGIBLE_FOR_VALIDATION

TaskBindingTransition:
  operation: KEEP | CREATE_AND_ACTIVATE | CREATE_CHILD | SUSPEND_AND_SWITCH | REACTIVATE | TENTATIVE
  source_task_id:
  target_task_id: null
  expected_registry_revision:
  expected_task_generation:
```

`ELIGIBLE_FOR_VALIDATION` 不是 CACHE 授权，只表示 FP4 可以继续校验。确定性 resolver 使用 lexicographic priority：

```text
0. Compatibility / hard invalidation
   Scope/profile/lane/lifecycle incompatible
   → CONTINUE and CACHE impossible

1. Hard switch
   host-normalized explicit new-task/project transition
   completed task + unrelated execution lineage
   → SWITCH

2. Hard continuity
   invocation-bound tool call → result
   same unresolved Host operation
   host-normalized explicit continue
   same Host task ID AND compatibility gate passed
   → CONTINUE

3. Structural relation
   compatible child operation → SUBTASK
   strong match to suspended Host task → RETURN

4. Otherwise
   → AMBIGUOUS
```

不使用 query embedding、semantic similarity、LLM classifier 或 retrieval result 覆盖上述顺序。Host-normalized
event 可以响应用户的“继续/新任务/返回某任务”意图，但用户 marker 本身不携带 Scope、profile 或 mutation authority。
Transition Validator 必须以 `registry_revision/task_generation` 做 compare-and-swap，检查 compatibility 后才更新 Registry。

### 7A.2.3 Delayed tool result 与 ABA 防护

tool invocation 时冻结 origin binding：

```yaml
ExecutionBindingToken:
  task_id:
  task_generation:
  lane_id:
  operation_id:
  registry_revision_at_invocation:
  scope_digest:
  profile_digest:
```

正式不变量：

```text
ToolResultBinding = BindingAtInvocation
ToolResultBinding != BindingAtCompletion
```

即使 result 到达时 lane 已切换到另一个 task，也只能写回原 task 的 execution state；原 task suspended 时保留并通知，
generation 已失效/对象不存在时进入 typed quarantine/orphan handling，绝不能绑定当前 active task。token 若跨不可信
Worker 边界必须是 opaque、integrity-protected、audience-bound handle；它只用于 correlation，不授予 MemorySlot、
Scope 或 Runtime authority。

### 7A.2.4 AMBIGUOUS、SUBTASK、RETURN 与 CACHE 边界

冻结以下 invariants：

```text
FP1-I01  TaskIdentity MUST NOT be established/upgraded from RetrievalResult
FP1-I02  SameTask != CacheReusable
FP1-I03  ToolResultBinding = BindingAtInvocation
FP1-I04  TaskRelationDecision != RegistryMutation
FP1-I05  ParentBinding does not authorize ChildBinding
FP1-I06  ReturnedTask does not authorize OldSlot reuse
FP1-I07  Task Resolver may veto CACHE but cannot authorize CACHE
```

AMBIGUOUS 不永久创建新 task，也不复用旧 CACHE：

```text
candidate tasks share compatible Host-authorized Scope/profile
→ tentative binding + cache PROHIBITED
→ 后续 FP2/FP3 可在最小已授权 Scope 做 NONE/L0/L1

candidate tasks cross Scope/profile
→ no union retrieval
→ NONE / explicit clarification / Host-approved rebind
```

Memory 返回内容不能反向消除 task ambiguity；只有新的 Host execution event、显式 task transition 或人工确认可以。
SUBTASK 可继承 project/workspace/artifact locator hint，但不自动继承 authority、profile、slot 或 OpenIssue status。
RETURN 必须重新验证 Scope/profile、canonical position、Claim/OpenIssue revisions、dependency frontier 和 NeedCovered。

### 7A.2.5 FP1 实现边界与 terminal gate

FP1 只实现：

```text
TaskIdentityState / TaskMemoryBinding public envelope
TaskRegistry/Graph + per-lane active binding
deterministic lexicographic TaskRelationResolver
TaskRelationDecision → deterministic Transition Validator → CAS mutation
ExecutionBindingToken + delayed-result/orphan handling
payload-free relation/transition trace
continuous OpenWorker product workload + negative-control tests
```

FP1 只输出 typed `TaskBindingContext` 供后续阶段消费。实际 requested→validated→attempted→terminal route propagation
属于 FP2；MemoryNeed/StateKey resolution 属于 FP3；完整 `CacheReusable` proof 属于 FP4。FP1 不以 `L0 calls > 0`
或最终 FastPath coverage 作为 PASS 条件，但必须消除 task-boundary 引起的 unsafe CACHE。

FP1 terminal hard gates：

```text
retrieval-established/upgraded task identity       = 0
Task Resolver LLM/embedding/retrieval calls        = 0
delayed-result wrong-task binding                  = 0
cross-Scope/profile false merge                    = 0
ACTION_SAFE task false merge                       = 0
task-boundary unsafe CACHE                         = 0
registry CAS/generation/ABA test failures          = 0
relation/transition trace completeness             = 1.0
hidden provider calls                              = 0
```

同时报告但不在 FP1 后验编造阈值：`CONTINUE/RETURN/SUBTASK` precision/recall、false merge/split、AMBIGUOUS rate、
`TaskFragmentationRate`、orphan count、`BindingSwitchesPerTask`、unjustified switch rate、resolver p50/p95、
unnecessary L1 rate。统计以完整 trajectory/task 聚类，不把同一 task 的 turn 当独立 replicate。

### 7A.2.6 Learned resolver 延后门：当前 Goal 禁止训练

当前 DG-12 不包含 FP1-B、FP1-C、LightGBM、XGBoost、Qwen3-4B classifier 或任何 learned Task Resolver work package。
允许保存 payload-free deterministic execution trace 和失败分层，但不得建立训练标签集、feature pipeline、trainer、
checkpoint、model registry 或在线 model route。

只有同时满足以下事实，才可在 `PE11` 反思中**考虑** successor Goal，而不是自动启动训练：

```text
PD02 FP1～FP6 online lane terminal
AND EH04 = PASS or SKIPPED_NO_RETAINED_CHANGE
AND PE08 OpenWorker/MCP/Serving E2E benchmark = FUNCTIONAL_AND_SAFETY_PASS
AND at least one frozen core memory benchmark has completed through OpenWorker→MCP→Runtime
AND deterministic resolver residual errors materially limit task success or FastPath efficiency
AND a new disjoint DEV/validation data plan exists
```

即使满足也只能提出 DG-13/successor proposal；不得修改已冻结 DG-12 candidate、不得在已消费的 DG-12 split 上训练
或重新确认。若 deterministic resolver 已满足正确性与效率目标，则 learned resolver 保持 `PARKED_NOT_JUSTIFIED`。

## 7A.3 `MemoryNeedSignature` 与独立 FastEligibility 标注

第一版 Need Resolver 必须是 typed、版本化和可回放的确定性合同；无法解析时保守进入 L1 或明确 abstain，不用
embedding similarity 伪造结构化 coverage：

```yaml
MemoryNeedSignature:
  scope:
  required_authority:
  consistency_floor:
  claim_ids: []
  state_keys:
    - subject:
      predicate:
      claim_type:
  open_issue_ids: []
  temporal_need: CURRENT | HISTORICAL | AS_OF
  evidence_need: NONE | SUPPORT_POINTERS | RAW_EVIDENCE
  intent_class: NONE | CURRENT_STATE | HISTORY | CONFLICT | EXPLANATION
```

评测不能由同一个 Need Resolver 同时生成 state key 又判自己正确。首次连续任务 workload 必须冻结独立的
ground-truth annotation：

```text
memory dependency
intent class
expected claim/state key or explicit KEY_ABSENT
FastEligible
required authority/consistency
expected route set
```

只在 `memory-dependent CURRENT_STATE turns` 上计算：

```text
StateAddressabilityRate
= needs with an existing correct canonical key
  / memory-dependent current-state needs
```

Horizon/LongMemEval 的 session-oriented ingestion 必须单独标记；其 addressability 不能替代真实 OpenWorker writer
workload 的产品结论。

地址率诊断的强制分支为：

```text
StateAddressability high + Fast execution low
→ routing/integration gap；优先修 Host/MCP/Runtime propagation

StateAddressability low on real continuous product workload
→ write-side representation gap；进入通用 canonical state identification/derivation slice

StateAddressability low only on session-oriented benchmark adapter
→ dataset representation characteristic；不得据此改坏产品 writer 或伪造 state key
```

write-side 修复仍必须走 Evidence→Proposal→Decision→append-only ClaimVersion/OpenIssue；不得原地改写 session
archive、根据 gold answer 建 key，或让 eval adapter直接创建已接受的 canonical truth。

## 7A.4 `CurrentStateReadService`：服务，不是新 Projection

产品 application service 接受 `claim_id` 或完整 canonical state key，并在一个一致 canonical snapshot 中读取：

```text
ClaimHead
+ EffectiveClaimState
+ relevant live OpenIssue and revision
+ minimum provenance pointer
= compact CurrentStateEnvelope
```

最小返回合同：

```yaml
CurrentStateEnvelope:
  status: HIT | MISS | BLOCKED | AMBIGUOUS | CANONICAL_UNAVAILABLE
  claims: []
  open_issues: []
  canonical_position:
  slot_validation_handle:
  trace_id:
```

强制边界：

- 不创建 async authoritative CurrentState database、current-state vector truth 或第二 ECS 实现；
- current-state lookup 不依赖 query embedding、FTS、vector、RRF 或 reranker；
- 若以后增加自然语言→state-key locator，它只生成 candidate key，随后仍由 exact canonical read 决定；
- Claim 与 live OpenIssue 必须来自同一合法 snapshot；canonical unavailable 时不得用旧 projection 假装 current；
- Evidence 正文默认不加载，只返回经校验 pointer；只有显式 evidence need 才 recovery。

## 7A.5 Route 执行合同与 `Route Execution Fidelity`

Router 输出必须成为跨 OpenWorker、MCP、Client 和 Runtime 的 typed execution contract：

```yaml
RecallExecutionTrace:
  need_signature_id:
  requested_route:
  validated_route:
  attempted_routes: []
  terminal_route:
  result: HIT | MISS | BLOCKED | ABSTAINED | ERROR
  policy_override_reason:
  fallback_reason:
  next_route_recommended:
  query_embedding_calls:
  vector_calls:
  reranker_calls:
```

Runtime 有权因权限、Scope、一致性或 canonical 状态拒绝/加强 Host route；这种安全覆盖必须显式记录，不能算路由
错误。禁止：

```text
requested_route=L0
→ Runtime silently executes full L1
→ report says L0
```

正式指标：

```text
RouteExecutionFidelity
= P(first attempted route = validated route
    | valid request AND no required/explicit policy override)

L0 requested → L0 hit / miss / blocked
L0 → L1 explicit escalation
CACHE → validated hit / truth miss / coverage miss / policy miss
L1 → FTS stop / vector escalation / reranker escalation
```

无显式覆盖样本的 `RouteExecutionFidelity` 必须为 `1.0`；trace 缺失不能归类为成功。

## 7A.6 CACHE：Truth Validity 与 Need Coverage

Slot coverage 使用结构化合同：

```yaml
MemorySlotCoverage:
  scope:
  authority_supported:
  claim_ids_and_head_versions: []
  state_keys_and_head_versions: []
  open_issue_ids_and_revisions: []
  temporal_coverage:
  evidence_depth:
  policy_identity:
  dependency_frontier:
```

正式 predicate：

```text
CacheReusable
= BrokerBoundValidationProofValid
  AND PolicyCompatible
  AND NeedCovered(MemoryNeedSignature, MemorySlotCoverage)
  AND DependencyFrontierValid
```

`NeedCovered` 必须是确定性集合/层级 predicate；不可判断即 `CACHE_MISS`。仅验证旧 claim IDs 会漏掉同 Scope
中新出现且与当前 Need 相关的事实，因此初版允许用全局 canonical position 保守失效，随后才能用 state-key、
issue-revision 或 scope dependency frontier 降低过度 invalidation。优化 invalidation 粒度不能改变真值。

## 7A.7 Progressive L1 与 DCEP 的位置

只有 NONE/CACHE/L0 不适用或失败后才进入：

```text
L1-A exact alias / FTS candidate generation
→ canonical resolution + gate
→ query-type-specific sufficiency
   ├─ sufficient → STOP
   └─ insufficient → L1-B query embedding + vector
                      → gate + sufficiency
                      ├─ sufficient → STOP
                      └─ ambiguous → L1-C fusion/reranker
```

早停必须发生在 canonical resolution/gate 后，且按 query type 冻结：singleton current-state、set-valued、
historical/as-of、conflict/branch 和 ACTION_SAFE 具有不同 completeness 条件。高 lexical score 不证明集合完整；FTS
未命中不证明事实不存在。不能确定时必须升级或 abstain。Progressive L1 会改变检索/Context 行为，因此必须在
DEV shadow/ablation 中验证，不能自动当作等价性能改动。

DCEP 仅在读取和合法 recovery 后仍存在 evidence/authority/OpenIssue blocker、且 Host 需要规划信息获取动作时
启动。若用户只问“是否已确定”，CurrentStateRead 可直接返回 live OpenIssue；L0 miss 本身不触发 DCEP。

## 7A.8 连续产品 workload、四象限与阈值冻结

Fast Path 第一轮不用 Horizon，使用两个 matched、disjoint、public/synthetic/de-identified 的连续 OpenWorker
workload：`FASTPATH_DEV` 用于 characterization/开发，`FASTPATH_CONFIRMATION` 的 turn 与 labels 在 FP6 前 sealed。
每个 workload 均包含：

```text
one project
20–50 turns
one persistent goal with normal follow-ups
current decision/config/object queries
same-task continuation and tool retry
history/explanation query
conflict and live OpenIssue
revoke and stale slot/index adversary
explicit goal switch and Scope/profile switch
```

FP0 已封存的 `fast-path-workloads.yaml`、DEV labels 与 confirmation seal 不得为 0.9.0 改写。现有 workload 已覆盖
普通 continuation、goal/scope/profile switch 和 RETURN；FP1 新增的 SUBTASK、AMBIGUOUS、same-file/different-goal、
per-lane concurrency、non-LIFO RETURN、delayed result 和 ABA 只进入 deterministic product/integration negative-control
tests，不创建新 confirmation split，也不调用 answer/judge Provider。expected relation/transition 由 test fixture 的 Host
execution graph 和 invocation binding 冻结，不读取 gold memory answer、retrieved Claim 或未来 turn。

现有每个 turn 继续使用已冻结独立 MemoryNeed/StateKey/FastEligibility 标签形成 Fast Path 主诊断：

| | Fast executed | Deep executed |
| --- | ---: | ---: |
| **Fast eligible** | 正确 | routing/execution gap |
| **Fast ineligible** | false-fast | 正确 |

对 `Fast eligible + deep` 再区分 task continuity、Need resolution、state key、route propagation、state availability；
对 `Fast ineligible + deep` 中的 current-state turn 再统计 representation gap。先做 Phase-0 characterization，不
预设 `80–95%` fast coverage。指标分母固定为：

```text
FastPathExecutionCoverage
= correctly executed NONE/CACHE/L0 among FastEligible turns
  / FastEligible turns

FalseFastRate
= incorrectly executed NONE/CACHE/L0 among FastIneligible turns
  / FastIneligible turns
```

DEV 分布出现后、confirmation labels 打开前，才冻结最小有意义的 coverage/deep-call/latency
改善和置信区间。以下硬门从第一轮即生效：

```text
ACTION_SAFE false-fast                      = 0
stale/under-covered CACHE authorization     = 0
RouteExecutionFidelity without override     = 1.0
route/need trace completeness               = 1.0
hidden provider calls                       = 0
task/canonical correctness                  = non-inferior
```

在线表与历史物化表必须分别裁决；cold build 结果不能替代 Fast Path，Fast Path 也不能掩盖正式 benchmark 的 cold
materialization 成本。

## 7A.9 OpenViking 设计吸收：访问模式，不是后端替换

OpenViking 的可复用价值主要来自“已知地址直接访问、简单/复杂查询分流、内容分级加载、服务端组装、跨轮发送
去重与派生处理异步化”。MiLAi 只吸收这些访问模式，不吸收其 truth model。本版依据 `2026-08-24` 可访问的
OpenViking 官方 architecture、context layers、Viking URI、retrieval、session、transaction 和 capability reference
文档形成设计约束；当前工作区没有可验证的 OpenViking checkout，因此这些事实是 documentation-level，尚不是
可运行 baseline identity：

- <https://docs.openviking.ai/en/concepts/01-architecture>
- <https://docs.openviking.ai/en/concepts/03-context-layers>
- <https://docs.openviking.ai/en/concepts/04-viking-uri>
- <https://docs.openviking.ai/en/concepts/07-retrieval>
- <https://docs.openviking.ai/en/concepts/08-session>
- <https://docs.openviking.ai/en/concepts/09-transaction>
- <https://docs.openviking.ai/en/agent-integrations/16-capability-reference>

不得把比较写成“OpenViking 没有一致性/事务、MiLAi 才有”。OpenViking 官方设计包含 transaction、path lock、
fencing 与 recovery；MiLAi 要验证的差异是 Evidence authority、OpenIssue、revoke、Scope 和 ACTION_SAFE 的
epistemic contract，而不是泛化地否定另一系统的数据一致性。

双方同名层级的含义必须保持分离：

| OpenViking 设计轴 | MiLAi 对应设计轴 | 本 Goal 的吸收方式 |
| --- | --- | --- |
| `viking://` typed URI | Claim ID / typed canonical state key | `StateKeyRef` 作为 locator hint，随后 exact canonical revalidation |
| Abstract / Overview / Detail | Context evidence depth | `ProgressiveEvidenceLoad`，不重命名 MiLAi L0/L1/L2 |
| `find()` / `search()` | L0 direct state read / progressive L1 | 借鉴 cheap/expensive 分流；OpenViking `find()` 仍是 semantic path，不等同 MiLAi L0 |
| context assembly / recall ledger | `prepare_memory_context` / exposure accounting | 服务端一次组装；`ExposureLedger` 只消除重复正文，不决定 CACHE 合法性 |
| async semantic processing | async derived projection/proposal preparation | 只异步派生层；Canonical commit 和 ACTION_SAFE validation 继续受治理 |
| content store + vector locator | Canonical Core + non-authoritative projection | projection 只生成 candidate，永不升级为 authority |

正式吸收五项能力，全部落入现有 FP/Lane，不新增 `DG12OpenViking*` 产品模块：

### A. Typed `StateKeyRef`：把“地址”带过 Host/MCP 边界

```yaml
StateKeyRef:
  version:
  scope:
  subject:
  predicate:
  claim_type:
  claim_id: null
  relevant_open_issue_ids: []
  canonical_position_seen: null
```

`StateKeyRef` 不是新 canonical object，也不是 capability。Host 可以在持续 task 中复用它，但 Runtime 每次必须
重新校验 tenant、Scope、profile、authority、Claim head、GroundingBlock、revoke 与 live OpenIssue。自然语言
locator 只能产生 candidate ref；完整 key 缺失或歧义时进入 progressive L1，不能根据相似度伪造 exact hit。

### B. `ExposureLedger`：只回答“已经发过什么”，不回答“现在是否足够”

```yaml
ExposureLedgerEntry:
  prepared_artifact_id:
  keyed_delivery_digest:
  detail_level: ABSTRACT | OVERVIEW | EVIDENCE_DETAIL
  task_id:
  slot_id:
  audience_profile:
  canonical_position:
  open_issue_revisions: []
  sent_at:
  cooldown_until:
```

必须满足：

```text
ExposureKnown(entry) != NeedCovered(need, slot)
ExposureKnown(entry) != CacheReusable(need, slot)
ExposureKnown(entry) != CanonicalValidity
```

Exposure dedup 只能在 Runtime 已完成本轮 canonical/Need validation、且新 prepared artifact digest 与原发送内容相同
后抑制重复 body；它不能跳过 Context preparation，也不能用旧 digest 压制新 Claim head、OpenIssue revision、revoke
或 Scope 变化。digest 必须按 privacy domain keyed，trace 不保存用户正文。OpenViking 风格的 `dedup_turns/cooldown`
在实验配置中必须显式冻结，不能依赖可能变化的默认值。

### C. `ProgressiveEvidenceLoad`：pointer first，正文按 Need 加载

```text
CURRENT_STATE / evidence_need=NONE
→ compact CurrentStateEnvelope

SUPPORT_POINTERS
→ compact state + validated provenance pointers

OVERVIEW
→ bounded supporting-evidence overview

RAW_EVIDENCE
→ explicit RECOVER_EVIDENCE with Scope/authority/retention checks
```

MiLAi 默认 context 不携带全部历史 fragment 或 raw Evidence。层级降级只优化 token/IO；若请求要求的 evidence
depth 未满足，结果必须是 `NEEDS_RECOVERY/ABSTAIN`，不能因 budget 下降而把 INFORMATIONAL 结果冒充
ACTION_SAFE。目录摘要、LLM summary 或 projection overview 都不是 canonical claim。

### D. Server-side `prepare_memory_context`：一次调用完成选择、预算与去重

OpenWorker 主链优先使用一个稳定 MCP application operation：

```yaml
prepare_memory_context:
  input:
    task_memory_state:
    memory_need_signature:
    token_budget:
    previously_seen_slot_handle:
  output:
    status: UNCHANGED | REPLACE | NEEDS_RECOVERY | ABSTAIN | ERROR
    current_state_envelope:
    exposure_delta:
    recall_execution_trace:
```

这不是把多个权限判断移到 Worker；它只是减少 Worker→MCP 往返和重复 JSON/body。trusted broker/Runtime 仍执行
route validation、canonical gate、slot proof 和 exposure decision。`UNCHANGED` 必须同时满足 CacheReusable 与本轮
prepared artifact 没有需要发送的 delta。

### E. Async Derived Plane：让语义派生退出同步 turn，但不异步真相

允许后台执行：fragment/summary derivation、embedding、FTS/vector projection、proposal preparation、物理 cleanup
与 compaction。必须同步完成或显式返回 pending/degraded 的是：Evidence capture receipt、Scope/authority validation、
canonical head/OpenIssue/revoke 检查，以及 ACTION_SAFE context certification。未 adjudicate 的 Observation/Evidence
最多进入明确标注的 INFORMATIONAL 临时上下文，不能成为 current Claim 或关闭 OpenIssue。

实施映射固定为：

```text
FP1 → deterministic execution-aware Task Binding / Registry / generation safety
FP2 → prepare_memory_context + typed route trace
FP3 → StateKeyRef + CurrentStateRead + progressive pointer contract
FP4 → MemorySlotCoverage 与 ExposureLedger 严格分离
FP5 → progressive evidence depth + progressive L1 + exposure-token ablation
Lane B → async derived projection/materialization；仅按 stage profile 保留
PE00/PE01 → OpenViking baseline checkout/config/readiness freeze
```

若 address/exposure/progressive-load 候选造成任何 stale suppression、under-covered CACHE、OpenIssue/revoke 漏检、
ACTION_SAFE false-fast 或 task quality 回归，立即回退相应候选。若只减少日志/正文但对 token、调用或 p95 无可测收益，
保留简单合同、PARK 复杂 ledger/cooldown 机制，不为“模仿 OpenViking”继续扩展产品架构。

---

# 8. 全阶段可观察性

## 8.1 必填 stage metrics

```text
db_create_or_clone_ms
migration_ms
api_start_ms / worker_start_ms / mcp_start_ms
embedding_load_ms / embedding_warm_ms
reranker_load_ms / reranker_warm_ms

evidence_ms / proposal_ms / review_ms / governance_total_ms
fragment_derivation_ms
embedding_ms
embedding_logical_items / embedding_unique_items
embedding_inference_batches / embedding_cache_hits
projection_write_ms / projection_index_maintenance_ms
outbox_wait_ms / projection_drain_total_ms / watermark_ready_ms
projection_restore_ms / projection_attach_ms
workload_fingerprint_ms / workload_reuse_validation_ms

task_relation_ms / task_transition_ms / task_state_rebind_ms
task_relation / confidence_tier / reason_codes / transition_operation
registry_revision / task_generation / binding_generation / execution_lane_id
cache_reuse_constraint / delayed_result_origin_task / delayed_result_terminal_task
task_resolver_llm_calls / task_resolver_embedding_calls / task_resolver_retrieval_calls
need_resolution_ms / state_key_resolution_ms
requested_route / validated_route / attempted_routes / terminal_route
policy_override_reason / fallback_reason / next_route_recommended
cache_validation_ms / cache_truth_valid / cache_need_covered / cache_dependency_valid
current_state_read_ms / current_state_status / state_key_exists
state_key_ref_present / state_key_ref_resolved / state_key_ref_revalidated
exposure_validation_ms / exposure_body_suppressed / exposure_bytes_saved / exposure_tokens_saved
context_detail_level / evidence_recovery_calls / evidence_body_bytes
fast_eligible_label / route_execution_fidelity / false_fast
query_embedding_calls / vector_calls / reranker_calls

mcp_transport_ms
query_embedding_ms
fts_ms / vector_ms / fusion_ms
recent_canonical_ms / canonical_gate_ms
reranker_ms / context_compile_ms
query_internal_total_ms
mcp_adapter_wrapper_ms / query_outer_total_ms

reset_ms / cleanup_ms
answer_ms / judge_ms
```

必须同时保存非重叠 top-level span 与可嵌套 child span。以下恒等式用于检查遗漏和重复计时：

```text
cold_history_build_ms
≈ governance_total_ms
 + projection_drain_total_ms
 + build_orchestration_unattributed_ms

projection_drain_total_ms
≈ fragment_derivation_ms
 + embedding_ms
 + projection_write_ms
 + projection_index_maintenance_ms
 + projection_worker_unattributed_ms

query_outer_total_ms
≈ mcp_transport_ms
 + mcp_adapter_wrapper_ms
 + query_internal_total_ms
 + outer_query_unattributed_ms
```

`projection_write_ms` 若已经包含 index maintenance，必须通过 span parent/child 关系标记，不能再相加；
`watermark_ready_ms` 是 readiness wall span，不得与其内部 worker stages 二次求和。每份 terminal profile 必须列出
`explained_wall_ms`、`unattributed_wall_ms` 和 `explained_ratio`，目标为 `>= 0.95`。不足时先补计时，不先优化。
`mcp_adapter_wrapper_ms` 必须是扣除 transport 与 Runtime internal query 后的 exclusive wrapper span；若现有
instrumentation 只能得到 inclusive span，则保留 parent/child 关系并另报 exclusive remainder，不得直接相加。

## 8.2 Materialization lifecycle 与复用指标

复用状态必须显式分层：

```text
same_lease_reuse_hits
process_restart_reuse_hits
fresh_database_restore_hits
cross_arm_reuse_hits
cross_run_reuse_hits
partial_fragment_cache_hits
validated_reuse_hit_rate
reuse_invalidation_rate
```

并报告：

```text
normalized_fragments_total / unique
duplicate_ratio_within_history
duplicate_ratio_within_arm
duplicate_ratio_cross_arm
duplicate_ratio_cross_run
restore_bytes / restore_ms / attach_ms
coverage_frontier / required_canonical_position / coverage_gap_count
```

未持久化到进程重启或 fresh DB 的命中只能写 `SAME_LEASE_REUSE`，不得写 persistent cache、projection image 或
product restart recovery。digest 统计只能作用于 public/de-identified 数据或相同 privacy domain，不能输出可用于
跨 tenant existence inference 的原始 digest。

## 8.3 每个层级的统计

```text
run
product deployment
evaluation lease
cohort/history
question
method
benchmark
```

每层记录 online route/deep/cold、success/failure、attempt、CPU、RSS、storage、calls 和 token。日志不保存完整用户正文、
prompt、token、密码、KEK 或 cookie。

## 8.4 主要效率输出

```text
cold deployment cost
governed cold history build cost
projection drain throughput and cost
fresh-DB restore/attach cost, if implemented
warm online query p50/p95/p99
NONE / CACHE / L0 / L1 route rates and per-route p50/p95/p99
StateAddressabilityRate / FastEligibilityRate / FastPathExecutionCoverage
RouteExecutionFidelity / false-fast / cache coverage-miss rate
CONTINUE / RETURN / SUBTASK precision-recall / false merge / false split / AMBIGUOUS rate
TaskFragmentationRate / orphan tasks / BindingSwitchesPerTask / unjustified switch rate
delayed-result wrong-task bindings / task-boundary unsafe CACHE
Task Resolver p50/p95 / Task Resolver model and embedding call rate (=0 in DG-12)
FTS-only / vector / reranker escalation rate
query embedding calls per all Agent turns
ExpensiveMemoryRate = (VectorTurns + RerankerTurns) / AllAgentTurns
memory context/tool-result tokens per route / validated slot reuse saved tokens
exposure-dedup saved body bytes/tokens / false suppression count
ABSTRACT / OVERVIEW / EVIDENCE_DETAIL route mix and evidence recovery rate
recent-canonical / FTS / reranker / MCP-wrapper shares
amortized E2E per question
questions/hour
embedding logical items/second
embedding unique items/second
embedding batches/second
projection rows/second
storage bytes/history and /question
quality per 1K prompt tokens
quality per second
```

产品性能、Evaluation amortization 与实验基础设施性能必须分三张表。`reference / reuse` 只能说明评测摊销；
只有 cold product 或 warm OpenWorker→MCP→Runtime 路径才能形成产品 throughput/latency claim。

---

# 9. 本体整理、通用产品开发与薄 Evaluation Harness

## 9.1 旧工作包统一收敛

`DG12-BHE00 = PASS`，其 profile 保留。`DG12-BHE01` 已停止，`BHE02～08` 和上一版 `PC00～07` 不再形成
多套并行状态机，统一映射到下面的 CORE/PD/EH 工作包体系：

| 旧范围 | 新 owner |
| --- | --- |
| `PC00/PC01` ownership、identity、configuration | `CORE00/CORE01` |
| `PC02/PC05/PC06` observability、lifecycle、已有 policy 整理 | `CORE01`，新增优化进入 `PD00` |
| `PC03/PC04` batch projection、bulk ingest | `PD00` |
| `PC07` package/E2E | `CORE02` 基线 + `PD01` 优化后复验 |
| `BHE01` lifecycle + loader 混合原型 | `CORE01` product 提取 + `EH00` eval 特配 |
| `BHE02～06` pool/planner/cache/batch | `PD00` + `EH01` |
| `BHE07/BHE08` performance/freeze | `EH02/EH03` |

不得为旧编号生成新的 terminal、receipt 或补审文件；状态只在新工作包记录。

## `DG12-CORE00` Existing Code Inventory & Ownership

目标：在写新功能前完成一次可执行的旧代码整理决定。

必须完成：

- 枚举 §4B.1 全范围的源文件、主要 symbol、entrypoint、public export、反向依赖和测试；
- 以 §4B.1 七类动作逐项分类，记录 target owner、target API、compatibility、test owner 和删除条件；
- 冻结 package dependency graph 和 §4B.2 目标结构；
- 找出所有产品中的 Goal/benchmark identity、默认配置、私有跨包 import 和重复实现；
- 区分 source-locked historical bytes 与可整理的 active code；
- 增加 architecture checks 的测试设计，但本步骤不靠审计生成 PASS。

唯一主要产物：`var/dg12/product/core-refactor-matrix.json`。允许附同目录的 machine-readable dependency graph，
不生成逐文件迁移报告。

退出条件：active file/symbol 覆盖率 100%，`UNDECIDED` 为 0，每个迁移项都能回答“为什么属于产品或 eval”。

## `DG12-CORE01` Core Migration & Structure Normalization

目标：按矩阵把现有通用代码真正迁入正确本体 owner，而不是只完成目录设计。

必须完成以下纵向迁移：

1. 将只供 OpenWorker 使用的 `agent_prefetch`、UDS client 和 provider execution 从 Runtime adapter 层移到
   MCP/OpenWorker 的公共 owner，消除 OpenWorker→`milai.adapters.*` 和 OpenWorker→Runtime HTTP 旁路；
2. 将 grouped compact、turn window、temporal/aggregate、numeric/unit、assistant-role retention 整理成
   semantic product policies，旧 DG identity 仅作为兼容 alias；
3. 将 `StageRecorder` 中可复用的 payload-free timing/usage 模型提升到 `milai.observability`，benchmark
   monkey-patch 保持历史诊断，不进入产品；
4. 用产品 `milai.operations`、正式 OpenWorker/MCP 生命周期替代 `_CohortRuntime`、`_runtime_context` 和
   `CohortRuntimeSlot` 中的产品职责；
5. 将 workload DTO、CUPID/Horizon/BEAM/Memora loader、selection、scorer 留在 `evals/`，拆开 lifecycle 与
   dataset 枚举；
6. 收敛 DG10/DG11 scripts：source-locked 原位只读；活跃可复用逻辑进入稳定 package/CLI；无调用者且未锁定
   的一次性脚本删除或归档；
7. 将测试移动到代码 owner：Runtime 测 server semantics，Client/MCP/OpenWorker 测 integration，evals 只测
   adapter/protocol/scorer。

迁移按 §4B.4 一条纵向能力一条纵向能力执行。每完成一条就切换实际 caller 并删除活跃重复实现，不等到最后
才做一次“大搬家”。此阶段不引入新的 benchmark shortcut，也不以性能涨幅作为 PASS 条件。

退出条件：满足 §4B.6 全部门，状态升级 `CORE_NORMALIZED`。

## `DG12-CORE02` Product-only Baseline Acceptance

构建整理后的 Runtime、Client、MCP、OpenWorker wheels，并在不挂载 `evals/`、不读取 `var/dg*`、
不加载 benchmark 的条件下执行：

```text
fresh exact-role PostgreSQL
→ clean wheel install in non-repo cwd
→ Runtime start/ready/warm
→ trusted broker + milai-mcp + profile UDS ready
→ OpenWorker reader-lite memory_mode task
→ Evidence / Proposal / Decision
→ recall / prepare-context / cache validation
→ explicit handoff to independent submitter lane
→ OpenIssue / revoke / wrong-scope / stale projection adversary
→ multiple tasks and queries in one deployment
→ graceful close and cleanup
```

同时验证：Runtime/integration import boundary、semantic identity mixed-version、legacy read、新写 semantic、
wheel contents、MCP initialize/list_tools/tools_call/reconnect、profile isolation、CLI、配置、rollback 到 DG11
frozen wheels。Generic direct Client、LangGraph 和 AutoGen 可在主链通过后运行 portability smoke，但不替代或阻断
OpenWorker/MCP acceptance。

退出条件：`CORE_BASELINE_E2E_PASS`。在此之前 `PD00` 和任何新 benchmark 运行都不允许开始。

## `DG12-PD00` General Product Capability Development

只有 `CORE02 = PASS` 后才开发新能力。候选来自 BHE00 profile，但必须面向所有合法 MiLAi 用户：

```text
payload-free stage observability
EmbeddingProvider.embed_many() and true tensor batching
ProjectionBatchProcessor with per-item identity/retry/watermark
long-lived Runtime/MCP/broker/relay/model warm lifecycle
governed bulk ingest only if profile proves it is needed
semantic context/retrieval policy improvements
```

每个能力都必须：

- 从 OpenWorker/MCP 主接口使用，不要求 benchmark 配置；
- 在 unit、真实 PostgreSQL、OpenWorker/MCP E2E 中验证；
- 保持 Scope、authority、OpenIssue、revoke、order、idempotency、Outbox、watermark；
- 分开记录产品 online route/deep/cold 成本和资源占用；
- 最多三次有实质差异的尝试，然后 `KEEP / REVERT / SKIPPED_NOT_JUSTIFIED`；
- 不创建 `dg12_*` 产品模块或“一实验一实现”文件。

`GovernedBulkIngest` 不得自动接受 Proposal、跳过 Decision 或隐藏 per-item failure。`embed_many()` 的 fallback
可以逐项执行，但 ONNX batch claim 必须来自真实 tensor batch。

## `DG12-PD01` Optimized Product Vertical E2E

对 `PD00` 所有 retained 改动重新构建 wheels，重复 `CORE02` OpenWorker/MCP 产品纵向路径，并报告：

```text
correctness and safety regression
cold deployment
warm multi-query latency
embedding logical items / inference batches
throughput and RSS/storage
token and provider calls
rollback
```

退出条件不是“所有优化成功”，而是每个候选均 terminal，retained set 通过产品 E2E，状态为
`PRODUCT_DEVELOPMENT_TERMINAL`。随后才允许建立 evaluation harness。

## `DG12-EH00` Thin Product Adapter & Dataset-specific Adaptation

在 `evals/` 建立薄层：

```text
evals.harness:
  WorkloadHistory / WorkloadQuestion DTO
  EvaluationRuntimeLease
  OpenWorkerMcpMemoryMethodAdapter
  ResultRecord

evals.datasets:
  CUPID / Horizon / BEAM / Memora / LongMemEval mapping

evals.scorers and evals.protocols:
  metric / judge contract / split / schedule / thresholds
```

`evals/` 可以针对 benchmark 的字段、时间格式、session 结构、答案 schema、官方 scorer 和 resource protocol
做特殊适配；但只能把特殊输入转换为通用 workload，再通过 OpenWorker/MCP 产品路径调用，不能实现 MiLAi
context compiler、retrieval、governance、Runtime lifecycle 或 cache semantics。Direct Client adapter 只可作为
诊断分解对照，必须命名为 `DIRECT_CLIENT_DIAGNOSTIC`，不得作为正式 MiLAi 方法。

退出条件：同一 `OpenWorkerMcpMemoryMethodAdapter` 可接收任意合规 workload DTO；新增 benchmark 只新增
mapping/scorer/config，不新增 MiLAi 执行引擎，不 import `_CohortRuntime`、repository 或其他私有 helper。

## `DG12-EH01` Reusable Evaluation Infrastructure

交付 isolated temporary database/blob provisioner、immutable-workload fingerprint、one-build/many-question planner、
bounded lease pool、public/de-identified artifact cache、seeded schedule、checkpoint 和 terminal accounting。

这些能力属于 evaluation infrastructure，不进入产品 wheel，不实现 memory behavior。它通过产品
start/ready/warm 和 OpenWorker/MCP public contracts 获取服务；资源 reset 只作用于明确标记的临时
evaluation resource。

## `DG12-EH02` Product-vs-Harness Performance A/B

比较：

```text
DG11 frozen product / reference-faithful
CORE02 normalized OpenWorker/MCP product / faithful deployment
PD01 retained OpenWorker/MCP product / persistent deployment
PD01 retained OpenWorker/MCP product / thin harness immutable-workload reuse
```

分别报告代码整理影响、产品优化收益与评测摊销收益。只有前三项可形成产品 latency/throughput claim；第四项
只说明评测成本。Horizon 10-case smoke 初始工程目标为 wall time 至少降低 5 倍，同时 context/Top-K/治理语义
和安全零差异；未达到时依据 stage profile 决定 KEEP/REVERT，不增加 benchmark-specific shortcut。

## `DG12-EH03` Harness Freeze

交付 `product-package-manifest.json`、`public-api-contract.json`、`harness-manifest.json`、
`evaluation-resource-config.yaml`、`equivalence-summary.json` 和 `resource-plan.json`。`EH03 = PASS` 后允许
ND00/ND01 使用现有快速路径并为 PD02 提供 anchor；若 PD02 改变 execution bytes，ND02/PE 必须等待 EH04，
不能继续使用已被 supersede 的 EH03 identity。

## `DG12-PD02` Fast Path Reachability & Evidence-driven Performance Closure

目标：基于 EH02 的真实 profile，按顺序关闭三条不同产品主链：

```text
A. OpenWorker online Fast Path Reachability
B. remaining L1/deep recovery latency
C. cold governed materialization throughput
```

不得把三者合并为一个“MiLAi latency”，也不得在 A 未 terminal 时用向量、reranker 或 paging 微优化替代在线
纵向路径修复。

入口条件：

```text
ND01 performance observation/focal/rival/prediction/falsifier 已冻结
EH03 frozen product/harness identity 可复算
formal paper labels 未打开
```

本工作包已经 terminal：FP1 deterministic binding 通过，FP2～FP5 retained product path 通过 EH04 等价性复验，
但 FP6 untouched confirmation 的 hard/non-inferiority gate 未通过，deep/cold matched product blocks 也未建立。
因此 `DG12-PD02=TERMINAL_TARGET_MISS`，以下步骤保留为已执行合同与后续设计参考，不能继续重跑 FP6 或补发 speed
claim。

### Lane A — Online Fast Path（必须先执行）

1. **FP0 Shadow baseline**：冻结 §7A.8 的 DEV/CONFIRMATION workload identity 与独立标签，封存 confirmation
   labels；只在 DEV 增加 payload-free trace且不改变 route，得到 pre-change StateAddressability、FastEligibility、
   FastPathExecutionCoverage、REF、per-route latency、embedding/vector/reranker calls；
2. **FP1 Deterministic Execution-aware Task Binding**：按 §7A.2 实现 `TaskIdentityState/TaskMemoryBinding`、
   Registry/Graph、五类 relation、lexicographic resolver、Decision→Transition Validator、generation/CAS 和
   invocation-time delayed-result binding；把 current utterance 与 active goal 分开，task/goal/Scope/profile 切换
   显式 rebind/invalidate。Task Resolver 的 LLM/embedding/retrieval/training calls 必须为 0；
3. **FP2 Route contract**：把 requested→validated→attempted→terminal route 贯通 OpenWorker、MCP、Client、Runtime，
   关闭“Router 说 L0、Runtime 静默跑 L1”；同时以 server-side `prepare_memory_context` 合并选择、预算和返回，
   但不把 route/canonical/slot validation 下放给 Worker；
4. **FP3 Current state**：实现 §7A.4 application service、typed `StateKeyRef` 和 Need/StateKey resolution；默认返回
   compact state + provenance pointer，按 §7A.3 四象限区分
   routing gap、真实产品 representation gap 与 benchmark/session characteristic。只有真实产品 representation gap
   成立时，才通过现有治理写链实现通用 state identification/derivation candidate；
5. **FP4 Validated slot**：实现结构化 `MemoryNeedSignature/MemorySlotCoverage`、broker-bound validation proof 和
   dependency invalidation；不可判断一律 CACHE miss；新增 `ExposureLedger` 时必须与 coverage 分表、分 predicate，
   只能抑制 identical prepared body，不能授权 CACHE；
6. **FP5 Progressive L1**：先按 Need 做 ABSTRACT→OVERVIEW→EVIDENCE_DETAIL progressive load；只对仍进入 L1
   的 turn 做 FTS→vector→reranker 逐级升级；早停必须通过 query-type-specific canonical sufficiency，若改变
   Top-K/Context 则作为新 DEV candidate；
7. **FP6 Confirmation**：在 sealed、untouched `FASTPATH_CONFIRMATION` 上只运行一次，形成 online lane terminal；
   不使用 DEV 或 Horizon/session archive 代替 confirmation。

FP1 不拆成训练型 FP1-B/FP1-C，也不为了提高 relation accuracy 启动模型。FP1 只交付 deterministic
`TaskBindingContext`；FP2/FP3/FP4 分别负责 route、Need/StateKey 与 CACHE proof。即使 FP1 的 false split 或
AMBIGUOUS rate 尚有优化空间，只要 hard safety/correctness gate 通过，就先完成完整产品链和端到端 benchmark，
不能把 learned resolver 变成进入 FP2 的前置条件。

FP5 DEV terminal 后、FP6 labels 打开前必须冻结 machine-readable `fast-path-acceptance.yaml`。在没有真实分布前不编造
`80–95%` coverage；阈值必须包含最小有意义的 coverage/deep-call/latency effect、CI 规则和 non-inferiority，且
不得在 FP6 后修改。

### Lane B — Deep recovery 与 Cold Materialization（Lane A terminal 后执行）

1. **补足归因**：实现 §8 非重叠 span，并在 matched repeated blocks 上达到 `explained_ratio >= 0.95`；
2. **Deep-path closure**：在真实进入 L1 的 turn 上先关闭 `recent_canonical` query plan、scope/time index 与 FTS；
   只有剩余 profile 仍指向 reranker 时才调整 pooling/batch/thread；补齐当前约 `11.507 s/10 cases` 的
   OpenWorker/MCP/adapter outer difference；
3. **Cold discrimination**：按 §7.4 顺序运行 `M0～M4`，先区分 governance、embedding、scalar write/index；
4. **最小产品替代**：只实现证据指向的最简单通用能力：set-based writer、governed pipeline、privacy-domain CAS
   中的一个；派生 projection 可后台执行，但 canonical certification 不得异步化；每次只改变一个主要机制；
5. **Restore decision**：只有 M3/M4 不能接近 warm floor，且 M5 的 restart/replica/migration use case 有独立收益，
   才实现 `ProjectionMaterializationStore`；否则明确 `PARKED_NOT_JUSTIFIED`。

禁止把 worker 暂停、precomputed vector、直接 DML、same-lease workload receipt 或 evaluation cache 当成 retained
产品实现。所有保留代码必须进入稳定 Runtime/application/persistence/operations owner，可由普通 OpenWorker/MCP
路径使用，名称不得包含 DG12、Horizon 或 benchmark identity。

本工作包的冻结工程目标为：

```text
primary correctness:
  Top-K/context/canonical/OpenIssue/revoke/scope difference = 0
  retrieval-established task identity = 0
  Task Resolver model/embedding/retrieval calls = 0
  delayed-result wrong-task binding = 0
  cross-Scope/profile and ACTION_SAFE task false merge = 0
  task-boundary unsafe CACHE = 0
  task relation/transition trace completeness = 1.0
  ACTION_SAFE false-fast = 0
  stale or under-covered CACHE authorization = 0
  RouteExecutionFidelity without explicit override = 1.0
  route/need trace completeness = 1.0

online product target:
  fast-path-acceptance.yaml = frozen before FP6
  task/canonical correctness = non-inferior
  FastPathExecutionCoverage / deep-call / query-embedding / overall latency
    = meet frozen minimum meaningful effect, or terminal miss without false claim

cold product target:
  10-case first materialization + query <= 268.900 s
  # 相对 1344.500 s frozen reference 达到原始 5x 目标

deep L1 product target:
  10-case outer retrieval <= 31.548 s
  # 相对当前 L1-heavy 63.097 s 至少 2x；不代表 all-turn online latency

evaluation reuse regression ceiling:
  same-lease exact reuse <= 80.000 s
  build_calls = 0

resource guard:
  hidden provider calls = 0
  peak RSS/storage increase <= 25%, unless预冻结的 quality/throughput Pareto 明确接受
```

Lane B 性能比较至少使用 3 个 matched repeated blocks，报告中位数、范围/CI、case 分布和 service state；现有
单次 EH02 结果只作 anchor，不伪装 replicate。Lane A 以 turn/task 为实验单位并报告连续任务内相关性，不把
每个 embedding/candidate 当 replicate。每个候选最多三次有实质差异的实现。

同一个 terminal result 必须分别保存 `online_lane`、`deep_lane`、`materialization_lane`，每个 lane 只允许：

```text
PASS_TARGET_MET
TERMINAL_TARGET_MISS
REVERTED_NO_EQUIVALENT_BENEFIT
PARKED_NOT_JUSTIFIED
```

`TERMINAL_TARGET_MISS` 不触发无限整改；若安全/功能等价、资源计划仍可执行，可以继续实验，但必须删除论文中的
性能优势 claim，并把真实瓶颈作为负面或系统限制报告。PD02 只生成一个 terminal performance result，不生成
attempt-by-attempt review/receipt 链。

## `DG12-EH04` Product/Harness Reconfirmation & Refreeze

若 PD02 保留了任何 product/eval execution bytes，则必须：

```text
rebuild retained Runtime/Client/MCP/OpenWorker wheels
→ fresh exact-role PostgreSQL + non-repo clean install
→ OpenWorker → relay/UDS → broker → MCP → Runtime product E2E
→ deterministic Task Binding/Registry/generation + continuous TaskMemoryState + NONE/CACHE/L0/L1 route propagation
→ CurrentStateRead + slot coverage/invalidation + explicit L1 fallback
→ Top-K/context/Scope/OpenIssue/revoke/watermark equivalence
→ product online/deep/cold performance reconfirmation
→ thin harness identity/resource-plan refreeze
→ DG11 rollback fresh-install smoke
```

EH04 生成一个新的 immutable manifest set，并明确 supersede EH03 的哪些 execution identities；不得覆盖 EH03，也
不得产生 candidate.1/candidate.2 链。若 PD02 没有保留任何字节变化，则状态为
`SKIPPED_NO_RETAINED_CHANGE`，直接复用 EH03 digest。只有 `EH04 = PASS` 或上述合法 skip 后，ND02/PE00 才能
使用最终 execution identity。

---

# 9A. Skill-assisted 实验创新发现

本节把已安装 Skill 映射为少量、可触发、可停止的工作方法。它们协助发现和验证，不增加新的审批层。

## 9A.1 选择的 Skill 与精确用途

| Skill | Trigger / 工作包 | 只允许产生的作用 | 停止条件 |
| --- | --- | --- | --- |
| `system-profile` | 已完成的 `BHE00/EH02`、当前 `PD02` | 选择 CPU、wall、I/O、memory、process/GPU 等 profiler；将通用指标沉淀到本体 observability | online/deep/cold 各有可复算 route/stage 归因，deep/cold wall time ≥95% 可解释 |
| `hypothesis-generation` | `ND00/ND01` | 将已观察结果拆成 observation、候选机制、rival、prediction、falsifier、negative control | 候选达到 test-ready，不能自动选 winner |
| `scientific-critical-thinking` | `ND00/ND04/PE11` | 检查泄漏、混杂、伪重复、measurement bias、claim 越界和替代解释 | 输出一次结构化 concern 列表；不衍生 review 版本 |
| `experimental-design` | `ND02/ND03/PE00` | 设计 paired/block/counterbalanced/factorial 实验，冻结 seed 与 run order | treatment、unit、block、replicate、analysis 全部可解释 |
| `experiment-plan` | `ND05/PE00` | 将最多两个 paper claim 映射到最多五个 main-paper experiment blocks 和真实 run order | must-run、nice-to-have、预算、失败解释已冻结 |
| `evaluating-llms-harness` | 可选 model-control calibration | 在需要排除 answer-model 本体漂移时，用冻结 vLLM backend 跑标准 LLM task | 只报告模型 calibration；不得替代 MiLAi/MCP benchmark |
| `ablation-planner` | `ND03/PE09`，仅初步 signal 后 | 使用 component/remove/replace/sensitivity 表，写清 `what_it_tests` 与预期方向 | 能区分 focal 与 rival；不做无界 sweep |
| `statistical-analysis` | `PE00/PE10` | 预选 paired test、assumption、CI、effect size、multiplicity 和 sensitivity | 预注册分析与 exploratory 分析分开 |
| `analyze-results` | 每个 terminal run、`PE10/PE11` | 固定按 observation→interpretation→implication→next test 汇总 raw table 和相对 baseline delta | 一个 run 只产生一个 terminal interpretation |
| `novelty-check` | `ND04`，仅经验 signal 后一次 | 搜索方法机制与经验 finding 的 recent/historical prior work，记录 closest work 和 search boundary | 最多一份合并查新；不得从“未命中”推出 novel |
| `academic-plotting` | `PE10/PE12` | 仅用 matplotlib/seaborn 从冻结 CSV/JSON 生成可复算 PDF+300 DPI PNG | 图、数据、脚本一一对应；不使用外部 Gemini |

项目适配覆盖 Skill 的通用默认值：

- `ablation-planner` 和 `novelty-check` 的默认 secondary reviewer 步骤禁用；开发期不自动 spawn agent；
- `result-to-claim`、`auto-review-loop`、`peer-review` 不进入开发主链；其高频 reviewer 路由与本 Goal 的
  review budget 冲突；
- `academic-plotting` 只采用数值图工作流，不发送未公开方法、数据或结果到外部图像 API；
- `evaluating-llms-harness` 只能校准 answer model，不能证明 memory quality、MCP wire、Scope 或 revoke；
- `scikit-learn`、`fine-tuning-*`、`peft-*`、`trl-*`、`dspy` 等训练/优化 Skill 在当前 DG-12 Task Binding 路径
  全部禁用；安装了 Skill 不构成训练授权，§7A.2.6 successor gate 未满足时不得读取其训练工作流后启动实验；
- Skill 建议的通用 `refine-logs/`、timestamp latest-copy 和根 `MANIFEST.md` 不适用于本项目；统一使用 §17
  的单一闭集，防止重新产生报告碎片。

## 9A.2 创新候选对象与状态

创新发现对象必须保持分离：

```text
Observation
  measured pattern with provenance and uncertainty

Research Question
  bounded question about the pattern

Hypothesis Candidate
  one possible mechanism or relation

Rival / Bias Explanation
  alternative mechanism, leakage, measurement, selection, drift or chance

Discriminating Prediction
  focal and rival predict different observable outcomes

Experiment Result
  evidence bearing on candidates

Novelty Candidate
  empirically useful delta whose prior-work status is still unresolved

Paper Claim
  human-selected, search-bounded and formally tested statement
```

状态只允许：

```text
DRAFT_OBSERVATION
→ EVIDENCE_BOUNDED
→ TEST_READY_CANDIDATES
→ DEV_SIGNAL | NO_SIGNAL | INDETERMINATE
→ MECHANISM_DISTINGUISHED | MIXED_EXPLANATION
→ SEARCH_BOUNDED
→ PAPER_CANDIDATE | PARKED
→ FORMAL_SUPPORTED | FORMAL_MIXED | FORMAL_NOT_SUPPORTED
```

机器或 Skill 不得写 `PROVEN`、`TRUE`、`NOVEL` 或 `SELECTED_WINNER`。如果 formal test 后才发现新模式，
该模式只能标记 `POST_HOC_EXPLORATORY`，进入 DG-13 的新数据/新 split，不能反写成本次预注册创新。

## 9A.3 发现轴，不是预设 claim

下面只定义可探测方向，不预先声明创新：

- flat retrieval 与 canonical/branch/OpenIssue-aware memory 的质量—错误确定性差异；
- session、turn、adjacent-window 和 multi-resolution representation 的边界条件；
- temporal/aggregate deterministic operator 是否只在明确语义类型上产生收益；
- assistant-role、numeric/unit、preference update 和 conflict retention 的独立贡献；
- compact compiler 的 token 压缩是否保持 evidence coverage，而非只缩短 prompt；
- governed ingest、projection、retrieval 与 warm Agent invocation 的效率—正确性 Pareto；
- abstention、branch diversity 与 action-safe correctness 之间的可测 trade-off。

某个方向只有在实验区分了“机制收益”与“更多 token、更多 calls、更多 compute、benchmark 偶然性”后，才可
成为 novelty candidate。

## 9A.4 创新发现工作包

### `DG12-ND00` Observation Ledger

输入仅限 DG10/DG11 已冻结结果、DG12 stage profile、公开 DEV/smoke 和新 terminal run。输出：

```text
var/dg12/discovery/observations.jsonl
var/dg12/discovery/failure-slices.csv
```

每项至少记录 source/run/case、unit、metric、uncertainty、是否预期、已知 preprocessing 和潜在混杂。一次
最多保持 3 个 active observation family；其余进入 backlog，避免“看到一个异常就开一条研究线”。

### `DG12-ND01` Rival Hypothesis Registry

对每个 active observation 使用 `hypothesis-generation` 的本地模板形成 focal、至少一个 rival 和
`UNKNOWN_OR_MIXED` 路径。输出：

```text
var/dg12/discovery/hypothesis-registry.json
var/dg12/discovery/prediction-rival-matrix.csv
var/dg12/discovery/falsification-controls.json
```

每个候选必须写明 mechanism、boundary、observable、falsifier、negative/procedural control、indeterminate
outcome 和下一最小实验。没有区分性预测的候选直接 `PARKED_NOT_TESTABLE`。

当前 ND01 必须把性能问题作为一个 observation family 收敛，而不是先选定“embedding cache”或“projection
paging”为答案：

| 路径 | 必须同时保留的 rival | 区分实验 |
| --- | --- | --- |
| online task continuity | current question 被当 active goal、task/goal/Scope 正常切换、slot identity 错误 | continuous OpenWorker shadow trace + explicit switch controls |
| state addressability | canonical key 已存在但未定位、writer 只形成 session archive、Need label 错误 | independent need→key annotation + exact canonical existence check |
| route execution | Host Router 未传播、Runtime policy override、L0 state unavailable、trace 误记 | requested/validated/attempted/terminal route matrix |
| CACHE | snapshot stale、policy mismatch、Need coverage miss、新相关事实未进入 dependency set | truth/coverage/frontier 三因素 negative controls |
| L1 escalation | FTS 已充分、vector 才补足、reranker 才区分、early-stop 造成 completeness loss | query-type-specific progressive shadow ablation |
| cold materialization | lifecycle 固定成本、governance round-trip、embedding compute、scalar write/index、worker orchestration | `M0～M4` |
| durable reuse | exact workload-only、partial-content duplicate、fresh-DB restore、真正产品 restart/replica use case | duplicate analysis + conditional `M5` |
| deep recovery | recent-canonical SQL、FTS、reranker、MCP/adapter outer overhead | payload-free nested span + one-stage-at-a-time replacement |

ND01 terminal 必须冻结每个 rival 的预期 stage delta、若 focal 成立时的观测、若 rival 成立时的观测和无法区分时
的状态，同时登记 §PD02 的 fast-path hard gates、待 FP0 后冻结的 confirmation threshold、5x cold、2x deep-L1
与资源 guard。此步骤不改 Runtime、不跑正式 paper labels、不调用 answer/judge，也不启动 AI 审计；完成后直接
进入 PD02，严格先执行 online lane，再执行 deep/materialization lane。

### `DG12-ND02` Mechanism Screening

在 disjoint DEV/synthetic 上先做低成本 screening：

1. retrieval/context-only，确认被测组件真的改变预期中介量；
2. 再对最小 case slice 做 answer-model 调用；
3. case 是实验单位；turn、embedding item、native request 只是嵌套测量，不能扩充 `n`；
4. benchmark/category/history length 作为 block，method order 使用冻结 counterbalance；
5. ≤4 个二元因素可用 full factorial；5～8 个因素只能用可解释的 Resolution IV/V fractional design；
6. 禁止用 Resolution III 的 alias 结果形成机制 claim；禁止无边界 OFAT sweep。

输出一个 seeded `screening-design.csv` 和一个 terminal result，不生成 reviewer 文档。

### `DG12-ND03` Discriminating Ablations

只有 `DEV_SIGNAL` 候选进入。采用 `ablation-planner` 的结构，但由本地执行者和用户批准，不启动审阅代理：

```text
remove component
replace with strongest simple alternative
negative-control perturbation
targeted 2×2 interaction when a named interaction hypothesis exists
bounded sensitivity curve only for decision-relevant parameter
```

同时 active 的高成本消融最多 3 个。优先 config-only；每个消融必须写 `what_it_tests`、
`expected_if_focal`、`expected_if_rival`、cost 和 terminal decision。三次有界尝试后仍不区分则 `PARKED`。

### `DG12-ND04` Empirical Novelty Gate

进入查新前必须同时满足：

- 至少两个独立 slice 方向一致，或一个专门 slice 加一次独立 replication；
- focal 与至少一个 rival 出现可区分结果，control 未失败；
- effect size/CI 与 raw case 分布可见，不以单一均值晋级；
- 收益不只来自更多 visible tokens、answer calls 或未计费 compute；
- Scope/OpenIssue/revoke/canonical safety 零回退；
- 质量—token—latency—storage 至少处于可解释 Pareto 区域。

满足后才执行一次合并 `novelty-check`：将最多 1 个主候选和 1 个支持候选转成不含 secret/raw 未公开
样本的技术描述，检索近期与历史 prior work，记录查询、日期、数据库、筛选边界、closest work、重叠机制
和差异。输出：

```text
var/dg12/discovery/novelty-search-boundary.json
var/dg12/discovery/prior-work-ledger.csv
var/dg12/discovery/novelty-assessment.md
```

允许结论是 `NOT_LOCATED_WITHIN_DOCUMENTED_BOUNDARY`、`OVERLAPS_PRIOR_WORK` 或
`EMPIRICAL_FINDING_MAY_BE_DISTINCT`；禁止自动给出 universal novelty 或 SOTA。

### `DG12-ND05` Paper Thesis Handoff

由人类 owner 从实验和 prior work 中选择最多：

```text
1 primary claim
+
1 supporting claim
```

并明确类型：

```text
METHOD CONTRIBUTION
SYSTEMS CONTRIBUTION
EMPIRICAL FINDING
NEGATIVE / BOUNDARY FINDING
```

`experiment-plan` 将其压缩为最多 5 个 main-paper experiment block；其余为 appendix 或 cut。每个 block
必须包含 claim、dataset/split、strong baseline、metric、success criterion、failure interpretation、成本和目标
table/figure。该 handoff 通过后 `PE00` 才能冻结 paper protocol。若没有可信创新候选，仍可继续完成严谨的
characterization/negative-results 包，但不得包装为方法创新。

---

# 10. 快速路径等价性与安全门

在正式输入打开前，同一无标签 smoke 必须同时通过：

| 检查 | 要求 |
| --- | --- |
| Canonical | Evidence/Proposal/Decision/Claim/OpenIssue 数量、identity、lineage 相同 |
| Projection | fragment kind/order/text hash 相同；向量在冻结 tolerance 内一致 |
| Watermark | 无 gap、无跨 cohort delivery，最终位置相同 |
| Retrieval | Top-K source ID、顺序、matched_by、reject reason 相同 |
| Context | rendered context hash、token、omitted IDs 相同 |
| MCP | typed status、trace、degraded/abstention 相同 |
| Task | current utterance 不改写 active goal；task/goal/Scope switch 显式 rebind/invalidate |
| Route | requested、validated、attempted、terminal 和 fallback 完整；无静默 L0→L1 |
| L0 | exact/current read 来自同一 canonical snapshot，不依赖 FTS/vector/reranker |
| Cache | truth token、policy、Need coverage、dependency frontier 全部验证；不可判断即 miss |
| Fast safety | ACTION_SAFE false-fast、stale-cache authorization、wrong-scope fast hit 均为 0 |
| OpenIssue | issue ID、branch、revision、discharge preservation 相同 |
| Revoke | stale FTS/vector/cache 不得重新进入 context |
| Scope | wrong-scope sentinel 全部拒绝 |
| Calls | answer/judge/hidden provider call 与预注册值相同 |
| Failure | denominator、retry identity、terminal class 相同 |
| Isolation | 前一 cohort 的 row、bytes、projection、cache 不可观察 |

任何输出差异不能因为“新答案更好”而被接受。质量改变意味着它是新的方法/candidate，必须走独立 DEV、
freeze 和正式 arm，而不是被叫作等价加速。

---

# 11. 论文方法与 Baseline 矩阵

## 11.1 Controlled Backbone Track

所有方法使用同一个 Qwen answer model、同一 prompt contract、同一 memory token budget、同一问题顺序、
同一最大 answer calls：

| Method ID | 类型 | 用途 |
| --- | --- | --- |
| `CTRL-NONE` | 无记忆 | 测量任务本身和模型先验 |
| `CTRL-FULL` | 完整历史 | context 可容纳时的 characterization |
| `CTRL-TRUNC-FULL` | 确定性截断历史 | 长上下文上限对照 |
| `CTRL-CUSTOM-LEX1` | 历史自定义 lexical Top-1 | 仅历史连续性，不称官方 baseline |
| `LME-BM25-S` | 官方/复现 session BM25 | 稀疏检索 baseline |
| `LME-BM25-T` | 官方/复现 turn BM25 | 细粒度稀疏检索 baseline |
| `LME-DENSE` | 冻结 dense retrieval | 向量 baseline |
| `DG10-FROZEN` | 前代 MiLAi | 产品代际对照 |
| `DG11-FULL` | 当前 frozen MiLAi | 功能候选主 arm |
| `DG12-BATCH` | 等价 batch candidate | 只在 §10 通过时用于效率 arm |
| `LME-ORACLE` | gold/evidence upper bound | 上限，不参加普通 win/loss |

`evaluation-fast` 不是一个新质量方法 ID；若其 context 与 `DG11-FULL` 完全相同，只是执行引擎不同。

## 11.2 Native Open-Source Track

| 方法 | 本地项目 | 比较用途 |
| --- | --- | --- |
| `MEM0-OSS` | `/cra/memory/mx_memory/mem0` | 抽取式长期记忆与检索 |
| `HINDSIGHT-OSS` | `/cra/memory/mx_memory/hindsight` | retain/recall/reflect 原生路径 |
| `GRAPHITI-OSS` | `/cra/memory/mx_memory/graphiti` | temporal graph retrieval |
| `REME-OSS` | `/cra/memory/mx_memory/ReMe` | Agent memory/retrieval 原生配置 |
| `OPENVIKING-URI` | `NOT_INSTALLED / PE00 PRE-FREEZE` | 已知 URI 的 direct read + Abstract/Overview 分级加载 |
| `OPENVIKING-FIND` | `NOT_INSTALLED / PE00 PRE-FREEZE` | 单 query semantic retrieval；不冒充 MiLAi L0 exact read |
| `OPENVIKING-CONTEXT` | `NOT_INSTALLED / PE00 PRE-FREEZE` | 完整 context/search assembly，显式冻结 dedup 与 intent 配置 |

要求：

- 固定 commit/package、依赖、许可证、prompt 和 config；
- 使用推荐可运行开源配置；
- 所有内部 LLM/embedding/retrieval calls 和 tokens 计费；
- 不能因分数低而事后排除；
- 技术排除必须在正式分数前冻结理由；
- Native Track 与 Controlled Track 分表，不能直接作同协议显著性结论。

### 11.2.1 OpenViking 三档 baseline 与公平边界

OpenViking 当前仅完成文档级调研，本地 checkout、commit、依赖和可运行配置均未冻结；因此本表是 PE00 inclusion
候选，不是“已安装/已跑”。PE00 必须先生成 `var/dg12/baselines/openviking/source-manifest.json`，绑定 repository
URL、commit、package lock、license、embedding/LLM/reranker identity、async readiness 条件和 hardware。若无法在
资源 ceiling 内完成推荐开源配置，必须在任何正式 score 可见前标为 `EXCLUDED_TECHNICAL`。

三档不能合并：

```text
OV-URI
  known viking:// address
  → read / abstract / overview

OV-FIND
  one user query
  → query embedding + semantic candidate path
  → no intent-LLM expansion unless pinned implementation requires and records it

OV-CONTEXT
  session/task context
  → full search/context assembly
  → explicit intent, rerank, budget and dedup_turns config
```

MiLAi 匹配档位：

```text
MiLAi-CACHE       validated slot + Need coverage
MiLAi-L0          StateKeyRef → exact CurrentStateRead
MiLAi-L1-PROG     exact/FTS → vector → reranker progressive escalation
MiLAi-L1-FULL     frozen monolithic deep-recovery characterization
```

正式报告分成两张不能互相替代的表：

1. **Shared Context Access**：相同 answer model、history/query、memory token budget、hardware、warm/cold state 和
   answer-call ceiling，比较 task quality、prompt/context tokens、E2E/first-byte latency、internal LLM/embedding/
   reranker calls、跨轮重复 body 和 storage；OpenViking async extraction/indexing 必须等到冻结 readiness 条件，
   不能把未完成后台任务的 miss 与 MiLAi ready state 比较；
2. **Governed State Behavior**：MiLAi 单独报告 currentness、OpenIssue、revoke、Scope/authority、false certainty、
   stale-cache 与 ACTION_SAFE。OpenViking 只有在原生 API 明确提供等价语义时才进入对应 cell；否则写
   `NOT_SAME_CONTRACT`，不能把缺少该合同写成其安全失败，也不能用普通 retrieval quality 代替 MiLAi correctness。

OpenViking baseline 只在隔离 Evaluation Plane 运行：无 MiLAi Runtime/broker socket、token、DSN 或 canonical write
credential，不进入 OpenWorker 正式 route，不成为 MiLAi package dependency。其最优结果不得反向选择 MiLAi
formal threshold；MiLAi 对 OpenViking 风格设计的内部消融与原生 OpenViking 系统比较必须分开标识。

## 11.3 Benchmark-native 方法

- LongMemEval official BM25/dense/full/oracle；
- LongMemEval-V2 official RAG 与 AgentRunbook/controller；
- BEAM official dense RAG；LIGHT 仅在预注册资源上限内运行；
- Memora official metric/protocol；
- Horizon/CUPID 官方输入与 scorer；
- BFCL 只测模型工具选择/参数/no-call/多轮语义，不证明 MCP wire。

## 11.4 Inclusion Freeze

在任何正式 answer score 可见前生成 `method-inclusion.json`：

```text
INCLUDED
EXCLUDED_TECHNICAL
EXCLUDED_LICENSE
EXCLUDED_RESOURCE_CEILING
CHARACTERIZATION_ONLY
UPPER_BOUND_ONLY
```

每项都绑定理由和证据。不得使用 `EXCLUDED_LOW_SCORE`。

---

# 12. Benchmark 组合与正式实验

## `DG12-PE00` Claim、阈值与 Protocol v2

输入为 `ND05` 的 paper thesis handoff。使用 `experimental-design`、`experiment-plan` 和
`statistical-analysis` 在看正式结果前冻结：

```text
claim → benchmark → method → metric → threshold → statistic → allowed wording
```

同时冻结：实验单位、block/strata、paired structure、method counterbalance、seed、exclusion、missing/failure、
multiplicity、CI/effect-size、formal/exploratory 边界。正式标签或 aggregate score 打开后不再修改。

## `DG12-PE01` Harness 与 Baseline Reconfirmation

使用新 frozen harness 重新做无标签 smoke；确认旧 PE01～08 smoke 只是 reference，不自动成为 protocol v2
正式证据。

## `DG12-PE02` LongMemEval

核心：

```text
LME-PAPER-HOLDOUT-100        held-out generalization
LME-FULL-500-CHARACTERIZATION
```

先一次性生成所有 method contexts，再按 frozen Latin-square schedule 调用 answer model。100-case paper
partition 的结果不能反向修改 candidate；full-500 characterization 与 held-out 表分开。

## `DG12-PE03` Memora

预注册 60 question、三 persona/period strata。报告：

```text
FAMA
Remembering / Reasoning / Recommending
forget/update behavior
answer/judge calls
build/query/token/storage cost
```

同 answer model 自评只作 characterization；主要 judge 使用已冻结的独立本地 evaluator 和 deterministic
criteria。

## `DG12-PE04` LongMemEval-V2

先验证 modality contract：question image、accessibility tree、screenshot、trajectory 顺序均不得静默丢失。
如果只能做 text-only slice，必须标记 `ADAPTED_PROTOCOL`，不能称 official full score。

## `DG12-PE05` BEAM 128K

正式输入：20 个 history、400 questions。每个 history 只 build 一次。报告长上下文质量、build cost、warm
query、存储和失败分布。500K/1M 只有在 128K 质量与资源满足后进入；10M 不阻断核心结果包。

## `DG12-PE06` HorizonBench

正式 120 cases，按 model source × static/evolved 分层。重点测长期偏好是否随反馈演化，报告每类质量、
context source 和 retrieval failure taxonomy。

## `DG12-PE07` CUPID

正式 90 cases，consistent/contrastive/changing 各 30。重点测偏好冲突、变更与错误确定性。

## `DG12-PE08` Agent/MCP/Serving

重放：

```text
F0 / F1
T2
Hardened S1–S10
20 paired Agent tasks
OpenWorker → relay/UDS → broker → MCP → Runtime
OpenWorker reader-lite / explicit submitter handoff / operator isolation
revoke / OpenIssue / cache / wrong-scope adversary
optional Generic direct-client / LangGraph / AutoGen portability smoke
```

OpenWorker 继续使用 host-owned `memory_mode`，不恢复用户文本 marker 路由。普通 Worker 只获得 reader-lite
UDS capability；submitter 使用独立 profile/lane；Worker root 不等于 host、broker 或 Runtime authority。

Serving 分层：

```text
T0 raw vLLM
T1 OpenWorker → Gateway → vLLM, no memory
T2 OpenWorker + MiLAi integration loaded, host-owned memory_mode=NONE
T3 memory path OpenWorker → MCP → Runtime; answer path OpenWorker → Gateway → vLLM
```

报告 gateway、Agent integration、memory control 和有效 memory E2E overhead。

`PE08=FUNCTIONAL_AND_SAFETY_PASS` 至少要求 F0/F1、T2、Hardened S1–S10、paired Agent tasks、wrong-scope、
revoke、OpenIssue、CACHE 与 delayed-result task binding 全部无 blocking failure，且完整 Provider/route denominator
可复算。PE08 PASS 本身只解除 §7A.2.6 的一个前置条件，不自动授权训练；还必须有一个 core memory benchmark
完整 terminal、deterministic residual materially limiting 和 successor Goal/new disjoint data plan。

## `DG12-PE09` 消融

执行 §13 和 `ND03` 晋级的预注册消融，不进行无界组合搜索。`ablation-planner` 只提供本地结构；不启动
secondary reviewer。formal 消融只回答已冻结机制问题，不能用 test 结果发明新参数组合。

## `DG12-PE10` 统计与 Failure Taxonomy

只分析，不改代码。使用 `statistical-analysis` 执行预注册 paired analysis、assumption/diagnostic、CI、effect
size、multiplicity 和 sensitivity；使用 `analyze-results` 输出 raw table 以及
observation→interpretation→implication→next-test。报告类别、长度、调用、token、延迟、存储和失败矩阵。
不得把 turn、embedding 或 provider call 当成独立 case 增大样本量，也不得用 post-hoc observed power 美化
阴性结果。

## `DG12-PE11` 结果驱动反思

把 formal result 映射回 `ND01` candidate/rival/falsifier，区分：

```text
claim supported within frozen scope
mixed or boundary-dependent
mechanism not distinguished
claim not supported
post-hoc exploratory observation
```

使用 `scientific-critical-thinking` 检查 leakage、confound、measurement、selection、pseudoreplication 和 claim
scope；使用 `analyze-results` 生成 KEEP/REVERT/REDESIGN/PARK 决策和下一 Goal proposal。不修改本次
evaluated candidate；任何新假设进入 DG-13 新 split，不在本次数据上自证。

## `DG12-PE12` 最终结果包

只生成一次 final package。`academic-plotting` 仅从冻结的 CSV/JSON 生成可复算数据图：主结果、分层结果、
消融、质量—token—latency—storage Pareto 和 failure taxonomy；每图保留脚本、PDF 与 300 DPI PNG。必要时
进行一次只读独立 review。

---

# 13. 消融设计

## 13.1 质量消融

```text
DG11-FULL
- vector
- FTS
- reranker
- temporal operator
- aggregate operator
- recency channel
- turn windows
- multi-session set coverage
- assistant-role retention
- numeric/unit preservation
- compact compiler
```

每个消融使用同 answer model、同 token ceiling 和同 case order。先一因素；只有明确交互假设才做有限 2×2。

## 13.2 治理反事实

这些不是可发布产品配置，只测安全机制贡献：

```text
- Canonical Gate
- OpenIssue preservation
- revoke stale rejection
- Scope/authority binding
- validated cache binding
- branch diversity
```

反事实结果必须标记 `UNSAFE_ABLATION`，不能作为更快的产品方案。

## 13.3 效率消融

```text
current-question-as-task vs Host-task-ID-only vs deterministic execution anchors vs lexicographic Task Binding
strict stack vs Registry/Graph + per-lane active binding
completion-time tool-result binding vs invocation-time binding
router-output-only vs fully propagated route contract
L1-default vs CurrentStateRead L0
snapshot-only cache vs truth+NeedCoverage+dependency validation
search-first vs StateKeyRef address-first
MemorySlotCoverage only vs Coverage + independent ExposureLedger
always resend context body vs validated identical-body exposure dedup
full evidence body vs ABSTRACT→OVERVIEW→EVIDENCE_DETAIL progressive load
monolithic L1 vs FTS→vector→reranker progressive escalation
cold synchronous derived projection vs async derived plane at identical readiness
cold per-case deployment
pre-migrated database only
persistent API/Worker only
persistent MCP only
model prewarm only
history reuse only
batch embedding only
content-addressed cache only
Evaluation Lease=1 vs Lease=2
reranker pool and thread settings
```

本 Goal 的 Task Binding 消融不包含 LightGBM、XGBoost、Qwen classifier、fine-tuning 或 learned-router arm。
Oracle Task Relation 只能在端到端结果后的离线 headroom 分析中使用 Host execution graph/人工 ambiguous label，
不得读取 gold memory answer、retrieved Claim 或未来 turn，也不得反向修改 DG-12 candidate。

## 13.4 参数曲线

只在 DEV/smoke 上冻结少量曲线：

```text
memory token budget
candidate pool size
final top-k
batch size
Slot count
reranker on/off and pool size
progressive L1 sufficiency threshold/config identity
```

正式 test 只使用一个预注册配置，不在 test 上择优。

## 13.5 创新候选的最小消融证据

每个准备写入主论文的机制候选至少需要：

| 对照 | 回答的问题 |
| --- | --- |
| full candidate | 联合系统实际达到什么结果 |
| remove focal component | 该组件是否必要 |
| strongest simple replacement | 收益是否来自一个更简单的已知替代 |
| cost/token/call-matched control | 收益是否只是更多资源 |
| negative-control slice | 该机制是否只在其预测适用的类别上起效 |

如果 focal 与 replacement 相同，结论优先是“实现选择”而不是“新机制”。如果 removal 改变所有类别而非预测
类别，优先检查 prompt length、coverage 或系统性 confound。只有存在明确交互假设时才增加一个 2×2；不为
图表完整性遍历全部组合。

---

# 14. Provider、Token、Judge 与 Review

## 14.1 Answer Provider

唯一正式 answer provider：

```text
self-hosted vLLM 0.27.1
Qwen3.6-35B-A3B-FP8
temperature = 0
top_p = 1
thinking = false
strict answer contract
```

固定 weights digest、model config、vLLM image/build、tokenizer、chat template、prompt 和 served context length。
DG-12 不训练、微调、蒸馏或合并 answer model，也不在不同 method 间更换模型或偷偷增加 answer calls。

## 14.2 Token Truth

三层口径：

```text
vLLM native usage
  = accounting truth

exact tokenizer recount of final serialized prompt
  = deterministic verification

system/tool/query/memory/result attribution
  = component decomposition
```

pre-count 必须针对最终 chat template、tool serialization 和 special tokens 后的 prompt，而不是原始 messages。

## 14.3 Provider Calls

必须区分：

```text
ingest extraction
reflection/consolidation
embedding logical item
embedding inference batch
reranker
memory query model
answer
judge
retry/failure
```

每个 logical request 绑定 native request ID；hidden call 为 0。失败和 retry 保留在 denominator。

## 14.4 Judge

优先级：

```text
Tier 1 deterministic exact/F1/evidence/retrieval/safety metrics
Tier 2 frozen independent local evaluator or blinded human subset
Tier 3 same-answer-model judge, characterization only
```

同一个 vLLM answer model 不能成为唯一 release-blocking judge。外部 cloud judge 不进入本 Goal。

## 14.5 Codex 最终 Review

若最终 claim/evidence 风险需要独立审阅，使用一次 `gpt-5.6-sol`。官方 OpenAI model catalog 将其列为
复杂推理与编码的旗舰模型，并支持 `xhigh` reasoning；实际调用前仍需记录本机 Codex 版本、账户可用性和
resolved model identity。不可用时停止并报告，不能静默替换模型。

只允许在 materialized frozen review workspace 中执行：

```text
review/<bundle-sha>/
├─ claim-matrix
├─ frozen protocol/config
├─ selected source/tests
├─ raw result summaries and hashes
├─ statistics
└─ explicit review prompt/schema
```

Workspace 必须：

```text
read-only
no .git
no .env
no raw private content
no Runtime/MCP/broker socket
no candidate write permission
```

命令形态在本机 `codex exec --help` 验证后冻结，例如：

```text
codex exec
  --model gpt-5.6-sol
  --sandbox read-only
  --ephemeral
  --cd <materialized-review-workspace>
  --output-schema <review-result-schema.json>
```

Review 只做 claim-to-evidence 对抗核对；不生成样本、不评分答案、不改候选、不关闭 finding、不成为最终
authority。Finding 通过确定性重现裁决；不启动第二次 AI re-review。

官方模型参考：<https://developers.openai.com/api/docs/models>

---

# 15. 公平性与统计合同

## 15.1 同协议比较

Controlled Track 固定：

```text
same case and history
same answer model and prompt
same memory token ceiling
same tool/answer call ceiling
same scorer
same service-state policy
same scheduling seed
```

Native Track 保留方法真实配置并全量计费，单独报告。

## 15.2 顺序

每个 case 的 method 顺序按冻结 cyclic Latin square 或适用的 balanced/Williams schedule counterbalance。
三方法示意：

```text
group A: A → B → C
group B: B → C → A
group C: C → A → B
```

真实方法数为 `M` 时必须生成并冻结完整 seeded schedule，保证每个方法在 period/position 上尽量平衡；不能
把上面的三行示意硬套到 `M > 3`。benchmark、category、history-length bucket 和 service window 是预声明
block；记录 GPU queue、并发、重试和 shared/exclusive service window。

## 15.3 Threshold Freeze

打开正式 labels/aggregate score 前冻结 machine-readable `thresholds.yaml`。至少包含：

```text
primary quality metric and minimum meaningful delta
paired CI rule
category safety floors
maximum safety failures = 0
token/call/resource ceilings
harness equivalence requirements
```

数值来自 DEV、资源和论文问题，而不是 test 结果。

## 15.4 统计输出

- paired per-case delta；
- bootstrap 95% CI；
- effect size；
- wins/losses/ties；
- 按 category、history length、memory type 分层；
- 多个随机 seed 仅用于非确定性方法；
- task quality—token—latency—storage Pareto；
- 所有 preregistered case，包括 infrastructure failure。

`p < 0.05` 不能代替工程意义；也不能只报告总体均值隐藏类别回退。

## 15.5 实验单位、重复与探索边界

```text
primary experimental unit = benchmark case / independent agent task
paired observation         = same unit under frozen methods
block                      = benchmark/category/history-length/service window
technical measurement      = turn/fragment/embedding/native request/token sample
```

技术测量可以解释机制和成本，但不能作为独立 replicate 扩大质量检验的 `n`。确定性 answer arm 每 case 只回答
一次；非确定性 native method 才按预注册 seed 重复，并用 hierarchical/cluster-aware 分析保留嵌套结构。
screening/DEV 产生的假设标记 exploratory；只有在 untouched formal split 上按 frozen plan 测试的 claim 才是
confirmatory。多个 benchmark 支持 transport，不把同一 case 的多个 metric 当成多次独立复制。

---

# 16. 结果驱动开发循环

## 16.1 正式 freeze 前

只使用已打开 DEV、synthetic 和 disjoint smoke：

```text
observe one failure family
→ write one falsifiable hypothesis
→ implement one bounded change
→ run retrieval/context first
→ run minimum answer DEV only if retrieval changed as expected
→ compare quality + safety + efficiency
→ KEEP or REVERT
```

一次只改变一个主要机制。任何收益必须跨至少两个 slice，或对一个预注册专门 slice 有显著、可解释收益。

## 16.2 正式 freeze 后

```text
candidate/protocol/config/scorer/threshold frozen
→ run formal experiments once
→ analyze once
→ no code/config change to same evaluated candidate
```

## 16.3 正式结果后的反思

每个主要失败映射到：

```text
retrieval miss
ranking miss
context compilation loss
temporal/update error
OpenIssue/safety abstention
answer-model failure
benchmark ambiguity
infrastructure failure
```

然后给出：

```text
KEEP       evidence supports current design
REVERT     optimization has no cross-slice value
REDESIGN   architecture/algorithm needs new candidate
PARK       benefit smaller than cost or data insufficient
```

需要新质量算法时生成 DG-13 proposal 和新 DEV/holdout 计划，不在 DG-12 paper test 上继续调参。

Task Binding 同样遵守这一规则：端到端 benchmark 前不训练；benchmark 后只有在 deterministic residual 明确造成
task success/FastPath 损失时，PE11 才能记录 `CONSIDER_LEARNED_TASK_RESOLVER`。训练本身必须进入 successor Goal、
使用新的 disjoint data，并重新建立 candidate/protocol；不得把模型补丁塞回已评测的 DG-12 candidate。

## 16.4 实验发掘创新的闭环

```text
raw result / failure slice
→ freeze observation before interpretation
→ generate focal + rival + unknown/mixed
→ choose the cheapest discriminating experiment
→ measure mediator first, answer quality second
→ analyze paired effect + uncertainty + cost
→ KEEP / REVISE / REJECT hypothesis
→ only then search closest prior work
→ freeze at most 1 primary + 1 supporting claim
→ confirm once on untouched formal data
```

创新候选晋级需要“预测命中”和“rival 被区分”，不是某个数字变大。下列情况不能晋级：

- 增益仅来自更长 prompt、更多 answer/tool calls 或未计费内部模型；
- 只在生成假设的同一 case 上成立；
- 只报告 aggregate，预测类别没有更强效应；
- negative/procedural control 同样改善；
- safety correctness 下降换取 answer F1；
- closest prior work 已包含同机制与同主要证据；
- CI/样本分布无法区分有用效应与随机或 service drift。

若方法新颖性不成立但发现“治理约束在何种更新/冲突场景改善错误确定性”具有稳定、未被先前工作覆盖的
经验规律，可以转为 `EMPIRICAL_FINDING`；若只证明高效实现，则转为 `SYSTEMS CONTRIBUTION`。三者必须
分开写，不能用系统工程量替代算法创新。

---

# 17. Artifact 与产出收敛

## 17.1 目标目录

```text
var/dg12/
├─ current-state.json
├─ ledger.jsonl
├─ baselines/
│  └─ openviking/
│     ├─ source-manifest.json
│     ├─ method-config.yaml
│     ├─ feasibility.json
│     └─ comparison.json
├─ runs/<run-id>/
├─ product/
│  ├─ core-refactor-matrix.json
│  ├─ package-dependency-graph.json
│  ├─ legacy-source-locks.json
│  ├─ legacy-identity-compatibility.yaml
│  ├─ public-api-contract.json
│  ├─ core-baseline-e2e.json
│  ├─ optimized-product-e2e.json
│  └─ performance-refreeze.json
├─ harness/
│  ├─ product-vs-harness-ab.json
│  ├─ reusable-infrastructure.json
│  └─ freeze/
│     ├─ product-package-manifest.json
│     ├─ public-api-contract.json
│     ├─ harness-manifest.json
│     ├─ evaluation-resource-config.yaml
│     ├─ equivalence-summary.json
│     └─ resource-plan.json
├─ performance/
│  ├─ fast-path-workloads.yaml
│  ├─ fast-path-dev-labels.jsonl
│  ├─ fast-path-confirmation-seal.json
│  ├─ fast-path-acceptance.yaml
│  ├─ fast-path-profile.json
│  ├─ materialization-decomposition.json
│  ├─ deep-recovery-profile.json
│  ├─ reuse-duplicate-analysis.json
│  └─ optimization-terminal.json
├─ discovery/
│  ├─ observations.jsonl
│  ├─ failure-slices.csv
│  ├─ hypothesis-registry.json
│  ├─ prediction-rival-matrix.csv
│  ├─ falsification-controls.json
│  ├─ screening-design.csv
│  ├─ novelty-search-boundary.json
│  ├─ prior-work-ledger.csv
│  └─ novelty-assessment.md
├─ freeze/
│  ├─ protocol.yaml
│  ├─ claim-matrix.yaml
│  ├─ thresholds.yaml
│  ├─ method-configs/
│  └─ harness-manifest.json
├─ figures/
│  ├─ data/
│  ├─ scripts/
│  ├─ pdf/
│  └─ png/
└─ final/
   ├─ final-report.json
   ├─ statistics.json
   ├─ limitations.md
   ├─ reproduction.md
   └─ result-package.tar.gz
```

## 17.2 产出纪律

- 同一 run 只有一个目录；
- product artifacts 描述稳定能力和兼容性，不以 benchmark/case 作为代码 owner；
- `core-refactor-matrix.json` 是整理期唯一主矩阵；不得为每个被迁移文件另建报告；
- `materialization-decomposition.json` 汇总 M0～M5、matched repetitions 和 stage attribution；同一 cell 的失败
  与修复不再衍生多份总结文档；
- `optimization-terminal.json` 是 PD02 唯一结论，必须列出 retained/reverted/parked 代码和未达目标；
- EH04 若触发，只在现有 `harness/freeze/` 旁生成一个 content-addressed immutable successor set，并由
  `performance-refreeze.json` 指向；不得覆盖 EH03 或生成多层 latest-copy；
- 失败写入 run terminal 和 ledger，不新增多份 failure-review Markdown；
- current-state 原子更新；
- observation append-only；hypothesis status 通过稳定 ID 更新，不能改写原 observation；
- raw generation、trace、usage 和 statistics 不混写；
- Skill 输出复用上述目录，不创建 `refine-logs/`、通用 `MANIFEST.md` 或 timestamp latest-copy；
- OpenViking 只使用一个 source manifest、一个 method config、一个 feasibility 和一个 comparison；每次运行的 raw
  trace 仍进入普通 `runs/<run-id>/`，不在 baseline 目录复制结果树；
- 每个 paper figure 必须绑定 frozen source data、生成脚本和图文件；
- final package 只生成一次；
- review record 若需要只生成一次；
- cache、临时数据库、模型文件和 `.env` 不进入 result package；
- archive scanner 必须解包递归检查 secret/cache/log/blob/backup。

---

# 18. 状态机与当前矩阵

## 18.1 Goal 状态机

```text
PROFILED_CORE_CONSOLIDATION_REQUIRED
→ CORE_INVENTORY_COMPLETE
→ CORE_NORMALIZED
→ CORE_BASELINE_E2E_PASS
→ PRODUCT_DEVELOPMENT
→ PRODUCT_DEVELOPMENT_TERMINAL
→ THIN_HARNESS_EQUIVALENT
→ DISCOVERY_OBSERVATIONS_READY
→ RIVAL_HYPOTHESES_FROZEN
→ ONLINE_FAST_PATH_CLOSURE
→ ONLINE_FAST_PATH_TERMINAL
→ DEEP_AND_MATERIALIZATION_CLOSURE
→ PRODUCT_HARNESS_REFROZEN | NO_RETAINED_PERFORMANCE_CHANGE
→ DISCOVERY_SCREENING
→ PAPER_CANDIDATES_FROZEN | NO_NOVELTY_CANDIDATE
→ PAPER_PROTOCOL_FROZEN
→ FORMAL_RUNNING
→ PAPER_RESULTS_FROZEN
→ ANALYSIS_COMPLETE
→ COMPLETE
```

质量结果分支：

```text
ANALYSIS_COMPLETE
├─ QUALITY_ADVANTAGE_SUPPORTED
├─ QUALITY_MIXED
└─ QUALITY_NOT_PROVEN
```

三者都可在实验完整时进入 `COMPLETE`。

## 18.2 当前工作包状态

| Work package | 当前状态 |
| --- | --- |
| `DG12-BHE00` | `PASS` |
| `DG12-BHE01` | `STOPPED_PRODUCT_BOUNDARY_VIOLATION` |
| `DG12-BHE02..08` | `SUPERSEDED_BY_CORE/PD/EH` |
| `DG12-PC00..07` | `SUPERSEDED_BY_CORE/PD` |
| `DG12-CORE00` | `PASS` |
| `DG12-CORE01` | `PASS` |
| `DG12-CORE02` | `PASS` |
| `DG12-PD00` | `PASS` |
| `DG12-PD01` | `PASS` |
| `DG12-EH00` | `PASS` |
| `DG12-EH01` | `PASS` |
| `DG12-EH02` | `PASS` |
| `DG12-EH03` | `PASS` |
| `DG12-ND00` | `PASS` |
| `DG12-ND01` | `PASS` |
| `DG12-PD02` | `TERMINAL_TARGET_MISS` |
| `DG12-EH04` | `PASS` |
| `DG12-ND02` | `PASS_DEV_SIGNAL` |
| `DG12-ND03` | `PASS_MECHANISM_DISTINGUISHED` |
| `DG12-ND04` | `PASS_METHOD_OVERLAP_EMPIRICAL_BOUNDARY_OPTION` |
| `DG12-ND05` | `PASS_SELECTED_BOUNDARY_PACKAGE` |
| `DG12-PE00` | `PASS_DOCUMENT_FREEZE_EXECUTION_GAPS_DISCOVERED_PE02` |
| `DG12-PE00V3` | `IN_PROGRESS_AUTHORIZED_PRE_LABEL_SUCCESSOR` |
| `DG12-PE01` | `PASS`；须对 v3 successor identity 重跑无标签 reconfirmation |
| `DG12-PE02` | `BLOCKED_PRE_LABEL_PROTOCOL_AND_HARNESS_GAPS` |
| `DG12-PE03..09` | `BLOCKED_BY_PE02` |
| `DG12-PE10..12` | `BLOCKED_BY_FORMAL_RESULTS` |

旧 PE smoke 仅为 `REFERENCE_AVAILABLE`，不自动成为 v3 正式证据。v2 freeze 与 PE02 blocked terminal 原样保留；
`freeze-v3/` 在 one-way manifest 写入前仍是 pre-label successor construction，不得仅凭目录存在宣称
`PAPER_PROTOCOL_V3_FROZEN`。本版只改变 v3 的物理执行并发和通用 harness 吞吐，不重开 PD02、EH04、ND02～05，
也不改变任何已封存结果。

---

# 19. 执行顺序与资源预算

## 19.1 主链

```text
DG12-BHE00 stage profile = PASS
→ CORE00 existing-code inventory = PASS
→ CORE01 product structure normalization = PASS
→ CORE02 normalized wheels + OpenWorker/MCP baseline E2E = PASS
→ PD00 generic product capabilities = PASS
→ PD01 retained wheels + optimized OpenWorker/MCP E2E = PASS
→ EH00 thin public-product adapter = PASS
→ EH01 reusable evaluation infrastructure = PASS
→ EH02 product/harness performance decomposition = PASS
→ EH03 harness freeze = PASS
→ ND00 observation ledger = PASS
→ ND01 rival hypotheses = PASS
→ PD02-A FP0 shadow baseline = PASS
→ PD02 deterministic fast path + deep/materialization work = TERMINAL_TARGET_MISS
→ EH04 product/harness equivalence = PASS
→ ND02/ND03 mechanism screening and discrimination = PASS
→ ND04 bounded novelty search = PASS_OVERLAP_WITH_EMPIRICAL_BOUNDARY_OPTION
→ ND05 paper thesis handoff = PASS
→ PE00 v2 document freeze = PASS_WITH_EXECUTION_GAPS_DISCOVERED
→ PE01 v2 no-label reconfirmation = PASS
→ PE02 pre-label audit = BLOCKED_WITH_ZERO_FORMAL_OUTPUT
→ PE00V3 successor protocol/harness + concurrency identity [CURRENT]
→ v3 PE01/PE02 no-label gates
→ PE02 LongMemEval formal execution once
→ PE03 Memora
→ PE04 LongMemEval-V2
→ PE05 BEAM
→ PE06 Horizon
→ PE07 CUPID
→ PE08 Agent/MCP/Serving
→ PE09 ablations
→ PE10 statistics
→ PE11 reflection [may propose successor learned resolver; no DG-12 training]
→ PE12 final package
```

Independent benchmark methods 必须在冻结配置后并行执行。旧的“同一 vLLM 最多 2 个请求”上限废止；当前
正式 operating point 为 8 个 provider requests，harness hard ceiling 为 16。正式 run 内 worker count 固定，
不同 method 不得使用不同 answer concurrency；answer 与 judge 使用分离 service window，不允许未经记录的共享负载。

## 19.2 每次 run 前资源计划

```text
case/history/question count
logical embedding items
embedding batches
answer/judge/internal calls
prompt/completion tokens
estimated wall time
storage
max workers/retries
cleanup plan
skill trigger and expected artifact, if any
```

资源不足时优先排队、分 shard 或降低尚未开始的整个 service window 并重新冻结资源 identity；不得删方法、缩小
已预注册 denominator，或在正式 run 中按分数/方法动态改变并发。

## 19.3 Provider 与 review 上限

| Lane | 正式 operating point | Hard ceiling | 隔离与用途 |
| --- | ---: | ---: | --- |
| stateless/local context | 8 threads | 16 | NONE/FULL/BM25/lexical/oracle 等无共享可变 Runtime 的 cell |
| stateful product context | 4 processes × 1 worker | 8 processes | 每进程独立 DB lease、env 与 checkpoint；禁止同进程并行迁移 |
| dense baseline | 2 processes | 2 | 分别绑定 `cuda:2`、`cuda:3`；不占 vLLM GPU0/1 |
| prompt/token build | 8 workers | 16 | 不调用 Provider，不打开 label |
| answer Provider | 8 requests | 16 | 固定 Latin-order rolling window；所有方法相同 |
| judge Provider | 8 requests | 16 | 与 answer service window 互斥 |

逻辑调用与审阅上限保持：

```text
formal answer attempts       = 1 per method/case unless frozen terminal retry applies
failed-terminal retry        = 0 for PE02 v3
hidden answer calls          = 0
development AI reviews       = 0
final AI reviews             <= 1
```

## 19.4 并发选择、背压与公平性合同

当前容量依据由 `system-profile` 形成并写入 `var/dg12/performance/parallelism-capacity-profile.json`：32 个逻辑 CPU、
16 个物理核、约 251 GiB RAM（采样时约 215 GiB available）、4×A100 40GB；vLLM tensor parallel 使用 GPU0/1，
GPU2/3 在采样时可供隔离 baseline。正式资源计划至少保留 4 个物理核和 32 GiB RAM 给 PostgreSQL、Runtime、MCP
与 OS。

2026-08-25 的 no-label 本地 vLLM 容量探针按固定 `4 → 8` 顺序完成：4/4 与 8/8 请求均成功，
12 个逻辑请求均有 native request ID，failure=0。因存在服务预热和顺序混杂，该探针只支撑
`answer_workers=8` 的容量可行性，不用于宣称 4 路与 8 路的性能加速比。

并发只改变物理调度，不改变实验处理：

```text
same planned method/case cells
same frozen Latin submission order
same prompt/context/token ceilings
same one-attempt logical IDs
same failure denominator
same scorer
```

`DG12-BATCH` 使用 `stable_case_ordinal % shard_count` 形成 4 个不相交 shard，分别运行独立进程和数据库 lease；
coordinator 只有在 shard 的 case-ID union 完整且 intersection 为空时才接受 archive。DG10/DG11 frozen Runtime 因
process-global migration/env boundary继续保持每进程 1 worker，但两个 method process 可与 DG12 shard 在全局 4-process
semaphore 下并行。

`LME-DENSE` 使用同一稳定 ordinal 规则分成 2 个不相交 shard：shard 0 强制绑定 `cuda:2`，
shard 1 强制绑定 `cuda:3`。双分片的 union/intersection 检查与 stateful shard 一样是合并前置条件。

正式 labels 打开前固定 worker count。开发/无标签 preflight 可用 `4 → 8` 短阶梯确认 provider failure=0；16 只保留
为后继容量实验 hard ceiling，不在本轮直接启用。正式执行开始后禁止根据 score、method、case 长度动态升降并发；
如果资源健康在开始前不满足 reserve，则整个 service window 暂不启动。开始后发生 overload 按冻结 failure terminal
进入 denominator，不用提高 retry 掩盖过载。

usage ledger 必须使用进程内已验证链头执行 O(1) append，并在启动、resume、外部文件 identity 变化和最终封存时
做完整 hash-chain verification；不得为并发性能关闭篡改检测。每个 run 报告 requested/effective workers、queue wait、
native request ID、provider failure、DB lease、CPU/RSS/GPU 峰值和 wall time，且 answer/judge service window 分开。

---

# 20. Stop、Rollback 与失败处理

## 20.1 立即停止并回滚最近改动

```text
canonical invariant violation
cross-tenant/scope/profile leakage
OpenIssue or revoke fail-open
stale cache authorizes action
under-covered MemorySlot reused as CACHE hit
Host hint/active_goal_summary/canonical_position_seen treated as canonical authority
retrieval/model output establishes or upgrades TaskIdentity
TaskRelationDecision directly mutates Registry without validated revision/generation transition
delayed tool result binds to completion-time active task instead of invocation-time task
Task Resolver invokes LLM/embedding/retrieval or starts learned-model training in DG-12
requested/validated L0 silently executes L1 while trace still reports L0
CurrentStateRead returns state without live OpenIssue/revoke/scope validation
projection manifest/segment treated as canonical truth
lazy logical invalidation after revoke, permission or retention change
raw cross-tenant content digest/CAS enables existence inference
fresh-DB restore bypasses governed canonical backup/restore contract
direct benchmark DML to canonical state
gold label enters retrieval/compiler/prompt
hidden provider call
secret/private content leakage
failure denominator manipulation
runtime/integration imports evals/scripts/var or benchmark private helper
goal/benchmark-named implementation starts owning product behavior
```

## 20.2 停止优化假设

```text
three bounded attempts without benefit
gain exists only through more visible tokens/calls
gain disappears under paired comparison
batch changes Top-K/context without becoming a declared new method
latency or storage cost dominates quality benefit
unsafe ablation is required to win
less than 95% wall time is attributed but implementation optimization begins
same-lease reuse is reported as product cold-build or restart speedup
full CAS/segment/compaction/lazy-fault stack is implemented before M0～M5 discrimination
multiple cold-path mechanisms change in one attempt and contribution cannot be identified
GPU/vector/ANN optimization is prioritized while measured vector stage remains below 1% and no new profile contradicts it
deep-path micro-optimization begins before FP1～FP4 fast-path vertical closure
fast-path coverage is increased by optimistic CACHE, dropped hard cases or false-fast routing
Need Resolver generates the evaluation labels used to score itself
FTS/vector score is used as ACTION_SAFE completeness without canonical/query-type sufficiency
```

## 20.3 正式实验失败

- Infrastructure failure 写入 denominator；按 frozen retry policy 处理；
- scorer/judge 不可用时停止对应 run，不改用未冻结 evaluator；
- vLLM 服务身份漂移时整个相关 run 无效；
- formal labels 已打开后禁止改变候选；
- 负质量结果不触发重复 formal run；
- 部分 benchmark 失败不能被其他 benchmark 的 PASS 掩盖。

## 20.4 回滚

- Product：回滚到 DG11 frozen wheels；不删除既有 canonical state；
- Harness：保留 `reference-faithful`；薄 evaluation lease/pool 可整体关闭；
- Evaluation cache：删除 cache 不影响 canonical 或结果复算；
- Native batch：关闭 semantic batch config 并使用单项 fallback；
- Set-based writer：切回已验证 scalar procedure；保留 canonical/outbox state，不回退已提交治理事务；
- Projection store：detach derived segment/image 并从 canonical/outbox 重建；Manifest 删除不改变 canonical state；
- Schema：默认不改；若 batch migration 必要，projection-only、可重建、真实 PG 验证；
- Result：失败 run 不覆盖历史，final package 尚未冻结前可重新构建，但不能重用已开始 Provider 的逻辑 ID。

---

# 21. Definition of Done

DG-12 只有同时满足以下事实才完成：

## 21.1 本体开发

1. §4B 范围的 active file、主要 symbol、entrypoint 和测试 100% 进入 `core-refactor-matrix.json`；
2. 每项只有一个 owner 和 terminal action，`UNDECIDED`、`KEEP_FOR_GOAL` 为 0；
3. `runtime/`、`integrations/` 对 `evals/`、`scripts/`、`var/dg*` 的运行时 import 为 0；
4. OpenWorker integration 不 import `milai.adapters.*`、Runtime 私有 module 或直连 Runtime HTTP；
5. 新产品模块、符号、默认配置和写入 identity 不包含 Goal 或 benchmark 名称；
6. legacy DG10/DG11 identity 按冻结 compatibility table read-old/write-new 或 fail closed；
7. 每项采用的 context/retrieval/lifecycle 行为只有一个活跃实现，无 product/eval 双实现漂移；
8. source-locked historical bytes 未改写，并已退出 active CLI、默认配置与 import graph；
9. stage observability、batch、long-lived lifecycle 和 memory policy 由正式产品 package 拥有；
10. 每项新能力可由 OpenWorker/MCP 主路径使用，不需要 paper dataset 或 DG 状态；
11. exact-role PostgreSQL、Scope/OpenIssue/revoke/cache/idempotency/outbox/watermark 无回归；
12. Runtime/Client/MCP/OpenWorker wheels 可 clean install，并从 non-repo cwd 完成权威纵向 E2E；
13. BHE01、`_CohortRuntime`、`_runtime_context` 未进入产品包、public API 或后续关键路径；
14. 临时移除 `evals/` 和非锁定历史 scripts 后，产品仍可构建、安装、运行和完成通用示例；
15. 产品性能收益和 evaluation amortization 收益分开报告；
16. OpenWorker host-owned task identity 与 turn query 分离，不从用户文本/模型输出获取 memory authority；
17. MemoryNeed、MemorySlotCoverage、CurrentStateEnvelope 和 RecallExecutionTrace 是 typed public boundary；
18. Host hint、slot 或 locator 结果均经过 tenant/Scope/authority/OpenIssue/revoke canonical revalidation；
19. L0/current-state 路径不调用 query embedding、FTS、vector 或 reranker；
20. `StateKeyRef` 是 typed locator 而非 authority/new store，并能跨持续 task 复用和重新校验；
21. `ExposureLedger` 与 `MemorySlotCoverage` 使用不同类型、predicate、指标和失效逻辑，exposure 从未授权 CACHE；
22. 默认 Context 使用 compact state/pointer，OVERVIEW/RAW_EVIDENCE 只按显式 Need 渐进加载；
23. server-side `prepare_memory_context` 在 trusted boundary 内完成 route、budget、slot 与 exposure 组装，Worker
    不获得新的 secret、Scope 或 authority；
24. async derived plane 只处理 projection/summary/proposal preparation/cleanup，未 adjudicate 内容从未成为
    ACTION_SAFE current truth；
25. `TaskIdentityState` 与 `TaskMemoryBinding` 类型、owner 和依赖方向分离，retrieval output 从未成为 identity input；
26. Task Registry 是 Host-owned graph，支持 per-lane active、SUBTASK、SWITCH、RETURN、AMBIGUOUS，不退化为全局栈；
27. TaskRelationDecision 与 Registry mutation 分离，Transition Validator 使用 revision/generation CAS；
28. delayed tool result 始终按 invocation-time token 绑定，wrong-task、ABA 和跨 Scope/profile 污染为 0；
29. Task Relation 只能把 CACHE 标为 `PROHIBITED/ELIGIBLE_FOR_VALIDATION`，从未正向授权复用；
30. 当前 Task Resolver 是 deterministic lexicographic resolver，LLM、embedding、retrieval 和 hidden Provider calls 为 0；
31. DG-12 没有 Task Resolver training dataset、feature pipeline、trainer、checkpoint、model registry 或 learned route。

## 21.2 Harness

1. 三种执行模式实现并明确标记；
2. cold build 与 warm query 的非重叠 stage metrics 各解释至少 95% wall time；
3. governance、fragment、embedding、write/index、watermark、internal query 和 MCP outer overhead 可分别复算；
4. fast migration/start 与 evaluation lease 数而非 case 数相关；
5. history build 与 unique history 数相关；
6. MCP/API/model 常驻；
7. Lease=1/2 有真实资源比较；
8. same-lease、restart、fresh-DB、cross-arm、cross-run、partial-CAS reuse 状态没有混写；
9. within-history/arm、cross-arm/run digest duplicate ratio 已统计，或因 privacy/data boundary 明确不可统计；
10. evaluation-fast 与 faithful 通过全部等价性和隔离门；
11. 正式 MiLAi harness arm 只调用 installed OpenWorker/MCP product path，无 `_private` 或 direct Runtime HTTP；
12. 新 benchmark 只需 mapping/scorer/config，不新增 MiLAi execution engine；
13. Horizon 10-case 初始工程目标达到或有基于 profile 的明确 terminal miss 结论；
14. Evaluation reuse 收益没有被写成产品 cold-build、restart recovery 或 online latency 收益；
15. OpenViking checkout/config 若纳入，具有冻结 source identity、readiness、内部调用核算与隔离证明；若排除，理由在
    正式 score 打开前冻结；
16. `OV-URI/OV-FIND/OV-CONTEXT` 与 `MiLAi-CACHE/L0/L1-PROG/L1-FULL` 的档位未混写，governed-state
    非等价 cell 明确标为 `NOT_SAME_CONTRACT`；
17. stateless context、stateful process、dense GPU、answer、judge 与 prompt-build 使用独立 lane 和冻结 worker 数；
18. 8-way answer/context 并发动态测试通过，worker hard ceiling、invalid value 与 freeze ceiling 均 fail closed；
19. stateful context shard 的 case-ID union 完整、intersection 为空，每个 shard 使用独立 DB lease 且进程内 worker=1；dense 双 shard 完整、互斥且分别绑定 GPU2/3；
20. 并发未改变 Latin submission order、逻辑 request ID、attempt、失败分母、token ceiling 或 scorer；
21. usage ledger append 不再随事件数二次重扫，但启动、resume、外部漂移和封存时的完整 hash-chain 检验仍通过。

## 21.3 Runtime batch

1. `embed_many` 真实 tensor batch 保持 byte-equivalent、logical item 与 inference batch 分离；
2. batch logical item、inference batch、cache hit 分开；
3. set-based projection writer 按 M3/M4 证据实现并 PASS，或在三次有界尝试后明确 `REVERTED/PARKED`；
4. Outbox/order/idempotency/watermark/dead-letter/revoke 无回归；
5. bulk/pipeline 不跳过 Evidence→Proposal→Decision，per-item failure 可见；
6. DG11 rollback wheel 可 fresh install；
7. batch 结果不被冒充成原 frozen candidate latency。

## 21.4 性能瓶颈闭环

1. matched、disjoint 的 FASTPATH_DEV/CONFIRMATION 连续 OpenWorker workload 与独立
   FastEligibility/Need/StateKey/expected-route 标签已冻结，confirmation 在 FP6 前 sealed；
2. `active_goal` 不再由当前 question 隐式重建；task/goal/Scope/profile switch 均显式 rebind/invalidate；
3. requested、validated、attempted、terminal route 和 override/fallback 全链路可见，无静默 L0→L1；
4. `CurrentStateReadService` 只读取 ClaimHead、EffectiveClaimState 和 live OpenIssue 的一致 canonical snapshot；
5. CACHE 同时验证 broker-bound Runtime proof、policy、Need coverage 和 dependency frontier，不可判断即 miss；
6. StateAddressability、FastEligibility、FastPathExecutionCoverage、REF、route mix 和 per-route latency 已分开报告，
   routing gap、真实产品 representation gap 与 benchmark/session characteristic 未混写；
7. `ACTION_SAFE false-fast=0`、stale/under-covered CACHE authorization `=0`、无覆盖时 `REF=1.0`、trace completeness
   `=1.0`；
8. FP5 DEV terminal 后冻结 `fast-path-acceptance.yaml`，FP6 untouched confirmation 达标或得到一次 terminal miss；
9. progressive L1 只作用于 fast path 不适用/失败的 turn，且每次早停都在 canonical gate 后满足 query-type-
   specific completeness；
10. M0～M4 使用同一产品 identity、同一 workload 和 matched repeated blocks 完成；M5 只有被证据触发才运行；
11. cold materialization 的 governance、embedding、write/index 与 orchestrator remainder 已分离；
12. deep recovery 的 recent-canonical、FTS、reranker 与 MCP outer overhead 已分离；
13. 每个 retained 优化能映射到一个被测瓶颈和一个 strongest simple replacement；
14. online、deep-L1、cold product 与 evaluation amortization 四类结果分开裁决；
15. cold product 达到 `<=268.900 s`，或三次有界尝试后得到 `TERMINAL_TARGET_MISS` 且不再衍生审计；
16. deep-L1 outer retrieval 达到 `<=31.548 s`，或有同样明确的 terminal miss 与下一阶段资源计划；
17. Top-K、Context、Scope、OpenIssue、revoke、watermark 和 hidden-call 差异为 0；
18. CAS/segment/image/lazy fault 只有在前置判别条件成立时才保留，Manifest 从未成为 authority；
19. 若 product bytes 改变，EH04 clean-install/E2E/equivalence/rollback/refreeze 已 PASS；否则记录合法 skip；
20. address-first、ExposureLedger 与 progressive content load 各有独立 DEV ablation，重复 body/token 收益和
    false suppression 分母完整，或被明确 PARK；
21. exposure dedup、async readiness 或 content-tier degradation 从未造成 stale suppression、under-covered CACHE、
    OpenIssue/revoke 漏检或 ACTION_SAFE false-fast；
22. FP1 的 retrieval-established identity、delayed-result wrong binding、cross-Scope/profile false merge、ACTION_SAFE
    task false merge、task-boundary unsafe CACHE 与 CAS/ABA failures 全为 0；
23. FP1 relation/transition trace completeness 为 1.0，并报告 fragmentation、binding stability、AMBIGUOUS、
    false merge/split 与 resolver p50/p95；
24. FP1 没有以 `L0 calls` 或后验 FastPath threshold 冒充自身 PASS；完整 route/Need/CACHE/confirmation 仍分别由
    FP2/FP3/FP4/FP6 关闭。

## 21.5 创新发现

1. observation、hypothesis、rival、prediction、falsifier 和 evidence 未混写；
2. 同时 active observation family 不超过 3，paper claim 不超过 `1 primary + 1 supporting`；
3. 至少一个实验明确区分 focal 与 rival，或如实得到 `NO_NOVELTY_CANDIDATE`；
4. case/agent task 是实验单位，技术测量未被当成独立 replicate；
5. 创新候选有 simple replacement、resource-matched 和 negative-control 证据；
6. 只有有重复 DEV signal 的候选进行一次 search-bounded novelty check；
7. exploratory discovery 与 untouched formal confirmation 分离；
8. method、systems、empirical/negative contribution 分开表述；
9. Skill 未自动启动开发期 reviewer、外部 judge 或外部图像 API；
10. 即使没有创新候选，完整、诚实的 characterization/negative result 仍可关闭 discovery 工作包。

## 21.6 实验

1. protocol、claim matrix、threshold、method config 在正式结果前冻结；
2. official BM25/dense/full/oracle 完成；
3. Mem0/Hindsight/Graphiti/ReMe/OpenViking 完成或有预冻结技术排除；OpenViking 未安装时不得写成已运行；
4. LongMemEval、Memora、LongMemEval-V2 至少完成两个核心矩阵；
5. BEAM/Horizon/CUPID 按资源和协议完成或如实 terminal；
6. 关键质量、安全和效率消融完成；
7. Agent/MCP/OpenWorker/serving 无功能或安全回归；
8. raw generation、trace、usage、failure denominator 可复算；
9. paired statistics、CI、effect size、类别和 Pareto 完整；
10. same-vLLM judge 不是唯一结论来源；
11. PE08 OpenWorker/MCP/Serving E2E 达到 functional/safety PASS，且至少一个 core memory benchmark 已完整通过
    OpenWorker→MCP→Runtime 执行；在此之前 learned Task Resolver 始终 PARKED。

## 21.7 过程

1. 开发期 AI review 为 0；
2. 最终独立 review 至多一次；
3. 没有多层 candidate/receipt/rereview 链；
4. 每个失败只有一个 terminal；
5. evaluated candidate 在 formal freeze 后未修改；
6. 负结果没有被隐藏或改名为 PASS；
7. 只生成一个 final result package；
8. 根据结果形成明确的下一步 KEEP/REVERT/REDESIGN/PARK；
9. Skill 的使用由明确 trigger 驱动，且没有产生额外状态机或报告版本链；
10. 没有新增 goal-named product module、一次性 run script 或 benchmark-owned MiLAi 业务实现；
11. 当前 Goal 没有训练/微调 Task Resolver；任何后续 learned candidate 只作为 PE11 之后的新 Goal proposal。

## 21.8 仍然禁止的声明

```text
PRODUCTION_READY
SCHEMA_FROZEN
EXTERNAL_PROVIDER_BILLING_VERIFIED
REAL_PRIVATE_DATA_APPROVED
DYNAMIC_TOOL_AGENT_READY
GENERAL_MULTI_AGENT_MEMORY_PLATFORM
OFFICIAL_BENCHMARK_WINNER       # 未按官方同协议完成前
STATE_OF_THE_ART                # 无完整可复算公开比较前
```

---

# 22. 当前唯一下一执行清单

```text
[x] 1. 已创建 var/dg12/current-state.json 与 ledger.jsonl
[x] 2. BHE00 已完成一次 faithful stage profile；保留为优化 baseline
[x] 3. 已停止 BHE01 goal-specific RuntimeSlot 方向
[x] 4. CORE00：全量生成旧代码/symbol/entrypoint/依赖/测试整理矩阵，`UNDECIDED=0`
[x] 5. CORE00：冻结规范 package graph、public owner、legacy source locks 和删除条件
[x] 6. CORE01：完成 OpenWorker/MCP owner、semantic identity、public lifecycle 与历史代码本体化
[x] 7. CORE02：规范 wheels 通过无 benchmark OpenWorker→relay/UDS→broker→MCP→Runtime E2E
[x] 8. PD00：完成通用 observability、真实 tensor batch、长生命周期等 retained 产品能力
[x] 9. PD01：完成 retained product 正确性、rollback、clean install 和 OpenWorker/MCP E2E
[x] 10. EH00/EH01：完成薄 adapter、evaluation lease、exact workload reuse 和 terminal accounting
[x] 11. EH02：完成产品/评测分解；产品 `1.463x` 未达 5x，same-lease reuse `19.815x`
[x] 12. EH03：冻结当前 product/harness identity、等价性和资源计划
[x] 13. ND00：冻结 observation 与 failure slices
[x] 14. ND01：补齐 Fast Path、deep recovery、cold materialization 的 focal/rival、预测和 falsifier
[x] 15. PD02-FP0：冻结 disjoint DEV/CONFIRMATION 与独立标签，sealed confirmation；在 DEV shadow 测 baseline
[x] 16. PD02-FP1：只实现 deterministic Execution-aware Task Binding、Registry/Graph、transition/CAS、
    invocation-time tool-result binding 与安全 trace；Task Resolver 模型/embedding/retrieval/training calls=0
[x] 17. PD02-FP2～FP5：完成 route、CurrentStateRead、Need/Slot 与 progressive L1 retained path
[x] 18. PD02-FP6：一次 sealed untouched confirmation 已消费，结果 `TERMINAL_TARGET_MISS`，禁止重跑
[x] 19. PD02 deep/cold：有界尝试已 terminal；当前产品 matched block 不足，不声明 2x/5x speed
[x] 20. PD02 terminal：`TERMINAL_TARGET_MISS`，ProjectionStore/CAS/segment/lazy fault 未实现
[x] 21. EH04：clean install、OpenWorker/MCP E2E、等价性与 successor wheels PASS
[x] 22. ND02～05：机制 signal、区分实验、一次有边界查新与 paper thesis handoff 已完成
[x] 23. PE00：v2 文档协议冻结；PE02 后续发现执行 identity 缺口
[x] 24. PE01：v2 identity 下无标签 reconfirmation PASS
[x] 25. PE02 preflight：零正式调用停止于 `BLOCKED_PRE_LABEL_PROTOCOL_AND_HARNESS_GAPS`
[x] 26. PE00V3：owner authorization、两份独立盲法 annotation、consensus 与 claim disposition 已完成
[x] 27. PE00V3：将旧固定 2-way harness 改为 8-way stateless/provider + 4-process stateful lane；逻辑 attempt 不变
[x] 28. PE00V3：刷新 producer source hashes，生成并验证唯一 one-way paper freeze manifest
[x] 29. 对 v3 identity 重跑无标签 PE01/PE02 gate；两者均 PASS，已单独授权正式 PE02
[ ] 30. PE02：按 frozen 8-way resource plan 执行一次 100×11 LongMemEval context/answer/scoring
[ ] 31. PE03～09：使用各 benchmark 独立的冻结资源计划并发运行，不复用 PE02 score 改候选
[ ] 32. PE10～12：统计、图表、反思和唯一 final package
[ ] 33. 确有必要时执行一次 gpt-5.6-sol 只读独立 review
```

当前禁止的下一动作：

```text
直接启动 Horizon/BEAM 正式全量 run
继续重跑 DG11 holdout
重新打开已 terminal 的 PD02、EH04、ND01～05，或用早期非 terminal FP1 文件改写 hypothesis contract
把 FP1 拆成 FP1-B/FP1-C，或在 FP1 内训练 LightGBM、XGBoost、Qwen/LLM classifier
让 Task Resolver 调用 embedding、semantic retrieval、vLLM/外部 Provider，或从 retrieved Claim 推断 same task
把 payload-free FP1 trace 自动转成训练集、feature store、checkpoint 或 model registry
在 PE08 E2E 与至少一个 core memory benchmark 完整跑通前启动 learned Task Resolver 开发
在 benchmark 后直接修改 DG-12 candidate，而不是通过 PE11 形成 successor Goal/new disjoint data plan
跳过 continuous OpenWorker workload，直接用 Horizon/session archive 估计日常 Fast Path coverage
把 current question 继续作为 active_goal/task identity
让 Host known-claim/state/issue hint 或 canonical_position_seen 决定 current/cached truth
只记录 Router 输出，不记录 Runtime validated/attempted/terminal route
在 FP0 后使用同一 Need Resolver 重写 ground-truth FastEligibility 标签
用 embedding similarity 判定 CACHE NeedCovered
用 ExposureLedger、cooldown 或“正文发过”判定 CACHE NeedCovered
把 OpenViking `find()` 标成无 embedding 的 direct state read，或把其 L0/L1/L2 与 MiLAi 路由同名等价
把 OpenViking 接入 MiLAi 产品 canonical 写链、授予 Runtime/DB secret 或加入产品 package dependency
在 FP6 confirmation 打开后修改 fast-path threshold、Need label 或 route policy
为补救已 terminal 的 PD02 speed miss 而修改冻结 product candidate、重跑 FP6 或先实现 projection paging
在 deep/cold explained_ratio < 95% 时猜测单一瓶颈并优化
跳过 M0～M4，直接实现 CAS + segment + compaction + lazy fault 全栈
把 same-lease exact reuse 声称为产品 cold build、restart recovery 或跨 run cache
优先优化当前仅占 0.9% 的 vector 或先给 reranker 上 GPU
使用裸全局 content digest 跨 tenant dedupe
让 projection manifest、segment 或 cache 绕过 Canonical Gate
先生成审计/receipt/candidate 版本链
让 Skill 自动启动 reviewer/subagent 或创建另一套状态目录
继续扩展 evals/dg12/runtime_slot.py、slot_smoke.py 或新 benchmark runner 作为产品实现
把整个 evals/dg12、evals/benchmark 或历史 scripts 直接复制进 Runtime
保留产品与 eval 两份可以独立演进的 context/retrieval/lifecycle 实现
在 runtime/integrations 中新增 DG12、Horizon、CUPID、BEAM、Memora 命名的产品符号
让 eval adapter import Runtime/MCP 私有 helper 或直接操作 canonical repository
为每个工作包或正式 run 新建一个 Python 执行脚本
在 PE02 正式 resource plan 与资源预检 PASS 前打开 paper labels
把 8-way 物理并发解释成 8 次逻辑 attempt、增加 retry 或按 method/score 动态改变并发
让共享 process-global migration/env 的 stateful Runtime 在同一进程内多线程跑 case
同时运行 answer 与 judge，或让 dense baseline 抢占 vLLM 的 GPU0/1
先写“创新点”再为其寻找有利实验
在同一正式 split 上发现并确认同一个新假设
修改 frozen DG11 candidate
打开 paper labels 后再修改 threshold
```

本 Goal 当前唯一执行任务是：

> **v3 并发 identity、source inventory、one-way manifest 与无标签 PE01/PE02 gate 均已 PASS。当前只为唯一一次
> 100×11 LongMemEval 正式 PE02 建立并验证 resource plan；预检 PASS 后才打开 label 并执行。并发不增加
> 逻辑调用、retry、隐藏 Provider 调用或审计。**

当前不是再做 OpenViking 调研、训练 Task Resolver、修改 MiLAi candidate 或优化复杂检索。OpenViking 仅保留已冻结
的 Evaluation baseline/technical exclusion 语义；PD02 的性能 miss 已终结，论文阶段应通过真实 benchmark 结果反思，
不能回到审计驱动或为了好分数修改同一候选。PE02 完整跑通后再按依赖推进 PE03～09；learned Task Resolver 仍只能
在 PE08 E2E 与 core memory benchmark 完成、且 deterministic residual 被证明 materially limiting 后，由 PE11 提出
successor Goal，不能在 DG-12 内自动开始训练。
