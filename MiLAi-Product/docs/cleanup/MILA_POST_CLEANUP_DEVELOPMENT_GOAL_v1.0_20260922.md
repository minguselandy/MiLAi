---
goal_id: MILAI-POST-CLEANUP-DEVELOPMENT-01
version: v1.0
date: 2026-09-22
status: PAUSED_FOR_GPT6_HANDOFF
kind: PRODUCT_BEHAVIORAL_CLOSURE_AND_LAB_RESEARCH
source_roadmap: docs/cleanup/MILA_POST_CLEANUP_DEVELOPMENT_ROADMAP_v1.0_20260922.md
source_roadmap_sha256: fcf2bb29da976f1db1ab2fb00a6a989b49346ef1a2466cdc553d1deed0b40e9e
baseline_commit: dfeb359d2301b99c0125d9e54e9c29a9025d7f59
baseline_git_tree: 8b08c84e8d13d82e513034d690be057dc159722b
product_tree_sha256: 7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521
frozen_architecture: 1.0.0
schema_status: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
paused_at: 2026-09-22T08:24:12+08:00
pause_reason: USER_REQUESTED_MIGRATION_TO_GPT6
handoff_document: docs/cleanup/MILA_GPT6_PROJECT_HANDOFF_GUIDE_v1.0_20260922.md
current_work_package: 3A-0_STATUS_RECONCILIATION_SUBMITTED_PENDING_REMOTE_CLOSURE
next_work_package: VERIFY_AND_MERGE_PR_27_THEN_START_3A-1
new_experiment_allocations: 0
new_model_requests: 0
---

# MiLAi Cleanup 后开发与研究执行 Goal v1.0

## 0. 本文件的作用

本文件把《MiLAi 后续开发与研究推进规划 v1.0》转换为可执行、可停止、可审计的 Goal。
路线图定义方向，本 Goal 定义执行状态、依赖、准入、PR 边界、证据、停止条件和终局。

本次文档生成只完成 Goal 注册：

```text
不修改 Product 或 Lab 行为
不启动、恢复或停止历史实验
不调用模型、Provider 或 Judge
不分配 generation/token 额度
不修改历史结果或 Frozen Architecture
不改变 Schema 状态
```

进入任何需要模型、外部 Provider、formal pool、共享服务或长期进程的工作包前，必须另有明确的
有限预算、输入、停止条件和执行授权。本文件不能被解释为无限实验授权。

---

# 1. Objective

在 cleanup C0–C10 已完成的稳定边界上，依次完成：

1. Product 剩余行为债务的证据化分类；
2. Runtime、MCP、Host、Provider 与 Lab 的 trace ownership 和 join contract；
3. Memory opportunity、selection、exposure、observable use、outcome 与 revision 的可计算账本；
4. Lab-only 的 Utility、Evidence-grounded Revision、State-guided Attention 和 RL-like policy
   adaptation 的最小可证伪研究；
5. 仅在机制实际激活且有独立收益证据时进入 transfer、multi-session 和 Product promotion；
6. 若收益不成立，以 `KEEP_SIMPLE`、`KEEP_LAB_ONLY` 或 `NO_PROMOTION` 形成同样有效的终局。

```text
Behavioral Closure
    ↓
Trace Ownership + Join Contract
    ↓
Memory Opportunity Ledger
    ↓
Utility → Revision → Attention → Policy Adaptation
    ↓
Independent Transfer / Multi-session Confirmation
    ↓
Promotion or No-promotion Decision
```

本 Goal 不以代码量、PASS 数量、实验数量或机制复杂度为成功标准。成功标准是行为边界更明确、
因果归因更诚实、无效检索与暴露更少、成本可结算，并得到支持“推广”或“不推广”的证据。

---

# 2. Authority and baseline

## 2.1 权威顺序

1. `SOURCE_OF_TRUTH.md`、根 `AGENTS.md`；
2. `MiLAi-Product/architecture/v1.0/**` 与 Product `AGENTS.md`；
3. 当前 Product contracts、迁移、实现和可执行测试；
4. Lab `AGENTS.md`、冻结协议、run-specific Product lock 与实验 manifest；
5. 本 Goal；
6. 源路线图；
7. 历史 Goal、报告和 Archive，仅作为不可改写的证据。

路线图与当前可执行事实冲突时，不静默改代码来迎合路线图；必须记录 drift，并明确采用的事实。

## 2.2 注册基线

