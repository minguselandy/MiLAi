---
document_id: MILA-ML-R02
version: "0.2"
status: ACTIVE_USER_LIMITED_8X4
document_type: ARCHITECTURE_CONVERGENCE_AND_END_TO_END_VALIDATION_GOAL
updated_at: 2026-08-31
architecture_baseline: MILA-ML-ARCH@1.0
execution_order_authority: MILA-ML-MASTER
predecessor_goal: MILA-ML-R01@0.3
predecessor_run: ml-r01-20260831-001
execution_authorized: true
execution_scope: LONGMEMEVAL_8_CASES_X_4_ARMS_THEN_STOP
formal_holdout_authorized: false
product_default_enable_authorized: false
benchmark_judge_backend: VLLM_QWEN_ONLY
leaderboard_equivalence_claimed: false
---

# MiLAi ML-R02：统一 Memory Lifecycle 架构收敛与 LongMemEval 验证 Goal

> 日期：2026-08-31（Asia/Shanghai）  
> 性质：设计与执行合同；用户已于 2026-08-31 明确授权执行，但将 benchmark 范围限制为 `8 cases × 4 arms`，完成后结束；本文仍不授权 128/500-case、formal holdout 或产品默认启用。  
> 上位规范：`architecture/v1.0`、`MiLAi_Lean_V1_实施合同.md`、`MILA-ML-ARCH@1.0`。  
> 激活条件：ML-R01 当前 R4 pilot 已封存，且 `MILA-ML-MASTER` 显式登记本 Goal 为活动后继。

---

# 1. 总目标

本 Goal 不再增加新的 DG 式局部策略，而是完成一次项目级收敛：

```text
先消除开发冲突与重复决策权
→ 理顺唯一 Memory Lifecycle 产品路径
→ 以简单、可替换的组件完成 Formation / Evolution / Recollection
→ 保持普通回忆高召回、严格操作高正确性
→ 修复运行、并发与可观测性
→ 最后运行 matched LongMemEval-S 500-case
```

方法 Thesis：

> **Raw Evidence、Formed representation 与 Canonical State 应共享一个候选汇合点和一个最终决策权；普通回忆使用受治理的宽候选与软排序，严格操作使用 Grounded Binding、typed operator 和 completeness proof。Formation 只有在同一产品路径中证明真实 mediator gain 后，才获得持久化与 Canary 资格。**

这不是一次全仓库重写，也不是建设自由搜索 Agent。实现目标是：

```text
更少的并行语义链
更少的重复对象与 feature flag
更高的普通记忆召回
更严格且唯一的 COMPLETE authority
产品与 eval 使用同一实现
失败后有界修复而非立即终止整个 Program
```

---

# 2. 与当前 ML-R01 的接续关系

截至本文生成时，权威状态为：

```text
artifact:
  var/ml_repair/ml-r01-20260831-001/terminal.json

status:
  ACTIVE_R4

current authorized scope:
  8_CASES_X_4_ARMS_THEN_STOP

128 / 500:
  not authorized in the current ML-R01 execution
```

当前 R4 的 `context-seal-8.json` 已保留一个重要的 harness 负证据：32/32 context cells 均成功，四臂分母、snapshot identity、memory budget 和 isolation safety 均通过；seal 的失败来自 shard-terminal 对一个真实 benchmark case 执行 510 条 Evidence 全量 revoke/purge witness 超时，并把该 cleanup 长尾计入 500-case 语义窗口外推。它是 benchmark/cleanup 计时边界冲突，不是 context delivery 或 Memory 方法失败。

同一 pilot 中，Formation 对 8 个产品 case 均 eligible，但 attempted/applied 为 0、全部走 Raw fallback。该事实只能路由 B2 的同构接入与 mediator 检查，不能单独判定 Formation 方法无效。

因此：

1. 本 Goal 是条件式后继，不得与 ML-R01 R4 同时修改 Runtime、runner、Reader、Judge 或 benchmark 配置。
2. ML-R01 R0–R3 及已成功 R4 cells 全部继承，不重新运行。
3. 当前 R4 pilot 必须先完成、终止或以明确 checkpoint 封存；不得静默中断后改名重开。
4. 若 ML-R01 已完成某个未受代码变化影响的 BM25/Dense baseline cell，ML-R02 可以按 identity 复用。
5. ML-R02 修改后的 MiLA 产品臂必须使用新代码身份重跑；不能把旧 MiLA 输出当作新架构结果。
6. 当前总 Goal、AGENTS 和局部 Goal 的动态状态漂移应在 ML-R01 封存后一次同步，不在活动 run 中反复改写。

必须保留、不重新包装的历史结论：

