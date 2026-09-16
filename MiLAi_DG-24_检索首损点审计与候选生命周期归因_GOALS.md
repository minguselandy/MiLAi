# MiLAi DG-24：检索首损点审计与候选生命周期归因 Goal

> Goal ID：DG-24
> 方法名：Retrieval First-Loss Audit / Candidate Lifecycle Attribution
> 文档版本：0.1.0 DRAFT FOR OWNER EXECUTION AUTHORIZATION
> 起草日期：2026-08-29（Asia/Shanghai）
> 当前状态：DOCUMENT READY / IMPLEMENTATION NOT STARTED
> 本次 Owner 授权：仅生成 Goal 文档；不等于授权执行代码、运行数据库、调用模型、打开 formal holdout 或发布 Candidate
> 前置终态：DG-23 = PARKED_READER_SEMANTIC_NON_MONOTONICITY
> 本 Goal 性质：纯观察性诊断；不优化检索算法，不改变产品候选、Binding、Sufficiency 或答案
> 主终态：PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED
> Reader：禁止调用
> 生成式 Provider / Controller：禁止调用
> Canonical mutation：禁止
> Candidate 默认：OFF
> Formal holdout：UNTOUCHED / NOT AUTHORIZED
> Public MCP schema：禁止修改
> PostgreSQL schema：禁止修改
> architecture/v1.0：禁止修改
> 默认禁止：ALGORITHM TREATMENT / RULE REMOVAL / LEAVE-ONE-RULE-OUT / RERANKER / TOP-K TUNING / MULTI-CHANNEL PRODUCT UNION / GOLD-AWARE RUNTIME / EVAL-OWNED RETRIEVAL / RETRY-TO-PASS

---

# 0. Goal 决定

DG-24 是 DG-20～DG-23 之后的诊断性 successor。它不覆盖、重算或改判任何前序 Goal 的历史终态。

DG-20～DG-23 已经分别建立或暴露：

~~~text
DG-20
  fresh RequirementState
  Capability-constrained official acquisition
  deterministic-only path can recover some missing evidence

DG-21
  type-directed acquisition and temporal point retrieval improved
  generalized policy still exceeded an acquisition-call gate
  Reader failure prevented complete effect scoring

DG-22
  recall / Binding precision improved
  temporal COUNT remained incomplete
  one correct-case regression blocked overall PASS

DG-23
  presentation budget was separated from deterministic decisions
  context structure, safety, recall/Binding and quality gates passed
  fixed Reader still regressed two temporal-count cases
~~~

这些结果不能直接回答以下问题：

~~~text
一个合法、answer-bearing evidence obligation
究竟在哪一个真实产品 stage 首次失去可达性？

它是：
  没被任何 channel 发现
  channel 可用但未调用
  被 query expression 限制
  被 hard filter 删除
  被 local/global cutoff 挤掉
  被错误 dedup representative 替换
  未通过合法 Governance Gate
  未被 Interpretation/Binding 接受
  还是 evidence items 已齐但 proof obligation 未闭合？
~~~

DG-24 的唯一主目标是：

> 在不改变当前产品行为的条件下，对每个 opened-development query 的每个 requirement、evidence role / acceptable evidence equivalence group 和 proof obligation，机器化定位其在 discovery、filtering、ranking、selection、interpretation、binding 或 proof closure 中的首个不可恢复损失点。

DG-24 不是准确率修复 Goal。其 PASS 不要求 EM、F1、Recall@K 或 OperatorReady 提升；任何提升都不能作为本 Goal 的成功证据。

## 0.1 纯观察性定义

DG-24 中的“纯观察性”同时满足：

~~~text
同一个 request
同一个 query plan / QueryIR
同一个 capability and policy snapshot
同一个 repository / index snapshot
同一个 channel invocation decision
同一个 query text and generated features
同一个 candidate sequence
同一个 dedup result
同一个 Gate result
同一个 EvidenceSet selection
同一个 Interpretation / Binding
同一个 RequirementState
同一个 Sufficiency / operator readiness

只新增：
  immutable trace
  isolated read-only official probe
  post-seal scorer attribution
~~~

以下行为不属于观察：

~~~text
删除或替换 _SYNONYMS
改变 regex query classification
把 lexical/entity hard filter 改为 soft feature
改变 fixed channel priority
增加 per-channel quota union
扩大 product Top-k / candidate cap
修改 fusion / scorer
加入 vLLM reranker
加入 residual cue
执行 leave-one-rule-out
按 case ID、答案或 gold evidence 分支
~~~

这些 treatment 必须等待 DG-24 封存，再由 successor Goal 预注册。

## 0.2 Primary claims、supporting claims 与 anti-claims

| ID | 类型 | 可在 DG-24 检验的命题 | 最低证据 |
| --- | --- | --- | --- |
| C1 | Primary | 当前真实 retrieval-to-Sufficiency 路径可以在不改变行为的前提下被完整追踪 | tracing OFF/ON 的 candidate order、Binding、RequirementState、Sufficiency 与 operator digest 完全一致 |
| C2 | Primary | 每个 opened-dev requirement 的合法 evidence group 或 proof obligation 都能获得唯一、机器可复算的 first-loss attribution | 全部分母有 disposition；无未解释 drop；scorer 独立复算一致 |
| C3 | Primary | 产品执行、official audit probe 与 gold scorer 可以物理隔离 | 产品与 probe seal 前 labels 未加载；Runtime trace 不含 gold IDs；probe 不进入产品 Binding |
| C4 | Supporting | 当前已实现 channel 的 availability 与 product router opportunity loss 可以被独立量化 | official AcquisitionService 的宽池 probe、channel lineage、snapshot identity 与 offline cut curves |
| C5 | Supporting | 当前 synonym、regex、hard filter 和 priority 规则对候选生命周期的观察性关联可以量化 | RuleFeatureAttributionReport；不做规则移除，不做 answer 因果主张 |
| AC1 | Anti-claim | DG-24 不证明 retrieval accuracy 已改善 | product output 必须不变；无 treatment arm |
| AC2 | Anti-claim | DG-24 不证明某条规则因果导致成功或失败 | 不运行 leave-one-rule-out；correct_answer_dependency 固定为 NOT_MEASURED_DG24 |
| AC3 | Anti-claim | DG-24 不证明 state-aware reranking、multi-channel union、vLLM planner 或 graph retrieval 有效 | 这些方法均不进入执行路径 |
| AC4 | Anti-claim | DG-24 不解决 temporal completeness 或 Reader semantic non-monotonicity | proof loss 与 Reader lane 分开路由 |
| AC5 | Anti-claim | opened-dev attribution 不等于 formal holdout generalization、Production readiness 或 Schema freeze | formal holdout 0 case；Candidate OFF；架构和 schema 不变 |

## 0.3 研究与工程命题

DG-24 回答的是：

~~~text
Where is the first irrecoverable loss?
~~~

不是：

~~~text
Which new algorithm should win?
~~~

形式化对象包括两类。

证据等价组：

\[
G_{r,j} = \{e_1, e_2, \ldots\}
\]

其中任一合法 evidence span 可以承担 requirement r 的 evidence role j。

证明义务：

\[
O_{r,k} \in
\{
RANGE\_SCAN,
PARTITION\_CLOSURE,
EVENT\_TIME\_RESOLUTION,
EVENT\_IDENTITY,
DEDUP,
PROJECTION\_CLOSURE,
RAW\_FALLBACK\_CLOSURE,
ACCESS\_SNAPSHOT
\}
\]

两者分母必须分开。找到了所有 event points，不等于 RANGE_COMPLETENESS proof 已成立。

## 0.4 Successor 边界

DG-24 terminal 只能选择后续方向，不能自动实施：

| 主要首损点 | 合法 successor |
| --- | --- |
| NOT_DISCOVERED / expression / channel availability | DG-25 multi-channel candidate generation |
| CHANNEL_ELIGIBLE_NOT_INVOKED | DG-25 routing / quota union |
| hard filter / cutoff / fixed priority / dedup representative | DG-25 ranking and selection |
| Interpretation / grounded span / semantic relation | DG-27 grounded interpretation |
| temporal or set proof obligation | DG-28 BoundedRangeScanProofV02 |
| EvidenceSet 与 operator 正确、Reader 仍回归 | DG-29 Reader evidence-consumption conformance |
| 所有正式 channel 均不可达且存在 associative evidence | 另开 bounded cue-graph Goal |
| deterministic path 已经完成 | 不调用模型，不增加 treatment |

---

# 1. 权威事实基线

## 1.1 规范优先级

发生冲突时按以下顺序解释：

1. architecture/v1.0/ frozen bundle；
2. MiLAi_Logical_Architecture_v1_设计文档.md 中的 frozen MUST；
3. MiLAi_Lean_V1_实施合同.md；
4. executable Runtime、official AcquisitionService 与真实 PostgreSQL tests；
5. DG-23 S9/S8/S7/S6/S0 sealed receipts、products、scores 与 manifests；
6. DG-23 Goal；
7. 本 Goal；
8. runbook、README、注释和自然语言总结。

必须保持：

~~~text
EvidenceRecord != ClaimVersion
search result != accepted evidence
candidate score != RequirementBinding
RequirementState != completion authority
proof obligation != retrieved event point
projection/search/context/model cannot raise truth or authority
permission/retention/revoke unknown fails closed
Sufficiency and operator remain deterministic
Audit result cannot mutate Production policy or canonical state
~~~

## 1.2 绑定输入与 SHA-256

