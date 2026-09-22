---
goal_id: MILAI-POST-CLEANUP-DEVELOPMENT-01
version: v1.0
date: 2026-09-22
status: ACTIVE
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
current_work_package: 3C-2_RESEARCH_REVISION_ELIGIBILITY_BRIDGE
next_work_package: 3C-3_DETERMINISTIC_ATTENTION_POLICY
new_experiment_allocations: 1
new_model_requests: 199
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
到 GPT-6；随后用户明确要求继续执行本 Goal，当前状态恢复为 `ACTIVE`。
历史暂停不再阻止当前工作包；旧实验和模型预算仍不自动恢复。

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
| 3A-0 | Status reconciliation | Product/Lab docs | no | PASS — PR #27 / main identity verified | G0 |
| 3A-1 | Worker `--once` revalidation | Product evidence | expected no | PASS — PR #28 / main identity verified | 3A-0 |
| 3B-1 | Trace Ownership v1/v2 | Product/testkit + Lab | small/contractual | PASS — scoped receipt / PR #34 / main identity verified | 3A-0 |
| 3A-2D | Host Continuity diagnosis | Product evidence | no | DIAGNOSED_FAIL — PR #35 / main identity verified; native replay OPEN / cache-miss FIXED | 3B-1 vocabulary |
| 3A-2R | Host Continuity remediation | Product | conditional | PASS — PR #36 / full #63 / main identity verified | 3A-2D FAIL |
| 3A-3D | Resolver diagnostic | Product/Lab tests | no | FAIL_REMEDIATION_REQUIRED — PR #37 / main identity verified; 17 PASS / 13 FAIL retained | 3A-0 |
| 3A-3R | Resolver remediation | Product | conditional | FAIL_REMEDIATION_REQUIRED — partial repair merged PR #38/full #64; C06/C21 remain OPEN, not full closure | 3A-3D FAIL |
| 3B-2 | Memory Opportunity Ledger | Lab | no | PASS — PR #39 / exact-head fast / identical-tree merge / main identity verified; scoped accounting, not mechanism benefit | 3B-1 PASS |
| 3C-1 | Utility Selection | Lab | no | KEEP_SIMPLE — PR #42 / main identity verified; benefit not established | 3B-2 real-run proof |
| 3C-2 | Evidence-grounded Revision | Lab | no | IN_PROGRESS — zero-model eligibility bridge; no real correction denominator/effect terminal or new model allocation | 3B-2 + lineage |
| 3C-3 | State-guided Attention | Lab | no | IN_PROGRESS — zero-model state/mode contract proposal; no effect execution | 3B-2 + frozen state |
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
[x] Utility matched evidence or KEEP_SIMPLE terminal — PR #42 scoped KEEP_SIMPLE
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
[x] Utility matched evidence or KEEP_SIMPLE — PR #42 scoped KEEP_SIMPLE
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

## 2026-09-23 — Revision eligibility implementation; effect evidence still absent

- Base/rollback `ba88a572f956f9ef4e96ab04e4ad9d988e95d544`, verified remote main.
  Readiness PR #43 exact-head fast `35789620049` and main fast `35789799253` PASS;
  candidate/merge tree `aeecfcd70807d28a9bae2b0b17c5de04915a3dff` matched.
- [Lab-only bridge](../../../MiLAi-Lab/docs/RESEARCH_REVISION_ELIGIBILITY.md) reuses
  VersionUtility validation/confirmation and both replace/append revision lineages.
  It binds exact source contents and semantic/provenance review declarations before
  later reuse; missing support/independence stays UNKNOWN, same-cluster/hidden-H/
  retired/non-correction versions receive no core correction credit. The caller
  must authenticate review and timing; checksums alone do not prove semantic support.
- 62 targeted tests PASS, changed-file Ruff/mypy PASS. A synthetic existing-session
  revision → restore → later exposure join seals before the later task. This is
  engineering coverage, not a real correction denominator or model benefit.
  Package/static/build verification is delegated to classified Lab fast CI;
  no repeated Product full, historical replay or broader data scan.
- No Product executable, Schema/API/permission/Canonical, old bank or ledger contract
  change. C06/C21 remain OPEN; Conformance remains UNVERIFIED; Schema stays NO-GO.
  No new generation/embedding/endpoint probe or model allocation. Utility is closed;
  3C-2/3C-3 effect terminals remain outstanding. Next safe work is the separate pure
  deterministic Attention seam, not another experiment.

## 2026-09-23 — Revision/Attention readiness; no new model allocation

- Current main `fcefea3f8944755b555f60817f6ba007290ae184` matched remote main,
  worktree initially clean. PR #42 remote closure verified: exact-head fast
  `35748269576`, candidate/merge tree `0831c6594385ab0fd0561ee4c3d80e2bc8e20f94`,
  main fast `35749519699` PASS; Lab 4,693 PASS / 137 SKIP / 4 DESELECTED.
