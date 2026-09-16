---
document_id: MILA-MF01
version: "0.2"
status: DESIGN_ACTIVE_S0_S1
execution_order_authority: MILA-ML-MASTER
architecture_baseline: MILA-ML-ARCH@1.0
---

# MiLAi MF-01：Formation First-Loss Audit Goal

> Goal ID：MF-01
> 文档版本：0.2 / ACTIVE LOCAL GOAL
> 日期：2026-08-30（Asia/Shanghai）
> Program：[MF-01～MF-06 Master](./MiLAi_MF-01-MF-06_Memory_Formation_and_Representation_MASTER.md)
> 类型：观察性 Goal
> 当前状态：DESIGN_ACTIVE_S0_S1 / S2_EFFECT_REQUIRES_LOCAL_LABEL_AND_SNAPSHOT_GATE
> Product behavior：不得改变
> Formal holdout：不使用

---

# 1. 问题

当前 MiLA 已实现可靠 Evidence、Canonical evolution 和 query-time retrieval，但尚不知道简单记忆在写入与形成阶段首先丢在哪里。

MF-01 只回答：

> 对一个未来需要被读取的语义义务，它在 Raw Evidence、episode、mention、identity、event time、state/change、proposal、canonical disposition 或 projection 中首次缺失或错误的位置是什么？

MF-01 不实现新 extractor，不提高 QA，不修改检索算法。

---

# 2. Research Hypotheses

| Hypothesis | 最小可信证据 |
| --- | --- |
| MF01-H1 当前 Formation first loss 可定位 | 每个已标注适用义务都有唯一 first-loss stage、reason code 或 TERMINAL_SURVIVAL |
| MF01-H2 审计不改变产品行为 | 同一输入下 Evidence、Proposal、Canonical state、projection 和 query output 与审计前一致 |

不声称：

~~~text
Formation 已改善
新 representation 有效
Canonical promotion 正确率提高
retrieval 或 Reader 得分提高
~~~

---

# 3. 审计单位

不追踪所有候选，只追踪 sealed label 中的语义义务：

~~~text
case
└─ raw evidence span
   ├─ episode obligation
   ├─ entity mention / identity obligation
   ├─ event mention / identity obligation
   ├─ occurrence-time obligation
   ├─ state assertion obligation
   ├─ state transition obligation
   └─ expected canonical disposition
~~~

每个 case 只标注实际适用的义务，避免为简单事实强制创建 episode、event 或 transition 对象。

---

# 4. 当前实际 Stage

~~~text
F00 RAW_EVIDENCE_CAPTURED
F10 EPISODE_FORMED
F20 MENTION_FORMED
F30 IDENTITY_RESOLVED
F40 EVENT_TIME_GROUNDED
F50 STATE_OR_CHANGE_FORMED
F60 PROPOSAL_EMITTED
F70 CANONICAL_DISPOSITION
F80 RETRIEVAL_PROJECTION_BUILT
~~~

每个 stage 只能返回：

~~~text
SURVIVED
FIRST_LOSS
NOT_APPLICABLE
NOT_IMPLEMENTED
AUTHORIZED_REJECTION
~~~

当前源码不存在的能力记录 NOT_IMPLEMENTED。评估脚本不得为获得完整 trace 而模拟 episode、identity、event time 或 proposal。

---

# 5. Label 合同

小型 Formation validation 直接绑定 Raw Evidence：

~~~yaml
case_id:
evidence_id:
span_start:
span_end:
obligation_id:
obligation_kind:
expected:
acceptable_alternatives: []
expected_canonical_disposition:
annotation_status:
~~~

obligation_kind：

~~~text
EPISODE_BOUNDARY
ENTITY_MENTION
ENTITY_IDENTITY
EVENT_MENTION
EVENT_IDENTITY
EVENT_OCCURRENCE_TIME
STATE_ASSERTION
STATE_TRANSITION
CANONICAL_DISPOSITION
RETRIEVAL_PROJECTION
~~~

使用当前 10 个 diagnosis/dev cases，并补充覆盖缺失类型的最小本地 fixture。所有 label 在运行 first-loss scorer 前冻结；不使用 formal holdout。

---

# 6. First-loss reason codes

## Episode

~~~text
EPISODE_BOUNDARY_MISSED
EPISODE_OVERMERGED
EPISODE_UNDERSEGMENTED
~~~

## Identity / Event

~~~text
ENTITY_MENTION_MISSED
ENTITY_OVERMERGED
ENTITY_OVERSPLIT
ALIAS_UNRESOLVED
EVENT_MENTION_MISSED
EVENT_IDENTITY_DUPLICATED
DISTINCT_EVENTS_COLLAPSED
~~~

## Temporal

~~~text
SOURCE_TIME_USED_AS_EVENT_TIME
RELATIVE_TIME_UNRESOLVED
TIMEZONE_UNRESOLVED
DURATION_FRAGMENTED
~~~

## State / Change

~~~text
STATE_ASSERTION_NOT_FORMED
EVENT_MISCLASSIFIED_AS_STATE
STATE_MISCLASSIFIED_AS_EVENT
UPDATE_RELATION_MISCLASSIFIED
TEMPORARY_CONSTRAINT_TREATED_AS_REPLACEMENT
CORRECTION_NOT_LINKED
REVOCATION_NOT_LINKED
~~~

## Proposal / Projection