| Artifact | SHA-256 | 用途 |
| --- | --- | --- |
| architecture/v1.0/architecture_manifest.json | ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e | frozen architecture identity |
| MiLAi_Lean_V1_实施合同.md | 395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba | implementation contract |
| MiLAi_DG-23_预算稳定上下文编译与答案回归闭环_GOALS.md | c36fca58068feeb6cc1aaa3561dbaf1970271bcc287e1776e5dafd01dc9b97f5 | predecessor Goal |
| var/dg23/s9/dg23-s9-terminal-20260829-001/receipt.json | fa1a71b1c724c0632ca3edea04a6a331821a554cd8bb0e79f41e863e002020f2 | authoritative predecessor terminal |
| var/dg23/s0/dg23-s0-baseline-freeze-20260829-001/baseline.json | d0a974448d3ea78de3adb8b95aedfb39377dca8c7e4ff672ed6247a2bcdf5d28 | opened-dev baseline identity |
| var/dg23/s0/dg23-s0-baseline-freeze-20260829-001/denominator-freeze.json | 6ed89d02fbfe4023e8171768055c847772356cb41f745f929364e3763945a87a | 10-case order and denominator |
| var/dg23/s6/dg23-s6-opened-dev-context-20260829-019/sealed-opened-dev-context-product.json | c29ef303695ef9b991fe4fc9e7e2dc30548e2cc8674d803952b6b3d764ab5c78 | predecessor product trace source |
| var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/context-score.json | ba641d024c81a9e502c3b3ab7a13b6719bf5b2bb1fe891e6700ec6808d290ee0 | predecessor mediator score |
| var/dg23/s7/dg23-s7-matched-reader-20260829-002/answer-score.json | 9e4a42b072dea1133f9714ead53987bf7c9156da549efae41161f9e2305835d4 | predecessor Reader regression facts |
| var/dg23/s8/dg23-s8-quality-20260829-004/receipt.json | 1868f439e196bb0e3d1614461606c4e2a733ce52261b4f3aee48b5508ca36bcb | predecessor quality identity |

以上制品只读。执行 DG-24 时必须创建新的 run ID、var/dg24/、failure index、source manifest、artifact manifest 与 terminal receipt。

## 1.3 DG-23 终态机器事实

DG-24 以 terminal receipt 为准：

~~~text
overall_disposition
  PARKED_READER_SEMANTIC_NON_MONOTONICITY

context_decision_disposition
  PASS_BUDGET_INVARIANT_DECISION_AND_CONTEXT

recall_binding_disposition
  PASS_DG22_RECALL_BINDING_NON_REGRESSION

answer_disposition
  FAIL_CORRECT_CASE_REGRESSION

safety_disposition
  PASS_DG23_SAFETY

quality_disposition
  PASS_DG23_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE

schema_lane
  NOT_ENTERED_SCHEMA_AUTH_REQUIRED

formal_holdout_consumed
  false

candidate_default
  false
~~~

DG-23 opened-development metrics 只作为冻结背景：

~~~text
safe_oracle_normalized_recall                 0.8666666666666667
required_evidence_coverage_reference          22
required_evidence_coverage_512                18
accepted_binding_precision                    1.0
additional_acquisition_calls                  4
candidates_hydrated                           18
useful_candidate_rate                         1.0
wrong_complete                                0
primary_regression_case_ids                   2e6d26dc, 88432d0a
~~~

DG-24 不重跑 Reader，也不以这些 answer metrics 作为 PASS denominator。

## 1.4 当前 opened-development case order

顺序冻结为：

~~~text
gpt4_8279ba03
9a707b82
2a1811e2
0bb5a684
2e6d26dc
4dfccbf7
gpt4_88806d6e
a89d7624
a82c026e
88432d0a
~~~

这些是 diagnosis/development cases，不是 formal holdout。case ID 只允许出现在 evaluator orchestration、artifact 分区和 scorer 中；Runtime 的 routing、filter、ranking、Binding 与 proof logic 禁止读取 case ID。

## 1.5 当前源码观察点

本 Goal 起草时，下列源码身份构成首轮审计入口：

| Source | SHA-256 | 当前关注点 |
| --- | --- | --- |
| runtime/src/milai/application/accuracy_acquisition.py | ddd6a05ae168c62f1e309c4e1de684c063f30514e66ec4d9eeaeed755932947e | synonym normalization、type rules、channel bundle、candidate filtering |
| runtime/src/milai/application/evidence_acquisition.py | 6909326e1bf2f0236127fddf43484d75b1ccca77c52498b4263b1e6a6cca5b6a | official executor、probe selection、fusion、Gate/Binding/proof |
| runtime/src/milai/persistence/retrieval_repository.py | 9c158681ea5ac06e7101b276dbe6467ccba2edc141332ae74af2340445c8575a | official FTS/dense/temporal repository execution |
| runtime/src/milai/application/acquisition.py | b01d2729f6f19032a6077ab5a552058ba2c729e6933e515c0c11e1744f5bd19d | probe query、ranking、fusion |
| runtime/src/milai/application/retrieval.py | bc525c55be666eca3d71cccadba775bfeb222d5a241fac651fcb78f97958b2c7 | product read path orchestration |
| runtime/src/milai/application/memory_query.py | 8307d22e830bf9bfffcb1db51fe51d8e13b2a2898ee7192bbf97e814286135ba | regex-driven query/operator classification |
| runtime/src/milai/application/evidence_semantics.py | 888bfa3f161f455930909f0ddb2c489655f4b08bb5106f8a4cba56665a4d2cef | semantic normalization、span projection、interpretation |
| runtime/src/milai/application/requirement_state.py | de7c5ae47c1d28b0f3f978f1e0897237c3e73009a91997e09b59bd1b4d75fe1a | fresh RequirementState |
| runtime/src/milai/application/sufficiency.py | fc8d54a76e2c9303a8c7cc09a57095c01732ca632fefc2d8fe9ddaedcc115dda | typed sufficiency |
| runtime/src/milai/application/deterministic_recovery.py | 9b62d078d30eb1ff08e0c7ccd24e1f525d4584c7530395d4c80d88a815bdf334 | deterministic action selection |
| runtime/src/milai/application/acquisition_capability.py | 3cccfec3f3d4877cadf6859ef0d6a0794ed4d2101013b884555f66bb0a563568 | CapabilitySet 与 feasible actions |

这些 hash 不是对 stage 顺序的推断。S0 必须从实际调用图建立 StageImplementationRegistryV01；若执行授权前源码变化，必须生成新的 source manifest 并显式说明，不得静默沿用上述 identity。

## 1.6 已知架构冲突

当前代码包含具有 benchmark-shaped 风险的机制，例如：

~~~text
hard-coded synonym normalization
regex query/operator classification
lexical or entity anchor filtering
candidate-disabled experimental paths
channel bundle / priority decisions
local and global candidate ceilings
temporal event heuristics
~~~

DG-24 不预判这些机制一定错误。它先回答：

~~~text
规则是否被触发？
规则改变了哪些 query features？
规则关联到哪些 retrieval occurrences？
candidate 在哪个 stage 被保留或删除？
合法 gold equivalence group 是否只沿该路径出现？
未调用的 official channel 是否本可发现该 group？
~~~

只有封存上述观察后，DG-25 才能实施 causal treatment。

---

# 2. 授权、范围与禁止项

## 2.1 授权矩阵

只有 Owner 明确要求“执行 DG-24 Goal”后，才可进入 S0。

| 变更或动作 | 本文预定义 | 执行 DG-24 后是否还需额外授权 |
| --- | --- | --- |
| 内部 immutable retrieval trace contract | 是 | 否；必须 behavior-neutral |
| 内部 StageImplementationRegistry | 是 | 否 |
| official read-only diagnostic probe entrypoint | 是 | 否；必须复用正式 AcquisitionService |
| scorer-only gold equivalence registry | 是 | 否；不得被 Runtime import |
| var/dg24 audit artifacts 与 runbook | 是 | 否 |
| 当前 10 opened-dev cases | 是 | 否；仅在 phase boundary 后打开 labels |
| real PostgreSQL integration/security test | 是 | 否；不得改 schema |
| Reader 调用 | 否 | 本 Goal 禁止 |
| generative Provider / vLLM planner / reranker 调用 | 否 | 本 Goal 禁止 |
| algorithm/ranking/filter/routing treatment | 否 | 本 Goal 禁止 |
| leave-one-rule-out | 否 | 移至 DG-25 |
| public MCP schema change | 否 | 退出本 Goal并另行授权 |
| PostgreSQL migration | 否 | 退出本 Goal并另行授权 |
| architecture/v1.0 change | 否 | 本 Goal禁止 |
| formal holdout | 否 | 必须另行明确授权 |
| Candidate default-on / Production release | 否 | 本 Goal禁止 |

## 2.2 In scope

~~~text
真实 pipeline stage registry
request / snapshot / config / source identity freeze
per-channel RetrievalOccurrence lineage
Evidence candidate lifecycle
dedup winner/loser lineage
filter/drop/cutoff reason codes
requirement / evidence-role / equivalence-group mapping
proof-obligation disposition
product-faithful label-free trace
official read-only channel availability probe
post-seal gold scoring
stage retention curve
first-loss distribution
observational rule-feature attribution
successor routing recommendation
~~~

## 2.3 Out of scope

~~~text
retrieval algorithm improvement
new synonyms or cue generation
removing existing rules
multi-channel product union
score normalization changes
RRF changes
hard-filter relaxation
Top-k changes
dense model changes
vLLM integration
state-aware reranking
action ranking
active retrieval loop
cue graph
temporal proof V02 implementation
Reader prompt/context/model changes
answer scoring as a primary endpoint
formal holdout
public schema
database migration
canonical commit
Production enablement
~~~

## 2.4 零模型调用的精确定义

DG-24 禁止：

~~~text
Reader calls
generative Provider calls
controller calls
reranker model calls
cue-generation calls
judge calls
automatic retries
~~~

若 official dense channel 的现有 repository 路径需要冻结的 embedding/index client，audit probe 可以按当前正式合同使用，但必须：

~~~text
使用已存在的 official adapter
记录 exact model/index identity
不重建索引
不切换 embedding model
不新增隐藏 generation call
成本单独记为 diagnostic probe cost
~~~

---

# 3. 三平面隔离与标签边界

## 3.1 物理分离

DG-24 必须有三个互不混用的平面。

### A. Product trace plane

输出：