- [Bounded readiness finding](../../../MiLAi-Lab/docs/REVISION_ATTENTION_READINESS.md):
  four already inspected DB/OS DEV/VALID banks, 24 completed positions, 37 current
  revision-1 cards, no historical versions/changed patches/predecessor links. Twelve
  v0.7 Actor exposure receipts joined to settled requests and actual payload hashes;
  none establish revised-version later exposure. This is not a general Revision
  negative result or exhaustive pool search. No Travel/TEST/RESERVE/SUPPORT data added.
- Reuse existing revision engine, version accounting and Opportunity Ledger taxonomy/
  exact-version later-exposure joins. The incremental seam is prototype admission,
  correction support, feedback visibility and source-cluster independence, not another
  bank or duplicate ledger. Old state_focus is
  FULL/FOCUS projection with a different request envelope, not three-mode Attention.
  Proposed field ownership/freshness/absence and bounded deterministic policy are
  now explicit; implementation and effect evidence remain outstanding.
- No new generation/embedding/endpoint probe, model allocation or service change.
  Documentation-only L0 scope; no repeated package/full tests. Utility is closed,
  Revision/Attention effect terminals and overall Goal completion remain unproven.

## 2026-09-22 — Authorized proxy batch closed locally; KEEP_SIMPLE

- The user explicitly permitted historical exact-bundle adoption/rejection as a
  proxy, still requiring paired quality and full cost accounting. The frozen
  allocation was unchanged; method/provenance/meaningfulness/native pins and
  [protocol](../../../MiLAi-Lab/docs/UTILITY_PROXY_PROTOCOL.md) were sealed before
  the first request. No TEST, confirmation, Travel, RESERVE or SUPPORT bank used.
- [Result](../../../MiLAi-Lab/docs/UTILITY_PROXY_RESULT.md): all 24 independent
  pairs and three fixed repeats complete; one budget-interrupted arm and nine
  unstarted arms retained. 199 generations / 341,591 reported tokens, 200 tokenizer
  calls and one model-info call; 400 outbound total, zero new embedding/rerank,
  zero unknown outbound usage, 909.961 seconds. The conservative text-slot guard
  includes auxiliary calls; no makeup or reuse of unused ceilings is authorized.
- Only one independent opportunity met the pre-outcome meaningful-alternatives
  rule. OS428 was correct in both arms but used 36 more total tokens; its repeat
  is incomplete. DB selection never changed, yet three pairs differed in native
  quality with identical initial payloads. These losses are retained as background
  variability, not attributed as causal Utility harm. No repeatable benefit or
  positive non-regression claim; 3C-1 KEEP_SIMPLE, no Product promotion.
- All 696 sealed pins reverified after execution. Historical formation/cache costs
  are separately disclosed; lifecycle attribution/use remain UNKNOWN. Product
  executable/schema/API/permissions/Canonical behavior unchanged; C06/C21 OPEN.
  33 distinct targeted tests and Lab static/boundary checks passed; no repeated
  Product full. Result PR closure is pending, not silently assumed.
- Preparation PR #41 closed: tested head `883cd7861a2d1b3044a032415ee47c3b9486ba19`,
  fast `35740683722` PASS; squash `ae434539f6b99fd2da0c9ab6e208ff7ce34f9d88`,
  identical tree `bd173eb75f6df156223ada3d02050fcdff2b39cc`, main fast `35741790217`
  PASS. Lab CI 4,682 PASS / 137 SKIP / 4 DESELECTED. Remote base main rechecked.
- 3C-2/3C-3 have no model-execution allocation; 3C-4, transfer, second solver and
  promotion remain unadmitted. Overall Goal completion is not claimed.

## 2026-09-22 — User-authorized finite first Utility batch

The user explicitly authorized one new DB/OS development batch, not a historical
study resume. The [Lab admission record](../../../MiLAi-Lab/docs/UTILITY_FIRST_BATCH.md)
binds the frozen 12 independent positions per domain, four preselected repeats per
domain and all 32 STATIC/UTILITY pairs (64 executions). Only already exposed frozen
DEV/VALID material is permitted; TEST, confirmation, Travel, RESERVE, SUPPORT and
outcome-based replacement are excluded.

Solver remains Qwen3.6-35B-A3B-FP8 on the existing loopback endpoint and M1 profile;
only the existing bge-m3 retrieval contract is allowed, reranking off. Limits:
400 text requests / 3,000,000 text tokens; 128 embedding requests / 50,000 tokens;
528 total requests; four hours from first request. Failures/retries/maintenance
count, unknown usage reserves its known upper bound, and the deadline cannot be
extended. The task schedule was frozen with zero new requests. Method/utility
provenance and transport admission are unfinished; no effect result is claimed.
Product executable behavior and existing resolver debt remain unchanged.