~~~text
PROPOSAL_NOT_EMITTED
FALSE_PROPOSAL_EMITTED
VALID_PROPOSAL_REJECTED
PROJECTION_NOT_BUILT
PROJECTION_STALE
PROVENANCE_LINK_MISSING
~~~

合法的权限拒绝、治理拒绝或不需要 Canonical promotion 使用 AUTHORIZED_REJECTION / NOT_APPLICABLE，不计作 Formation bug。

---

# 7. 最小 Trace

每个义务只写一行终态，不复制完整候选生命周期：

~~~yaml
case_id:
obligation_id:
obligation_kind:
source_span_id:
last_surviving_stage:
first_loss_stage:
reason_code:
observed_object_ids: []
source_lineage_ok:
stage_availability:
~~~

若义务到 F80 仍正确：

~~~text
first_loss_stage = null
reason_code = TERMINAL_SURVIVAL
~~~

这避免重演 DG-24 的大规模逐候选审计成本。

---

# 8. 执行阶段

## S0 — Actual-path freeze

- 枚举当前源码真实存在的 Formation stage、writer 和 projection。
- 冻结 Evidence snapshot、代码身份、配置与当前产品输出。
- 记录缺失 stage 为 NOT_IMPLEMENTED。
- 写 var/mf01/run-lock.json。

## S1 — Label seal

- 完成 raw span、episode、identity、event time、state/transition 和 disposition 标签。
- 每个 label 保存可接受 alternative。
- 计算每类义务的 label count、scope coverage 与可判定率；不足以支撑对应 first-loss 时，在 effect 前 terminal 为 `PARKED_INSUFFICIENT_LIFECYCLE_LABELS`。
- 冻结 Evidence snapshot identity、label digest 与允许的分析单位。
- scorer 开始后不改 label。

## S2 — Passive trace

- Entry：S1 label adequacy 通过；Evidence snapshot 与产品行为基线已封存；trace hook 的 behavior-equivalence smoke 通过。
- S2 不依赖 DG-27 或 DG-28 disposition；与 Program C 使用独立冻结 snapshot 和独立 attribution。
- 在实际 Formation 路径增加只读 trace hook，或离线读取现有对象。
- 不改变排序、proposal、Steward、Canonical 或 projection 行为。
- 审计 runner 不引入新的 Provider/embedding call。

## S3 — First-loss score

- 为每个适用义务计算唯一 first loss。
- 输出 stage retention 和 reason distribution。
- 将主要首损点路由到 MF-02、MF-03 或 MF-04。

## S4 — Terminal

- 运行 targeted trace tests 与直接行为等价回归。
- 写 results.json 与 terminal.json。
- 不因发现错误而在 MF-01 内实现 treatment。

---

# 9. 指标

~~~text
ObligationAttributionCoverage
StageAvailabilityCoverage
EpisodeBoundaryRetention
IdentityRetention
EventIdentityRetention
OccurrenceTimeRetention
StateAssertionRetention
TransitionRetention
ProposalRetention
ProjectionRetention
ProvenanceClosureRate
BehaviorEquivalence
IntroducedProviderCalls
CanonicalMutationsCausedByAudit
~~~

主要结果是 first-loss distribution，不是最终 QA F1。

---

# 10. PASS 与路由

PASS：

~~~text
所有适用 label 都有 first loss 或 TERMINAL_SURVIVAL
所有不存在的 stage 明确标记 NOT_IMPLEMENTED
source span 和 object lineage 可回放
BehaviorEquivalence = true
IntroducedProviderCalls = 0
CanonicalMutationsCausedByAudit = 0
formal_holdout_used = false
~~~

终态：

| 状态 | 含义 |
| --- | --- |
| PASS_FORMATION_FIRST_LOSS_LOCALIZED | 首损完成定位 |
| PARKED_INSUFFICIENT_LIFECYCLE_LABELS | 标签数量或类型不足以进入 passive effect |
| PARKED_LABEL_MAPPING_INCOMPLETE | label 无法映射实际 Evidence |
| PARKED_LINEAGE_UNRESOLVED | 对象不能回到 source span |
| FAIL_AUDIT_CHANGED_BEHAVIOR | trace 改变产品行为 |

Successor 路由：

| 主要首损 | 后继 |
| --- | --- |
| episode boundary | MF-02 |
| identity、event identity、event time | MF-03 |
| assertion、transition、proposal | MF-04 |
| projection only | Program C / projection treatment |
| 当前 Formation 已充分 | 进入 MF-06 eligibility review；有 state/change labels 时仍须 EV-01 disposition |

---

# 11. 轻量制品与测试

主要运行文件仅保留：

~~~text
var/mf01/run-lock.json
var/mf01/trace.jsonl
var/mf01/results.json
var/mf01/terminal.json
~~~

标签存于 eval fixture，不生成逐阶段 receipt、source manifest、deliverable index、独立 runbook 或 reviewer loop。

开发测试：

~~~text
trace serialization
reason-code coverage
first-loss scorer
behavior equivalence smoke
~~~

只有实际修改数据库、权限或冻结架构时才触发对应全量门；MF-01 设计上不应触发这些变化。

---

# 12. 立即执行

1. 读取当前 DeriveAndDiagnose、Episode、Proposal、Outbox 和 projection 实现，形成 stage availability map。
2. 冻结当前 10 cases 的 raw Evidence span labels。
3. 对缺少的 Formation 类型增加最小本地 fixture。
4. 实现 passive trace 与 first-loss scorer。
5. 封存结果后选择 MF-02、MF-03 或 MF-04；MF-01 内不修 extractor。