```text
Repository:                    minguselandy/MiLAi
main commit:                   dfeb359d2301b99c0125d9e54e9c29a9025d7f59
main Git tree:                 8b08c84e8d13d82e513034d690be057dc159722b
Product manifest files:        422
Product manifest SHA-256:      7927bb6a0cad2ed139a7ce05f34f64cd47e3c0cd75bb77ff431a433b83c0c693
Product tree SHA-256:          7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521
Architecture manifest:         ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e
Architecture version:          1.0.0
Conformance:                   10 PASS / 34 UNVERIFIED / 0 DEVIATION
Conformance overall:           UNVERIFIED
TECH_DEBT:                     5 FIXED / 5 NEEDS_REVALIDATION / 0 OPEN
Cleanup:                       C0–C10 COMPLETE
Authoritative full workflow:   Run #60 / ID 35632657133 / 17 jobs PASS
Schema:                        0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
```

不可变树对象：

```text
MiLAi-Product/architecture/v1.0  fb9f953e07e9a06bd08695827dd91ccb0d21be38
MiLAi-Lab/studies/archive        b69ac4d6ebca0a52ae3ec6edff5dce914816f157
MiLAi-Artifact-Archive           36ac04b4b0562265250bb15f01a4d40c4ac4f710
```

## 2.3 基线解释

- `10/34/0` 是证据状态，不是机械刷全 PASS 的 KPI。
- `NEEDS_REVALIDATION` 不是 `OPEN`；必须先诊断。
- Cleanup Run #60 不自动证明后续行为改动。
- `MiLAi-Lab/product.lock.json` 是历史 pin，不自动代表本 Goal baseline。新的 Product-backed
  effect run 必须生成并验证 run-specific lock，旧 lock 不覆盖。
- Product 默认行为保持现状，直到 Phase 3E Promotion Gate 通过。

---

# 3. Non-goals and immutable boundaries

## 3.1 明确不做

```text
不继续全仓结构拆分或为了减小文件而重构
不为增加 Conformance PASS 数量补无意义测试
不在机制未激活前扩大 benchmark/formal holdout
不把 EXPOSED 写成 USED
不把 task success 平均奖励给全部 Memory
不把 Lab prototype 直接下沉 Product 默认路径
不引入 LLM controller 替代确定性首版
不建设 deep-RL、policy-gradient、online fine-tuning 或 hidden reward 平台
不自动恢复暂停实验
不自动启用第二 solver
```

## 3.2 Product 不变量

- PostgreSQL Canonical Core 仍是正式状态唯一权威。
- Evidence 是 observation，不是 accepted truth。
- ClaimVersion、transition、decision 与 issue history 保持 append-only。
- ClaimHead 只通过 exact-head CAS 移动。
- Search、Context、模型、adapter 与 projection 不得提高 authority。
- permission、scope、tenant、retention、revocation 与 Runtime unavailable 继续 fail closed。
- Evidence revocation 同步阻断 authority；derived cleanup 可以异步。
- secondary index failure 只能降低 recall，不能提高 authority。
- canonical unavailable 或 evidence insufficient 必须显式 abstain。

## 3.3 文件、接口和研究边界

- 不原地修改 `architecture/v1.0/**`，不重写 migration 0001–0049。
- 未经 Promotion Gate，不新增 Product schema、MCP tool、Runtime route 或默认 routing。
- Product 不导入 Lab/Archive；Lab 只用 public interface/testkit/read-only trace contract。
- 历史 receipts、failures、results、sealed inputs 与 Archive bytes 不覆盖、不改写。
- 不提交 secret、raw private content、模型权重、Provider transcript、数据库 dump 或运行日志。
- 若需要 schema、migration、permission、canonical 或 public API 改动，停止当前包并另开 ADR/Goal。

```text
Product owns:
  reliable substrate, identity, authorization, canonical state,
  evidence, retrieval, context, product trace facts, public hooks

Lab owns:
  experimental arms, utility, attention, revision policy,
  mechanism comparison, reward attribution, transfer evaluation
```

Product 可证明 acquisition、selection 和 exposure；仅因 Memory 进入 prompt 不得声称模型使用了它。

---

# 4. State machine and phase ledger

## 4.1 Goal 状态

```text
READY_FOR_EXECUTION
  → ACTIVE
  ↔ PAUSED_FOR_GPT6_HANDOFF
  → COMPLETE_PROMOTED
  → COMPLETE_NO_PROMOTION
```

异常终态：`BLOCKED_EXTERNAL_AUTHORITY`、`BLOCKED_INVALID_EVIDENCE`、
`STOPPED_SAFETY_REGRESSION`、`SUPERSEDED_BY_REVIEWED_GOAL`。

本文件生成时为 `READY_FOR_EXECUTION`；3A-0 启动后改为 `ACTIVE`。用户随后要求暂停并迁移
到 GPT-6，当前状态为 `PAUSED_FOR_GPT6_HANDOFF`。该状态不是完成、失败或实验恢复授权。

