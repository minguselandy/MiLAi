# MiLAi 后续开发与研究推进规划 v1.0

> 文档状态：READY_FOR_EXECUTION
> 基线日期：2026-09-22
> 基线仓库：`minguselandy/MiLAi`
> 当前 `main`：`dfeb359d2301b99c0125d9e54e9c29a9025d7f59`
> Cleanup：C0–C10 COMPLETE
> Frozen Architecture：`1.0.0`，保持不可修改
> 当前 Product tree：`7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521`
> 当前 Conformance：`10 PASS / 34 UNVERIFIED / 0 DEVIATION`
> 当前 TECH_DEBT：`5 FIXED / 5 NEEDS_REVALIDATION / 0 OPEN`
> Product 默认：保持现状；任何研究机制在独立收益证据形成前不得进入默认路径
> Schema：保持 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

---

## 1. 规划目的

代码整理已经完成，下一阶段不再继续大规模结构重构，而进入“行为闭环 + 测量基础 + 自适应记忆研究 + 独立验证”的开发周期。

后续开发必须解决四个核心问题：

1. **Product 当前未验证的行为边界到底是什么。**
2. **Memory 从取得、选择、暴露到实际使用与结果之间能否形成可靠的可追踪链。**
3. **Utility、Revision、State-guided Attention 等机制是否产生可重复、可归因、成本可接受的收益。**
4. **只有在 Lab 中出现独立收益证据后，哪些机制值得进入 Product ADR 和最小行为 PR。**

主线定义为：

```text
Behavioral Closure
        ↓
Trace / Continuity / Resolver Closure
        ↓
Memory Opportunity & Use Attribution
        ↓
Utility Selection
        ↓
Evidence-grounded Revision
        ↓
State-guided Attention
        ↓
RL-like Online Policy Adaptation
        ↓
Transfer / Multi-session Confirmation
        ↓
Product Promotion Gate
```

本规划明确停止以下开发模式：

```text
❌ 继续为了“文件更小”做结构拆分
❌ 为提高 Conformance PASS 数量而机械补测试
❌ 在机制尚未激活时直接扩大 Benchmark
❌ 把 Memory 暴露等同于 Memory 使用
❌ 用单次任务成功给每张 Memory 分配奖励
❌ 把 Lab 机制直接写入 Product 默认路径
❌ 使用未证明必要性的 LLM controller 替换确定性控制
```

---

# 2. 当前权威基线

## 2.1 Cleanup 后工程状态

Cleanup 已完成：

- Retrieval 责任拆分进入 `retrieval_core/`；
- Memory Context 由 facade + `memory_context_core/` 承载；
- MCP Server 拆分为内部 owner modules；
- OpenWorker Host 拆分为明确的 ingress / task / memory / provider / trace seam；
- Lab runner 已开始采用 thin wrapper + typed package implementation；
- 所有 receipt-referenced pytest node ID 保持存在；
- 5 个已 FIXED technical debt 已生成 current-tree `post-cleanup.receipt.json`；
- Frozen Architecture、Lab archive 和 Artifact Archive 历史 bytes 保持不变；
- Final Run #60 完整 17-job composition PASS。

因此，后续开发默认禁止再次进行全仓代码整理。

---

## 2.2 当前剩余 TECH_DEBT

| Item | State | 后续处置 |
|---|---|---|
| process-local task continuity/state | NEEDS_REVALIDATION | 与 Host continuation 合并审查 |
| cache-miss Host continuation | NEEDS_REVALIDATION | 与上项建立统一 Host Continuity Contract |
| resolver lexical-language assumptions | NEEDS_REVALIDATION | 建立多语言/自然表达诊断 corpus |
| Runtime vs Host/provider trace ownership | NEEDS_REVALIDATION | 优先处理，作为后续研究归因基础 |
| worker `--once` docs/behavior | NEEDS_REVALIDATION | 快速行为复核 |
| confirmation binding | FIXED | 不修改 |
| validation-token/capsule lifecycle | FIXED | 不修改 |
| projection purge/rebuild | FIXED | 不修改 |
| OpenWorker HTTP auth/exposure | FIXED | 不修改 |
| CAS blob-first orphan | FIXED | 不修改 |