~~~text
ProductRetrievalTraceV01
CandidateLifecycleTraceV01
StageImplementationRegistryV01
~~~

特性：

~~~text
label-free
执行当前产品真实路径
不额外调用 channel
不改变 candidate / decision
不读取 acceptable evidence IDs
不读取 expected answer
~~~

### B. Official audit probe plane

输出：

~~~text
OfficialAuditProbeTraceV01
~~~

特性：

~~~text
label-free
只在全部 Product trace seal 后运行
调用相同 repository / index / AcquisitionService
使用只读 snapshot
不进入产品 Binding / RequirementState / Sufficiency
不更新 seen-region ledger
不推进 index watermark
不写 canonical state
~~~

### C. Gold scorer plane

输入：

~~~text
sealed ProductRetrievalTraceV01
sealed OfficialAuditProbeTraceV01
pre-sealed GoldEquivalenceRegistryV01
pre-sealed ProofObligationRegistryV01
~~~

输出：

~~~text
ScoredFirstLossReportV01
RuleFeatureAttributionReportV01
stage retention reports
successor routing report
~~~

特性：

~~~text
registry 在首个 product request 前由独立 scorer steward 预注册并封存
product/probe runner 只能看到 registry digest，不能读取内容
只有 Product 和 probe 两个 seal 均验证后，scorer 才可重新打开同一 registry
registry 不得在观察 lifecycle trace 后修改
不得调用 Runtime retrieval
不得回写 product/probe artifacts
不得重新运行任何 case
~~~

## 3.2 强制执行顺序

~~~text
Phase 0
  scorer steward freezes gold/proof registries
  → opaque registry seals
  → close label store

Phase A
  all product-faithful runs
  → product seal

Phase B
  all official diagnostic probes
  → probe seal

Phase C
  verify both seals
  → reopen the exact pre-sealed scorer-only registries
  → reject any registry identity drift
  → score

Phase D
  quality and integrity
  → terminal seal
~~~

禁止交错：

~~~text
product case 1
→ probe case 1
→ score case 1
→ product case 2
~~~

原因是 probe 可能改变进程缓存、数据库 page cache 或服务延迟；即使不改变逻辑状态，也不能让其先于未封存的 product execution。

## 3.3 Label-free enforcement

Product 与 probe 进程必须：

~~~text
不 import eval scorer module
不 import GoldEquivalenceRegistry
不读取 expected answer
不读取 acceptable_evidence_ids
不读取 acceptable_span_ids
不读取 equivalence_group_id
不读取 correct-case list
不读取 regression-case identity作为 routing feature
~~~

最低强制措施：

1. scorer steward 先生成不含 expected answer / gold evidence 的 InputOnlyCaseManifestV01；
2. product/probe runner 只能读取 InputOnlyCaseManifestV01，不得解析原始混合 label fixture；
3. gold/proof registry 位于 scorer-only package；
4. registry 在首个 product request 前由 scorer steward 预封存；
5. Runtime source tree 不得依赖 scorer package；
6. product/probe process 设置 label-access deny guard；
7. 测试中令 scorer import 或 gold file open 立即失败；
8. sealed product/probe artifacts 不含 gold fields；
9. product/probe 只接收 opaque registry seal digest，不接收内容；
10. scorer receipt 记录 reopening 时间晚于 product/probe 两个 seal 时间；
11. scorer 验证 registry identity 与 pre-run seal 完全一致；
12. scorer 验证 product/probe SHA-256 后才执行 join。

InputOnlyCaseManifestV01 只允许：

~~~yaml
InputOnlyCaseManifestV01:
  schema_version: input-only-case-manifest-v0.1
  case_order: []
  requests:
    - case_id:
      request_payload_digest:
      query_text:
      source_snapshot_ref:
      tenant_scope_digest:
  forbidden_fields_absent:
    expected_answer: true
    acceptable_evidence_ids: true
    acceptable_span_ids: true
    equivalence_group_ids: true
    correctness_labels: true
~~~

case_id 只用于 runner 的 artifact partition；传入 Runtime 的 request payload 必须剥离 case_id，并由 contract test 证明。

## 3.4 Audit runner 权限

遵循 Lean V1 实施合同：

~~~text
Audit runner
  只读授权 snapshot
  写 isolated audit artifacts
  无 Production canonical commit 权限
~~~

若需要真实 PostgreSQL：

~~~text
使用独立 audit/test login role
tenant/scope context 与产品请求一致
只读事务
禁止 migration owner
禁止 Steward executor
临时数据库必须登记并清理
~~~

---

# 4. First-loss 的分析单位

## 4.1 层级

唯一允许的主分析层级：

~~~text
query
└── requirement
    ├── evidence role
    │   └── acceptable evidence equivalence group
    └── proof obligation
~~~

不能只用 query-level gold turn。

## 4.2 Evidence role

示例：

### DIVIDE_VALUES

~~~text
NUMERATOR_VALUE
DENOMINATOR_VALUE
ENTITY_COMPATIBILITY
UNIT_COMPATIBILITY
~~~

### VERSION_DIFF

~~~text
OLD_VALUE
NEW_VALUE
TRANSITION_PROVENANCE
TIME_OR_VERSION_ORDER
~~~

### PREFERENCE_RESOLVE

~~~text
PREFERENCE_SUPPORT
CURRENTNESS_OR_UPDATE
CONFLICT_SIDE
SOURCE_ROLE
~~~

### COUNT_DISTINCT

Evidence item obligations：

~~~text
one group per distinct event member
EVENT_OCCURRENCE
EVENT_OCCURRENCE_TIME
DISTINCT_EVENT_IDENTITY
~~~

Proof obligations：

~~~text
BOUNDED_RANGE_SCAN
SOURCE_PARTITION_CLOSURE
EVENT_TIME_RESOLUTION
DEDUP_COMPLETENESS
PROJECTION_CLOSURE
RAW_FALLBACK_CLOSURE
ACCESS_SNAPSHOT
~~~

## 4.3 Acceptable evidence equivalence group

Gold registry 不应强迫唯一 turn：

~~~yaml
equivalence_group:
  requirement_id:
  evidence_role:
  acceptable:
    - exact evidence record
    - exact answer-bearing span
    - authorized adjacent context that contains the same grounded fact
  exclusions:
    - topic-only mention
    - assistant paraphrase without allowed source role
    - source-time-only item when event time is required
~~~

每组必须有 scorer-side mapping rationale。若 gold 无法映射到 requirement / role / legal source，则终态不能 PASS。

## 4.4 Proof obligation 不是 candidate

Proof obligation 的生命周期是：

~~~text
obligation emitted
→ feasible proof action available?
→ action selected?
→ action executed?
→ proof artifact produced?
→ proof validator accepted?
→ RequirementState recomputed?
~~~

它不能被伪装成：

~~~text
找到更多相似 candidate
~~~

---

# 5. StageImplementationRegistryV01

## 5.1 目的

规范 stage 名只是审计词汇，不得替代理解实际代码。

S0 必须从当前执行调用图生成：

~~~yaml
StageImplementationRegistryV01:
  schema_version: stage-implementation-registry-v0.1
  source_manifest_digest:
  product_entrypoint:
  official_probe_entrypoint:

  stages:
    - stage_id:
      sequence_index:
      semantic_name:
      status:
        ENABLED
        DISABLED
        NOT_APPLICABLE
      source_file:
      source_symbol:
      source_sha256:
      implementation_digest:
      input_contract:
      output_contract:
      can_drop_candidate:
      can_reintroduce_candidate:
      reason_code_enum:
~~~

actual sequence_index 是权威顺序。若实现中 hydration 在 Gate 之前，就按真实顺序记录；不能为了符合架构图篡改 trace。

## 5.2 最低 stage vocabulary

实际实现可拆分，但不得把多个可丢失阶段合并到无法归因：

~~~text
S00 QUERY_INPUT
S01 QUERY_IR_COMPILED
S02 REQUIREMENT_EMITTED

S10 CHANNEL_ELIGIBILITY
S11 CHANNEL_INVOCATION_DECISION
S12 RAW_CHANNEL_RESULTS
S13 INDEX_OR_REPOSITORY_PREFILTER
S14 CHANNEL_LOCAL_RANK
S15 CHANNEL_LOCAL_CUTOFF

S20 CROSS_CHANNEL_UNION
S21 DEDUPLICATION
S22 GLOBAL_PRIORITY_OR_FUSION
S23 GLOBAL_CUTOFF

S30 HYDRATION
S31 EVIDENCE_GOVERNANCE_GATE
S32 EVIDENCESET_SELECTION

S40 SPAN_PROJECTION
S41 INTERPRETATION
S42 BINDING_VALIDATION
S43 REQUIREMENT_STATE_RECOMPUTE
S44 SUFFICIENCY_OR_PROOF
S45 OPERATOR_READINESS
~~~

每个 case/channel 不存在的 stage 必须显式记录：

~~~text
NOT_APPLICABLE
NOT_ENABLED
NOT_INVOKED_BY_POLICY
CHANNEL_UNAVAILABLE
~~~

不得省略。

## 5.3 Stage implementation gate

任何 first-loss report 引用 stage_id 时，必须能追溯到：

~~~text
source file
source symbol
source identity
implementation digest
execution sequence
validator identity
~~~

若 trace 只写理想 stage 名、无法映射实际源码，则：

~~~text
PARKED_UNRESOLVED_CANDIDATE_LINEAGE
~~~

---

# 6. Candidate 与 retrieval identity

## 6.1 三层 identity

### RetrievalDocumentIdentity

表示某个 index/projection 中被检索的文档：

~~~yaml
RetrievalDocumentIdentity:
  projection_kind:
  projection_version:
  index_identity:
  document_id:
  source_locator:
  content_digest:
~~~

### EvidenceRecordIdentity

表示 canonical Evidence Plane 中的记录：

~~~yaml
EvidenceRecordIdentity:
  tenant_scope_digest:
  evidence_id:
  source_identity:
  source_ref:
  content_hash:
  observed_at:
  retention_snapshot_digest:
  permission_snapshot_digest:
