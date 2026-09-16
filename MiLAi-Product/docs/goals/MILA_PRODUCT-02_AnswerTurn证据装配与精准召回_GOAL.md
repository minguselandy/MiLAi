---
document_id: MILA-PRODUCT-02
version: "1.2"
status: PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE
document_type: PRODUCT_DEVELOPMENT_AND_EXPERIMENT_GOAL
title: Answer-Turn 证据装配、精准召回与渐进 Memory 增强
created_at: "2026-09-02T00:01:11+08:00"
updated_at: "2026-09-02T08:19:40+08:00"
repository: MiLAi-Product
parent: MILA-PRODUCT-GOALS@1.1
predecessor: MILA-PRODUCT-01
product_version: 0.1.0-candidate
schema_status: 0.1.x_EXPERIMENTAL_NO_GO_FOR_FREEZE
execution_authorized: true
auto_continue_after_stage_pass: true
repair_and_continue_on_recoverable_failure: true
formal_holdout_authorized: false
formal_holdout_consumed: false
selected_disposition: B0_B1_EQUIVALENT_BASELINE
public_api_change_authorized: false
database_schema_change_authorized: false
default_complex_feature_enablement_authorized: false
benchmark_owner: MiLAi-Lab
development_policy: SIMPLE_FIRST_SINGLE_FAILURE_REPAIR_CONTINUE
audit_policy: ONE_TRACE_ONE_TRACKER_STAGE_END_SUMMARY
---

# MiLAi Product-02：Answer-Turn 证据装配、精准召回与渐进 Memory 增强 Goal

## 0. 执行状态与权威关系

执行结果（2026-09-02）：Core 已按本 Goal 的 simple-first 与 staged-gate 约定完成。U2 的
EvidenceSet/atomic Context 原型通过契约与本地门，但 B2 在密封 128-case 的精确证据覆盖和
Qwen Judge 上均显著回退，因此终态为 `PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE`，选择
`B0_B1_EQUIVALENT_BASELINE`，B2 保持默认关闭。128 entry 未通过，故未运行、也未消耗
500-case formal holdout。详细制品、哈希与门禁见 Tracker。

本文件是 Product-01 S4 之后的后继开发计划。它在被用户明确激活前只具有规划权，不授权代码、
数据库、公共 API、默认 feature flag、formal holdout 或外部服务变更。

激活后，本 Goal 自动采用以下执行纪律：

```text
阶段通过
→ 更新一次 Tracker
→ 自动进入下一阶段

阶段未通过但可修复
→ 选择一个代表失败 case
→ 定位最早首损边界
→ 只修一个通用根因
→ 窄测通过后继续

Optional treatment 无增益
→ 删除或关闭 treatment
→ 保留更简单 baseline
→ 不阻断 Core 可用性交付
```

本 Goal 继承：

- Product-01 S0–S3 已接受的本地可用性、identity、Context 和 Binding 机器事实；
- `architecture/v1.0` 的 Evidence、Canonical、Scope、Revocation 和单一写入权边界；
- Product 不导入 Lab、Lab 通过正式接口或精确 Product identity 测试的仓库边界；
- Candidate 默认关闭，复杂能力必须经过独立机会门和效果门。

本 Goal 取代 Product-01 尚未完成的 S4 后续执行和 500-case 进入决策，但不覆盖、删除或改写
Product-01 S0–S4 的历史证据。

## 1. 当前机器事实

### 1.1 已完成且不重做

```text
Product/Lab 仓库拆分                                  PASS
Product → Lab/legacy import boundary                   PASS
architecture/v1.0 bundle validation                    PASS
fresh PostgreSQL 0049 / real-role / worker / restart   PASS
24-case identity/context preflight                     PASS
S2 known-false Binding repair                           PASS
S3 local golden flow                                    23/24
S3 warm typed control                                   100/100
Runtime 与六个 adapter 构建                             PASS
```

这些阶段只在后续改动触及相应边界时运行受影响回归，不重新创建整套审计制品。

### 1.2 Product-01 S4 的有效结论

权威 128-case run：

```text
Product commit                         1b5e4a7122da2b38b9a57bba143215cc0afa3387
Lab run                               product01-s4-128-20260901T143318Z
SystemContextSuccessRate              B0=1.0, B1=1.0
Evidence-group coverage               0.6015625 → 0.625
Qwen Judge accuracy                   0.28125 → 0.3125
Session Recall@5                      0.739583 → 0.729297
Session NDCG@5                        0.693233 → 0.677722
strict Wrong COMPLETE                 3 → 1
paired wins / losses                  5 / 1
paired Judge CI                       [0.0, 0.0703125]
terminal                              FAIL_S4_REPAIR_OR_KEEP_BASELINE
500-case                              NOT_ENTERED
```