后续不得把 `NEEDS_REVALIDATION` 自动解释成缺陷。
先诊断，只有执行证据证明行为缺口后才能转 `OPEN`。

---

# 3. 总体阶段

```text
Phase 3A  Product Behavioral Closure
Phase 3B  Measurement Foundation
Phase 3C  Adaptive Memory Research
Phase 3D  Transfer / Independent Confirmation
Phase 3E  Product Promotion Decision
```

依赖关系：

```text
3A
 ├─ worker --once
 ├─ Host Continuity
 └─ Resolver diagnostic
        │
        └─────┐
              ↓
3B Trace Ownership + Opportunity Ledger
              ↓
3C Utility → Revision → Attention → Policy Adaptation
              ↓
3D Transfer / Multi-session / unseen confirmation
              ↓
3E ADR / Product candidate / keep-Lab decision
```

---

# 4. Phase 3A — Product Behavioral Closure

## Goal 3A-0 — Status Reconciliation

### 目的

先统一 Product/Lab 文档状态，避免执行 Goal 与真实代码状态继续分叉。

### 修改范围

只修改状态文档，不修改 Product 行为。

建议更新：

```text
MiLAi-Product/docs/PRODUCT_CURRENT_STATUS.md
MiLAi-Product/docs/PRODUCT_GOALS.md
MiLAi-Lab/docs/LAB_CURRENT_STATUS.md
MiLAi-Lab/docs/LAB_GOALS.md
```

### 必须写清

Product：

```text
main
Product tree
manifest
Conformance 10/34/0
TECH_DEBT 5 FIXED / 5 NEEDS_REVALIDATION
cleanup COMPLETE
Run #60 final baseline
```

Lab：

```text
Evidence/Utility:
    IMPLEMENTATION_IN_PROGRESS / UNPROVEN

ReasoningBank:
    historical/partially executed
    no automatic resume

Adaptive Memory v0.1:
    engineering complete
    special-policy benefit unestablished
```

### 完成标准

- 所有“PLANNED_NOT_STARTED / IMPLEMENTATION_IN_PROGRESS / PAUSED”标签按真实执行状态统一；
- 不改历史报告；
- 不覆盖旧 Goal 状态，只在 current-status 文档说明当前主线。

---

## Goal 3A-1 — Worker `--once` Revalidation

### 目标

确认 `milai-worker --once` 的真实 contract，并判断该 TECH_DEBT 是否只是历史文档不足。

### 当前候选语义

```text
startup
→ dependency/settings initialization
→ blob orphan reconciliation
→ one bounded worker cycle
→ projection watermark reconciliation when applicable
→ database close
→ exit
```

`--once` 不等于“处理一个事件”，而是“执行一次 bounded cycle”。

### 测试矩阵

| Case | Expected |
|---|---|
| empty queue | ping/cycle 后正常退出 |
| queue below limit | 处理全部 eligible items |
| queue above limit | 按 `worker_event_limit` 截断 |
| multiple projections | 每个 projection 受各自 bounded cycle 控制 |
| orphan exists | cycle 前执行 orphan reconciliation |
| no projection work | 不 sleep，不进入持续 polling |
| processing failure | 非零退出或明确 fail-closed |
| `--check` | 不 lease queue，不处理事件 |
| watermark | 有 work 时执行 reconciliation |

### 输出

```text
docs/revalidation/worker-once/
    REVALIDATION.md
    receipt.json
```

### 决策

如果实现与 runbook 一致：

```text
NEEDS_REVALIDATION → FIXED
```

若文档不一致但行为合理：

```text
修文档
NEEDS_REVALIDATION → FIXED
```

只有真实安全/一致性缺陷才：

```text
NEEDS_REVALIDATION → OPEN
```

---

## Goal 3A-2 — Host Continuity Contract

### 合并处理的两个 debt

```text
process-local task continuity/state
cache-miss Host continuation
```

### 核心设计原则

明确区分：