工作包只使用：

```text
PENDING / IN_PROGRESS / PASS / FAIL_REMEDIATION_REQUIRED
KEEP_SIMPLE / KEEP_LAB_ONLY / NOT_ADMITTED / BLOCKED
```

## 4.2 TECH_DEBT 决策

```text
NEEDS_REVALIDATION
  ├─ behavior and docs agree       → FIXED
  ├─ behavior correct, docs drift  → docs repair → FIXED
  ├─ item no longer applies        → OBSOLETE
  └─ reproducible behavior gap     → OPEN + separate remediation Goal
```

不得用代码阅读或单一 happy path 直接分类。

## 4.3 Ledger

| ID | Work package | Owner | Product behavior | Status | Entry gate |
| --- | --- | --- | --- | --- | --- |
| G0 | Goal registration | docs | no | COMPLETE | roadmap bound |
| 3A-0 | Status reconciliation | Product/Lab docs | no | IN_PROGRESS — PR #27 pending | G0 |
| 3A-1 | Worker `--once` revalidation | Product evidence | expected no | PENDING | 3A-0 |
| 3B-1 | Trace Ownership v1 | Product/testkit + Lab | small/contractual | PENDING | 3A-0 |
| 3A-2D | Host Continuity diagnosis | Product evidence | no | PENDING | 3B-1 vocabulary |
| 3A-2R | Host Continuity remediation | Product | conditional | NOT_ADMITTED | 3A-2D FAIL |
| 3A-3D | Resolver diagnostic | Product/Lab tests | no | PENDING | 3A-0 |
| 3A-3R | Resolver remediation | Product | conditional | NOT_ADMITTED | 3A-3D FAIL |
| 3B-2 | Memory Opportunity Ledger | Lab | no | PENDING | 3B-1 PASS |
| 3C-1 | Utility Selection | Lab | no | PENDING | 3B-2 real-run proof |
| 3C-2 | Evidence-grounded Revision | Lab | no | PENDING | 3B-2 + lineage |
| 3C-3 | State-guided Attention | Lab | no | PENDING | 3B-2 + frozen state |
| 3C-4 | RL-like adaptation | Lab | no | NOT_ADMITTED | prior mechanism acts |
| 3D-1 | Frozen-bank transfer | Lab | no | NOT_ADMITTED | repeatable DEV signal |
| 3D-2 | Online stream | Lab | no | NOT_ADMITTED | frozen policy/order |
| 3D-3 | Dependent multi-session | Lab | no | NOT_ADMITTED | frozen continuity protocol |
| 3D-4 | Second solver | Lab | no | NOT_ADMITTED | signal + user authorization |
| 3E-1 | Promotion decision | docs | no | PENDING | terminal research evidence |
| 3E-2 | ADR/minimal candidate | Product | conditional | NOT_ADMITTED | PROMOTE decision |
| GF | Final evidence closure | cross-repo | no extra behavior | PENDING | terminal path |

依赖硬规则：

```text
Trace Ownership before Opportunity Ledger
Opportunity Ledger before mechanism-effect experiments
Diagnosis before remediation
Repeatable DEV signal before holdout/transfer
Independent confirmation before Product promotion
```

---

# 5. Phase 3A — Product Behavioral Closure

## 5.1 3A-0 Status Reconciliation

只更新 current status/goals：

```text
MiLAi-Product/docs/PRODUCT_CURRENT_STATUS.md
MiLAi-Product/docs/PRODUCT_GOALS.md
MiLAi-Lab/docs/LAB_CURRENT_STATUS.md
MiLAi-Lab/docs/LAB_GOALS.md
```

Product 必须写清 exact main/tree/manifest、Conformance `10/34/0`、TECH_DEBT `5/5/0`、cleanup
COMPLETE、Run #60 和 Schema NO-GO。Lab 必须区分 Evidence/Utility 当前实现、ReasoningBank 历史
执行与暂停范围、Adaptive Memory 工程完成但收益未建立，并明确旧实验不自动恢复。

历史报告不改；旧 Goal 状态保留为当时快照。退出条件：四份 current 文档一致、链接有效、无行为
diff、L0 和 docs-only fast CI PASS。

## 5.2 3A-1 Worker `--once` Revalidation

问题：`milai-worker --once` 是否实现“一次 bounded worker cycle”，并具有明确退出合同？

```text
startup
→ settings/dependency initialization
→ blob orphan reconciliation
→ one bounded worker cycle
→ watermark reconciliation when applicable
→ database close
→ exit
```

`--once` 不等于“只处理一个事件”。必测：empty queue、below/above limit、multiple projections、
orphan、no projection work、processing failure、`--check`、watermark work。queue/lease/watermark/
orphan/exit 结论必须有真实 PostgreSQL 证据。