```text
DG24       first-loss map
DG25       complex acquisition caused Binding/Wrong COMPLETE failure
DG26       fixed-pool StateView had no independent gain
DG27       model semantic finalizer did not establish a safe common boundary
DG28       simple deterministic union had development-set opportunity
DG30       read-path integration passed, release_ready=false
MF01–04    non-holdout Formation representation evidence
MD01–02    unified bundle evidence; MD02 boundary H1 MISS / H2 PASS
EV01       governed bridge compatibility, not automatic product evolution
ML-CLOSURE delivery failure baseline
ML-R01     lease repair, 128/128 delivery, progressive boundary evidence
```

---

# 3. 研究假设与反主张

最多保留两个主假设。

| Hypothesis | 内容 | 最低可信证据 | Blocks |
| --- | --- | --- | --- |
| `MLR02-H1 ARCHITECTURE CONVERGENCE` | 单一 DecisionEngine 与 ordinary/strict 双模式能在减少重复逻辑的同时提高普通回忆并保持严格完成正确性 | 最终 COMPLETE authority 只有一个；普通 Context recall 不回归；strict Binding precision=1；Wrong COMPLETE=0；已有正确 operator/current-state 不回归 | B1、B3 |
| `MLR02-H2 FORMATION UTILITY` | 与 Raw fallback 同构的统一 Formation 能在相同 query-time budget 下提高 LongMemEval 的记忆利用 | 产品 Formation 实际应用；产生新 AcceptedBinding/coverage；500-case `F-R` Judge Accuracy 达到预注册实用效应且 paired CI 支持；无 authority/safety 回归 | B2、B4 |

必须排除的反主张：

```text
增益只来自更多候选、更多 token、更多 Reader/Judge 调用或更大 latency
增益只来自 benchmark-specific synonym / regex / case rule
增益来自失败样本、拒答样本或 context delivery 不完整
Formation 实验验证的是 A，产品实际执行的是 B
复杂 adaptive/refinding 比 simple memory path 更必要
Qwen Judge 结果等价于官方 GPT-4o leaderboard
```

若 H2 不成立，不影响 H1 与 Lean Memory Core 完成；结论应是选择 Simple Raw/Canonical memory，并保持 Formation OFF，而不是继续增加 graph、planner 或搜索轮次。

---

# 4. 本 Goal 的完成范围

“完成全部开发”在本文中严格限定为 Phase 1 文本个人记忆生命周期：

```text
Evidence capture / projection
Semantic Formation
Entity / Event / Event-time / State-change representation
optional governed proposal drafting
Canonical Evolution through existing Steward path
Raw / Formed / Canonical Recollection
ordinary and strict Context compilation
typed operator / temporal completeness
OpenWorker → MCP → Runtime product path
worker/readiness/release/harness closure
LongMemEval-S 500-case matched validation
```

明确不进入：

```text
multimodal memory
procedural skill / workflow learning
multi-agent shared memory
automatic Canonical promotion
automatic Scope Evolution
Graphiti/Zep/OpenViking production backend
unbounded L2 or free-search Agent
model-controlled COMPLETE
formal internal holdout
Schema freeze / Production-ready claim
```

Runtime 和 Schema 继续保持：

```text
Runtime 0.1.x CANDIDATE
Schema 0.1.x EXPERIMENTAL
NO-GO FOR SCHEMA FREEZE
```

---

# 5. 目标架构

## 5.1 写路径

```text
Raw Evidence
  ├─ Raw Projection
  ├─ Unified FormationEngine
  │    └─ FormationArtifactCandidate / Formed Projection
  └─ optional governed proposal draft
         ↓
     OperationProposal
         ↓
     Validator / StewardDecision
         ↓
     ClaimVersion / ClaimHead / OpenIssue
```

不可改变：

```text
Evidence != belief
Formation artifact != Canonical State
模型输出 != accepted Claim
Canonical mutation only through existing procedure
ClaimVersion append-only
ClaimHead exact-head CAS
conflict preserved as OpenIssue
revoke synchronously fail-closed
```

## 5.2 读路径

```text
RawEvidenceReader ───────┐
FormedProjectionReader ─┼→ CandidateUnion
CanonicalReader ─────────┘
                              ↓
                       Live Governance Gate
                              ↓
                       Unified DecisionEngine
                         ├─ ORDINARY_RECALL
                         │    soft semantic selection
                         │    coherent evidence context
                         │    no unproved COMPLETE
                         │
                         └─ STRICT_OPERATOR
                              grounded interpretation
                              AcceptedBinding
                              RequirementState
                              typed operator / proof
                              one Sufficiency authority
                              ↓
                        MemoryContextCompiler
                              ↓
                         Reader / Agent
```

模型可以参与：

```text
ambiguous query interpretation
semantic episode formation
entity/event/time proposal
candidate interpretation or ranking
```

模型不能拥有：

```text
permission or scope authority
arbitrary tool/action generation
Binding acceptance authority
completeness authority
Canonical commit authority
```

---

# 6. 冲突替换表