```text
Native Execution Identity
vs
Persistent Memory Continuation Identity
```

#### Native Execution Identity

```text
host_instance
task_session
task_operation
task_generation
execution_lane
```

生命周期：

```text
process-local
```

负责：

```text
CONTINUE
SWITCH
SUBTASK
RETURN
operation replay rejection
delayed result binding
ABA generation protection
```

Host restart 后不得把旧 `TaskRegistry` 当作当前 execution identity。

#### Persistent Memory Continuation Identity

由 Runtime/Canonical/Context/Continuation substrate 管理：

```text
Evidence
Canonical state
ContextCapsule
retrieval continuation
explicit Working State
```

允许跨进程恢复，但必须重新授权和重新验证。

### 推荐 contract

```text
Host restart
→ old process-local task graph ends
→ new native TASK_START
→ old retained Host cache cannot be blindly reused
→ Runtime reauthorization
→ fresh memory need resolution
→ fresh/exact Context validation
→ persisted memory may be reacquired
```

### 测试矩阵

| Scenario | Expected |
|---|---|
| same process + same session + new operation | CONTINUE |
| same process + duplicate operation | reject |
| SWITCH | old task suspended，新 task active |
| delayed result after SWITCH | 仍绑定 origin task |
| ABA same task ID/new generation | old execution token orphan |
| Host restart + same session | TASK_START |
| Host restart + old cache locator | 禁止直接 reuse |
| restart + persisted Runtime memory | fresh recall 可以重新取得 |
| cache miss | exact/fresh recovery |
| canonical position changed | old reuse rejected |
| scope/profile changed | reuse prohibited |
| Runtime unavailable | fail closed |
| old native token after restart | reject/orphan |

### 输出

```text
docs/revalidation/host-continuity/
    REVALIDATION.md
    receipt.json
```

先诊断，不预设需要行为修改。

---

## Goal 3A-3 — Resolver Lexical / Language Diagnostic

### 当前风险

`DeterministicMemoryNeedResolver` 会直接选择：

```text
NONE
L0
L1
```

而其输入解释依赖：

- 英文 token regex；
- 英文 stopwords；
- 中英文特定正则；
- 固定 alias family；
- lexical term overlap；
- hard-coded decision bonus。

因此它是 production routing seam，不只是提示性辅助逻辑。

### 第一阶段只做诊断

建立冻结 corpus：

```text
English
Chinese
mixed-language
paraphrase
synonym
short imperative
identifier-heavy query
exact state request
history request
conflict request
retry request
no-memory request
ambiguous state-key request
```

每条记录：

```text
expected intent
expected route
expected state-key binding
actual intent
actual route
actual key
reason_code
```

### failure family

```text
INTENT_MISS
FALSE_RECALL
WRONG_ROUTE
STATE_KEY_MISS
STATE_KEY_AMBIGUITY
LANGUAGE_TOKENIZATION
ALIAS_OVERFIT
RETRY_CARRYOVER_ERROR
```

### 禁止

首轮不得：

```text
❌ 引入 LLM resolver
❌ 改 routing weights
❌ 改 Retrieval ranking
❌ 新增 hidden retrieval
```

### 如果需要修复

优先级：

```text
structured Host signal
→ exact known StateKey match
→ Unicode-normalized typed matching
→ language-neutral lexical fallback
→ minimal regex fallback
```

---

# 5. Phase 3B — Measurement Foundation

## Goal 3B-1 — Trace Ownership v1

这是下一阶段最重要的工程 Goal。

### 问题

当前已有 Runtime trace、Context trace、Host trace 和 Provider usage，但 ownership 没有被统一成一个正式 contract。

后续研究必须明确：

```text
谁能证明 acquisition？
谁能证明 selection？
谁能证明 exposure？
谁能证明 observable use？
谁能证明 outcome？
谁能证明 revision？
```

### Ownership

| Layer | Owns |
|---|---|
| Runtime | acquisition、gate、binding、canonical position、Context assembly |
| MCP | authorized tool invocation、transport boundary |
| Host | task binding、memory request、Context injection、provider invocation |
| Provider | native request ID、usage、terminal generation result |
| Lab | experimental arm、task score、reward、revision attribution |

