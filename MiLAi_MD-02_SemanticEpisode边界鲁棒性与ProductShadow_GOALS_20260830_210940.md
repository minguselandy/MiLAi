---
document_id: MILA-MD02
version: "0.1"
status: DESIGN_COMPLETE_EXECUTION_NOT_AUTHORIZED
execution_order_authority: MILA-ML-MASTER@1.5
architecture_baseline: MILA-ML-ARCH@1.0
execution_authority: NONE
predecessor_terminal: var/mf02/mf02-semantic-episode-four-arm-20260830-001/terminal.json
---

# MiLAi MD-02：Semantic Episode 边界鲁棒性与 Product Shadow Goal

> 日期：2026-08-30（Asia/Shanghai）  
> Program：Memory Formation / Recollection Integration  
> 性质：DESIGN-ONLY Goal  
> Formal holdout：不使用  
> Experimental feature flags：默认 `OFF`

> **权限边界**：本文只完成 Goal 与实验合同设计，不授权创建标签、修改代码、运行 effect、接入产品、访问数据库、调用模型或使用 formal holdout。

## 1. 基线与问题

MF-02 已建立：

```text
PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION

Direct EpisodePairwiseF1       0.958333
delta vs best simple           0.291667
Simple Read AUC                0.734375
delta vs best simple           0.098958
DistractorTurnRate delta      -0.097222
```

因此不再重复证明 semantic episode 优于 turn/window/session，也不增加检索层。当前剩余问题是：

1. sealed validation 中仍有 3 个 over-merge/topic-shift error；
2. 当前 Formation 只在离线 sidecar/evaluation 路径运行；
3. 尚未证明它在 official read path 旁路执行时不会改变候选、Binding、Sufficiency、Operator 或 Context；
4. 尚未验证 bundle 遇到新 Evidence、撤销、权限变化或 retention 变化时能否拒绝 stale state 并回退 Raw path。

MD-02 的方法命题：

> **以 query-independent、可审计的 boundary evidence 降低 over-merge；同时让 Semantic Episode 仅作为 official read path 的 observation-only shadow 运行，证明其具备 freshness、撤销传播和行为等价性，而不获得产品决策权。**

## 2. Research Hypotheses

| Hypothesis | 预注册最小证据 |
| --- | --- |
| `MD02-H1` — 通用 boundary evidence 降低 over-merge | 新 sealed validation 上，`OverMergePairRate` 相对冻结 MF-02 builder 绝对下降 `≥0.05` 且 paired bootstrap lower bound `>0`；`OverSplitPairRate` 增量 `≤0.02`，EpisodePairwiseF1 与 SupportClosureAUC 非劣界均为 `-0.02` |
| `MD02-H2` — Product shadow 行为等价且 freshness-safe | official baseline behavior identity `=1.0`；stale/revoked/unreadable bundle rejection `=1.0`；Raw fallback `=1.0`；额外 acquisition/Reader/Provider/model calls、DB writes 和 Canonical mutations 全为 `0` |

Anti-claims：

```text
不声称产品 release-ready
不声称 formal-holdout 泛化
不声称解决全部 topic segmentation
不把 shadow observation 作为 Evidence、Binding、Claim 或 COMPLETE
不引入 Dense、reranker、planner、多轮 refinding 或更大候选预算
```

## 3. 目标结构

```text
Pre-query, query-independent shadow build
  authorized complete Formation snapshot
    → MemoryFormationBundleV01
    → noncanonical sidecar identity

Query-time official read
  official request
    ├─ Baseline official read path
    │    → Acquisition
    │    → Gate / Binding / Sufficiency / Operator / Context
    │    → authoritative baseline result
    │
    └─ Observation-only shadow consumer
         → validate the prebuilt bundle against current source state
         → map the same official Raw anchors to SemanticEpisode units
         → SemanticEpisodeShadowObservationV01
         → metrics/trace only
```

Query text、Raw FTS results 和 baseline candidate pool 均不得进入 Formation build；它们只允许在查询时映射到已经形成的 episode。

两条支路不得汇合。Shadow 结果不能进入：

```text
candidate pool
AcceptedBinding
RequirementState
Sufficiency
Operator
Reader context
Canonical state
```

## 4. Boundary Evidence V02

V02 不使用 query、case ID、gold、模型或最终答案。它只从当前 Raw snapshot 和现有 query-independent typed artifacts 构造：