| 当前冲突 | 当前影响 | 本 Goal 的唯一替代 | 旧路径处置 |
| --- | --- | --- | --- |
| acquisition 内部 Sufficiency + Retrieval 最终 Sufficiency + conditional reconcile | 同时造成 false negative 与 Wrong COMPLETE | 一个 `DecisionEngine` | 删除第二完成权与 reconcile |
| query/content 词项交集可判 lookup COMPLETE | 表面相关即错误完成 | grounded AcceptedBinding | 删除该 COMPLETE 分支 |
| 普通 recall 使用完整 strict Binding presentation | Reader 看不到合法相关证据 | `ORDINARY_RECALL` 软选择 | strict 仅保留给 operator |
| V01 compiler → V02 translator | requirement/operator 语义漂移 | native V02 compiler | translator 仅作历史 artifact reader |
| 产品 V01 temporal proof 与 eval V02 proof | COUNT 完备合同不一致 | 产品统一写 `BoundedRangeScanProofV02` | 删除产品 V01 writer |
| MD/MF Formation Bundle 与产品 GeneralizedFormationBundle 不同构 | 实验结论不能归因到产品 | 一个 `MemoryFormationBundleService` / `FormationEngine` | helper 可内部保留，不再作为独立 contract |
| process-local Formation 全 partition 同步 rebuild | 重启丢失、多进程不一致、ingest O(n) | 先统一 shadow；有增益后才建 worker-owned durable projection | process-local store 退役或仅保留测试 fixture |
| Formation→Evolution 仅 eval caller | 生命周期未闭合 | opt-in review-only proposal drafting | 禁止自动批准 |
| 多个独立 feature bool | 未验证组合爆炸 | `BASELINE / FORMED_SHADOW / FORMED_CANARY` profiles | legacy flags 兼容期后移除 |
| 统一 RuntimeSettings / 子进程继承环境 | Worker 获得非必要密钥 | role-specific settings + env allowlist | 移除继承式 secret exposure |
| `worker --once` 文档与行为不符 | preflight 隐式消费队列 | 真正无副作用 `--check` | `--once` 只表示单批处理 |
| API ready 与数据面 readiness 混淆 | API 可用不等于 projection 已追平 | `/health/ready` 保持进程本地；`milai-ops status` 汇总 worker/backlog/watermark | 不新建 heartbeat 服务或表 |
| 大量 DG runner/receipt 工具 | 开发认知与运行成本过高 | 一个产品 LongMemEval runner + compact artifacts | 历史 runner read-only archive |

任何新增抽象必须替换至少一条旧路径；不得以“兼容”为理由永久保留新旧两套 authority。

---

# 7. 优雅性、正确性与开发效率原则

## 7.1 优雅性预算

```text
one Canonical write authority
one final decision authority
one native product QueryIR
one temporal proof writer
one Formation builder contract
one product LongMemEval runner
three feature profiles at most
```

禁止新增：

```text
第三套 DecisionBoundary
每个内部函数一套 digest/envelope
每个 stage 一份 receipt/manifest/deliverable index
eval-owned retrieval/ranking/Binding
自由文本失败账本洪泛
case-ID / answer / gold-aware rules
Prompt/Top-k/seed sweep
无界 retry 或 refinding
```

仅在以下边界保留 identity/digest：

```text
persistent artifact
cross-process worker payload
model request/response
external experiment frozen input/output
release artifact
```

## 7.2 失败处理

单次实现失败不是总 Goal terminal：

```text
protocol / implementation miss
→ 记录机器可读 root cause
→ 修改共享机制
→ 仅恢复失败 cell
→ 不换 seed / case / Judge / budget
```

```text
effect miss
→ 只暂停依赖该 effect 的后继
→ 其他独立工作继续
```

```text
safety failure
→ 对应 profile 保持 OFF
→ 修复 authority boundary
→ 不恢复重复决策链
```

同一根因最多进行 3 次有实质修改的 repair iteration。第三次仍失败时，可以 PARK 该组件，但必须继续不依赖它的 Block；禁止完全相同配置自动重跑。

## 7.3 测试分层

```text
每次编辑:
  touched unit / contract + edited-file Ruff / mypy

每个子阶段:
  relevant integration slice

涉及 DB/schema/security:
  corresponding real PostgreSQL / RLS / migration tests

总集成:
  one full Runtime suite

benchmark 前:
  one 8-case then 128-case product smoke
```

不在每次 repair 后运行全部历史 DG tests。

---

# 8. 五个执行 Block

## B0 — Predecessor Seal 与最小 Characterization

### 目的

封存 ML-R01 R4，建立本次真正会被修改的四类行为基线，而不是再做一次全仓库审计。

### 工作

1. 等待当前授权的 `8 cases × 4 arms` pilot 终态。
2. 复用成功 checkpoint，不重复 R0–R3。
3. 冻结四组非 holdout characterization：