## 2026-09-22 — Opportunity Ledger closed; research execution remains unallocated

- PR #39 exact head `e72c2370d915ff3db2d2f483a479331b1eccca94`; classified fast
  `35717333297` PASS. Lab package CI: 4,657 PASS / 137 SKIP / 4 DESELECTED,
  with static/build and archive integrity PASS. Product Runtime/integration suites
  and full composition were not repeated; no job restart or extra model request.
- Expected-head squash merge `53e13c47c72a3f49f4cd66007320083babdc07be`; tested and
  merged tree `897f16db73433f212a98ab4fc9e992c6477d0c13` match. Local main equals
  origin/main; main fast `35718296416` PASS. Only the separately prepared, untracked
  zero-model preflight draft existed during this sync; no unknown changes overwritten.
- 3B-2 is PASS for its declared engineering scope: versioned ownership, validated
  joins, the offline minimum matrix, actual pre-outcome capture, deterministic real
  ledger replay and pinned method/Product identities. The real run's zero selection
  opportunities and unknown task outcomes/use are not research negative results.
- [3C preflight](../../../MiLAi-Lab/docs/POST_CLEANUP_RESEARCH_PREFLIGHT.md) records
  the next question, matched-arm constraints, legacy integration gaps and missing
  execution choices. Input scope, model/profile and finite request/token/time ceilings
  are not authorized by old manifests or a generic continuation. User input requested;
  no model/embedding/Provider/Judge call, shared-service change or historical resume.
- No Phase 3C mechanism outcome or overall Goal completion is claimed. Existing
  Resolver C06/C21 remain explained OPEN debt. Original proof snapshots are preserved;
  this journal supplies later remote closure without rewriting historical receipts.

## 2026-09-22 — Opportunity Ledger local proof, real capture and explicit limits

- [Lab contract](../../../MiLAi-Lab/docs/MEMORY_OPPORTUNITY_LEDGER.md) and
  [compact proof](../../../MiLAi-Lab/data/manifests/memory-opportunity-ledger-proof-20260922.json)
  bind source `7dbaeeca27f3515542f111bdb0ab699e0cbf7982`; Product executable tree
  unchanged. Pure ledger, validated raw owner exports and opt-in pre-outcome capture
  retain exact versions, cache origins, ordered exposures, failure costs and UNKNOWNs.
- 107 targeted tests, changed Ruff/mypy, two Lab boundaries and CLI smoke PASS.
  One real isolated MCP/HTTP/PG/Host run: 10 attempts, 9 fixture calls, 4.696 s;
  all pre-outcome snapshots persisted, exact ledger recomputation PASS. Model calls,
  model tokens and research allocations 0. Dedicated DB stopped with data retained.
- Actual funnel has 7 available / 5 exposed attempts / 0 selection opportunities.
  Task outcomes/use remain UNKNOWN; 3 requests have unknown fixture usage and all
  embedding counters remain explicitly unobserved. Multiple-choice, supported-use
  and revision-effect cases are simulation-only, not relabeled real model evidence.
- 3B-2 remains IN_PROGRESS until fast CI, expected-head merge, candidate/merge tree
  and main identity pass. No Product full or historical replay rerun is required.
  Phase 3C needs separate finite inputs/budget/stop authority before model work.

## 2026-09-22 — Partial Resolver repair merged; independent Opportunity Ledger entered

- PR #38 exact head `03877e019552715e59b9c19c301c01002b7cb054`; automatic fast
  `35690275412` and `35690275863` PASS. One final-candidate full composition,
  Run #64 / `35690275830`, all 17 jobs PASS; no rerun after the waiting interruption.
- Expected-head squash merge `8c0c526487fda508560c3d340e95d59b1ec3db6e`;
  candidate/merge tree `7be3a26554d61a56ad3824581caef88e67d40ad5` matched.
  Local main equals origin/main; main fast `35713661491` PASS.
- C06 undeclared synonym and C21 cross-language exact predicate remain genuine
  unsatisfied expectations with owner/risk/constraints in ADR-058 and the OPEN receipt.
  CI PASS is delivery evidence, not a semantic PASS. 3A-3R is not marked complete;
  no fixture dictionary, model controller or unreviewed API expansion is admitted.
- `research/memory-opportunity-ledger` starts from exact main. Its entry gate is
  3B-1 PASS, independent of the explained legacy-client capability gaps. It consumes
  the current query-first public trace/testkit, not a replacement resolver pathway.
  The original corpus and failing expectations remain active and unmodified.
- 3B-2 must freeze opportunities before outcomes, bind exact ordered versions, retain
  unknown/failure costs and validate later revision reuse. Offline fixtures alone
  cannot close the required real bounded-run gate. No Product behavior/schema change,
  research model allocation or historical experiment resume follows from this entry.