```yaml
BoundaryEvidenceV02:
  previous_episode_source_ids: []
  current_source_id:

  continuation_signals:
    dialogue_pair_continuity:
    correction_or_update_relation:
    entity_continuity:
    event_or_state_continuity:
    lexical_cohesion:

  split_signals:
    session_change:
    explicit_topic_shift:
    subject_or_event_change:
    incompatible_predicate_context:
    time_gap_without_continuity:

  decision:
    CONTINUE
    SPLIT

  reason_code:
  producer_identity:
```

约束：

1. `SESSION_CHANGE` 继续是确定性 split。
2. assistant question-answer continuity 只是一个 signal，不能无条件吞并后续 user turn。
3. 单一共享词不能单独证明 continuation。
4. entity/event/state 信号只能来自 source-grounded、query-independent Formation artifacts。
5. Boundary decision 仍然 noncanonical、可重建，并保留完整 Raw spans。

当前 MF-02 的 3 个 sealed errors 只能定义失败类型，不得成为 V02 repair-dev 样本、规则词表或主效果分母。

## 5. Product Shadow 合同

### 5.1 `SemanticEpisodeShadowObservationV01`

```yaml
schema_version:
request_identity:
baseline_behavior_digest:

source_snapshot_digest:
source_watermark:
bundle_digest:
episode_digests: []
raw_anchor_digest:
shadow_context_evidence_ids: []

freshness_status:
  CURRENT
  STALE
  INELIGIBLE

disposition:
  OBSERVED
  STALE_REJECTED
  PERMISSION_REJECTED
  RAW_FALLBACK

canonical: false
canonical_mutation: false
```

可信 Runtime 写入 identity/digest；Formation policy 只产生 boundary/episode artifacts。

### 5.2 行为等价

`ProductBehaviorIdentity` 使用 canonical serialization 比较：

```text
official retrieval occurrences and order
governance-gated Evidence candidates
AcceptedBinding
RequirementState
Sufficiency
Operator result
Reader-bound Context plan
```

Shadow trace 不进入该 digest。`flag OFF` 与 `shadow ON` 的 baseline behavior digest 必须逐 request 相等。

### 5.3 Freshness 与 fallback

Shadow consumption 前必须重新核对：

```text
source snapshot digest
Evidence identities
permission snapshot
retention readability
revocation state
source watermark
```

任一变化：

```text
reject shadow bundle
record typed disposition
continue unchanged Raw baseline
never infer absence or COMPLETE from stale formed state
```

### 5.4 产品边界

```text
internal candidate flag only
default OFF
no public MCP field
no PostgreSQL migration
no background worker
no durable Episode replacement
no Context or Canonical mutation
```

## 6. 数据与分层

后续若获得显式执行授权，建立：

```text
boundary-repair-dev:
  8 new conversations
  labels visible for generalized repair

shadow-validation:
  at least 24 new conversations
  at least 96 turns
  at least 24 memory probes
  scorer-only labels

freshness-contract:
  unchanged snapshot
  appended Evidence
  revoked Evidence
  permission removed
  retention unreadable
  Formation failure / Raw fallback

formal holdout:
  untouched
```

Shadow validation 至少包括：

```text
12 over-merge-pressure conversations
  shared entity/term but different predicate, event or user goal

6 continuation-pressure conversations
  lexical disjointness but same entity/event/state

6 mixed conversations
  correction, assistant bridge, time gap and session boundary
```

MF-02 的 24-case sealed set只做历史 non-regression replay，不计入 MD-02 H1/H2 分母，也不允许据其错误回调 V02。

## 7. 核心实验 Block

### B1 — New-data and contract sanity（MUST）

- 封存 repair-dev、shadow-validation 和 freshness-contract identities。
- 验证 label determinability、Raw span closure 和 source-role metadata。
- 手算 `BoundaryEvidenceV02` 与 shadow freshness/fallback 场景。
- 不运行产品 effect。

### B2 — Boundary V01 versus V02（MUST）

- 在同一新 sealed validation 上比较冻结 MF-02 builder 与 V02。
- 主指标：conversation-macro `OverMergePairRate`。
- 非劣指标：OverSplitPairRate、EpisodePairwiseF1、SupportClosureAUC。
- V02 semantic 调整只允许使用 repair-dev；sealed labels 不回调。

### B3 — Official-path observation-only shadow（MUST）

- 同一 request 先封存 baseline result，再启用 internal shadow。
- 查询前必须由正式 `MemoryFormationBundleService` 对完整 Formation snapshot 构建 bundle；查询时复用 official Raw anchors，不允许 eval-owned 替代实现或从 query candidates 临时形成 memory。
- 比较 `ProductBehaviorIdentity`，执行 freshness-contract 六类场景。
- Shadow failure 不终止 baseline read，但必须产生 typed trace。

### B4 — Cost, failure and terminal（MUST）