输出：

```text
docs/revalidation/worker-once/REVALIDATION.md
docs/revalidation/worker-once/receipt.json
docs/revalidation/INDEX.md
docs/TECH_DEBT.md
```

receipt 绑定 Product commit/tree、DB identity、命令、node/case IDs、正负结果与限制。

## 5.3 3A-2 Host Continuity

分别覆盖：

```text
process-local task continuity/state
cache-miss Host continuation
```

Native Execution Identity（`host_instance/task_session/task_operation/task_generation/execution_lane`）
是 process-local，负责 replay rejection、delayed result binding 和 ABA protection。Persistent
Memory Continuation Identity 由 Runtime/Canonical/Context/Working State 管理，可跨进程重新取得，
但必须重新授权与验证。

```text
Host restart
→ old native graph ends
→ new TASK_START
→ no blind old-cache reuse
→ Runtime reauthorization
→ fresh memory-need resolution
→ fresh/exact Context validation
→ persisted memory may be reacquired
```

必须覆盖：same-process CONTINUE、duplicate reject、SWITCH、delayed result、ABA generation、restart
same session、old locator、persisted Runtime memory、cache miss、canonical change、scope/profile change、
Runtime unavailable、old native token。

首 PR 只做 diagnosis。FAIL 时保留失败、受影响 debt 转 OPEN、另建
`fix/host-continuity-<specific-gap>` 和独立 remediation receipt。

输出：

```text
docs/revalidation/host-continuity/REVALIDATION.md
docs/revalidation/host-continuity/receipt.json
conditional: remediation.receipt.json
```

## 5.4 3A-3 Resolver Language Diagnostic

冻结 English、Chinese、mixed-language、paraphrase、synonym、short imperative、identifier-heavy、
exact-state、history、conflict、retry、no-memory 与 ambiguous-state-key corpus。每例记录 expected/
actual intent、route、key 与 reason code。

failure family：

```text
INTENT_MISS / FALSE_RECALL / WRONG_ROUTE / STATE_KEY_MISS
STATE_KEY_AMBIGUITY / LANGUAGE_TOKENIZATION / ALIAS_OVERFIT
RETRY_CARRYOVER_ERROR
```

首轮禁止 LLM resolver、weight/ranking/budget 变化和 hidden retrieval。若需修复，顺序固定为：

```text
structured Host signal
→ exact StateKey
→ Unicode-normalized typed matching
→ language-neutral lexical fallback
→ minimal regex fallback
```

不得加入 case ID、gold term 或 benchmark-specific synonym。

输出：

```text
docs/revalidation/resolver-language/REVALIDATION.md
docs/revalidation/resolver-language/corpus.json
docs/revalidation/resolver-language/receipt.json
conditional: remediation.receipt.json
```

## 5.5 Phase 3A exit

```text
[ ] five NEEDS_REVALIDATION items have executable classifications
[ ] no unexplained OPEN debt
[ ] Product/Lab current docs agree
[ ] diagnosis and remediation evidence remain distinct
```

“无未解释 OPEN”不隐藏缺陷；它要求每个 OPEN 有 owner、scope、risk 和下一步。

---

# 6. Phase 3B — Measurement Foundation

## 6.1 3B-1 Trace Ownership v1

| Layer | Owns | Must not claim |
| --- | --- | --- |
| Runtime | acquisition、gate、binding、canonical position、Context assembly | model used Memory |
| MCP | authorized invocation、transport boundary | answer correctness |
| Host | task binding、memory request、Context injection、provider invocation | reinterpret Runtime gate |
| Provider | native request ID、usage、terminal result | canonical truth |
| Lab | arm、score、reward、revision attribution | expose hidden labels to Product |

稳定 join：

```text
host_attempt_trace_id
→ retrieval_trace_id
→ decision_snapshot_digest
→ evidence_set_digest
→ reader_context_sha256
→ provider_native_request_id
→ Lab result_ref
→ exact memory version/revision
```

每个 key 说明 owner、cardinality、nullable 条件、redaction、retry、versioning 和 replay handling。

Memory-use 状态严格区分：

```text
ACQUIRED → SELECTED → EXPOSED → OBSERVABLY_USED
         → OUTCOME_ASSOCIATED → CAUSALLY_ATTRIBUTED
```

observable-use support 只接受 explicit evidence alias、structured citation/reference、tool-mediated
reference 或 named exact-version revision。无支持时 `use=UNKNOWN`；不能由 exposure 推断 true。

首版优先为 Product/Host public/read-only testkit + Lab join artifact，不新增 Product DB schema。
退出必须覆盖 success、retry、abstain、failure、no-memory、unknown-use，并通过脱敏与边界检查。