禁止：

```text
Host 重新解释 Runtime Gate
MCP 声称 answer correctness
Runtime 声称模型使用了 Memory
Product 消费 Lab hidden result label
```

---

## Trace Join Contract

建立稳定 join：

```text
host_attempt_trace_id
        ↓
retrieval_trace_id
        ↓
decision_snapshot_digest
        ↓
evidence_set_digest
        ↓
reader_context_sha256
        ↓
provider_native_request_id
        ↓
Lab result_ref
        ↓
memory version/revision
```

### Use 定义

严格区分：

```text
ACQUIRED
SELECTED
EXPOSED
OBSERVABLY_USED
OUTCOME_ASSOCIATED
CAUSALLY_ATTRIBUTED
```

Product 只能可靠证明前三者。

以下才可作为 `OBSERVABLY_USED` 的候选：

```text
explicit evidence alias
structured citation/reference
tool-mediated memory reference
revision based on a named memory version
```

只进入 Prompt：

```text
EXPOSED != USED
```

没有 observable support：

```text
use = UNKNOWN
```

### 首版实现

尽量作为：

```text
Lab join artifact + Product/Host testkit
```

不要新增 Product DB schema。

---

## Goal 3B-2 — Memory Opportunity Ledger

### 目的

避免以后继续用“跑了多少题”代替“机制真正有多少次机会生效”。

统一记录：

```text
memory_available
retrieved_candidate_count
meaningful_alternative_count
selected_versions
exposed_versions
explicit_adoption
explicit_rejection
observable_use
task_outcome
revision_opportunity
revision_created
later_retrieval
later_exposure
later_use
```

### 以后所有实验都报告 funnel

例如：

```text
100 tasks
32 memory available
18 meaningful alternatives
11 selector changed choice
7 selected memory exposed
4 observable use
3 revision opportunities
2 revisions reused later
```

这比：

```text
100 tasks / 57 correct
```

更能回答 Memory 机制是否真正工作。

---

# 6. Phase 3C — Adaptive Memory Research

## 研究约束

这一阶段默认 **Lab-only**。

禁止：

```text
Product schema change
MCP tool addition
Runtime routing modification
default behavior change
```

只有独立确认后才考虑 Product。

---

## Goal 3C-1 — Utility Selection

### 当前基础

现有 `VersionUtility` 已经正确避免：

```text
task success
→ 每张 exposed card +1
```

它把 outcome 绑定到：

```text
ordered exposure sequence
```

这是正确方向。

### 实验问题

> 历史 utility 信息是否会改变 memory selection，并带来稳定的质量/成本收益？

### 入组条件

只选：

```text
retrieved candidates >= 2
meaningful alternatives >= 2
历史 utility 可区分
```

没有 selector choice 的任务不计入机制 denominator。

### Arms

```text
STATIC
UTILITY
```

保持：

```text
same task
same retrieved candidate pool
same model
same tools
same generation budget
same context budget
```

只改变 selection。

### 指标

主指标：

```text
selection_change_rate
observable_use_rate
task_success_delta
task_quality_delta
token_delta
latency_delta
harm/regression count
```

### Stop Gate

如果：

```text
selector 几乎不改变选择
```

则：

```text
STOP: insufficient mechanism opportunity
```

如果 selection 改变但 outcome 无收益：

```text
STOP / redesign utility signal
```

不直接扩大样本。

---

## Goal 3C-2 — Evidence-grounded Revision

### 问题

历史 revision 中存在：

```text
example refresh
unsupported correction
scope expansion
incorrect rationale
```

因此必须先把 revision 类型化。

### Revision taxonomy

```text
CORRECTION
SCOPE_NARROWING
SCOPE_EXPANSION
EXAMPLE_REFRESH
RETIRE
```

核心收益评价只计：

```text
CORRECTION
SCOPE_NARROWING
```

`EXAMPLE_REFRESH` 不作为纠错收益。

### Revision input

必须同时具备：

```text
old memory version
original supporting evidence
current feedback
```