```text
D: simple lookup / multi-operand / current / contested / wrong-complete
Q: supported QueryIR operator families + ambiguous negative
T: bounded count / ambiguous time / max_items / source-time-only
F: topic/continuation/correction/temporary state/restart/revocation
```

4. 只产生一个 `baseline-results.json`；测试 fixture 保存在源码中。
5. 保留当前 R4 cleanup timeout 证据；将 `semantic_context_window` 与 `cleanup_operational_window` 分开。
6. 32 个已经成功的 context cells按 exact identity 复用；修复后只重建 seal并运行独立 cleanup witness。

### Entry gate

```text
ML-R01 terminal or explicit checkpoint seal exists
current feature defaults recorded
formal holdout unopened
core integration slice runnable
```

### Effect gate

```text
all future replacement points covered by at least one characterization test
baseline reproducible twice without external model variance
no product behavior changed
```

### Failure interpretation

无法稳定复现现有行为时，先修 harness/fixture；不得开始架构迁移。

---

## B1 — 单一 Recollection 与 Decision 语义

### Claim tested

`MLR02-H1`

### B1.1 Unified DecisionEngine

新增薄 facade，复用现有 domain 实现：

```python
DecisionEngine.decide(
    query_ir,
    governed_candidates,
    canonical_results,
    spans,
    interpretations,
    bindings,
    operator_result,
    temporal_proof,
) -> DecisionResult
```

迁移顺序：

```text
Retrieval final point uses DecisionEngine
→ acquisition returns intermediate evidence/binding only
→ remove _acquisition_owns_final_sufficiency
→ remove term-overlap lookup COMPLETE
→ move useful grounded-span validation into DecisionEngine
→ retire independent DG27 finalizer
```

完成合同：

```text
LOOKUP            >=1 grounded AcceptedBinding
CANONICAL_EXACT   one live scope/time/current CanonicalBinding
MULTI_OPERAND     every required operand bound
COUNT_DISTINCT    accepted event set + complete temporal proof
CONTESTED         never silent COMPLETE
```

### B1.2 Ordinary / Strict 双模式

```text
ORDINARY_RECALL:
  live governance admission
  soft relevance / coherence
  Reader-visible evidence may exceed AcceptedBinding
  no unproved COMPLETE

STRICT_OPERATOR:
  Grounded Interpretation
  AcceptedBinding
  RequirementState
  typed operator / proof
  deterministic completion
```

两种模式共享 permission、scope、revocation、provenance 和 trace，不共享过严的 presentation policy。

### B1.3 Native QueryIR V02

按 family 渐进迁移：

```text
LOOKUP / CURRENT_STATE
MULTI_OPERAND / COMPARE / DIVIDE
SET / COUNT
TEMPORAL
PREFERENCE / UPDATE
AMBIGUOUS
```

已迁移 family 不再调用 V01 compiler；未迁移 family 暂保 compat。全部完成后，产品 translator 调用数必须为 0，历史 artifact reader 可保留。

### B1.4 Unified Temporal Proof

现有 official bounded Raw scan 直接产生 `BoundedRangeScanProofV02`：

```text
resolved event interval
+ repository snapshot/watermark
+ partition scan facts
+ event-time normalization
+ event identity/dedup facts
+ access facts
→ BoundedRangeScanProofV02
```

没有独立 event projection 时，只有完整 Raw bounded fallback 才能闭合 projection gap；模型不得证明完整性。

### Effect gate

必须同时满足：

```text
FinalCompleteAuthorityCount = 1
Wrong COMPLETE = 0
StrictAcceptedBindingPrecision = 1.0
ordinary ContextEvidenceRecall >= B0 baseline
current/canonical/contested behavior no regression
supported QueryIR structural equivalence = 1.0
product V01→V02 translator calls = 0 after final migration
COUNT COMPLETE only when proof.closure_complete
ambiguous/source-time/max_items/dedup-incomplete → PARTIAL
```

若某一 QueryIR family 迁移失败，只保留该 family compat，不阻塞其他 family。若 temporal OperatorReady 无增益，保留正确 PARTIAL，不恢复关键词 COMPLETE。

---

## B2 — Unified Formation、Evolution 与高效 Memory Representation

### Claim tested

`MLR02-H2` 的 mediator 前置。

### B2.1 唯一 FormationEngine

以一个正式 application contract 统一：

```text
Raw Evidence snapshot
→ SemanticEpisode
→ Entity / Event / Event-time candidates
→ State assertions / transitions
→ Recollection projection records
→ MemoryFormationBundle / FormationArtifactEnvelope
```

产品与 eval 必须调用同一 builder。`build_generalized_formation` 可以成为内部 helper，但不得继续定义第二种产品 bundle。

强制语义：