## 6.2 3B-2 Memory Opportunity Ledger

必需字段：

```text
run/arm/task/attempt identity
product_lock_digest / method / policy version
memory_available / retrieved_candidate_count / meaningful_alternative_count
selected_versions / exposed_versions
explicit_adoption / explicit_rejection / observable_use
task_outcome
revision_opportunity / revision_created
later_retrieval / later_exposure / later_use
retrieval_calls / embedding_calls / model_generations
input/output/maintenance tokens / latency / failures / unknown_usage
```

规则：meaningful alternatives 在 outcome 前冻结；selected 绑定 exact version；多版本保留 ordered
exposure sequence；adoption 不等于 use；failed/unknown request 保留成本；later reuse 必须发生在
revision 后；ledger 是 Lab artifact，不直写 Product canonical tables。

最小 proof 覆盖：no memory、single candidate、multiple alternatives、selected-not-exposed、
exposed-use-unknown、observable use、known/unknown usage failure、revision-never-reused、revision-later-used。

后续实验必须先报告 funnel：

```text
tasks → memory available → meaningful alternatives → selection changed
→ exposed → observable use → outcome → revision opportunity
→ revision → later retrieved → later exposed → later used
```

无 opportunity 的任务可进入总体质量/成本表，但不得进入 mechanism-effect denominator。

## 6.3 Phase 3B exit

```text
[ ] ownership contract versioned
[ ] join works for success/failure/retry/unknown
[ ] ledger generated from one real bounded run
[ ] deterministic ledger validation exists
[ ] hidden labels/private Product internals do not cross boundary
[ ] exact Product lock and method identity recorded
```

---

# 7. Phase 3C — Adaptive Memory Research

Phase 3C 默认 Lab-only。本 Goal 注册时研究预算均为 0。

## 7.1 Common preflight

每个实验先冻结：

```text
QUESTION / MECHANISM / OPPORTUNITY DENOMINATOR / ARM DIFFERENCE
PRIMARY METRIC / COST METRIC / SAFETY METRIC
STOP CONDITION / PROMOTION CONDITION
INPUT AND SPLIT HASHES / PRODUCT LOCK / METHOD / MODEL / PROFILE
MAX REQUESTS / TOKENS / WALL TIME
FAILURE AND UNKNOWN-USAGE SETTLEMENT
```

缺一项即 `DO NOT START MODEL CALLS`。arms 保持 same task、candidate pool、model、tools、generation
budget、context budget 和 visible feedback；差异必须显式记录为 confounder。

## 7.2 3C-1 Utility Selection

只纳入 candidates >= 2、meaningful alternatives >= 2、outcome 前 utility 可区分的机会。arms 为
`STATIC` 与 `UTILITY`，只改变 selection。

指标：selection change、observable use、task quality/success delta、token/latency delta、failure、
unknown usage、harm/regression。

```text
selection_change_rate ≈ 0
    → STOP_INSUFFICIENT_MECHANISM_OPPORTUNITY

selection changes but no repeatable benefit
    → KEEP_SIMPLE or a separately reviewed redesign
```

不得以“样本不够”自动扩容。

## 7.3 3C-2 Evidence-grounded Revision

taxonomy：`CORRECTION / SCOPE_NARROWING / SCOPE_EXPANSION / EXAMPLE_REFRESH / RETIRE`。核心纠错
收益只统计前两类。

输入必须有 exact old version、original evidence、current feedback、visibility regime；输出必须有
new version/predecessor、changed claims/applicability、type/reason、evidence/feedback refs 和 policy
version。新版本不无条件继承旧 utility。

有效 effect denominator：

```text
revision created
→ later independent task retrieves lineage
→ revised version exposed
```

无 later exposure 只计 maintenance cost。arms 为 `APPEND_ONLY` 与 `REVISION`；
`REVISION_WITHOUT_SOURCE_CHECK` 仅可作有限诊断。

停止：no later reuse、unsupported correction，或只有 example refresh 而无 correction claim。

## 7.4 3C-3 State-guided Attention v0.1

允许的已有/显式 Lab state：current question、active goal、hypotheses、failed approaches、unresolved
constraints、next actions、memory intentions、uncertainty、open conflicts、recent evidence。每个字段
说明 owner、freshness 和 absence semantics，不得从 hidden result 构造。

首版 modes 只有 `FOCUS / CONFLICT / EXPLORE`，policy deterministic、bounded、traceable，无额外
controller LLM。

```text
State → Focused Retrieval → Coverage/Confidence Check
→ bounded expansion only if insufficient
→ Evidence/Utility/Conflict scoring → convergence → Context
```