### Revision output

```text
new version
predecessor
changed claims
changed applicability
reason
evidence refs
feedback refs
```

### 有效 denominator

只有：

```text
revision created
→ later task retrieves lineage
→ revised version exposed
```

才进入 Revision effect denominator。

没有 later reuse：

```text
maintenance cost only
```

### Arms

```text
APPEND_ONLY
REVISION
```

如果需要再加：

```text
REVISION_WITHOUT_SOURCE_CHECK
```

只能作为诊断，不作为候选主方法。

---

## Goal 3C-3 — State-guided Attention v0.1

这是下一阶段最值得探索的核心创新。

### 目标

使用 Host/Task State 动态分配有限 Memory attention，而不是所有 query 使用固定 retrieval pattern。

### State

首版只使用已有或 Lab 可显式构造的字段：

```text
current_question
active_goal
hypotheses
failed_approaches
unresolved_constraints
next_actions
memory_intentions
uncertainty
open_conflicts
recent_evidence
```

### Attention Mode

首版只使用三个离散 mode：

```text
FOCUS
CONFLICT
EXPLORE
```

#### FOCUS

优先：

```text
current goal
explicit entities
current state
direct evidence
```

#### CONFLICT

优先：

```text
OpenIssue
contradiction
failure history
alternative branch
negative evidence
```

#### EXPLORE

有界扩大：

```text
related experience
adjacent source
different strategy
failed-approach alternative
```

### Attention Policy 输出

```json
{
  "mode": "CONFLICT",
  "focus_budget": 4,
  "conflict_budget": 4,
  "explore_budget": 2,
  "reason": "OPEN_CONFLICT_PRESENT"
}
```

### 首版要求

```text
deterministic
bounded
traceable
no extra controller LLM
```

### Retrieval pipeline

```text
State
 ↓
Focused Retrieval
 ↓
Coverage / Confidence Check
 ↓
If insufficient
 ↓
Bounded Divergent Expansion
 ↓
Evidence / Utility / Conflict scoring
 ↓
Convergence
 ↓
Context
```

### 第一阶段指标

不要先追 Answer score。

先看：

```text
unnecessary retrieval ↓
irrelevant exposure ↓
required evidence coverage ↑
conflict coverage ↑
tokens ↓
latency ↓
task quality non-regression
```

只有这些成立后才进入 answer-effect 扩样本。

---

## Goal 3C-4 — RL-like Online Policy Adaptation

### 原则

借鉴 MemRL 的：

```text
experience
→ outcome
→ value update
→ future selection
```

而不是训练 controller model。

### 学习对象

不是 LLM weights，而是：

```text
Memory Policy State
```

可包含：

```text
memory-version utility
bundle utility
attention-mode utility
policy-action utility
```

### 首版更新方式

使用可解释 bounded incremental update。

不要引入：

```text
deep RL
policy-gradient
online model fine-tuning
hidden reward model
```

### Credit Assignment

如果一个 request 同时 exposed：

```text
A
B
C
```

成功后不得：

```text
A += reward
B += reward
C += reward
```

首版保持：

```text
bundle-level
or
ordered-exposure-sequence-level
```

只有 counterfactual/ablation 后才拆 item contribution。

---

# 7. Phase 3D — Transfer / Multi-session Confirmation

这一阶段有严格准入。

必须先满足：

```text
Utility
or Revision
or Attention
```

至少一个机制在 matched DEV comparison 中有：

```text
mechanism activated
repeatable signal
acceptable cost
no new safety regression
```

否则不进入大规模 transfer。

---

## 正式主表

只保留四个主要方法：

```text
Native
OM
ReasoningBank
MiLAi
```

内部 candidate variant：

```text
STATIC
UTILITY
REVISION
ATTENTION
```

只做 mechanism ablation，不全部放入主表。

---

## Protocol 1 — Frozen Bank Transfer

```text
support tasks
→ form/freeze bank
→ unseen evaluation tasks
→ no evaluation writes
```

回答：

> 经验是否真正泛化到未参与形成的新任务？

---