```text
observed_at/source ordinal stable ordering
assistant allowed as episode context
assistant cannot create user state/event
permission snapshot comes from committed Evidence
Raw span coverage preserved
deterministic replay
```

### B2.2 Product Shadow

```text
official Evidence ingest
→ unified FormationEngine
→ formed candidate selection
→ official hydration/Gate
→ unified DecisionEngine shadow
```

记录真正 mediator：

```text
formation matched/applied
new governed candidates
new accepted bindings
required evidence coverage delta
operator-ready delta
raw fallback
latency/storage amplification
```

如果 `formation_applied=0`，判定为 delivery failure，修复后恢复失败 cells；不能据此声称 Formation 无效。

### B2.3 条件式 Durable Projection

只有 Product Shadow 已产生真实 Binding/coverage gain 才进入。最小持久化复用现有 Outbox/worker：

```text
partition key
source snapshot / watermark
artifact payload or projection rows
producer identity
build epoch / status
revocation lineage
```

读语义：

```text
fresh    → formed lane available
stale    → raw fallback; cannot prove COMPLETE
missing  → raw fallback
revoked  → immediate fail-closed
```

持久化后删除同步 ingest O(n) 全 partition rebuild 和 process-local cross-process state。

若需要新表，必须提交窄 ADR、Migration、upgrade/downgrade 或不可逆说明及真实 PostgreSQL/RLS/rebuild 测试；不得修改 frozen `architecture/v1.0`。

### B2.4 Governed Evolution Bridge

Formed state/change artifact 只可生成 review-only proposal draft：

```text
FormationArtifactCandidate
→ deterministic validation
→ OperationProposal
→ existing CommitPolicy / StewardDecision
→ existing Canonical procedure
```

禁止自动批准、直接 DML 或从 retrieval/context 反向提交 Claim。

### Effect gate

```text
ProductFormationBuilderCount = 1
eval/product builder identity equal
assistant contamination = 0
RawSpanCoverage non-regression
deterministic replay = 1.0
product shadow visible behavior identity = 1.0
Canonical mutation in shadow = 0
permission/revocation leak = 0
formation_applied > 0
at least one new valid Binding or coverage/operator-ready gain
```

Durable 子门：

```text
restart parity = 1.0
deterministic rebuild = 1.0
revoked Evidence retrieval leak = 0
stale projection COMPLETE = 0
ingest does not synchronously rebuild full partition
```

若 Formation 实际应用但无 mediator gain：

```text
durable projection = NOT_ENTERED_NO_FORMATION_GAIN
Formation profiles remain OFF/SHADOW
B1、B3、B4 Raw path continue
```

---

## B3 — 产品集成、运行可靠性与代码简化

### B3.1 配置和进程边界

```text
CommonSettings
ApiSettings
WorkerSettings
```

Worker 使用显式 env allowlist，不继承 API、Steward、Agent 或 audit secrets。

实现：

```text
milai-worker --check     dependency-only, no queue mutation
milai-worker --once      process one bounded batch
/health/ready            API/DB/blob process-local readiness
milai-ops status         managed worker PID + watermarks + degraded routes
```

写后读继续使用现有 exact projection-readiness barrier。补充 Blob-before-DB orphan reconciliation；不为 readiness 新建 heartbeat 表，也不把 API 与 Worker 拆成更多微服务。

修正 namespace cleanup 的共享 Blob 终态语义。当前 `BLOCKED_SHARED_REFERENCE` 是正确的保留决定，但 cleanup 聚合只把 `ERASED` 计为完成，会让共享 CAS Blob 永久超时。兼容保留原字段，并新增/明确：

```text
primary_bytes_terminal_count
primary_bytes_erased_count
primary_bytes_retained_shared_count
primary_bytes_retention_blocked_count
```

完成条件是 logical revoke、derived purge 和 primary bytes 进入合法终态，不是强迫共享 Blob 立即物理删除。Focused PostgreSQL gate 必须证明：另一条 live Evidence 仍可读；已清理 namespace 不可读/不可检索；最后一个 live reference 撤销后才真正 `ERASED`；各终态 count 之和等于 accepted count。

### B3.2 Feature profile

默认只允许：

```text
BASELINE
FORMED_SHADOW
FORMED_CANARY
```

Dense 只有绑定真实模型 identity、维度和 projection version 时才可用；deterministic hash 必须报告 `UNAVAILABLE_FOR_SEMANTIC_DENSE`。

vLLM semantic adapter 仅可作为 DecisionEngine 的可替换 interpretation/ranking provider；没有已证明 residual 时，不加入 planner、action ranking 或第二轮 refinding。

### B3.3 删除与降格

完成后删除或降格：

```text
legacy term-overlap COMPLETE
conditional final-sufficiency reconcile
independent DG27 finalizer
product V01 temporal proof writer
product V01→V02 translator
independent GeneralizedFormationBundle product entry
duplicate SemanticEpisode shadow executor
process-local Formation builder authority
unverified feature-flag combinations
```