这说明 B1 有局部答案收益，但不能发布：全局排名有所回退、Wrong COMPLETE 未清零，并且当前
`reader_visible_gold_span_coverage` 实际只比较可见 session ID，不是精确 answer-bearing turn/span。

128 cases 中有大量两臂共同失败；部分完全相同的 Reader prompt 仍得到不同答案。这要求后续把
retrieval mediator 与 Reader variance 分开，不能把所有 QA 变化归因于 Memory。

### 1.3 当前工作区必须先处理

Product `main` 当前 HEAD 为 `1b5e4a7`，存在未提交的 S4 修复：

```text
M docs/goals/MILA_PRODUCT-01_ISSUES.md
M runtime/src/milai/application/decision_engine.py
M runtime/tests/unit/test_product01_s2_lookup_readiness.py
```

这些修改属于用户工作区。执行 U0 时必须先审阅、窄测和决定保留或修正，不能覆盖、丢弃或把它们
当成已经验证的机器事实。当前候选意图是阻止 Raw Evidence lookup 单独授予 `COMPLETE`，但尚无
fresh superseding 128-case 证明。

## 2. 问题锚点与方法命题

### 问题锚点

当前 MiLA 能够捕获、治理、搜索并装配 Context，但大量失败发生在：

```text
answer-bearing turn 未发现
或
session 已命中但 answer-bearing turn 未装入
或
多个 operand 没有同时形成 EvidenceSet
或
Operator 消费了没有被 RequirementBinding 接受的候选
或
正确 EvidenceSet 被噪声和 Reader 不稳定破坏
```

### 方法命题

> 先把一次正式读取做正确：Raw/Canonical 小配额召回、局部原子展开、按 requirement/operand
> 选择 EvidenceSet、AcceptedBinding-only operator 和最小 Reader Context。只有剩余失败被证明
> 需要语义 Formation、时间图或 observation-conditioned 二次检索时，才独立引入相应能力。

## 3. 两个产品假设与一个反主张

### PRODUCT02-H1 — Lean Recall Usability

在不引入 Formation、Graph、Reflect 或多轮 Agent 的情况下：

```text
direct Raw turn + Canonical exact
+ optional Dense small quota
+ bounded same-session local expansion
+ requirement-role EvidenceSet
+ atomic progressive Context
```

可以提高真实 answer-bearing turn/span 与 required role 的 Reader-visible coverage，并保持
Wrong COMPLETE、scope/revocation leak 和产品延迟在可接受范围。

最低可信证据：

- known-false Wrong COMPLETE 单点重放全部正确；
- 24-case context/identity/serialization preflight 通过；
- 128-case matched run 的精确 turn/span 或 role coverage 有预注册净提升；
- 相同预算下 Judge 不出现明显净回退；
- Product 本地 golden flow、warm control 和 adapter 回归通过。

### PRODUCT02-H2 — Complexity Must Earn Entry

Formation、temporal graph、Reflect 或 ReFind-style extra action 只有在健康 Lean baseline 上存在
明确 residual、同预算 oracle 能恢复且简单修复不能恢复时，才可能带来独立增益。

最低可信证据：

- 能力 Entry gate 由 residual failure attribution 决定，而不是由项目流行度决定；
- 每种复杂能力单独 matched，不在一个 arm 中叠加；
- treatment 无增益时保持 OFF，不影响 `PASS_LEAN_MEMORY_USABLE`；
- Effect PASS 最多授权 CANARY，不自动授权 durable schema 或 default-on。

### Anti-claim — 不是靠更多候选、更多 token 或 benchmark 规则过关

必须排除：

```text
扩大 Top-k
增加 Reader token budget
多跑一次随机 Reader
换 seed 或 case order
增加 case-specific synonym / regex / case ID
同时修改 acquisition、ranking 和 prompt
把 session hit 冒充 answer span hit
```

## 4. 只保留六个强不变量

为减少防御性编程，所有开发只共享六个跨层硬边界：

1. `subject/session/source/turn/scope` identity 必须真实且不可跨来源邻接。
2. Raw Evidence 是来源记录，摘要、Graph、Formation 和模型输出不能替代它。
3. 任何派生表示都只能返回 source Evidence IDs，必须由现有 hydration + Gate 重新验证。
4. 普通 lookup 必须有 grounded relation/span；严格 operator 的每个 operand 必须来自
   `AcceptedBinding`。
5. `COMPLETE` 只有一个 DecisionBoundary owner；相关性分数、Reader 或外部 adapter 无权声明。
6. `reader_visible_trace` 必须精确等于实际序列化给 Reader 的内容。