## 2026-09-22 — Deterministic resolver boundaries improved; debt remains OPEN

- [ADR-058](../adr/ADR-058-deterministic-resolver-language-boundaries.md) and source
  `9b4aa1670dc75dfc2149baeb75719f017267e92a` preserve frozen aliases/structured Runtime
  signals, normalize typed Unicode, prefer known exact identifiers, retain ambiguity,
  respect changed retry intent/key and keep prior routes. No scoring weight/budget,
  schema/API, permission, Canonical or Lab policy change.
- Same frozen corpus/method: client 20 PASS/2 FAIL, Runtime 8 PASS/0 FAIL. Original
  17/13 diagnosis is untouched. [Separate partial result](../revalidation/resolver-language/REMEDIATION.md)
  retains C06 synonym and C21 translation expectations as unsatisfied; no case terms
  were added or expectations weakened. Debt stays OPEN, not FIXED.
- Narrow tests: client 64 PASS/2 strict XFAIL; Runtime 49 PASS. Changed Ruff/mypy pass.
  Product tree `847967d2e212b974d92b0b08d6e0f8b135a3c1080adf61790dcb771b9c832311`;
  manifest 425 files. Prior behavior receipts remain historical on the changed identity.
- Models/embeddings/retrieval/DB/Provider calls/tokens/allocations 0. One L4 is required
  on the final material candidate; none has been launched for intermediate edits.
  3A-3R remains IN_PROGRESS pending candidate gates and explicit remaining-gap disposition;
  no research or Opportunity Ledger work is claimed complete.

## 2026-09-22 — Resolver diagnosis closed; separate remediation entered

- PR #37 tested head `3eae5cad9136518365e90f93a85f7ca191bfaef7`, fast
  `35688803848` PASS. Expected-head squash merge:
  `87aa53c73ec0a67ff412923e2151c71def575130`; candidate/merge tree
  `0cc79d8797f1cb1c4321839015eab9f3e1bd980a` matched.
- Local main equals origin/main, clean; main fast `35688919530` PASS.
  Only affected Runtime/client fast gates and boundary/identity/Conformance ran;
  no Lab suite, PostgreSQL rerun or full historical composition for this diagnosis.
- 3A-3D is closed as FAIL_REMEDIATION_REQUIRED, not a behavior PASS. Frozen corpus,
  result and receipt remain at their diagnosis identities; this journal adds remote closure.
- `fix/resolver-typed-language-boundaries` starts from exact main. Examine existing
  Host signals/StateKeys first; preserve frozen aliases and explicit-read semantics.
  Correct general typed matching/ambiguity/retry/language boundaries without fixture
  synonyms, changed scoring weights, hidden retrieval, model controller or schema/API change.
  Any capability outside a bounded general remedy remains explicitly explained, not relabeled PASS.
- No repair proof yet; debt stays 9 FIXED/0 NEEDS_REVALIDATION/1 OPEN. L1 comes first;
  material behavior requires one L4 on the final candidate, not intermediate full runs.
  Research/model allocation remains zero; 3B-2 and subsequent research are pending.

## 2026-09-22 — Frozen resolver diagnosis records 13 desired-behavior gaps

- Corpus and recorder committed before execution at
  `6f9e34efe6399792b44fc0d51438c742e6e5a1c0`; Product executable identity unchanged.
  [Results and limits](../revalidation/resolver-language/REVALIDATION.md): client
  11 PASS/11 FAIL; Runtime interpreter 6 PASS/2 FAIL. All expected/actual records remain.
- Source explains English/ASCII dependence, changed-intent retry carry-over and lexical
  tie selection. Chinese automatic no-memory inputs remain POSSIBLE/SEARCH. Frozen
  alias compatibility and current query-first ownership are explicitly distinguished.
  No actual retrieval, Context exposure, authority bypass or model effect was measured.
- Product tests preserve 17 PASS/13 strict XFAIL after primary collection; no failure
  is counted as a pass. Changed Ruff passes. Scoped FAIL receipt is valid; Conformance
  stays 9 PASS/35 UNVERIFIED/0 DEVIATION. Debt: 9 FIXED/0 NEEDS_REVALIDATION/1 OPEN.
- This PR is diagnosis only. 3A-3D waits for exact-head fast, identical-tree merge and
  main identity. Separate remediation is conditional after closure; no full composition
  rerun, database or model call. Research allocations/tokens remain zero.

## 2026-09-22 — Host remediation closed; Resolver diagnosis entered

- PR #36 exact head `ba4723e236aa6fd4949a688d9593059b459a6bd9`; fast runs
  `35685753382` and `35685753972` PASS. One final-candidate full composition,
  Run #63 / `35685753906`, PASS with all 17 jobs; no manual rerun.