先评价 unnecessary retrieval、irrelevant exposure、evidence/conflict coverage、tokens、latency 和
quality non-regression。若成本/无关暴露无改善，停止，不直接扩大 answer-effect 样本。

## 7.5 3C-4 RL-like Policy Adaptation

只有前序 mechanism 在真实 opportunity 上改变 action 才准入。学习对象限于 memory-version、bundle、
attention-mode 或 policy-action utility，使用可解释 bounded update，不训练 controller weights。

一个 request 暴露 A/B/C 后，success 不得给 A/B/C 分别加 reward。首版保持 bundle-level 或 ordered
exposure-sequence-level；只有 counterfactual/ablation 后才拆 item contribution。

```text
if learned value never changes a later action:
    STOP_NO_POLICY_EFFECT
```

## 7.6 Phase 3C exit

```text
[ ] Utility matched evidence or KEEP_SIMPLE terminal
[ ] Revision real later-reuse denominator or STOP terminal
[ ] Attention cost/evidence comparison or KEEP_SIMPLE terminal
[ ] adaptation changes later action or remains validly NOT_ADMITTED/STOPPED
[ ] at least one repeatable signal, or all mechanisms have honest negative terminals
[ ] every request/token settled; unknown usage explicit
```

全部得到 `KEEP_SIMPLE` 是合法的 Phase 3C COMPLETE。

---

# 8. Phase 3D — Transfer / Multi-session Confirmation

## 8.1 Admission

至少一个 Utility、Revision 或 Attention 机制在 matched DEV 中满足：mechanism activated、repeatable
signal、complete cost acceptable、no safety regression、policy frozen。否则整个 3D 为
`NOT_ADMITTED`，不得消费 holdout。

正式主表只保留 `Native / OM / ReasoningBank / MiLAi`；STATIC/UTILITY/REVISION/ATTENTION 仅作为
mechanism ablation。

## 8.2 Protocols

Frozen Bank：support 形成 bank → freeze → unseen evaluation → no evaluation writes。

Online Stream：task → outcome → allowed update → next task；所有 arms 同 ordering、visible feedback、
budget，不用前半程/后半程替代 matched control。

Dependent Multi-session：A 形成 person/plan/constraint → B/C 依赖续接；不得每 session 独立 reset。
主要验证 constraint preservation、revision carry-over、task-person identity 和 plan continuity。

## 8.3 Second solver

只有 core policy frozen、single-solver unseen signal、首 solver ledger/usage 全结算且用户明确授权新
有限预算后才能启用。

## 8.4 Exit

```text
[ ] admitted protocols have terminal results
[ ] full cost/failure/safety accounting
[ ] no holdout-driven policy change
[ ] second solver completed or explicitly deferred/not admitted
```

若未准入，记录原因，而不是生成空结果。

---

# 9. Phase 3E — Product Promotion Gate

```text
Lab prototype
→ pinned Product baseline
→ matched comparison
→ mechanism activated
→ independent unseen confirmation
→ benefit/cost/safety review
→ architecture impact review
→ Product ADR
→ minimal behavior PR
```

Decision record 必须回答：机制是什么、击败何种简单 baseline、真实机会数、observable use 与因果
支持、完整生命周期成本、harm/failure/unknown、Product contract 影响和保留 Lab-only 的部分。

## 9.1 Terminal A — Promote

`PROMOTE_MINIMAL_CANDIDATE` 后才写 ADR 和最小 Product slice。必须说明 architecture/API/schema/
permission/canonical/migration 影响，生成 current-tree receipts，涉及 persistence/authority 时使用真实
PostgreSQL，并只在最终候选触发一次 full composition。不得把 benchmark ID、hidden scorer 或实验
配置带入 Product。

## 9.2 Terminal B — No promotion

`KEEP_LAB_ONLY / KEEP_SIMPLE / NO_PROMOTION / INSUFFICIENT_MECHANISM_OPPORTUNITY /
BENEFIT_NOT_ESTABLISHED` 都是完整终局。必须保留负结果、成本和停止原因，并证明 Product 默认未变。

---

# 10. PR and branch plan