- 报告 build time、per-turn CPU time、memory high-water mark 和 P50/P95 shadow overhead。
- 本 Goal 不预设产品 latency SLA；成本是后继 admission 输入，不用于事后选择 PASS 指标。
- 输出 over-merge、over-split、stale rejection、permission rejection 和 raw fallback 分布。
- 只按 H1/H2 与安全门形成 compact terminal。

## 8. 指标与硬门

### 8.1 Boundary

```text
OverMergePairRate
OverSplitPairRate
EpisodePairwisePrecision / Recall / F1
BoundaryPrecision / Recall / F1
SupportClosureAUC[1..8]
DistractorTurnRate
```

统计单位为 conversation/probe；paired bootstrap 固定在 conversation level。

### 8.2 Shadow equivalence

```text
BaselineBehaviorIdentityRate
ShadowBuildSuccessRate
ShadowDeterministicReplayRate
FreshBundleAcceptanceRate
StaleBundleRejectionRate
IneligibleBundleRejectionRate
RevokedEvidenceLeakRate
PermissionLeakRate
RawFallbackRate
AdditionalOfficialAcquisitionCalls
AdditionalReaderProviderModelCalls
CanonicalMutationCount
DatabaseWriteCount
```

### 8.3 必须保持

```text
RawSpanCoverage = 1.0
SourceOrderPreservation = 1.0
UserSemanticSourcePrecision = 1.0
ArtifactLineageClosure = 1.0
BaselineBehaviorIdentityRate = 1.0
ShadowBuildSuccessRate = 1.0 on eligible snapshots
ShadowDeterministicReplayRate = 1.0
FreshBundleAcceptanceRate = 1.0
StaleBundleRejectionRate = 1.0
IneligibleBundleRejectionRate = 1.0
RevokedEvidenceLeakRate = 0
PermissionLeakRate = 0
RawFallbackRate = 1.0 when shadow is unusable
AdditionalOfficialAcquisitionCalls = 0
AdditionalReaderProviderModelCalls = 0
CanonicalMutationCount = 0
DatabaseWriteCount = 0
formal holdout used = false
default feature flag = OFF
```

## 9. Terminal 决策

```text
MD02-H1 PASS and MD02-H2 PASS
→ PASS_MD02_BOUNDARY_ROBUST_PRODUCT_SHADOW

MD02-H1 MISS and MD02-H2 PASS
→ PASS_MD02_SHADOW_EQUIVALENT_BOUNDARY_UNRESOLVED
→ shadow contract 可保留，V02 不采用

MD02-H1 PASS and MD02-H2 MISS without authority leak
→ PARKED_MD02_SHADOW_INTEGRATION_NOT_EQUIVALENT

MD02-H1 MISS and MD02-H2 MISS without safety failure
→ PARKED_MD02_NO_GENERALIZED_PRODUCT_GAIN

Raw/scope/permission/revocation/Canonical boundary violated
→ FAIL_MD02_AUTHORITY_OR_EVIDENCE_BOUNDARY
```

一次 fail-closed protocol/implementation error 是 `REPAIR_ITERATION`。同一通用根因最多进行 3 次有证据修复；不得用 sealed case ID、答案、gold、Prompt、seed 或窗口 sweep 修复。

## 10. 建议执行顺序（未授权）

```text
S0 explicit execution authorization
→ S1 new labels + freshness contract seal
→ S2 Boundary V01/V02 matched effect
→ S3 official-path product shadow effect
→ S4 compact terminal and successor route
```

资源预算：

```text
GPU hours: 0
model / Provider / Reader calls: 0
new acquisition rounds: 0
main sealed effects: one boundary effect + one shadow effect
```

## 11. 预期交付

若后续获得执行授权，交付上限为：

```text
BoundaryEvidenceV02 typed contract and deterministic policy
SemanticEpisodeShadowObservationV01
one internal default-OFF shadow hook
targeted unit/contract/effect tests
var/md02/<run-id>/
  run-lock.json
  results.json
  terminal.json
  repair-log.jsonl       # only when repairs occur
```

不生成 Migration、public schema、逐阶段 receipt、transitive manifest、重复 runbook 或多轮 reviewer。

## 12. 后续路由

只有 `PASS_MD02_BOUNDARY_ROBUST_PRODUCT_SHADOW` 才可以另行评估：

```text
incremental/background Formation topology
larger identity/time/state-change validation
expanded MF-06 Formed+Simple comparison
product latency/admission budget
```

即使 PASS，也不自动授权 formal holdout、默认产品启用、durable schema、Reader 接入、Canonical promotion 或 adaptive retrieval。