~~~

### EvidenceSpanIdentity

表示可承担 Binding 的原子 span：

~~~yaml
EvidenceSpanIdentity:
  evidence_id:
  span_start:
  span_end:
  span_digest:
  source_role:
  occurrence_time:
~~~

projection document、EvidenceRecord 与 EvidenceSpan 不能共用一个含糊 candidate_id。

## 6.2 RetrievalOccurrence

同一 Evidence 可被多个 channel 发现：

~~~yaml
RetrievalOccurrenceV01:
  occurrence_id:
  request_identity:
  requirement_id:
  channel:
  channel_query_digest:
  channel_query_semantic_summary:
  normalized_terms: []
  generated_feature_ids: []
  retrieval_document_identity:
  raw_rank:
  raw_score:
  score_direction:
  latency_ms:
~~~

## 6.3 EvidenceCandidate

dedup 后对象：

~~~yaml
EvidenceCandidateV01:
  candidate_identity:
  evidence_record_identity:
  hydrated_span_identities: []
  session_id:
  turn_id:
  region_id:

  discovery_lineage:
    - occurrence_id:
      channel:
      raw_rank:
      raw_score:
~~~

## 6.4 Dedup trace

每次 dedup 必须记录：

~~~yaml
DedupDecisionV01:
  dedup_policy_version:
  dedup_key_version:
  dedup_key_digest:
  winner_candidate_identity:
  loser_candidate_identities: []
  winner_reason:
  preserved_channel_lineage: []
~~~

如果 gold evidence 在 dedup 后仍由合法代表存在，则不能记为 loss。

如果错误 winner 丢失 answer-bearing span，则：

~~~text
DEDUP_WRONG_REPRESENTATIVE
~~~

## 6.5 Canonical serialization

所有 digest 使用：

~~~text
UTF-8
stable field order
stable list ordering where contract requires
explicit null handling
no wall-clock field in semantic digest
SHA-256
~~~

trace ID、latency、created_at 不得进入产品行为等价 digest。

---

# 7. Trace contracts

## 7.1 RetrievalAuditRunV01

~~~yaml
RetrievalAuditRunV01:
  schema_version: retrieval-audit-run-v0.1
  run_id:
  phase:
    PRODUCT
    OFFICIAL_PROBE
    SCORER
    TERMINAL

  case_order_digest:
  code_commit:
  source_manifest_digest:
  config_digest:
  feature_flag_digest:
  dataset_snapshot_identity:
  memory_snapshot_identity:
  transaction_snapshot_identity:
  policy_snapshot_digest:
  permission_snapshot_digest:

  index_identities:
    raw_fts:
    enriched_fts:
    dense:
    temporal:

  query_ir_digest:
  requirement_set_digest:
  stage_registry_digest:

  reader_calls: 0
  generative_provider_calls: 0
  canonical_write_enabled: false
  automatic_retry_enabled: false
  formal_holdout_consumed: false
~~~

code_commit 可以为空，但 source manifest 不可为空。dirty worktree 不能用 commit identity 代替 transitive source identity。

## 7.2 ProductRetrievalTraceV01

~~~yaml
ProductRetrievalTraceV01:
  schema_version: product-retrieval-trace-v0.1
  run_identity:
  request_identity:
  query_identity:

  query_plan_digest:
  query_ir_digest:
  requirements:
    - requirement_id:
      kind:
      required:

  channel_decisions:
    - channel:
      capability_status:
      policy_eligibility:
      invocation_disposition:
      reason_code:

  occurrences: []
  dedup_decisions: []
  candidate_lifecycles: []
  proof_obligations: []

  terminal_digests:
    ordered_candidate_digest:
    gate_digest:
    evidence_set_digest:
    interpretation_digest:
    binding_digest:
    requirement_state_digest:
    sufficiency_digest:
    operator_readiness_digest:

  behavior_neutrality:
    baseline_digest:
    traced_digest:
    exact_match:
~~~

禁止出现：

~~~text
expected_answer
acceptable_evidence_ids
acceptable_span_ids
equivalence_group_id
gold_label
correct_case
~~~

## 7.3 CandidateLifecycleTraceV01

~~~yaml
CandidateLifecycleTraceV01:
  schema_version: candidate-lifecycle-trace-v0.1
  occurrence_id:
  candidate_identity:
  requirement_candidates: []

  discovery:
    channel:
    query_digest:
    normalized_terms: []
    generated_feature_ids: []
    channel_rank:
    raw_score:

  lifecycle:
    - sequence_index:
      stage_id:
      disposition:
        KEPT
        DROPPED
        REJECTED
        REDISCOVERED
        NOT_APPLICABLE
      reason_code:
      rank_before:
      rank_after:
      cutoff:
      validator_identity:
      decision_digest:
~~~

## 7.4 OfficialAuditProbeTraceV01

~~~yaml
OfficialAuditProbeTraceV01:
  schema_version: official-audit-probe-trace-v0.1
  run_identity:
  product_seal_digest:
  request_identity:
  requirement_id:
  channel:

  official_executor_identity:
  repository_identity:
  index_identity:
  snapshot_identity:
  scope_digest:
  policy_digest:
  query_digest:

  requested_audit_cap:
  returned_occurrences: []
  offline_cut_views:
    - cutoff:
      status:
        AVAILABLE
        EXCEEDS_VERIFIED_OFFICIAL_AUDIT_CAP
      occurrence_ids: []

  mutations:
    canonical: false
    context: false
    seen_region_ledger: false
    watermark: false

  product_binding_consumed: false
~~~

每个 query、requirement、channel、snapshot、scope 只允许一个最宽的授权 probe。S0 必须在不读取 gold 的条件下，根据 official repository 的已验证上限冻结 M_audit。Recall@8/16/32/64 中所有不超过 M_audit 的 cutoff 必须由同一 sealed result 离线切片，不能执行四次 repository call；超过 official 上限的 cutoff 显式记为 EXCEEDS_VERIFIED_OFFICIAL_AUDIT_CAP，不得临时扩权。

## 7.5 GoldEquivalenceRegistryV01

~~~yaml
GoldEquivalenceRegistryV01:
  schema_version: gold-equivalence-registry-v0.1
  scorer_only: true
  dataset_snapshot_identity:
  annotation_policy_version:

  queries:
    - query_id:
      requirements:
        - requirement_id:
          evidence_roles:
            - role:
              equivalence_groups:
                - equivalence_group_id:
                  acceptable_evidence_ids: []
                  acceptable_span_ids: []
                  acceptable_adjacent_regions: []
                  exclusions: []
                  rationale:
~~~

## 7.6 ProofObligationRegistryV01

~~~yaml
ProofObligationRegistryV01:
  schema_version: proof-obligation-registry-v0.1
  scorer_only: true

  queries:
    - query_id:
      requirements:
        - requirement_id:
          obligations:
            - obligation_id:
              kind:
              required:
              satisfaction_contract:
              acceptable_proof_artifact_types: []
~~~

## 7.7 RequirementLossAttributionV01

~~~yaml
RequirementLossAttributionV01:
  schema_version: requirement-loss-attribution-v0.1
  query_id:
  requirement_id:
  evidence_role:
  equivalence_group_id:

  discovery_availability:
  product_discovery:
  product_terminal_survival:

  first_loss_stage:
  first_loss_reason:
  first_irrecoverable_loss_stage:
  first_irrecoverable_loss_reason:

  transient_drop_stages: []
  rediscovery_stages: []
  last_surviving_candidate_identities: []

  authorized_absence: false
  label_resolution:
    EXACT_ID
    EXACT_SPAN
    ACCEPTABLE_ADJACENT_CONTEXT
    UNRESOLVED
~~~

## 7.8 ProofObligationTraceV01

~~~yaml
ProofObligationTraceV01:
  schema_version: proof-obligation-trace-v0.1
  query_id:
  requirement_id:
  obligation_id:
  obligation_kind:

  applicable_actions: []
  invoked_actions: []
  produced_proof_artifact_ids: []
  validator_identity:

  disposition:
    SATISFIED
    ACTION_NOT_AVAILABLE
    ACTION_NOT_SELECTED
    EXECUTION_FAILED
    VALIDATION_FAILED
    UNRESOLVED

  first_loss_reason:
~~~

## 7.9 ScoredFirstLossReportV01

~~~yaml
ScoredFirstLossReportV01:
  schema_version: scored-first-loss-report-v0.1
  product_seal_digest:
  probe_seal_digest:
  gold_registry_digest:
  proof_registry_digest:
  scorer_identity:

  per_equivalence_group: []
  per_evidence_role: []
  per_requirement: []
  per_query: []
  proof_obligations: []

  retention_curves: {}
  first_loss_distribution: {}
  channel_availability: {}
  authorized_absence: {}
  successor_routing: {}
~~~

---

# 8. First-loss 语义

## 8.1 Alive

对 equivalence group G 和某 stage 后的候选集合 S：

\[
Alive(G,S) =
\mathbb{1}
\left[
\exists e \in S:
e \models G
\right]
\]

其中满足关系由 scorer-side GoldEquivalenceRegistry 和合法 Gate/source-role/time contract 共同决定。

## 8.2 三种 discovery

必须分开：

~~~text
DiscoveryAvailability
  official diagnostic probe 的任一当前已实现 channel 是否能发现 G

ProductDiscovery
  当前产品实际调用路径是否发现 G

ProductTerminalSurvival
  G 是否存活到 EvidenceSet / Binding 输入
~~~

典型解释：

~~~text
Availability = true
ProductDiscovery = false
原因 = CHANNEL_ELIGIBLE_NOT_INVOKED
→ router opportunity loss

Availability = false
ProductDiscovery = false
→ NOT_DISCOVERED / representation or channel gap

ProductDiscovery = true
TerminalSurvival = false
→ filter / cutoff / dedup / Gate / selection loss
~~~

## 8.3 First loss 与 first irrecoverable loss

pipeline 可能非单调：candidate 被一个 channel cutoff 删除，随后由另一个 channel 再发现。