历史 DG runners 和 artifact validators 转为 read-only archive，不进入默认开发测试。保留一个产品 LongMemEval runner、一个 artifact validator 和一个 compact repair log。

只有 B4 支持产品候选并形成 `SHADOW_ONLY_READY` 或更高处置时，才执行一次 fresh wheel/sdist、clean-venv install、CLI smoke 和最小 BOM。许可证仍未声明时保持 `LOCAL_ONLY`；不生成 transitive release manifest。

### B3.4 Quality gate

```text
targeted unit/contract          PASS
core integration slices        PASS
real PostgreSQL/RLS/migration  PASS when affected
Ruff / strict mypy             PASS
OpenWorker → MCP → Runtime     PASS
one final full Runtime suite   PASS
temporary DB cleanup           PASS
release package migration head/current source identity aligned when release candidate entered
```

### Effect gate

```text
authority/scope/revocation violations = 0
Canonical invariant violations = 0
unexpected worker exits = 0
worker preflight mutations = 0
stale projection silent readiness = 0
default profile = BASELINE
old decision/formation authorities have no product callers
```

---

## B4 — LongMemEval-S 最终测试

### 目的

在开发全部完成后，以官方 LongMemEval 任务与 scorer 语义，使用本地 vLLM Qwen Reader/Judge，验证产品送达、检索、Formation utility、Reader 和成本。不开启 OpenAI GPT-4o，也不宣称官方 leaderboard 等价。

### 4 个主臂

| Arm | 作用 | Canonical authority |
| --- | --- | --- |
| `BM25-T` | official-style lexical retrieval reference | 无 |
| `DENSE` | frozen verified semantic dense reference；能力不可用时明确 `UNAVAILABLE` | 无 |
| `MLR02-R` | unified Raw + Canonical Simple Recollection | MiLA Gate/DecisionEngine |
| `MLR02-F` | unified Formed + Raw fallback + Canonical Simple Recollection | MiLA Gate/DecisionEngine |

不加入第五个 adaptive/refinding 主臂。只有 B4 后仍存在明确、可执行的 second-round oracle opportunity，才另建后继 Goal。

### 数据与固定项

```text
dataset              LongMemEval-S cleaned public 500
case order           frozen once
QA denominator       500
retrieval denominator official labeled subset (expected 470, verified at lock)
Reader               same frozen Qwen/vLLM identity for every arm
Judge                frozen Qwen/vLLM identity
Judge prompt         official LongMemEval anscheck semantics
temperature          0
answer max output    500 tokens
Judge max output     10 tokens
logical attempts     1 per cell
automatic retry      transport-only, at most once, same request identity
formal holdout       untouched
label timing         query-only during context; gold opened only after answers seal
```

若 Reader 与 Judge 使用同一 Qwen model，必须报告 self-judge bias；结果只支持本地 matched comparison。

### Context budget

不再以 512/2048 人工切片作为主比较。B4 preflight 用冻结 tokenizer 计算：

```text
B = min(
  served_model_max_context - fixed_prompt_tokens - answer_reserve,
  product_wire_safe_token_capacity,
  benchmark_adapter_supported_capacity
)
```

规则：

```text
B 在打开答案前封存
四臂使用相同 B
按完整 Evidence/turn/session 原子单元装配
不得截断 atomic dialogue pair
超限时按冻结 ranking 丢弃完整最低优先级单元
1024/512 只能作为 predecessor/离线压力诊断，不是 ML-R02 主结论
```

### 并发与资源

运行前重新 probe 实际资源；若仍为 16 物理核、4×A100：

```text
GPU0/1  vLLM Reader/Judge，answer 和 judge 分窗口
GPU2/3  two deterministic dense shards
CPU      BM25 + product orchestration
```

并发上限：

```text
stateful product contexts   4 isolated processes × 1 worker
stateless BM25/Dense        up to 8 workers
answer lane                 up to 8 in flight
judge lane                  up to 8 in flight
global hard ceiling         16
```

产品 context 固定复用 ML-R01 已证明的 `4 processes × 1 worker`，不再为提高并发重复做 4/8 sweep。Answer/Judge 使用已经通过无标签 capability probe 的 8-way 上限；资源压力只能下调，不能依据 accuracy 上调。

效率规则：

```text
R/F share one ingest/projection snapshot
one namespace per case
physical DB cleanup at shard terminal
checkpoint every terminal cell
successful cell never repeated
failed cell resumed by exact identity
BM25/Dense unchanged outputs may be reused by digest
no hidden Provider/model call
```