- Expected-head squash merge `3eab81c9e1c23b07e3aead351cc3adfe423470c0`;
  candidate/merge tree `3874a68fa06892d4c3bf0a0fe354339d1bde8f9e` matched.
  Local main equals origin/main and main fast `35688151840` PASS.
- 3A-2R is now PASS for its declared scope. Original diagnosis and remediation
  receipts retain their historical snapshots; this journal supplies remote closure.
- `research/resolver-language-diagnostic` starts from exact merged main. The
  [diagnosis plan](../revalidation/resolver-language/DIAGNOSIS_PLAN.md) freezes
  30 synthetic cases and a pure recorder before execution. No resolver repair,
  hidden retrieval, model call, database, ranking/budget or default-route change.
  Client compatibility prefetch and current Runtime interpretation stay distinct.
- 3A-3D is IN_PROGRESS, not a result claim. Research allocations/model requests 0;
  3B-2 and research remain pending. Schema remains NO-GO FOR SCHEMA FREEZE.

## 2026-09-22 — Native retirement guard repaired; final-candidate gates pending

- [ADR-057](../adr/ADR-057-retired-native-host-instance-rejection.md) and seven source
  lines retain/reject retired native IDs under the existing lock, before graph mutation
  and tool-continuation handling. Runtime memory/caching, permission, Canonical, schema,
  migration and Provider budgets are unchanged. No Lab source changes.
- Source `faf3922c2b1d037f0c3a019dd1bbaf6dc059be15`, Product tree
  `08cd98fea12383fd26cf3f10b39bc04ffea23da2271f45ebe55c772a57ecafe2`:
  24 native tests PASS / 0 XFAIL, plus 2 real MCP/HTTP/PG recovery cases PASS.
  Four fresh Host processes / 10 attempts / 8 controlled fixture calls. Changed Ruff/mypy pass.
- [Separate remediation receipt](../revalidation/host-continuity/REMEDIATION.md) gives
  SCOPED G9/G7 evidence. Original diagnosis and cache-miss receipts retain their old
  identities. Local debt is `9 FIXED / 1 NEEDS_REVALIDATION / 0 OPEN`, not a merged
  work-package completion claim. New Product manifest does not rebind old receipts.
- Owned processes/DB stopped with data retained; model requests/tokens/allocations 0.
  L4 is required once on the final material behavior candidate. No local full-suite or
  historical-replay duplicate; no intermediate L4 run. 3A-2R remains IN_PROGRESS.

## 2026-09-22 — Host diagnosis merged; separate native-instance remediation entered

- PR #35 exact head `99d28e02e5343ebedeffac41940de8808eb78acc`, fast `35685033957`
  PASS. Expected-head squash merge `e7604346471593127f09dbae321e95f018d2fa13`;
  candidate/merge tree `fe157cd172946f83b8d6fafc21c600fb967ad881` matched.
- Local main equals origin/main; main fast `35685136321` PASS, including tree identity.
  Only affected OpenWorker package plus boundaries/identity/Conformance ran; Runtime,
  Lab, historical replay and full composition were not repeated for diagnosis.
- `fix/host-continuity-retired-instance` starts from that exact main. 3A-2R is limited
  to rejecting retired native instances before state mutation or dispatch; no change
  to Runtime cache validation, persistent Memory identity, permissions or Canonical.
  Original FAIL receipt/strict assertions stay until a separate repair is proved.
- Debt remains `8 FIXED / 1 NEEDS_REVALIDATION / 1 OPEN`; no premature FIXED claim.
  L1 precedes the final candidate's required L4; no intermediate full composition.
  Models, experimental allocations and resumed historical experiments remain zero.

## 2026-09-22 — Host diagnosis: retired native replay OPEN, cache-miss proof PASS

- No Product executable change. [Diagnosis and separate receipts](../revalidation/host-continuity/REVALIDATION.md)
  preserve **18 native PASS / 2 FAIL**, source `c70ceacb5bc2aeb19ad332b2ec04c8c700bf3145`.
  A → B → retired A repeats an old operation and reaches a third actual Adapter MCP/Provider
  fixture call. Ordinary duplicate, delayed result, ABA, scope/profile and token controls pass.
- Final source `6712e800ef28189f191eb313108a6b8d86b3d795`: **2 real PG cases PASS**,
  4 fresh Host processes / 10 attempts / 8 controlled Provider calls. Exact persistent
  Claim reacquisition, validated receipt reuse and fresh cache-miss fallback work;
  stopped actual Runtime blocks Provider. No model request/token or allocation.
- Host test-harness failures remain recorded separately. The two Product behavior assertions
  remain strict XFAIL for diagnostic CI; they are not repaired or counted as PASS.
  Product manifest/executable identity is unchanged, so existing 3B-1 scope/canonical
  evidence is reused rather than rerun. Owned processes/DB stopped, data retained.