因此同时记录：

~~~text
first_loss_stage
first_irrecoverable_loss_stage
transient_drop_stages
rediscovery_stages
~~~

定义：

~~~text
TRANSIENT_DROP
  某 equivalence group 在 stage i 失去全部当前 occurrence，
  但在后续合法 stage 通过独立 lineage 重新出现。

FIRST_IRRECOVERABLE_LOSS
  从该 stage 之后到当前产品 terminal，
  equivalence group 再未以合法候选或合法代表出现。
~~~

报告主要排序使用 first_irrecoverable_loss；首次 drop 作为机制诊断保留。

## 8.4 Pre-discovery loss

若 channel 可用但未执行：

~~~text
CHANNEL_ELIGIBLE_NOT_INVOKED
~~~

这是 invocation opportunity loss，不是“candidate 被删除”。

若 channel 不存在或 index 未就绪：

~~~text
CHANNEL_NOT_AVAILABLE
~~~

若所有已实现 official channel 的宽池都没有 group：

~~~text
NO_CHANNEL_RETRIEVED_GOLD
~~~

## 8.5 Authorized absence

若 gold source 在当前权限、revocation、retention 或 tenant snapshot 下合法不可访问：

~~~text
AUTHORIZED_ABSENCE = true
~~~

必须同时报告：

~~~text
raw benchmark availability
policy-conditioned legal availability
~~~

它不能算 retrieval bug，也不能从分母静默删除。

## 8.6 Interpretation 与 Binding

若 group 存活至 candidate/evidence set，但：

~~~text
无 grounded span
关系未解释
subject/predicate/value/time/role/unit 不匹配
~~~

first loss 位于：

~~~text
SPAN_PROJECTION
INTERPRETATION
BINDING_VALIDATION
~~~

不能回写成 discovery failure。

## 8.7 Proof loss

当所有 required event-member groups 已 legally bound，但 COMPLETE 仍缺：

~~~text
first loss = PROOF_ACTION 或 PROOF_VALIDATION
~~~

不能归入 candidate recall。

---

# 9. First-loss reason taxonomy

reason code 必须来自冻结 enum，不允许自由文本代替主原因。

## 9.1 Discovery / invocation

~~~text
CHANNEL_NOT_AVAILABLE
CHANNEL_NOT_ENABLED
CHANNEL_ELIGIBLE_NOT_INVOKED
QUERY_EXPRESSION_MISMATCH
INDEX_REPRESENTATION_MISSING
TEMPORAL_SCOPE_MISROUTED
ENTITY_ALIAS_MISMATCH
NO_CHANNEL_RETRIEVED_GOLD
~~~

## 9.2 Query classification / prefilter

~~~text
LEXICAL_ANCHOR_HARD_DROP
ENTITY_ANCHOR_HARD_DROP
SOURCE_ROLE_FILTER_DROP
TIME_FILTER_DROP
SCOPE_FILTER_DROP
REGEX_TYPE_MISCLASSIFICATION
BENCHMARK_RULE_ASSOCIATION
~~~

## 9.3 Ranking / cutoff / fusion

~~~text
CHANNEL_CUTOFF_DROP
FIXED_PRIORITY_SUPPRESSION
GLOBAL_CUTOFF_DROP
SESSION_AGGREGATION_SUPPRESSION
REDUNDANCY_DISPLACEMENT
DEDUP_WRONG_REPRESENTATIVE
~~~

## 9.4 Governance / hydration

~~~text
ACCESS_DENIED_EXPECTED
REVOCATION_FILTERED_EXPECTED
POLICY_SCOPE_MISMATCH
HYDRATION_NOT_FOUND
HYDRATION_VERSION_MISMATCH
UNREADABLE_EVIDENCE
~~~

其中 expected governance drop 同时设置 AUTHORIZED_ABSENCE 或合法 candidate rejection，不得标记为 accuracy repair target。

## 9.5 Span / Interpretation / Binding

~~~text
SPAN_NOT_GROUNDED
SUBJECT_MISMATCH
PREDICATE_MISMATCH
VALUE_TYPE_MISMATCH
SOURCE_ROLE_MISMATCH
EVENT_TIME_MISMATCH
UNIT_MISMATCH
DUPLICATE_BINDING
CONFLICT_UNRESOLVED
INTERPRETATION_NOT_PRODUCED
~~~

## 9.6 Completeness

~~~text
PROOF_ACTION_NOT_AVAILABLE
PROOF_ACTION_NOT_SELECTED
BOUNDED_SCAN_INCOMPLETE
MAX_ITEMS_HIT
SOURCE_PARTITION_NOT_CLOSED
PROJECTION_BACKFILL_GAP
AMBIGUOUS_EVENT_TIME
EVENT_IDENTITY_UNRESOLVED
DEDUP_INCOMPLETE
RAW_FALLBACK_INCOMPLETE
ACCESS_SNAPSHOT_INVALID
PROOF_VALIDATION_FAILED
~~~

## 9.7 Audit-integrity failures

这些不是 retrieval first-loss 原因，而是 Goal 自身失败：

~~~text
STAGE_IMPLEMENTATION_UNBOUND
OCCURRENCE_LINEAGE_MISSING
DEDUP_LINEAGE_MISSING
GOLD_ROLE_MAPPING_UNRESOLVED
PRODUCT_PROBE_PATH_DIVERGENCE
LABEL_PRODUCT_BOUNDARY_VIOLATION
TRACING_BEHAVIOR_CHANGED
SNAPSHOT_IDENTITY_MISMATCH
SEAL_IDENTITY_MISMATCH
~~~

---

# 10. RuleFeatureAttributionReportV01

## 10.1 目的

DG-24 只记录规则与候选生命周期的观察性关联：

~~~yaml
RuleFeatureAttributionV01:
  rule_id:
  rule_family:
    SYNONYM
    REGEX_CLASSIFIER
    HARD_FILTER
    CHANNEL_PRIORITY
    TEMPORAL_HEURISTIC
  source_file:
  source_symbol:
  source_sha256:
  rule_version:

  affected_queries: []
  affected_requirements: []
  added_terms: []
  normalized_terms: []
  matched_occurrence_ids: []
  kept_candidate_ids: []
  dropped_candidate_ids: []

  acceptable_groups_observed_on_rule_path: []
  acceptable_groups_observed_on_independent_paths: []
  non_gold_candidates_on_rule_path: []

  final_binding_association:
  correct_answer_dependency: NOT_MEASURED_DG24
  causal_effect: NOT_ESTIMATED
~~~

## 10.2 允许的观察性指标

~~~text
RuleActivationRate
OpenedDevRuleExposureRate
GoldOccurrenceRulePathAssociationRate
ExclusiveObservedGoldPathRate
HardFilterGoldDropRate
RegexMisclassificationAssociationRate
FixedPriorityOpportunityLoss
GeneratedFeatureNonGoldRate
~~~

ExclusiveObservedGoldPathRate 只表示在当前 sealed traces 中没有第二条已观察路径；不得写成移除规则后的因果结论。

## 10.3 明确禁止

DG-24 不执行：

~~~text
Current rules vs remove one rule
rule mutation replay
rule order randomization
answer rerun
gold-aware query rewrite
~~~

leave-one-rule-out 是 intervention，必须在 DG-25 以独立 treatment、固定 baseline 和预注册指标执行。

---

# 11. Work Packages

## DG24-WP00 — Baseline、source、stage 与 denominator freeze

交付：

- 绑定 §1.2 artifact identities；
- 冻结 10-case order、memory snapshot、policy/config/index identities；
- 生成并封存 InputOnlyCaseManifestV01；
- 按 official repository capability、与 gold 无关地冻结每个 channel 的 M_audit；
- 由 scorer steward 在查看任何 DG-24 product/probe trace 前冻结 GoldEquivalenceRegistryV01 与 ProofObligationRegistryV01；
- 只向 product/probe runner 暴露两个 registry 的 opaque seal digest；
- 生成 current transitive source manifest；
- 生成 StageImplementationRegistryV01；
- 冻结 product semantic comparison fields；
- 建立 var/dg24/failure-index.jsonl append-only ledger；
- 证明 formal holdout 未访问；
- 证明 labels 未加载。

硬门：

~~~text
architecture manifest mismatch                 0
predecessor artifact mismatch                  0
source identity unresolved                     0
stage implementation unbound                   0
formal holdout consumed                        false
product/probe label access                     0
input-only manifest forbidden fields           0
gold/proof registry pre-run seal               valid
~~~

## DG24-WP01 — Trace contracts 与 synthetic lifecycle

零 Reader、零生成式 Provider、零 opened-dev labels。

实现内部 trace contracts：

~~~text
RetrievalAuditRunV01
StageImplementationRegistryV01
RetrievalOccurrenceV01
EvidenceCandidateV01
DedupDecisionV01
ProductRetrievalTraceV01
CandidateLifecycleTraceV01
OfficialAuditProbeTraceV01
~~~

synthetic matrix 至少覆盖：

~~~text
single-channel discovery and survival
eligible channel not invoked
unavailable channel
local cutoff drop
global cutoff drop
hard-filter drop
drop then rediscovery
dedup preserving legal representative
dedup losing answer-bearing span
governance authorized absence
hydration failure
interpretation failure
binding mismatch
proof action unavailable
proof action unselected
proof validation failure
~~~

## DG24-WP02 — Product-path instrumentation 与行为等价

在当前真实 product path 增加 immutable observer。

要求：

~~~text
trace OFF baseline run
trace ON matched run
same request identity inputs
same snapshot
same config/capability/policy
same repository call set and order
same candidate set and order
same Gate
same EvidenceSet
same Interpretation/Binding
same RequirementState
same Sufficiency/operator readiness
~~~

禁止：

~~~text
observer callback changes sorting
trace collection consumes iterators
trace field generation calls retrieval again
trace serialization changes transaction boundary
trace latency alters timeout policy
~~~

若 behavior 不一致，立即终止，不进入 opened-dev trace。