除此以外，通道、融合、episode routing、reranker、cue、graph traversal 和 packing 都是可替换
策略。不得在每个策略内部复制 permission、revocation、authority 或 sufficiency 状态机。

### 4.1 参考项目是全程修复模式库，不是 U4 专属功能

Hindsight、ReFind、Mem0、Graphiti、OpenViking 从 U0 开始即可用于失败反思和最小修复设计。
引用它们不等于引入整个项目、外部依赖或完整架构。每次只迁移与当前首损直接相关的最小机制：

| 当前首损 | 优先参考 | 可立即借鉴的最小模式 | 仍需留在 U4 的完整能力 |
| --- | --- | --- | --- |
| Raw turn 未发现、单通道漏召回 | Hindsight、ReFind | Raw turn-first；BM25/Dense 独立小 quota；保留 channel lineage | 全量 graph/temporal fusion、Reflect |
| session 命中但 answer turn 未装入 | ReFind、OpenViking | same-session bounded local expansion；L0/L1 只导航、L2 Raw 作证 | 递归层级 retriever、LLM query planner |
| 多 operand 被全局 Top-k 挤掉 | Hindsight、OpenViking | per-requirement breadth-first coverage；再用余量加深 | 全局 learned fusion、复杂层级目录系统 |
| grounded relation 或 source role 错误 | Hindsight、Mem0 | source IDs、exact spans、speaker/scope metadata | 自动 fact/profile promotion |
| occurrence time、current/as-of 错误 | Graphiti、Hindsight | mention time 与 occurrence time 分离；valid-time 作为 Binding 字段 | durable temporal graph、自动 fact invalidation |
| Raw 已有但表示不可检索 | Mem0、Graphiti | ADD-only、source-linked、noncanonical projection prototype | 新 Store、worker、自动 entity merge/update/delete |
| 首轮后出现新 cue 且仍缺 role | ReFind | seen-region ledger；只补 missing role 的一次 query reformulation | 默认多轮 ReAct、模型 finish/search authority |
| 普通 Recall 已完成但任务需要综合 | Hindsight | Recall 与 Reflect 分离；先证据后分析 | always-on Reflect、mental model authority |

使用顺序必须是：

```text
当前失败首损
→ 查找参考项目中的对应机制
→ 提取最小可验证模式
→ 在现有 MiLA boundary 内实现
→ 单点正反例验证
→ 决定保留、简化或回滚
```

禁止使用顺序：

```text
发现外部项目有完整模块
→ 先接入整个模块
→ 再寻找它可能解决的 MiLA 问题
```

因此，U4 只控制这些思路的完整持久化、外部依赖、模型化、多轮化或 default/canary 授权；
U0–U3 可以随时吸收无需扩大 authority 和系统复杂度的局部算法模式。

## 5. Core 范围与后置范围

### Core MUST-RUN

- 审阅并验证当前未提交的 S4 repair；
- 修正 answer-turn/span 指标，不再使用错误命名的 session proxy；
- 建立 direct-turn-first 的一次正式读取；
- 以小 per-channel quota 保留 Raw FTS、Dense（若健康）和 Canonical exact 的机会；
- bounded same-session atomic turn/dialogue-pair expansion；
- requirement/operand EvidenceSet selection；
- ordinary `LookupReadiness` 与 strict `Sufficiency` 分离；
- 所有 strict operator 改为 AcceptedBinding-only；
- breadth-first-then-depth atomic Context packing；
- Product 本地可用性和 128-case matched 验证；
- 128 entry 通过后，才允许一次 500-case Qwen confirmation。

### Conditional / 后置的完整能力

- Episode L0/L1 navigation；
- Mem0-style ADD-only Formation candidate；
- Graphiti-style entity/event-time bitemporal projection；
- Hindsight-style Reflect；
- ReFind-style one-pass residual action。

这里后置的是完整 subsystem 或独立 treatment，不是对其设计模式的阅读和最小迁移。例如
OpenViking 的 breadth-first atomic packing 已属于 U1/U2；只有完整层级索引/递归检索才留到 U4。

### 本 Goal 明确不做

- 自由搜索 Agent、默认四轮 ReAct 或模型 `finish_search`；
- Graph/summary/mental model 成为 Canonical truth；
- Neo4j、第二套 durable store 或新 background worker；
- public MCP schema 或 PostgreSQL schema 变更；
- 自动 profile promotion、LLM update/delete Claim；
- broad runtime rewrite 或一次性清理全部历史 DG 代码；
- 为单一 LongMemEval case 加专用规则；
- formal holdout、production-ready 或 Schema freeze 声明。