- TECH_DEBT is `8 FIXED / 1 NEEDS_REVALIDATION / 1 OPEN`. Receipts are scoped, not
  broad Conformance or production claims. Diagnostic remote closure is pending.
  The failure admits a separate `fix/host-continuity-retired-instance` after that merge;
  resolver diagnosis and Opportunity Ledger remain pending, research stays unallocated.

## 2026-09-22 — 3B-1 closed; Host continuity diagnosis entered

- PR #34 tested head `bffaa845bea4cc82a5685131ef402e00cb793c18`, fast run
  `35683142058` PASS. Expected-head squash merge:
  `9474c63e56e5029c33e2dca5c19e772e4868b18d`.
- Candidate and merge share Git tree `1c070d6d9c62ea3ce71a68b22ca3ec4e87c2584e`;
  local main fast-forwarded to origin/main cleanly. Main fast `35683815988` PASS,
  including tested-tree identity, boundaries, Product manifest and Conformance.
- 3B-1 is PASS for the declared public serial testkit scope. Its immutable receipt
  retains the pre-merge PENDING snapshot; this journal supplies later remote closure.
  No full composition, old replay or extra local test rerun was needed for closure.
- Enter `behavior/host-continuity-diagnosis` from exact merged main. The
  [diagnosis plan](../revalidation/host-continuity/DIAGNOSIS_PLAN.md) covers both remaining
  Host debts without authorizing fixes. Existing continuity tests are reusable evidence;
  missing real restart/cache-miss cases still need executable diagnosis.
- Debt remains `7 FIXED / 3 NEEDS_REVALIDATION / 0 OPEN`; no Host PASS/FAIL classification
  is inferred from reading code. Model requests/tokens and research allocations stay zero.

## 2026-09-22 — Scoped fresh/Claim/cache ownership proof complete locally

- [Receipt and limits](../revalidation/trace-ownership/REVALIDATION.md): final source
  `519ba02bbedc7507237bb78267679ef0cf62cf71`, Product tree
  `22c011d0d9dc267c2a82a71cd9a4c2b2fdbb199f65aa0084eaf25d6583487f8a`.
  47 Product tests (8 real PostgreSQL), 76 targeted Lab tests pass.
- Two actual chains total 18 Host attempts / 16 controlled Provider fixture calls.
  Evidence bodies and Claim records retain distinct exact hashes. Five actual cache
  validations bind new Runtime requests to observed origins; governed supersession
  causes a fresh retrieval before the revised version can be reused.
- Claim/cache run retains its actual source `83e69ed74a30a76f16bb6b039f4b7013b1cf2d77`;
  only two test files changed before the final source. No old evidence is relabeled.
- Trace debt is locally FIXED for the serial non-stream query-first public testkit;
  TECH_DEBT is `7 FIXED / 3 NEEDS_REVALIDATION / 0 OPEN`. This is SCOPED G7, not
  full architecture conformance, Host continuity or measured model benefit.
- 3B-1 stays IN_PROGRESS until exact-head fast CI, expected-head merge and main identity
  pass. Model requests/tokens and research allocations remain zero. Dedicated DB and
  owned processes are stopped, data retained. No full-suite or historical replay rerun.

## 2026-09-22 — Fresh chain merged; Runtime Claim/cache observations locally verified

- PR #33 exact head `d4062203eed49bb7fffa7ca3472106c21a1278a9`, fast `35680232860`
  PASS; expected-head squash merge `489ea7ca8c3756630f32da0e2c52a0940c97d74e`.
  Candidate/merge tree `7affaf3ac122d939513bcf406ed09c72efa13a93` matched;
  local main fast-forwarded cleanly; main identity fast `35680800370` PASS.
- `behavior/trace-cache-provenance` starts from that exact main. Its Runtime-only
  [Claim/cache owner slice](../reference/trace-cache-owner.md) observes immutable
  governed Claim records and the current receipt revalidation separately from the
  original retrieval; support Evidence refs are not claimed as acquired bodies.
- Source `00ff8c3a1f4a524ddbc5f7e149f64128e88b7a12`: 29 narrow tests PASS, including
  five real PostgreSQL cases for exact/wrong-scope neutrality, actual HTTP reuse,
  scope invalidation and governed supersession. Changed static checks passed.
  Isolated database stopped with data retained; models/allocations 0.
- Lab cache/Claim join, actual cross-layer cache proof and final Product debt receipt
  remain pending. This local producer slice is not remote closure or 3B-1 PASS.
  No full composition, historical replay, default behavior or Schema change.

## 2026-09-22 — Runtime producer merged; actual fresh cross-layer join verified