## DG24-WP03 — Phase A product-faithful label-free trace

执行：

~~~text
10 opened-dev cases
× current official product path
× one run per frozen request identity
× zero Reader
× zero retry
~~~

输出：

~~~text
per-case ProductRetrievalTraceV01
candidate lifecycle
channel decisions
proof-obligation product trace
behavior-equivalence report
product-phase receipt
product seal
~~~

所有 case 完成后一次性封存 product seal。S3 期间禁止 official audit probes。

## DG24-WP04 — Phase B official read-only channel probes

Entry：全部 Product traces 已封存且 seal 验证通过。

对每个当前已实现、当前 snapshot 可合法查询的 channel：

~~~text
same query
same requirement
same tenant/scope/policy snapshot
same official repository/index
one wide audit cap
offline views at each supported member of 8/16/32/64
~~~

要求：

~~~text
official AcquisitionService / repository
read-only snapshot
isolated audit namespace
no product Binding consumption
no seen-region mutation
no index/watermark mutation
no canonical mutation
no product rerun after probe
~~~

输出 official probe seal。

如果 eval harness 自己实现 BM25、fusion、neighbor expansion、temporal filtering 或 candidate packing：

~~~text
PARKED_EVAL_PRODUCT_PATH_DIVERGENCE
~~~

## DG24-WP05 — Phase C scorer-only registry reopen and validation

Entry：

~~~text
product seal valid
probe seal valid
all product/probe processes exited
~~~

重新打开 S0 之前已预封存的 registry；禁止根据 product/probe trace 增删 acceptable evidence 或 proof obligation。

交付：

- pre-sealed GoldEquivalenceRegistryV01 identity verification；
- pre-sealed ProofObligationRegistryV01 identity verification；
- mapping rationale；
- annotation/mapping disagreement ledger；
- scorer-only registry-reopen receipt；
- no-runtime-import contract test。

对每个 query/requirement：

~~~text
all required evidence roles mapped
all acceptable groups mapped
all proof obligations emitted
authorized absence policy defined
~~~

若任一 gold 无法映射：

~~~text
PARKED_GOLD_MAPPING_INCOMPLETE
~~~

发现 mapping 不完整后不得补标签并继续同一 Goal run；必须保留失败，修订 annotation protocol，重新预封存 registry，并使用全新 run identity 从 S0 开始。

## DG24-WP06 — First-loss scoring 与 successor routing

scorer 只读取 sealed artifacts。

生成：

~~~text
RequirementLossAttributionV01
ProofObligationTraceV01
ScoredFirstLossReportV01
RuleFeatureAttributionReportV01
StageRetentionReportV01
ChannelAvailabilityReportV01
FirstLossDistributionV01
SuccessorRoutingReportV01
~~~

独立复算至少两次，输入相同必须 byte-stable 或 canonical-digest-stable。

## DG24-WP07 — Quality、PostgreSQL、Security 与 rollback

运行：

~~~text
targeted DG24 unit tests
trace behavior-equivalence regression
DG20–DG23 behavioral regression
contract tests
strict mypy
Ruff
real PostgreSQL integration
real PostgreSQL security
architecture validate/lock
temporary database cleanup
secret/privacy scan for audit artifacts
~~~

即使数据库 schema 未改，也必须验证 audit role、tenant/scope、read-only probe 与 canonical no-write。

## DG24-WP08 — Terminal seal

生成唯一 terminal receipt，引用：

~~~text
S0–S7 receipts
product seal
probe seal
gold/proof registry identities
scored reports
failure index
source manifest
artifact manifest
runbook
~~~

terminal builder 不得重跑 retrieval、probe 或 scorer；只允许验证并汇总已封存制品。

---

# 12. Stage 执行顺序

~~~text
S0 Baseline / Source / Stage Freeze
→ S1 Trace Contracts and Synthetic Lifecycle
→ S2 Behavior-Neutral Product Instrumentation
→ S3 Phase-A Product-faithful Label-free Trace
→ S4 Phase-B Official Read-only Channel Probes
→ S5 Phase-C Pre-sealed Registry Reopen and Validation
→ S6 First-loss Scoring and Routing
→ S7 Quality / PostgreSQL / Security
→ S8 Terminal Seal
~~~

## S0 — Freeze

Entry：Owner 明确授权执行 DG-24。

Exit：所有 identity、stage implementation、denominator、禁止项与 label boundary 已冻结。

## S1 — Contracts

Entry：S0 PASS。

Exit：所有 trace schema、identity、drop/rediscovery、proof 与 authorized-absence synthetic tests 通过。

## S2 — Instrumentation

Entry：S1 PASS。

Exit：trace OFF/ON 对所有 semantic product fields 完全等价。

失败：

~~~text
PARKED_BEHAVIOR_CHANGED
~~~

## S3 — Product trace

Entry：S2 PASS。

Exit：10/10 product traces 完成、labels 0 access、product seal 生成。

任何 case 不允许自动 retry。基础设施失败使用新 run ID；不得替换原失败 receipt。

## S4 — Official probes

Entry：S3 全部 case seal 完成。

Exit：所有 current implemented channels 都有 official probe disposition 与 probe seal。

## S5 — Gold/proof registry reopen

Entry：S3/S4 seal verified。

Exit：S0 前预封存的 registry identity 未变化，且每个 requirement role / group / proof obligation 有合法 scorer mapping。

## S6 — Scoring

Entry：S5 PASS。

Exit：全部 first-loss、retention、rule association、channel availability 与 successor routing 可独立复算。

## S7 — Quality

Entry：S6 已封存，无论结果偏向哪个 successor 都进入质量门。

Exit：代码质量、真实 PostgreSQL、安全、清理和架构 lock 全部有 receipt。

## S8 — Terminal

Entry：S0–S7 receipts 齐全。

Exit：按 §18 封存唯一终态；不得以 tests PASS 覆盖 lineage、mapping、boundary 或 behavior failure。

---

# 13. Claim-driven experiment blocks

| Block | Claim | Runs | Priority | Stop/Go |
| --- | --- | --- | --- | --- |
| B1 Stage/source freeze | C1/C2 | static call graph + runtime witness | MUST | stage 无 source symbol/digest 即 STOP |
| B2 Synthetic lifecycle | C1/C2 | finite synthetic mutation matrix | MUST | drop/rediscovery/dedup/proof 任一不可归因即 STOP |
| B3 Behavior neutrality | C1 | trace OFF vs ON matched execution | MUST | candidate/decision drift 任一即 STOP |
| B4 Product trace | C1/C3 | 10 cases, label-free, no Reader | MUST | labels access 或 retry 任一即 STOP |
| B5 Channel availability | C4 | one official wide probe per requirement/channel | MUST | eval-owned retrieval 即 PARK |
| B6 Gold/proof mapping | C2/C3 | scorer-only mapping | MUST | unresolved role/group 即 PARK |
| B7 First-loss scoring | C2/C4/C5 | sealed trace join | MUST | denominator/disposition 不完整即 STOP |
| B8 Rule causal ablation | none in DG24 | zero | CUT | route to DG25 |
| B9 State-aware reranking | none in DG24 | zero | CUT | only after ranking loss is shown |
| B10 Reader answer | none in DG24 | zero | CUT | route to DG29 |

## 13.1 最重要的 anti-confounds

所有 product trace 必须冻结：

~~~text
snapshot
query and case order
CapabilitySet
policy
feature flags
repository/index
candidate caps
channel invocation logic
fusion
dedup
Gate
Binding
RequirementState
Sufficiency
operator
~~~

所有 official probes 必须：

~~~text
发生在 product seal 之后
不再触发 product rerun
不修改 index, cache contract, ledger or canonical state
使用官方服务
~~~

所有 scoring 必须：

~~~text
发生在 product/probe seal 之后
只读 sealed artifacts
不执行 Runtime
~~~

---

# 14. Metrics

## 14.1 Evidence equivalence-group retention

\[
GoldRetention(s)=
\frac{
\#\text{acceptable evidence groups alive after stage }s
}{
\#\text{required acceptable evidence groups}
}
\]

同时报告：

~~~text
RawGoldRetention
PolicyConditionedGoldRetention
AuthorizedAbsenceCount
~~~

## 14.2 Evidence-role coverage

\[
RoleCoverage(s)=
\frac{
\#\text{required evidence roles covered after stage }s
}{
\#\text{required evidence roles}
}
\]

同一 role 有多个 equivalence groups 时，按 annotation contract 计算 OR/AND，不得由 scorer 临时决定。

## 14.3 Proof-obligation disposition

分母独立：

~~~text
ProofSatisfiedRate
ProofActionUnavailableRate
ProofActionNotSelectedRate
ProofExecutionFailureRate
ProofValidationFailureRate
ProofUnresolvedRate
~~~

不得合并进 CandidateRecall。

## 14.4 Discovery 与 channel

~~~text
ChannelAvailabilityRecall@8
ChannelAvailabilityRecall@16
ChannelAvailabilityRecall@32
ChannelAvailabilityRecall@64
UnionOracleRecall@M
ChannelUniqueGoldContribution
ProductDiscoveryRecall
RouterOpportunityLoss
ChannelEligibleNotInvokedRate
NoChannelRetrievedRate
~~~

M 表示 S0 预注册且经过 official capability 验证的 M_audit。UnionOracleRecall 只说明 official probe availability，不是 product recall improvement。超过 M_audit 的 cutoff 不进入同一分母，也不按 miss 计数。

## 14.5 Lifecycle

~~~text
ChannelLocalCutoffLossRate
HardFilterGoldDropRate
GlobalCutoffLossRate
FixedPrioritySuppressionRate
DedupWrongRepresentativeRate
TransientDropRate
RediscoveryRate
HydrationFailureRate
InterpretationLossRate
BindingValidationLossRate
~~~

## 14.6 Rule attribution

~~~text
RuleActivationRate
OpenedDevRuleExposureRate
GoldOccurrenceRulePathAssociationRate
ExclusiveObservedGoldPathRate
GeneratedFeatureNonGoldRate
RegexMisclassificationAssociationRate
~~~

