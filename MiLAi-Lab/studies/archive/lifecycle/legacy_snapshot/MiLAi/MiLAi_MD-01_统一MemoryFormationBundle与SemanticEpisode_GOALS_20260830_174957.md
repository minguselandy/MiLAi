---
document_id: MILA-MD01
version: "0.1"
status: DESIGN_COMPLETE_EXECUTION_NOT_AUTHORIZED
execution_order_authority: MILA-ML-MASTER@1.3
architecture_baseline: MILA-ML-ARCH@1.0
execution_authority: NONE
---

# MiLAi MD-01：统一 Memory Formation Bundle 与 Semantic Episode Goal

> 日期：2026-08-30（Asia/Shanghai）  
> 主线：Memory Formation / Memory Evolution  
> 性质：DESIGN-ONLY Goal；拟议 sidecar implementation 不修改 PostgreSQL/public MCP/frozen architecture  
> Formal holdout：不使用  
> Experimental feature flags：OFF

> **范围声明**：本文仅完成 Goal 与实验路线设计，不授权创建 fixture、修改代码、调用模型、执行 effect、修改数据库或使用 holdout。

## 1. 问题与方法命题

MF-03 和 MF-04 已经分别形成 identity/event/time 与 state/change，但它们仍是彼此分离的 sidecar；当前没有一个 query-independent Memory object 同时表达：

```text
Raw Evidence coverage
semantic episode context
entity / event / occurrence time
state assertion / transition
freshness / watermark
raw fallback and canonical authority boundary
```

MD-01 拟实现：

> **Raw-preserving MemoryFormationBundleV01：以 SemanticEpisode 作为上下文组织单元，复用已验证的 MF-03/MF-04 typed artifacts，并始终将 Raw Evidence 作为可回放底座。**

## 2. Research Hypotheses

| Hypothesis | 最小可信证据 |
| --- | --- |
| MD01-H1 统一 bundle 能正确表达完整 Memory Formation snapshot | Raw span coverage=1.0，source-role leakage=0，sub-artifact lineage=1.0，deterministic replay=1.0，canonical mutations=0 |
| MD01-H2 简单 episode formation 能在真实对照上组织上下文 | 预注册 multi-turn validation 上 BoundaryPrecision/Recall 均≥0.90，episode pairwise F1≥0.90，不使用 case-ID/gold-aware rule |

Anti-claim：不把收益归因于更多 retrieval channel、query-time model、更大 Top-k 或 Canonical 自动写入。

## 3. 对象与边界

### `SemanticEpisodeCandidateV01`

```yaml
episode_digest:
source_spans: []              # 按原始对话顺序，精确回到 Evidence
participant_roles: []
topic_terms: []               # 只是可重建 feature
boundary_reason:
source_time_start:
source_time_end:
producer_identity:
canonical: false
```

### `MemoryFormationBundleV01`

```yaml
bundle_digest:
source_snapshot_digest:
source_evidence_ids: []
source_watermark:
coverage_status: COMPLETE
episode_candidates: []
semantic_sidecar:             # MF-03 entity/event/time
state_change_sidecar:         # MF-04 state/change
raw_fallback_required: true
canonical: false
canonical_mutation: false
```

硬边界：

1. assistant turn 可参与 episode context，但不得被形成为用户个人 state/event。
2. Episode 只是 noncanonical context projection，不等于现有 durable `Episode` aggregate。
3. Bundle 不能直接提升 Claim；仍需 EV-01 和唯一 Proposal/Steward 路径。
4. 任一 formed artifact 失效时必须可从 Raw Evidence 重建。

## 4. 计划开发 Block（未授权执行）

### B1 — Contrasting episode validation（MUST）

- 固定 8–12 个 non-holdout conversations。
- 覆盖 same-topic continuation、explicit topic shift、session change、time gap、pronoun continuation、correction continuation。
- 在执行 scorer 前封存 expected episode membership 和 boundary reason。

### B2 — Typed memory objects（MUST）

- 新增 episode 和 bundle Pydantic contracts。
- 验证 digest、排序、全量 Raw coverage、timezone-aware watermark、sub-artifact source closure。

### B3 — Query-independent builder（MUST）

- 一次构造 episodes、MF-03 semantic sidecar 和 MF-04 state/change sidecar。
- 状态/事件形成只消费 user Evidence；episode 保留 user/assistant 对话上下文。
- 不调 Provider、Reader、retrieval 或 database。

### B4 — Matched formation effect（MUST）

- 直接评估 episode boundary/pairwise metrics、Raw coverage、source-role isolation 和 deterministic replay。
- 重放现有 MF-03/MF-04 tests，不重新调整已封存 14-case 规则。

### B5 — Integration readiness（NICE-TO-HAVE）

- 只生成 application service 和 sidecar receipt。
- 不进入 migration/background worker/product flag，直到更大 validation 证明泛化。

## 5. 建议执行顺序（未授权执行）

```text
S0 Goal + label seal
→ S1 domain contracts
→ S2 episode/bundle builder
→ S3 matched effect + repair loop
→ S4 regression/static/replay + terminal
```

中间 protocol/implementation 失败优先修复通用根因，不终止 Program。只有 Raw Evidence 丢失、scope 泄漏、未授权 Canonical mutation 或数据损坏立即停止当次 effect。

## 6. PASS 与负结果

`PASS_MD01_MEMORY_FORMATION_CORE` 需要：

```text
RawSpanCoverage = 1.0
EpisodeBoundaryPrecision >= 0.90
EpisodeBoundaryRecall >= 0.90
EpisodePairwiseF1 >= 0.90
UserSemanticSourcePrecision = 1.0
ArtifactLineageClosure = 1.0
DeterministicReplay = 1.0
Provider/Reader/Retrieval/DB calls = 0
Canonical mutations = 0
existing MF-03/MF-04 regression = 0
```

允许的负结果：

```text
PARKED_EPISODE_BOUNDARY_NO_GENERALIZED_GAIN
PARTIAL_BUNDLE_PASS_EPISODE_UNRESOLVED
FAIL_RAW_OR_AUTHORITY_BOUNDARY
```

## 7. 后续获授权时的预期交付

- domain contracts 与 query-independent builder
- 封存 validation fixture
- unit/effect tests
- `var/md01/.../receipt.json`
- 更新 Program A / MILA-ML-MASTER / 执行报告