- PR #32 tested head `314338a05e9b6c9f448f7c570a9b23581c91dc09`, fast `35677817059`
  PASS; protected merge `6f5ecf6132e81585509d5124cab55e51cc7754f7`, candidate/merge
  tree `84c3bdf3ac9246c16de01450795b7d3da403f04b` matched. Main fast `35677932965` PASS.
- Branch `behavior/trace-ownership-chain` adds the explicit loopback Runtime harness,
  actual MCP/Context dispatch observation and Lab owner-export assembler. Final source
  `717da6e74aba02e296e30ac4f037c208b753ab18`; Product 425 files, tree
  `90a900fef01ccca5b54cc4a558e3c530cf7a8b421f859d764761a8d6c4f75511`.
- [Bounded same-execution proof](../reference/trace-ownership-chain.md): 8 Host attempts,
  real broker/MCP subprocess/HTTP/PG/worker, 7 in-process Provider fixture invocations,
  3.195 s. Fresh success/retry/abstain/no-memory and three failure dispatch states join;
  all use remains UNKNOWN and failure usage remains explicit. Models/allocations 0.
- Runtime 10, OpenWorker 12, Lab join/assembly 47 and boundary contract 5 targeted tests
  passed; changed static and both Lab boundaries passed. Package checks go to fast CI;
  no repeated full composition or historical replay. Isolated DB stopped, data retained.
- Repeats did not produce cache hits. Cache-origin, supported version paths and final
  debt receipt remain pending; 3B-1 remains IN_PROGRESS, not PASS. Existing historical
  receipts remain unchanged; Product default behavior and Schema NO-GO are unchanged.

## 2026-09-22 — Host producer merged; Runtime owner export and real PG evidence

- PR #31 tested head `7aeeb1477c67b9c7584ebbeb0c1dca5e1da0a798`, fast `35676964005`
  PASS; protected squash merge `0971ef6c942bdb2267e70389db76849a5a561db8`.
  Candidate/merge tree `7433c0c5744f8edd186eed03faefbc5b5604ff35` matched; main fast
  `35677115118` PASS. Runtime follow-up branch starts from this exact main.
- New `--owner-trace` option on the public retrieval testkit is off by default. It exports
  the captured DecisionSnapshot digest, gate/binding digests, actual recorded trace/position,
  and exact materialized EvidenceRecord hashes. Missing versions remain explicit gaps.