禁止生成：

~~~text
CorrectAnswerRuleCausalEffect
RuleRemovalGain
RuleTreatmentF1
~~~

## 14.7 First-loss distribution

至少按以下层级报告：

~~~text
equivalence-group micro
evidence-role micro
requirement macro
query macro
operator family
channel
authorized vs unauthorized availability
proof obligation type
~~~

QueryMacroFirstLoss 不得通过多数 candidate 遮盖一个缺失的 required operand。

## 14.8 行为与成本

~~~text
ProductBehaviorDigestMismatchCount
ProductRepositoryCallDelta
ProductCandidateOrderMismatchCount
ProductBindingMismatchCount
ProductRequirementStateMismatchCount
ProductSufficiencyMismatchCount
ProductOperatorReadinessMismatchCount

AuditProbeCalls
AuditCandidatesReturned
AuditLatency
AuditEmbeddingCalls where applicable
TraceSerializationLatency
TraceArtifactBytes
~~~

diagnostic probe cost 与 product cost 分开，不能把 probe 计入当前产品效率，也不能隐藏。

---

# 15. Hard Gates

## 15.1 不可降低的安全门

~~~text
Wrong COMPLETE                                  = 0/N
Wrong scope                                     = 0/N
Authority violation                             = 0/N
Permission/retention/revoke violation           = 0/N
Time-axis substitution                          = 0/N
Canonical mutation                              = 0/N
Runtime case-ID/gold routing                    = 0/N
Automatic retry                                 = 0/N
Reader calls                                    = 0/N
Generative Provider/controller calls            = 0/N
Formal holdout consumption                      = false
Candidate default                               = false
~~~

## 15.2 Behavior-neutrality 门

trace OFF/ON：

~~~text
request semantic digest mismatch                = 0/N
repository call-set/order mismatch              = 0/N
channel invocation mismatch                     = 0/N
candidate set/order mismatch                    = 0/N
dedup winner mismatch                           = 0/N
Gate mismatch                                   = 0/N
EvidenceSet mismatch                            = 0/N
Interpretation/Binding mismatch                 = 0/N
RequirementState mismatch                       = 0/N
Sufficiency/operator mismatch                   = 0/N
~~~

latency 只做 characterization，不允许 trace 改变 timeout/fallback disposition。

## 15.3 Attribution completeness 门

~~~text
opened-dev product traces                       = 10/10
observed occurrences with lifecycle             = 100%
dedup decisions with recoverable lineage        = 100%
stage IDs bound to source symbol/digest          = 100%
required evidence roles mapped                  = 100%
acceptable equivalence groups dispositioned     = 100%
proof obligations dispositioned                 = 100%
first irrecoverable loss resolved                = 100%
free-text-only primary reasons                  = 0
authorized absence separately reported           = 100%
~~~

## 15.4 Product/probe/scorer boundary 门

~~~text
gold/proof registries sealed before product      = 100%
registry identity drift after product start      = 0
product/probe process label access                = 0
gold fields in product/probe artifacts           = 0
gold fields in InputOnlyCaseManifest              = 0
Runtime imports scorer/gold registry             = 0
probe results entering product Binding           = 0
product reruns after probe start                 = 0
eval-owned retrieval implementation              = 0
seen-region mutation by probe                     = 0
watermark/index mutation by probe                 = 0
scorer registry reopen before both seals          = 0
~~~

## 15.5 Official probe fidelity 门

~~~text
official executor identity present               = 100%
official repository identity present             = 100%
index/snapshot/scope identity present             = 100%
one widest call per requirement/channel          = 100%
offline cut views derived from same result        = 100%
unavailable vs not-invoked separated              = 100%
~~~

## 15.6 Rule audit 门

~~~text
known synonym/regex/hard-filter/priority rules inventoried  = 100%
rule source symbol and digest present                         = 100%
affected occurrence lineage present                          = 100%
leave-one-rule-out executions                                 = 0
correct_answer_dependency                                     = NOT_MEASURED_DG24
causal_effect                                                  = NOT_ESTIMATED
~~~

## 15.7 Quality 门

~~~text
targeted DG24 tests                           PASS
DG20–DG23 behavioral regression              PASS
contract tests                               PASS
strict mypy                                  PASS
Ruff                                         PASS
real PostgreSQL integration/security         PASS
temporary PostgreSQL cleanup                 PASS
architecture validate/lock                   PASS
artifact privacy/secret scan                 PASS
source/artifact manifest verification        PASS
~~~

## 15.8 PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED

主 PASS 必须同时满足：

1. 当前 10 个 diagnosis/dev cases 全部可重放；
2. tracing 前后 request、candidate order、Binding、RequirementState、Sufficiency 与 operator 完全一致；
3. 所有 observed occurrences 有 lifecycle disposition；
4. 所有 acceptable evidence equivalence groups 有 first-loss attribution；
5. 所有 proof obligations 有独立 disposition；
6. gold/proof registry 在 product 前预封存，且 product、official probe、scorer 三平面物理分离；
7. official probes 复用正式 AcquisitionService / repository / index；
8. stage IDs 绑定实际 source symbol 和 implementation digest；
9. dedup 后所有 channel lineage 可恢复；
10. AUTHORIZED_ABSENCE 与 retrieval bug 分开；
11. Reader、生成式 Provider、canonical mutation、retry 全部为 0；
12. formal holdout 未触碰，Candidate 默认关闭；
13. 没有 leave-one-rule-out、algorithm treatment 或 answer rerun；
14. quality/PostgreSQL/security/architecture/manifest 全部通过。

---

# 16. Test Plan

## 16.1 Unit tests

至少覆盖：

~~~text
canonical trace serialization
semantic digest excludes latency/timestamp
stage registry source binding
occurrence identity uniqueness
same Evidence multi-channel lineage
dedup winner/loser preservation
candidate kept/dropped/rejected transition
drop then rediscovery
first vs first-irrecoverable loss
eligible-not-invoked
unavailable channel
authorized absence
proof obligation state machine
reason-code enum rejects free-text primary reason
gold fields rejected from product trace schema
~~~

## 16.2 Property tests

~~~text
reordering trace serialization does not change canonical digest
adding latency does not change behavior digest
one Evidence discovered by N channels preserves N lineages after dedup
rediscovery prevents earlier drop from becoming irrecoverable
removing non-gold trace metadata does not change first-loss result
scorer is deterministic under input-order permutation
each supported offline @K view is a prefix of the one sealed wide probe
cutoffs above verified M_audit are typed unavailable, not counted as misses
~~~

## 16.3 Contract tests

~~~text
Runtime cannot import scorer-only package
product/probe runner accepts only InputOnlyCaseManifestV01
product process cannot open gold registry
probe process cannot open gold registry
scorer cannot invoke retrieval entrypoint
gold/proof registry identity cannot change after first product request
official probe identifies official executor/repository
probe cannot mutate context/canonical/seen ledger/watermark
trace ON and OFF execute identical repository calls
public MCP request/response schema unchanged
PostgreSQL schema unchanged
~~~

## 16.4 Synthetic lifecycle tests

为每个 first-loss reason family 建立最小 fixture：

~~~text
discovery
invocation
prefilter
rank/cutoff
dedup
governance
hydration
span
interpretation
binding
proof
~~~

synthetic labels 只属于 scorer fixture，Runtime 仍只看无标签 Evidence。

## 16.5 Opened-dev evaluation tests

~~~text
10/10 case order exact
all product runs before all probes
gold/proof registry pre-sealed before all product runs
all probes before scorer registry reopen
one product run per request identity
zero Reader
zero retry
all denominators present
all reports independently reproducible
~~~

## 16.6 Real PostgreSQL integration/security

至少验证：

~~~text
audit role read-only
cross-tenant probe denied
wrong scope probe denied or filtered
revoked Evidence remains inaccessible
unreadable retention fails closed
snapshot identity stable
official FTS/dense/temporal repository path
no canonical tables mutated
no outbox/watermark advancement
temporary database cleanup
~~~

## 16.7 Failure injection

~~~text
repository timeout
projection unavailable
index identity drift
snapshot mismatch
hydration not found
trace write failure
seal mismatch
product/probe opened registry content
scorer reopened registry before both execution seals
scorer tries Runtime import
probe attempts mutation
dedup lineage missing
stage source digest mismatch
~~~

全部必须 typed、fail-closed、zero automatic retry。

---

# 17. Failure Discipline

## 17.1 Append-only

- 每次执行使用新 run ID；
- 失败 receipt、trace、partial artifact 与 ledger append-only 保留；
- 不覆盖 DG20–DG23 artifacts；
- 不删除失败以制造 clean manifest；
- 不用 retry 结果替换第一次结果；
- 产品、probe、scorer 各有独立 run namespace；
- terminal 只汇总已封存制品。

## 17.2 立即停止条件

~~~text
architecture lock mismatch
public MCP schema drift
PostgreSQL migration required
formal holdout accessed
Runtime case-ID/gold branch
product/probe opens registry content
scorer reopens registry before product/probe seals
trace changes product behavior
probe uses eval-owned retrieval
probe mutates product state
Reader or generative Provider called
canonical mutation
Wrong COMPLETE > 0
scope/authority/permission violation > 0
candidate lineage irrecoverable
~~~

## 17.3 Diagnosis budget

每个 blocking condition 最多：

~~~text
one reproducible diagnosis
one narrow instrumentation repair
one fresh rerun with new run ID
~~~

不能通过改变 retrieval rule、Top-k、channel、seed 或 label mapping 修复审计失败。

## 17.4 Failures 不得被 aggregate 覆盖

~~~text
tests PASS
~~~

不能覆盖：

~~~text
behavior changed
label boundary violation
gold mapping incomplete
product/probe divergence
candidate lineage unresolved
~~~

---

# 18. Terminal Dispositions

## 18.1 PASS

~~~text
DG24 = PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED
~~~

仅当 §15.8 全部满足。