| Order | Branch | Scope | Full composition |
| ---: | --- | --- | --- |
| 1 | `docs/post-cleanup-status-reconciliation` | 3A-0 docs | no |
| 2 | `behavior/revalidate-worker-once` | 3A-1 | no unless behavior changes |
| 3 | `behavior/trace-ownership-v1` | 3B-1 | only if material Product behavior changes |
| 4 | `behavior/host-continuity-diagnosis` | 3A-2D | no |
| 5 | `fix/host-continuity-<specific-gap>` | conditional | final candidate only |
| 6 | `research/resolver-language-diagnostic` | 3A-3D | no |
| 7 | `fix/memory-need-resolver-<specific-gap>` | conditional | final candidate only |
| 8 | `research/memory-opportunity-ledger` | 3B-2 | no Product full |
| 9 | `research/utility-selection-v1` | 3C-1 | no Product full |
| 10 | `research/evidence-grounded-revision-v1` | 3C-2 | no Product full |
| 11 | `research/state-attention-v1` | 3C-3 | no Product full |
| 12 | `research/policy-adaptation-v1` | conditional 3C-4 | no Product full |
| 13 | `research/transfer-confirmation-v1` | conditional 3D | no Product full |
| 14 | `docs/product-promotion-decision` | 3E decision | no |
| 15 | `behavior/<minimal-candidate>` | conditional Product candidate | exactly once at L4 |
| 16 | `docs/post-cleanup-development-results` | final result | no repeated full |

一个 PR 只处理一个 decision boundary；diagnosis/remediation 不混合。docs-only PR 不加
`full-composition`。Lab-only 且 Product tree 未变时不跑 Product full。full label 在 tested head 上只加
一次，metadata follow-up 前移除。merge 前记录 tested head，合并后比较 candidate/merge tree identity，
main fast identity PASS 后才登记完成。

---

# 11. Validation cadence

## L0 — Document/static

```text
JSON/YAML parse where applicable
Markdown link/path review
git diff --check
Product manifest --check
receipt verifier --check
Conformance --check
repository boundary
```

不运行 package/full tests。

## L1 — Targeted development

changed module Ruff/type check、exact adjacent unit/contract/integration nodes。数据库语义只能用真实
PostgreSQL 关闭。

## L2 — Affected package

Product：affected package Ruff/mypy/tests/build + manifest/receipt/Conformance/boundary。

Lab：两个 boundary gate、Ruff、mypy、targeted non-regression tests、runner smoke；packaging 改动才
build；Product-backed effect run 前必须验证 pin。

## L3 — Root fast CI

每个 PR 使用 path-classified fast workflow；未受影响 package 应 skip。

## L4 — Full composition

只用于 material Product remediation final candidate、accepted minimal Product candidate，或 final closure
中尚无权威可执行身份的情况。相同 executable tree 不重复运行。

一次 L4 包括 Runtime/PostgreSQL、六 integrations、Lab fast、四 historical shards、Archive、Product
identity、Conformance 和 composition。

失败时区分 implementation/test/infra/timing，保留原失败，只重跑失败 job 时记录 attempt；不通过
提高 timeout、放宽权限、扩大 budget 或 case-specific rule 修绿。没有对应风险的长测试取消。

---

# 12. Evidence and accounting

Product receipt 至少包含 schema/version、debt ID、source commit/tree/manifest、environment/DB identity、
exact commands/node IDs、positive/negative case IDs、status、covered claim、limits 和 diagnosis/remediation
关系。

Lab run 至少绑定 Goal/work-package、arm kind、method/policy/config、run-specific Product lock、input/split/
manifest hashes、model/provider/profile、request/token/time ceiling、actual/unknown usage、output/result ledger
hash 和 trace join version。

固定成本项：retrieval、embedding、solver、maintenance/controller/judge、input/output/maintenance tokens、
bank formation、per-task、amortization、latency、failed request、unknown usage、closed unused allocation。

合法结果语言：engineering works、mechanism activated on N opportunities、matched signal/no signal、benefit
not established、unknown、keep simple/Lab-only。

禁止：code exists→works、exposed→used、task success→all memory helped、DEV win→transfer、test count→
conformance、one solver→general Product benefit。

---

# 13. Stop and escalation

立即停止：需要原地修改 Frozen Architecture、弱化 permission/canonical、hidden labels 进入 inference、
Product pin 失败、freeze 后 input/split 改变、unknown usage 无法保存、holdout 影响开发、机制无机会、
learned value 不改变 action、revision 无 later reuse、出现 safety regression、预算/时间耗尽。

必须另开 Goal/ADR：new migration/schema、new public MCP tool/route、authority/permission 改变、default
retrieval/ranking/threshold/budget 改变、second solver、formal holdout reopening、model/reward-model training。

---

# 14. Completion definition

## Phase 3A

```text
[ ] five NEEDS_REVALIDATION items have executable classifications
[ ] no unexplained OPEN debt
[ ] Product/Lab current docs are reconciled
```

## Phase 3B

```text
[ ] Trace Ownership v1 fixed/versioned
[ ] acquisition→selection→exposure→use join executes
[ ] Opportunity Ledger generated from real bounded execution
```

## Phase 3C