## Protocol 2 — Online Stream

```text
task 1
→ outcome
→ update
→ task 2
→ outcome
→ update
...
```

对照必须：

```text
same ordering
same visible feedback
same budget
```

不能简单比较前半程 vs 后半程。

---

## Protocol 3 — Dependent Multi-session

使用完整会话依赖：

```text
session A
→ persons/plans/constraints
→ session B
→ session C
```

禁止：

```text
把每个 session 独立 reset
```

主要验证：

```text
historical constraint preservation
revision carry-over
task-person identity
plan continuity
```

---

## 第二 Solver

继续 deferred。

只有在：

```text
核心政策已冻结
+
单 solver unseen confirmation 有信号
```

之后再启用第二 solver。

---

# 8. Phase 3E — Product Promotion Gate

任何新机制进入 Product 前必须经过：

```text
Lab prototype
    ↓
Pinned Product baseline
    ↓
Matched comparison
    ↓
Mechanism actually activated
    ↓
Independent unseen confirmation
    ↓
Benefit / cost / safety
    ↓
Architecture impact review
    ↓
Product ADR
    ↓
Minimal behavior PR
```

### 不满足时

允许终局：

```text
KEEP_LAB_ONLY
KEEP_SIMPLE
NO_PROMOTION
```

这不是失败。

---

# 9. 建议 PR / Goal 顺序

| Order | Goal | 类型 | Product 行为改动 |
|---:|---|---|---|
| 1 | Status Reconciliation | docs | 否 |
| 2 | worker `--once` revalidation | Product evidence | 大概率否 |
| 3 | Trace Ownership v1 | Product/Testkit | 小 |
| 4 | Host Continuity diagnosis | Product evidence | 否 |
| 5 | Host Continuity remediation | Product | 仅诊断 FAIL 时 |
| 6 | Resolver lexical diagnostic | Product/Lab tests | 否 |
| 7 | Resolver remediation | Product | 仅诊断 FAIL 时 |
| 8 | Memory Opportunity Ledger | Lab | 否 |
| 9 | Utility Selection | Lab research | 否 |
| 10 | Evidence-grounded Revision | Lab research | 否 |
| 11 | State Attention v0.1 | Lab research | 否 |
| 12 | RL-like policy adaptation | Lab research | 否 |
| 13 | Transfer / Multi-session | Lab research | 否 |
| 14 | Product Promotion ADR | Product docs | 条件性 |
| 15 | Minimal Product candidate | Product | 条件性 |

---

# 10. 推荐分支命名

```text
docs/post-cleanup-status-reconciliation

behavior/revalidate-worker-once

behavior/trace-ownership-v1

behavior/host-continuity-diagnosis
fix/host-continuity-<specific-gap>

research/resolver-language-diagnostic
fix/memory-need-resolver-<specific-gap>

research/memory-opportunity-ledger

research/utility-selection-v1
research/evidence-grounded-revision-v1
research/state-attention-v1
research/policy-adaptation-v1

research/transfer-confirmation-v1
```

---

# 11. 测试策略

继续使用 cleanup 后的 local-first cadence。

## Product diagnosis / remediation

开发中：

```text
targeted unit
targeted integration
Ruff
mypy
```

最终 candidate：

```text
affected package
manifest
receipt verifier
Conformance
boundary
full composition once
```

不再每个小 commit 跑全部 replay。

---

## Lab-only research

开发：

```text
targeted Lab tests
Ruff
mypy
boundary
runner smoke
```

实验前：

```text
frozen manifest
input hash
model/profile pin
budget
stop gate
```

实验后：

```text
usage settlement
output hash
trace join
result ledger
```

Product tree 不变时：

```text
不跑完整 Product composition
```

---

# 12. Research Execution Discipline

每一个实验必须先写：

```text
QUESTION
MECHANISM
OPPORTUNITY DENOMINATOR
ARM DIFFERENCE
PRIMARY METRIC
COST METRIC
SAFETY METRIC
STOP CONDITION
PROMOTION CONDITION
```

没有这些字段：

```text
不启动模型调用
```

---

# 13. Stop Gates