## 6. 目标产品读取路径

```text
Query
  ↓
Lean RecallPlan
  mode: LOOKUP | STRICT
  roles: [ANSWER | OPERAND_A | OPERAND_B | EVENT_MEMBER | OLD_STATE | NEW_STATE ...]
  operator: optional
  ↓
existing tenant/scope/capability boundary
  ↓
small official acquisition
  ├─ Canonical exact/current/as-of
  ├─ Raw Turn FTS
  ├─ Raw Turn Dense（健康且配置时）
  └─ same-session adjacency/local window
  ↓
per-channel quota union + Evidence identity dedup
  ↓
atomic hydration
  ↓
existing live Evidence/Canonical Gate
  ↓
requirement-role EvidenceSet selection
  ↓
┌────────────────────────────────────────────┐
│                                            │
▼                                            ▼
LOOKUP                                   STRICT
GroundedAnswerSpanBinding               TypedRequirementBinding
subject/relation/source-role            identity/unit/time/dedup/proof
LookupReadiness                         StrictSufficiency
│                                            │
└───────────────────┬────────────────────────┘
                    ↓
         breadth-first atomic admission
         then deepen selected evidence
                    ↓
        exact Reader-visible trace
                    ↓
       Reader or deterministic operator
```

严格 operator 顺序必须是：

```text
candidate
→ governed Evidence
→ semantic/typed Binding
→ AcceptedBinding operand
→ operator
→ completion decision
```

禁止：

```text
raw candidate/date/score
→ operator OK
→ promote COMPLETE
```

## 7. 简洁代码设计约束

### 7.1 不做大重写

只沿本次触及的纵向 seam 提取稳定接口。建议的逻辑对象只有：

```text
LeanRecallPlan
RetrievalOccurrence
EvidenceSet
AcceptedOperatorInputs
AtomicContextUnit
```

可以先适配现有 `MemoryQueryIR`、retrieval、Binding 和 Context 类型，不要求立即新建公共 schema。
只有当同一职责在两个以上调用路径稳定复用时，才物理拆分模块。

### 7.2 三种内部 profile

```text
LEAN      默认候选：一次 Raw/Canonical 读取，无模型 Planner
FORMED    后置候选：LEAN + 非权威派生 projection
ACTIVE    实验候选：FORMED 或 LEAN + 最多一次 residual action
```

在本 Goal Core 完成前仅实现并验证 `LEAN`。`FORMED/ACTIVE` 不得通过多个相互耦合 flag 偷渡进入
默认产品路径。

### 7.3 校验只放在边界

允许新增校验的位置：

```text
external request
identity/scope boundary
database persistence
external model/adapter response
canonical authority boundary
```

内部纯函数接收已经验证的 typed object 后，不再重复检查相同字段。不要增加多层
`try/except Exception`、silent fallback、自动修复图或重复 digest envelope。

### 7.4 一个 trace，避免审计堆积

每个 Evidence 只记录一条轻量生命周期：

```text
discovered
→ hydrated
→ admitted/rejected
→ bound/rejected
→ reader-visible/not-visible
```

包含：

```text
evidence_id
session_id / turn_id
channel + rank
requirement_role
disposition + reason_code
serialized token range（若可见）
```

不创建 receipt-of-receipt、每次单测 manifest、重复 witness 或逐文件源码哈希。

## 8. 五个执行阶段

### U0 — 接管当前修复并建立真实基线

#### 目标

将当前未提交 S4 repair 变成可判断的候选，修正指标语义，并建立单 case 可重放的 Lean baseline。

#### 开发任务

1. 审阅三个 dirty files，确认用户改动意图和相互依赖；
2. 为 Raw Evidence 不授予 strict COMPLETE 建立一个 known-false 正例和一个合法 strict operator
   对照例；
3. 禁止 operator 仅凭 `status=OK/COMPLETE` 提升完成状态；
4. 将 `reader_visible_gold_span_coverage` 重命名为真实含义
   `ReaderVisibleGoldSessionCoverage`；
5. 新增通过 exact turn/span identity 计算的：
   - `AnswerBearingTurnRecall`
   - `ReaderVisibleAnswerTurnCoverage`
   - `ReaderVisibleAnswerSpanCoverage`（仅在标签具有 exact span 时）；
6. 将 infrastructure failure、semantic insufficiency 和 Reader failure 分开；
7. 单 case replay 输出一条完整 evidence lifecycle trace。

#### 最小测试

```text
1 个已知 Wrong COMPLETE case
1 个合法 operator COMPLETE 对照
1 个 session-hit / answer-turn-miss case
1 个 exact answer-turn-visible case
targeted unit + Lab metric test
```