```text
[ ] Utility matched evidence or KEEP_SIMPLE
[ ] Revision later-reuse evidence or STOP
[ ] Attention cost/evidence comparison or KEEP_SIMPLE
[ ] adaptation changes later action or is validly not admitted/stopped
[ ] at least one repeatable signal, or all have honest negative terminals
```

## Phase 3D

```text
[ ] admitted protocols have terminal results
[ ] or Phase 3D is NOT_ADMITTED for lack of qualifying signal
[ ] costs/failures/unknown usage/safety fully settled
```

## Phase 3E

满足其一：

```text
A. PROMOTED
   reviewed ADR + minimal Product PR + current receipts + full composition PASS

B. NO_PROMOTION
   evidence supports KEEP_LAB_ONLY/KEEP_SIMPLE/NO_PROMOTION
   Product default unchanged; no open allocation
```

## Repository closure

```text
[ ] final results and terminal ledger exist
[ ] manifest and Conformance receipt fresh
[ ] historical evidence unchanged
[ ] immutable tree identities preserved or explicitly reviewed
[ ] PR tested-head and merge identities recorded
[ ] main == origin/main
[ ] worktree clean except separately reported user-owned files
[ ] Schema remains honestly classified
```

合法终态为 `COMPLETE_PROMOTED` 或 `COMPLETE_NO_PROMOTION`；二者都表示完成。

---

# 15. First executable slice — submitted, remote closure pending

Goal 激活后的唯一默认工作包是 `3A-0 Status Reconciliation`：

1. 从 exact `main` 创建 `docs/post-cleanup-status-reconciliation`；
2. 区分四份 current status/goals 中的 current claim 与 historical snapshot；
3. 更新 Product baseline、cleanup、Conformance 和 TECH_DEBT；
4. 更新 Lab 当前主线、暂停/不恢复边界、工程完成/收益未证实边界；
5. 只运行 L0；
6. 创建 docs-only PR，不加 `full-composition`；
7. fast CI 按 tested head 合并并核对 tree/main identity；
8. 再激活 3A-1，不自动启动研究实验。

---

# 16. Execution journal

## 2026-09-22 — Goal generated

- 完整读取并绑定源路线图及 SHA-256。
- 注册 main、Product tree、Conformance、TECH_DEBT 与 cleanup Run #60。
- 转换为 diagnosis-first、gate-driven、promotion-or-no-promotion 执行合同。
- full composition 限制为高风险最终候选的一次性 L4，不在小 PR 重跑长测试。
- 新 experiment allocation 与 model request 均为 0；历史实验未恢复。
- 初始状态：`READY_FOR_EXECUTION`；首个工作包：`3A-0_STATUS_RECONCILIATION`。

## 2026-09-22 — 3A-0 Status Reconciliation submitted

- Product current baseline 已更新到 cleanup 后 main、Product manifest/tree、Conformance `10/34/0`
  与 TECH_DEBT `5 FIXED / 5 NEEDS_REVALIDATION / 0 OPEN`。
- Product Goals 已把本 Goal 设为当前治理主线；V02-18 保留为历史 plan snapshot。
- Lab Current Status 已区分 Evidence/Utility 的已执行实现状态、ReasoningBank 的暂停历史和
  Adaptive Memory 的工程完成/收益未证实边界。
- Lab Goals 已解释旧 `PLANNED_NOT_STARTED` 与后续 `IMPLEMENTATION_IN_PROGRESS` 的时间关系；
  历史 Goal 未改写，旧实验未恢复。
- 本阶段无 Product/Lab 行为改动、无模型请求、无新实验 allocation。
- 本地 L0 已通过，候选已提交为 PR #27；但 PR 尚未合并，3A-0 仍等待 fast CI、tested-head merge、
  candidate/merge tree identity 和 post-merge main identity，因此尚未取得最终 `PASS`。

## 2026-09-22 — User pause and GPT-6 handoff

- 用户在 PR #27 fast workflow 执行期间明确要求暂停开发。
- 暂停前最后一次观测：PR #27 head `e31baf3ff88151e6d7aa9692cba715d562991269`；fast Run
  `35671618962` 状态为 `in_progress`。该状态只是暂停时快照，恢复时必须从 GitHub 重新读取。
- 暂停后不再轮询、不合并 PR、不启动 3A-1，也不运行额外测试或实验。
- GPT-6 接手说明见
  `docs/cleanup/MILA_GPT6_PROJECT_HANDOFF_GUIDE_v1.0_20260922.md`。
- 恢复顺序固定为：核对 PR #27 live head/CI → 合并并证明 identity → 将 3A-0 标记 PASS →
  从最新 main 创建 3A-1 分支。不得从未合并候选直接开始 3A-1。