允许表述：

> 在冻结的 10 个 deidentified opened-development cases、当前 Runtime、official acquisition channels、policy、scope 与 snapshot 上，DG-24 在不改变产品行为的条件下，完成了 requirement/evidence-role/equivalence-group 与 proof-obligation 层级的候选生命周期追踪和 first-irrecoverable-loss 定位，并量化了当前 channel availability、router opportunity loss 与规则路径关联。

## 18.2 PARKED

### Candidate lineage 无法恢复

~~~text
PARKED_UNRESOLVED_CANDIDATE_LINEAGE
~~~

适用：

~~~text
dedup 后无法恢复 channel 来源
候选身份无法从 projection 映射到 Evidence/span
实际 drop stage 无法确定
~~~

### Gold mapping 不完整

~~~text
PARKED_GOLD_MAPPING_INCOMPLETE
~~~

适用：

~~~text
gold evidence 无法映射 requirement role
acceptable equivalence group 不可合法定义
proof obligation annotation 不完整
~~~

### Eval 与产品路径分叉

~~~text
PARKED_EVAL_PRODUCT_PATH_DIVERGENCE
~~~

适用：

~~~text
probe 使用自建 BM25/fusion/filter
probe 未调用 official repository/index
scorer 重新执行 retrieval
~~~

### Behavior 被 tracing 改变

~~~text
PARKED_BEHAVIOR_CHANGED
~~~

适用：trace ON/OFF 任一 product semantic digest 或 repository call set 不一致。

### Label/Product boundary 违规

~~~text
PARKED_LABEL_PRODUCT_BOUNDARY_VIOLATION
~~~

适用：

~~~text
product/probe seal 前读取 gold
Runtime import scorer registry
gold fields 进入 product trace/request
~~~

## 18.3 FAIL_SAFETY_OR_INTEGRITY

出现以下任一情况：

~~~text
canonical mutation
scope/permission/tenant violation
Wrong COMPLETE
formal holdout access
architecture/schema unauthorized change
artifact identity fraud
~~~

终态：

~~~text
DG24 = FAIL_SAFETY_OR_INTEGRITY
~~~

## 18.4 Claim boundary

DG-24 禁止表述：

~~~text
retrieval recall improved
MiLA retrieval accuracy is solved
synonym rules causally help or hurt
hard filters should be removed
multi-channel union is superior
StateView reranking works
vLLM understands RequirementState
temporal COUNT is solved
Reader regression is solved
formal LongMemEval improved
Production ready
Schema ready
architecture freeze update ready
~~~

---

# 19. Deliverables

最低交付清单：

1. S0 baseline/source/stage freeze receipt；
2. transitive source manifest；
3. StageImplementationRegistryV01；
4. trace schema bundle；
5. reason-code registry；
6. synthetic lifecycle matrix；
7. trace OFF/ON behavior-equivalence report；
8. sealed ProductRetrievalTraceV01 collection；
9. CandidateLifecycleTraceV01 collection；
10. channel invocation report；
11. dedup lineage report；
12. product-phase seal；
13. sealed OfficialAuditProbeTraceV01 collection；
14. channel availability curves；
15. probe-phase seal；
16. GoldEquivalenceRegistryV01；
17. ProofObligationRegistryV01；
18. registry seal/reopen boundary receipt；
19. RequirementLossAttributionV01 collection；
20. ProofObligationTraceV01 collection；
21. StageRetentionReportV01；
22. FirstLossDistributionV01；
23. RuleFeatureAttributionReportV01；
24. ChannelAvailabilityReportV01；
25. AuthorizedAbsenceReportV01；
26. SuccessorRoutingReportV01；
27. quality receipt；
28. real PostgreSQL integration/security receipt；
29. append-only failure index；
30. source/artifact manifest；
31. runbook：docs/runbooks/dg24-retrieval-first-loss-audit.md；
32. S8 terminal receipt。
33. InputOnlyCaseManifestV01 与 forbidden-field validation receipt。

建议目录：

~~~text
runtime/src/milai/observability/retrieval_audit.py
runtime/src/milai/application/retrieval_audit_probe.py
runtime/src/milai/domain/retrieval_audit.py

evals/dg24/
  gold_registry.py
  proof_registry.py
  scorer.py
  contracts.py

scripts/run_dg24_s0_freeze.py
scripts/run_dg24_s1_contracts.py
scripts/run_dg24_s2_behavior_equivalence.py
scripts/run_dg24_s3_product_trace.py
scripts/run_dg24_s4_official_probes.py
scripts/run_dg24_s5_registry.py
scripts/run_dg24_s6_scoring.py
scripts/run_dg24_s7_quality.py
scripts/build_dg24_s8_terminal.py

tests/test_dg24_*.py
var/dg24/s0 ... var/dg24/s8
docs/runbooks/dg24-retrieval-first-loss-audit.md
~~~

evals/dg24 只允许拥有：

~~~text
fixture orchestration
gold/proof mapping
post-seal scoring
reporting
~~~

不得拥有：

~~~text
ranking
fusion
neighbor expansion
temporal filtering
candidate packing
Binding
Sufficiency
~~~

---

# 20. Rollback 与兼容

## 20.1 Feature boundary

内部 audit feature 默认关闭：

~~~text
retrieval_first_loss_audit_v0_1 = false
~~~

关闭后恢复当前 DG-23 product behavior，不删除 DG-24 traces 或 failure receipts。

## 20.2 Schema

~~~text
public MCP migration          none
PostgreSQL migration          none
architecture/v1.0 mutation   none
~~~

内部 trace contract 写入 audit artifact，不成为公共产品 schema。

若证明必须改变数据库/public schema：

~~~text
NOT_ENTERED_SCHEMA_AUTH_REQUIRED
~~~

并停止本 Goal。

## 20.3 Rollback trigger

任一情况立即关闭 audit feature：

~~~text
candidate order drift
Binding/RequirementState/Sufficiency drift
repository call drift
latency 引发 timeout/fallback drift
audit content privacy leak
gold boundary violation
canonical or index mutation
quality/security regression
~~~

---

# 21. 执行检查表

进入 S0 前：

- [ ] Owner 明确授权执行 DG-24；
- [ ] DG-20～DG-23 artifacts 保持只读；
- [ ] 当前用户工作树修改已记录并保留；
- [ ] formal holdout 未使用；
- [ ] Candidate 默认关闭；
- [ ] Reader 与生成式 Provider credentials 不进入运行环境。
- [ ] scorer steward 与 product/probe runner 的权限和 artifact namespace 已分离。

进入 S2 前：

- [ ] StageImplementationRegistry 绑定实际 source symbol/digest；
- [ ] identity/dedup/lifecycle contracts 完整；
- [ ] synthetic drop/rediscovery/proof tests 通过；
- [ ] product trace schema 不允许 gold fields。

进入 S3 前：

- [ ] trace OFF/ON behavior-equivalence 全通过；
- [ ] no eval-owned business logic；
- [ ] no algorithm treatment；
- [ ] no schema/migration；
- [ ] gold/proof registries 已预封存；
- [ ] InputOnlyCaseManifestV01 已封存且 forbidden gold fields = 0；
- [ ] product runner 只能读取 opaque registry seal digest；
- [ ] product/probe label access guard 已启用。

进入 S4 前：

- [ ] 10/10 product runs 完成；
- [ ] product seal 验证；
- [ ] product process 已结束；
- [ ] 之后不再重跑 product；
- [ ] official probe 只读与 no-mutation tests 通过。

进入 S5 前：

- [ ] all official probes dispositioned；
- [ ] probe seal 验证；
- [ ] probe process 已结束；
- [ ] Runtime/probe artifacts 无 gold fields。

进入 S6 前：

- [ ] gold registry 只在 scorer package；
- [ ] reopened registry identity 与 S0 pre-run seal 一致；
- [ ] requirement/evidence-role mapping complete；
- [ ] proof-obligation registry complete；
- [ ] authorized absence policy frozen；
- [ ] scorer registry-reopen receipt 时间晚于两个 execution seal。

进入 S8 前：

- [ ] all equivalence groups dispositioned；
- [ ] all proof obligations dispositioned；
- [ ] first-loss distributions 可独立复算；
- [ ] rule report 无 causal claim；
- [ ] successor routing 由 observed first loss 决定；
- [ ] quality/PostgreSQL/security complete；
- [ ] temporary databases removed；
- [ ] architecture manifest verified。

终态前：

- [ ] Reader calls = 0；
- [ ] generative Provider/controller calls = 0；
- [ ] automatic retry = 0；
- [ ] canonical mutation = 0；
- [ ] formal holdout untouched；
- [ ] Candidate default false；
- [ ] product/probe/scorer seals match；
- [ ] source/artifact manifests match；
- [ ] terminal disposition 与失败事实一致；
- [ ] claim boundary 未扩大。

---

# 22. 最终原则

DG-24 的核心不是再提出一种检索算法，而是先建立证据生命周期的可观测事实：

~~~text
Requirement emitted
→ channel available?
→ channel invoked?
→ evidence discovered?
→ filter kept it?
→ cutoff retained it?
→ dedup preserved the right representative?
→ Governance admitted it?
→ span/interpretation grounded it?
→ Binding accepted it?
→ proof obligation closed?
→ Sufficiency became valid?
~~~

最关键的实验规则：

> Product trace、official channel probe 和 gold scorer 必须依次封存、物理隔离；审计不能先看答案再决定追踪什么。

最关键的归因规则：

> candidate 曾被删除但随后重新发现时，记录 transient drop；只有后续再未合法恢复的 stage 才是 first irrecoverable loss。

最关键的工程规则：

> 当前的 synonym、regex、hard filter 和 fixed priority 在 DG-24 中只被观察和归因，不被删除、替换或调参。

最关键的开发路由：

> 先确定正确证据是没有被发现、没有被调用、被规则误删、被 cutoff 挤掉、未被语义绑定，还是缺少完备性证明；然后只为占主导的 first-loss 类别创建 successor treatment。