Benchmark timed window 不再拿真实 LongMemEval case 做全量 revoke/purge witness。撤销/物理清理正确性由既有真实 PostgreSQL suite 加一条独立、固定、脱敏的小型 technical witness 验证；benchmark namespaces 最终通过 exact ephemeral DB drop 清理。R/F 之间允许写 query trace，但禁止 Evidence、projection 或 Canonical mutation 改变共享 source snapshot。

另外保留一条独立的 512-Evidence synthetic namespace-cleanup load witness，用于定位“projection delivery/watermark 已终态、但 primary erasure/status 未闭合”的删除 operability；它不进入 LongMemEval wall time、failure denominator 或语义评分。不得通过延长 timeout 或增加 worker 掩盖真实 settlement 缺口。

Resume 后不得用单次恢复 invocation wall 外推全量时间。`semantic_context_wall` 必须从每个唯一 case 的冻结 timing 重构：

```text
per_product_shard = startup + Σ unique_case.case_wall
product_wall      = max(per_product_shard)
```

paired R/F 每 case 只计一次共享 ingest/projection 成本；BM25/Dense 按各自冻结调度重构。`cleanup_witness_wall` 与 exact DB drop 单列为 operational cost。失败 seal 保留，修复后生成 superseding seal，不覆盖旧证据。

### 分阶段运行

```text
L0  8-case post-development product sanity
    ↓ delivery and capability pass
L1  128 × 4 contexts
    ↓ all contexts terminal
L2  128 × 4 answers
    ↓ answers sealed
L3  128 × 4 Qwen Judge
    ↓ viability decision
L4  extend to 500, reusing first 128 and unchanged baseline outputs
```

协议/容量失败进入 repair/resume，不解释方法效果。128 只作 delivery、safety 与资源门，不根据中期 Accuracy 改方法、预算或决定是否隐藏完整负结果；只要 delivery/safety 可闭合且资源可用，就按预注册计划扩到 500。

### 主指标

```text
Qwen Judge Accuracy
paired MLR02-F minus MLR02-R Accuracy delta
paired bootstrap 95% CI
```

次指标：

```text
Recall@5 / NDCG@5 / MRR
Exact Match / normalized F1
ability-stratified accuracy
RequiredEvidenceCoverage
ValidBindingRecall / AcceptedBindingPrecision
OperatorReady / TemporalCompleteness
Formation eligible/applied/new-binding counts
context/answer/judge latency P50/P95
FormationCostPerEvidence
query CostPerUsefulBinding
storage amplification / projection lag
```

### Delivery gate

```text
all required cells terminal
R/F context delivery = 500/500
transport/readiness/worker/isolation failures = 0 after repair
cross-case evidence leak = 0
authority/scope/revocation violation = 0
Canonical mutation by Formation/Reader/Judge = 0
Wrong COMPLETE on strict applicable cases = 0
```

任一产品臂未达到完整 delivery，只能形成 delivery diagnosis；不能解释 Formation/Reader 效果。

### 128→500 viability

必须同时满足：

```text
128/128 contexts, answers, judges terminal
Formation applied > 0
strict AcceptedBindingPrecision = 1.0
Wrong COMPLETE = 0
no safety-critical correct-case regression
resource window supports completion
no unresolved delivery or protocol failure
```

若 Formation application rate `<10%`，报告为 sparse specialist；全分母 ITT 仍是主结论，不使用 applied subset 作因果结论。

### H2 支持门

预注册 practical effect：

```text
MLR02-F - MLR02-R Judge Accuracy >= +0.02
paired 95% CI lower bound > 0
strict safety metrics no regression
query-time model/action/token ceilings matched
P95 query latency <= 1.5 × MLR02-R
```

外部 QA 中允许个别普通问题 win/loss 交换，但必须满足 paired net gain；strict typed correctness、authority、revocation 和 Wrong COMPLETE 仍要求零回归。

若点估计为正但 CI 跨 0，结论是 `INCONCLUSIVE`。若无增益或成本过高，选择 `MLR02-R`，保持 Formation OFF；不得用 subgroup、换 Judge 或改预算事后救活。

---

# 9. 执行顺序与并行开发

```text
B0 predecessor seal
        ↓
B1.1 Unified DecisionEngine
        ├───────────────┐
        ↓               ↓
B1.3 QueryIR       B2.1 FormationEngine
        ↓               ↓
B1.4 Temporal      B2.2 Product Shadow
        │               ↓ mediator gain only
        │          B2.3 Durable Projection
        └───────────────┬───────────────┘
                        ↓
                 B2.4 Evolution Bridge
                        ↓
                 B3 Integration/Cleanup
                        ↓
                 B4 LongMemEval
```