#### 退出门

```text
known false strict COMPLETE                       0
legitimate strict operator regression             0
answer-turn metric exactness                       1.0
session metric no longer named span metric         PASS
single-case serialization replay                   PASS
Product/Lab import boundary                        PASS
```

若失败，保持 U0 `ACTIVE_REPAIR`，不进入新的 retrieval treatment。

### U1 — Answer-turn-first Lean Acquisition

#### 目标

在一次 acquisition phase 内提高 answer-bearing turn 的发现和装载，不增加 Agent、Formation 或
Graph。

#### 开发任务

1. Raw Turn FTS 保持 direct lane，不先聚合为完整 session；
2. Dense 健康时使用独立小 quota，不削减 Raw FTS 的既有预算；
3. Canonical exact/current/as-of 作为独立 lane；
4. 检索 occurrence 与 Evidence identity 分离，多通道命中同一 Evidence 后保留全部 lineage；
5. 命中 anchor 后仅在真实 same session 内展开 paired user/assistant 或 bounded local turns；
6. session/episode 只作 locality prior，不能替代 answer turn；
7. 每个 role 至少保留一个候选机会后，再使用剩余预算排序；
8. 超大 unit 跳过或降级为 pointer，不截断 atomic dialogue pair。

#### Treatment

```text
A0  U0 repaired baseline
A1  A0 + direct-turn per-channel quota union
A2  A1 + bounded same-session local expansion
```

三臂共享 candidate、hydration、Reader token、call、timeout 和 retry ceilings。A1/A2 不能通过
扩大总扫描预算获得优势。

#### 主指标

```text
RawAnswerTurnRecall
HydratedAnswerTurnCoverage
AdmittedAnswerTurnCoverage
ReaderVisibleAnswerTurnCoverage
RequiredRoleCandidateCoverage
RepeatedRegionRate
NoiseTokensPerUsefulEvidence
P50/P95 resolve latency
```

#### 选择规则

- treatment 至少使 `ReaderVisibleAnswerTurnCoverage` 或 `RequiredRoleCandidateCoverage` 提高
  `+0.03` absolute；另一项不得低于 baseline `-0.01`；
- strict Wrong COMPLETE、scope/revoke/cross-session leak 必须为 0；
- P95 不高于 baseline `1.5x`；
- 未达到效果门时选择更简单的 A0/A1，不阻断 U2。

### U2 — Requirement EvidenceSet、Binding 与薄 Reader

#### 目标

把“找到相关候选”变成“覆盖回答所需角色”，并让确定性 operator 不再消费未绑定候选。

#### 开发任务

1. 不新增 benchmark-shaped QueryType；在现有 QueryIR 之上生成最小 `LeanRecallPlan`：
   `LOOKUP|STRICT + roles + optional operator`；
2. 每个 EvidenceSet item 保存：
   `evidence_id + exact span/turn + source role + requirement role + time + lineage`；
3. ordinary lookup 只要求 grounded subject/relation/source-role，不强制完整 Event ontology；
4. strict operator 要求 identity/unit/event-time/dedup/proof 等适用 obligations；
5. `SUM/DIFFERENCE/COUNT/ORDER/STATE_AS_OF` 只能接收 `AcceptedOperatorInputs`；
6. Context 先广度覆盖每个 role，再对高价值 Evidence 加深；
7. 无绑定 distractor 不进入 strict operator Context；ordinary Reader 只接收最小可解释 EvidenceSet；
8. Reader 输出错误不能反向改变 Binding 或 Canonical State。

#### 单点病例族

每次只选择一个代表 case，按以下顺序处理：

```text
multi-operand value
multi-session set/count
relative temporal point
current/as-of state
assistant-source lookup
ordinary relation hard negative
Reader-noise regression
```

每个修复必须包含：

```text
1 个失败 case 重放
1 个正确对照 case
1 个错误关系或错误时间负控
受影响模块 targeted tests
```

#### 退出门

```text
AcceptedReferenceIntegrity                        1.0
SemanticBindingPrecision known-false slice        1.0
strict Wrong COMPLETE                             0
operator consumes unbound operand                 0
correct operator fixture regression               0
Reader-visible atomic unit truncation              0
Canonical mutation from read path                 0
```

### U3 — 本地可用性交付与 LongMemEval 决策

#### 目标

先交付一个可安装、可记、可找、可解释、可撤销的 `LEAN` profile，再使用 LongMemEval 判断其泛化，
而不是让 benchmark 阻塞本地可用性。

#### Product 门