- Runtime targeted tests: 40 PASS / 0 skips (2.79 s), including real PostgreSQL empty,
  visible and wrong-scope cases. All three normal/baseline/traced neutrality checks pass.
  Exact commands, external JUnit identity and limits are in the
  [testkit runbook](../reference/retrieval-trace-testkit.md#opt-in-runtime-owner-export-v1).
  Isolated PostgreSQL 16.14 container stopped after testing; data retained. No model calls.
- Source commit `63022a76a6bf1f9408d4c26c3ebc4f66540170a4`, Git tree
  `3311524648ab7c9608e550cfd65af8b2a86df2bc`; Product 424 files, tree
  `223dad55d2c0f3f9a50686192a35d10a28127c989a9d45f3cbf1a6a77cc6b265`.
  No default Runtime/MCP behavior, schema, permission or Canonical change; existing receipts
  remain historical, Conformance stays `9 PASS / 35 UNVERIFIED / 0 DEVIATION`.
- 3B-1 remains IN_PROGRESS: producer facts must still be assembled for the same actual
  MCP/Host/Provider invocation, with cache-origin and exact-version provenance. No Phase 3C
  or model-backed effect run is admitted by these engineering tests.

## 2026-09-22 — 3B-1 offline contract merged; opt-in Host producer observation in progress

- PR #30 tested head `d7d4a49a76699a806ab3e968ce75520a22d69759`, exact fast run
  `35675543341` PASS. Protected squash merge `5d77fa6ace30d8bc64eeef287d10bfffd4c44992`;
  candidate/merge tree `f4d0e46bff01bfa4ed609095f3e9e2ae9f7e20a5` matched. Main fast
  `35676214359` PASS. This closes the offline slice, not 3B-1.
- Follow-up branch `behavior/trace-owner-exports` preserves the tested PR candidate and adds
  an explicitly imported [Host owner observation testkit](../reference/host-trace-testkit.md).
  It delegates to the real Adapter/gateway, binds fresh attempt IDs to actual transport calls,
  retains unknown usage, and exports only allowlisted metadata. The default Adapter is not
  instrumented; its sole edit is a transport Protocol annotation.
- Targeted Product-owned tests and adjacent regressions: 28 PASS (0.64 s), changed-module
  Ruff/mypy PASS. Initial fixture/assertion failures and limitations are recorded in the runbook.
  MCP/Provider are synthetic test transports; no external model requests or experiment allocations.
- Runtime decision/version export, actual MCP binding, cache-origin provenance and assembled
  end-to-end proof remain pending. Trace debt stays NEEDS_REVALIDATION; 3B-1 stays IN_PROGRESS.
- Producer source commit `652d2a2ef4637b11b4d0a4592a25712aa7a93b3a`, source Git tree
  `75313f97cbbb23985a01337adf0dc94cc49fb18a`. Product now has 423 manifest files and tree
  `5d7a5b4d0b79b9ef6555ad8eac8f1c9cecbdf1545e12ab2ef4c5bc455205e272`.
  Fresh generated Conformance is `9 PASS / 35 UNVERIFIED / 0 DEVIATION`: the 14 existing
  behavior receipts are preserved at their original identities and are historical for this
  additive source tree. This is an evidence-freshness change, not a diagnosed regression;
  unrelated behavior tests are not repeated to restore a PASS count.

## 2026-09-22 — 3A-1 closed; docs-only CI optimization closed; 3B-1 entered

- PR #28 tested head `63f80ab5358c9f264274ee1904b590f0859b6fbd`, fast `35674072940` PASS;
  protected squash merge `81f2f12844674983973ae7dad99868211ba1a1bb`.
  Candidate/merge tree `15807bbaac1702adc0fcc7402524364ceda888ae` matched;
  main fast `35674495200` PASS. 3A-1 is now PASS.
- PR #29 limits Lab Markdown documentation changes to the docs-only path. Non-Markdown docs,
  source, tests, tools, configuration and explicit full override remain conservative.
  Classifier 8 tests PASS; exact-head fast `35674538585` PASS at
  `e8ea5f1f2c2e809b2bdd53392a6ed837147db825`; protected squash merge
  `755cdfc947f34efa03cc0bb1eed682233767b061`; tree
  `44e9ff8b7fee6da005e5b8b20eb10a3396f17ac1` matched; main fast `35674644575` PASS.
- Branch `behavior/trace-ownership-v1` starts from that exact main. Initial scope is the
  [versioned ownership candidate](../reference/trace-ownership-v1.md) and Lab-only pure joiner.
  Synthetic success/retry/abstain/failure/no-memory/unknown-use cases do not establish live
  Product ownership. 3B-1 remains IN_PROGRESS; trace debt remains NEEDS_REVALIDATION.
- Product executable tree unchanged; no Schema/API/permission/Canonical change. No model
  requests, new experiment allocation, resumed historical experiment or full composition.
- Offline joiner targeted tests: `37 passed` (0.17 s); changed-file Ruff/mypy and both Lab
  boundary gates PASS. Product manifest, current conformance receipt and repository boundary
  PASS. Package-wide verification is delegated to the classified Lab fast CI, not duplicated
  locally; no packaging change, database test, historical replay or full-composition run.

## 2026-09-22 — 3A-1 local revalidation PASS; remote closure pending

- Real child CLI/isolated PostgreSQL 16.14 matrix and adjacent tests: 20 PASS / 0 skips (12.02 s).
- Source/tests commit `4b76405f3e3e73ed85713161eb9465e7bbf5cc82`; Product executable identity unchanged.
- Empty/below/above limit, independent projections, orphan, no work, handled failure,
  dependency-check, watermark and nonzero startup failure are covered.
- Exit 0 is normal cycle return, not all-delivery success. Handled failure persists PENDING or
  DEAD_LETTER and the affected watermark stays behind its gap. The runbook now states this contract.
- TECH_DEBT becomes `6 FIXED / 4 NEEDS_REVALIDATION / 0 OPEN`; new scoped receipt in
  `docs/revalidation/worker-once/receipt.json`. No Product behavior or new full-composition run.
- Initial new-test metric-key failure is preserved in the report; final targeted execution passed.
- 3A-1 remains IN_PROGRESS until tested-head merge and main identity close.

## 2026-09-22 — User resume; 3A-0 closed; 3A-1 entered

- 用户明确要求执行本 Goal，并减少不必要的测试和审计；使用 L0–L4 最小充分验证。
- PR #27 tested head: `83ae1435d9003c1eeaf5d9182675974fbcd2f479`;
  exact-head fast run `35672424053` PASS; full run `35672424071` SKIPPED，未执行 full jobs。
- 使用该 head 作为 expected-head squash merge；merge/main:
  `cf149939eea9f184159ebfb6aab1a3e791988250`。
- Candidate/merge Git tree 同为 `cd974ead30b0de003e654fc9e0568f96062b711e`，
  `git diff --exit-code <candidate> origin/main` PASS。
- 本地 main 已 fast-forward，`main == origin/main`，工作区干净；该 merge commit 的
  main fast run `35673403788` PASS，包含 Tested PR tree identity。
- 从 exact main 创建 `behavior/revalidate-worker-once`；3A-0 PASS，3A-1 IN_PROGRESS。
- 本次恢复没有启动历史实验、模型/Provider/Judge 调用或分配新的实验额度。

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