## Utility

```text
if selection_change_rate ≈ 0:
    STOP
```

## Revision

```text
if no later reuse opportunity:
    STOP
```

## Attention

```text
if irrelevant exposure/cost does not improve:
    STOP
```

## Policy adaptation

```text
if learned value never changes later action:
    STOP
```

## Transfer

```text
if DEV has no repeatable mechanism signal:
    DO NOT ENTER HOLDOUT
```

---

# 14. 项目级指标

后续不再只汇总：

```text
tests passed
tasks completed
tokens consumed
```

必须固定以下 funnel：

```text
Memory Available
Memory Retrieved
Meaningful Alternatives
Memory Selected
Memory Exposed
Observable Use
Outcome
Revision Opportunity
Revision Created
Later Retrieved
Later Exposed
Later Used
```

以及成本：

```text
retrieval calls
embedding calls
model generations
input tokens
output tokens
maintenance tokens
latency
failed requests
unknown usage
```

---

# 15. 产品与研究边界

## Product

保持：

```text
reliable substrate
governance
identity
state
evidence
retrieval
context
receipts
policy hooks
```

## Lab

拥有：

```text
attention
utility
revision
transfer
online policy adaptation
mechanism comparison
experimental credit assignment
```

目标架构：

```text
Product
  reliable substrate
  state
  evidence
  receipt
  policy hooks
       ↑
Lab
  attention
  utility
  revision
  transfer
  policy learning
```

除非通过 Promotion Gate，不把 Lab intelligence 下沉 Product。

---

# 16. 下一阶段优先级

## P0

```text
Status reconciliation
worker --once revalidation
Trace Ownership
```

## P1

```text
Host Continuity
Resolver language diagnostic
Memory Opportunity Ledger
```

## P2

```text
Utility Selection
Evidence-grounded Revision
```

## P3

```text
State-guided Attention
RL-like adaptation
```

## P4

```text
Transfer
Multi-session
Second solver
Product promotion
```

---

# 17. 完成定义

## Phase 3A COMPLETE

```text
[ ] 5 NEEDS_REVALIDATION 均有证据化分类
[ ] 无未解释 OPEN debt
[ ] Product status docs current
```

## Phase 3B COMPLETE

```text
[ ] Trace Ownership contract 固定
[ ] Acquisition→Selection→Exposure→Use join 可执行
[ ] Opportunity Ledger 可从真实运行生成
```

## Phase 3C COMPLETE

```text
[ ] Utility 有 matched comparison
[ ] Revision 有真实 later-reuse denominator
[ ] Attention 有成本/证据质量比较
[ ] 至少一个机制出现 repeatable signal，或全部得到 KEEP_SIMPLE 结论
```

## Phase 3D COMPLETE

```text
[ ] unseen/frozen-bank confirmation
[ ] online stream comparison
[ ] dependent multi-session comparison
[ ] 成本、失败和安全结果完整
```

## Phase 3E COMPLETE

以下二者之一即可：

```text
A. Product promotion:
   ADR accepted
   minimal behavior PR
   new current-tree receipts
   full composition PASS
```

或：

```text
B. No promotion:
   evidence supports KEEP_LAB_ONLY / KEEP_SIMPLE
   Product baseline unchanged
```

---

# 18. 总体决策原则

后续开发不再以“Memory 系统越来越复杂”为成功标准。

真正的成功标准是：

```text
更少的无效检索
更少的无关暴露
更可靠的证据使用
更准确的适用范围
更低的维护成本
更好的后续任务表现
更清楚的因果归因
```

MiLAi 下一阶段最值得验证的核心研究命题应统一为：

> **Evidence-grounded, State-conditioned, Utility-adaptive, Attention-controlled Memory**

其最小闭环是：

```text
Evidence
   ↓
Memory Version
   ↓
Utility
   ↓
State
   ↓
Attention
   ↓
Selective Retrieval
   ↓
Observable Use
   ↓
Outcome
   ↓
Revision
   ↺
```

只有这个闭环在真实任务中出现可重复收益之后，再考虑把机制推进 Product。