```text
fresh install/init/doctor/start/smoke/stop          PASS
golden capture → query → trace → revoke             PASS
24 product scenarios task success                   >= 0.95
100 warm typed terminal rate                         1.0
read-after-write searchable P95                      <= 5 s
retrieval + Context P95                              <= 2 s
model outage deterministic fallback                  1.0
scope/revocation/deletion leak                       0
```

Product 门通过即可得出 `PASS_LEAN_MEMORY_USABLE`，不等待 U4。

#### Lab 运行楼梯

```text
targeted single-case replay
→ 8-case mixed failure-family micro-slice
→ 24-case context/metric preflight
→ fresh matched 128-case decision run
→ 128 entry PASS 后才允许 500-case Qwen confirmation
```

#### 128-case treatment

```text
B0  U0 repaired baseline
B1  selected U1 acquisition
B2  B1 + U2 EvidenceSet/atomic Context
```

只比较提交后的 Product package/manifest。Product 不读取 labels、case ID、Judge prompt 或 Lab
artifact。

#### 128/500 硬门

```text
SystemContextSuccessRate                            >= 0.99
ReaderVisibleTraceExactness                         1.0
cross-session contamination                         0
strict Wrong COMPLETE                               0
scope/revocation/wrong-relation leak                 0
system failure counted as semantic abstention        0
candidate complex profiles default                   OFF
```

#### 效果决策

主要归因顺序：

```text
AnswerTurnCoverage
→ RequiredRoleCoverage
→ SemanticBinding
→ OperatorReady
→ Qwen Judge
```

Qwen Judge 为次级结果，因为相同 prompt 仍可能出现生成方差。Candidate 最终选择要求：

- 精确 answer-turn 或 required-role coverage 至少一项 `+0.03` absolute，另一项无明显回退；
- Judge point delta 不为负，paired 95% CI lower bound 不低于 `-0.01`；
- P95 不高于 baseline `1.5x`；
- hard gates 全部通过。

未满足效果门时交付最简单的已通过 profile，不反复调整 seed、Top-k、Prompt 或 case。

#### 高效并发

- Product context、Reader、Judge 使用独立池；
- 先在 24/128 测得无 lease、显存和 timeout 退化的最高稳定并发，再冻结；
- Answer 全部完成后才并发 Judge；
- matched arms 可复用不受 treatment 影响的 ingest/index snapshot，不复用 treatment Context；
- CPU lint/type/unit 与互不依赖 adapter tests 并行；
- 每个 case 的 B0/B1/B2 交错，降低端点时间漂移；
- semantic result 不 retry、不投票；健康检查后的 transport retry 最多一次。

### U4 — 复杂能力的条件式升级队列

U4 不属于 Core Definition of Done。每种能力必须独立满足相同两级门：

```text
Entry PASS
= healthy Lean baseline
∧ residual 明确归因于该能力
∧ same-budget oracle 能修复
∧ FTS/Dense/adjacency/EvidenceSet 简单修复不能修复

Effect PASS
= matched treatment 取得预注册 mediator gain
∧ shared hard gates = 0 violations
∧ latency/cost 在预算内
```

状态只使用：

```text
NOT_ENTERED_NO_MEASURED_OPPORTUNITY
PARKED_NO_EFFECT
PASS_CANARY_CANDIDATE
```

#### U4-A — Episode navigation

仅当 session/episode 已可发现但 local expansion 仍无法定位 answer turn，且 query-independent
episode abstract oracle 能导航到正确 Raw turn 时进入。

借鉴 OpenViking：L0/L1 只导航，L2 Raw turn 才能 Binding；先广后深，不使用 hierarchy-only
retrieval。

#### U4-B — ADD-only Formation / temporal projection

仅当 residual 属于跨 episode identity、event occurrence time、current/as-of state，并且 formed
oracle 在同预算下能恢复时进入。

借鉴 Mem0/Graphiti，但必须：

```text
query-independent
Raw-preserving
source-linked
noncanonical
ADD-only candidate
conflict → Proposal/OpenIssue candidate
```

不在 Effect PASS 前创建新表、watermark、worker 或外部图依赖。

#### U4-C — One-pass ReFind

仅当：

```text
fresh RequirementState 仍有 missing role
AND observation 提供了新 cue
AND 存在未执行合法 action
AND oracle 显示额外动作可恢复 Evidence
```

才允许一次 official extra acquisition。模型只补 cue 或排序已有 feasible actions；不能自由工具调用、
不能 `finish_search`、不能切换 scope、不能声明 COMPLETE。

#### U4-D — Reflect / associative analysis