| Milestone | 核心结果 | 并行度 | Go/repair decision |
| --- | --- | ---: | --- |
| M0 | ML-R01 seal + D/Q/T/F baseline | 1 | baseline 稳定才改代码 |
| M1 | single DecisionEngine + ordinary/strict | 1–2 | Wrong COMPLETE=0，recall 不回归 |
| M2 | QueryIR/Temporal 与 Formation 可并行 | 2–3 | 各 lane 独立修复，不互相拖停 |
| M3 | conditional durability + Evolution bridge | 1–2 | Formation 有 mediator gain 才持久化 |
| M4 | operations、cleanup、full quality | 2 | 完整产品 smoke 后进入 benchmark |
| M5 | 8→128→500 LongMemEval | bounded 16 | delivery 完整后才解释效果 |

---

# 10. 制品与审计上限

本 Goal 每个有效 effect 最多保存：

```text
run-lock.json
results.json
terminal.json
repair-log.jsonl      # only when repair occurred
```

源码测试和 Migration 正常进入仓库，不复制到 effect 目录。

禁止默认生成：

```text
per-stage receipt
transitive source manifest
deliverable index
reviewer loop
duplicate runbook
hundreds of free-text failure rows
```

终态只生成一份 compact architecture/effect summary，并引用现有测试输出。只有 release packaging 才生成 release manifest。

---

# 11. 终态决策

协议、实现或环境失败优先进入 repair，不直接 terminal。最终只允许以下状态：

| Terminal | 条件 |
| --- | --- |
| `PASS_MLR02_UNIFIED_MEMORY_FORMATION_SUPPORTED` | H1 PASS；H2 PASS；LongMemEval delivery/safety/efficiency PASS；Formation 可保持 default-OFF Canary 候选 |
| `PASS_MLR02_UNIFIED_SIMPLE_MEMORY_SELECTED` | H1 PASS；H2 未支持或成本过高；Raw/Canonical simple path 完成并选择，Formation 保持 OFF |
| `PARTIAL_MLR02_ARCHITECTURE_PASS_BENCHMARK_INCONCLUSIVE` | 架构与质量通过，但 Qwen/vLLM effect CI 不充分或环境无法完成外部结论 |
| `PARKED_MLR02_ENVIRONMENT_OR_VLLM_UNAVAILABLE` | 相同外部服务/资源不可用且已完成有界诊断；不归因到 Memory 方法 |
| `FAIL_MLR02_AUTHORITY_OR_STATE_SAFETY` | 未能修复的跨 tenant、revocation、Canonical invariant、重复 commit 或 Wrong COMPLETE 安全失败 |

即使 H2 PASS，本 Goal 最多授权：

```text
SHADOW_ONLY_READY
或
CANARY_CANDIDATE_READY
```

不直接授权：

```text
DEFAULT_ON
Schema freeze
Production ready
formal holdout consumption
automatic Canonical promotion
```

---

# 12. Definition of Done

只有以下事实全部有机器证据时，本 Goal 才算开发完成：

1. 产品最终 COMPLETE authority 只有一个。
2. Ordinary recall 与 strict operator 使用明确不同的 presentation/commitment policy。
3. lexical term overlap 不能直接产生 COMPLETE。
4. 产品只生成一种 native QueryIR，历史 translator 不在产品调用链。
5. 产品 temporal COUNT 使用统一 V02 proof，完整性不能由模型或点事件推断。
6. 产品与 eval 使用同一个 Formation builder 和 artifact contract。
7. Raw Evidence、provenance、permission、revocation 与 Raw fallback 始终保留。
8. Formation 无法自动提交 Canonical；Proposal/Steward/ClaimVersion/OpenIssue 仍是唯一写路径。
9. Formation 有效时使用可重建、watermark-addressed、revocation-safe projection；无效时不建设或启用复杂存储。
10. Worker 使用最小配置/密钥，`--check` 无副作用，readiness 能看到 projection health。
11. 默认 feature profile 为 `BASELINE`；Dense/Model capability 不可用时明确报告 unavailable。
12. 旧完成权、旧 Formation 产品入口和重复 runner 已删除或无产品 caller。
13. targeted、integration、真实 PostgreSQL/RLS（如适用）、Ruff、mypy、OpenWorker/MCP 和一次 full Runtime gate 通过。
14. LongMemEval 先完成 delivery，再完成 Qwen/vLLM Judge；四臂预算、Reader、Judge 和调用次数匹配。
15. 500-case 结果完整报告正结果、负结果、成本、稀疏 application 和失败分布，不以内部 subset 替代全分母。
16. Formal holdout 未消费，产品默认未擅自启用，Runtime/Schema 仍如实标记 Candidate/Experimental。

---

# 13. 激活后的前三项动作

```text
1. seal ML-R01 R4 pilot and synchronize the execution master once
2. freeze minimal D/Q/T/F characterization without changing behavior
3. implement Unified DecisionEngine before touching Formation durability or LongMemEval
```

最关键的执行原则：

> **先删除重复权力，再增加能力；先证明统一 Formation 在产品路径中有用，再持久化；先保证全部 benchmark cell 真正送达，再讨论模型分数。**