仅面向 recommendation、跨 episode synthesis、thread resume 等真正需要综合的任务；ordinary lookup
和 deterministic operator 永不默认调用 Reflect。

## 9. 单点失败修复循环

### 9.1 首损分类顺序

对每个失败 case，必须按以下顺序寻找第一个错误边界：

```text
F0  INFRASTRUCTURE
F1  DISCOVERY
F2  HYDRATION_OR_LOCAL_EXPANSION
F3  ADMISSION_OR_PACKING
F4  SEMANTIC_BINDING
F5  OPERATOR_OR_PROOF
F6  READER
F7  JUDGE_OR_HARNESS
```

后续层失败不能用来掩盖前一层。例如 answer turn 没有进入 Reader 时，不修改 Reader prompt；候选已进入
但 Binding 错误时，不扩大 Top-k。

### 9.2 每轮修复协议

```text
1. 从一个失败家族选择一个最小代表 case
2. 单 case 确定性重放，保存一条 lifecycle trace
3. 固定上下游，形成一个可证伪根因
4. 查询参考项目模式库，选择一个最小可迁移机制或继续使用 MiLA 本地机制
5. 只改一个 component / policy
6. 跑失败正例 + 正确对照 + 安全负控
7. 通过后跑 8-case micro-slice
8. 再跑受影响的 24/128 gate
9. 保留修复，或干净回滚该 treatment
10. 记录“借鉴了什么、拒绝了什么、为什么”，继续下一首损家族
```

同一轮禁止同时修改：

```text
acquisition + ranking
ranking + Context budget
Context + Reader prompt
QueryIR + gold mapping
model + seed + concurrency
```

### 9.3 失败后的改进方向

| 首损 | 优先反思 | 参考项目模式 | 允许的通用改进 | 禁止的假修复 |
| --- | --- | --- | --- | --- |
| DISCOVERY | query 表达或通道可达性 | Hindsight multi-signal；ReFind raw turn | 独立 small quota、Raw/Dense、适用 temporal lane | 无边界扩大 Top-k、case synonym |
| LOCAL EXPANSION | session/turn identity、窗口方向 | ReFind local context；OpenViking L2 drill-down | paired turn、same-session bounded expansion | 整 session 前缀、跨 session 拼接 |
| ADMISSION | 全局 cutoff、长 unit 占满预算 | OpenViking breadth-first-then-depth；Hindsight source lineage | role breadth-first、skip/降级 oversized unit | 截断 dialogue pair、只加 token |
| BINDING | subject/relation/source/time 不匹配 | Hindsight source/time fields；Mem0 scoped metadata | grounded span、typed operand、ambiguity | score 高就接受、模型 confidence |
| TEMPORAL/STATE | mention/event/current 混淆 | Graphiti bitemporal；Hindsight occurrence time | occurrence-time Binding、current/as-of resolver | ingestion order、自动覆盖旧 Claim |
| OPERATOR | operand 或 proof 未闭合 | 外部项目只提供证据组织，不提供 MiLA authority | AcceptedBinding-only、deterministic proof | raw dated result、Reader 自行计算 |
| READER | 噪声、顺序、生成不稳定 | Hindsight Recall/Reflect 分离；OpenViking progressive load | 最小 EvidenceSet、deterministic result | 重复调用投票、将答案写入 prompt |
| REPRESENTATION | Raw 存在但现有索引不可表达 | Mem0 ADD-only；Graphiti Episode→Fact lineage | noncanonical sidecar prototype、Raw fallback | 新 Store、自动 promotion、物理覆盖 Raw |
| RESIDUAL | 首轮后仍缺 role 且出现新 cue | ReFind observation-conditioned search | 最多一次 missing-role action | 默认多轮 Agent、模型 COMPLETE |
| HARNESS | metric、identity、并发错误 | 不由外部 Memory 项目修复 | 修评测实现并 fresh rerun | 把 system failure 算 abstention |

### 9.4 三次修复仍重复时

同一通用根因经过三次实质修复仍重复，不追加第四层 validator、fallback 或 retry。必须执行一次
design simplification：

```text
删除该 treatment
或
替换为更简单 deterministic path
或
降级到 optional Lab prototype
```

这不是整个 Goal 失败；Tracker 记录反思后继续处理其他可完成任务。

## 10. 测试阶梯与计算资源

### 日常开发

```text
edit
→ 单 case / 单函数 test
→ targeted positive + negative unit tests
→ affected module lint/type/test
→ 8-case micro-slice（仅语义路径）
→ 24-case stage gate
```

### 阶段结束

```text
affected package full tests
→ 必要时 isolated PostgreSQL
→ Product manifest/build
→ 128-case matched Lab run
```

### Goal 交付前一次

```text
Runtime full matrix
+ six adapters/builds
+ architecture bundle lock
+ fresh local golden flow
```

不在每个代码改动后运行全量 Runtime、六 adapters、PostgreSQL 和 128 cases。

### 并行原则

- 互不写同一数据库的 unit/static/package jobs 可并行；
- PostgreSQL integration 使用独立临时数据库名，完成后只删除精确目标；
- vLLM 并发先用短 slice 测稳定上限，正式 run 不动态改变；
- 计算资源优先给不同 failure families，不用来重复同一 semantic result；
- 缓存只复用由 content/config digest 证明 treatment-invariant 的 ingest、embedding 和 index；
- Reader/Judge 失败不得触发 Context 重算，避免重复 Product 调用。

## 11. 最小记录与文档

Product 只维护：

```text
本 Goal
一份轻量 Tracker（含 issue/reflection 表）
每阶段一段 acceptance summary
PRODUCT_CURRENT_STATUS 聚合状态
必要时更新 product.manifest.json
```

Lab 每个正式 run 最多保存：

```text
run.json
cases.jsonl
metrics.json
terminal.json
```

单点开发重放无需创建正式 terminal；测试输出和 Tracker 一行足够。只有 128/500 sealed decision run
生成正式四件套。

## 12. 阶段自动流转

| 当前结果 | 自动动作 |
| --- | --- |
| 阶段硬门与效果门通过 | 更新 Tracker，进入下一阶段 |
| 可修复 product/test/environment failure | 保持 `ACTIVE_REPAIR`，执行单点循环 |
| Optional treatment 无增益 | `PARKED_NO_EFFECT`，关闭它并继续 |
| 简单 candidate 无增益 | 保留 repaired baseline，继续 U2/U3 产品交付 |
| 模型不可用 | 使用 deterministic fallback；benchmark 标记 pending |
| 需要 API/Schema/默认启用/破坏性操作 | 暂停并请求授权 |
| authority/scope/revocation breach | 隔离临时环境，修复安全根因后 fresh 重放 |

不允许因为一次 recoverable test failure 把整个 Goal 标记 terminal。

## 13. Core Definition of Done

- [x] 当前三个 dirty files 已审阅，用户改动没有被覆盖；
- [x] Product-01 S4 Wrong COMPLETE repair 具有 targeted 正反例和 fresh superseding test；
- [x] session coverage 与 answer-turn/span coverage 指标已分离；
- [x] direct Raw turn、Canonical exact 和健康 Dense 使用独立小 quota；
- [x] same-session local expansion 不跨 source session；
- [x] EvidenceSet 按 requirement/operand 覆盖；
- [x] ordinary LookupReadiness 与 StrictSufficiency 分离；
- [x] strict operator operand 全部来自 AcceptedBinding；
- [x] Context 按 role 先广后深，只装入 atomic units；
- [x] known false Wrong COMPLETE、scope/revoke/wrong-relation leak 为 0；
- [x] Product 本地 golden flow、24 scenarios、100 warm 通过；
- [x] fresh 128-case matched decision 完成；
- [x] 128 entry 未通过，按约定未执行 500-case Qwen confirmation；
- [x] `LEAN` profile 具有单一关闭/回退路径；
- [x] FORMATION、Graph、Reflect 和 multi-round Agent 未进入默认产品路径；
- [x] Product 不导入 Lab，Lab 不绕过 Product official path；
- [x] Schema 继续为 `NO-GO FOR FREEZE`，不虚报 production-ready。

Core 完成不要求任何 U4 能力进入。允许的结论只有：

```text
PASS_LEAN_MEMORY_USABLE
PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE
ACTIVE_REPAIR
BLOCKED_AUTHORITY_OR_EXTERNAL_DEPENDENCY
```

## 14. 激活后的前三项动作

1. 只读审阅当前 dirty diff；对 Raw Evidence COMPLETE repair 运行最窄正反例，决定保留或修正；
2. 修复 Lab 的 session-proxy 指标命名，建立 exact answer-turn/span 指标和一个单 case trace；
3. 从 S4 失败中选择一个“session 已命中但 answer turn 未装入”的病例，实现 direct-turn/local
   atomic admission 的第一处纵向改动，并用一个正确对照和一个跨 session 负控验证。

最终原则：

> 先让一次读取稳定找到并装入真正回答问题的原始证据，再让 EvidenceSet 和 deterministic operator
> 正确使用它。复杂 Formation、Graph 和主动再检索必须用剩余错误证明自己的必要性；失败时修最早
> 首损点，单点通过后继续，不用更多规则、更多审计或更多模型调用掩盖问题。
